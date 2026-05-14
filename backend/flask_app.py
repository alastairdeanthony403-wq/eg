"""
AI Trading Engine — Flask backend
Routes are mounted under /api.

Data sources
────────────
Crypto          : Binance REST API (Coinbase fallback)
Forex / Stocks
/ Commodities   : Polygon.io REST API (/v2/aggs) — single unified key: POLYGON_API_KEY

Key fixes in this version
─────────────────────────
[A] Replaced TwelveData with Polygon.io for all non-crypto data.
[B] Backtester for non-crypto uses Polygon daily bars (1825-day history, 30-min cache).
[C] Backtester prepends 80 warmup bars so strategies can initialise on short windows.
[D] run_simple_ma_strategy — fixed PnL scaling (percentage return, not raw price diff).
[E] run_unified_bot_strategy — London no-acceptance filter, 3-candle FVG, FVG entry,
    sweep depth gate, NY window extended to 17:00 GMT.
[F] Price display: returns both `price` and `price_display` for the frontend.
[G] /api/backtest: descriptive error messages at every failure point.
[H] Symbols endpoint returns market membership for frontend grouping.
"""

from flask import Flask, jsonify, request, g
from flask_cors import CORS
import pandas as pd
import requests
import uuid
import os
import time
import random
import jwt as pyjwt
import bcrypt
import json
from datetime import datetime, timedelta, timezone
from functools import wraps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)


@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        response = app.response_class()
        response.status_code = 200
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)


# ─────────────────────────────────────────────
# SYMBOLS & MARKETS
# ─────────────────────────────────────────────
MARKETS = {
    "crypto":      ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
    "forex":       ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
    "stocks":      ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "SPY"],
    "commodities": ["XAUUSD", "XAGUSD", "USOIL", "UKOIL"],
}

ALL_SYMBOLS = (
    MARKETS["crypto"]
    + MARKETS["forex"]
    + MARKETS["stocks"]
    + MARKETS["commodities"]
)

# Polygon.io ticker map — translates internal symbols to Polygon API tickers.
# Forex + metals use the "C:" prefix (Polygon Forex/FX endpoint).
# Oil uses liquid ETF proxies available on all Polygon plans (USO = WTI, BNO = Brent).
# Stocks pass through directly.
POLYGON_SYMBOL_MAP = {
    # Forex
    "EURUSD": "C:EURUSD", "GBPUSD": "C:GBPUSD", "USDJPY": "C:USDJPY",
    "AUDUSD": "C:AUDUSD", "USDCAD": "C:USDCAD",
    # Metals (available via Polygon FX endpoint with C: prefix)
    "XAUUSD": "C:XAUUSD",   # Gold spot
    "XAGUSD": "C:XAGUSD",   # Silver spot
    # Oil — ETF proxies available on all Polygon plans
    "USOIL":  "USO",         # United States Oil Fund (WTI)
    "UKOIL":  "BNO",         # iPath S&P GSCI Crude Oil ETF (Brent)
    # Stocks
    "AAPL": "AAPL", "TSLA": "TSLA", "NVDA": "NVDA",
    "MSFT": "MSFT", "AMZN": "AMZN", "SPY":  "SPY",
}

# Interval → (multiplier, timespan) for Polygon /v2/aggs
POLYGON_INTERVAL_MAP = {
    "1m":  (1,  "minute"),
    "5m":  (5,  "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "1h":  (1,  "hour"),
    "4h":  (4,  "hour"),
    "1d":  (1,  "day"),
}

# Approximate ms per bar — used to compute the from/to window
_POLYGON_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}

# [A] Signals always use 5m — much better TwelveData hit rate on the free tier
SIGNALS_INTERVAL = "5m"

# Earliest safe date for each market (for random window selection)
MARKET_EARLIEST = {
    "crypto":      datetime(2020, 1, 1, tzinfo=timezone.utc),
    "forex":       datetime(2018, 1, 1, tzinfo=timezone.utc),
    "stocks":      datetime(2018, 1, 1, tzinfo=timezone.utc),
    "commodities": datetime(2018, 1, 1, tzinfo=timezone.utc),
}

DEFAULT_CONFIG = {
    "symbols":                  ALL_SYMBOLS,
    "risk_reward":              2,
    "risk_percent":             1,
    "min_confidence":           70,   # loosened from 75
    "starting_balance":         10000,
    "max_trades_per_day":       5,
    "max_daily_loss_percent":   3,
    "max_consecutive_losses":   2,
    "avoid_quiet_market":       True,
    "avoid_sideways_market":    True,
    "min_volume_multiplier":    0.8,
    "min_smc_score":            6,    # loosened from 7
    "blocked_crypto_hours_utc": [0, 1, 2, 3],
    "trading_mode":             "local_paper",
}

JWT_SECRET     = os.environ.get("JWT_SECRET", "ai-trading-engine-secret-change-me")
JWT_ALGO       = "HS256"
JWT_EXPIRY_DAYS = 7

MARKET_DATA_TTL_SECONDS    = 30
SUMMARY_TTL_SECONDS        = 90   # cache signals for 90 s — gives backtest room to breathe
NON_CRYPTO_CANDLE_TTL      = 600  # cache non-crypto candles for 10 min

_raw_candle_cache    = {}
_non_crypto_cache    = {}   # separate long-lived cache for Polygon.io responses
_summary_cache       = {}

# ── Polygon.io rate-limiter ──────────────────────────────────────────────────
# Free plan: 5 calls/minute.  Starter+: unlimited.
# We enforce ≥12 s between requests to stay safely inside free-plan limits.
# On paid plans, set POLYGON_RATE_LIMIT_SECS=0 in env to disable the delay.
_polygon_lock          = __import__("threading").Lock()
_polygon_last_call_ts  = 0.0
POLYGON_RATE_LIMIT_SECS = float(os.environ.get("POLYGON_RATE_LIMIT_SECS", "12"))


def _polygon_get(url, params, timeout=25):
    """GET a Polygon.io URL, rate-limited to POLYGON_RATE_LIMIT_SECS between calls."""
    global _polygon_last_call_ts
    if POLYGON_RATE_LIMIT_SECS > 0:
        with _polygon_lock:
            elapsed = time.time() - _polygon_last_call_ts
            if elapsed < POLYGON_RATE_LIMIT_SECS:
                time.sleep(POLYGON_RATE_LIMIT_SECS - elapsed)
            _polygon_last_call_ts = time.time()
    return requests.get(url, params=params, timeout=timeout)

BINANCE_BASE_URLS = [
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://data-api.binance.vision",
]

COINBASE_PRODUCT_MAP = {
    "BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD",
    "BNBUSDT": "BNB-USD", "SOLUSDT": "SOL-USD",
}
COINBASE_GRAN_MAP = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
import psycopg2


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT,
        name TEXT, created_at TEXT, settings TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id TEXT, user_id TEXT, symbol TEXT, type TEXT, entry REAL, sl REAL,
        tp REAL, size REAL, exit REAL, pnl REAL, status TEXT, time TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id TEXT, user_id TEXT, message TEXT, time TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS journal (
        id TEXT PRIMARY KEY, user_id TEXT, symbol TEXT, side TEXT,
        entry REAL, exit REAL, pnl REAL, mood TEXT, tags TEXT,
        notes TEXT, screenshot_url TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS backtest_runs (
        id TEXT PRIMARY KEY, user_id TEXT, symbol TEXT, interval TEXT,
        strategy TEXT, start_date TEXT, end_date TEXT, total_trades INTEGER,
        net_pnl REAL, profit_factor REAL, max_drawdown REAL,
        max_drawdown_percent REAL, win_rate REAL, summary_json TEXT,
        trades_json TEXT, created_at TEXT)""")
    conn.commit()
    conn.close()


init_db()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
def make_token(user_id, email):
    payload = {
        "sub": user_id, "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 200
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth.split(" ", 1)[1]
        try:
            payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
            g.user_id    = payload["sub"]
            g.user_email = payload.get("email")
        except Exception as e:
            return jsonify({"error": f"Invalid token: {e}"}), 401
        return f(*args, **kwargs)
    return wrapper


def get_user_config():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT settings FROM users WHERE id=%s", (g.user_id,))
    row = c.fetchone()
    conn.close()
    cfg = dict(DEFAULT_CONFIG)
    if row and row[0]:
        try:
            cfg.update(json.loads(row[0]))
        except Exception:
            pass
    return cfg


@app.route("/api/auth/register", methods=["POST", "OPTIONS"])
def register():
    data     = request.get_json(force=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name     = (data.get("name") or "").strip() or email.split("@")[0]
    if not email or len(password) < 6:
        return jsonify({"error": "Email and password (min 6 chars) required"}), 400
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email=%s", (email,))
    if c.fetchone():
        conn.close()
        return jsonify({"error": "Email already registered"}), 400
    user_id = str(uuid.uuid4())
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    c.execute("INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)",
              (user_id, email, pw_hash, name, now_str(), json.dumps(DEFAULT_CONFIG)))
    conn.commit(); conn.close()
    return jsonify({"token": make_token(user_id, email),
                    "user": {"id": user_id, "email": email, "name": name}})


@app.route("/api/auth/login", methods=["POST", "OPTIONS"])
def login():
    data     = request.get_json(force=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT id, password_hash, name FROM users WHERE email=%s", (email,))
    row = c.fetchone(); conn.close()
    if not row or not bcrypt.checkpw(password.encode(), row[1].encode()):
        return jsonify({"error": "Invalid credentials"}), 401
    return jsonify({"token": make_token(row[0], email),
                    "user": {"id": row[0], "email": email, "name": row[2]}})


@app.route("/api/auth/me", methods=["GET"])
@auth_required
def me():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT id, email, name, created_at FROM users WHERE id=%s", (g.user_id,))
    row = c.fetchone(); conn.close()
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"id": row[0], "email": row[1], "name": row[2], "created_at": row[3]})


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _request_json(url, params=None, timeout=12):
    return requests.get(url, params=params, timeout=timeout)


def _cache_get(cache, key, ttl):
    e = cache.get(key)
    if not e:
        return None
    if time.time() - e["timestamp"] > ttl:
        cache.pop(key, None)
        return None
    return e["value"]


def _cache_set(cache, key, value):
    cache[key] = {"timestamp": time.time(), "value": value}
    return value


def add_alert(user_id, message):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO alerts VALUES (%s,%s,%s,%s)",
              (str(uuid.uuid4()), user_id, message, now_str()))
    conn.commit(); conn.close()


def detect_market(symbol):
    if symbol.endswith("USDT"):
        return "crypto"
    if symbol in MARKETS["forex"]:
        return "forex"
    if symbol in MARKETS["commodities"]:
        return "commodities"
    return "stocks"


def format_price(price, symbol):
    """[F] Return a display-friendly string for any market's price."""
    if price is None:
        return "—"
    market = detect_market(symbol)
    if market == "crypto":
        if price >= 1000:
            return f"{price:,.2f}"
        if price >= 1:
            return f"{price:.4f}"
        return f"{price:.6f}"
    if market == "forex":
        return f"{price:.5f}" if "JPY" not in symbol else f"{price:.3f}"
    if market == "commodities":
        return f"{price:.3f}" if price < 100 else f"{price:,.2f}"
    # stocks
    return f"{price:.2f}"


# ─────────────────────────────────────────────
# BINANCE (CRYPTO)
# ─────────────────────────────────────────────
def _fetch_binance_klines(symbol, interval="1m", limit=100):
    last_error = None
    for base_url in BINANCE_BASE_URLS:
        try:
            r = _request_json(f"{base_url}/api/v3/klines",
                              params={"symbol": symbol, "interval": interval, "limit": limit},
                              timeout=8)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) >= 2:
                    return data
            last_error = f"HTTP {r.status_code} from {base_url}"
        except requests.exceptions.RequestException as e:
            last_error = f"{base_url}: {e}"
    raise RuntimeError(f"All Binance endpoints failed. Last error: {last_error}")


def _coinbase_fetch_candles(product_id, granularity, total_needed):
    all_rows, end_time = [], datetime.now(timezone.utc)
    while len(all_rows) < total_needed:
        batch_size = min(300, total_needed - len(all_rows))
        start_time = end_time - timedelta(seconds=granularity * batch_size)
        r = _request_json(
            f"https://api.exchange.coinbase.com/products/{product_id}/candles",
            params={"granularity": granularity,
                    "start": start_time.isoformat(),
                    "end":   end_time.isoformat()},
            timeout=12)
        if r.status_code != 200:
            raise RuntimeError(f"Coinbase HTTP {r.status_code}")
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            break
        all_rows.extend(rows)
        earliest_ts = min(x[0] for x in rows)
        end_time = datetime.fromtimestamp(earliest_ts, tz=timezone.utc) - timedelta(seconds=granularity)
        if len(rows) < batch_size:
            break
    unique  = {int(r[0]): r for r in all_rows if isinstance(r, list) and len(r) >= 6}
    ordered = [unique[k] for k in sorted(unique.keys())]
    if not ordered:
        raise RuntimeError("Coinbase returned no usable candle data")
    return ordered[-total_needed:]


def _aggregate_coinbase_1h_to_4h(rows, limit):
    rows = sorted(rows, key=lambda x: x[0])
    grouped, bucket = [], []
    for row in rows:
        bucket.append(row)
        if len(bucket) == 4:
            grouped.append([
                int(bucket[0][0]),
                min(float(r[1]) for r in bucket),
                max(float(r[2]) for r in bucket),
                float(bucket[0][3]),
                float(bucket[-1][4]),
                sum(float(r[5]) for r in bucket),
            ])
            bucket = []
    return grouped[-limit:]


def _fetch_coinbase_raw(symbol="BTCUSDT", interval="5m", limit=200):
    product_id  = COINBASE_PRODUCT_MAP.get(symbol)
    granularity = COINBASE_GRAN_MAP.get(interval)
    if not product_id or not granularity:
        raise RuntimeError(f"No Coinbase mapping for {symbol} {interval}")
    if interval == "4h":
        raw_1h = _coinbase_fetch_candles(product_id, 3600, max(limit * 4, 4))
        rows   = _aggregate_coinbase_1h_to_4h(raw_1h, limit)
    else:
        rows = _coinbase_fetch_candles(product_id, granularity, limit)
    # normalise to Binance kline shape [time_ms, open, high, low, close, volume]
    return [[int(r[0]) * 1000, str(r[3]), str(r[2]), str(r[1]),
             str(r[4]), str(r[5])] for r in rows]


def fetch_binance_raw(symbol="BTCUSDT", interval="5m", limit=500):
    """Fetch recent crypto candles via Binance → Coinbase fallback."""
    if not symbol or not symbol.endswith("USDT"):
        raise ValueError(f"fetch_binance_raw: not a USDT symbol: {symbol}")
    cache_key = (symbol, interval, int(limit))
    cached = _cache_get(_raw_candle_cache, cache_key, MARKET_DATA_TTL_SECONDS)
    if cached is not None:
        return cached
    binance_err = None
    try:
        return _cache_set(_raw_candle_cache, cache_key,
                          _fetch_binance_klines(symbol, interval, limit))
    except Exception as e:
        binance_err = str(e)
    try:
        return _cache_set(_raw_candle_cache, cache_key,
                          _fetch_coinbase_raw(symbol, interval, limit))
    except Exception as fb:
        raise RuntimeError(
            f"Crypto candle fetch failed.\n"
            f"  Binance error : {binance_err}\n"
            f"  Coinbase error: {fb}"
        )


def fetch_binance_range(symbol, interval, start_ms, end_ms, limit=1000):
    """Fetch a specific historical date range from Binance (crypto only)."""
    url    = "https://data-api.binance.vision/api/v3/klines"
    params = {
        "symbol":    symbol,
        "interval":  interval,
        "startTime": int(start_ms),
        "endTime":   int(end_ms),
        "limit":     int(limit),
    }
    r = requests.get(url, params=params, timeout=12)
    if r.status_code != 200:
        raise RuntimeError(
            f"Binance range fetch failed: HTTP {r.status_code} — {r.text[:200]}"
        )
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Binance returned unexpected data: {str(data)[:200]}")
    return data


# ─────────────────────────────────────────────
# POLYGON.IO (FOREX / STOCKS / COMMODITIES)
# ─────────────────────────────────────────────

def fetch_polygon_candles(symbol, interval, limit=200):
    """
    Fetch OHLCV candles from Polygon.io for any non-crypto symbol.

    Endpoint: /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}

    Symbol routing:
      Forex / metals  →  C:EURUSD, C:XAUUSD, etc.
      Stocks          →  AAPL, TSLA, SPY, etc.
      Oil (USO/BNO)   →  stock ETF tickers available on all plans

    Returns list of [ts_ms, open, high, low, close, volume] as strings,
    oldest-first, matching the same format as fetch_binance_raw().
    """
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "POLYGON_API_KEY is not set. "
            "Add it to your Render environment variables."
        )

    interval_cfg = POLYGON_INTERVAL_MAP.get(interval)
    if not interval_cfg:
        # Auto-upgrade 1m → 5m for non-crypto to reduce API load
        if interval == "1m":
            interval_cfg = POLYGON_INTERVAL_MAP["5m"]
        else:
            raise RuntimeError(
                f"Polygon does not support interval '{interval}'. "
                f"Supported: {list(POLYGON_INTERVAL_MAP.keys())}"
            )
    multiplier, timespan = interval_cfg

    ticker = POLYGON_SYMBOL_MAP.get(symbol, symbol)

    # Cache check
    nc_key = (symbol, interval, limit)
    cached = _cache_get(_non_crypto_cache, nc_key, NON_CRYPTO_CANDLE_TTL)
    if cached is not None:
        return cached

    # Compute from/to window — request enough history to fill `limit` bars,
    # with a 3× buffer to account for weekends and market closures.
    bar_ms   = _POLYGON_INTERVAL_MS.get(interval, 300_000)
    now_ms   = int(time.time() * 1000)
    from_ms  = now_ms - int(bar_ms * limit * 3)
    from_dt  = datetime.utcfromtimestamp(from_ms / 1000).strftime("%Y-%m-%d")
    to_dt    = datetime.utcfromtimestamp(now_ms   / 1000).strftime("%Y-%m-%d")

    url    = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}"
              f"/range/{multiplier}/{timespan}/{from_dt}/{to_dt}")
    params = {
        "adjusted": "true",
        "sort":     "asc",
        "limit":    min(limit * 3, 50000),   # Polygon max per page
        "apiKey":   api_key,
    }

    try:
        r    = _polygon_get(url, params, timeout=25)
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Polygon network error for {symbol} ({ticker}): {e}")

    status = data.get("status", "")
    if status in ("ERROR", "NOT_AUTHORIZED", "DELAYED"):
        raise RuntimeError(
            f"Polygon error for {symbol} ({ticker}): "
            f"{data.get('error', data.get('message', status))}"
        )

    results = data.get("results") or []
    if not results:
        raise RuntimeError(
            f"Polygon returned 0 bars for {symbol} ({ticker}). "
            f"Check that the symbol is supported on your plan and markets are not closed."
        )

    candles = []
    for bar in results:
        try:
            ts  = int(bar["t"])
            o   = float(bar["o"])
            h   = float(bar["h"])
            lo_ = float(bar["l"])
            c   = float(bar["c"])
            vol = float(bar.get("v") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if c <= 0 or h <= 0 or lo_ <= 0:
            continue
        candles.append([ts, str(o), str(h), str(lo_), str(c), str(vol)])

    # Keep only the most recent `limit` bars
    candles = candles[-limit:]

    if not candles:
        raise RuntimeError(
            f"Polygon returned bars for {symbol} but all had invalid prices."
        )

    _cache_set(_non_crypto_cache, nc_key, candles)
    return candles


# ─────────────────────────────────────────────
# NON-CRYPTO BACKTEST DATA (Polygon daily bars)
# ─────────────────────────────────────────────
# Polygon free plan has no per-minute credit limit (unlike TwelveData),
# so we can request daily bars freely. We still cache for 30 min to avoid
# hammering the API on repeated backtest runs.
# ─────────────────────────────────────────────

_backtest_daily_cache = {}
BACKTEST_DAILY_TTL    = 1800  # 30 minutes


def fetch_non_crypto_backtest_candles(symbol, period_days, random_window=True):
    """
    Fetch daily candles for non-crypto backtest via Polygon.io.
    Uses 1d interval → only 1 API credit per call.
    Cached for 30 min so repeated runs cost nothing.
    Returns (candles, "1d", start_date, end_date).
    """
    # Check cache first — if we already have this symbol's daily data, slice it
    cached = _cache_get(_backtest_daily_cache, symbol, BACKTEST_DAILY_TTL)
    if cached is None:
        # Fetch up to 5 years of daily data in one credit
        try:
            candles = fetch_polygon_candles(symbol, "1d", limit=1825)
        except RuntimeError as e:
            raise RuntimeError(
                f"Could not load daily data for {symbol} from Polygon.io.\n{e}\n\n"
                f"Check that POLYGON_API_KEY is set and the symbol is supported on your plan."
            )
        if not candles or len(candles) < 30:
            raise RuntimeError(
                f"Polygon returned only {len(candles) if candles else 0} daily "
                f"candles for {symbol}. The symbol may not be supported on your plan."
            )
        _cache_set(_backtest_daily_cache, symbol, candles)
        cached = candles

    all_candles = cached

    # How many extra bars to prepend so every strategy has enough warmup history.
    # unified_bot needs WARMUP=55, vwap_ema needs ADR_PERIOD=10 full days,
    # simple_ma needs 30. Use 80 to cover all cases with headroom.
    WARMUP_BARS = 80

    # Determine the "trade window" (what the user asked for)
    if random_window and len(all_candles) > period_days + WARMUP_BARS + 5:
        max_start = len(all_candles) - period_days - 1
        trade_start = random.randint(WARMUP_BARS, max_start)
    else:
        trade_start = max(WARMUP_BARS, len(all_candles) - period_days)

    trade_end = min(trade_start + period_days, len(all_candles))

    # Prepend warmup bars (strategy uses them to warm up indicators but doesn't
    # "trade" them — the strategies' own WARMUP guards handle that internally)
    fetch_start = max(0, trade_start - WARMUP_BARS)
    window      = all_candles[fetch_start:trade_end]

    if len(window) < 5:
        raise RuntimeError(
            f"Not enough daily candles for {symbol} "
            f"(got {len(window)}). The symbol may not be available on your Polygon plan."
        )

    # Extract date range for display — show only the user's requested window
    def ms_to_date(ts):
        return datetime.utcfromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")

    start_date = ms_to_date(all_candles[trade_start][0])
    end_date   = ms_to_date(all_candles[trade_end - 1][0])

    return window, "1d", start_date, end_date


# ─────────────────────────────────────────────
# UNIVERSAL CANDLE FETCHERS
# ─────────────────────────────────────────────

def fetch_candles_for_symbol(symbol, interval="5m", limit=200):
    """Route to the right data source by market type."""
    market = detect_market(symbol)
    if market == "crypto":
        return fetch_binance_raw(symbol, interval, limit)
    candles = fetch_polygon_candles(symbol, interval, limit)
    if not candles:
        raise RuntimeError(f"No Polygon candles returned for {symbol}")
    return candles


def raw_candles_to_df(raw):
    if not raw or len(raw) < 2:
        return None
    first = raw[0]
    if len(first) >= 12:
        df = pd.DataFrame(raw, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ])
    elif len(first) >= 6:
        df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    else:
        return None
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    df.dropna(subset=["time", "open", "high", "low", "close"], inplace=True)
    return df.reset_index(drop=True) if len(df) >= 2 else None


def fetch_df_for_symbol(symbol, interval="5m", limit=200):
    try:
        raw = fetch_candles_for_symbol(symbol, interval, limit)
        return raw_candles_to_df(raw)
    except Exception as e:
        print(f"[fetch_df] {symbol} {interval}: {e}")
        return None


# ─────────────────────────────────────────────
# SIGNAL & BOT LOGIC
# ─────────────────────────────────────────────

def generate_signal(df):
    if df is None or len(df) < 2:
        return "HOLD"
    c = df["close"]
    return "BUY" if c.iloc[-1] > c.iloc[-2] else \
           "SELL" if c.iloc[-1] < c.iloc[-2] else "HOLD"


def get_structure(df):
    if df is None or len(df) < 20:
        return "Range / Mixed"
    closes = df["close"]
    sma20  = closes.tail(20).mean()
    c0, c1, c2 = closes.iloc[-1], closes.iloc[-2], closes.iloc[-3]
    if c0 > sma20 and c0 > c1 > c2:
        return "Bullish Structure"
    if c0 < sma20 and c0 < c1 < c2:
        return "Bearish Structure"
    return "Range / Mixed"


def get_market_regime(df):
    if df is None or len(df) < 20:
        return "Unknown"
    rh  = df["high"].tail(20).max()
    rl  = df["low"].tail(20).min()
    avg = df["close"].tail(20).mean()
    if avg == 0:
        return "Unknown"
    rng = ((rh - rl) / avg) * 100
    return "Trending" if rng > 2.5 else "Active" if rng > 1.0 else "Range / Quiet"


def estimate_confidence(df, signal):
    if df is None or len(df) < 20:
        return 50
    closes = df["close"]
    latest, prev = closes.iloc[-1], closes.iloc[-2]
    sma20  = closes.tail(20).mean()
    sma5   = closes.tail(5).mean()
    conf   = 50
    if signal == "BUY":
        if latest > sma20: conf += 15
        if latest > prev:  conf += 10
        if latest > sma5:  conf += 10
    elif signal == "SELL":
        if latest < sma20: conf += 15
        if latest < prev:  conf += 10
        if latest < sma5:  conf += 10
    return max(35, min(95, conf))


def get_higher_timeframe(interval):
    return "1h" if interval in ["1m", "5m", "15m"] else "4h"


def get_trend_bias(df):
    if df is None or len(df) < 50:
        return "Neutral"
    ef = df["close"].ewm(span=20, adjust=False).mean()
    es = df["close"].ewm(span=50, adjust=False).mean()
    if ef.iloc[-1] > es.iloc[-1]:
        return "Bullish"
    if ef.iloc[-1] < es.iloc[-1]:
        return "Bearish"
    return "Neutral"


def detect_liquidity_sweep(df):
    if df is None or len(df) < 25:
        return None
    cur = df.iloc[-1]
    ph  = df["high"].iloc[-21:-1].max()
    pl  = df["low"].iloc[-21:-1].min()
    if cur["high"] > ph and cur["close"] < ph:
        return "SELL_SWEEP"
    if cur["low"] < pl and cur["close"] > pl:
        return "BUY_SWEEP"
    return None


def detect_break_of_structure(df):
    if df is None or len(df) < 30:
        return None
    rh    = df["high"].iloc[-15:-1].max()
    rl    = df["low"].iloc[-15:-1].min()
    close = df.iloc[-1]["close"]
    if close > rh:
        return "BULLISH_BOS"
    if close < rl:
        return "BEARISH_BOS"
    return None


def price_in_discount_zone(df):
    if df is None or len(df) < 30:
        return False
    rh, rl = df["high"].tail(30).max(), df["low"].tail(30).min()
    return df.iloc[-1]["close"] <= (rh + rl) / 2


def price_in_premium_zone(df):
    if df is None or len(df) < 30:
        return False
    rh, rl = df["high"].tail(30).max(), df["low"].tail(30).min()
    return df.iloc[-1]["close"] >= (rh + rl) / 2


def detect_fvg_retrace(df, direction):
    if df is None or len(df) < 10:
        return False
    c = df.tail(8).reset_index(drop=True)
    cur = c.iloc[-1]["close"]
    for i in range(2, len(c)):
        c1, c3 = c.iloc[i - 2], c.iloc[i]
        if direction == "BUY" and c3["low"] > c1["high"]:
            if c1["high"] <= cur <= c3["low"]:
                return True
        if direction == "SELL" and c3["high"] < c1["low"]:
            if c3["high"] <= cur <= c1["low"]:
                return True
    return False


def session_allowed(cfg):
    return datetime.utcnow().hour not in cfg["blocked_crypto_hours_utc"]


def evaluate_bot_window(df, strategy="bot", symbol="BTCUSDT", interval="5m",
                         higher_df=None, cfg=None):
    cfg = cfg or DEFAULT_CONFIG
    if df is None or len(df) < 50:
        return {
            "signal": "HOLD", "bias": "Neutral", "structure": "Range / Mixed",
            "regime": "Unknown", "confidence": 50,
            "trade_idea": "Not enough data",
            "higher_tf": get_higher_timeframe(interval), "higher_tf_bias": "Neutral",
            "liquidity_sweep": None, "bos": None, "smc_score": 0,
            "reasons": ["Insufficient candle history — need ≥50 bars"],
        }

    raw_signal  = generate_signal(df)
    structure   = get_structure(df)
    regime      = get_market_regime(df)
    confidence  = estimate_confidence(df, raw_signal)
    higher_tf   = get_higher_timeframe(interval)
    if higher_df is None:
        higher_df = fetch_df_for_symbol(symbol, higher_tf, 100)
    higher_tf_bias = get_trend_bias(higher_df)
    sweep = detect_liquidity_sweep(df)
    bos   = detect_break_of_structure(df)

    final, idea, smc_score, reasons = "HOLD", "Wait for clearer confirmation", 0, []

    if strategy == "basic":
        final = raw_signal
        idea  = {"BUY": "Pullback long / continuation",
                 "SELL": "Reject highs / continuation short"}.get(final, idea)
        reasons.append(f"Basic momentum signal = {raw_signal}")

    elif strategy == "ema_rsi":
        ef = df["close"].ewm(span=9,  adjust=False).mean()
        es = df["close"].ewm(span=21, adjust=False).mean()
        if ef.iloc[-1] > es.iloc[-1] and confidence >= 65:
            final, idea = "BUY",  "EMA momentum long"
            confidence  = max(confidence, 70)
            reasons.append("EMA9 > EMA21 and confidence ≥ 65")
        elif ef.iloc[-1] < es.iloc[-1] and confidence >= 65:
            final, idea = "SELL", "EMA momentum short"
            confidence  = max(confidence, 70)
            reasons.append("EMA9 < EMA21 and confidence ≥ 65")

    else:   # smart_money / bot
        min_score = cfg["min_smc_score"]
        buy_checks = [
            ("HTF bias bullish",              higher_tf_bias == "Bullish"),
            ("Buy-side liquidity sweep",       sweep == "BUY_SWEEP"),
            ("Bullish break of structure",     bos == "BULLISH_BOS"),
            ("Price in discount zone",         price_in_discount_zone(df)),
            ("FVG retracement long",           detect_fvg_retrace(df, "BUY")),
            (f"Confidence ≥ {cfg['min_confidence']}%",
                                               confidence >= cfg["min_confidence"]),
            ("Trending / active regime",       regime not in ["Range / Quiet", "Unknown"]),
            ("Clear structure (not range)",    structure != "Range / Mixed"),
            ("Active session window",          session_allowed(cfg)),
        ]
        sell_checks = [
            ("HTF bias bearish",              higher_tf_bias == "Bearish"),
            ("Sell-side liquidity sweep",      sweep == "SELL_SWEEP"),
            ("Bearish break of structure",     bos == "BEARISH_BOS"),
            ("Price in premium zone",          price_in_premium_zone(df)),
            ("FVG retracement short",          detect_fvg_retrace(df, "SELL")),
            (f"Confidence ≥ {cfg['min_confidence']}%",
                                               confidence >= cfg["min_confidence"]),
            ("Trending / active regime",       regime not in ["Range / Quiet", "Unknown"]),
            ("Clear structure (not range)",    structure != "Range / Mixed"),
            ("Active session window",          session_allowed(cfg)),
        ]
        bs = sum(1 for _, ok in buy_checks  if ok)
        ss = sum(1 for _, ok in sell_checks if ok)
        if bs >= min_score:
            final, idea = "BUY",  "HTF bullish + sweep + BOS + retracement entry"
            confidence = max(confidence, 80); smc_score = bs
            reasons = ([f"✓ {n}" for n, ok in buy_checks  if ok] +
                       [f"✗ {n}" for n, ok in buy_checks  if not ok])
        elif ss >= min_score:
            final, idea = "SELL", "HTF bearish + sweep + BOS + retracement entry"
            confidence = max(confidence, 80); smc_score = ss
            reasons = ([f"✓ {n}" for n, ok in sell_checks if ok] +
                       [f"✗ {n}" for n, ok in sell_checks if not ok])
        else:
            smc_score = max(bs, ss)
            best = buy_checks if bs >= ss else sell_checks
            reasons = ([f"✓ {n}" for n, ok in best if ok] +
                       [f"✗ {n}" for n, ok in best if not ok])

    bias = {"BUY": "Bullish", "SELL": "Bearish"}.get(final, higher_tf_bias)
    return {
        "signal": final, "bias": bias, "structure": structure,
        "regime": regime, "confidence": confidence, "trade_idea": idea,
        "higher_tf": higher_tf, "higher_tf_bias": higher_tf_bias,
        "liquidity_sweep": sweep, "bos": bos,
        "smc_score": smc_score, "reasons": reasons,
    }


def calculate_trade_levels(df, signal, rr=2):
    lc = float(df.iloc[-1]["close"])
    lh = float(df.iloc[-1]["high"])
    ll = float(df.iloc[-1]["low"])
    if signal == "BUY":
        sl = ll * 0.995
        tp = lc + (lc - sl) * rr
    elif signal == "SELL":
        sl = lh * 1.005
        tp = lc - (sl - lc) * rr
    else:
        sl, tp = lc, lc
    return {"entry": round(lc, 6), "sl": round(sl, 6), "tp": round(tp, 6)}


def get_symbol_summary(symbol, strategy="bot", interval=SIGNALS_INTERVAL, cfg=None):
    """[A][E][F] Fetch latest prices and signals for a symbol."""
    cfg       = cfg or DEFAULT_CONFIG
    cache_key = (symbol, strategy, interval)
    cached    = _cache_get(_summary_cache, cache_key, SUMMARY_TTL_SECONDS)
    if cached is not None:
        return cached

    fetch_iv = SIGNALS_INTERVAL
    df = fetch_df_for_symbol(symbol, fetch_iv, 200)
    if df is None:
        return None

    # Only fetch higher TF for crypto — Polygon is cheaper but still rate-limited
    # Non-crypto higher TF would double the credits used per symbol
    market = detect_market(symbol)
    if market == "crypto":
        higher_df = fetch_df_for_symbol(symbol, get_higher_timeframe(fetch_iv), 100)
    else:
        higher_df = None   # saves 14 credits per signal refresh

    ev     = evaluate_bot_window(df, strategy, symbol, fetch_iv, higher_df, cfg)
    prev   = float(df.iloc[-2]["close"]) if len(df) > 1 else float(df.iloc[-1]["close"])
    last   = float(df.iloc[-1]["close"])
    chg    = ((last - prev) / prev * 100) if prev else 0
    levels = calculate_trade_levels(df, ev["signal"], cfg.get("risk_reward", 2))

    return _cache_set(_summary_cache, cache_key, {
        "symbol":          symbol,
        "market":          market,
        "price":           round(last, 6),
        "price_display":   format_price(last, symbol),
        "live_price":      round(last, 6),
        "change_pct":      round(chg, 4),
        "signal":          ev["signal"],
        "bias":            ev["bias"],
        "structure":       ev["structure"],
        "regime":          ev["regime"],
        "confidence":      ev["confidence"],
        "trade_idea":      ev["trade_idea"],
        "higher_tf":       ev["higher_tf"],
        "higher_tf_bias":  ev["higher_tf_bias"],
        "liquidity_sweep": ev["liquidity_sweep"],
        "bos":             ev["bos"],
        "smc_score":       ev["smc_score"],
        "reasons":         ev["reasons"],
        "entry":           levels["entry"],
        "sl":              levels["sl"],
        "tp":              levels["tp"],
    })


# ─────────────────────────────────────────────
# BACKTESTER HELPERS
# ─────────────────────────────────────────────

def interval_to_pandas_rule(i):
    return {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}.get(i)


def get_session_name(dt):
    h = dt.hour
    if 7  <= h < 12: return "London"
    if 12 <= h < 21: return "New York"
    return "Asia"


def _ts_to_str(ts):
    """Convert a millisecond or second timestamp to a readable string."""
    try:
        t = int(ts)
        if t > 1e12:          # milliseconds
            return datetime.utcfromtimestamp(t / 1000).strftime("%Y-%m-%d %H:%M:%S")
        return datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


# ─────────────────────────────────────────────
# SHARED INDICATOR HELPERS (used by new strategies)
# ─────────────────────────────────────────────

def _adr_series(daily_highs, daily_lows, period=10):
    """
    10-period Average Daily Range.
    Inputs are parallel lists of daily high/low values (one per trading day).
    Returns a list of the same length; first `period-1` values are None.
    """
    if len(daily_highs) < period:
        return [None] * len(daily_highs)
    ranges = [daily_highs[j] - daily_lows[j] for j in range(len(daily_highs))]
    result = [None] * (period - 1)
    for i in range(period - 1, len(ranges)):
        result.append(sum(ranges[i - period + 1: i + 1]) / period)
    return result


def _vwap_series(candles):
    """
    Intraday VWAP that resets at the start of each calendar day.
    Candles: standard [ts_ms, open, high, low, close, volume] list.
    Returns list of VWAP values (same length).
    No lookahead — uses only completed bars.
    """
    from datetime import datetime, timezone as _tz

    def _date(ts):
        t = int(ts)
        if t > 1e12: t //= 1000
        return datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")

    result = []
    cum_tpv = 0.0
    cum_vol  = 0.0
    cur_day  = None

    for c in candles:
        d   = _date(c[0])
        hi  = float(c[2]); lo = float(c[3]); cl = float(c[4])
        vol = float(c[5]) if float(c[5]) > 0 else 1.0
        tp  = (hi + lo + cl) / 3.0
        if d != cur_day:
            cur_day = d; cum_tpv = 0.0; cum_vol = 0.0
        cum_tpv += tp * vol
        cum_vol  += vol
        result.append(cum_tpv / cum_vol)

    return result


def _candle_et_hour_minute(ts_ms):
    """Return (hour, minute) in US/Eastern time for a candle timestamp."""
    from datetime import datetime, timezone as _tz, timedelta as _td
    ts = int(ts_ms)
    if ts > 1e12: ts //= 1000
    utc_dt = datetime.utcfromtimestamp(ts)
    # ET = UTC-5 (EST) or UTC-4 (EDT). Approximate: use UTC-4 Apr-Oct, UTC-5 otherwise.
    month = utc_dt.month
    offset = -4 if 4 <= month <= 10 else -5
    et_dt  = utc_dt + _td(hours=offset)
    return et_dt.hour, et_dt.minute, et_dt.weekday()   # weekday: 0=Mon


def _candle_et_hm(ts_ms):
    """Return (hour*100 + minute) integer in ET for easy comparison."""
    h, m, _ = _candle_et_hour_minute(ts_ms)
    return h * 100 + m


# ─────────────────────────────────────────────
# STRATEGY: 0DTE Opening Range Breakout (ORB)
#
# Instrument:  SPY or any stock symbol (simulates 0DTE ATM options)
# Timeframe:   5-minute bars (or 1-minute, auto-adapts)
# Opening range: first bar(s) covering 09:30–09:35 ET
# Entry:       Break above 5-min high → simulated CALL (+side)
#              Break below 5-min low  → simulated PUT  (-side)
# Only trades: Mondays, Wednesdays, Fridays
# PnL model:   Options premium ~0.5% of underlying per $1 move.
#              TP = +100% of option price, SL = -50% of option price.
#              Time stop: 15:30 ET force-close.
# Risk:        2% of account per trade (spec requirement).
# ─────────────────────────────────────────────

def run_orb_strategy(candles, starting_balance=1000,
                     fee_pct=0.04, slippage_pct=0.02):
    """
    0DTE Opening Range Breakout — SPY options simulation.

    No overlap with unified_bot / simple_ma: those strategies use
    EMA/ADX session-based logic. This uses pure price-structure
    (opening range) on equity options with fixed +100%/-50% targets.

    PnL is modelled as:
      option_premium  ≈ ATR_5m × 0.5   (rough ATM premium estimate)
      position_size   = risk_dollar / (option_premium × 0.50)
                        (stop = 50% of premium = risk_dollar)
      win  = +100% premium × size
      loss =  -50% premium × size
    """
    RISK_PCT        = 0.02   # 2% per trade (spec)
    TP_PCT          = 1.00   # +100% of option price
    SL_PCT          = 0.50   # -50%  of option price
    TIME_STOP_ET    = 1530   # 15:30 ET
    OPEN_RANGE_MINS = 5
    TRADE_DAYS      = {0, 2, 4}   # Mon=0 Wed=2 Fri=4

    trades  = []
    balance = float(starting_balance)

    if len(candles) < 10:
        return trades, balance

    # Group candles by ET date
    from collections import defaultdict
    day_candles = defaultdict(list)
    for c in candles:
        ts = int(c[0]); ts_s = ts // 1000 if ts > 1e12 else ts
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        utc = _dt.utcfromtimestamp(ts_s)
        month = utc.month
        offset = -4 if 4 <= month <= 10 else -5
        import datetime as _dtmod
        et = utc + _dtmod.timedelta(hours=offset)
        day_key = et.strftime("%Y-%m-%d")
        wd = et.weekday()
        day_candles[day_key].append((c, et.hour, et.minute, wd))

    for day_key in sorted(day_candles.keys()):
        bars = day_candles[day_key]
        if not bars:
            continue

        # Only Mon/Wed/Fri
        weekday = bars[0][3]
        if weekday not in TRADE_DAYS:
            continue

        # Build opening range (09:30–09:35 ET)
        or_bars = [(c, h, m) for c, h, m, _ in bars
                   if h == 9 and 30 <= m < 30 + OPEN_RANGE_MINS]
        if not or_bars:
            continue

        or_high = max(float(b[0][2]) for b in or_bars)
        or_low  = min(float(b[0][3]) for b in or_bars)
        if or_high <= or_low:
            continue

        # Estimate ATM option premium ≈ half the opening range
        option_premium = (or_high - or_low) * 0.5
        if option_premium <= 0:
            continue

        risk_dollar = balance * RISK_PCT
        # size such that a 50% move in premium = risk_dollar
        size = risk_dollar / (option_premium * SL_PCT)

        # Find breakout bar after 09:35 ET, before 15:30 ET
        position = None
        day_traded = False

        for c, hr, mn, _ in bars:
            hm = hr * 100 + mn
            if hm < 935:
                continue   # still in opening range
            if hm >= TIME_STOP_ET and position is None:
                break      # past time stop with no trade

            price = float(c[4])   # close of this bar
            hi    = float(c[2])
            lo    = float(c[3])
            t_str = _ts_to_str(c[0])

            # Force-close at time stop
            if hm >= TIME_STOP_ET and position is not None:
                ep   = position["entry_price"]
                side = position["side"]
                prem = position["premium"]
                raw_ret = (price - ep) / ep if side == "BUY" else (ep - price) / ep
                opt_pnl = raw_ret / (or_high - or_low) * prem * size if (or_high - or_low) > 0 else 0
                opt_pnl = max(opt_pnl, -prem * SL_PCT * size)
                fee     = risk_dollar * fee_pct / 100 * 2
                net_pnl = opt_pnl - fee
                balance += net_pnl
                trades.append({
                    "side":       side,
                    "entry":      round(ep, 4),
                    "exit":       round(price, 4),
                    "entry_time": position["time"],
                    "exit_time":  t_str,
                    "pnl":        round(net_pnl, 4),
                    "reason":     "Time stop",
                    "setup":      f"ORB | OR {or_low:.2f}-{or_high:.2f}",
                })
                position = None
                break

            if position is None and not day_traded:
                # Entry on breakout (use close of bar, no lookahead)
                if price > or_high:
                    ep = price * (1 + slippage_pct / 100)
                    position = {"side": "BUY", "entry_price": ep,
                                "premium": option_premium, "time": t_str}
                    day_traded = True
                elif price < or_low:
                    ep = price * (1 - slippage_pct / 100)
                    position = {"side": "SELL", "entry_price": ep,
                                "premium": option_premium, "time": t_str}
                    day_traded = True

            elif position is not None:
                side = position["side"]
                ep   = position["entry_price"]
                prem = position["premium"]
                # Model option PnL: proportional to underlying move / premium
                underlying_move = (price - ep) if side == "BUY" else (ep - price)
                opt_pnl_pct = underlying_move / prem   # as fraction of premium
                # TP: +100% of premium
                if opt_pnl_pct >= TP_PCT:
                    net_pnl = prem * TP_PCT * size - risk_dollar * fee_pct / 100 * 2
                    balance += net_pnl
                    trades.append({
                        "side":       side,
                        "entry":      round(ep, 4),
                        "exit":       round(price, 4),
                        "entry_time": position["time"],
                        "exit_time":  t_str,
                        "pnl":        round(net_pnl, 4),
                        "reason":     "Take profit (+100%)",
                        "setup":      f"ORB | OR {or_low:.2f}-{or_high:.2f}",
                    })
                    position = None
                # SL: -50% of premium
                elif opt_pnl_pct <= -SL_PCT:
                    net_pnl = -(prem * SL_PCT * size) - risk_dollar * fee_pct / 100 * 2
                    balance += net_pnl
                    trades.append({
                        "side":       side,
                        "entry":      round(ep, 4),
                        "exit":       round(price, 4),
                        "entry_time": position["time"],
                        "exit_time":  t_str,
                        "pnl":        round(net_pnl, 4),
                        "reason":     "Stop loss (-50%)",
                        "setup":      f"ORB | OR {or_low:.2f}-{or_high:.2f}",
                    })
                    position = None

    return trades, balance


# ─────────────────────────────────────────────
# STRATEGY: VWAP + EMA Trend
#
# Indicators: 9 EMA, 21 EMA, VWAP (intraday, resets daily)
# Entry:      After 10:30 ET. 9/21 EMA crossover where:
#               - Long:  price > VWAP (VWAP acting as support)
#               - Short: price < VWAP (VWAP acting as resistance)
# Risk:       2% of account per trade
# SL:         50% of 10-period ADR from entry
# Scale-out:  Sell 50% at 75% of ADR from entry (Normal Lite target)
#             Trail remainder at 1×ATR once first target hit
# No overlap with unified_bot: unified_bot uses session/London sweep logic.
#   This strategy uses intraday VWAP support/resistance — fundamentally different.
# ─────────────────────────────────────────────

def run_vwap_ema_strategy(candles, starting_balance=1000,
                           fee_pct=0.04, slippage_pct=0.02):
    """
    VWAP + 9/21 EMA Trend with 2-part scaling.

    Differences from unified_bot (no duplication):
      • Uses VWAP as dynamic support/resistance filter (new)
      • Entries only after 10:30 ET (time-of-day filter, not session-based)
      • 2-part exit: 50% off at 75% of ADR, trail remainder at 1×ATR (new)
      • ADR-based stop (Average Daily Range), not ATR-based (new)
      • 2% risk (vs unified_bot 1%)

    Compatible with 1-minute bars (as specified). Works on 5m too.
    No lookahead: all indicators computed on completed bars.
    """
    RISK_PCT        = 0.02   # 2% per trade
    ENTRY_AFTER_ET  = 1030   # 10:30 ET earliest entry
    CLOSE_ET        = 1600   # 16:00 ET force-close
    ADR_PERIOD      = 10
    EMA_FAST        = 9
    EMA_SLOW        = 21
    ADR_SL_MULT     = 0.50   # SL = 50% of ADR
    ADR_TP1_MULT    = 0.75   # First target = 75% of ADR
    TRAIL_ATR_MULT  = 1.0    # Trail remainder at 1×ATR

    trades  = []
    balance = float(starting_balance)

    if len(candles) < max(EMA_SLOW, ADR_PERIOD * 2) + 5:
        return trades, balance

    closes = [float(c[4]) for c in candles]
    highs  = [float(c[2]) for c in candles]
    lows   = [float(c[3]) for c in candles]

    ema9_s  = _ema_series(closes, EMA_FAST)
    ema21_s = _ema_series(closes, EMA_SLOW)
    vwap_s  = _vwap_series(candles)
    atr_s   = _atr_series(highs, lows, closes, 14)

    # Build daily high/low for ADR computation
    from collections import defaultdict
    day_hl = defaultdict(lambda: {"h": None, "l": None})
    dates_in_order = []

    def bar_date(idx):
        ts = int(candles[idx][0])
        if ts > 1e12: ts //= 1000
        from datetime import datetime as _dt
        utc = _dt.utcfromtimestamp(ts)
        month = utc.month
        off = -4 if 4 <= month <= 10 else -5
        import datetime as _dtmod
        et = utc + _dtmod.timedelta(hours=off)
        return et.strftime("%Y-%m-%d")

    for j in range(len(candles)):
        d  = bar_date(j)
        h  = highs[j]; l = lows[j]
        dh = day_hl[d]
        dh["h"] = max(h, dh["h"] or h)
        dh["l"] = min(l, dh["l"] or l)
        if not dates_in_order or dates_in_order[-1] != d:
            dates_in_order.append(d)

    # ADR per day (computed on prior 10 completed days, no lookahead)
    daily_ranges = [(day_hl[d]["h"] - day_hl[d]["l"]) for d in dates_in_order]
    daily_adr    = {}
    for k, d in enumerate(dates_in_order):
        if k >= ADR_PERIOD:
            daily_adr[d] = sum(daily_ranges[k - ADR_PERIOD: k]) / ADR_PERIOD
        else:
            daily_adr[d] = None

    # Main loop
    position     = None
    current_day  = None
    day_traded   = False

    for i in range(EMA_SLOW + 1, len(candles)):
        e9  = ema9_s[i];   e9p  = ema9_s[i-1]
        e21 = ema21_s[i];  e21p = ema21_s[i-1]
        vwap = vwap_s[i]
        atr_v = atr_s[i]

        if any(v is None for v in [e9, e9p, e21, e21p, vwap, atr_v]):
            continue

        close = closes[i]; hi = highs[i]; lo = lows[i]
        t_str = _ts_to_str(candles[i][0])
        d     = bar_date(i)
        hm    = _candle_et_hm(candles[i][0])

        if d != current_day:
            current_day = d; day_traded = False

        adr = daily_adr.get(d)

        # Force-close at 16:00 ET
        if position is not None and hm >= CLOSE_ET:
            side = position["side"]; ep = position["entry"]
            raw_pnl = ((close - ep) if side == "BUY" else (ep - close)) * position["size"]
            fee = ep * position["size"] * fee_pct / 100 * 2
            net = raw_pnl - fee
            balance += net
            trades.append({
                "side":       side,
                "entry":      round(ep, 6),
                "exit":       round(close, 6),
                "entry_time": position["time"],
                "exit_time":  t_str,
                "pnl":        round(net, 4),
                "reason":     "Force close",
                "setup":      position.get("setup", ""),
            })
            position = None; day_traded = False
            continue

        # ── Manage open position ──────────────────────────────────────────
        if position is not None:
            side    = position["side"]
            ep      = position["entry"]
            sl      = position["sl"]
            tp1     = position["tp1"]
            tp1_hit = position["tp1_hit"]
            trail_sl = position["trail_sl"]
            sz_full  = position["size"]
            sz_rem   = position["size_rem"]
            peak     = position["peak"]

            if side == "BUY":
                if hi > peak: peak = hi; position["peak"] = peak
            else:
                if lo < peak: peak = lo; position["peak"] = peak

            # Advance trail stop
            if tp1_hit:
                if side == "BUY":
                    candidate = peak - atr_v * TRAIL_ATR_MULT
                    if candidate > trail_sl: trail_sl = candidate; position["trail_sl"] = trail_sl
                else:
                    candidate = peak + atr_v * TRAIL_ATR_MULT
                    if candidate < trail_sl: trail_sl = candidate; position["trail_sl"] = trail_sl

            eff_sl = trail_sl if tp1_hit else sl

            # First target (75% ADR): close 50% of position
            if not tp1_hit:
                if (side == "BUY" and hi >= tp1) or (side == "SELL" and lo <= tp1):
                    partial_sz   = sz_full - sz_rem          # 50% already exiting
                    raw_pnl_p1   = ((tp1 - ep) if side == "BUY" else (ep - tp1)) * partial_sz
                    fee_p1       = ep * partial_sz * fee_pct / 100 * 2
                    net_p1       = raw_pnl_p1 - fee_p1
                    balance     += net_p1
                    position["tp1_hit"] = True
                    position["trail_sl"] = ep  # move stop to breakeven
                    trail_sl    = ep
                    trades.append({
                        "side":       side,
                        "entry":      round(ep, 6),
                        "exit":       round(tp1, 6),
                        "entry_time": position["time"],
                        "exit_time":  t_str,
                        "pnl":        round(net_p1, 4),
                        "reason":     "Target 1 (75% ADR) — 50% closed",
                        "setup":      position.get("setup", ""),
                    })
                    continue

            # Full exit: stop loss or trail
            exit_price = exit_reason = None
            if side == "BUY":
                if lo <= eff_sl:
                    exit_price  = eff_sl
                    exit_reason = "Trailing stop" if tp1_hit else "Stop loss"
            else:
                if hi >= eff_sl:
                    exit_price  = eff_sl
                    exit_reason = "Trailing stop" if tp1_hit else "Stop loss"

            if exit_price is not None:
                raw_pnl = ((exit_price - ep) if side == "BUY" else (ep - exit_price)) * sz_rem
                fee     = ep * sz_rem * fee_pct / 100 * 2
                net     = raw_pnl - fee
                balance += net
                trades.append({
                    "side":       side,
                    "entry":      round(ep, 6),
                    "exit":       round(exit_price, 6),
                    "entry_time": position["time"],
                    "exit_time":  t_str,
                    "pnl":        round(net, 4),
                    "reason":     exit_reason + " (remainder)",
                    "setup":      position.get("setup", ""),
                })
                position = None
            continue

        # ── Entry ─────────────────────────────────────────────────────────
        if day_traded or adr is None or hm < ENTRY_AFTER_ET:
            continue

        cross_up   = e9p <= e21p and e9 > e21
        cross_down = e9p >= e21p and e9 < e21

        side = None
        if cross_up   and close > vwap:   side = "BUY"
        elif cross_down and close < vwap: side = "SELL"

        if side is None:
            continue

        # SL = 50% ADR, TP1 = 75% ADR
        sl_dist  = adr * ADR_SL_MULT
        tp1_dist = adr * ADR_TP1_MULT
        if sl_dist <= 0:
            continue

        risk_dollar = balance * RISK_PCT
        size        = risk_dollar / sl_dist
        if size <= 0:
            continue

        ep = close * (1 + slippage_pct/100) if side == "BUY" else close * (1 - slippage_pct/100)
        sl_price  = ep - sl_dist  if side == "BUY" else ep + sl_dist
        tp1_price = ep + tp1_dist if side == "BUY" else ep - tp1_dist

        position = {
            "side":     side,
            "entry":    ep,
            "time":     t_str,
            "sl":       sl_price,
            "tp1":      tp1_price,
            "tp1_hit":  False,
            "trail_sl": sl_price,
            "peak":     ep,
            "size":     size,
            "size_rem": size * 0.50,   # 50% stays after first target
            "setup":    f"VWAP+EMA | {'above' if side=='BUY' else 'below'} VWAP | ADR {adr:.4f}",
        }
        day_traded = True

    return trades, balance


# ─────────────────────────────────────────────
# [D] BACKTEST STRATEGY: SIMPLE MA (percentage-based PnL)
# ─────────────────────────────────────────────

def run_simple_ma_strategy(candles, starting_balance=1000,
                            fee_pct=0.04, slippage_pct=0.02):
    """
    [D] MA crossover + fixed percentage risk per trade.
    Uses a 10/30 SMA crossover on closes.
    PnL is expressed as % of entry so it works for any price scale
    (BTC at 60k, EUR/USD at 1.08, AAPL at 180, Gold at 2300).
    """
    trades      = []
    balance     = float(starting_balance)
    risk_pct    = 0.01          # 1 % of balance per trade
    fee_rate    = fee_pct    / 100
    slip_rate   = slippage_pct / 100

    # need at least 30 candles to start
    if len(candles) < 35:
        return trades, balance

    closes = [float(c[4]) for c in candles]

    def sma(arr, n):
        return sum(arr[-n:]) / n if len(arr) >= n else None

    position = None   # None | dict

    for i in range(30, len(candles)):
        fast = sma(closes[:i], 10)
        slow = sma(closes[:i], 30)
        if fast is None or slow is None:
            continue

        prev_fast = sma(closes[:i - 1], 10)
        prev_slow = sma(closes[:i - 1], 30)
        if prev_fast is None or prev_slow is None:
            continue

        price      = closes[i]
        entry_time = _ts_to_str(candles[i][0])

        # --- entry ---
        if position is None:
            crossed_up   = prev_fast <= prev_slow and fast > slow
            crossed_down = prev_fast >= prev_slow and fast < slow
            if crossed_up:
                ep    = price * (1 + slip_rate)
                position = {"side": "BUY",  "entry": ep, "time": entry_time,
                            "sl": ep * 0.997, "tp": ep * 1.006}
            elif crossed_down:
                ep    = price * (1 - slip_rate)
                position = {"side": "SELL", "entry": ep, "time": entry_time,
                            "sl": ep * 1.003, "tp": ep * 0.994}
            continue

        # --- exit ---
        side = position["side"]
        ep   = position["entry"]
        sl   = position["sl"]
        tp   = position["tp"]
        hi   = float(candles[i][2])
        lo   = float(candles[i][3])

        exit_price  = None
        exit_reason = "Held"

        if side == "BUY":
            if lo <= sl:
                exit_price, exit_reason = sl,    "Stop loss"
            elif hi >= tp:
                exit_price, exit_reason = tp,    "Take profit"
            elif fast < slow:
                exit_price, exit_reason = price, "Signal reversal"
        else:
            if hi >= sl:
                exit_price, exit_reason = sl,    "Stop loss"
            elif lo <= tp:
                exit_price, exit_reason = tp,    "Take profit"
            elif fast > slow:
                exit_price, exit_reason = price, "Signal reversal"

        if exit_price is not None:
            # percentage return so it's price-scale independent
            ret       = ((exit_price - ep) / ep) if side == "BUY" \
                         else ((ep - exit_price) / ep)
            risk_amt  = balance * risk_pct
            gross_pnl = risk_amt * (ret / 0.003)   # normalise to ~1 % per ATR unit
            fee       = risk_amt * fee_rate * 2
            net_pnl   = gross_pnl - fee
            balance  += net_pnl
            trades.append({
                "side":       side,
                "entry":      round(ep,         6),
                "exit":       round(exit_price, 6),
                "entry_time": position["time"],
                "exit_time":  entry_time,
                "pnl":        round(net_pnl, 4),
                "reason":     exit_reason,
            })
            position = None

    return trades, balance


# ─────────────────────────────────────────────
# INDICATOR HELPERS
# ─────────────────────────────────────────────

def _ema_series(values, period):
    """Full EMA series, None for warm-up bars."""
    if len(values) < period:
        return [None] * len(values)
    mult   = 2 / (period + 1)
    result = [None] * (period - 1)
    val    = sum(values[:period]) / period
    result.append(val)
    for v in values[period:]:
        val = (v - val) * mult + val
        result.append(val)
    return result


def _atr_series(highs, lows, closes, period=14):
    """Average True Range (Wilder smoothing), same length as input."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    trs = [None]
    for i in range(1, len(closes)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        ))
    result = [None] * period
    val    = sum(trs[1:period + 1]) / period
    result.append(val)
    for t in trs[period + 1:]:
        val = (val * (period - 1) + t) / period
        result.append(val)
    return result


def _rsi_series(values, period=14):
    """Wilder RSI, same length as input, None for warm-up."""
    if len(values) <= period:
        return [None] * len(values)
    result = [None] * period
    gains  = [max(values[i] - values[i-1], 0) for i in range(1, len(values))]
    losses = [max(values[i-1] - values[i], 0) for i in range(1, len(values))]
    avg_g  = sum(gains[:period])  / period
    avg_l  = sum(losses[:period]) / period
    result.append(100 - 100 / (1 + avg_g / avg_l) if avg_l else 100.0)
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i])  / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        result.append(100 - 100 / (1 + avg_g / avg_l) if avg_l else 100.0)
    return result


def _adx_series(highs, lows, closes, period=14):
    """
    Average Directional Index — measures trend strength (0-100).
    Values > 25 indicate a trending market worth trading.
    """
    n = len(closes)
    if n < period * 2 + 1:
        return [None] * n

    # +DM, -DM, TR
    plus_dm  = [0.0]
    minus_dm = [0.0]
    trs      = [0.0]
    for i in range(1, n):
        up   = highs[i]  - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm.append(up   if (up > down and up > 0)   else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(highs[i]-lows[i],
                       abs(highs[i]-closes[i-1]),
                       abs(lows[i] -closes[i-1])))

    # Smooth with Wilder
    def wilder_smooth(arr, p):
        out  = [None] * p
        val  = sum(arr[:p])
        out.append(val)
        for v in arr[p:]:
            val = val - val / p + v
            out.append(val)
        return out

    s_tr  = wilder_smooth(trs,      period)
    s_pdm = wilder_smooth(plus_dm,  period)
    s_mdm = wilder_smooth(minus_dm, period)

    di_plus  = [None if s_tr[i] is None or s_tr[i] == 0
                else 100 * s_pdm[i] / s_tr[i] for i in range(n)]
    di_minus = [None if s_tr[i] is None or s_tr[i] == 0
                else 100 * s_mdm[i] / s_tr[i] for i in range(n)]

    dx = []
    for i in range(n):
        if di_plus[i] is None or di_minus[i] is None:
            dx.append(None)
        else:
            s = di_plus[i] + di_minus[i]
            dx.append(100 * abs(di_plus[i] - di_minus[i]) / s if s else 0.0)

    # Smooth DX → ADX
    first_valid = next((i for i, v in enumerate(dx) if v is not None), None)
    if first_valid is None:
        return [None] * n
    adx_out = [None] * (first_valid + period)
    start   = first_valid + period
    if start >= n:
        return [None] * n
    val = sum(v for v in dx[first_valid:first_valid + period] if v is not None) / period
    adx_out.append(val)
    for j in range(start + 1, n):
        if dx[j] is not None:
            val = (val * (period - 1) + dx[j]) / period
        adx_out.append(val)
    return adx_out[:n]


# ─────────────────────────────────────────────
# UNIFIED BOT STRATEGY  v3
#
# What was wrong with v2 and what we fixed
# ─────────────────────────────────────────────
# BUG 1 — EMA200 warm-up = 200 bars.  On a 2-day 5m window (576 candles)
#   the strategy only had 376 bars to trade, and the EMA200 trend hadn't
#   had time to form a reliable macro direction. Fixed: use EMA50 as the
#   macro filter (50-bar warm-up) so the strategy works on short windows.
#
# BUG 2 — Fee formula was `(ep + exit_price) * size * fee_rate`.
#   This multiplies two prices × size = price² units, not money.
#   For BTC at $90k: (90000 + 90000) * size * 0.0004 = 72 per unit, absurd.
#   Fixed: fee = `notional * fee_rate * 2` where notional = entry_price * size.
#   Now fees are a realistic ~0.04% of trade value each side.
#
# BUG 3 — SL based on `min(recent_lows[-5:])`.  On choppy 5m BTC data the
#   5 most recent lows are all very close to current price, giving a tiny
#   r_dist → enormous position size → single loss wipes the account.
#   Fixed: SL = entry ± 1.5 × ATR (always structurally meaningful and
#   proportional to actual volatility), with size = risk_dollar / sl_distance.
#
# BUG 4 — Entry fires every bar that passes the filter — it re-enters
#   immediately after a closed trade with no pause to re-assess.
#   Fixed: mandatory 3-bar cooldown after ANY exit (win or loss).
#
# Design principles
# ─────────────────
#  • 1 % of starting_balance risked per trade — fixed, never compounds down.
#  • SL = 1.5 × ATR from entry.  TP = SL_distance × 2.5 (2.5 R:R minimum).
#  • Trailing stop activates at +1 R, trails at 1 × ATR behind peak price.
#  • Entry requires: EMA trend stack + ADX > 20 (trending) + RSI zone filter.
#  • Works on any price scale: size is always risk_dollar / sl_distance.
# ─────────────────────────────────────────────

def run_unified_bot_strategy(candles, starting_balance=1000,
                              fee_pct=0.04, slippage_pct=0.02):
    """
    ICT -- Asian Range -> London Push -> New York Reversal

    Phase 1  Asian session  00:00-08:00 GMT   Mark ASH / ASL
    Phase 2  London open    08:00-10:30 GMT   Detect manipulation push
    Phase 3  NY open        13:00-15:00 GMT   Trade the reversal

    Entry : Displacement candle (body > 50% of range) closing back toward
            the Asian range. FVG left by that candle used for tighter entry.
    SL    : Above London push high (shorts) / below London push low (longs).
    TP1   : Asian range midpoint -- 50% partial exit, SL moved to breakeven.
    TP2   : Opposite Asian range boundary (ASL for shorts, ASH for longs).

    Daily-candle fallback (timestamp gap >= 20 h):
    EMA9/21/50 + ADX + RSI trend-follow, one trade per bar.

    Session limits: 3 wins / 1 loss per calendar day.
    """
    from collections import defaultdict

    # -- Constants --------------------------------------------------------
    RISK_PCT          = 0.01        # 1% of starting balance per trade
    MAX_WINS_DAY      = 3
    MAX_LOSS_DAY      = 1

    # GMT session boundaries (minutes from midnight)
    ASIAN_START   =    0   # 00:00
    ASIAN_END     =  480   # 08:00
    LONDON_START  =  480   # 08:00
    LONDON_END    =  630   # 10:30
    NY_START      =  780   # 13:00  — NY open, reversal entry window begins
    NY_END        = 1020   # 17:00  — London/NY overlap end; doc says "strongest 13:00–17:00 GMT"
    SESSION_CLOSE = 1200   # 20:00  — hard EOD close

    DISP_BODY_RATIO = 0.50   # displacement body must be > 50% of candle range
    SL_BUFFER       = 0.0005 # 0.05% buffer beyond push extreme

    # Fallback (daily bars only)
    WARMUP        = 55
    ADX_MIN_DAILY = 18
    RSI_BUY_LO    = 40;  RSI_BUY_HI  = 75
    RSI_SELL_LO   = 25;  RSI_SELL_HI = 60

    # -- Setup -----------------------------------------------------------
    trades      = []
    balance     = float(starting_balance)
    risk_dollar = balance * RISK_PCT
    fee_rate    = fee_pct    / 100
    slip_rate   = slippage_pct / 100

    if not candles or len(candles) < 10:
        return trades, balance

    gap_ms   = int(candles[1][0]) - int(candles[0][0]) if len(candles) >= 2 else 0
    is_daily = gap_ms >= 20 * 3600 * 1000

    def _hm(ts):
        dt = datetime.utcfromtimestamp(int(ts) / 1000)
        return dt.hour * 60 + dt.minute

    def _date(ts):
        return datetime.utcfromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")

    def _str(ts):
        return datetime.utcfromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M")

    # ====================================================================
    # PATH A -- INTRADAY
    # ====================================================================
    if not is_daily:
        # Pre-pass: bucket candles into sessions per day
        day_buckets = defaultdict(lambda: {"asian": [], "london": [], "ny": [], "after": []})
        for c in candles:
            hm = _hm(c[0]); d = _date(c[0])
            if   ASIAN_START  <= hm < ASIAN_END:    day_buckets[d]["asian"].append(c)
            elif LONDON_START <= hm < LONDON_END:   day_buckets[d]["london"].append(c)
            elif NY_START     <= hm < NY_END:       day_buckets[d]["ny"].append(c)
            elif NY_END       <= hm < SESSION_CLOSE: day_buckets[d]["after"].append(c)

        position    = None
        current_day = None
        day_wins    = 0
        day_losses  = 0

        for day in sorted(day_buckets.keys()):
            dd     = day_buckets[day]
            asian  = dd["asian"]
            london = dd["london"]
            ny     = dd["ny"]
            after  = dd["after"]

            if day != current_day:
                current_day = day
                day_wins    = 0
                day_losses  = 0
                # Force-close any position carried from previous day
                if position is not None:
                    all_prev = sorted(
                        [c for bkt in day_buckets.values()
                         for c in (bkt["ny"] + bkt["after"])
                         if _date(c[0]) < day],
                        key=lambda c: int(c[0])
                    )
                    lc  = float(all_prev[-1][4]) if all_prev else position["entry"]
                    sz  = position["size_rem"] if position["scaled"] else position["size"]
                    gp  = ((lc - position["entry"]) if position["side"] == "BUY"
                           else (position["entry"] - lc)) * sz
                    fee = position["entry"] * sz * fee_rate * 2
                    net = gp - fee
                    balance += net
                    trades.append({
                        "side": position["side"], "entry": round(position["entry"], 6),
                        "exit": round(lc, 6),     "pnl":   round(net, 4),
                        "entry_time": position["time"], "exit_time": position["time"],
                        "reason": "End-of-day close",
                    })
                    position = None

            if not asian or not london or not ny:
                continue
            if day_losses >= MAX_LOSS_DAY or day_wins >= MAX_WINS_DAY:
                continue

            # Phase 1: Asian range
            ash = max(float(c[2]) for c in asian)
            asl = min(float(c[3]) for c in asian)
            mid = (ash + asl) / 2
            if ash <= asl:
                continue

            # Phase 2: London push -- which boundary did it sweep?
            l_high = max(float(c[2]) for c in london)
            l_low  = min(float(c[3]) for c in london)

            pushed_above = l_high > ash
            pushed_below = l_low  < asl

            if not pushed_above and not pushed_below:
                continue

            # If both swept take the larger deviation
            if pushed_above and pushed_below:
                if (l_high - ash) >= (asl - l_low):
                    pushed_below = False
                else:
                    pushed_above = False

            # Phase 2 quality filters — distinguish manipulation from genuine breakout
            # -----------------------------------------------------------------------
            # Filter 1: sweep must penetrate at least 10% of the Asian range.
            # A 1-pip brush of the boundary is noise, not institutional sweep.
            asian_range_size = ash - asl
            if asian_range_size <= 0:
                continue
            sweep_depth = (l_high - ash) if pushed_above else (asl - l_low)
            if sweep_depth < asian_range_size * 0.10:
                continue

            # Filter 2: "no acceptance" — the London session must FAIL to hold
            # beyond the Asian range boundary.  The last London candle close must
            # be back inside (or at) the boundary, confirming the push was
            # manipulation rather than a genuine trend continuation.
            last_london_close = float(london[-1][4])
            if pushed_above and last_london_close > ash:
                continue   # Price accepted above ASH → genuine breakout, skip
            if pushed_below and last_london_close < asl:
                continue   # Price accepted below ASL → genuine breakout, skip

            # Phase 3: NY reversal direction is OPPOSITE to push
            if pushed_above:
                reversal  = "SELL"
                push_ext  = l_high
                sl_price  = push_ext * (1 + SL_BUFFER)
                tp1_price = mid
                tp2_price = asl
            else:
                reversal  = "BUY"
                push_ext  = l_low
                sl_price  = push_ext * (1 - SL_BUFFER)
                tp1_price = mid
                tp2_price = ash

            # Find displacement candle + FVG in NY session
            # ---------------------------------------------------------------
            # Aggressive entry : enter at displacement candle close.
            # Conservative entry: wait for price to retrace into the FVG zone
            #   left by the displacement (better R:R, tighter stop).
            # We prefer conservative when a clean FVG is present; fall back to
            # aggressive if no FVG forms or price never retraces into it.
            entry_candle = None
            fvg_hi = fvg_lo = None
            fvg_entry_price = None   # set when price fills the FVG zone

            for k, c in enumerate(ny):
                o   = float(c[1]); h = float(c[2])
                lo_ = float(c[3]); cls = float(c[4])
                rng = h - lo_
                if rng == 0:
                    continue
                body = abs(cls - o)

                is_disp = (body / rng) > DISP_BODY_RATIO
                if reversal == "SELL":
                    is_disp = is_disp and cls < o and cls <= ash
                else:
                    is_disp = is_disp and cls > o and cls >= asl

                if not is_disp:
                    continue

                entry_candle = c

                # Proper ICT FVG: 3-candle pattern — gap between candle[k-1]
                # and candle[k+1] that candle[k] (displacement) skipped over.
                if k >= 1 and k + 1 < len(ny):
                    prev = ny[k - 1]; nxt = ny[k + 1]
                    if reversal == "SELL":
                        # Bearish FVG: prev.low > next.high  (imbalance above next)
                        if float(prev[3]) > float(nxt[2]):
                            fvg_hi = float(prev[3]); fvg_lo = float(nxt[2])
                    else:
                        # Bullish FVG: prev.high < next.low  (imbalance below next)
                        if float(prev[2]) < float(nxt[3]):
                            fvg_lo = float(prev[2]); fvg_hi = float(nxt[3])
                break

            if entry_candle is None:
                continue

            # --- Entry selection: conservative (FVG) preferred, else aggressive ---
            # Look ahead through remaining NY candles for a retrace into the FVG.
            # If found, that candle becomes the entry; if not, use aggressive entry.
            ec = float(entry_candle[4])
            if fvg_hi is not None and fvg_lo is not None:
                fvg_mid = (fvg_hi + fvg_lo) / 2
                try:
                    k_disp = ny.index(entry_candle)
                except ValueError:
                    k_disp = len(ny)
                # Scan forward for a candle that trades into the FVG zone
                for c_fwd in ny[k_disp + 1:]:
                    h_fwd = float(c_fwd[2]); l_fwd = float(c_fwd[3])
                    if reversal == "SELL" and h_fwd >= fvg_lo:
                        # Price retraced up into the FVG — conservative short entry
                        fvg_entry_price = min(h_fwd, fvg_mid)
                        entry_candle = c_fwd
                        break
                    elif reversal == "BUY" and l_fwd <= fvg_hi:
                        # Price retraced down into the FVG — conservative long entry
                        fvg_entry_price = max(l_fwd, fvg_mid)
                        entry_candle = c_fwd
                        break
            # Final entry: conservative (FVG retrace) preferred, aggressive fallback
            raw_entry   = fvg_entry_price if fvg_entry_price is not None else ec
            entry_price = raw_entry * (1 - slip_rate) if reversal == "SELL" else raw_entry * (1 + slip_rate)

            risk_dist = abs(entry_price - sl_price)
            if risk_dist <= 0:
                continue

            size = risk_dollar / risk_dist

            position = {
                "side":     reversal,
                "entry":    entry_price,
                "sl":       sl_price,
                "tp1":      tp1_price,
                "tp2":      tp2_price,
                "size":     size,
                "size_rem": size * 0.5,
                "scaled":   False,
                "time":     entry_candle[0],
                "setup":    ("ICT " + ("bear" if reversal == "SELL" else "bull") +
                             " | push " + ("above ASH" if pushed_above else "below ASL") +
                             (" | FVG entry" if fvg_entry_price is not None
                              else " | aggressive entry")),
            }

            # Walk remaining candles (rest of NY + after-hours)
            try:
                k_start = ny.index(entry_candle) + 1
            except ValueError:
                k_start = len(ny)
            remaining = ny[k_start:] + after

            for c in remaining:
                if position is None:
                    break
                h   = float(c[2]); lo_ = float(c[3])
                t   = c[0]; side = position["side"]

                if side == "SELL":
                    if not position["scaled"] and lo_ <= position["tp1"]:
                        ep  = position["tp1"]; sz = position["size"] * 0.5
                        gp  = (position["entry"] - ep) * sz
                        fee = position["entry"] * sz * fee_rate * 2
                        net = gp - fee
                        balance += net
                        trades.append({
                            "side": "SELL", "entry": round(position["entry"], 6),
                            "exit": round(ep, 6), "pnl": round(net, 4),
                            "entry_time": position["time"], "exit_time": t,
                            "reason": "TP1 -- Asian midpoint (50%)",
                        })
                        position["scaled"] = True
                        position["sl"]     = position["entry"]  # move to breakeven

                    elif position["scaled"] and lo_ <= position["tp2"]:
                        ep  = position["tp2"]; sz = position["size_rem"]
                        gp  = (position["entry"] - ep) * sz
                        fee = position["entry"] * sz * fee_rate * 2
                        net = gp - fee
                        balance += net
                        trades.append({
                            "side": "SELL", "entry": round(position["entry"], 6),
                            "exit": round(ep, 6), "pnl": round(net, 4),
                            "entry_time": position["time"], "exit_time": t,
                            "reason": "TP2 -- Opposite Asian boundary (ASL)",
                        })
                        day_wins += 1; position = None

                    elif h >= position["sl"]:
                        ep  = position["sl"]
                        sz  = position["size_rem"] if position["scaled"] else position["size"]
                        gp  = (position["entry"] - ep) * sz
                        fee = position["entry"] * sz * fee_rate * 2
                        net = gp - fee
                        balance += net
                        trades.append({
                            "side": "SELL", "entry": round(position["entry"], 6),
                            "exit": round(ep, 6), "pnl": round(net, 4),
                            "entry_time": position["time"], "exit_time": t,
                            "reason": ("Stop loss (at breakeven)"
                                       if position["scaled"] else "Stop loss"),
                        })
                        if not position["scaled"]: day_losses += 1
                        position = None

                else:  # BUY
                    if not position["scaled"] and h >= position["tp1"]:
                        ep  = position["tp1"]; sz = position["size"] * 0.5
                        gp  = (ep - position["entry"]) * sz
                        fee = position["entry"] * sz * fee_rate * 2
                        net = gp - fee
                        balance += net
                        trades.append({
                            "side": "BUY", "entry": round(position["entry"], 6),
                            "exit": round(ep, 6), "pnl": round(net, 4),
                            "entry_time": position["time"], "exit_time": t,
                            "reason": "TP1 -- Asian midpoint (50%)",
                        })
                        position["scaled"] = True
                        position["sl"]     = position["entry"]

                    elif position["scaled"] and h >= position["tp2"]:
                        ep  = position["tp2"]; sz = position["size_rem"]
                        gp  = (ep - position["entry"]) * sz
                        fee = position["entry"] * sz * fee_rate * 2
                        net = gp - fee
                        balance += net
                        trades.append({
                            "side": "BUY", "entry": round(position["entry"], 6),
                            "exit": round(ep, 6), "pnl": round(net, 4),
                            "entry_time": position["time"], "exit_time": t,
                            "reason": "TP2 -- Opposite Asian boundary (ASH)",
                        })
                        day_wins += 1; position = None

                    elif lo_ <= position["sl"]:
                        ep  = position["sl"]
                        sz  = position["size_rem"] if position["scaled"] else position["size"]
                        gp  = (ep - position["entry"]) * sz
                        fee = position["entry"] * sz * fee_rate * 2
                        net = gp - fee
                        balance += net
                        trades.append({
                            "side": "BUY", "entry": round(position["entry"], 6),
                            "exit": round(ep, 6), "pnl": round(net, 4),
                            "entry_time": position["time"], "exit_time": t,
                            "reason": ("Stop loss (at breakeven)"
                                       if position["scaled"] else "Stop loss"),
                        })
                        if not position["scaled"]: day_losses += 1
                        position = None

            # Force-close at session end if still open
            if position is not None:
                last = (after or ny)[-1] if (after or ny) else None
                if last:
                    lc  = float(last[4])
                    sz  = position["size_rem"] if position["scaled"] else position["size"]
                    gp  = ((lc - position["entry"]) if position["side"] == "BUY"
                           else (position["entry"] - lc)) * sz
                    fee = position["entry"] * sz * fee_rate * 2
                    net = gp - fee
                    balance += net
                    trades.append({
                        "side": position["side"], "entry": round(position["entry"], 6),
                        "exit": round(lc, 6), "pnl": round(net, 4),
                        "entry_time": position["time"], "exit_time": last[0],
                        "reason": "Session-end close (20:00 GMT)",
                    })
                    position = None

        return trades, balance

    # ====================================================================
    # PATH B -- DAILY BARS fallback  (EMA + ADX + RSI)
    # ====================================================================
    closes = [float(c[4]) for c in candles]
    highs  = [float(c[2]) for c in candles]
    lows   = [float(c[3]) for c in candles]

    ema9_s  = _ema_series(closes, 9)
    ema21_s = _ema_series(closes, 21)
    ema50_s = _ema_series(closes, 50)
    atr_s   = _atr_series(highs, lows, closes, 14)
    rsi_s   = _rsi_series(closes, 14)
    adx_s   = _adx_series(highs, lows, closes, 14)

    position    = None
    current_day = None
    day_wins    = 0
    day_losses  = 0

    for i in range(WARMUP, len(candles)):
        e9    = ema9_s[i];  e21 = ema21_s[i]; e50 = ema50_s[i]
        atr_v = atr_s[i];  rsi_v = rsi_s[i]; adx_v = adx_s[i]
        if any(v is None for v in [e9, e21, e50, atr_v, rsi_v, adx_v]) or atr_v <= 0:
            continue

        close = closes[i]; hi = highs[i]; lo = lows[i]
        t_str = _str(candles[i][0])
        today = _date(candles[i][0])

        if today != current_day:
            current_day = today; day_wins = 0; day_losses = 0

        if position is not None:
            ep = position["entry"]; sl_p = position["sl"]; tp_p = position["tp"]
            side = position["side"]; sz = position["size"]
            exit_price = exit_reason = None
            if side == "BUY":
                if lo <= sl_p:  exit_price, exit_reason = sl_p, "Stop loss"
                elif hi >= tp_p: exit_price, exit_reason = tp_p, "Take profit"
            else:
                if hi >= sl_p:  exit_price, exit_reason = sl_p, "Stop loss"
                elif lo <= tp_p: exit_price, exit_reason = tp_p, "Take profit"
            if exit_price:
                gp  = ((exit_price - ep) if side == "BUY" else (ep - exit_price)) * sz
                fee = ep * sz * fee_rate * 2
                net = gp - fee
                balance += net
                if net > 0: day_wins   += 1
                else:       day_losses += 1
                trades.append({
                    "side": side, "entry": round(ep, 6), "exit": round(exit_price, 6),
                    "pnl": round(net, 4), "entry_time": position["time"],
                    "exit_time": t_str, "reason": exit_reason,
                })
                position = None
            continue

        if day_losses >= MAX_LOSS_DAY or day_wins >= MAX_WINS_DAY:
            continue

        sl_dist = max(atr_v * 1.5, close * 0.001)
        direction = None
        if e9 > e21 and close > e50 and adx_v >= ADX_MIN_DAILY and RSI_BUY_LO < rsi_v < RSI_BUY_HI:
            direction = "BUY"
        elif e9 < e21 and close < e50 and adx_v >= ADX_MIN_DAILY and RSI_SELL_LO < rsi_v < RSI_SELL_HI:
            direction = "SELL"
        if not direction:
            continue

        ep   = close * (1 + slip_rate) if direction == "BUY" else close * (1 - slip_rate)
        sl_p = ep - sl_dist if direction == "BUY" else ep + sl_dist
        tp_p = ep + sl_dist * 3.0 if direction == "BUY" else ep - sl_dist * 3.0
        sz   = risk_dollar / sl_dist
        position = {
            "side": direction, "entry": ep, "sl": sl_p, "tp": tp_p,
            "size": sz, "time": t_str,
        }

    return trades, balance


# ─────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────

@app.route("/api/health")
def health():
    polygon_key = os.environ.get("POLYGON_API_KEY", "")
    return jsonify({
        "ok":           True,
        "time":         now_str(),
        "polygon_key":  bool(polygon_key),
    })


@app.route("/api/symbols", methods=["GET"])
def get_symbols():
    """[H] Return canonical symbol list with market membership."""
    symbol_market = {sym: mkt for mkt, syms in MARKETS.items() for sym in syms}
    return jsonify({
        "symbols": ALL_SYMBOLS,
        "markets": MARKETS,
        "symbol_market": symbol_market,
    })


@app.route("/api/signals", methods=["GET"])
@auth_required
def signals():
    """
    [A][E] Signals for all 18 symbols using 5m interval.

    Rate-limit strategy:
    - Crypto (Binance) symbols are free to poll — no TD credits used.
    - Non-crypto symbols are cached for NON_CRYPTO_CANDLE_TTL (5 min).
      On the first call all 14 non-crypto symbols are fetched sequentially
      through the rate-limiter (8 s gap each = ~112 s total).
      On subsequent calls within 5 min the cached data is returned instantly.
    - The frontend polls every 15 s but most calls hit the cache.
    """
    cfg      = get_user_config()
    strategy = request.args.get("strategy", "bot").lower()
    out      = []
    errors   = []

    # Return cached summaries without waiting on TD for symbols we already have
    fresh, needs_fetch = [], []
    for sym in ALL_SYMBOLS:
        cache_key = (sym, strategy, SIGNALS_INTERVAL)
        cached = _cache_get(_summary_cache, cache_key, SUMMARY_TTL_SECONDS)
        if cached is not None:
            fresh.append(cached)
        else:
            needs_fetch.append(sym)

    # Return cached symbols immediately; fetch the rest
    out.extend(fresh)
    for sym in needs_fetch:
        try:
            s = get_symbol_summary(sym, strategy, SIGNALS_INTERVAL, cfg)
            if s:
                out.append(s)
            else:
                errors.append({"symbol": sym, "error": "No data returned"})
        except Exception as e:
            errors.append({"symbol": sym, "error": str(e)})

    # Re-sort to the canonical order so the frontend always sees consistent ordering
    order = {sym: i for i, sym in enumerate(ALL_SYMBOLS)}
    out.sort(key=lambda s: order.get(s["symbol"], 999))

    return jsonify({
        "signals":     out,
        "last_update": now_str(),
        "errors":      errors,
        "config":      cfg,
    })


@app.route("/api/signal/<symbol>", methods=["GET"])
@auth_required
def signal_detail(symbol):
    cfg      = get_user_config()
    interval = request.args.get("interval", SIGNALS_INTERVAL)
    strategy = request.args.get("strategy", "bot").lower()
    s = get_symbol_summary(symbol.upper(), strategy, interval, cfg)
    if not s:
        return jsonify({"error": f"No data for {symbol}"}), 404
    return jsonify(s)


@app.route("/api/chart-candles", methods=["GET"])
@auth_required
def chart_candles():
    try:
        symbol   = request.args.get("symbol", "BTCUSDT").upper()
        interval = request.args.get("interval", "5m")
        limit    = int(request.args.get("limit", 200))
        df = fetch_df_for_symbol(symbol, interval, limit)
        if df is None:
            return jsonify({"ok": False, "data": [], "error": f"No candle data for {symbol}"}), 200
        out = [{
            "time":  int(r["time"].timestamp()),
            "open":  float(r["open"]),
            "high":  float(r["high"]),
            "low":   float(r["low"]),
            "close": float(r["close"]),
        } for _, r in df.iterrows()]
        return jsonify({"ok": True, "data": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "data": []}), 500


@app.route("/api/backtest", methods=["POST", "OPTIONS"])
@auth_required
def api_backtest():
    """
    [B][C][D][G] Full multi-market backtester.
    • Crypto  : Binance range fetch with random historical window.
    • Non-crypto: Polygon daily bars fetched once and sliced for random windows.
    • Returns descriptive error messages at every failure point.
    """
    data = request.get_json(force=True) or {}

    symbol      = str(data.get("symbol",      "BTCUSDT")).upper()
    interval    = str(data.get("interval",    "5m"))
    strategy    = str(data.get("strategy",    "unified_bot")).lower()
    period_days = max(2, min(int(data.get("period_days", 7)), 60))
    rand_window = bool(data.get("random_window", True))
    sb          = float(data.get("starting_balance", 1000))
    fee_pct     = float(data.get("fee_percent",       0.04))
    slip_pct    = float(data.get("slippage_percent",  0.02))

    market = detect_market(symbol)

    # ── validate symbol ──
    if symbol not in ALL_SYMBOLS:
        return jsonify({
            "error": f"Symbol '{symbol}' is not supported. "
                     f"Supported symbols: {ALL_SYMBOLS}"
        }), 400

    # ── validate interval ──
    valid_intervals = ["1m", "5m", "15m", "1h", "4h"]
    if interval not in valid_intervals:
        return jsonify({
            "error": f"Interval '{interval}' is not supported. "
                     f"Use one of: {valid_intervals}"
        }), 400

    # ── fetch candles ──
    actual_interval = interval          # may be upgraded for non-crypto on short intervals
    start_date = end_date = None

    try:
        if market == "crypto":
            # Binance range fetch with random window
            iv_minutes  = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}[interval]
            target_rows = max(100, min(int(period_days * 24 * 60 / iv_minutes), 1000))
            period_ms   = period_days * 24 * 60 * 60 * 1000
            now_utc     = datetime.now(timezone.utc)

            if rand_window:
                earliest   = MARKET_EARLIEST["crypto"]
                latest_end = now_utc - timedelta(hours=1)
                latest_start = latest_end - timedelta(days=period_days)
                if latest_start > earliest:
                    span = int((latest_start - earliest).total_seconds())
                    offset = random.randint(0, span)
                    start_dt = earliest + timedelta(seconds=offset)
                else:
                    start_dt = earliest
                end_dt   = start_dt + timedelta(days=period_days)
                start_ms = int(start_dt.timestamp() * 1000)
                end_ms   = int(end_dt.timestamp()   * 1000)
            else:
                end_ms   = int(now_utc.timestamp() * 1000)
                start_ms = end_ms - period_ms
                start_dt = datetime.utcfromtimestamp(start_ms / 1000)
                end_dt   = datetime.utcfromtimestamp(end_ms   / 1000)

            start_date = start_dt.strftime("%Y-%m-%d")
            end_date   = end_dt.strftime("%Y-%m-%d")

            candles = fetch_binance_range(symbol, interval, start_ms, end_ms, target_rows)

            if not candles or len(candles) < 60:
                return jsonify({
                    "error": (
                        f"Binance returned only {len(candles)} candles for "
                        f"{symbol} {interval} ({start_date} → {end_date}). "
                        f"Need ≥ 60. Try a longer period_days or a different symbol."
                    )
                }), 400

        else:
            # Non-crypto: use Polygon daily bars (cached 30 min,
            # cached 30 min) to avoid competing with the signals rate limit.
            candles, actual_interval, start_date, end_date = \
                fetch_non_crypto_backtest_candles(
                    symbol, period_days, random_window=rand_window
                )

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({
            "error": f"Unexpected error fetching candles for {symbol}: {e}"
        }), 500

    # ── run strategy ──
    try:
        if strategy == "unified_bot":
            trades, ending_balance = run_unified_bot_strategy(candles, sb, fee_pct, slip_pct)
        elif strategy == "orb_0dte":
            trades, ending_balance = run_orb_strategy(candles, sb, fee_pct, slip_pct)
        elif strategy == "vwap_ema":
            trades, ending_balance = run_vwap_ema_strategy(candles, sb, fee_pct, slip_pct)
        else:
            trades, ending_balance = run_simple_ma_strategy(candles, sb, fee_pct, slip_pct)
    except Exception as e:
        return jsonify({
            "error": f"Strategy '{strategy}' crashed: {e}. "
                     f"Candles available: {len(candles)}"
        }), 500

    # ── compute summary stats ──
    total   = len(trades)
    wins    = [t for t in trades if t["pnl"] > 0]
    losses  = [t for t in trades if t["pnl"] <= 0]
    net_pnl = ending_balance - sb

    win_rate     = (len(wins) / total * 100) if total else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))
    pf           = (gross_profit / gross_loss) if gross_loss else 0

    start_ts = candles[0][0]
    end_ts   = candles[-1][0]
    days     = max(1, (int(end_ts) - int(start_ts)) / (1000 * 60 * 60 * 24))

    # ── persist ──
    run_id = str(uuid.uuid4())
    try:
        conn = get_conn(); c = conn.cursor()
        summary_obj = {
            "starting_balance": sb, "final_balance": round(ending_balance, 2),
            "net_pnl": round(net_pnl, 2), "total_trades": total,
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(win_rate, 2), "profit_factor": round(pf, 2),
        }
        c.execute(
            """INSERT INTO backtest_runs VALUES
               (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                run_id, g.user_id, symbol, actual_interval, strategy,
                start_date, end_date,
                total, round(net_pnl, 2), round(pf, 2),
                0, 0, round(win_rate, 2),
                json.dumps(summary_obj), json.dumps(trades[:200]), now_str(),
            ),
        )
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[backtest] DB save failed: {e}")

    summary = {
        "starting_balance": sb,
        "final_balance":    round(ending_balance, 2),
        "net_pnl":          round(net_pnl, 2),
        "total_trades":     total,
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate":         round(win_rate, 2),
        "profit_factor":    round(pf, 2),
        "start_date":       start_date,
        "end_date":         end_date,
        "actual_interval":  actual_interval,
        "candles_used":     len(candles),
        "trades_per_day":   round(total / days, 2),
    }

    return jsonify({
        "ok":             True,
        "id":             run_id,
        "symbol":         symbol,
        "market":         market,
        "interval":       actual_interval,
        "strategy":       strategy,
        "start_date":     start_date,
        "end_date":       end_date,
        "start_time":     int(start_ts),
        "end_time":       int(end_ts),
        "candles_used":   len(candles),
        "total_trades":   total,
        "net_pnl":        round(net_pnl, 2),
        "win_rate":       round(win_rate, 2),
        "profit_factor":  round(pf, 2),
        "trades_per_day": round(total / days, 2),
        "trades":         trades,
        "summary":        summary,
    })


@app.route("/api/backtest-runs", methods=["GET"])
@auth_required
def list_backtest_runs():
    conn = get_conn(); c = conn.cursor()
    c.execute(
        """SELECT id, symbol, interval, strategy, total_trades, net_pnl,
                  profit_factor, max_drawdown_percent, win_rate, created_at
           FROM backtest_runs WHERE user_id=%s ORDER BY created_at DESC LIMIT 50""",
        (g.user_id,))
    rows = c.fetchall(); conn.close()
    return jsonify([{
        "id": r[0], "symbol": r[1], "interval": r[2], "strategy": r[3],
        "total_trades": r[4], "net_pnl": r[5], "profit_factor": r[6],
        "max_drawdown_percent": r[7], "win_rate": r[8], "created_at": r[9],
    } for r in rows])


@app.route("/api/backtest-runs/<run_id>", methods=["GET"])
@auth_required
def backtest_run_detail(run_id):
    conn = get_conn(); c = conn.cursor()
    c.execute(
        """SELECT symbol, interval, strategy, summary_json, trades_json, created_at
           FROM backtest_runs WHERE id=%s AND user_id=%s""",
        (run_id, g.user_id))
    row = c.fetchone(); conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "symbol": row[0], "interval": row[1], "strategy": row[2],
        "summary": json.loads(row[3]), "trades": json.loads(row[4]),
        "created_at": row[5],
    })


# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
@auth_required
def get_settings():
    return jsonify(get_user_config())


@app.route("/api/settings", methods=["POST"])
@auth_required
def update_settings():
    data = request.get_json(force=True) or {}
    cfg  = get_user_config()
    for k in [
        "risk_reward", "risk_percent", "min_confidence", "starting_balance",
        "max_trades_per_day", "max_daily_loss_percent", "max_consecutive_losses",
        "min_smc_score", "min_volume_multiplier", "trading_mode",
        "avoid_quiet_market", "avoid_sideways_market",
    ]:
        if k in data:
            cfg[k] = data[k]
    if "symbols" in data and isinstance(data["symbols"], list):
        cfg["symbols"] = [s.upper() for s in data["symbols"] if isinstance(s, str)]
    if "blocked_crypto_hours_utc" in data and isinstance(data["blocked_crypto_hours_utc"], list):
        cfg["blocked_crypto_hours_utc"] = data["blocked_crypto_hours_utc"]
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET settings=%s WHERE id=%s", (json.dumps(cfg), g.user_id))
    conn.commit(); conn.close()
    return jsonify(cfg)


# ─────────────────────────────────────────────
# JOURNAL
# ─────────────────────────────────────────────

@app.route("/api/journal", methods=["GET"])
@auth_required
def list_journal():
    conn = get_conn(); c = conn.cursor()
    c.execute(
        """SELECT id, symbol, side, entry, exit, pnl, mood, tags, notes, created_at
           FROM journal WHERE user_id=%s ORDER BY created_at DESC""",
        (g.user_id,))
    rows = c.fetchall(); conn.close()
    return jsonify([{
        "id": r[0], "symbol": r[1], "side": r[2], "entry": r[3],
        "exit": r[4], "pnl": r[5], "mood": r[6],
        "tags": json.loads(r[7] or "[]"), "notes": r[8], "created_at": r[9],
    } for r in rows])


@app.route("/api/journal", methods=["POST"])
@auth_required
def create_journal():
    d   = request.get_json(force=True) or {}
    eid = str(uuid.uuid4())
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "INSERT INTO journal VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (eid, g.user_id, (d.get("symbol") or "").upper(), d.get("side"),
         float(d.get("entry") or 0), float(d.get("exit") or 0),
         float(d.get("pnl") or 0), d.get("mood") or "neutral",
         json.dumps(d.get("tags") or []), d.get("notes") or "",
         d.get("screenshot_url") or "", now_str()))
    conn.commit(); conn.close()
    return jsonify({"id": eid, "ok": True})


@app.route("/api/journal/<eid>", methods=["DELETE"])
@auth_required
def delete_journal(eid):
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM journal WHERE id=%s AND user_id=%s", (eid, g.user_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# PAPER TRADING
# ─────────────────────────────────────────────

def simulate_market_execution(side, price, quantity,
                               fee_percent=0.04, slippage_percent=0.02):
    fee_rate      = fee_percent    / 100
    slippage_rate = slippage_percent / 100
    fill_price    = price * (1 + slippage_rate) if side.upper() == "BUY" \
                    else price * (1 - slippage_rate)
    notional = fill_price * quantity
    return {
        "fill_price": fill_price, "quantity": quantity,
        "notional": notional, "fee": notional * fee_rate,
        "slippage_percent": slippage_percent, "fee_percent": fee_percent,
    }


def get_latest_price(symbol):
    market = detect_market(symbol)
    if market == "crypto":
        candles = fetch_binance_raw(symbol, "1m", 2)
    else:
        candles = fetch_polygon_candles(symbol, "5m", 2)
    if not candles:
        raise RuntimeError(f"Could not fetch latest price for {symbol}")
    return float(candles[-1][4])


AUTO_PAPER_TRADING = {}


@app.route("/api/paper/start", methods=["POST", "OPTIONS"])
@auth_required
def paper_start():
    data     = request.get_json(force=True) or {}
    symbol   = (data.get("symbol") or "BTCUSDT").upper()
    side     = (data.get("side")   or "BUY").upper()
    quantity = float(data.get("quantity") or 0.001)
    try:
        latest_price = get_latest_price(symbol)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    execution = simulate_market_execution(
        side, latest_price, quantity,
        float(data.get("fee_percent")       or 0.04),
        float(data.get("slippage_percent")  or 0.02),
    )
    trade_id = str(uuid.uuid4())
    conn = get_conn(); c = conn.cursor()
    c.execute(
        """INSERT INTO trades
           (id,user_id,symbol,type,entry,sl,tp,size,exit,pnl,status,time)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (trade_id, g.user_id, symbol, side, execution["fill_price"],
         0, 0, quantity, 0, 0, "OPEN", now_str()))
    conn.commit(); conn.close()
    return jsonify({
        "ok": True, "trade_id": trade_id, "symbol": symbol, "side": side,
        "latest_price": latest_price, "execution": execution,
    })


def update_open_trades():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT id, symbol, type, entry, size FROM trades WHERE status='OPEN'")
    for trade_id, symbol, side, entry, size in c.fetchall():
        try:
            price = get_latest_price(symbol)
            pnl   = (price - entry) * size if side == "BUY" else (entry - price) * size
            c.execute("UPDATE trades SET pnl=%s WHERE id=%s", (pnl, trade_id))
        except Exception as e:
            print(f"[update_open_trades] {symbol}: {e}")
    conn.commit(); conn.close()


@app.route("/api/paper/update", methods=["POST", "OPTIONS"])
@auth_required
def paper_update():
    update_open_trades()
    return jsonify({"ok": True})


@app.route("/api/paper/status", methods=["GET", "OPTIONS"])
@auth_required
def paper_status():
    return jsonify({"enabled": AUTO_PAPER_TRADING.get(g.user_id, False)})


@app.route("/api/paper/start-auto", methods=["POST", "OPTIONS"])
@auth_required
def paper_start_auto():
    AUTO_PAPER_TRADING[g.user_id] = True
    return jsonify({"ok": True, "enabled": True})


@app.route("/api/paper/stop-auto", methods=["POST", "OPTIONS"])
@auth_required
def paper_stop_auto():
    AUTO_PAPER_TRADING[g.user_id] = False
    return jsonify({"ok": True, "enabled": False})


# ─────────────────────────────────────────────
# PAPER TRADES CRUD
# ─────────────────────────────────────────────

@app.route("/api/trades", methods=["GET"])
@auth_required
def list_trades():
    conn = get_conn(); c = conn.cursor()
    c.execute(
        """SELECT id,symbol,type,entry,sl,tp,size,exit,pnl,status,time
           FROM trades WHERE user_id=%s ORDER BY time DESC LIMIT 200""",
        (g.user_id,))
    rows = c.fetchall(); conn.close()
    return jsonify([{
        "id": r[0], "symbol": r[1], "side": r[2], "entry": r[3],
        "sl": r[4], "tp": r[5], "size": r[6], "exit": r[7],
        "pnl": r[8], "status": r[9], "time": r[10],
    } for r in rows])


@app.route("/api/trades", methods=["POST"])
@auth_required
def open_paper_trade():
    d    = request.get_json(force=True) or {}
    sym  = (d.get("symbol") or "BTCUSDT").upper()
    side = d.get("side", "BUY").upper()
    df   = fetch_df_for_symbol(sym, SIGNALS_INTERVAL, 200)
    if df is None:
        return jsonify({"error": f"No market data for {sym}"}), 400
    cfg    = get_user_config()
    levels = calculate_trade_levels(df, side, cfg.get("risk_reward", 2))
    price  = float(df.iloc[-1]["close"])
    risk_amt   = cfg["starting_balance"] * (cfg["risk_percent"] / 100)
    stop_dist  = abs(price - levels["sl"])
    size = risk_amt / stop_dist if stop_dist else 0
    tid  = str(uuid.uuid4())
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "INSERT INTO trades VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,'OPEN',%s)",
        (tid, g.user_id, sym, side, price, levels["sl"], levels["tp"], size, now_str()))
    conn.commit(); conn.close()
    add_alert(g.user_id, f"OPEN {sym} {side} @ {format_price(price, sym)}")
    return jsonify({"ok": True, "id": tid, "entry": price,
                    "sl": levels["sl"], "tp": levels["tp"], "size": size})


@app.route("/api/trades/<tid>/close", methods=["POST"])
@auth_required
def close_paper_trade(tid):
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT symbol,type,entry,size FROM trades WHERE id=%s AND user_id=%s AND status='OPEN'",
        (tid, g.user_id))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Trade not found or already closed"}), 404
    sym, side, entry, size = row
    df    = fetch_df_for_symbol(sym, SIGNALS_INTERVAL, 5)
    price = float(df.iloc[-1]["close"]) if df is not None else float(entry)
    pnl   = (price - entry) * size if side == "BUY" else (entry - price) * size
    c.execute(
        "UPDATE trades SET exit=%s,pnl=%s,status='CLOSED',time=%s WHERE id=%s",
        (price, pnl, now_str(), tid))
    conn.commit(); conn.close()
    add_alert(g.user_id, f"CLOSED {sym} PnL {round(pnl, 4)}")
    return jsonify({"ok": True, "exit_price": price, "pnl": round(pnl, 4)})


@app.route("/api/alerts", methods=["GET"])
@auth_required
def get_alerts():
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT message,time FROM alerts WHERE user_id=%s ORDER BY time DESC LIMIT 50",
        (g.user_id,))
    rows = c.fetchall(); conn.close()
    return jsonify([{"message": r[0], "time": r[1]} for r in rows])


@app.route("/api/equity", methods=["GET"])
@auth_required
def equity():
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT pnl,time FROM trades WHERE user_id=%s AND status='CLOSED'",
        (g.user_id,))
    rows = c.fetchall(); conn.close()
    cfg  = get_user_config()
    bal  = cfg["starting_balance"]
    pts  = [{"time": "Start", "equity": round(bal, 2)}]
    for pnl, t in rows:
        bal += float(pnl or 0)
        pts.append({"time": t, "equity": round(bal, 2)})
    return jsonify(pts)


@app.route("/api/stats", methods=["GET"])
@auth_required
def stats():
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT pnl FROM trades WHERE user_id=%s AND status='CLOSED'",
        (g.user_id,))
    pnls   = [float(r[0] or 0) for r in c.fetchall()]
    conn.close()
    total  = len(pnls)
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    cfg    = get_user_config()
    return jsonify({
        "total_trades":     total,
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate":         round(len(wins) / total * 100, 2) if total else 0,
        "net_pnl":          round(sum(pnls), 2),
        "balance":          round(cfg["starting_balance"] + sum(pnls), 2),
        "starting_balance": cfg["starting_balance"],
    })

"""
AI Trading Engine — Flask backend
Routes are mounted under /api.

Fixes in this version
─────────────────────
[A] TwelveData candles: use 5m (not 1m) for signals — free tier supports it reliably.
[B] TwelveData range fetch: new fetch_twelvedata_range() picks a random historical
    window using the `start_date` / `end_date` query params supported by TwelveData.
[C] Backtester for non-crypto: retry up to 3 random date windows if one is thin.
[D] Backtester strategies:
      • run_simple_ma_strategy — fixed PnL scaling (use percentage return, not raw diff)
      • run_unified_bot_strategy — loosened entry conditions so it produces trades in
        short windows; added short-side entries; fixed fee formula for small prices.
[E] /api/signals: fetch with 5m interval → higher hit-rate on TwelveData free tier.
[F] Price display: always return both `price` (raw) and `price_display` (pre-formatted
    string) so the frontend can just show `price_display` without guessing decimals.
[G] /api/backtest: descriptive error messages at every failure point.
[H] Symbols endpoint now also returns market membership so the frontend can group them.
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
    "stocks":      ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN"],
    "commodities": ["XAUUSD", "XAGUSD", "USOIL", "UKOIL"],
}

ALL_SYMBOLS = (
    MARKETS["crypto"]
    + MARKETS["forex"]
    + MARKETS["stocks"]
    + MARKETS["commodities"]
)

# TwelveData symbol name map (their API uses different identifiers)
TD_SYMBOL_MAP = {
    "EURUSD": "EUR/USD",  "GBPUSD": "GBP/USD",  "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD",  "USDCAD": "USD/CAD",
    "XAUUSD": "XAU/USD",  "XAGUSD": "XAG/USD",
    "USOIL":  "WTI/USD",  "UKOIL":  "BRENT/USD",
    # stocks pass through as-is
}

# TwelveData interval map
TD_INTERVAL_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min",
    "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1day",
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
_non_crypto_cache    = {}   # separate long-lived cache for TwelveData responses
_summary_cache       = {}

# ── TwelveData rate-limiter ──────────────────────────────────────────────────
# Free plan: 8 credits/minute.  We enforce ≥10 s between outgoing TD requests
# so we never exceed 6/min even if signals and backtester fire simultaneously.
_td_lock            = __import__("threading").Lock()
_td_last_call_time  = 0.0
TD_MIN_INTERVAL_SEC = 10.0        # seconds between TwelveData HTTP calls


def _td_rate_limited_get(params, timeout=25):
    """Call TwelveData time_series, blocking until the rate-limit gap has passed."""
    global _td_last_call_time
    with _td_lock:
        now     = time.time()
        elapsed = now - _td_last_call_time
        if elapsed < TD_MIN_INTERVAL_SEC:
            time.sleep(TD_MIN_INTERVAL_SEC - elapsed)
        _td_last_call_time = time.time()
    r = requests.get("https://api.twelvedata.com/time_series",
                     params=params, timeout=timeout)
    return r

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
# TWELVEDATA (FOREX / STOCKS / COMMODITIES)
# ─────────────────────────────────────────────

def _td_symbol(symbol):
    return TD_SYMBOL_MAP.get(symbol, symbol)


def fetch_twelvedata_candles(symbol, interval, limit=200,
                              start_date=None, end_date=None):
    """
    [B] Fetch candles from TwelveData with rate-limiting + long-lived caching.

    Rate limit (free plan): 8 credits/minute.
    We enforce ≥8 s between outgoing calls via _td_rate_limited_get().
    Results are cached for NON_CRYPTO_CANDLE_TTL (5 min) so repeated
    signals refreshes don't cost extra credits.
    """
    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "TWELVEDATA_API_KEY env variable is not set. "
            "Add it to your Render environment variables."
        )

    td_interval = TD_INTERVAL_MAP.get(interval)
    if not td_interval:
        raise RuntimeError(
            f"TwelveData does not support interval '{interval}'. "
            f"Supported: {list(TD_INTERVAL_MAP.keys())}"
        )

    td_sym = _td_symbol(symbol)

    # Cache key includes date range so backtest windows don't collide with signal fetches
    nc_key = (symbol, interval, limit, start_date, end_date)
    cached = _cache_get(_non_crypto_cache, nc_key, NON_CRYPTO_CANDLE_TTL)
    if cached is not None:
        return cached

    params = {
        "symbol":     td_sym,
        "interval":   td_interval,
        "outputsize": min(limit, 5000),
        "apikey":     api_key,
        "format":     "JSON",
    }
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    try:
        r    = _td_rate_limited_get(params, timeout=25)
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"TwelveData network error for {symbol}: {e}")

    if "values" not in data:
        code    = data.get("code", "?")
        message = data.get("message", str(data)[:300])
        if str(code) == "429":
            raise RuntimeError(
                f"TwelveData rate limit hit for {symbol}. "
                f"The free plan allows 8 API credits/minute. "
                f"Wait ~60 seconds and try again, or upgrade your TwelveData plan."
            )
        raise RuntimeError(
            f"TwelveData API error for {symbol} ({td_sym}) [{code}]: {message}"
        )

    values = data["values"]
    if not values:
        raise RuntimeError(
            f"TwelveData returned 0 candles for {symbol} "
            f"(interval={interval}, start={start_date}, end={end_date})"
        )

    candles = []
    for item in reversed(values):          # TwelveData returns newest-first
        try:
            ts = int(datetime.fromisoformat(item["datetime"]).timestamp() * 1000)
        except Exception:
            continue
        candles.append([
            ts,
            item["open"],
            item["high"],
            item["low"],
            item["close"],
            item.get("volume", 0),
        ])

    _cache_set(_non_crypto_cache, nc_key, candles)
    return candles


# ─────────────────────────────────────────────
# [B] TWELVEDATA RANDOM RANGE FETCH
# ─────────────────────────────────────────────

def _random_date_window(market, period_days):
    """Return (start_date_str, end_date_str) for a random historical window."""
    earliest   = MARKET_EARLIEST[market]
    # leave 1 day buffer so we never ask for the future
    latest_end = datetime.now(timezone.utc) - timedelta(days=1)
    latest_start = latest_end - timedelta(days=period_days)
    if latest_start <= earliest:
        start_dt = earliest
    else:
        span_seconds = int((latest_start - earliest).total_seconds())
        offset       = random.randint(0, span_seconds)
        start_dt     = earliest + timedelta(seconds=offset)
    end_dt = start_dt + timedelta(days=period_days)
    if end_dt > latest_end:
        end_dt   = latest_end
        start_dt = max(earliest, end_dt - timedelta(days=period_days))
    return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")


def fetch_twelvedata_for_backtest(symbol, interval, period_days,
                                  random_window=True, max_attempts=2):
    """
    [C] Fetch non-crypto candles for backtesting.

    Key change vs previous version:
    • max_attempts defaulted to 2 (not 3) — each attempt costs ~8 s due to
      the rate-limiter, so 2 attempts = max 16 s latency.
    • Rate-limit errors (429) are NOT retried — they propagate immediately with
      a clear message telling the user to wait 60 s.
    • Only "thin data" (< 60 candles returned) triggers a second attempt with a
      different random window.
    """
    market = detect_market(symbol)
    errors = []

    # Upgrade 1m → 5m for non-crypto (TwelveData free plan caps 1m at 800 rows)
    safe_interval = interval
    if interval == "1m" and market != "crypto":
        safe_interval = "5m"

    iv_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30,
                  "1h": 60, "4h": 240, "1d": 1440}.get(safe_interval, 5)
    limit = min(5000, (period_days * 24 * 60) // iv_minutes + 10)

    for attempt in range(1, max_attempts + 1):
        if random_window:
            start_date, end_date = _random_date_window(market, period_days)
        else:
            end_dt     = datetime.now(timezone.utc) - timedelta(days=1)
            start_dt   = end_dt - timedelta(days=period_days)
            start_date = start_dt.strftime("%Y-%m-%d")
            end_date   = end_dt.strftime("%Y-%m-%d")

        try:
            candles = fetch_twelvedata_candles(
                symbol, safe_interval,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            )
            if candles and len(candles) >= 60:
                return candles, safe_interval, start_date, end_date
            errors.append(
                f"Attempt {attempt} ({start_date}→{end_date}): "
                f"only {len(candles)} candles returned (need ≥60)"
            )
        except RuntimeError as e:
            msg = str(e)
            errors.append(f"Attempt {attempt} ({start_date}→{end_date}): {msg}")
            # Don't retry rate-limit errors — just surface them immediately
            if "rate limit" in msg.lower() or "429" in msg:
                raise RuntimeError(
                    f"TwelveData rate limit hit.\n"
                    f"The free plan allows only 8 API credits per minute.\n"
                    f"Please wait ~60 seconds then try again.\n\n"
                    f"To fix permanently: upgrade your TwelveData plan at "
                    f"https://twelvedata.com/pricing, or reduce how often the "
                    f"signals page refreshes."
                )

    raise RuntimeError(
        f"Could not fetch enough candles for {symbol} after {max_attempts} attempt(s).\n"
        + "\n".join(errors)
    )


# ─────────────────────────────────────────────
# UNIVERSAL CANDLE FETCHERS
# ─────────────────────────────────────────────

def fetch_candles_for_symbol(symbol, interval="5m", limit=200):
    """Route to the right data source by market type."""
    market = detect_market(symbol)
    if market == "crypto":
        return fetch_binance_raw(symbol, interval, limit)
    candles = fetch_twelvedata_candles(symbol, interval, limit)
    if not candles:
        raise RuntimeError(f"No TwelveData candles returned for {symbol}")
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

    # [A] Use 5m for signals — much more reliable on TwelveData free tier
    fetch_iv = SIGNALS_INTERVAL
    df = fetch_df_for_symbol(symbol, fetch_iv, 200)
    if df is None:
        return None

    higher_df = fetch_df_for_symbol(symbol, get_higher_timeframe(fetch_iv), 100)
    ev        = evaluate_bot_window(df, strategy, symbol, fetch_iv, higher_df, cfg)

    prev  = float(df.iloc[-2]["close"]) if len(df) > 1 else float(df.iloc[-1]["close"])
    last  = float(df.iloc[-1]["close"])
    chg   = ((last - prev) / prev * 100) if prev else 0
    levels = calculate_trade_levels(df, ev["signal"], cfg.get("risk_reward", 2))

    return _cache_set(_summary_cache, cache_key, {
        "symbol":          symbol,
        "market":          detect_market(symbol),
        # [F] both raw and display-ready price
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

    # ── Constants ─────────────────────────────────────────────────────────
    RISK_PER_TRADE   = 0.01    # 1 % of starting_balance risked per trade
    REWARD_RISK      = 2.5     # TP = 2.5 × SL distance
    SL_ATR_MULT      = 1.5     # SL = entry ± SL_ATR_MULT × ATR
    TRAIL_ATR_MULT   = 1.0     # trailing stop trails 1 × ATR behind peak
    TRAIL_TRIGGER_R  = 1.0     # activate trail once +1 R profit booked
    COOLDOWN_BARS    = 3       # bars to pause after any exit
    ADX_MIN          = 22      # only trade in trending markets
    RSI_BUY_LO       = 45
    RSI_BUY_HI       = 68
    RSI_SELL_LO      = 32
    RSI_SELL_HI      = 55
    ATR_PERIOD       = 14
    RSI_PERIOD       = 14
    ADX_PERIOD       = 14
    WARMUP           = 55
    # Notional cap: never put more than 20% of balance into one position.
    # This bounds leverage regardless of price scale.
    # e.g. $100k balance → max notional $20k → max 0.22 BTC at $90k.
    # With fee=0.04% each side: fee = $20k * 0.0008 = $16 (1.6% of $1k risk) ✓
    MAX_NOTIONAL_FRACTION = 0.20   # 20% of starting_balance per trade

    trades       = []
    balance      = float(starting_balance)
    risk_dollar  = starting_balance * RISK_PER_TRADE  # fixed for entire run
    max_notional = starting_balance * MAX_NOTIONAL_FRACTION
    fee_rate     = fee_pct    / 100
    slip_rate    = slippage_pct / 100
    position     = None
    cooldown     = 0

    if len(candles) < WARMUP + 10:
        return trades, balance

    closes = [float(c[4]) for c in candles]
    highs  = [float(c[2]) for c in candles]
    lows   = [float(c[3]) for c in candles]

    ema9  = _ema_series(closes, 9)
    ema21 = _ema_series(closes, 21)
    ema50 = _ema_series(closes, 50)
    atr   = _atr_series(highs, lows, closes, ATR_PERIOD)
    rsi   = _rsi_series(closes, RSI_PERIOD)
    adx   = _adx_series(highs, lows, closes, ADX_PERIOD)

    for i in range(WARMUP, len(candles)):

        e9    = ema9[i]
        e21   = ema21[i]
        e50   = ema50[i]
        atr_v = atr[i]
        rsi_v = rsi[i]
        adx_v = adx[i]

        if any(v is None for v in [e9, e21, e50, atr_v, rsi_v, adx_v]):
            continue
        if atr_v <= 0:
            continue

        close = closes[i]
        hi    = highs[i]
        lo    = lows[i]
        t_str = _ts_to_str(candles[i][0])

        bull_stack = e9 > e21 > e50
        bear_stack = e9 < e21 < e50
        trending   = adx_v >= ADX_MIN

        # ── Manage open position ──────────────────────────────────────────
        if position is not None:
            side      = position["side"]
            ep        = position["entry"]
            sl        = position["sl"]
            tp        = position["tp"]
            r_dist    = position["r_dist"]
            trail_act = position["trail_active"]
            trail_sl  = position["trail_sl"]
            peak      = position["peak"]

            if side == "BUY":
                if hi > peak:
                    peak = hi
                    position["peak"] = peak
            else:
                if lo < peak:
                    peak = lo
                    position["peak"] = peak

            exit_price  = None
            exit_reason = None

            if side == "BUY":
                if not trail_act and peak >= ep + r_dist * TRAIL_TRIGGER_R:
                    trail_act = True
                    trail_sl  = peak - atr_v * TRAIL_ATR_MULT
                    position["trail_active"] = True
                    position["trail_sl"]     = trail_sl

                if trail_act:
                    candidate = peak - atr_v * TRAIL_ATR_MULT
                    if candidate > trail_sl:
                        trail_sl = candidate
                        position["trail_sl"] = trail_sl
                    eff_sl = trail_sl
                else:
                    eff_sl = sl

                if lo <= eff_sl:
                    exit_price  = eff_sl
                    exit_reason = "Trailing stop" if trail_act else "Stop loss"
                elif hi >= tp:
                    exit_price, exit_reason = tp, "Take profit"
                elif not trail_act and not bull_stack:
                    exit_price, exit_reason = close, "Trend break"

            else:  # SELL
                if not trail_act and peak <= ep - r_dist * TRAIL_TRIGGER_R:
                    trail_act = True
                    trail_sl  = peak + atr_v * TRAIL_ATR_MULT
                    position["trail_active"] = True
                    position["trail_sl"]     = trail_sl

                if trail_act:
                    candidate = peak + atr_v * TRAIL_ATR_MULT
                    if candidate < trail_sl:
                        trail_sl = candidate
                        position["trail_sl"] = trail_sl
                    eff_sl = trail_sl
                else:
                    eff_sl = sl

                if hi >= eff_sl:
                    exit_price  = eff_sl
                    exit_reason = "Trailing stop" if trail_act else "Stop loss"
                elif lo <= tp:
                    exit_price, exit_reason = tp, "Take profit"
                elif not trail_act and not bear_stack:
                    exit_price, exit_reason = close, "Trend break"

            if exit_price is not None:
                sz       = position["size"]
                notional = ep * sz
                fee      = notional * fee_rate * 2
                raw_pnl  = ((exit_price - ep) if side == "BUY"
                            else (ep - exit_price)) * sz
                net_pnl  = raw_pnl - fee
                balance += net_pnl
                trades.append({
                    "side":       side,
                    "entry":      round(ep,         6),
                    "exit":       round(exit_price, 6),
                    "sl":         round(sl,          6),
                    "tp":         round(tp,          6),
                    "size":       round(sz,          6),
                    "r_dist":     round(r_dist,      6),
                    "entry_time": position["time"],
                    "exit_time":  t_str,
                    "pnl":        round(net_pnl, 4),
                    "reason":     exit_reason,
                    "trail_used": trail_act,
                })
                position = None
                cooldown = COOLDOWN_BARS

            continue

        # ── Cooldown ──────────────────────────────────────────────────────
        if cooldown > 0:
            cooldown -= 1
            continue

        # ── Entry ─────────────────────────────────────────────────────────
        if not trending:
            continue

        if bull_stack and RSI_BUY_LO <= rsi_v <= RSI_BUY_HI:
            sl_dist  = atr_v * SL_ATR_MULT
            ep       = close * (1 + slip_rate)
            sl_price = ep - sl_dist
            tp_price = ep + sl_dist * REWARD_RISK
            # Size: risk 1% of starting balance, but cap notional at MAX_NOTIONAL_MULT×
            raw_size   = risk_dollar / sl_dist if sl_dist > 0 else 0
            capped_size = min(raw_size, max_notional / ep) if ep > 0 else raw_size
            if capped_size > 0:
                # Recalculate actual risk after capping (may be less than 1%)
                actual_risk = capped_size * sl_dist
                position = {
                    "side": "BUY",  "entry": ep,        "time": t_str,
                    "sl":   sl_price, "tp":  tp_price,
                    "r_dist": actual_risk, "size": capped_size,
                    "trail_active": False, "trail_sl": sl_price,
                    "peak": ep,
                }

        elif bear_stack and RSI_SELL_LO <= rsi_v <= RSI_SELL_HI:
            sl_dist  = atr_v * SL_ATR_MULT
            ep       = close * (1 - slip_rate)
            sl_price = ep + sl_dist
            tp_price = ep - sl_dist * REWARD_RISK
            raw_size    = risk_dollar / sl_dist if sl_dist > 0 else 0
            capped_size = min(raw_size, max_notional / ep) if ep > 0 else raw_size
            if capped_size > 0:
                actual_risk = capped_size * sl_dist
                position = {
                    "side": "SELL", "entry": ep,        "time": t_str,
                    "sl":   sl_price, "tp":  tp_price,
                    "r_dist": actual_risk, "size": capped_size,
                    "trail_active": False, "trail_sl": sl_price,
                    "peak": ep,
                }

    return trades, balance


# ─────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────

@app.route("/api/health")
def health():
    td_key = os.environ.get("TWELVEDATA_API_KEY", "")
    return jsonify({
        "ok":               True,
        "time":             now_str(),
        "twelvedata_key":   bool(td_key),
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
    • Non-crypto: TwelveData range fetch with up to 3 random window attempts.
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
            # Non-crypto: TwelveData with retry
            candles, actual_interval, start_date, end_date = \
                fetch_twelvedata_for_backtest(
                    symbol, interval, period_days,
                    random_window=rand_window, max_attempts=3
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
        candles = fetch_twelvedata_candles(symbol, "5m", 2)
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

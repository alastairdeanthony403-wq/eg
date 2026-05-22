# BOT VERSION: 2.0 — Self-Learning SMC Engine
# Improvements: ATR SL, weighted confidence, ADX filter,
# extended FVG, trailing stops, dynamic SMC threshold,
# session learning, self-adjusting config from trade history

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
[v2] ATR-based SL, weighted confidence, ADX gate, extended FVG lookback,
     trailing stops in daily backtest path, dynamic SMC threshold,
     extended session blocking, self-learning system.
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
    "crypto": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
        "XRPUSDT", "ADAUSDT", "AVAXUSDT", "DOGEUSDT",
        "DOTUSDT", "LINKUSDT", "LTCUSDT", "UNIUSDT",
        "ATOMUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT",
    ],
    "forex": [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
        "NZDUSD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY",
        "AUDCAD", "AUDJPY", "CADJPY", "CHFJPY",
    ],
    "stocks": [
        "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "SPY",
        "GOOGL", "META", "NFLX", "AMD", "QQQ",
        "JPM", "BAC", "V", "MA",
    ],
    "commodities": ["XAUUSD", "XAGUSD", "USOIL", "UKOIL", "NATGAS", "COPPER"],
}

ALL_SYMBOLS = (
    MARKETS["crypto"]
    + MARKETS["forex"]
    + MARKETS["stocks"]
    + MARKETS["commodities"]
)

POLYGON_SYMBOL_MAP = {
    # Forex
    "EURUSD": "C:EURUSD", "GBPUSD": "C:GBPUSD", "USDJPY": "C:USDJPY",
    "AUDUSD": "C:AUDUSD", "USDCAD": "C:USDCAD", "NZDUSD": "C:NZDUSD",
    "USDCHF": "C:USDCHF", "EURGBP": "C:EURGBP", "EURJPY": "C:EURJPY",
    "GBPJPY": "C:GBPJPY", "AUDCAD": "C:AUDCAD", "AUDJPY": "C:AUDJPY",
    "CADJPY": "C:CADJPY", "CHFJPY": "C:CHFJPY",
    # Commodities
    "XAUUSD": "C:XAUUSD", "XAGUSD": "C:XAGUSD",
    "USOIL":  "USO",      "UKOIL":  "BNO",
    "NATGAS": "UNG",      "COPPER": "COPX",
    # Stocks & ETFs
    "AAPL": "AAPL", "TSLA": "TSLA", "NVDA": "NVDA",
    "MSFT": "MSFT", "AMZN": "AMZN", "SPY":  "SPY",
    "GOOGL": "GOOGL", "META": "META", "NFLX": "NFLX",
    "AMD":   "AMD",   "QQQ":  "QQQ",
    "JPM":   "JPM",   "BAC":  "BAC",
    "V":     "V",     "MA":   "MA",
}

POLYGON_INTERVAL_MAP = {
    "1m":  (1,  "minute"),
    "5m":  (5,  "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "1h":  (1,  "hour"),
    "4h":  (4,  "hour"),
    "1d":  (1,  "day"),
}

_POLYGON_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}

SIGNALS_INTERVAL = "5m"

MARKET_EARLIEST = {
    "crypto":      datetime(2020, 1, 1, tzinfo=timezone.utc),
    "forex":       datetime(2018, 1, 1, tzinfo=timezone.utc),
    "stocks":      datetime(2018, 1, 1, tzinfo=timezone.utc),
    "commodities": datetime(2018, 1, 1, tzinfo=timezone.utc),
}

# ── Section 9: extended session blocking ──────────────────────────────────
DEFAULT_CONFIG = {
    "symbols":                  ALL_SYMBOLS,
    "risk_reward":              2,
    "risk_percent":             1,
    "min_confidence":           70,
    "starting_balance":         10000,
    "max_trades_per_day":       5,
    "max_daily_loss_percent":   3,
    "max_consecutive_losses":   2,
    "avoid_quiet_market":       True,
    "avoid_sideways_market":    True,
    "min_volume_multiplier":    0.8,
    "min_smc_score":            7,
    "blocked_crypto_hours_utc": [0, 1, 2, 3, 22, 23],   # extended late-night dead zones
    "blocked_sessions":         [],                       # e.g. ["Asia"] — populated by learning
    "atr_multiplier":                1.5,   # v2: ATR stop distance multiplier
    "enable_trailing_stop":          True,  # v2: trailing stop in backtester
    "enable_fallback_strategy":      True,  # v2: allow EMA fallback when SMC fails
    "trading_mode":                  "local_paper",
    # ── Risk / reward ─────────────────────────────────────────────────────
    "min_rr_ratio":                  3.0,   # minimum R:R — every trade ≥ 1:3
    "max_sl_pct":                    2.0,   # reject trade if SL > 2% of entry price
    # ── Weekly goals ──────────────────────────────────────────────────────
    "weekly_win_goal":               3,     # stop new trades after N wins this week
    "weekly_profit_target_percent":  3.0,   # stop new trades after +3% weekly profit
    "weekly_max_loss_percent":       0.8,   # stop new trades after -0.8% weekly loss
}

JWT_SECRET      = os.environ.get("JWT_SECRET", "ai-trading-engine-secret-change-me")
JWT_ALGO        = "HS256"
JWT_EXPIRY_DAYS = 30   # was 7 — tokens were expiring too quickly

MARKET_DATA_TTL_SECONDS  = 30
SUMMARY_TTL_SECONDS      = 90
NON_CRYPTO_CANDLE_TTL    = 600

_raw_candle_cache    = {}
_non_crypto_cache    = {}
_summary_cache       = {}

_polygon_lock         = __import__("threading").Lock()
_polygon_last_call_ts = 0.0
POLYGON_RATE_LIMIT_SECS = float(os.environ.get("POLYGON_RATE_LIMIT_SECS", "12"))


def _polygon_get(url, params, timeout=25):
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
    # ── Section 1A: self-learning log ─────────────────────────────────
    c.execute("""CREATE TABLE IF NOT EXISTS bot_learning_log (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        symbol TEXT,
        interval TEXT,
        strategy TEXT,
        analysis_json TEXT,
        adjustments_json TEXT,
        before_config TEXT,
        after_config TEXT,
        trades_analyzed INTEGER,
        win_rate_before FLOAT,
        win_rate_after FLOAT
    )""")
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


@app.route("/api/auth/refresh", methods=["POST", "GET"])
@auth_required
def refresh_token():
    """Issue a fresh JWT token for an already-authenticated user."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT id, email, name FROM users WHERE id=%s", (g.user_id,))
    row = c.fetchone(); conn.close()
    if not row:
        return jsonify({"error": "User not found"}), 404
    new_token = make_token(row[0], row[1])
    return jsonify({
        "token": new_token,
        "user": {"id": row[0], "email": row[1], "name": row[2]},
    })


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
    return [[int(r[0]) * 1000, str(r[3]), str(r[2]), str(r[1]),
             str(r[4]), str(r[5])] for r in rows]


def fetch_binance_raw(symbol="BTCUSDT", interval="5m", limit=500):
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


# Interval → milliseconds map for pagination
_INTERVAL_MS = {
    "1m":  60_000,   "3m":  180_000,  "5m":   300_000,
    "15m": 900_000,  "30m": 1_800_000,"1h":  3_600_000,
    "4h":  14_400_000,"1d": 86_400_000,
}

def fetch_binance_range_paginated(symbol, interval, start_ms, end_ms, max_candles=10000):
    """
    Fetch ALL candles in [start_ms, end_ms] for a crypto symbol, making
    multiple Binance API calls (1000 per page) as needed.
    Binance hard-limits each request to 1000 candles, so 30 days of 5m data
    (8640 candles) requires ~9 sequential requests.
    """
    iv_ms       = _INTERVAL_MS.get(interval, 300_000)
    all_candles = []
    cur_start   = int(start_ms)
    end_ms      = int(end_ms)

    while cur_start < end_ms and len(all_candles) < max_candles:
        chunk = fetch_binance_range(symbol, interval, cur_start, end_ms, 1000)
        if not chunk:
            break
        all_candles.extend(chunk)
        if len(chunk) < 1000:
            break   # received fewer than a full page → no more data
        # Advance start to just after the last received candle
        cur_start = int(chunk[-1][0]) + iv_ms

    # Deduplicate by open-timestamp (safety net) and trim to max
    seen, deduped = set(), []
    for c in all_candles:
        ts = int(c[0])
        if ts not in seen:
            seen.add(ts); deduped.append(c)
    return deduped[:max_candles]


# ─────────────────────────────────────────────
# POLYGON.IO (FOREX / STOCKS / COMMODITIES)
# ─────────────────────────────────────────────

def fetch_polygon_candles(symbol, interval, limit=200):
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "POLYGON_API_KEY is not set. "
            "Add it to your Render environment variables."
        )
    interval_cfg = POLYGON_INTERVAL_MAP.get(interval)
    if not interval_cfg:
        if interval == "1m":
            interval_cfg = POLYGON_INTERVAL_MAP["5m"]
        else:
            raise RuntimeError(
                f"Polygon does not support interval '{interval}'. "
                f"Supported: {list(POLYGON_INTERVAL_MAP.keys())}"
            )
    multiplier, timespan = interval_cfg
    ticker = POLYGON_SYMBOL_MAP.get(symbol, symbol)
    nc_key = (symbol, interval, limit)
    cached = _cache_get(_non_crypto_cache, nc_key, NON_CRYPTO_CANDLE_TTL)
    if cached is not None:
        return cached
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
        "limit":    min(limit * 3, 50000),
        "apiKey":   api_key,
    }
    try:
        r    = _polygon_get(url, params, timeout=25)
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Polygon network error for {symbol} ({ticker}): {e}")
    status = data.get("status", "")
    if status in ("ERROR", "NOT_AUTHORIZED"):
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

_backtest_daily_cache = {}
BACKTEST_DAILY_TTL    = 1800


def fetch_non_crypto_backtest_candles(symbol, period_days, random_window=False):
    cached = _cache_get(_backtest_daily_cache, symbol, BACKTEST_DAILY_TTL)
    if cached is None:
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
    WARMUP_BARS = 250   # increased: EMA200 needs 200 bars to initialize

    if random_window and len(all_candles) > period_days + WARMUP_BARS + 5:
        max_start  = len(all_candles) - period_days - 1
        trade_start = random.randint(WARMUP_BARS, max_start)
    else:
        trade_start = max(WARMUP_BARS, len(all_candles) - period_days)

    trade_end   = min(trade_start + period_days, len(all_candles))
    fetch_start = max(0, trade_start - WARMUP_BARS)
    window      = all_candles[fetch_start:trade_end]

    if len(window) < 5:
        raise RuntimeError(
            f"Not enough daily candles for {symbol} "
            f"(got {len(window)}). The symbol may not be available on your Polygon plan."
        )

    def ms_to_date(ts):
        return datetime.utcfromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")

    start_date = ms_to_date(all_candles[trade_start][0])
    end_date   = ms_to_date(all_candles[trade_end - 1][0])

    return window, "1d", start_date, end_date


# ─────────────────────────────────────────────
# UNIVERSAL CANDLE FETCHERS
# ─────────────────────────────────────────────

def fetch_candles_for_symbol(symbol, interval="5m", limit=200):
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
    """
    6-state regime classifier using ADX, EMA slope, and volatility ratio.
    States: Strong Bull | Strong Bear | Trending Bull | Trending Bear |
            High Volatility | Active | Range / Quiet | Unknown
    """
    if df is None or len(df) < 50:
        return "Unknown"
    try:
        closes   = df["close"]
        highs_l  = df["high"].tolist()
        lows_l   = df["low"].tolist()
        closes_l = closes.tolist()

        # ATR-based volatility ratio vs 50-bar history
        atr_s     = _atr_series(highs_l, lows_l, closes_l, 14)
        valid_atr = [v for v in atr_s if v is not None]
        if len(valid_atr) >= 20:
            cur_atr   = valid_atr[-1]
            hist_avg  = sum(valid_atr[-50:]) / len(valid_atr[-50:])
            vol_ratio = cur_atr / hist_avg if hist_avg > 0 else 1.0
        else:
            vol_ratio = 1.0

        # EMA slope for direction
        ema20    = closes.ewm(span=20, adjust=False).mean()
        ema50    = closes.ewm(span=50, adjust=False).mean()
        e20_now  = float(ema20.iloc[-1])
        e20_prev = float(ema20.iloc[-5])
        e50_now  = float(ema50.iloc[-1])
        going_up = e20_now > e50_now and e20_now > e20_prev
        going_dn = e20_now < e50_now and e20_now < e20_prev

        adx = calculate_adx(df)

        if vol_ratio > 2.0:
            return "High Volatility"        # turbulence — gate everything
        if adx >= 30:
            if going_up: return "Strong Bull"
            if going_dn: return "Strong Bear"
            return "Trending"
        if adx >= 20:
            if going_up: return "Trending Bull"
            if going_dn: return "Trending Bear"
            return "Active"
        return "Range / Quiet"
    except Exception:
        return "Unknown"


# ── Section 2: ATR calculation (pandas-based) ─────────────────────────────
def calculate_atr(df, period=14):
    high       = df["high"]
    low        = df["low"]
    close      = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


# ── Section 4: ADX calculation (pandas-based) ─────────────────────────────
def calculate_adx(df, period=14):
    high     = df["high"]
    low      = df["low"]
    close    = df["close"]
    plus_dm  = high.diff().clip(lower=0)
    minus_dm = low.diff().multiply(-1).clip(lower=0)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr14    = tr.ewm(span=period, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr14
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr14
    denom    = (plus_di + minus_di).replace(0, float("nan"))
    dx       = 100 * (plus_di - minus_di).abs() / denom
    adx_val  = dx.ewm(span=period, adjust=False).mean().iloc[-1]
    return round(float(adx_val) if pd.notna(adx_val) else 25.0, 2)


# ── Section 3: weighted confidence model ──────────────────────────────────
def estimate_confidence(df, signal, smc_checks_passed=0, total_checks=9):
    if df is None or len(df) < 20:
        return 50
    score = 50  # base

    # SMC alignment (0-20 points)
    score += (smc_checks_passed / total_checks) * 20

    # Volume confirmation (0-10 points)
    try:
        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        cur_vol = df["volume"].iloc[-1]
        if pd.notna(avg_vol) and avg_vol > 0:
            if cur_vol > avg_vol * 1.5:
                score += 10
            elif cur_vol > avg_vol:
                score += 5
    except Exception:
        pass

    # ATR regime filter (0-10 points) — reward trending volatility
    try:
        atr     = calculate_atr(df)
        atr_avg = df["close"].pct_change().rolling(14).std().iloc[-1] * df["close"].iloc[-1]
        if pd.notna(atr_avg) and atr > atr_avg:
            score += 10
    except Exception:
        pass

    # Candle body strength (0-10 points)
    try:
        candle     = df.iloc[-1]
        body       = abs(candle["close"] - candle["open"])
        full_range = candle["high"] - candle["low"]
        if full_range > 0 and (body / full_range) > 0.6:
            score += 10
    except Exception:
        pass

    # Trend alignment bonus/penalty (±10 points)
    try:
        ema9  = df["close"].ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21 = df["close"].ewm(span=21, adjust=False).mean().iloc[-1]
        ema50 = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        if signal == "BUY" and ema9 > ema21 > ema50:
            score += 10
        elif signal == "SELL" and ema9 < ema21 < ema50:
            score += 10
        elif (signal == "BUY" and ema9 < ema50) or (signal == "SELL" and ema9 > ema50):
            score -= 10
    except Exception:
        pass

    return max(35, min(97, round(score)))


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


def _find_swing_pivots(df, lookback=50, pivot_bars=3):
    """
    Return (last_swing_high, last_swing_low) — the most recent confirmed
    pivot high and pivot low in the prior `lookback` bars (current bar excluded).

    A pivot high requires all `pivot_bars` bars on EACH side to have a
    strictly lower high.  A pivot low requires all `pivot_bars` bars on
    each side to have a strictly higher low.  Scans newest-first so we
    always return the most recent confirmed pivots.
    """
    if df is None or len(df) < pivot_bars * 2 + 3:
        return None, None

    end   = len(df) - 1                        # exclude current bar
    start = max(0, end - lookback)
    window = df.iloc[start:end].reset_index(drop=True)
    n = len(window)

    last_sh = last_sl = None

    for i in range(n - pivot_bars - 1, pivot_bars - 1, -1):
        h = float(window.iloc[i]["high"])
        l = float(window.iloc[i]["low"])

        if last_sh is None:
            left_h  = window["high"].iloc[i - pivot_bars : i]
            right_h = window["high"].iloc[i + 1 : i + pivot_bars + 1]
            if (left_h < h).all() and (right_h < h).all():
                last_sh = h

        if last_sl is None:
            left_l  = window["low"].iloc[i - pivot_bars : i]
            right_l = window["low"].iloc[i + 1 : i + pivot_bars + 1]
            if (left_l > l).all() and (right_l > l).all():
                last_sl = l

        if last_sh is not None and last_sl is not None:
            break

    return last_sh, last_sl


def detect_break_of_structure(df):
    """
    Bullish BOS: current close breaks above the most recent confirmed
    swing-high pivot (3-bar confirmation, 50-bar lookback).
    Bearish BOS: current close breaks below the most recent confirmed
    swing-low pivot.

    Unlike a simple range-max check this won't fire every bar in a
    trending market — it requires a genuine structural level to be broken.
    """
    if df is None or len(df) < 20:
        return None

    swing_high, swing_low = _find_swing_pivots(df, lookback=50, pivot_bars=3)
    close = float(df.iloc[-1]["close"])

    if swing_high is not None and close > swing_high:
        return "BULLISH_BOS"
    if swing_low  is not None and close < swing_low:
        return "BEARISH_BOS"
    return None


def price_in_discount_zone(df):
    """Price ≤ 38.2% Fibonacci level of the 30-bar range (true discount territory)."""
    if df is None or len(df) < 30:
        return False
    rh  = df["high"].tail(30).max()
    rl  = df["low"].tail(30).min()
    rng = rh - rl
    if rng <= 0:
        return False
    return df.iloc[-1]["close"] <= rl + rng * 0.382


def price_in_premium_zone(df):
    """Price ≥ 61.8% Fibonacci level of the 30-bar range (true premium territory)."""
    if df is None or len(df) < 30:
        return False
    rh  = df["high"].tail(30).max()
    rl  = df["low"].tail(30).min()
    rng = rh - rl
    if rng <= 0:
        return False
    return df.iloc[-1]["close"] >= rl + rng * 0.618


# ── Section 5: extended FVG lookback with interval param ──────────────────
def detect_fvg_retrace(df, direction, interval="5m"):
    if df is None or len(df) < 10:
        return False
    lookback = 30 if interval in ["5m", "15m"] else 15
    c   = df.tail(lookback).reset_index(drop=True)
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


# ── Section 9: session blocking with blocked_sessions support ─────────────
def session_allowed(cfg):
    now = datetime.utcnow()
    # Support both key names for backward compatibility with saved user configs
    blocked_hours = (
        cfg.get("blocked_hours_utc")
        or cfg.get("blocked_crypto_hours_utc", [])
    )
    if now.hour in blocked_hours:
        return False
    session = get_session_name(now)
    if session in cfg.get("blocked_sessions", []):
        return False
    return True


# ── Section 2: Structure-based SL with minimum 1:3 R:R enforcement ────────
def calculate_trade_levels(df, signal, rr=None, atr_multiplier=1.5, cfg=None):
    """
    Compute entry / SL / TP for a signal.

    Stop Loss  — placed just beyond the most recent swing pivot (2-bar
                 confirmation, 30-bar lookback), with a 0.3 ATR buffer.
                 Falls back to ATR × atr_multiplier when no pivot is found.

    Take Profit — entry ± SL_dist × rr  (minimum rr = cfg["min_rr_ratio"])

    Rejection   — rr_valid=False when SL distance > cfg["max_sl_pct"]% of price.

    Returns a dict with: entry, sl, tp, sl_distance, tp_distance, sl_pct,
                         rr, rr_valid, rejection_reason
    """
    cfg       = cfg or DEFAULT_CONFIG
    min_rr    = float(cfg.get("min_rr_ratio", 3.0))
    max_sl_pct = float(cfg.get("max_sl_pct", 2.0))
    # Honour the caller's rr but never go below the configured minimum
    if rr is None:
        rr = min_rr
    else:
        rr = max(float(rr), min_rr)

    lc = float(df.iloc[-1]["close"])
    try:
        atr = calculate_atr(df)
    except Exception:
        atr = lc * 0.005

    # Structure-based SL: find recent swing pivot (shallow lookback = 30 bars)
    swing_high, swing_low = _find_swing_pivots(df, lookback=30, pivot_bars=2)
    buf = atr * 0.3   # small buffer beyond the pivot

    sl = tp = lc
    sl_dist = 0.0

    if signal == "BUY":
        # SL just below most recent swing low; fall back to ATR
        if swing_low is not None and swing_low < lc:
            sl = swing_low - buf
        else:
            sl = lc - atr * atr_multiplier
        sl_dist = max(lc - sl, atr * 0.5)   # floor at 0.5 ATR
        sl      = lc - sl_dist
        tp      = lc + sl_dist * rr

    elif signal == "SELL":
        # SL just above most recent swing high; fall back to ATR
        if swing_high is not None and swing_high > lc:
            sl = swing_high + buf
        else:
            sl = lc + atr * atr_multiplier
        sl_dist = max(sl - lc, atr * 0.5)
        sl      = lc + sl_dist
        tp      = lc - sl_dist * rr

    sl_pct = (sl_dist / lc * 100) if lc > 0 else 0.0

    # Validate trade quality
    rr_valid = True
    rejection_reason = None
    if signal not in ("BUY", "SELL"):
        rr_valid = False
        rejection_reason = "No directional signal"
    elif sl_dist == 0:
        rr_valid = False
        rejection_reason = "Zero SL distance — cannot size position"
    elif sl_pct > max_sl_pct:
        rr_valid = False
        rejection_reason = (
            f"SL too wide: {sl_pct:.2f}% of price "
            f"(max allowed {max_sl_pct:.1f}%)"
        )

    return {
        "entry":            round(lc, 6),
        "sl":               round(sl, 6),
        "tp":               round(tp, 6),
        "sl_distance":      round(sl_dist, 6),
        "tp_distance":      round(sl_dist * rr, 6),
        "sl_pct":           round(sl_pct, 4),
        "rr":               round(rr, 2),
        "rr_valid":         rr_valid,
        "rejection_reason": rejection_reason,
    }


# ── Sections 4, 8: ADX gate + dynamic SMC threshold in evaluate_bot_window ─
def evaluate_bot_window(df, strategy="bot", symbol="BTCUSDT", interval="5m",
                         higher_df=None, cfg=None):
    cfg = cfg or DEFAULT_CONFIG
    if df is None or len(df) < 50:
        return {
            "signal": "HOLD", "bias": "Neutral", "structure": "Range / Mixed",
            "regime": "Unknown", "confidence": 50, "adx": 0,
            "trade_idea": "Not enough data",
            "higher_tf": get_higher_timeframe(interval), "higher_tf_bias": "Neutral",
            "liquidity_sweep": None, "bos": None, "smc_score": 0,
            "reasons": ["Insufficient candle history — need ≥50 bars"],
        }

    raw_signal     = generate_signal(df)
    structure      = get_structure(df)
    regime         = get_market_regime(df)
    higher_tf      = get_higher_timeframe(interval)
    if higher_df is None:
        higher_df = fetch_df_for_symbol(symbol, higher_tf, 100)
    higher_tf_bias = get_trend_bias(higher_df)
    sweep          = detect_liquidity_sweep(df)
    bos            = detect_break_of_structure(df)

    # ── Section 4: ADX hard gate ──────────────────────────────────────
    try:
        adx = calculate_adx(df)
    except Exception:
        adx = 25.0   # default to passable if calculation fails

    if adx < 20:
        return {
            "signal": "HOLD", "bias": "Neutral", "structure": structure,
            "regime": regime, "confidence": 40, "adx": adx,
            "trade_idea": "No trend detected — ADX filter active",
            "higher_tf": higher_tf, "higher_tf_bias": higher_tf_bias,
            "liquidity_sweep": sweep, "bos": bos, "smc_score": 0,
            "reasons": [f"ADX {adx:.1f} < 20 — no trend, signal blocked"],
        }

    # ── Turbulence gate — extreme volatility blocks all new signals ────
    if regime == "High Volatility":
        return {
            "signal": "HOLD", "bias": "Neutral", "structure": structure,
            "regime": regime, "confidence": 35, "adx": adx,
            "trade_idea": "High-volatility turbulence detected — new signals paused",
            "higher_tf": higher_tf, "higher_tf_bias": higher_tf_bias,
            "liquidity_sweep": sweep, "bos": bos, "smc_score": 0,
            "reasons": ["ATR ratio >2× historical average — turbulence gate active"],
        }

    final, idea, smc_score, confidence, reasons = \
        "HOLD", "Wait for clearer confirmation", 0, 50, []

    if strategy == "basic":
        confidence = estimate_confidence(df, raw_signal, smc_checks_passed=0)
        final = raw_signal
        idea  = {"BUY": "Pullback long / continuation",
                 "SELL": "Reject highs / continuation short"}.get(final, idea)
        reasons.append(f"Basic momentum signal = {raw_signal}")

    elif strategy == "ema_rsi":
        confidence = estimate_confidence(df, raw_signal, smc_checks_passed=0)
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
        # ── Section 8: dynamic SMC threshold ─────────────────────────
        if regime in ["Strong Bull", "Strong Bear"]:
            dynamic_min = max(7, cfg["min_smc_score"] - 1)    # strong trend → slightly easier
        elif regime in ["Trending Bull", "Trending Bear", "Trending"]:
            dynamic_min = cfg["min_smc_score"]                 # normal threshold
        elif regime == "High Volatility":
            dynamic_min = cfg["min_smc_score"] + 2             # turbulence → very strict
        elif regime in ["Range / Quiet", "Unknown"]:
            dynamic_min = cfg["min_smc_score"] + 1             # ranging → harder
        else:
            dynamic_min = cfg["min_smc_score"]

        # Preliminary confidence (no SMC alignment bonus yet — avoids circular dep)
        prelim_conf = estimate_confidence(df, raw_signal, smc_checks_passed=0)

        # ── RSI filter (14-period) ─────────────────────────────────────
        rsi_now = 50.0
        try:
            rsi_s = _rsi_series(df["close"].tolist(), 14)
            if rsi_s and rsi_s[-1] is not None:
                rsi_now = round(float(rsi_s[-1]), 1)
        except Exception:
            pass

        # ── Volume confirmation ────────────────────────────────────────
        volume_ok = True
        try:
            avg_vol = float(df["volume"].rolling(20).mean().iloc[-1])
            cur_vol = float(df["volume"].iloc[-1])
            if pd.notna(avg_vol) and avg_vol > 0:
                min_mult = cfg.get("min_volume_multiplier", 0.8)
                volume_ok = cur_vol >= avg_vol * min_mult
        except Exception:
            pass

        buy_checks = [
            ("HTF bias bullish",                      higher_tf_bias == "Bullish"),
            ("Buy-side liquidity sweep",               sweep == "BUY_SWEEP"),
            ("Bullish break of structure",             bos == "BULLISH_BOS"),
            ("Price in discount zone",                 price_in_discount_zone(df)),
            ("FVG retracement long",                   detect_fvg_retrace(df, "BUY", interval)),
            (f"Confidence ≥ {cfg['min_confidence']}%", prelim_conf >= cfg["min_confidence"]),
            ("Trending / active regime",               regime not in ["Range / Quiet", "Unknown", "High Volatility"]),
            ("Clear structure (not range)",            structure != "Range / Mixed"),
            ("Active session window",                  session_allowed(cfg)),
            (f"RSI not overbought (RSI {rsi_now:.0f} < 65)", rsi_now < 65),
            ("Volume above threshold",                 volume_ok),
        ]
        sell_checks = [
            ("HTF bias bearish",                      higher_tf_bias == "Bearish"),
            ("Sell-side liquidity sweep",              sweep == "SELL_SWEEP"),
            ("Bearish break of structure",             bos == "BEARISH_BOS"),
            ("Price in premium zone",                  price_in_premium_zone(df)),
            ("FVG retracement short",                  detect_fvg_retrace(df, "SELL", interval)),
            (f"Confidence ≥ {cfg['min_confidence']}%", prelim_conf >= cfg["min_confidence"]),
            ("Trending / active regime",               regime not in ["Range / Quiet", "Unknown", "High Volatility"]),
            ("Clear structure (not range)",            structure != "Range / Mixed"),
            ("Active session window",                  session_allowed(cfg)),
            (f"RSI not oversold (RSI {rsi_now:.0f} > 35)",   rsi_now > 35),
            ("Volume above threshold",                 volume_ok),
        ]
        bs = sum(1 for _, ok in buy_checks  if ok)
        ss = sum(1 for _, ok in sell_checks if ok)

        if bs >= dynamic_min:
            smc_score  = bs
            confidence = max(estimate_confidence(df, "BUY",  smc_checks_passed=bs, total_checks=11), 80)
            final, idea = "BUY", "HTF bullish + sweep + BOS + retracement entry"
            reasons = ([f"✓ {n}" for n, ok in buy_checks  if ok] +
                       [f"✗ {n}" for n, ok in buy_checks  if not ok])
        elif ss >= dynamic_min:
            smc_score  = ss
            confidence = max(estimate_confidence(df, "SELL", smc_checks_passed=ss, total_checks=11), 80)
            final, idea = "SELL", "HTF bearish + sweep + BOS + retracement entry"
            reasons = ([f"✓ {n}" for n, ok in sell_checks if ok] +
                       [f"✗ {n}" for n, ok in sell_checks if not ok])
        else:
            smc_score  = max(bs, ss)
            confidence = prelim_conf
            best       = buy_checks if bs >= ss else sell_checks
            reasons    = ([f"✓ {n}" for n, ok in best if ok] +
                          [f"✗ {n}" for n, ok in best if not ok])

    bias = {"BUY": "Bullish", "SELL": "Bearish"}.get(final, higher_tf_bias)
    return {
        "signal": final, "bias": bias, "structure": structure,
        "regime": regime, "confidence": confidence, "trade_idea": idea,
        "higher_tf": higher_tf, "higher_tf_bias": higher_tf_bias,
        "liquidity_sweep": sweep, "bos": bos,
        "smc_score": smc_score, "adx": adx, "reasons": reasons,
    }


def get_symbol_summary(symbol, strategy="bot", interval=SIGNALS_INTERVAL, cfg=None):
    cfg       = cfg or DEFAULT_CONFIG
    cache_key = (symbol, strategy, interval)
    cached    = _cache_get(_summary_cache, cache_key, SUMMARY_TTL_SECONDS)
    if cached is not None:
        return cached

    fetch_iv = SIGNALS_INTERVAL
    df = fetch_df_for_symbol(symbol, fetch_iv, 200)
    if df is None:
        return None

    market = detect_market(symbol)
    if market == "crypto":
        higher_df = fetch_df_for_symbol(symbol, get_higher_timeframe(fetch_iv), 100)
    else:
        higher_df = None

    ev     = evaluate_bot_window(df, strategy, symbol, fetch_iv, higher_df, cfg)
    prev   = float(df.iloc[-2]["close"]) if len(df) > 1 else float(df.iloc[-1]["close"])
    last   = float(df.iloc[-1]["close"])
    chg    = ((last - prev) / prev * 100) if prev else 0
    levels = calculate_trade_levels(
        df, ev["signal"],
        cfg.get("risk_reward", 2),
        cfg.get("atr_multiplier", 1.5),
        cfg,
    )

    # ── v2 enriched fields for the frontend ───────────────────────────
    # RSI 14
    try:
        rsi_s   = _rsi_series(df["close"].tolist(), 14)
        rsi_val = round(rsi_s[-1], 1) if rsi_s and rsi_s[-1] is not None else None
    except Exception:
        rsi_val = None

    # EMA alignment stack
    try:
        e9_v  = float(df["close"].ewm(span=9,  adjust=False).mean().iloc[-1])
        e21_v = float(df["close"].ewm(span=21, adjust=False).mean().iloc[-1])
        e50_v = float(df["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        if   e9_v > e21_v > e50_v: ema_align = "Bullish stack"
        elif e9_v < e21_v < e50_v: ema_align = "Bearish stack"
        elif e9_v > e50_v:          ema_align = "Mixed bullish"
        else:                       ema_align = "Mixed bearish"
    except Exception:
        ema_align = "Unknown"

    # Current trading session
    session_name = get_session_name(datetime.utcnow())

    # FVG both directions
    fvg_buy  = detect_fvg_retrace(df, "BUY",  fetch_iv)
    fvg_sell = detect_fvg_retrace(df, "SELL", fetch_iv)
    fvg_dir  = "BUY" if fvg_buy else ("SELL" if fvg_sell else None)

    # Quality rating
    conf_q = ev["confidence"]; smc_q = ev["smc_score"]
    if   conf_q >= 88 and smc_q >= 10: q_label = "A+"
    elif conf_q >= 80 and smc_q >= 9:  q_label = "A"
    elif conf_q >= 70 and smc_q >= 7:  q_label = "B"
    elif conf_q >= 60:                  q_label = "C"
    else:                               q_label = "D"

    # R:R ratio
    try:
        _risk   = abs(levels["entry"] - levels["sl"])
        _reward = abs(levels["tp"]    - levels["entry"])
        rr_val  = round(_reward / _risk, 2) if _risk else None
    except Exception:
        rr_val = None

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
        "adx":             ev.get("adx", 0),
        "reasons":         ev["reasons"],
        "entry":              levels["entry"],
        "sl":                 levels["sl"],
        "tp":                 levels["tp"],
        "sl_distance":        levels["sl_distance"],
        "tp_distance":        levels["tp_distance"],
        "sl_pct":             levels["sl_pct"],
        "risk_reward_ratio":  levels["rr"],
        "rr_valid":           levels["rr_valid"],
        "rejection_reason":   levels["rejection_reason"],
        # v2 enriched
        "rsi":             rsi_val,
        "ema_alignment":   ema_align,
        "session":         session_name,
        "fvg_detected":    bool(fvg_buy or fvg_sell),
        "fvg_direction":   fvg_dir,
        "quality":         q_label,
        "rr":              levels["rr"],
        "atr_multiplier":  cfg.get("atr_multiplier", 1.5),
        "min_smc_score":   cfg.get("min_smc_score", 6),
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
    try:
        t = int(ts)
        if t > 1e12:
            return datetime.utcfromtimestamp(t / 1000).strftime("%Y-%m-%d %H:%M:%S")
        return datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


# ─────────────────────────────────────────────
# SHARED INDICATOR HELPERS
# ─────────────────────────────────────────────

def _adr_series(daily_highs, daily_lows, period=10):
    if len(daily_highs) < period:
        return [None] * len(daily_highs)
    ranges = [daily_highs[j] - daily_lows[j] for j in range(len(daily_highs))]
    result = [None] * (period - 1)
    for i in range(period - 1, len(ranges)):
        result.append(sum(ranges[i - period + 1: i + 1]) / period)
    return result


def _vwap_series(candles):
    from datetime import datetime as _dt

    def _date(ts):
        t = int(ts)
        if t > 1e12: t //= 1000
        return _dt.utcfromtimestamp(t).strftime("%Y-%m-%d")

    result  = []
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
    from datetime import datetime as _dt, timedelta as _td
    ts = int(ts_ms)
    if ts > 1e12: ts //= 1000
    utc_dt = _dt.utcfromtimestamp(ts)
    month  = utc_dt.month
    offset = -4 if 4 <= month <= 10 else -5
    et_dt  = utc_dt + _td(hours=offset)
    return et_dt.hour, et_dt.minute, et_dt.weekday()


def _candle_et_hm(ts_ms):
    h, m, _ = _candle_et_hour_minute(ts_ms)
    return h * 100 + m


# ─────────────────────────────────────────────
# STRATEGY: 0DTE Opening Range Breakout (ORB)
# ─────────────────────────────────────────────

def run_orb_strategy(candles, starting_balance=1000,
                     fee_pct=0.04, slippage_pct=0.02):
    RISK_PCT        = 0.02
    TP_PCT          = 1.00
    SL_PCT          = 0.50
    TIME_STOP_ET    = 1530
    OPEN_RANGE_MINS = 5
    TRADE_DAYS      = {0, 2, 4}

    trades  = []
    balance = float(starting_balance)

    if len(candles) < 10:
        return trades, balance

    from collections import defaultdict
    day_candles = defaultdict(list)
    for c in candles:
        ts = int(c[0]); ts_s = ts // 1000 if ts > 1e12 else ts
        from datetime import datetime as _dt
        import datetime as _dtmod
        utc = _dt.utcfromtimestamp(ts_s)
        month  = utc.month
        offset = -4 if 4 <= month <= 10 else -5
        et = utc + _dtmod.timedelta(hours=offset)
        day_key = et.strftime("%Y-%m-%d")
        day_candles[day_key].append((c, et.hour, et.minute, et.weekday()))

    for day_key in sorted(day_candles.keys()):
        bars = day_candles[day_key]
        if not bars:
            continue
        weekday = bars[0][3]
        if weekday not in TRADE_DAYS:
            continue
        or_bars = [(c, h, m) for c, h, m, _ in bars
                   if h == 9 and 30 <= m < 30 + OPEN_RANGE_MINS]
        if not or_bars:
            continue
        or_high = max(float(b[0][2]) for b in or_bars)
        or_low  = min(float(b[0][3]) for b in or_bars)
        if or_high <= or_low:
            continue
        option_premium = (or_high - or_low) * 0.5
        if option_premium <= 0:
            continue
        risk_dollar = balance * RISK_PCT
        size = risk_dollar / (option_premium * SL_PCT)
        position   = None
        day_traded = False

        for c, hr, mn, _ in bars:
            hm    = hr * 100 + mn
            if hm < 935:
                continue
            if hm >= TIME_STOP_ET and position is None:
                break
            price = float(c[4])
            hi    = float(c[2])
            lo    = float(c[3])
            t_str = _ts_to_str(c[0])

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
                    "side": side, "entry": round(ep, 4), "exit": round(price, 4),
                    "entry_time": position["time"], "exit_time": t_str,
                    "pnl": round(net_pnl, 4), "reason": "Time stop",
                    "setup": f"ORB | OR {or_low:.2f}-{or_high:.2f}",
                })
                position = None
                break

            if position is None and not day_traded:
                if price > or_high:
                    ep = price * (1 + slippage_pct / 100)
                    position   = {"side": "BUY",  "entry_price": ep,
                                  "premium": option_premium, "time": t_str}
                    day_traded = True
                elif price < or_low:
                    ep = price * (1 - slippage_pct / 100)
                    position   = {"side": "SELL", "entry_price": ep,
                                  "premium": option_premium, "time": t_str}
                    day_traded = True

            elif position is not None:
                side = position["side"]
                ep   = position["entry_price"]
                prem = position["premium"]
                underlying_move = (price - ep) if side == "BUY" else (ep - price)
                opt_pnl_pct = underlying_move / prem
                if opt_pnl_pct >= TP_PCT:
                    net_pnl = prem * TP_PCT * size - risk_dollar * fee_pct / 100 * 2
                    balance += net_pnl
                    trades.append({
                        "side": side, "entry": round(ep, 4), "exit": round(price, 4),
                        "entry_time": position["time"], "exit_time": t_str,
                        "pnl": round(net_pnl, 4), "reason": "Take profit (+100%)",
                        "setup": f"ORB | OR {or_low:.2f}-{or_high:.2f}",
                    })
                    position = None
                elif opt_pnl_pct <= -SL_PCT:
                    net_pnl = -(prem * SL_PCT * size) - risk_dollar * fee_pct / 100 * 2
                    balance += net_pnl
                    trades.append({
                        "side": side, "entry": round(ep, 4), "exit": round(price, 4),
                        "entry_time": position["time"], "exit_time": t_str,
                        "pnl": round(net_pnl, 4), "reason": "Stop loss (-50%)",
                        "setup": f"ORB | OR {or_low:.2f}-{or_high:.2f}",
                    })
                    position = None

    return trades, balance


# ─────────────────────────────────────────────
# STRATEGY: VWAP + EMA Trend
# ─────────────────────────────────────────────

def run_vwap_ema_strategy(candles, starting_balance=1000,
                           fee_pct=0.04, slippage_pct=0.02):
    RISK_PCT        = 0.02
    ENTRY_AFTER_ET  = 1030
    CLOSE_ET        = 1600
    ADR_PERIOD      = 10
    EMA_FAST        = 9
    EMA_SLOW        = 21
    ADR_SL_MULT     = 0.50
    ADR_TP1_MULT    = 0.75
    TRAIL_ATR_MULT  = 1.0

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

    daily_ranges = [(day_hl[d]["h"] - day_hl[d]["l"]) for d in dates_in_order]
    daily_adr    = {}
    for k, d in enumerate(dates_in_order):
        if k >= ADR_PERIOD:
            daily_adr[d] = sum(daily_ranges[k - ADR_PERIOD: k]) / ADR_PERIOD
        else:
            daily_adr[d] = None

    position     = None
    current_day  = None
    day_traded   = False

    for i in range(EMA_SLOW + 1, len(candles)):
        e9   = ema9_s[i];  e9p  = ema9_s[i-1]
        e21  = ema21_s[i]; e21p = ema21_s[i-1]
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

        if position is not None and hm >= CLOSE_ET:
            side = position["side"]; ep = position["entry"]
            raw_pnl = ((close - ep) if side == "BUY" else (ep - close)) * position["size"]
            fee = ep * position["size"] * fee_pct / 100 * 2
            net = raw_pnl - fee
            balance += net
            trades.append({
                "side": side, "entry": round(ep, 6), "exit": round(close, 6),
                "entry_time": position["time"], "exit_time": t_str,
                "pnl": round(net, 4), "reason": "Force close",
                "setup": position.get("setup", ""),
            })
            position = None; day_traded = False
            continue

        if position is not None:
            side     = position["side"]
            ep       = position["entry"]
            sl       = position["sl"]
            tp1      = position["tp1"]
            tp1_hit  = position["tp1_hit"]
            trail_sl = position["trail_sl"]
            sz_full  = position["size"]
            sz_rem   = position["size_rem"]
            peak     = position["peak"]

            if side == "BUY":
                if hi > peak: peak = hi; position["peak"] = peak
            else:
                if lo < peak: peak = lo; position["peak"] = peak

            if tp1_hit:
                if side == "BUY":
                    candidate = peak - atr_v * TRAIL_ATR_MULT
                    if candidate > trail_sl: trail_sl = candidate; position["trail_sl"] = trail_sl
                else:
                    candidate = peak + atr_v * TRAIL_ATR_MULT
                    if candidate < trail_sl: trail_sl = candidate; position["trail_sl"] = trail_sl

            eff_sl = trail_sl if tp1_hit else sl

            if not tp1_hit:
                if (side == "BUY" and hi >= tp1) or (side == "SELL" and lo <= tp1):
                    partial_sz = sz_full - sz_rem
                    raw_pnl_p1 = ((tp1 - ep) if side == "BUY" else (ep - tp1)) * partial_sz
                    fee_p1     = ep * partial_sz * fee_pct / 100 * 2
                    net_p1     = raw_pnl_p1 - fee_p1
                    balance   += net_p1
                    position["tp1_hit"]  = True
                    position["trail_sl"] = ep
                    trail_sl = ep
                    trades.append({
                        "side": side, "entry": round(ep, 6), "exit": round(tp1, 6),
                        "entry_time": position["time"], "exit_time": t_str,
                        "pnl": round(net_p1, 4), "reason": "Target 1 (75% ADR) — 50% closed",
                        "setup": position.get("setup", ""),
                    })
                    continue

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
                    "side": side, "entry": round(ep, 6), "exit": round(exit_price, 6),
                    "entry_time": position["time"], "exit_time": t_str,
                    "pnl": round(net, 4), "reason": exit_reason + " (remainder)",
                    "setup": position.get("setup", ""),
                })
                position = None
            continue

        if day_traded or adr is None or hm < ENTRY_AFTER_ET:
            continue

        cross_up   = e9p <= e21p and e9 > e21
        cross_down = e9p >= e21p and e9 < e21

        side = None
        if cross_up   and close > vwap: side = "BUY"
        elif cross_down and close < vwap: side = "SELL"

        if side is None:
            continue

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
            "side": side, "entry": ep, "time": t_str,
            "sl": sl_price, "tp1": tp1_price, "tp1_hit": False,
            "trail_sl": sl_price, "peak": ep,
            "size": size, "size_rem": size * 0.50,
            "setup": f"VWAP+EMA | {'above' if side=='BUY' else 'below'} VWAP | ADR {adr:.4f}",
        }
        day_traded = True

    return trades, balance


# ─────────────────────────────────────────────
# STRATEGY: SIMPLE MA
# ─────────────────────────────────────────────

def run_simple_ma_strategy(candles, starting_balance=1000,
                            fee_pct=0.04, slippage_pct=0.02,
                            weekly_win_goal=3,
                            weekly_profit_target_pct=3.0,
                            weekly_max_loss_pct=0.8):
    trades      = []
    balance     = float(starting_balance)
    risk_pct    = 0.01
    fee_rate    = fee_pct    / 100
    slip_rate   = slippage_pct / 100

    if len(candles) < 35:
        return trades, balance

    closes = [float(c[4]) for c in candles]
    highs  = [float(c[2]) for c in candles]
    lows   = [float(c[3]) for c in candles]

    def sma(arr, n):
        return sum(arr[-n:]) / n if len(arr) >= n else None

    atr_all      = _atr_series(highs, lows, closes, 14)
    position     = None
    current_week = None
    week_wins    = 0
    week_losses  = 0
    week_pnl     = 0.0
    week_paused  = False

    def _iso_week(ts):
        return datetime.utcfromtimestamp(int(ts) / 1000).isocalendar()[:2]

    for i in range(30, len(candles)):
        fast = sma(closes[:i], 10)
        slow = sma(closes[:i], 30)
        if fast is None or slow is None:
            continue
        prev_fast = sma(closes[:i - 1], 10)
        prev_slow = sma(closes[:i - 1], 30)
        if prev_fast is None or prev_slow is None:
            continue

        # Weekly reset & pause check
        iso_w = _iso_week(candles[i][0])
        if iso_w != current_week:
            current_week = iso_w
            week_wins = 0; week_losses = 0; week_pnl = 0.0; week_paused = False

        price      = closes[i]
        entry_time = _ts_to_str(candles[i][0])
        atr        = atr_all[i] if (atr_all and i < len(atr_all) and atr_all[i]) else price * 0.003

        if position is None:
            if week_paused:
                continue
            crossed_up   = prev_fast <= prev_slow and fast > slow
            crossed_down = prev_fast >= prev_slow and fast < slow
            if crossed_up:
                ep      = price * (1 + slip_rate)
                sl_dist = atr * 1.5
                position = {"side": "BUY",  "entry": ep, "time": entry_time,
                            "sl": ep - sl_dist, "tp": ep + sl_dist * 2,
                            "sl_dist": sl_dist}
            elif crossed_down:
                ep      = price * (1 - slip_rate)
                sl_dist = atr * 1.5
                position = {"side": "SELL", "entry": ep, "time": entry_time,
                            "sl": ep + sl_dist, "tp": ep - sl_dist * 2,
                            "sl_dist": sl_dist}
            continue

        side    = position["side"]
        ep      = position["entry"]
        sl      = position["sl"]
        tp      = position["tp"]
        sl_dist = position["sl_dist"]
        hi      = float(candles[i][2])
        lo      = float(candles[i][3])

        exit_price  = None
        exit_reason = "Held"

        if side == "BUY":
            if lo <= sl:   exit_price, exit_reason = sl,    "Stop loss"
            elif hi >= tp: exit_price, exit_reason = tp,    "Take profit"
            elif fast < slow: exit_price, exit_reason = price, "Signal reversal"
        else:
            if hi >= sl:   exit_price, exit_reason = sl,    "Stop loss"
            elif lo <= tp: exit_price, exit_reason = tp,    "Take profit"
            elif fast > slow: exit_price, exit_reason = price, "Signal reversal"

        if exit_price is not None:
            size     = (balance * risk_pct) / sl_dist if sl_dist > 0 else 0
            if side == "BUY":
                raw_pnl = (exit_price - ep) * size
            else:
                raw_pnl = (ep - exit_price) * size
            fee      = ep * size * fee_rate * 2
            net_pnl  = raw_pnl - fee
            balance += net_pnl
            if net_pnl > 0: week_wins   += 1
            else:           week_losses += 1
            week_pnl += net_pnl
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
            # Check weekly pause after closing
            _wpct = week_pnl / float(starting_balance) * 100
            if (week_wins  >= weekly_win_goal or
                    _wpct  >= weekly_profit_target_pct or
                    _wpct  <= -weekly_max_loss_pct):
                week_paused = True
            continue

        # Skip new entries if weekly limit reached
        if position is None and week_paused:
            continue

    return trades, balance


# ─────────────────────────────────────────────
# INDICATOR HELPERS
# ─────────────────────────────────────────────

def _ema_series(values, period):
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


def _week_start():
    """Monday 00:00:00 UTC of the current ISO week, as a 'YYYY-MM-DD HH:MM:SS' string."""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(
        days=now.weekday(),
        hours=now.hour, minutes=now.minute,
        seconds=now.second, microseconds=now.microsecond,
    )
    return monday.strftime("%Y-%m-%d %H:%M:%S")


def get_weekly_stats(user_id):
    """Return wins/losses/PnL for closed trades opened since Monday 00:00 UTC."""
    ws = _week_start()
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "SELECT pnl FROM trades WHERE user_id=%s AND status='CLOSED' AND time >= %s",
        (user_id, ws),
    )
    pnls = [float(r[0] or 0) for r in c.fetchall()]
    conn.close()
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "weekly_wins":   len(wins),
        "weekly_losses": len(losses),
        "weekly_trades": len(pnls),
        "weekly_pnl":    round(sum(pnls), 2),
    }


def is_weekly_paused(user_id, cfg):
    """
    Check whether the bot should stop opening new trades this week.
    Returns a dict suitable for embedding in API responses.
    """
    ws          = get_weekly_stats(user_id)
    sb          = float(cfg.get("starting_balance", 10000))
    win_goal    = int(cfg.get("weekly_win_goal", 3))
    profit_tgt  = float(cfg.get("weekly_profit_target_percent", 3.0))
    max_loss    = float(cfg.get("weekly_max_loss_percent", 0.8))

    profit_pct        = (ws["weekly_pnl"] / sb * 100) if sb > 0 else 0.0
    win_goal_hit      = ws["weekly_wins"]  >= win_goal
    profit_target_hit = profit_pct >= profit_tgt
    max_loss_hit      = profit_pct <= -max_loss

    paused = max_loss_hit or win_goal_hit or profit_target_hit
    if max_loss_hit:
        reason = (
            f"Weekly max loss reached "
            f"({profit_pct:.1f}% ≤ -{max_loss}%) — trading paused until next week"
        )
    elif win_goal_hit:
        reason = (
            f"Weekly win goal reached "
            f"({ws['weekly_wins']}/{win_goal} wins) — trading paused until next week"
        )
    elif profit_target_hit:
        reason = (
            f"Weekly profit target reached "
            f"({profit_pct:.1f}% ≥ {profit_tgt}%) — trading paused until next week"
        )
    else:
        reason = None

    return {
        "weekly_trading_paused":   paused,
        "pause_reason":            reason,
        "weekly_wins":             ws["weekly_wins"],
        "weekly_losses":           ws["weekly_losses"],
        "weekly_trades":           ws["weekly_trades"],
        "weekly_pnl":              ws["weekly_pnl"],
        "weekly_profit_pct":       round(profit_pct, 2),
        "weekly_profit_target":    profit_tgt,
        "weekly_max_loss":         max_loss,
        "weekly_win_goal":         win_goal,
        "profit_target_hit":       profit_target_hit,
        "win_goal_hit":            win_goal_hit,
        "max_loss_hit":            max_loss_hit,
    }


def _kelly_fraction(trades, default=0.01, cap=0.03):
    """
    Half-Kelly position-sizing fraction from a list of {'pnl': float} dicts.
    Requires at least 10 closed trades; falls back to `default` otherwise.
    Returns a float (e.g. 0.015 = 1.5% of account per trade).
    """
    if not trades or len(trades) < 10:
        return default
    wins   = [t["pnl"] for t in trades if t.get("pnl", 0) > 0]
    losses = [abs(t["pnl"]) for t in trades if t.get("pnl", 0) <= 0]
    if not wins or not losses:
        return default
    w_rate  = len(wins) / len(trades)
    avg_win = sum(wins)  / len(wins)
    avg_los = sum(losses)/ len(losses)
    if avg_los == 0:
        return default
    b     = avg_win / avg_los            # payoff ratio
    kelly = (w_rate * b - (1 - w_rate)) / b
    return max(0.005, min(cap, kelly / 2.0))   # half-Kelly, capped at `cap`


def _adx_series(highs, lows, closes, period=14):
    n = len(closes)
    if n < period * 2 + 1:
        return [None] * n
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


def _sma_series(values, period):
    """Simple moving average — returns same-length list with None for warmup."""
    n = len(values)
    result = [None] * (period - 1)
    for i in range(period - 1, n):
        result.append(sum(values[i - period + 1: i + 1]) / period)
    return result


def _macd_line(closes, fast=12, slow=26):
    """MACD line (fast EMA − slow EMA)."""
    fe = _ema_series(closes, fast)
    se = _ema_series(closes, slow)
    return [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fe, se)
    ]


def _bb_series(closes, period=20, std_mult=2.0):
    """Bollinger Bands — returns (upper, mid, lower) as three lists."""
    n = len(closes)
    upper, mid, lower = [None] * n, [None] * n, [None] * n
    for i in range(period - 1, n):
        w = closes[i - period + 1: i + 1]
        m = sum(w) / period
        std = (sum((x - m) ** 2 for x in w) / period) ** 0.5
        mid[i]   = m
        upper[i] = m + std * std_mult
        lower[i] = m - std * std_mult
    return upper, mid, lower


def _dynamic_rr(score, regime="Unknown", adx_val=0):
    """
    Return a dynamic R:R ratio based on confluence score (out of 9 signals).
    score 5 → 2.0R, 6 → 2.5R, 7 → 3.0R, 8 → 3.5R, 9 → 4.0R
    ADX >= 35 or Strong regime adds 0.5R bonus.
    """
    base = {5: 2.0, 6: 2.5, 7: 3.0, 8: 3.5}.get(min(score, 8), 4.0)
    bonus = 0.5 if ("Strong" in str(regime) or adx_val >= 35) else 0.0
    return round(base + bonus, 1)


def _dynamic_risk_pct(score, base_risk=0.01):
    """
    Scale position risk by confluence score (out of 9 signals).
    score 5 → 0.8%, 6 → 1.0%, 7 → 1.2%, 8+ → 1.5%
    """
    scale = {5: 0.80, 6: 1.00, 7: 1.20, 8: 1.50}.get(min(score, 8), 1.50)
    return base_risk * scale


# ─────────────────────────────────────────────
# UNIFIED BOT STRATEGY  v3
# ─────────────────────────────────────────────
# Section 6: trailing stop added to PATH B (daily bars fallback)

def run_unified_bot_strategy(candles, starting_balance=1000,
                              fee_pct=0.04, slippage_pct=0.02,
                              weekly_win_goal=3,
                              weekly_profit_target_pct=3.0,
                              weekly_max_loss_pct=0.8,
                              user_cfg=None,
                              htf_candles=None):
    """
    ICT — Asian Range → London Push → New York Reversal

    PATH A : intraday candles  (gap < 20 h)
    PATH B : daily bars fallback with EMA/ADX/RSI trend-follow
             Section 6 trailing stop activates at 1R profit.
    Weekly limits: stop new entries when win goal / profit target / max loss hit.
    """
    from collections import defaultdict

    RISK_PCT       = 0.01
    MAX_WINS_DAY   = 2        # tightened: was 3
    MAX_LOSS_DAY   = 1

    ASIAN_START    =    0
    ASIAN_END      =  480
    LONDON_START   =  480
    LONDON_END     =  630
    NY_START       =  780
    NY_END         = 1020
    SESSION_CLOSE  = 1200

    DISP_BODY_RATIO = 0.52    # relaxed from 0.65 — crypto 5m needs looser threshold
    SL_BUFFER       = 0.0005
    SWEEP_DEPTH_PCT = 0.12    # relaxed from 0.20 — allow shallower liquidity grabs

    WARMUP        = 210   # PATH B: allows EMA200 to initialize (needs 200 bars)
    ADX_MIN_DAILY = 18    # PATH A fallback; PATH B uses confluence scoring
    RSI_BUY_LO    = 40;  RSI_BUY_HI  = 72   # PATH B confluence RSI bands
    RSI_SELL_LO   = 28;  RSI_SELL_HI = 60

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
    # PATH A — INTRADAY
    # ====================================================================
    if not is_daily:
        day_buckets = defaultdict(lambda: {"asian": [], "london": [], "ny": [], "after": []})
        for c in candles:
            hm = _hm(c[0]); d = _date(c[0])
            if   ASIAN_START  <= hm < ASIAN_END:    day_buckets[d]["asian"].append(c)
            elif LONDON_START <= hm < LONDON_END:   day_buckets[d]["london"].append(c)
            elif NY_START     <= hm < NY_END:       day_buckets[d]["ny"].append(c)
            elif NY_END       <= hm < SESSION_CLOSE: day_buckets[d]["after"].append(c)

        # Pre-compute EMA/ATR over all candles for the EMA momentum fallback
        _pa_cls  = [float(c[4]) for c in candles]
        _pa_hi   = [float(c[2]) for c in candles]
        _pa_lo   = [float(c[3]) for c in candles]
        _pa_e9   = _ema_series(_pa_cls, 9)
        _pa_e21  = _ema_series(_pa_cls, 21)
        _pa_e50  = _ema_series(_pa_cls, 50)
        _pa_atr  = _atr_series(_pa_hi, _pa_lo, _pa_cls, 14)
        _pa_cidx = {int(c[0]): j for j, c in enumerate(candles)}

        position    = None
        current_day = None
        day_wins    = 0
        day_losses  = 0
        ict_trade_days = set()   # days where ICT already produced a trade

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
                        "exit": round(lc, 6), "pnl": round(net, 4),
                        "entry_time": position["time"], "exit_time": position["time"],
                        "reason": "End-of-day close",
                        "rr": position.get("rr", 2.0), "sl_pct": position.get("sl_pct", 0),
                        "session": position.get("session", "NY"),
                    })
                    position = None

            if not asian or not london or not ny:
                continue
            if day_losses >= MAX_LOSS_DAY or day_wins >= MAX_WINS_DAY:
                continue

            ash = max(float(c[2]) for c in asian)
            asl = min(float(c[3]) for c in asian)
            mid = (ash + asl) / 2
            if ash <= asl:
                continue

            l_high = max(float(c[2]) for c in london)
            l_low  = min(float(c[3]) for c in london)

            pushed_above = l_high > ash
            pushed_below = l_low  < asl

            if not pushed_above and not pushed_below:
                continue

            if pushed_above and pushed_below:
                if (l_high - ash) >= (asl - l_low):
                    pushed_below = False
                else:
                    pushed_above = False

            asian_range_size = ash - asl
            if asian_range_size <= 0:
                continue
            sweep_depth = (l_high - ash) if pushed_above else (asl - l_low)
            if sweep_depth < asian_range_size * SWEEP_DEPTH_PCT:
                continue

            # NOTE: London acceptance check removed — it was too strict
            # (required London to close back inside the Asian range, which
            # filtered out ~80% of valid ICT setups on 5m crypto data)

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

            entry_candle    = None
            fvg_hi = fvg_lo = None
            fvg_entry_price = None

            for k, c in enumerate(ny):
                o   = float(c[1]); h = float(c[2])
                lo_ = float(c[3]); cls = float(c[4])
                rng = h - lo_
                if rng == 0:
                    continue
                body = abs(cls - o)

                is_disp = (body / rng) > DISP_BODY_RATIO
                # Require directional candle only — price position check removed
                # (cls <= ash was too strict: price often hasn't reverted yet in NY)
                if reversal == "SELL":
                    is_disp = is_disp and cls < o   # strong bearish body
                else:
                    is_disp = is_disp and cls > o   # strong bullish body

                if not is_disp:
                    continue

                entry_candle = c

                if k >= 1 and k + 1 < len(ny):
                    prev = ny[k - 1]; nxt = ny[k + 1]
                    if reversal == "SELL":
                        if float(prev[3]) > float(nxt[2]):
                            fvg_hi = float(prev[3]); fvg_lo = float(nxt[2])
                    else:
                        if float(prev[2]) < float(nxt[3]):
                            fvg_lo = float(prev[2]); fvg_hi = float(nxt[3])
                break

            if entry_candle is None:
                # ── EMA Momentum Fallback (runs when ICT setup doesn't fire) ──
                # Find first EMA9/21 crossover in NY+after with ATR expansion
                for c_fb in (ny + after):
                    j_fb = _pa_cidx.get(int(c_fb[0]), -1)
                    if j_fb < 2:
                        continue
                    e9_f  = _pa_e9[j_fb];  e9_fp  = _pa_e9[j_fb - 1]
                    e21_f = _pa_e21[j_fb]; e21_fp = _pa_e21[j_fb - 1]
                    e50_f = _pa_e50[j_fb]
                    atr_f = _pa_atr[j_fb]
                    if any(v is None for v in [e9_f, e9_fp, e21_f, e21_fp, atr_f]) or atr_f <= 0:
                        continue
                    # ATR must be active (≥80% of recent average)
                    lb_atr = [x for x in _pa_atr[max(0, j_fb - 20):j_fb] if x is not None]
                    avg_atr_f = sum(lb_atr) / len(lb_atr) if lb_atr else atr_f
                    if atr_f < avg_atr_f * 0.80:
                        continue
                    cross_up = e9_fp <= e21_fp and e9_f > e21_f
                    cross_dn = e9_fp >= e21_fp and e9_f < e21_f
                    if not cross_up and not cross_dn:
                        continue
                    fb_dir = "BUY" if cross_up else "SELL"
                    # EMA50 trend filter: only take signals aligned with medium-term trend
                    if fb_dir == "BUY"  and e50_f is not None and e9_f < e50_f * 0.998:
                        continue
                    if fb_dir == "SELL" and e50_f is not None and e9_f > e50_f * 1.002:
                        continue
                    # HTF bias filter: skip counter-trend EMA fallbacks
                    _fb_htf = _htf_bias_lu.get(int(c_fb[0])) if _htf_bias_lu else None
                    if _fb_htf == 'BEAR' and fb_dir == 'BUY':
                        continue
                    if _fb_htf == 'BULL' and fb_dir == 'SELL':
                        continue
                    fb_c   = float(c_fb[4])
                    fb_ep  = fb_c * (1 + slip_rate) if fb_dir == "BUY" else fb_c * (1 - slip_rate)
                    # SL: use HTF ATR if available; hard minimum 0.5% (was 0.2% — too tight)
                    _fb_htf_atr = _htf_atr_lu.get(int(c_fb[0])) if _htf_atr_lu else None
                    if _fb_htf_atr and _fb_htf_atr > 0:
                        fb_sl_d = max(_fb_htf_atr * 1.5, fb_ep * 0.003)
                    else:
                        fb_sl_d = max(atr_f * 3.0, fb_ep * 0.005)
                    fb_tp_d = fb_sl_d * 2.5
                    fb_sl  = fb_ep - fb_sl_d if fb_dir == "BUY" else fb_ep + fb_sl_d
                    fb_tp  = fb_ep + fb_tp_d if fb_dir == "BUY" else fb_ep - fb_tp_d
                    fb_sz  = risk_dollar / fb_sl_d if fb_sl_d > 0 else 0
                    if fb_sz <= 0:
                        continue
                    position = {
                        "side": fb_dir, "entry": fb_ep, "sl": fb_sl,
                        "tp1": fb_tp, "tp2": fb_tp,
                        "size": fb_sz, "size_rem": fb_sz * 0.5, "scaled": False,
                        "time": c_fb[0],
                        "rr":     round(fb_tp_d / fb_sl_d, 2) if fb_sl_d > 0 else 2.5,
                        "sl_pct": round(fb_sl_d / fb_ep * 100, 3) if fb_ep > 0 else 0,
                        "session": "NY-Momentum",
                    }
                    ict_trade_days.add(day)
                    try:
                        k_fb_start = (ny + after).index(c_fb) + 1
                    except ValueError:
                        k_fb_start = len(ny + after)
                    remaining = (ny + after)[k_fb_start:]
                    for c_r in remaining:
                        if position is None:
                            break
                        h_r = float(c_r[2]); lo_r = float(c_r[3]); t_r = c_r[0]
                        sd  = position["side"]
                        if sd == "SELL":
                            if not position["scaled"] and lo_r <= position["tp1"]:
                                ep_r = position["tp1"]; sz_r = position["size"] * 0.5
                                net_r = (position["entry"] - ep_r) * sz_r - position["entry"] * sz_r * fee_rate * 2
                                balance += net_r; day_wins += 1
                                trades.append({"side":"SELL","entry":round(position["entry"],6),"exit":round(ep_r,6),"pnl":round(net_r,4),"entry_time":position["time"],"exit_time":t_r,"reason":"Take profit","rr":position.get("rr",2.5),"sl_pct":position.get("sl_pct",0),"session":position.get("session","NY")})
                                position = None
                            elif h_r >= position["sl"]:
                                ep_r = position["sl"]; sz_r = position["size_rem"] if position["scaled"] else position["size"]
                                net_r = (position["entry"] - ep_r) * sz_r - position["entry"] * sz_r * fee_rate * 2
                                balance += net_r
                                if not position["scaled"]: day_losses += 1
                                trades.append({"side":"SELL","entry":round(position["entry"],6),"exit":round(ep_r,6),"pnl":round(net_r,4),"entry_time":position["time"],"exit_time":t_r,"reason":"Stop loss","rr":position.get("rr",2.5),"sl_pct":position.get("sl_pct",0),"session":position.get("session","NY")})
                                position = None
                        else:
                            if not position["scaled"] and h_r >= position["tp1"]:
                                ep_r = position["tp1"]; sz_r = position["size"] * 0.5
                                net_r = (ep_r - position["entry"]) * sz_r - position["entry"] * sz_r * fee_rate * 2
                                balance += net_r; day_wins += 1
                                trades.append({"side":"BUY","entry":round(position["entry"],6),"exit":round(ep_r,6),"pnl":round(net_r,4),"entry_time":position["time"],"exit_time":t_r,"reason":"Take profit","rr":position.get("rr",2.5),"sl_pct":position.get("sl_pct",0),"session":position.get("session","NY")})
                                position = None
                            elif lo_r <= position["sl"]:
                                ep_r = position["sl"]; sz_r = position["size_rem"] if position["scaled"] else position["size"]
                                net_r = (ep_r - position["entry"]) * sz_r - position["entry"] * sz_r * fee_rate * 2
                                balance += net_r
                                if not position["scaled"]: day_losses += 1
                                trades.append({"side":"BUY","entry":round(position["entry"],6),"exit":round(ep_r,6),"pnl":round(net_r,4),"entry_time":position["time"],"exit_time":t_r,"reason":"Stop loss","rr":position.get("rr",2.5),"sl_pct":position.get("sl_pct",0),"session":position.get("session","NY")})
                                position = None
                    if position is not None:
                        last_r = (after or ny)[-1] if (after or ny) else None
                        if last_r:
                            lc_r = float(last_r[4]); sz_r = position["size_rem"] if position["scaled"] else position["size"]
                            net_r = ((lc_r - position["entry"]) if position["side"] == "BUY" else (position["entry"] - lc_r)) * sz_r - position["entry"] * sz_r * fee_rate * 2
                            balance += net_r
                            trades.append({"side":position["side"],"entry":round(position["entry"],6),"exit":round(lc_r,6),"pnl":round(net_r,4),"entry_time":position["time"],"exit_time":last_r[0],"reason":"Session-end close","rr":position.get("rr",2.5),"sl_pct":position.get("sl_pct",0),"session":position.get("session","NY")})
                            position = None
                    break   # processed one fallback trade for this day
                continue

            ec = float(entry_candle[4])
            if fvg_hi is not None and fvg_lo is not None:
                fvg_mid = (fvg_hi + fvg_lo) / 2
                try:
                    k_disp = ny.index(entry_candle)
                except ValueError:
                    k_disp = len(ny)
                for c_fwd in ny[k_disp + 1:]:
                    h_fwd = float(c_fwd[2]); l_fwd = float(c_fwd[3])
                    if reversal == "SELL" and h_fwd >= fvg_lo:
                        fvg_entry_price = min(h_fwd, fvg_mid)
                        entry_candle = c_fwd
                        break
                    elif reversal == "BUY" and l_fwd <= fvg_hi:
                        fvg_entry_price = max(l_fwd, fvg_mid)
                        entry_candle = c_fwd
                        break

            raw_entry   = fvg_entry_price if fvg_entry_price is not None else ec
            entry_price = raw_entry * (1 - slip_rate) if reversal == "SELL" \
                          else raw_entry * (1 + slip_rate)

            risk_dist = abs(entry_price - sl_price)
            if risk_dist <= 0:
                continue

            size = risk_dollar / risk_dist

            _pa_tp2_dist = abs(tp2_price - entry_price)
            _pa_rr = round(_pa_tp2_dist / risk_dist, 2) if risk_dist > 0 else 2.0
            _pa_sl_pct = round(risk_dist / entry_price * 100, 3) if entry_price > 0 else 0
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
                "rr":       _pa_rr,
                "sl_pct":   _pa_sl_pct,
                "session":  "NY",
                "setup":    ("ICT " + ("bear" if reversal == "SELL" else "bull") +
                             " | push " + ("above ASH" if pushed_above else "below ASL") +
                             (" | FVG entry" if fvg_entry_price is not None
                              else " | aggressive entry")),
            }
            ict_trade_days.add(day)   # mark day as traded by ICT

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
                            "reason": "TP1 — Asian midpoint (50%)",
                            "rr": position.get("rr", 2.0), "sl_pct": position.get("sl_pct", 0),
                            "session": position.get("session", "NY"),
                        })
                        position["scaled"] = True
                        position["sl"]     = position["entry"]

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
                            "reason": "TP2 — Opposite Asian boundary (ASL)",
                            "rr": position.get("rr", 2.0), "sl_pct": position.get("sl_pct", 0),
                            "session": position.get("session", "NY"),
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
                            "rr": position.get("rr", 2.0), "sl_pct": position.get("sl_pct", 0),
                            "session": position.get("session", "NY"),
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
                            "reason": "TP1 — Asian midpoint (50%)",
                            "rr": position.get("rr", 2.0), "sl_pct": position.get("sl_pct", 0),
                            "session": position.get("session", "NY"),
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
                            "reason": "TP2 — Opposite Asian boundary (ASH)",
                            "rr": position.get("rr", 2.0), "sl_pct": position.get("sl_pct", 0),
                            "session": position.get("session", "NY"),
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
                            "rr": position.get("rr", 2.0), "sl_pct": position.get("sl_pct", 0),
                            "session": position.get("session", "NY"),
                        })
                        if not position["scaled"]: day_losses += 1
                        position = None

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
                        "rr": position.get("rr", 2.0), "sl_pct": position.get("sl_pct", 0),
                        "session": position.get("session", "NY"),
                    })
                    position = None

        return trades, balance

    # ====================================================================
    # PATH B — DAILY BARS: AI Multi-Strategy Confluence Engine
    # Uses 7 independent strategy signals; enters when ≥4 agree.
    # R:R and position size scale dynamically with the confluence score.
    # Trailing stop activates at 1R profit.
    # ====================================================================

    # ── Build HTF (1h) ATR + EMA50 bias lookup ────────────────────────────
    # Keyed by each candle's ms timestamp → used for proper SL sizing and
    # direction filter (only trade WITH the higher-timeframe trend).
    import bisect as _bisect
    _htf_atr_lu  = {}  # ts → 1h ATR value
    _htf_bias_lu = {}  # ts → 'BULL' or 'BEAR'

    if htf_candles and len(htf_candles) >= 20:
        _hc   = htf_candles
        _hcls = [float(c[4]) for c in _hc]
        _hhi  = [float(c[2]) for c in _hc]
        _hlo  = [float(c[3]) for c in _hc]
        _hatr = _atr_series(_hhi, _hlo, _hcls, 14)
        _hema = _ema_series(_hcls, 50)
        _hts  = sorted(
            [(int(_hc[j][0]), _hatr[j], _hema[j], _hcls[j])
             for j in range(len(_hc))],
            key=lambda x: x[0]
        )
        _hts_keys = [x[0] for x in _hts]
        for c5 in candles:
            ts5 = int(c5[0])
            idx = _bisect.bisect_right(_hts_keys, ts5) - 1
            if idx >= 0:
                _, h_atr, h_ema, h_cls = _hts[idx]
                if h_atr and h_ema:
                    _htf_atr_lu[ts5]  = h_atr
                    _htf_bias_lu[ts5] = 'BULL' if h_cls >= h_ema else 'BEAR'

    closes  = [float(c[4]) for c in candles]
    highs   = [float(c[2]) for c in candles]
    lows    = [float(c[3]) for c in candles]
    volumes = [float(c[5]) if len(c) > 5 and c[5] else 1.0 for c in candles]

    # ── Compute all strategy indicators ─────────────────────────────────
    ema9_s   = _ema_series(closes, 9)
    ema21_s  = _ema_series(closes, 21)
    ema50_s  = _ema_series(closes, 50)
    ema200_s = _ema_series(closes, 200)
    atr_s    = _atr_series(highs, lows, closes, 14)
    rsi_s    = _rsi_series(closes, 14)
    adx_s    = _adx_series(highs, lows, closes, 14)
    sma20_s  = _sma_series(closes, 20)
    macd_s   = _macd_line(closes, 12, 26)   # MACD line
    macd_sig = _ema_series(                  # MACD signal line
        [m if m is not None else 0.0 for m in macd_s], 9
    )
    bb_up, bb_mid, bb_lo = _bb_series(closes, 20, 2.0)

    # Allow learn-adjusted values to override hardcoded defaults
    _ucfg = user_cfg or {}
    CONFLUENCE_MIN  = int(_ucfg.get("confluence_min",  5))    # learn can lower this
    _DISP_BODY      = float(_ucfg.get("disp_body_ratio", DISP_BODY_RATIO))  # learn can adjust

    position       = None
    current_day    = None
    day_wins       = 0
    day_losses     = 0
    current_week   = None
    week_wins      = 0
    week_losses    = 0
    week_pnl       = 0.0
    week_paused    = False

    for i in range(WARMUP, len(candles)):
        e9    = ema9_s[i];  e21  = ema21_s[i];  e50  = ema50_s[i]
        e200  = ema200_s[i]
        atr_v = atr_s[i];   rsi_v = rsi_s[i];   adx_v = adx_s[i]
        sma20 = sma20_s[i]; mac   = macd_s[i];   mac_sig = macd_sig[i]

        # Skip bars with missing indicators
        if any(v is None for v in [e9, e21, e50, atr_v, rsi_v, adx_v, sma20, mac]) \
                or atr_v <= 0:
            continue

        close = closes[i]; hi = highs[i]; lo = lows[i]
        t_str = _str(candles[i][0])
        today = _date(candles[i][0])

        if today != current_day:
            current_day = today; day_wins = 0; day_losses = 0

        # ── Weekly reset ─────────────────────────────────────────────────
        dt_i     = datetime.utcfromtimestamp(int(candles[i][0]) / 1000)
        iso_week = dt_i.isocalendar()[:2]
        if iso_week != current_week:
            current_week = iso_week
            week_wins = 0; week_losses = 0; week_pnl = 0.0; week_paused = False

        # ── Manage open position with trailing stop ───────────────────────
        if position is not None:
            ep    = position["entry"]
            sl_p  = position["sl"]
            tp_p  = position["tp"]
            side  = position["side"]
            sz    = position["size"]
            trail = position.get("trailing_sl", sl_p)
            one_r = abs(ep - sl_p)

            exit_price = exit_reason = None

            if side == "BUY":
                if one_r > 0 and hi >= ep + one_r:
                    candidate = close - one_r * 0.5
                    if candidate > trail:
                        trail = candidate; position["trailing_sl"] = trail
                trail_active = trail > sl_p
                if trail_active and lo <= trail:
                    exit_price, exit_reason = trail, "Trailing stop"
                elif lo <= sl_p:
                    exit_price, exit_reason = sl_p, "Stop loss"
                elif hi >= tp_p:
                    exit_price, exit_reason = tp_p, "Take profit"
            else:
                if one_r > 0 and lo <= ep - one_r:
                    candidate = close + one_r * 0.5
                    if candidate < trail:
                        trail = candidate; position["trailing_sl"] = trail
                trail_active = trail < sl_p
                if trail_active and hi >= trail:
                    exit_price, exit_reason = trail, "Trailing stop"
                elif hi >= sl_p:
                    exit_price, exit_reason = sl_p, "Stop loss"
                elif lo <= tp_p:
                    exit_price, exit_reason = tp_p, "Take profit"

            if exit_price:
                gp  = ((exit_price - ep) if side == "BUY" else (ep - exit_price)) * sz
                fee = ep * sz * fee_rate * 2
                net = gp - fee
                balance += net          # ← FIX: was missing, caused net PnL = $0
                if net > 0: day_wins  += 1; week_wins   += 1
                else:       day_losses += 1; week_losses += 1
                week_pnl += net
                trades.append({
                    "side": side, "entry": round(ep, 6), "exit": round(exit_price, 6),
                    "pnl": round(net, 4),
                    "open_time": position["time"], "close_time": t_str,
                    "exit_reason": exit_reason,
                    "sl":  round(position["sl"],  6),
                    "tp":  round(position["tp"],  6),
                    "rr": position.get("rr", 3.0),
                    "sl_pct": position.get("sl_pct", 0),
                    "session": "Daily",
                    "confluence": position.get("confluence", 0),
                    "strategy_signals": position.get("strategy_signals", []),
                })
                position = None
                _wpct = week_pnl / float(starting_balance) * 100
                if (week_wins  >= weekly_win_goal or
                        _wpct  >= weekly_profit_target_pct or
                        _wpct  <= -weekly_max_loss_pct):
                    week_paused = True
            continue

        if day_losses >= MAX_LOSS_DAY or day_wins >= MAX_WINS_DAY:
            continue
        if week_paused:
            continue

        # ── Volume & ATR rolling averages (20-bar) ───────────────────────
        vol_lb  = volumes[max(0, i - 20):i]
        avg_vol = sum(vol_lb) / len(vol_lb) if vol_lb else 1.0
        atr_lb  = [x for x in atr_s[max(0, i - 20):i] if x is not None]
        avg_atr = sum(atr_lb) / len(atr_lb) if atr_lb else atr_v

        # ── EMA50 5-bar slope ────────────────────────────────────────────
        e50_prev = ema50_s[i - 5] if i >= 5 and ema50_s[i - 5] is not None else e50

        # ── HTF bias: use 1h EMA50 direction if available ────────────────
        # Falls back to EMA200 on same TF when no HTF candles were passed.
        _curr_ts_b   = int(candles[i][0])
        _htf_bias_v  = _htf_bias_lu.get(_curr_ts_b)  # 'BULL', 'BEAR', or None
        if _htf_bias_v == 'BULL':
            htf_ok_buy  = True;  htf_ok_sell = False
        elif _htf_bias_v == 'BEAR':
            htf_ok_buy  = False; htf_ok_sell = True
        else:
            # No HTF data → fall back to EMA200 on this timeframe
            htf_ok_buy  = (e200 is None) or (close > e200)
            htf_ok_sell = (e200 is None) or (close < e200)

        # ── Market activity gate: skip dead-flat bars ─────────────────────
        # Require ATR to be at least 60% of its 20-bar average
        if avg_atr > 0 and atr_v < avg_atr * 0.60:
            continue   # market too quiet — skip

        # ════════════════════════════════════════════════════════════════
        # CONFLUENCE SCORING  (9 signals, need ≥5 to enter)
        # More signals = higher conviction = wider R:R + larger position
        # ════════════════════════════════════════════════════════════════
        buy_signals  = []
        sell_signals = []

        # Signal 1 — EMA trend stack (all three aligned)
        if e9 > e21 > e50:
            buy_signals.append("EMA stack bullish")
        if e9 < e21 < e50:
            sell_signals.append("EMA stack bearish")

        # Signal 2 — ADX trend strength (market is trending, not flat)
        if adx_v >= 18:
            buy_signals.append("ADX trending")
            sell_signals.append("ADX trending")

        # Signal 3 — RSI in healthy momentum zone (wider for more signals)
        if 40 < rsi_v < 72:
            buy_signals.append("RSI healthy bull")
        if 28 < rsi_v < 60:
            sell_signals.append("RSI healthy bear")

        # Signal 4 — EMA50 slope (trend direction confirmed over 5 bars)
        if e50 > e50_prev:
            buy_signals.append("EMA50 rising")
        if e50 < e50_prev:
            sell_signals.append("EMA50 falling")

        # Signal 5 — MACD line above/below zero (momentum direction)
        if mac > 0:
            buy_signals.append("MACD bullish")
        if mac < 0:
            sell_signals.append("MACD bearish")

        # Signal 6 — Price vs SMA20 (medium-term trend filter)
        if close > sma20:
            buy_signals.append("Above SMA20")
        if close < sma20:
            sell_signals.append("Below SMA20")

        # Signal 7 — ATR expansion: trade when market is actively moving
        # This directly targets the "more market movement" requirement
        if avg_atr > 0 and atr_v >= avg_atr * 1.05:
            buy_signals.append("ATR expanding — market active")
            sell_signals.append("ATR expanding — market active")

        # Signal 8 — Bollinger Band position (price above/below midline)
        bb_m = bb_mid[i]
        if bb_m is not None and close > bb_m:
            buy_signals.append("Above BB midline")
        if bb_m is not None and close < bb_m:
            sell_signals.append("Below BB midline")

        # Signal 9 (bonus) — EMA200 HTF alignment when data available
        if e200 is not None and close > e200:
            buy_signals.append("Above EMA200 HTF")
        if e200 is not None and close < e200:
            sell_signals.append("Below EMA200 HTF")

        # ── Determine direction from confluence ───────────────────────────
        buy_score  = len(buy_signals)
        sell_score = len(sell_signals)

        direction = None
        score     = 0
        signals   = []

        if buy_score >= CONFLUENCE_MIN and buy_score > sell_score and htf_ok_buy:
            direction = "BUY";  score = buy_score;  signals = buy_signals
        elif sell_score >= CONFLUENCE_MIN and sell_score > buy_score and htf_ok_sell:
            direction = "SELL"; score = sell_score; signals = sell_signals

        if not direction:
            continue

        # ── Dynamic R:R and position sizing based on score ────────────────
        dyn_rr      = _dynamic_rr(score, adx_val=adx_v)
        risk_pct    = _dynamic_risk_pct(score)
        risk_dollar_dyn = balance * risk_pct

        # ── SL distance: use HTF ATR when available; hard minimum 0.5% ──
        _atr_mult_b = float((_ucfg or {}).get("atr_multiplier", 1.5))
        _htf_atr_v  = _htf_atr_lu.get(_curr_ts_b)
        if _htf_atr_v and _htf_atr_v > 0:
            # 1h ATR × multiplier — properly wide, respects real market noise
            sl_dist = max(_htf_atr_v * _atr_mult_b, close * 0.003)
        else:
            # No HTF data: use current-TF ATR but enforce 0.5% minimum
            # (was 0.1% — way too tight, caused constant stop-outs)
            sl_dist = max(atr_v * _atr_mult_b, close * 0.005)
        ep       = close * (1 + slip_rate) if direction == "BUY" else close * (1 - slip_rate)
        sl_p     = ep - sl_dist if direction == "BUY" else ep + sl_dist
        tp_p     = ep + sl_dist * dyn_rr if direction == "BUY" else ep - sl_dist * dyn_rr
        sz       = risk_dollar_dyn / sl_dist if sl_dist > 0 else 0
        rr_calc  = round(abs(tp_p - ep) / abs(ep - sl_p), 2) if abs(ep - sl_p) > 0 else dyn_rr
        sl_pct   = round(abs(ep - sl_p) / ep * 100, 3) if ep > 0 else 0

        position = {
            "side": direction, "entry": ep, "sl": sl_p, "tp": tp_p,
            "size": sz, "time": t_str,
            "trailing_sl": sl_p,
            "rr": rr_calc, "sl_pct": sl_pct,
            "confluence": score, "strategy_signals": signals,
        }

    return trades, balance


# ─────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────

@app.route("/api/health")
def health():
    polygon_key = os.environ.get("POLYGON_API_KEY", "")
    return jsonify({"ok": True, "time": now_str(), "polygon_key": bool(polygon_key)})


@app.route("/api/symbols", methods=["GET"])
def get_symbols():
    symbol_market = {sym: mkt for mkt, syms in MARKETS.items() for sym in syms}
    return jsonify({
        "symbols":       ALL_SYMBOLS,
        "markets":       MARKETS,
        "symbol_market": symbol_market,
    })


@app.route("/api/signals", methods=["GET"])
@auth_required
def signals():
    cfg      = get_user_config()
    strategy = request.args.get("strategy", "bot").lower()
    out      = []
    errors   = []

    fresh, needs_fetch = [], []
    for sym in ALL_SYMBOLS:
        cache_key = (sym, strategy, SIGNALS_INTERVAL)
        cached = _cache_get(_summary_cache, cache_key, SUMMARY_TTL_SECONDS)
        if cached is not None:
            fresh.append(cached)
        else:
            needs_fetch.append(sym)

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

    order = {sym: i for i, sym in enumerate(ALL_SYMBOLS)}
    out.sort(key=lambda s: order.get(s["symbol"], 999))

    weekly = {}
    try:
        weekly = is_weekly_paused(g.user_id, cfg)
    except Exception:
        pass

    return jsonify({
        "signals":     out,
        "last_update": now_str(),
        "errors":      errors,
        "config":      cfg,
        "weekly":      weekly,
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
    Section 7: random_window defaults to False, period_days defaults to 30,
               max period_days raised to 90.
    """
    data = request.get_json(force=True) or {}

    symbol      = str(data.get("symbol",      "BTCUSDT")).upper()
    interval    = str(data.get("interval",    "5m"))
    strategy    = str(data.get("strategy",    "unified_bot")).lower()
    period_days = max(2, min(int(data.get("period_days", 30)), 90))   # default 30, max 90
    rand_window = bool(data.get("random_window", False))               # default False
    sb          = float(data.get("starting_balance", 1000))
    fee_pct     = float(data.get("fee_percent",       0.04))
    slip_pct    = float(data.get("slippage_percent",  0.02))
    # Out-of-sample split: 0 = no split, 0.7 = 70% train / 30% test
    train_pct   = max(0.0, min(float(data.get("train_pct", 0.70)), 0.95))

    market = detect_market(symbol)

    if symbol not in ALL_SYMBOLS:
        return jsonify({
            "error": f"Symbol '{symbol}' is not supported. "
                     f"Supported symbols: {ALL_SYMBOLS}"
        }), 400

    valid_intervals = ["1m", "5m", "15m", "1h", "4h"]
    if interval not in valid_intervals:
        return jsonify({
            "error": f"Interval '{interval}' is not supported. "
                     f"Use one of: {valid_intervals}"
        }), 400

    actual_interval = interval
    start_date = end_date = None

    try:
        if market == "crypto":
            iv_minutes  = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}[interval]
            # Full candle count for the period (no artificial cap — pagination handles it)
            target_rows = int(period_days * 24 * 60 / iv_minutes)
            period_ms   = period_days * 24 * 60 * 60 * 1000
            now_utc     = datetime.now(timezone.utc)

            if rand_window:
                earliest     = MARKET_EARLIEST["crypto"]
                latest_end   = now_utc - timedelta(hours=1)
                latest_start = latest_end - timedelta(days=period_days)
                if latest_start > earliest:
                    span   = int((latest_start - earliest).total_seconds())
                    offset = random.randint(0, span)
                    start_dt = earliest + timedelta(seconds=offset)
                else:
                    start_dt = earliest
                end_dt = start_dt + timedelta(days=period_days)
            else:
                end_ms   = int(now_utc.timestamp() * 1000)
                start_ms = end_ms - period_ms
                start_dt = datetime.utcfromtimestamp(start_ms / 1000)
                end_dt   = datetime.utcfromtimestamp(end_ms   / 1000)

            start_ms   = int(start_dt.timestamp() * 1000)
            end_ms     = int(end_dt.timestamp()   * 1000)
            start_date = start_dt.strftime("%Y-%m-%d")
            end_date   = end_dt.strftime("%Y-%m-%d")

            # Paginated fetch — overcomes Binance 1000-candle per-request limit
            candles = fetch_binance_range_paginated(
                symbol, interval, start_ms, end_ms, max_candles=target_rows
            )

            if not candles or len(candles) < 60:
                return jsonify({
                    "error": (
                        f"Binance returned only {len(candles)} candles for "
                        f"{symbol} {interval} ({start_date} → {end_date}). "
                        f"Need ≥ 60. Try a longer period_days or a different symbol."
                    )
                }), 400

        else:
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

    # ── Train / test split index ─────────────────────────────────────────────
    # Parameter tuning (auto-learn/optimise) sees ONLY train candles.
    # Metrics reported to the user come from the TEST (held-out) portion.
    _split_idx    = int(len(candles) * train_pct) if train_pct > 0 else len(candles)
    _split_idx    = max(50, min(_split_idx, len(candles) - 1))
    _split_ts_ms  = int(candles[_split_idx][0])   # ms timestamp at the boundary
    _split_ts_sec = _split_ts_ms / 1000.0

    cfg = get_user_config()
    _ww_goal = cfg.get("weekly_win_goal",             3)
    _wpt_pct = cfg.get("weekly_profit_target_percent", 3.0)
    _wml_pct = cfg.get("weekly_max_loss_percent",      0.8)

    # ── Fetch 1h HTF candles for proper SL sizing + trend bias filter ────────
    # Only for crypto (Binance). Non-crypto uses Polygon daily bars (already HTF).
    htf_candles = None
    if market == "crypto" and strategy in ("unified_bot", "bot"):
        try:
            htf_start_ms = int((start_dt - timedelta(days=5)).timestamp() * 1000)
            htf_candles  = fetch_binance_range_paginated(
                symbol, "1h", htf_start_ms, end_ms,
                max_candles=period_days * 25 + 150
            )
        except Exception as _htf_err:
            print(f"[backtest] HTF 1h fetch skipped: {_htf_err}")

    try:
        if strategy in ("unified_bot", "bot"):   # "bot" kept as legacy alias
            trades, ending_balance = run_unified_bot_strategy(
                candles, sb, fee_pct, slip_pct,
                weekly_win_goal=_ww_goal,
                weekly_profit_target_pct=_wpt_pct,
                weekly_max_loss_pct=_wml_pct,
                user_cfg=cfg,
                htf_candles=htf_candles,  # 1h candles for MTF SL + bias
            )
        elif strategy == "orb_0dte":
            trades, ending_balance = run_orb_strategy(candles, sb, fee_pct, slip_pct)
        elif strategy == "vwap_ema":
            trades, ending_balance = run_vwap_ema_strategy(candles, sb, fee_pct, slip_pct)
        else:
            trades, ending_balance = run_simple_ma_strategy(
                candles, sb, fee_pct, slip_pct,
                weekly_win_goal=_ww_goal,
                weekly_profit_target_pct=_wpt_pct,
                weekly_max_loss_pct=_wml_pct,
            )
    except Exception as e:
        return jsonify({
            "error": f"Strategy '{strategy}' crashed: {e}. "
                     f"Candles available: {len(candles)}"
        }), 500

    # ── Normalize trade field names so frontend always gets consistent keys ──
    def _parse_ts(s):
        """Parse 'YYYY-MM-DD HH:MM' or ISO string → epoch seconds, or 0."""
        if not s:
            return 0
        try:
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return int(datetime.strptime(str(s), fmt).replace(tzinfo=timezone.utc).timestamp())
                except ValueError:
                    continue
            return int(int(s) / 1000) if str(s).isdigit() else 0
        except Exception:
            return 0

    for t in trades:
        # ── Convert raw integer timestamps to human-readable strings ─────────
        # EMA fallback & ICT path store candle[0] (Binance ms timestamp) directly.
        # JavaScript's String.slice() crashes on numbers → convert here once.
        for _tk in ("entry_time", "exit_time", "open_time", "close_time", "time"):
            _v = t.get(_tk)
            if isinstance(_v, (int, float)) and _v > 1_000_000_000:
                t[_tk] = _ts_to_str(int(_v))

        # Unify open_time / entry_time
        if "open_time" not in t:
            t["open_time"]  = t.get("entry_time", "")
        if "entry_time" not in t:
            t["entry_time"] = t["open_time"]
        # Unify close_time / exit_time
        if "close_time" not in t:
            t["close_time"] = t.get("exit_time", "")
        if "exit_time" not in t:
            t["exit_time"]  = t["close_time"]
        # Unify exit_reason / reason
        if "exit_reason" not in t:
            t["exit_reason"] = t.get("reason", "")
        if "reason" not in t:
            t["reason"] = t["exit_reason"]
        # Compute duration_seconds
        if "duration_seconds" not in t:
            ts_open  = _parse_ts(t.get("open_time")  or t.get("entry_time"))
            ts_close = _parse_ts(t.get("close_time") or t.get("exit_time"))
            t["duration_seconds"] = max(0, ts_close - ts_open)
        # Ensure rr, sl_pct, session, confluence always present
        t.setdefault("rr",         0)
        t.setdefault("sl_pct",     0)
        t.setdefault("session",    "—")
        t.setdefault("confluence", 0)

    # ── Full-run metrics (used for DB storage and chart) ─────────────────────
    total   = len(trades)
    wins    = [t for t in trades if t["pnl"] > 0]
    losses  = [t for t in trades if t["pnl"] <= 0]
    net_pnl = ending_balance - sb

    win_rate     = (len(wins) / total * 100) if total else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))
    pf           = (gross_profit / gross_loss) if gross_loss else 0

    # ── Train / test split metrics ────────────────────────────────────────────
    # Trades are split at _split_ts_sec (set earlier from the candle boundary).
    # All reported win-rate / PF figures come from the TEST portion only.
    _MIN_MEANINGFUL = 30  # minimum trades for statistics to be meaningful

    def _split_metrics(trade_list):
        if not trade_list:
            return {
                "total_trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "profit_factor": 0.0,
                "net_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
            }
        _wins   = [t for t in trade_list if t["pnl"] > 0]
        _losses = [t for t in trade_list if t["pnl"] <= 0]
        _gp  = sum(t["pnl"] for t in _wins)
        _gl  = abs(sum(t["pnl"] for t in _losses))
        _wr  = len(_wins) / len(trade_list) * 100 if trade_list else 0
        _pf  = (_gp / _gl) if _gl else (1.0 if _gp > 0 else 0.0)
        return {
            "total_trades":  len(trade_list),
            "wins":          len(_wins),
            "losses":        len(_losses),
            "win_rate":      round(_wr, 2),
            "profit_factor": round(_pf, 2),
            "net_pnl":       round(sum(t["pnl"] for t in trade_list), 2),
            "gross_profit":  round(_gp, 2),
            "gross_loss":    round(_gl, 2),
        }

    train_trades = [t for t in trades if _parse_ts(t.get("open_time") or t.get("entry_time")) < _split_ts_sec]
    test_trades  = [t for t in trades if _parse_ts(t.get("open_time") or t.get("entry_time")) >= _split_ts_sec]

    train_m = _split_metrics(train_trades)
    test_m  = _split_metrics(test_trades)

    # Low-sample warning: fewer than 30 test-period trades → stats unreliable
    low_sample_warning = len(test_trades) < _MIN_MEANINGFUL
    low_sample_msg = (
        f"Only {len(test_trades)} trades in the test window "
        f"(need ≥ {_MIN_MEANINGFUL} for reliable statistics). "
        "Run a longer period or adjust the train/test split."
    ) if low_sample_warning else None

    start_ts = candles[0][0]
    end_ts   = candles[-1][0]
    days     = max(1, (int(end_ts) - int(start_ts)) / (1000 * 60 * 60 * 24))

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

    # ── Auto-learn: silently analyse recent runs and adjust config ────────────
    auto_learn = _auto_learn_silent(g.user_id)

    split_date = _ts_to_str(int(_split_ts_ms))[:10]   # "YYYY-MM-DD"

    summary = {
        # ── Full-run figures (backward-compat) ─────────────────────────
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
        # ── Out-of-sample validation ────────────────────────────────────
        "train_pct":            train_pct,
        "split_date":           split_date,
        "train_summary":        train_m,
        "test_summary":         test_m,
        "low_sample_warning":   low_sample_warning,
        "low_sample_msg":       low_sample_msg,
        "random_window":        rand_window,
    }

    # Sample up to 400 candles for the chart (keep response size reasonable)
    _step = max(1, len(candles) // 400)
    candles_chart = [
        {
            "t": int(c[0]),
            "o": round(float(c[1]), 6),
            "h": round(float(c[2]), 6),
            "l": round(float(c[3]), 6),
            "c": round(float(c[4]), 6),
        }
        for c in candles[::_step]
    ]

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
        "candles_chart":  candles_chart,
        "auto_learn":     auto_learn,
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
        "atr_multiplier", "enable_trailing_stop", "enable_fallback_strategy",
    ]:
        if k in data:
            cfg[k] = data[k]
    if "symbols" in data and isinstance(data["symbols"], list):
        cfg["symbols"] = [s.upper() for s in data["symbols"] if isinstance(s, str)]
    if "blocked_crypto_hours_utc" in data and isinstance(data["blocked_crypto_hours_utc"], list):
        cfg["blocked_crypto_hours_utc"] = data["blocked_crypto_hours_utc"]
    if "blocked_sessions" in data and isinstance(data["blocked_sessions"], list):
        cfg["blocked_sessions"] = data["blocked_sessions"]
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


@app.route("/api/paper/positions", methods=["GET"])
@auth_required
def paper_positions():
    """Return open positions with live-refreshed P&L."""
    conn = get_conn(); c = conn.cursor()
    c.execute(
        """SELECT id, symbol, type, entry, sl, tp, size, time
           FROM trades WHERE user_id=%s AND status='OPEN'
           ORDER BY time DESC""",
        (g.user_id,))
    rows = c.fetchall()
    positions = []
    for trade_id, symbol, side, entry, sl, tp, size, t in rows:
        try:
            price   = get_latest_price(symbol)
            pnl     = (price - entry) * size if side == "BUY" else (entry - price) * size
            pnl_pct = (pnl / (entry * size) * 100) if entry and size else 0
            c.execute("UPDATE trades SET pnl=%s WHERE id=%s", (round(pnl, 4), trade_id))
            positions.append({
                "id": trade_id, "symbol": symbol, "side": side,
                "entry": entry, "current_price": round(price, 6),
                "sl": sl, "tp": tp, "size": size,
                "pnl": round(pnl, 4), "pnl_pct": round(pnl_pct, 2),
                "time": str(t),
            })
        except Exception as e:
            positions.append({
                "id": trade_id, "symbol": symbol, "side": side,
                "entry": entry, "current_price": entry,
                "sl": sl, "tp": tp, "size": size,
                "pnl": 0, "pnl_pct": 0, "time": str(t), "error": str(e),
            })
    conn.commit(); conn.close()
    return jsonify(positions)


@app.route("/api/paper/summary", methods=["GET"])
@auth_required
def paper_summary():
    """Account summary: balance, P&L breakdown, win rate, bot status."""
    conn = get_conn(); c = conn.cursor()
    c.execute(
        """SELECT id, symbol, type, entry, exit, pnl, status, time
           FROM trades WHERE user_id=%s ORDER BY time DESC LIMIT 500""",
        (g.user_id,))
    rows = c.fetchall(); conn.close()

    cfg              = get_user_config()
    starting_balance = float(cfg.get("starting_balance", 10000))

    all_trades = [
        {"id": r[0], "symbol": r[1], "side": r[2], "entry": r[3],
         "exit": r[4], "pnl": float(r[5] or 0), "status": r[6], "time": str(r[7])}
        for r in rows
    ]
    closed    = [t for t in all_trades if t["status"] == "CLOSED"]
    open_pos  = [t for t in all_trades if t["status"] == "OPEN"]

    realized   = sum(t["pnl"] for t in closed)
    unrealized = sum(t["pnl"] for t in open_pos)

    wins    = [t for t in closed if t["pnl"] > 0]
    losses  = [t for t in closed if t["pnl"] <= 0]
    gp      = sum(t["pnl"] for t in wins)
    gl      = abs(sum(t["pnl"] for t in losses))
    wr      = len(wins) / len(closed) * 100 if closed else 0
    pf      = gp / gl if gl else 0

    return jsonify({
        "starting_balance": starting_balance,
        "current_balance":  round(starting_balance + realized, 2),
        "realized_pnl":     round(realized, 2),
        "unrealized_pnl":   round(unrealized, 4),
        "total_closed":     len(closed),
        "open_positions":   len(open_pos),
        "win_rate":         round(wr, 2),
        "profit_factor":    round(pf, 2),
        "wins":             len(wins),
        "losses":           len(losses),
        "bot_active":       AUTO_PAPER_TRADING.get(g.user_id, False),
    })


@app.route("/api/paper/bot-scan", methods=["POST", "OPTIONS"])
@auth_required
def paper_bot_scan():
    """
    Scan watched symbols for live signals.
    When bot is active (or force=true in body), auto-opens trades for
    BUY/SELL signals that pass confidence + R:R gates and have no open position.
    Always returns JSON — never raises to Flask's HTML error handler.
    """
    try:
        data       = request.get_json(force=True) or {}
        force_open = bool(data.get("force", False))

        # ── Load config safely ────────────────────────────────────────────
        try:
            cfg = get_user_config()
        except Exception:
            cfg = dict(DEFAULT_CONFIG)

        symbols = (cfg.get("symbols") or ALL_SYMBOLS)[:12]

        min_conf   = int(cfg.get("min_confidence", 70))
        bot_active = AUTO_PAPER_TRADING.get(g.user_id, False)

        # ── Already-open symbols → skip to prevent pyramiding ─────────────
        open_symbols = set()
        try:
            conn = get_conn(); c = conn.cursor()
            c.execute("SELECT symbol FROM trades WHERE user_id=%s AND status='OPEN'", (g.user_id,))
            open_symbols = {row[0] for row in c.fetchall()}
            conn.close()
        except Exception:
            pass  # If DB fails, allow scan but don't gate on open positions

        weekly = {}
        try:
            weekly = is_weekly_paused(g.user_id, cfg)
        except Exception:
            pass

        scan_results, opened, skipped = [], [], []

        for sym in symbols:
            try:
                s = get_symbol_summary(sym, "bot", SIGNALS_INTERVAL, cfg)
                if not s:
                    continue
                signal     = s.get("signal", "HOLD")
                confidence = float(s.get("confidence") or 0)
                price_val  = float(s.get("price") or 0)

                scan_results.append({
                    "symbol":     sym,
                    "signal":     signal,
                    "confidence": confidence,
                    "price":      price_val,
                })

                should_trade = (bot_active or force_open) and signal in ("BUY", "SELL")
                if not should_trade:
                    continue
                if confidence < min_conf:
                    skipped.append({"symbol": sym, "reason": "low_confidence", "confidence": confidence})
                    continue
                if sym in open_symbols:
                    skipped.append({"symbol": sym, "reason": "already_open"})
                    continue
                if weekly.get("weekly_trading_paused"):
                    skipped.append({"symbol": sym, "reason": "weekly_pause"})
                    continue

                df = fetch_df_for_symbol(sym, SIGNALS_INTERVAL, 200)
                if df is None:
                    skipped.append({"symbol": sym, "reason": "no_data"})
                    continue

                levels = calculate_trade_levels(
                    df, signal, cfg.get("risk_reward", 2),
                    cfg.get("atr_multiplier", 1.5), cfg
                )
                if not levels.get("rr_valid"):
                    skipped.append({"symbol": sym, "reason": "rr_invalid",
                                     "rr": levels.get("rr")})
                    continue

                ep       = levels["entry"]
                sd       = levels["sl_distance"]
                risk_amt = starting_balance_for(g.user_id, cfg) * (cfg.get("risk_percent", 1) / 100)
                size     = risk_amt / sd if sd else 0

                tid = str(uuid.uuid4())
                conn = get_conn(); cu = conn.cursor()
                cu.execute(
                    "INSERT INTO trades VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,'OPEN',%s)",
                    (tid, g.user_id, sym, signal, ep, levels["sl"], levels["tp"], size, now_str()))
                conn.commit(); conn.close()
                add_alert(g.user_id,
                          f"BOT OPEN {sym} {signal} @ {format_price(ep, sym)} "
                          f"(conf {confidence:.0f}%)")
                open_symbols.add(sym)
                opened.append({
                    "id": tid, "symbol": sym, "side": signal,
                    "entry": ep, "sl": levels["sl"], "tp": levels["tp"],
                    "confidence": confidence,
                })
            except Exception as e:
                scan_results.append({"symbol": sym, "signal": "ERROR", "error": str(e)})

        return jsonify({
            "ok":         True,
            "scanned":    len(scan_results),
            "signals":    scan_results,
            "opened":     opened,
            "skipped":    skipped,
            "bot_active": bot_active,
            "scanned_at": now_str(),
        })

    except Exception as e:
        import traceback
        return jsonify({
            "ok":     False,
            "error":  str(e),
            "detail": traceback.format_exc()[-400:],
        }), 500


def starting_balance_for(user_id, cfg):
    """Return effective starting balance considering realized P&L."""
    return float(cfg.get("starting_balance", 10000))


@app.route("/api/paper/reset", methods=["POST", "OPTIONS"])
@auth_required
def paper_reset():
    """Wipe all paper trades and reset the account to starting balance."""
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM trades WHERE user_id=%s", (g.user_id,))
    conn.commit(); conn.close()
    AUTO_PAPER_TRADING[g.user_id] = False
    add_alert(g.user_id, "Paper account reset — all trades cleared")
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# LIVE CANDLE DATA (for frontend charts)
# ─────────────────────────────────────────────

@app.route("/api/candles", methods=["GET"])
@auth_required
def api_candles():
    """
    Return recent OHLC candles for a symbol in {t,o,h,l,c} format.
    Used by the Paper Trading chart and any other live chart widget.
    Query params: symbol, interval (default 5m), limit (default 300, max 1000)
    """
    try:
        symbol   = (request.args.get("symbol") or "BTCUSDT").upper().strip()
        interval = request.args.get("interval", "5m")
        limit    = max(10, min(int(request.args.get("limit", 300)), 1000))

        df = fetch_df_for_symbol(symbol, interval, limit)
        if df is None:
            return jsonify({"error": f"No market data available for {symbol}"}), 404

        candles = [
            {
                "t": int(row["timestamp"]),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
            }
            for _, row in df.iterrows()
        ]
        return jsonify({
            "symbol":   symbol,
            "interval": interval,
            "candles":  candles,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    cfg  = get_user_config()

    # ── Weekly pause gate ─────────────────────────────────────────────
    weekly = is_weekly_paused(g.user_id, cfg)
    if weekly["weekly_trading_paused"]:
        return jsonify({
            "error":          "Weekly trading paused",
            "pause_reason":   weekly["pause_reason"],
            "weekly_trading_paused": True,
            "weekly":         weekly,
        }), 403

    df = fetch_df_for_symbol(sym, SIGNALS_INTERVAL, 200)
    if df is None:
        return jsonify({"error": f"No market data for {sym}"}), 400

    levels = calculate_trade_levels(df, side, cfg.get("risk_reward", 2),
                                    cfg.get("atr_multiplier", 1.5), cfg)

    # ── R:R quality gate ──────────────────────────────────────────────
    if not levels["rr_valid"]:
        return jsonify({
            "error":            "Trade rejected — R:R quality check failed",
            "rejection_reason": levels["rejection_reason"],
            "rr":               levels["rr"],
            "sl_pct":           levels["sl_pct"],
            "rr_valid":         False,
        }), 422

    price     = levels["entry"]
    stop_dist = levels["sl_distance"]
    risk_amt  = cfg["starting_balance"] * (cfg.get("risk_percent", 1) / 100)
    size      = risk_amt / stop_dist if stop_dist else 0

    tid  = str(uuid.uuid4())
    conn = get_conn(); c = conn.cursor()
    c.execute(
        "INSERT INTO trades VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,'OPEN',%s)",
        (tid, g.user_id, sym, side, price, levels["sl"], levels["tp"], size, now_str()))
    conn.commit(); conn.close()
    add_alert(g.user_id, f"OPEN {sym} {side} @ {format_price(price, sym)}")
    return jsonify({
        "ok":    True, "id": tid,
        "entry": price, "sl": levels["sl"], "tp": levels["tp"],
        "size":  size,  "rr": levels["rr"],
        "sl_pct": levels["sl_pct"], "rr_valid": True,
    })


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
    rows   = c.fetchall()
    conn.close()
    pnls   = [float(r[0] or 0) for r in rows]
    total  = len(pnls)
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    cfg    = get_user_config()
    kelly  = _kelly_fraction(
        [{"pnl": p} for p in pnls],
        default=cfg.get("risk_percent", 1) / 100,
    )
    avg_win  = round(sum(wins)  / len(wins),   2) if wins   else 0
    avg_loss = round(sum(losses)/ len(losses), 2) if losses else 0
    return jsonify({
        "total_trades":     total,
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate":         round(len(wins) / total * 100, 2) if total else 0,
        "net_pnl":          round(sum(pnls), 2),
        "balance":          round(cfg["starting_balance"] + sum(pnls), 2),
        "starting_balance": cfg["starting_balance"],
        "avg_win":          avg_win,
        "avg_loss":         avg_loss,
        "kelly_fraction":   round(kelly * 100, 2),   # expressed as % of account
        "kelly_note":       "Half-Kelly — suggested max risk % per trade",
    })


# ─────────────────────────────────────────────
# WEEKLY STATS
# ─────────────────────────────────────────────

@app.route("/api/weekly-stats", methods=["GET"])
@auth_required
def weekly_stats_route():
    cfg = get_user_config()
    return jsonify(is_weekly_paused(g.user_id, cfg))


# ─────────────────────────────────────────────
# MONTE CARLO SIMULATION
# ─────────────────────────────────────────────

@app.route("/api/monte-carlo", methods=["POST", "OPTIONS"])
@auth_required
def monte_carlo():
    """
    Block-bootstrap Monte Carlo over a list of trade PnL values.
    Body: { "pnl_list": [...], "starting_balance": 10000, "iterations": 5000 }
    Uses blocks of 5 trades to preserve serial correlation.
    """
    body      = request.get_json(silent=True) or {}
    pnl_list  = [float(x) for x in body.get("pnl_list", [])]
    balance0  = float(body.get("starting_balance", 10000))
    iters     = min(int(body.get("iterations", 5000)), 10000)

    if len(pnl_list) < 5:
        return jsonify({"error": "Need at least 5 trades"}), 400

    import random as _rnd
    n           = len(pnl_list)
    block_size  = 5
    finals      = []
    max_dds     = []

    for _ in range(iters):
        sample = []
        while len(sample) < n:
            start = _rnd.randint(0, max(0, n - block_size))
            sample.extend(pnl_list[start:start + block_size])
        sample = sample[:n]

        bal  = balance0
        peak = bal
        mdd  = 0.0
        for pnl in sample:
            bal += pnl
            if bal > peak:
                peak = bal
            dd = (peak - bal) / peak if peak > 0 else 0.0
            if dd > mdd:
                mdd = dd
        finals.append(bal)
        max_dds.append(mdd * 100)

    finals.sort()
    max_dds.sort()

    def pct(lst, p):
        return round(lst[max(0, min(int(len(lst) * p / 100), len(lst) - 1))], 2)

    return jsonify({
        "iterations":          iters,
        "starting_balance":    balance0,
        "mean_final":          round(sum(finals) / len(finals), 2),
        "median_final":        pct(finals, 50),
        "p10_final":           pct(finals, 10),
        "p25_final":           pct(finals, 25),
        "p75_final":           pct(finals, 75),
        "p90_final":           pct(finals, 90),
        "profit_probability":  round(sum(1 for b in finals if b > balance0) / iters * 100, 1),
        "ruin_probability":    round(sum(1 for b in finals if b < balance0 * 0.5) / iters * 100, 1),
        "median_max_drawdown": pct(max_dds, 50),
        "p90_max_drawdown":    pct(max_dds, 90),
    })


# ─────────────────────────────────────────────
# SECTION 1: SELF-LEARNING SYSTEM
# ─────────────────────────────────────────────

def _analyze_losing_trades(losing_trades, backtest_runs, cfg):
    """
    Pure rule-based analysis of losing trades across recent backtest runs.
    Returns {"patterns": [...], "adjustments": {...}}
    Keys prefixed "_r_" carry human-readable reasons and are stripped before
    the response is sent to the client.
    """
    patterns    = []
    adjustments = {}
    total       = len(losing_trades)

    if total == 0:
        return {
            "patterns":    ["No losing trades found across the analyzed runs."],
            "adjustments": {},
        }

    # ── 1. Session & hour clustering ──────────────────────────────────
    session_counts = {"London": 0, "New York": 0, "Asia": 0}
    hour_counts    = {}

    for t in losing_trades:
        raw = t.get("entry_time", "")
        try:
            dt  = datetime.strptime(str(raw)[:19], "%Y-%m-%d %H:%M:%S")
            h   = dt.hour
            hour_counts[h] = hour_counts.get(h, 0) + 1
            sn  = get_session_name(dt)
            session_counts[sn] = session_counts.get(sn, 0) + 1
        except Exception:
            pass

    for session, count in session_counts.items():
        pct = count / total
        if pct >= 0.70:
            patterns.append(
                f"{count}/{total} losses ({round(pct*100)}%) occurred in "
                f"{session} session"
            )
            if session == "Asia":
                blocked = set(cfg.get("blocked_crypto_hours_utc", []))
                blocked |= set(range(0, 8))
                adjustments["blocked_crypto_hours_utc"] = sorted(blocked)
                adjustments["_r_blocked_hours"] = (
                    "70%+ losses in Asia session → hours 0–7 UTC added to blocked list"
                )
            else:
                bs = list(cfg.get("blocked_sessions", []))
                if session not in bs:
                    bs.append(session)
                adjustments["blocked_sessions"] = bs
                adjustments["_r_blocked_sessions"] = (
                    f"70%+ losses in {session} session → session blocked"
                )

    # Hour-level: any 3-hour UTC window with 60%+ of losses
    if total >= 5:
        for start_h in range(24):
            window = {start_h % 24, (start_h + 1) % 24, (start_h + 2) % 24}
            wcount = sum(hour_counts.get(h, 0) for h in window)
            if wcount / total >= 0.60:
                end_h = (start_h + 2) % 24
                patterns.append(
                    f"{wcount}/{total} losses clustered in the "
                    f"{start_h:02d}:00–{end_h:02d}:59 UTC window"
                )
                break

    # ── 2. Stop-loss tightness ────────────────────────────────────────
    sl_losses = [t for t in losing_trades
                 if "stop" in t.get("reason", "").lower()]
    if sl_losses:
        tight = sum(
            1 for t in sl_losses
            if float(t.get("entry") or 0) > 0
            and abs(float(t.get("exit") or 0) - float(t.get("entry") or 0))
               / float(t.get("entry") or 1) * 100 < 0.3
        )
        tight_pct = tight / len(sl_losses)
        if tight_pct >= 0.60:
            patterns.append(
                f"{tight}/{len(sl_losses)} stop-loss exits within 0.3% of entry "
                f"({round(tight_pct*100)}%) — SL consistently too tight"
            )
            cur_rr = float(cfg.get("risk_reward", 2))
            adjustments["risk_reward"] = round(cur_rr + 0.5, 1)
            adjustments["_r_rr"] = (
                f"Tight SL pattern → risk_reward {cur_rr} → "
                f"{round(cur_rr + 0.5, 1)}"
            )
    else:
        sl_losses = []  # ensure defined

    # ── 3. High SL hit rate → raise min_confidence ───────────────────
    sl_rate = len(sl_losses) / total
    if sl_rate >= 0.70:
        patterns.append(
            f"{round(sl_rate*100)}% of losing trades hit stop loss — "
            f"entries may lack sufficient conviction"
        )
        cur_conf = int(cfg.get("min_confidence", 70))
        if "min_confidence" not in adjustments and cur_conf < 88:
            adjustments["min_confidence"] = cur_conf + 5
            adjustments["_r_conf"] = (
                f"High SL hit rate → min_confidence {cur_conf} → {cur_conf + 5}"
            )

    # ── 4a. Zero trades in most runs → filters too restrictive ──────────
    wrs = [float(r.get("win_rate") or 0) for r in backtest_runs]
    zero_trade_runs = [r for r in backtest_runs if int(r.get("total_trades", 0) if "total_trades" in r else 0) == 0]
    if len(zero_trade_runs) >= max(1, len(backtest_runs) * 0.6):
        cur_cm = int(cfg.get("confluence_min", 5))
        new_cm = max(3, cur_cm - 1)   # relax threshold, floor at 3
        if new_cm < cur_cm:
            patterns.append(
                f"{len(zero_trade_runs)}/{len(backtest_runs)} runs placed 0 trades "
                f"— entry filters too restrictive, reducing confluence requirement"
            )
            adjustments["confluence_min"] = new_cm
            adjustments["_r_confluence"] = (
                f"0-trade runs → confluence_min {cur_cm} → {new_cm}"
            )
        # Also relax DISP_BODY_RATIO for PATH A
        cur_db = float(cfg.get("disp_body_ratio", 0.52))
        new_db = round(max(0.40, cur_db - 0.05), 2)
        if new_db < cur_db:
            adjustments["disp_body_ratio"] = new_db
            adjustments["_r_disp"] = (
                f"0-trade runs → disp_body_ratio {cur_db} → {new_db}"
            )

    # ── 4b. Low average win rate (trades exist but mostly losing) ────────
    if wrs:
        avg_wr = sum(wrs) / len(wrs)
        if avg_wr < 40 and len(zero_trade_runs) < len(backtest_runs):
            patterns.append(
                f"Average win rate is {avg_wr:.1f}% across {len(wrs)} runs "
                f"— signal selectivity too low"
            )
            # Raise confluence_min to be more selective (opposite of 4a)
            cur_cm2 = int(cfg.get("confluence_min", 5))
            if "confluence_min" not in adjustments and cur_cm2 < 8:
                adjustments["confluence_min"] = cur_cm2 + 1
                adjustments["_r_cm2"] = (
                    f"Low win rate → confluence_min {cur_cm2} → {cur_cm2 + 1}"
                )

    # ── 5. Directional bias ───────────────────────────────────────────
    buy_l  = sum(1 for t in losing_trades if t.get("side") == "BUY")
    sell_l = sum(1 for t in losing_trades if t.get("side") == "SELL")
    if buy_l / total >= 0.75:
        patterns.append(
            f"{buy_l}/{total} losses were BUY trades — "
            f"bearish macro bias may be consistently missed"
        )
    elif sell_l / total >= 0.75:
        patterns.append(
            f"{sell_l}/{total} losses were SELL trades — "
            f"bullish macro bias may be consistently missed"
        )

    # ── 6. Majority of runs unprofitable → sideways market flag ──────
    low_pf = [r for r in backtest_runs
              if float(r.get("profit_factor") or 0) < 1.0]
    if len(low_pf) / max(len(backtest_runs), 1) >= 0.60:
        patterns.append(
            f"{len(low_pf)}/{len(backtest_runs)} runs had profit_factor < 1.0 "
            f"— likely trading in ranging / low-volatility conditions"
        )
        if not cfg.get("avoid_sideways_market"):
            adjustments["avoid_sideways_market"] = True
            adjustments["_r_sideways"] = (
                "Majority of runs unprofitable → avoid_sideways_market enabled"
            )

    if not patterns:
        patterns.append(
            "No dominant failure pattern detected. "
            "Run at least 5 backtests for reliable pattern recognition."
        )

    return {"patterns": patterns, "adjustments": adjustments}


def _analyze_winning_trades(winning_trades, cfg):
    """
    Analyse winning trades to find what conditions reliably produce wins.
    Returns {patterns, adjustments} — merged with loss analysis to guide config.
    """
    patterns    = []
    adjustments = {}
    total       = len(winning_trades)

    if total < 3:
        return {"patterns": [], "adjustments": {}}

    # ── 1. Common strategy signals across wins ────────────────────────────
    signal_counts = {}
    for t in winning_trades:
        for sig in (t.get("strategy_signals") or []):
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

    for sig, cnt in sorted(signal_counts.items(), key=lambda x: -x[1])[:3]:
        if cnt / total >= 0.70:
            patterns.append(
                f"{cnt}/{total} wins had signal '{sig}' — key edge to preserve"
            )

    # ── 2. Session clustering in wins ────────────────────────────────────
    sess_counts = {}
    for t in winning_trades:
        s = t.get("session", "Unknown")
        sess_counts[s] = sess_counts.get(s, 0) + 1

    if sess_counts:
        best_s = max(sess_counts, key=sess_counts.get)
        bpct   = sess_counts[best_s] / total
        if bpct >= 0.65:
            patterns.append(
                f"{sess_counts[best_s]}/{total} wins ({round(bpct*100)}%) "
                f"occurred in {best_s} — strongest session edge"
            )

    # ── 3. Average winning confluence ─────────────────────────────────────
    avg_conf = sum(t.get("confluence", 0) or 0 for t in winning_trades) / total
    if avg_conf >= 6:
        cur_cm = int(cfg.get("confluence_min", 5))
        target = min(int(avg_conf), 8)
        if target > cur_cm:
            adjustments["confluence_min"] = target
            patterns.append(
                f"Avg winning confluence {avg_conf:.1f} → raising "
                f"confluence_min from {cur_cm} to {target}"
            )

    # ── 4. Healthy SL % range ─────────────────────────────────────────────
    sl_pcts = [float(t.get("sl_pct") or 0) for t in winning_trades if t.get("sl_pct")]
    if sl_pcts:
        avg_sl = sum(sl_pcts) / len(sl_pcts)
        if 0.3 < avg_sl < 2.0:
            patterns.append(
                f"Winning trades averaged {avg_sl:.2f}% SL distance — "
                f"healthy risk sizing"
            )

    # ── 5. Average R:R of wins ────────────────────────────────────────────
    rrs = [float(t.get("rr") or 0) for t in winning_trades if t.get("rr")]
    if rrs:
        avg_rr = sum(rrs) / len(rrs)
        patterns.append(f"Average R:R on winning trades: {avg_rr:.2f}")
        cur_rr = float(cfg.get("risk_reward", 2))
        if avg_rr > cur_rr + 0.5:
            adjustments["risk_reward"] = round(min(avg_rr, cur_rr + 0.5), 1)
            patterns.append(
                f"Wins achieved higher R:R than configured → "
                f"raising risk_reward target to {adjustments['risk_reward']}"
            )

    if not patterns:
        patterns.append(f"No dominant winning pattern yet ({total} wins analyzed)")

    return {"patterns": patterns, "adjustments": adjustments}


def _auto_learn_silent(user_id):
    """
    Called automatically after every backtest completes.
    Reads the last 5 runs for this user, runs the rule-based analyser,
    and applies any config adjustments it finds — silently.
    Returns a small summary dict that goes back in the backtest response.
    """
    import math
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT win_rate, profit_factor, trades_json, total_trades
            FROM   backtest_runs
            WHERE  user_id = %s
            ORDER  BY created_at DESC LIMIT 5
        """, (user_id,))
        rows = cur.fetchall()

        cur.execute("SELECT settings FROM users WHERE id=%s", (user_id,))
        cfg_row = cur.fetchone()
        conn.close()

        cfg = dict(DEFAULT_CONFIG)
        if cfg_row and cfg_row[0]:
            try: cfg.update(json.loads(cfg_row[0]))
            except Exception: pass

        if not rows:
            return {"applied": False, "adjustments": {}, "patterns": []}

        backtest_runs, losing_trades, winning_trades = [], [], []
        for r in rows:
            backtest_runs.append({
                "win_rate":      r[0],
                "profit_factor": r[1],
                "total_trades":  int(r[3] or 0),
            })
            try:
                for t in json.loads(r[2] or "[]"):
                    pnl = float(t.get("pnl", 0) or 0)
                    if pnl < 0:
                        losing_trades.append(t)
                    elif pnl > 0:
                        winning_trades.append(t)
            except Exception:
                pass

        # Merge loss + win analysis adjustments
        loss_analysis = _analyze_losing_trades(losing_trades, backtest_runs, cfg)
        win_analysis  = _analyze_winning_trades(winning_trades, cfg)

        # Loss adjustments take priority; win adjustments fill gaps
        merged_adj = {}
        merged_adj.update({k: v for k, v in win_analysis["adjustments"].items()
                           if not k.startswith("_r_")})
        merged_adj.update({k: v for k, v in loss_analysis["adjustments"].items()
                           if not k.startswith("_r_")})

        all_patterns = win_analysis["patterns"] + loss_analysis["patterns"]

        if not merged_adj:
            return {"applied": False, "suggested": {}, "adjustments": {}, "patterns": all_patterns}

        # ── NEVER auto-apply. Return suggestions only. ─────────────────────────
        # The user must call /api/apply-config explicitly to commit changes.
        return {
            "applied":              False,
            "suggested":            merged_adj,   # suggested (not yet applied)
            "adjustments":          {},            # nothing was applied
            "adjustments_applied":  0,
            "patterns":             all_patterns,
        }
    except Exception as e:
        print(f"[auto_learn] error: {e}")
        return {"applied": False, "adjustments": {}, "patterns": []}


# ── Grid of params the optimiser will sweep ──────────────────────────────────
OPTIMIZE_GRID = {
    "confluence_min":  [3, 4, 5, 6, 7],
    "risk_reward":     [1.5, 2.0, 2.5, 3.0],
    "disp_body_ratio": [0.40, 0.52, 0.62],
}


def _grid_score(total_trades, win_rate, profit_factor):
    """
    Composite score: rewards high PF × win-rate while penalising zero-trade runs.
    A run with ≥ 5 trades, 60% WR, and PF 2.0 scores 1.20.
    """
    import math
    if total_trades < 3:
        return 0.0
    wr_frac = (win_rate or 0) / 100.0
    pf      = profit_factor or 0.0
    trade_w = min(total_trades, 30) / 30.0
    return round(pf * wr_frac * trade_w, 4)


@app.route("/api/optimize", methods=["POST", "OPTIONS"])
@auth_required
def optimize_params():
    """
    Parameter grid search.
    Fetches candles once, then runs run_unified_bot_strategy for every
    combination in OPTIMIZE_GRID, scores each result, and applies the
    best-found config to the user's settings.

    Body (same fields as /api/backtest):
      symbol, interval, period_days, starting_balance, fee_percent,
      slippage_percent  (strategy is always unified_bot for this endpoint)
    """
    data       = request.get_json(force=True) or {}
    symbol     = data.get("symbol", "BTCUSDT").upper()
    interval   = data.get("interval", "5m")
    period_days= max(7, min(int(data.get("period_days", 30)), 90))
    sb         = float(data.get("starting_balance", 10000))
    fee_pct    = float(data.get("fee_percent",      0.04))
    slip_pct   = float(data.get("slippage_percent", 0.02))

    # ── Determine market ──────────────────────────────────────────────────────
    market = next(
        (m for m, syms in MARKETS.items() if symbol in syms), "crypto"
    )

    # ── Fetch candles once ────────────────────────────────────────────────────
    try:
        if market == "crypto":
            target_rows = period_days * 288   # 5 m bars per day
            end_dt   = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=period_days)
            start_ms = int(start_dt.timestamp() * 1000)
            end_ms   = int(end_dt.timestamp()   * 1000)
            candles  = fetch_binance_range_paginated(
                symbol, interval, start_ms, end_ms, max_candles=target_rows
            )
        else:
            candles, interval, _, _ = fetch_non_crypto_backtest_candles(
                symbol, period_days, random_window=False
            )
        if not candles or len(candles) < 60:
            return jsonify({"error": "Not enough candle data for optimisation."}), 400
    except Exception as e:
        return jsonify({"error": f"Candle fetch failed: {e}"}), 500

    cfg = get_user_config()

    # ── Build full Cartesian product of the grid ──────────────────────────────
    import itertools
    keys   = list(OPTIMIZE_GRID.keys())
    values = list(OPTIMIZE_GRID.values())
    combos = list(itertools.product(*values))  # e.g. 5×4×3 = 60

    results = []
    for combo in combos:
        trial_cfg = dict(cfg)
        for k, v in zip(keys, combo):
            trial_cfg[k] = v

        try:
            trades, ending_balance = run_unified_bot_strategy(
                candles, sb, fee_pct, slip_pct,
                weekly_win_goal=cfg.get("weekly_win_goal", 3),
                weekly_profit_target_pct=cfg.get("weekly_profit_target_percent", 3.0),
                weekly_max_loss_pct=cfg.get("weekly_max_loss_percent", 0.8),
                user_cfg=trial_cfg,
            )
        except Exception:
            continue

        total   = len(trades)
        wins    = [t for t in trades if float(t.get("pnl", 0) or 0) > 0]
        losses  = [t for t in trades if float(t.get("pnl", 0) or 0) <= 0]
        gp      = sum(float(t.get("pnl", 0) or 0) for t in wins)
        gl      = abs(sum(float(t.get("pnl", 0) or 0) for t in losses))
        wr      = (len(wins) / total * 100) if total else 0
        pf      = (gp / gl) if gl else (1.0 if gp > 0 else 0.0)
        net     = round(ending_balance - sb, 2)
        score   = _grid_score(total, wr, pf)

        results.append({
            "params":        {k: v for k, v in zip(keys, combo)},
            "total_trades":  total,
            "win_rate":      round(wr, 2),
            "profit_factor": round(pf, 2),
            "net_pnl":       net,
            "score":         score,
        })

    if not results:
        return jsonify({"error": "No results generated — all combos produced errors."}), 500

    results.sort(key=lambda r: r["score"], reverse=True)
    best    = results[0]
    top5    = results[:5]

    # ── NEVER auto-apply. Return suggestion only. ────────────────────────────
    # The user must call /api/apply-config with the suggested params to commit.
    return jsonify({
        "ok":              True,
        "combos_tested":   len(results),
        "best":            best,
        "top5":            top5,
        "applied":         False,   # never auto-applied
        "suggested_params": best["params"],
        "param_keys":      keys,
    })


@app.route("/api/learn", methods=["POST", "OPTIONS"])
@auth_required
def learn_from_mistakes():
    """
    Section 1B — analyze losing trades and auto-adjust config.
    Body params:
      n_runs     : int  — how many recent backtest runs to analyze (default 5, max 20)
      auto_apply : bool — whether to immediately apply suggested changes (default true)
      symbol     : str  — optional filter to a specific symbol
    """
    data       = request.get_json(force=True) or {}
    n_runs     = max(1, min(int(data.get("n_runs", 5)), 20))
    auto_apply = False   # NEVER auto-apply; user must call /api/apply-config
    symbol     = data.get("symbol")

    # ── Pull recent backtest runs ──────────────────────────────────────
    conn = get_conn(); cur = conn.cursor()
    query  = """SELECT id, symbol, interval, strategy, win_rate, net_pnl,
                       profit_factor, trades_json, summary_json, created_at,
                       total_trades
                FROM backtest_runs
                WHERE user_id = %s"""
    params = [g.user_id]
    if symbol:
        query  += " AND symbol = %s"
        params.append(symbol.upper())
    query  += " ORDER BY created_at DESC LIMIT %s"
    params.append(n_runs)

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return jsonify({
            "ok":    False,
            "error": "No backtest runs found. Run at least 1 backtest first.",
        }), 400

    backtest_runs = []
    losing_trades = []

    for row in rows:
        run = {
            "id":            row[0],
            "symbol":        row[1],
            "interval":      row[2],
            "strategy":      row[3],
            "win_rate":      row[4],
            "net_pnl":       row[5],
            "profit_factor": row[6],
            "created_at":    str(row[9]),
            "total_trades":  int(row[10] or 0),
        }
        backtest_runs.append(run)
        try:
            for t in json.loads(row[7] or "[]"):
                if float(t.get("pnl", 0) or 0) < 0:
                    t["_symbol"]   = row[1]
                    t["_strategy"] = row[3]
                    losing_trades.append(t)
        except Exception:
            pass

    cfg        = get_user_config()
    before_cfg = dict(cfg)

    avg_wr_before = (
        sum(float(r.get("win_rate") or 0) for r in backtest_runs)
        / len(backtest_runs)
    )

    # ── Rule-based analysis ───────────────────────────────────────────
    analysis  = _analyze_losing_trades(losing_trades, backtest_runs, cfg)
    patterns  = analysis["patterns"]
    all_adj   = analysis["adjustments"]

    real_adj = {k: v for k, v in all_adj.items() if not k.startswith("_r_")}
    reasons  = {k[3:]: v for k, v in all_adj.items() if k.startswith("_r_")}

    # ── Apply adjustments ─────────────────────────────────────────────
    after_cfg = dict(before_cfg)
    applied   = False
    if auto_apply and real_adj:
        after_cfg.update(real_adj)
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "UPDATE users SET settings=%s WHERE id=%s",
            (json.dumps(after_cfg), g.user_id),
        )
        conn.commit(); conn.close()
        applied = True

    # ── Persist learning log entry ────────────────────────────────────
    log_id = str(uuid.uuid4())
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO bot_learning_log
              (id, user_id, symbol, interval, strategy,
               analysis_json, adjustments_json,
               before_config, after_config,
               trades_analyzed, win_rate_before, win_rate_after)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            log_id,
            g.user_id,
            symbol or "ALL",
            backtest_runs[0]["interval"] if backtest_runs else "mixed",
            backtest_runs[0]["strategy"] if backtest_runs else "mixed",
            json.dumps({"patterns": patterns, "reasons": reasons}),
            json.dumps(real_adj),
            json.dumps(before_cfg),
            json.dumps(after_cfg),
            len(losing_trades),
            round(avg_wr_before, 2),
            None,   # win_rate_after filled after the next backtest run
        ))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[learn] DB save error: {e}")

    # ── Build before/after diff for the UI ───────────────────────────
    diff = {
        k: {"before": before_cfg.get(k), "after": after_cfg.get(k)}
        for k in real_adj
    }

    return jsonify({
        "ok":              True,
        "log_id":          log_id,
        "runs_analyzed":   len(backtest_runs),
        "trades_analyzed": len(losing_trades),
        "patterns":        patterns,
        "adjustments":     real_adj,
        "reasons":         reasons,
        "diff":            diff,
        "applied":         applied,
        "win_rate_before": round(avg_wr_before, 2),
    })


@app.route("/api/learn/history", methods=["GET"])
@auth_required
def learn_history():
    """Section 1C — return the last 20 learning log entries for this user."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT id, created_at, symbol, strategy,
               analysis_json, adjustments_json,
               before_config, after_config,
               trades_analyzed, win_rate_before, win_rate_after
        FROM bot_learning_log
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 20
    """, (g.user_id,))
    rows = cur.fetchall(); conn.close()

    result = []
    for r in rows:
        try:
            analysis = json.loads(r[4] or "{}")
            adj      = json.loads(r[5] or "{}")
            before   = json.loads(r[6] or "{}")
            after    = json.loads(r[7] or "{}")
            diff = {
                k: {"before": before.get(k), "after": after.get(k)}
                for k in adj
            }
        except Exception:
            analysis = {}; adj = {}; diff = {}
        result.append({
            "id":              r[0],
            "created_at":      str(r[1]),
            "symbol":          r[2],
            "strategy":        r[3],
            "patterns":        analysis.get("patterns", []),
            "reasons":         analysis.get("reasons", {}),
            "adjustments":     adj,
            "diff":            diff,
            "trades_analyzed": r[8],
            "win_rate_before": r[9],
            "win_rate_after":  r[10],
        })
    return jsonify(result)


# ─────────────────────────────────────────────────────────────────────────────
# APPLY CONFIG  — explicit user action to apply suggested param changes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/apply-config", methods=["POST", "OPTIONS"])
@auth_required
def apply_config():
    """
    Apply suggested configuration changes to the user's bot settings.
    This is the ONLY endpoint that writes config changes — auto-learn,
    optimise, and learn-from-mistakes all return suggestions only and
    require the user to call this endpoint explicitly.

    Body: { "changes": { "confluence_min": 5, "risk_reward": 2.5, ... } }
    """
    try:
        data    = request.get_json(force=True) or {}
        changes = data.get("changes") or {}
        if not isinstance(changes, dict) or not changes:
            return jsonify({"error": "Provide a non-empty 'changes' dict."}), 400

        cfg = get_user_config()
        before = {k: cfg.get(k) for k in changes}
        cfg.update(changes)

        conn = get_conn(); cur = conn.cursor()
        cur.execute("UPDATE users SET settings=%s WHERE id=%s",
                    (json.dumps(cfg), g.user_id))
        conn.commit(); conn.close()

        return jsonify({
            "ok":      True,
            "applied": changes,
            "before":  before,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def _wf_metrics(trades, sb):
    """Compute summary metrics for a list of trades."""
    if not trades:
        return {"total_trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}
    wins   = [t for t in trades if float(t.get("pnl", 0) or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl", 0) or 0) <= 0]
    gp = sum(float(t.get("pnl", 0) or 0) for t in wins)
    gl = abs(sum(float(t.get("pnl", 0) or 0) for t in losses))
    wr = len(wins) / len(trades) * 100 if trades else 0
    pf = (gp / gl) if gl else (1.0 if gp > 0 else 0.0)
    return {
        "total_trades":  len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(wr, 2),
        "profit_factor": round(pf, 2),
        "net_pnl":       round(sum(float(t.get("pnl", 0) or 0) for t in trades), 2),
    }


@app.route("/api/walkforward", methods=["POST", "OPTIONS"])
@auth_required
def api_walkforward():
    """
    Walk-forward analysis.

    Splits the full candle history into N equal windows.
    For each window:
      - In-sample (first train_pct of the window): grid-search best params.
      - Out-of-sample (last 1-train_pct of the window): run strategy with
        those best params and record honest OOS metrics.

    Returns per-window OOS results + an aggregate so the user can assess
    whether the edge is stable or curve-fitted to one period.

    Body:
      symbol, period_days (default 120, max 365), n_windows (2-6, default 4),
      train_pct (default 0.70), starting_balance, fee_percent, slippage_percent
    """
    try:
        data        = request.get_json(force=True) or {}
        symbol      = (data.get("symbol") or "BTCUSDT").upper()
        period_days = max(30, min(int(data.get("period_days", 120)), 365))
        n_windows   = max(2, min(int(data.get("n_windows",   4)),   6))
        train_pct   = max(0.50, min(float(data.get("train_pct", 0.70)), 0.90))
        sb          = float(data.get("starting_balance", 10000))
        fee_pct     = float(data.get("fee_percent",      0.04))
        slip_pct    = float(data.get("slippage_percent", 0.02))

        if symbol not in ALL_SYMBOLS:
            return jsonify({"error": f"Symbol '{symbol}' not supported."}), 400

        market = detect_market(symbol)

        # ── Fetch all candles for the full period ─────────────────────────────
        if market == "crypto":
            end_dt   = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=period_days)
            start_ms = int(start_dt.timestamp() * 1000)
            end_ms   = int(end_dt.timestamp()   * 1000)
            all_candles = fetch_binance_range_paginated(
                symbol, "5m", start_ms, end_ms,
                max_candles=period_days * 288
            )
        else:
            all_candles, _, _, _ = fetch_non_crypto_backtest_candles(
                symbol, period_days, random_window=False
            )

        if not all_candles or len(all_candles) < n_windows * 60:
            return jsonify({"error": f"Not enough candle data ({len(all_candles or [])} bars). "
                                     f"Need at least {n_windows * 60}."}), 400

        cfg = get_user_config()
        _ww  = cfg.get("weekly_win_goal",             3)
        _wpt = cfg.get("weekly_profit_target_percent", 3.0)
        _wml = cfg.get("weekly_max_loss_percent",      0.8)

        # ── Simplified grid for walk-forward (16 combos, keeps each window fast)
        import itertools
        WF_GRID = {
            "confluence_min": [4, 5, 6, 7],
            "risk_reward":    [1.5, 2.0, 2.5, 3.0],
        }
        wf_keys   = list(WF_GRID.keys())
        wf_combos = list(itertools.product(*WF_GRID.values()))

        # ── Split all_candles into n_windows equal chunks ─────────────────────
        w_size  = len(all_candles) // n_windows
        windows = [all_candles[i * w_size : (i + 1) * w_size] for i in range(n_windows)]

        window_results = []
        all_oos_trades = []
        MIN_MEANINGFUL = 30

        for wi, w_candles in enumerate(windows):
            sp = int(len(w_candles) * train_pct)
            sp = max(50, min(sp, len(w_candles) - 20))

            train_c = w_candles[:sp]
            test_c  = w_candles[sp:]

            # ── Grid search on in-sample candles ──────────────────────────────
            best_score  = -1
            best_params = {k: cfg.get(k) for k in wf_keys}  # fallback to current

            for combo in wf_combos:
                trial = dict(cfg)
                for k, v in zip(wf_keys, combo):
                    trial[k] = v
                try:
                    tr, _ = run_unified_bot_strategy(
                        train_c, sb, fee_pct, slip_pct,
                        weekly_win_goal=_ww,
                        weekly_profit_target_pct=_wpt,
                        weekly_max_loss_pct=_wml,
                        user_cfg=trial,
                    )
                    t_cnt = len(tr)
                    _wins_tr = [t for t in tr if float(t.get("pnl",0)or 0)>0]
                    _gl_tr   = abs(sum(float(t.get("pnl",0)or 0) for t in tr if float(t.get("pnl",0)or 0)<0))
                    _gp_tr   = sum(float(t.get("pnl",0)or 0) for t in _wins_tr)
                    _wr_tr   = len(_wins_tr)/t_cnt*100 if t_cnt else 0
                    _pf_tr   = (_gp_tr / _gl_tr) if _gl_tr else 0
                    score    = _grid_score(t_cnt, _wr_tr, _pf_tr)
                    if score > best_score:
                        best_score  = score
                        best_params = {k: v for k, v in zip(wf_keys, combo)}
                except Exception:
                    continue

            # ── Apply best params to OOS (test) candles ───────────────────────
            oos_cfg = dict(cfg); oos_cfg.update(best_params)
            try:
                oos_trades, _ = run_unified_bot_strategy(
                    test_c, sb, fee_pct, slip_pct,
                    weekly_win_goal=_ww,
                    weekly_profit_target_pct=_wpt,
                    weekly_max_loss_pct=_wml,
                    user_cfg=oos_cfg,
                )
            except Exception:
                oos_trades = []

            oos_m = _wf_metrics(oos_trades, sb)
            oos_m["low_sample_warning"] = oos_m["total_trades"] < MIN_MEANINGFUL

            # Human-readable window dates
            try:
                w_start = _ts_to_str(int(w_candles[0][0]))[:10]
                w_split = _ts_to_str(int(train_c[-1][0]))[:10]
                w_end   = _ts_to_str(int(w_candles[-1][0]))[:10]
            except Exception:
                w_start = w_split = w_end = "—"

            all_oos_trades.extend(oos_trades)
            window_results.append({
                "window":         wi + 1,
                "train_start":    w_start,
                "train_end":      w_split,
                "test_end":       w_end,
                "best_is_params": best_params,
                "is_score":       round(best_score, 4),
                "oos":            oos_m,
            })

        # ── Aggregate OOS across all windows ──────────────────────────────────
        agg = _wf_metrics(all_oos_trades, sb)
        pos_pf_windows = sum(1 for r in window_results if r["oos"]["profit_factor"] > 1.0)
        agg["windows_profitable"]   = pos_pf_windows
        agg["windows_total"]        = n_windows
        agg["consistency_pct"]      = round(pos_pf_windows / n_windows * 100, 1)
        agg["low_sample_warning"]   = agg["total_trades"] < MIN_MEANINGFUL * n_windows

        verdict = "STABLE" if pos_pf_windows >= n_windows * 0.75 else \
                  "MIXED"  if pos_pf_windows >= n_windows * 0.50 else "UNSTABLE"
        agg["verdict"] = verdict

        return jsonify({
            "ok":           True,
            "symbol":       symbol,
            "period_days":  period_days,
            "n_windows":    n_windows,
            "train_pct":    train_pct,
            "windows":      window_results,
            "aggregate":    agg,
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "detail": traceback.format_exc()[-400:]}), 500


# ── Global error handlers — always return JSON, never HTML ───────────────────
@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request", "detail": str(e)}), 400

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({"error": "Unauthorized"}), 401

@app.errorhandler(403)
def forbidden(e):
    return jsonify({"error": "Forbidden"}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found", "detail": str(e)}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405

@app.errorhandler(500)
def internal_error(e):
    import traceback
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    # Pass through HTTP exceptions to their own handlers
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    return jsonify({"error": str(e), "detail": traceback.format_exc()[-400:]}), 500

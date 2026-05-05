"""
AI Trading Engine — Flask backend (SaaS edition)
All routes are mounted under /api so the platform's ingress routes them to port 8001.
"""
from flask import Flask, jsonify, request, g
from flask_cors import CORS
import pandas as pd
import requests
import uuid
import sqlite3
import os
import time
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

CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True);

# ------------ DEFAULT BOT CONFIG (per-user override stored in DB) ------------
DEFAULT_CONFIG = {
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
    "risk_reward": 2,
    "risk_percent": 1,
    "min_confidence": 75,
    "starting_balance": 10000,
    "max_trades_per_day": 5,
    "max_daily_loss_percent": 3,
    "max_consecutive_losses": 2,
    "avoid_quiet_market": True,
    "avoid_sideways_market": True,
    "min_volume_multiplier": 0.8,
    "min_smc_score": 7,
    "blocked_crypto_hours_utc": [0, 1, 2, 3],
    "trading_mode": "local_paper",  # local_paper | testnet
}

JWT_SECRET = os.environ.get("JWT_SECRET", "ai-trading-engine-secret-change-me")
JWT_ALGO = "HS256"
JWT_EXPIRY_DAYS = 7

DB_NAME = os.path.join(BASE_DIR, "trades.db")
MARKET_DATA_TTL_SECONDS = 20
SUMMARY_TTL_SECONDS = 15

_raw_candle_cache = {}
_summary_cache = {}

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
COINBASE_GRANULARITY_MAP = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 3600}


# ---------------- DATABASE ----------------
import os
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


# ---------------- AUTH ----------------
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
            g.user_id = payload["sub"]
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
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip() or email.split("@")[0]
    if not email or len(password) < 6:
        return jsonify({"error": "Email and password (min 6 chars) required"}), 400

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email=%s", (email,))
    if c.fetchone():
        conn.close()
        return jsonify({"error": "Email already registered"}), 400

    user_id = str(uuid.uuid4())
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    c.execute("INSERT INTO users VALUES (%s, %s, %s, %s, %s, %s)",
              (user_id, email, pw_hash, name, now_str(), json.dumps(DEFAULT_CONFIG)))
    conn.commit()
    conn.close()
    token = make_token(user_id, email)
    return jsonify({"token": token, "user": {"id": user_id, "email": email, "name": name}})


@app.route("/api/auth/login", methods=["POST", "OPTIONS"])
def login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, password_hash, name FROM users WHERE email=%s", (email,))
    row = c.fetchone()
    conn.close()
    if not row or not bcrypt.checkpw(password.encode(), row[1].encode()):
        return jsonify({"error": "Invalid credentials"}), 401
    token = make_token(row[0], email)
    return jsonify({"token": token, "user": {"id": row[0], "email": email, "name": row[2]}})


@app.route("/api/auth/me", methods=["GET"])
@auth_required
def me():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, email, name, created_at FROM users WHERE id=%s", (g.user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"id": row[0], "email": row[1], "name": row[2], "created_at": row[3]})


# ---------------- HELPERS ----------------
def _request_json(url, params=None, timeout=10):
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
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO alerts VALUES (%s, %s, %s, %s)",
              (str(uuid.uuid4()), user_id, message, now_str()))
    conn.commit()
    conn.close()


# ---------------- MARKET DATA (binance + coinbase fallback) ----------------
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
            last_error = f"{base_url} HTTP {r.status_code}"
        except requests.exceptions.RequestException as e:
            last_error = f"{base_url}: {e}"
    raise RuntimeError(last_error or "All Binance endpoints failed")


def _coinbase_fetch_candles(product_id, granularity, total_needed):
    all_rows, end_time = [], datetime.now(timezone.utc)
    while len(all_rows) < total_needed:
        batch_size = min(300, total_needed - len(all_rows))
        start_time = end_time - timedelta(seconds=granularity * batch_size)
        r = _request_json(f"https://api.exchange.coinbase.com/products/{product_id}/candles",
                          params={"granularity": granularity,
                                  "start": start_time.isoformat(),
                                  "end": end_time.isoformat()}, timeout=12)
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
    unique = {int(r[0]): r for r in all_rows if isinstance(r, list) and len(r) >= 6}
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
            ts = int(bucket[0][0])
            low = min(float(r[1]) for r in bucket)
            high = max(float(r[2]) for r in bucket)
            grouped.append([ts, low, high, float(bucket[0][3]),
                            float(bucket[-1][4]), sum(float(r[5]) for r in bucket)])
            bucket = []
    return grouped[-limit:]


def _fetch_coinbase_raw(symbol="BTCUSDT", interval="5m", limit=200):
    product_id = COINBASE_PRODUCT_MAP.get(symbol)
    if not product_id or interval not in COINBASE_GRANULARITY_MAP:
        raise RuntimeError(f"No Coinbase mapping for {symbol} {interval}")
    if interval == "4h":
        raw_1h = _coinbase_fetch_candles(product_id, 3600, max(limit * 4, 4))
        rows = _aggregate_coinbase_1h_to_4h(raw_1h, limit)
    else:
        rows = _coinbase_fetch_candles(product_id, COINBASE_GRANULARITY_MAP[interval], limit)
    return [[int(r[0]) * 1000, str(r[3]), str(r[2]), str(r[1]),
             str(r[4]), str(r[5])] for r in rows]


def fetch_binance_raw(symbol="BTCUSDT", interval="5m", limit=500):
    if not symbol or not symbol.endswith("USDT"):
        raise ValueError("Invalid symbol")
    cache_key = (symbol, interval, int(limit))
    cached = _cache_get(_raw_candle_cache, cache_key, MARKET_DATA_TTL_SECONDS)
    if cached is not None:
        return cached
    binance_error = None
    try:
        return _cache_set(_raw_candle_cache, cache_key,
                          _fetch_binance_klines(symbol, interval, limit))
    except Exception as e:
        binance_error = str(e)
    try:
        return _cache_set(_raw_candle_cache, cache_key,
                          _fetch_coinbase_raw(symbol, interval, limit))
    except Exception as fb:
        raise RuntimeError(f"Binance failed ({binance_error}); Coinbase failed ({fb})")


def raw_candles_to_df(raw):
    if not raw or len(raw) < 2:
        return None
    first = raw[0]
    if len(first) >= 12:
        df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume",
                                        "close_time", "quote_asset_volume", "number_of_trades",
                                        "taker_buy_base", "taker_buy_quote", "ignore"])
    elif len(first) >= 6:
        df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    else:
        return None
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    df.dropna(subset=["time", "open", "high", "low", "close", "volume"], inplace=True)
    if len(df) < 2:
        return None
    return df.reset_index(drop=True)


def fetch_binance(symbol, interval="1m", limit=100):
    try:
        return raw_candles_to_df(fetch_binance_raw(symbol, interval, limit))
    except Exception:
        return None


# ---------------- BOT LOGIC ----------------
def generate_signal(df):
    if df is None or len(df) < 2:
        return "HOLD"
    return "BUY" if df.iloc[-1]["close"] > df.iloc[-2]["close"] else \
           "SELL" if df.iloc[-1]["close"] < df.iloc[-2]["close"] else "HOLD"


def get_structure(df):
    if df is None or len(df) < 20:
        return "Range / Mixed"
    closes = df["close"]
    sma20 = closes.tail(20).mean()
    c0, c1, c2 = closes.iloc[-1], closes.iloc[-2], closes.iloc[-3]
    if c0 > sma20 and c0 > c1 > c2:
        return "Bullish Structure"
    if c0 < sma20 and c0 < c1 < c2:
        return "Bearish Structure"
    return "Range / Mixed"


def get_market_regime(df):
    if df is None or len(df) < 20:
        return "Unknown"
    rh, rl = df["high"].tail(20).max(), df["low"].tail(20).min()
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
    sma20, sma5 = closes.tail(20).mean(), closes.tail(5).mean()
    confidence = 50
    if signal == "BUY":
        if latest > sma20: confidence += 15
        if latest > prev: confidence += 10
        if latest > sma5: confidence += 10
    elif signal == "SELL":
        if latest < sma20: confidence += 15
        if latest < prev: confidence += 10
        if latest < sma5: confidence += 10
    return max(35, min(95, confidence))


def get_higher_timeframe(interval):
    if interval in ["1m", "5m", "15m"]:
        return "1h"
    return "4h"


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
    ph = df["high"].iloc[-21:-1].max()
    pl = df["low"].iloc[-21:-1].min()
    if cur["high"] > ph and cur["close"] < ph:
        return "SELL_SWEEP"
    if cur["low"] < pl and cur["close"] > pl:
        return "BUY_SWEEP"
    return None


def detect_break_of_structure(df):
    if df is None or len(df) < 30:
        return None
    rh = df["high"].iloc[-15:-1].max()
    rl = df["low"].iloc[-15:-1].min()
    close = df.iloc[-1]["close"]
    if close > rh: return "BULLISH_BOS"
    if close < rl: return "BEARISH_BOS"
    return None


def price_in_discount_zone(df):
    if df is None or len(df) < 30: return False
    rh, rl = df["high"].tail(30).max(), df["low"].tail(30).min()
    return df.iloc[-1]["close"] <= (rh + rl) / 2


def price_in_premium_zone(df):
    if df is None or len(df) < 30: return False
    rh, rl = df["high"].tail(30).max(), df["low"].tail(30).min()
    return df.iloc[-1]["close"] >= (rh + rl) / 2


def detect_fvg_retrace(df, direction):
    if df is None or len(df) < 10: return False
    c = df.tail(8).reset_index(drop=True)
    cur_close = c.iloc[-1]["close"]
    for i in range(2, len(c)):
        c1, c3 = c.iloc[i-2], c.iloc[i]
        if direction == "BUY" and c3["low"] > c1["high"]:
            if c1["high"] <= cur_close <= c3["low"]:
                return True
        if direction == "SELL" and c3["high"] < c1["low"]:
            if c3["high"] <= cur_close <= c1["low"]:
                return True
    return False


def session_allowed(cfg):
    return datetime.utcnow().hour not in cfg["blocked_crypto_hours_utc"]


def evaluate_bot_window(df, strategy="bot", symbol="BTCUSDT", interval="5m",
                        higher_df=None, cfg=None):
    cfg = cfg or DEFAULT_CONFIG
    if df is None or len(df) < 50:
        return {"signal": "HOLD", "bias": "Neutral", "structure": "Range / Mixed",
                "regime": "Unknown", "confidence": 50, "trade_idea": "Not enough data",
                "higher_tf": get_higher_timeframe(interval), "higher_tf_bias": "Neutral",
                "liquidity_sweep": None, "bos": None, "smc_score": 0,
                "reasons": ["Insufficient candle history"]}

    raw_signal = generate_signal(df)
    structure = get_structure(df)
    regime = get_market_regime(df)
    confidence = estimate_confidence(df, raw_signal)
    higher_tf = get_higher_timeframe(interval)
    if higher_df is None:
        higher_df = fetch_binance(symbol, higher_tf, 100)
    higher_tf_bias = get_trend_bias(higher_df)
    sweep = detect_liquidity_sweep(df)
    bos = detect_break_of_structure(df)

    final, idea, smc_score, reasons = "HOLD", "Wait for clearer confirmation", 0, []

    if strategy == "basic":
        final = raw_signal
        idea = {"BUY": "Pullback long / continuation",
                "SELL": "Reject highs / continuation short"}.get(final, idea)
        reasons.append(f"Basic momentum signal = {raw_signal}")
    elif strategy == "ema_rsi":
        ef = df["close"].ewm(span=9, adjust=False).mean()
        es = df["close"].ewm(span=21, adjust=False).mean()
        if ef.iloc[-1] > es.iloc[-1] and confidence >= 65:
            final, idea = "BUY", "EMA momentum long"; confidence = max(confidence, 70)
            reasons.append("EMA9 above EMA21 with confidence ≥ 65")
        elif ef.iloc[-1] < es.iloc[-1] and confidence >= 65:
            final, idea = "SELL", "EMA momentum short"; confidence = max(confidence, 70)
            reasons.append("EMA9 below EMA21 with confidence ≥ 65")
    else:  # smart_money / bot
        buy_checks = [
            ("HTF bias bullish", higher_tf_bias == "Bullish"),
            ("Buy-side liquidity sweep", sweep == "BUY_SWEEP"),
            ("Bullish break of structure", bos == "BULLISH_BOS"),
            ("Price in discount zone", price_in_discount_zone(df)),
            ("FVG retracement long", detect_fvg_retrace(df, "BUY")),
            (f"Confidence ≥ {cfg['min_confidence']}%", confidence >= cfg["min_confidence"]),
            ("Trending / active regime", regime not in ["Range / Quiet", "Unknown"]),
            ("Clear structure (not range)", structure != "Range / Mixed"),
            ("Active session window", session_allowed(cfg)),
        ]
        sell_checks = [
            ("HTF bias bearish", higher_tf_bias == "Bearish"),
            ("Sell-side liquidity sweep", sweep == "SELL_SWEEP"),
            ("Bearish break of structure", bos == "BEARISH_BOS"),
            ("Price in premium zone", price_in_premium_zone(df)),
            ("FVG retracement short", detect_fvg_retrace(df, "SELL")),
            (f"Confidence ≥ {cfg['min_confidence']}%", confidence >= cfg["min_confidence"]),
            ("Trending / active regime", regime not in ["Range / Quiet", "Unknown"]),
            ("Clear structure (not range)", structure != "Range / Mixed"),
            ("Active session window", session_allowed(cfg)),
        ]
        bs = sum(1 for _, ok in buy_checks if ok)
        ss = sum(1 for _, ok in sell_checks if ok)
        if bs >= cfg["min_smc_score"]:
            final, idea = "BUY", "HTF bullish + sweep + BOS + retracement entry"
            confidence = max(confidence, 80); smc_score = bs
            reasons = [f"✓ {n}" for n, ok in buy_checks if ok] + \
                      [f"✗ {n}" for n, ok in buy_checks if not ok]
        elif ss >= cfg["min_smc_score"]:
            final, idea = "SELL", "HTF bearish + sweep + BOS + retracement entry"
            confidence = max(confidence, 80); smc_score = ss
            reasons = [f"✓ {n}" for n, ok in sell_checks if ok] + \
                      [f"✗ {n}" for n, ok in sell_checks if not ok]
        else:
            smc_score = max(bs, ss)
            best = buy_checks if bs >= ss else sell_checks
            reasons = [f"✓ {n}" for n, ok in best if ok] + \
                      [f"✗ {n}" for n, ok in best if not ok]

    bias = {"BUY": "Bullish", "SELL": "Bearish"}.get(final, higher_tf_bias)
    return {"signal": final, "bias": bias, "structure": structure, "regime": regime,
            "confidence": confidence, "trade_idea": idea, "higher_tf": higher_tf,
            "higher_tf_bias": higher_tf_bias, "liquidity_sweep": sweep, "bos": bos,
            "smc_score": smc_score, "reasons": reasons}


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
    return {"entry": round(lc, 2), "sl": round(sl, 2), "tp": round(tp, 2)}


def get_symbol_summary(symbol, strategy="bot", interval="1m", cfg=None):
    cfg = cfg or DEFAULT_CONFIG
    cache_key = (symbol, strategy, interval)
    cached = _cache_get(_summary_cache, cache_key, SUMMARY_TTL_SECONDS)
    if cached is not None:
        return cached
    df = fetch_binance(symbol, interval, 200)
    if df is None:
        return None
    higher_df = fetch_binance(symbol, get_higher_timeframe(interval), 100)
    ev = evaluate_bot_window(df, strategy, symbol, interval, higher_df, cfg)
    prev = float(df.iloc[-2]["close"]) if len(df) > 1 else float(df.iloc[-1]["close"])
    last = float(df.iloc[-1]["close"])
    chg = ((last - prev) / prev * 100) if prev else 0
    levels = calculate_trade_levels(df, ev["signal"], cfg.get("risk_reward", 2))
    return _cache_set(_summary_cache, cache_key, {
        "symbol": symbol, "price": round(last, 2), "live_price": round(last, 2),
        "change_pct": round(chg, 4), "signal": ev["signal"], "bias": ev["bias"],
        "structure": ev["structure"], "regime": ev["regime"],
        "confidence": ev["confidence"], "trade_idea": ev["trade_idea"],
        "higher_tf": ev["higher_tf"], "higher_tf_bias": ev["higher_tf_bias"],
        "liquidity_sweep": ev["liquidity_sweep"], "bos": ev["bos"],
        "smc_score": ev["smc_score"], "reasons": ev["reasons"],
        "entry": levels["entry"], "sl": levels["sl"], "tp": levels["tp"],
    })


# ---------------- BACKTESTER ----------------
def interval_to_pandas_rule(i):
    return {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}.get(i)


def resample_candles_for_interval(df, target):
    if df is None or df.empty:
        return None
    rule = interval_to_pandas_rule(target)
    if not rule: return None
    idx = df.copy()
    idx["time"] = pd.to_datetime(idx["time"], errors="coerce")
    idx.dropna(subset=["time"], inplace=True)
    if idx.empty: return None
    idx = idx.set_index("time")
    rs = idx.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna()
    return None if rs.empty else rs.reset_index()


def get_higher_timeframe_window(higher_df, current_time):
    if higher_df is None or higher_df.empty: return None
    f = higher_df[higher_df["time"] <= current_time]
    return None if f.empty else f.reset_index(drop=True)


def get_session_name(dt):
    h = dt.hour
    if 7 <= h < 12: return "London"
    if 12 <= h < 21: return "New York"
    return "Asia"


def generate_backtest_signals(candles, symbol="BTCUSDT", interval="5m", strategy="bot", cfg=None):
    print("SIGNALS:", signals[:5])
    print("SIGNALS COUNT:", len(signals))
    df = raw_candles_to_df(candles)
    signals = []
    if df is None or len(df) < 50: return signals
    higher_full = resample_candles_for_interval(df, get_higher_timeframe(interval))
    for i in range(50, len(df)):
        win = df.iloc[:i+1].copy().reset_index(drop=True)
        hw = get_higher_timeframe_window(higher_full, win.iloc[-1]["time"])
        ev = evaluate_bot_window(win, strategy, symbol, interval, hw, cfg)
        if ev["signal"] not in ["BUY", "SELL"]:
            continue
        levels = calculate_trade_levels(win, ev["signal"], (cfg or DEFAULT_CONFIG).get("risk_reward", 2))
        signals.append({"index": i, "symbol": symbol, "interval": interval,
                        "strategy": strategy, "type": ev["signal"], "price": levels["entry"],
                        "time": win.iloc[-1]["time"].strftime("%Y-%m-%d %H:%M:%S"),
                        "stop_loss": levels["sl"], "take_profit": levels["tp"],
                        "confidence": ev["confidence"], "smc_score": ev["smc_score"],
                        "reasons": ev["reasons"]})
    return signals


def run_backtest_engine(candles, signals, starting_balance=1000, fee_pct=0.04, slippage_pct=0.02):
    print("TRADES:", trades[:5])
    print("TRADES COUNT:", len(trades))
    balance = float(starting_balance); peak = balance; max_dd = 0.0
    trades = []; total_fees = 0.0; total_slip = 0.0
    cons_loss = 0; max_cons_loss = 0
    sess_perf = {"London": 0.0, "New York": 0.0, "Asia": 0.0}

    for sig in signals:
        ei = int(sig.get("index", 0))
        ep = float(sig.get("price", 0) or 0)
        side = sig.get("type", "BUY")
        sl = float(sig.get("stop_loss", ep) or ep)
        tp = float(sig.get("take_profit", ep) or ep)
        et = sig.get("time", "")
        sym = sig.get("symbol", "N/A"); tf = sig.get("interval", "N/A")
        xp = ep; xt = et; gp = 0.0; reason = "Timed exit"
        max_fwd = min(ei + 30, len(candles) - 1)
        for j in range(ei + 1, max_fwd + 1):
            cd = candles[j]; high = float(cd[2]); low = float(cd[3]); close = float(cd[4])
            ct = datetime.utcfromtimestamp(cd[0] / 1000).strftime("%Y-%m-%d %H:%M:%S")
            if side == "BUY":
                if low <= sl: xp = sl; gp = sl - ep; xt = ct; reason = "Stop loss"; break
                if high >= tp: xp = tp; gp = tp - ep; xt = ct; reason = "Take profit"; break
            else:
                if high >= sl: xp = sl; gp = ep - sl; xt = ct; reason = "Stop loss"; break
                if low <= tp: xp = tp; gp = ep - tp; xt = ct; reason = "Take profit"; break
            if j == max_fwd:
                xp = close; gp = (close - ep) if side == "BUY" else (ep - close); xt = ct
        fee = abs(ep) * (fee_pct / 100); slip = abs(ep) * (slippage_pct / 100)
        net = gp - fee - slip
        total_fees += fee; total_slip += slip
        balance += net; peak = max(peak, balance); max_dd = max(max_dd, peak - balance)
        if net < 0: cons_loss += 1; max_cons_loss = max(max_cons_loss, cons_loss)
        else: cons_loss = 0
        sess = get_session_name(datetime.strptime(et, "%Y-%m-%d %H:%M:%S"))
        sess_perf[sess] += net
        trades.append({"symbol": sym, "timeframe": tf, "session": sess, "side": side,
                       "entry_price": round(ep, 2), "exit_price": round(xp, 2),
                       "stop_loss": round(sl, 2), "take_profit": round(tp, 2),
                       "entry_time": et, "exit_time": xt, "gross_pnl": round(gp, 2),
                       "fee_cost": round(fee, 2), "slippage_cost": round(slip, 2),
                       "pnl": round(net, 2), "reason": reason})

    total = len(trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] < 0]
    gp = sum(wins); gl = abs(sum(losses))
    wr = round((len(wins) / total) * 100, 2) if total else 0
    pf = round(gp / gl, 2) if gl else round(gp, 2)
    summary = {"starting_balance": round(starting_balance, 2),
               "final_balance": round(balance, 2),
               "net_pnl": round(sum(t["pnl"] for t in trades), 2),
               "total_trades": total, "wins": len(wins), "losses": len(losses),
               "best_trade": round(max([t["pnl"] for t in trades], default=0), 2),
               "worst_trade": round(min([t["pnl"] for t in trades], default=0), 2),
               "win_rate": wr, "profit_factor": pf,
               "max_drawdown": round(max_dd, 2),
               "max_drawdown_percent": round((max_dd / starting_balance) * 100, 2) if starting_balance else 0,
               "average_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
               "average_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
               "max_consecutive_losses": max_cons_loss,
               "fees_paid": round(total_fees, 2),
               "slippage_paid": round(total_slip, 2),
               "session_performance": {k: round(v, 2) for k, v in sess_perf.items()}}
    return summary, trades


# ---------------- API ROUTES ----------------
@app.route("/api/health")
def health():
    return jsonify({"ok": True, "time": now_str()})


@app.route("/api/signals", methods=["GET"])
@auth_required
def signals():
    cfg = get_user_config()
    interval = request.args.get("interval", "1m")
    strategy = request.args.get("strategy", "bot").lower()
    out = []
    for sym in cfg["symbols"]:
        s = get_symbol_summary(sym, strategy, interval, cfg)
        if s: out.append(s)
    return jsonify({"signals": out, "last_update": now_str(), "config": cfg})


@app.route("/api/signal/<symbol>", methods=["GET"])
@auth_required
def signal_detail(symbol):
    cfg = get_user_config()
    interval = request.args.get("interval", "5m")
    strategy = request.args.get("strategy", "bot").lower()
    s = get_symbol_summary(symbol.upper(), strategy, interval, cfg)
    if not s: return jsonify({"error": "no data"}), 404
    return jsonify(s)


@app.route("/api/chart-candles", methods=["GET"])
@auth_required
def chart_candles():
    try:
        symbol = request.args.get("symbol", "BTCUSDT").upper()
        interval = request.args.get("interval", "5m")
        limit = int(request.args.get("limit", 200))
        df = fetch_binance(symbol, interval, limit)
        if df is None:
            return jsonify({"ok": False, "data": [], "error": "No data"})
        out = [{"time": int(r["time"].timestamp()), "open": float(r["open"]),
                "high": float(r["high"]), "low": float(r["low"]),
                "close": float(r["close"])} for _, r in df.iterrows()]
        return jsonify({"ok": True, "data": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "data": []}), 500

def get_klines(symbol="BTCUSDT", interval="5m", limit=500):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    res = requests.get(url, params=params, timeout=10)
    res.raise_for_status()

    candles = []
    for k in res.json():
        candles.append({
            "time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5])
        })

    return candles


def run_simple_ma_strategy(candles, starting_balance=1000, fee_pct=0.04, slippage_pct=0.02):
    trades = []
    balance = float(starting_balance)

    fee_rate = float(fee_pct) / 100
    slippage_rate = float(slippage_pct) / 100

    for i in range(20, len(candles) - 10, 20):
        entry_price = float(candles[i][4]) * (1 + slippage_rate)
        exit_price = float(candles[i + 10][4]) * (1 - slippage_rate)

        gross_pnl = exit_price - entry_price
        fees = (entry_price + exit_price) * fee_rate
        net_pnl = gross_pnl - fees
        balance += net_pnl

        trades.append({
            "entry": entry_price,
            "exit": exit_price,
            "pnl": net_pnl,
            "entry_time": candles[i][0],
            "exit_time": candles[i + 10][0]
        })

    return trades, balance

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    ema_value = sum(values[:period]) / period

    for price in values[period:]:
        ema_value = (price - ema_value) * multiplier + ema_value

    return ema_value


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def run_unified_bot_strategy(candles, starting_balance=1000, fee_pct=0.04, slippage_pct=0.02):
    trades = []
    balance = float(starting_balance)
    position = None

    fee_rate = fee_pct / 100
    slippage_rate = slippage_pct / 100

    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    htf_ema = ema(closes, 100)

    def get_bias(price):
        if not htf_ema:
            return None
        return "bullish" if price > htf_ema else "bearish"

    for i in range(100, len(candles)):
        recent_closes = closes[:i]
        recent_highs = highs[i - 20:i]
        recent_lows = lows[i - 20:i]

        fast_ema = ema(recent_closes, 9)
        slow_ema = ema(recent_closes, 21)
        trend_ema = ema(recent_closes, 50)
        current_rsi = rsi(recent_closes, 14)

        close = closes[i]
        recent_high = max(recent_highs)
        recent_low = min(recent_lows)

        # 🔥 STRONG BREAK FILTER (avoid weak fake breakouts)
        bullish_break = close > recent_high and (close - recent_high) / recent_high > 0.001
        bearish_break = close < recent_low and (recent_low - close) / recent_low > 0.001

        bullish_bias = fast_ema and slow_ema and trend_ema and fast_ema > slow_ema and close > trend_ema
        bearish_bias = fast_ema and slow_ema and trend_ema and fast_ema < slow_ema and close < trend_ema

        bias = get_bias(close)

        buy_signal = (
            bias == "bullish"
            and bullish_bias
            and current_rsi
            and current_rsi < 70
            and bullish_break
        )

        sell_signal = (
            bias == "bearish"
            and bearish_bias
            and current_rsi
            and current_rsi > 30
            and bearish_break
        )

        if position is None and buy_signal:
            entry_price = close * (1 + slippage_rate)
            position = {
                "side": "BUY",
                "entry": entry_price,
                "time": candles[i][0],
                "reason": "HTF bullish bias + EMA trend + RSI filter + bullish structure break"
            }

        elif position is None and sell_signal:
            entry_price = close * (1 - slippage_rate)
            position = {
                "side": "SELL",
                "entry": entry_price,
                "time": candles[i][0],
                "reason": "HTF bearish bias + EMA trend + RSI filter + bearish structure break"
            }

        elif position is not None:
            if position["side"] == "BUY":
                stop_loss = position["entry"] * 0.9975   # -0.25%
                take_profit = position["entry"] * 1.0075 # +0.75%   

                exit_signal = (
                    close <= stop_loss or
                    close >= take_profit or
                    close < slow_ema
                )

                gross_pnl = close - position["entry"]

            else:
                stop_loss = position["entry"] * 1.0025   # -0.25%
                take_profit = position["entry"] * 0.9925 # +0.75%

                exit_signal = (
                    close >= stop_loss or
                    close <= take_profit or
                    close > slow_ema
                )

                gross_pnl = position["entry"] - close

if exit_signal:
    low = float(candles[i][3])
    high = float(candles[i][2])

    if position["side"] == "BUY":
        if low <= stop_loss:
            exit_price = stop_loss
        elif high >= take_profit:
            exit_price = take_profit
        else:
            exit_price = close
    else:
        if high >= stop_loss:
            exit_price = stop_loss
        elif low <= take_profit:
            exit_price = take_profit
        else:
            exit_price = close

    fees = (position["entry"] + exit_price) * fee_rate
    net_pnl = gross_pnl - fees
    balance += net_pnl

    trades.append({
        "side": position["side"],
        "entry": position["entry"],
        "exit": exit_price,
        "pnl": net_pnl,
        "entry_time": position["time"],
        "exit_time": candles[i][0],
        "reason": position["reason"]
    })

    position = None

        
        
return trades, balance


@app.route("/api/backtest", methods=["POST", "OPTIONS"])
@auth_required
def api_backtest():
    data = request.get_json(force=True) or {}
    symbol = str(data.get("symbol", "BTCUSDT")).upper()
    interval = str(data.get("interval", "5m"))
    strategy = str(data.get("strategy", "bot")).lower()
    limit = max(100, min(int(data.get("limit", 300)), 1000))
    sb = float(data.get("starting_balance", 1000))
    fee = float(data.get("fee_percent", 0.04))
    slip = float(data.get("slippage_percent", 0.02))

    candles = fetch_binance_raw(symbol, interval, limit)

    if not candles or len(candles) < 50:
        return jsonify({"error": "Not enough candle data"}), 400



    if strategy == "unified_bot":
        trades, ending_balance = run_unified_bot_strategy(
            candles,
            starting_balance=sb,
            fee_pct=fee,
            slippage_pct=slip
        )
    else:
        trades, ending_balance = run_simple_ma_strategy(
            candles,
            starting_balance=sb,
            fee_pct=fee,
            slippage_pct=slip
        )

    total_trades = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    net_pnl = ending_balance - sb
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss else 0

    return jsonify({
        "total_trades": total_trades,
        "net_pnl": net_pnl,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trades": trades
    })

@app.route("/api/backtest-runs", methods=["GET"])
@auth_required
def list_backtest_runs():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, symbol, interval, strategy, total_trades, net_pnl,
                 profit_factor, max_drawdown_percent, win_rate, created_at
                 FROM backtest_runs WHERE user_id=%s ORDER BY created_at DESC LIMIT 50""",
              (g.user_id,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "symbol": r[1], "interval": r[2], "strategy": r[3],
                     "total_trades": r[4], "net_pnl": r[5], "profit_factor": r[6],
                     "max_drawdown_percent": r[7], "win_rate": r[8], "created_at": r[9]}
                    for r in rows])


@app.route("/api/backtest-runs/<run_id>", methods=["GET"])
@auth_required
def backtest_run_detail(run_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT symbol, interval, strategy, summary_json, trades_json, created_at
                 FROM backtest_runs WHERE id=%s AND user_id=%s""", (run_id, g.user_id))
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"symbol": row[0], "interval": row[1], "strategy": row[2],
                    "summary": json.loads(row[3]), "trades": json.loads(row[4]),
                    "created_at": row[5]})


# Settings
@app.route("/api/settings", methods=["GET"])
@auth_required
def get_settings():
    return jsonify(get_user_config())


@app.route("/api/settings", methods=["POST"])
@auth_required
def update_settings():
    data = request.get_json(force=True) or {}
    cfg = get_user_config()
    # whitelist
    for k in ["risk_reward", "risk_percent", "min_confidence", "starting_balance",
              "max_trades_per_day", "max_daily_loss_percent", "max_consecutive_losses",
              "min_smc_score", "min_volume_multiplier", "trading_mode",
              "avoid_quiet_market", "avoid_sideways_market"]:
        if k in data:
            cfg[k] = data[k]
    if "symbols" in data and isinstance(data["symbols"], list):
        cfg["symbols"] = [s.upper() for s in data["symbols"] if isinstance(s, str)]
    if "blocked_crypto_hours_utc" in data and isinstance(data["blocked_crypto_hours_utc"], list):
        cfg["blocked_crypto_hours_utc"] = data["blocked_crypto_hours_utc"]
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET settings=%s WHERE id=%s", (json.dumps(cfg), g.user_id))
    conn.commit()
    conn.close()
    return jsonify(cfg)


# Journal
@app.route("/api/journal", methods=["GET"])
@auth_required
def list_journal():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, symbol, side, entry, exit, pnl, mood, tags, notes, created_at
                 FROM journal WHERE user_id=%s ORDER BY created_at DESC""", (g.user_id,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "symbol": r[1], "side": r[2], "entry": r[3],
                     "exit": r[4], "pnl": r[5], "mood": r[6],
                     "tags": json.loads(r[7] or "[]"), "notes": r[8], "created_at": r[9]}
                    for r in rows])


@app.route("/api/journal", methods=["POST"])
@auth_required
def create_journal():
    d = request.get_json(force=True) or {}
    eid = str(uuid.uuid4())
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO journal VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (
        eid, g.user_id, (d.get("symbol") or "").upper(), d.get("side"),
        float(d.get("entry") or 0), float(d.get("exit") or 0),
        float(d.get("pnl") or 0), d.get("mood") or "neutral",
        json.dumps(d.get("tags") or []), d.get("notes") or "",
        d.get("screenshot_url") or "", now_str()))
    conn.commit()
    conn.close()
    return jsonify({"id": eid, "ok": True})


@app.route("/api/journal/<eid>", methods=["DELETE"])
@auth_required
def delete_journal(eid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM journal WHERE id=%s AND user_id=%s", (eid, g.user_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

def simulate_market_execution(side, price, quantity, fee_percent=0.04, slippage_percent=0.02):
    fee_rate = fee_percent / 100
    slippage_rate = slippage_percent / 100

    if side.upper() == "BUY":
        fill_price = price * (1 + slippage_rate)
    else:
        fill_price = price * (1 - slippage_rate)

    notional = fill_price * quantity
    fee = notional * fee_rate

    return {
        "fill_price": fill_price,
        "quantity": quantity,
        "notional": notional,
        "fee": fee,
        "slippage_percent": slippage_percent,
        "fee_percent": fee_percent
    }

def get_latest_price(symbol="BTCUSDT"):
    candles = fetch_binance_raw(symbol, "1m", 2)
    if not candles:
        raise Exception("Could not fetch latest price")

    latest = candles[-1]
    return float(latest[4])

AUTO_PAPER_TRADING = {}

@app.route("/api/paper/start", methods=["POST", "OPTIONS"])
@auth_required
def paper_start():
    data = request.get_json(force=True) or {}

    symbol = (data.get("symbol") or "BTCUSDT").upper()
    side = (data.get("side") or "BUY").upper()
    quantity = float(data.get("quantity") or 0.001)

    latest_price = get_latest_price(symbol)

    execution = simulate_market_execution(
        side=side,
        price=latest_price,
        quantity=quantity,
        fee_percent=float(data.get("fee_percent") or 0.04),
        slippage_percent=float(data.get("slippage_percent") or 0.02)
    )

    trade_id = str(uuid.uuid4())

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT INTO trades
    (id, user_id, symbol, type, entry, sl, tp, size, exit, pnl, status, time)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", (
    trade_id,
    g.user_id,
    symbol,
    side,
    execution["fill_price"],
    0,
    0,
    quantity,
    0,
    0,
    "OPEN",
    now_str()
))
    return jsonify({
        "ok": True,
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "latest_price": latest_price,
        "execution": execution
    })
    
def update_open_trades():
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT id, symbol, type, entry, size FROM trades WHERE status='OPEN'")
    rows = c.fetchall()

    for trade_id, symbol, side, entry, size in rows:
        current_price = get_latest_price(symbol)

        if side == "BUY":
            pnl = (current_price - entry) * size
        else:
            pnl = (entry - current_price) * size

        c.execute("""
            UPDATE trades
            SET pnl=%s
            WHERE id=%s
        """, (pnl, trade_id))

    conn.commit()
    conn.close()

def run_auto_trading(user_id):
    symbol = "BTCUSDT"

    # get recent candles
    candles = fetch_binance_raw(symbol, "5m", 100)

    if not candles:
        return

    # VERY SIMPLE STRATEGY (placeholder)
    last = candles[-1]
    prev = candles[-2]

    last_close = float(last[4])
    prev_close = float(prev[4])

    # basic momentum
    if last_close > prev_close:
        side = "BUY"
    else:
        side = "SELL"

    # 🔥 place paper trade
    place_paper_trade(user_id, symbol, side, 0.001)

@app.route("/api/paper/update", methods=["POST", "OPTIONS"])
@auth_required
def paper_update():
    conn = get_conn()
    c = conn.cursor()

    update_open_trades()

    # 🔥 AUTO TRADING LOGIC
    if AUTO_PAPER_TRADING.get(g.user_id, False):
        try:
            run_auto_trading(g.user_id)
        except Exception as e:
            print("AUTO TRADING ERROR:", e)

    return jsonify({"ok": True, "message": "Updated + auto trading executed"})

    c.execute("SELECT id, symbol, type, entry, size FROM trades WHERE status='OPEN'")
    rows = c.fetchall()

    for t in rows:
        trade_id, symbol, side, entry, size = t

        current_price = get_latest_price(symbol)

        if side == "BUY":
            pnl = (current_price - entry) * size
        else:
            pnl = (entry - current_price) * size

        # simple close rule (demo): close if profit or loss exceeds threshold
        if abs(pnl) > 5:
            c.execute("""
                UPDATE trades
                SET exit=%s, pnl=%s, status=%s
                WHERE id=%s
            """, (current_price, pnl, "CLOSED", trade_id))
        else:
            c.execute("""
                UPDATE trades
                SET pnl=%s
                WHERE id=%s
            """, (pnl, trade_id))

    conn.commit()
    conn.close()




@app.route("/api/paper/status", methods=["GET", "OPTIONS"])
@auth_required
def paper_status():
    return jsonify({
        "enabled": AUTO_PAPER_TRADING.get(g.user_id, False)
    })


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

# Paper trades
@app.route("/api/trades", methods=["GET"])
@auth_required
def list_trades():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT id, symbol, type, entry, sl, tp, size, exit, pnl, status, time
                 FROM trades WHERE user_id=%s ORDER BY time DESC LIMIT 200""", (g.user_id,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "symbol": r[1], "side": r[2], "entry": r[3],
                     "sl": r[4], "tp": r[5], "size": r[6], "exit": r[7],
                     "pnl": r[8], "status": r[9], "time": r[10]} for r in rows])


@app.route("/api/trades", methods=["POST"])
@auth_required
def open_paper_trade():
    d = request.get_json(force=True) or {}
    sym = (d.get("symbol") or "BTCUSDT").upper()
    side = d.get("side", "BUY").upper()
    df = fetch_binance(sym, "1m", 200)
    if df is None: return jsonify({"error": "No market data"}), 400
    cfg = get_user_config()
    levels = calculate_trade_levels(df, side, cfg.get("risk_reward", 2))
    price = float(df.iloc[-1]["close"])
    risk_amt = cfg["starting_balance"] * (cfg["risk_percent"] / 100)
    stop_dist = abs(price - levels["sl"])
    size = risk_amt / stop_dist if stop_dist else 0
    tid = str(uuid.uuid4())
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO trades VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, 'OPEN', %s)", (
        tid, g.user_id, sym, side, price, levels["sl"], levels["tp"], size, now_str()))
    conn.commit(); conn.close()
    add_alert(g.user_id, f"OPEN {sym} {side} @ {round(price,2)}")
    return jsonify({"ok": True, "id": tid, "entry": price, "sl": levels["sl"], "tp": levels["tp"], "size": size})


@app.route("/api/trades/<tid>/close", methods=["POST"])
@auth_required
def close_paper_trade(tid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT symbol, type, entry, size FROM trades WHERE id=%s AND user_id=%s AND status='OPEN'",
              (tid, g.user_id))
    row = c.fetchone()
    if not row: conn.close(); return jsonify({"error": "Trade not found"}), 404
    sym, side, entry, size = row
    df = fetch_binance(sym, "1m", 5)
    price = float(df.iloc[-1]["close"]) if df is not None else float(entry)
    pnl = (price - entry) * size if side == "BUY" else (entry - price) * size
    c.execute("UPDATE trades SET exit=%s, pnl=%s, status='CLOSED', time=%s WHERE id=%s",
              (price, pnl, now_str(), tid))
    conn.commit(); conn.close()
    add_alert(g.user_id, f"CLOSED {sym} PnL {round(pnl,2)}")
    return jsonify({"ok": True, "exit_price": price, "pnl": round(pnl, 2)})


@app.route("/api/alerts", methods=["GET"])
@auth_required
def get_alerts():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT message, time FROM alerts WHERE user_id=%s ORDER BY time DESC LIMIT 50", (g.user_id,))
    rows = c.fetchall(); conn.close()
    return jsonify([{"message": r[0], "time": r[1]} for r in rows])


@app.route("/api/equity", methods=["GET"])
@auth_required
def equity():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT pnl, time FROM trades WHERE user_id=%s AND status='CLOSED'", (g.user_id,))
    rows = c.fetchall(); conn.close()
    cfg = get_user_config()
    bal = cfg["starting_balance"]
    pts = [{"time": "Start", "equity": round(bal, 2)}]
    for pnl, t in rows:
        bal += float(pnl or 0)
        pts.append({"time": t, "equity": round(bal, 2)})
    return jsonify(pts)


@app.route("/api/stats", methods=["GET"])
@auth_required
def stats():
    conn = get_conn(); c = conn.cursor()
    c.execute("""SELECT pnl FROM trades WHERE user_id=%s AND status='CLOSED'""", (g.user_id,))
    pnls = [float(r[0] or 0) for r in c.fetchall()]
    conn.close()
    total = len(pnls); wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p < 0]
    cfg = get_user_config()
    return jsonify({
        "total_trades": total, "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / total * 100, 2) if total else 0,
        "net_pnl": round(sum(pnls), 2),
        "balance": round(cfg["starting_balance"] + sum(pnls), 2),
        "starting_balance": cfg["starting_balance"],
    })

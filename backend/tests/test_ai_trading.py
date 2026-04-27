"""AI Trading Engine - pytest backend suite"""
import os, uuid, pytest, requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://algo-trading-lab-5.preview.emergentagent.com").rstrip("/")
DEMO = {"email": "trader@demo.com", "password": "trader123"}

@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE}/api/auth/login", json=DEMO, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]

@pytest.fixture(scope="session")
def h(token):
    return {"Authorization": f"Bearer {token}"}

# --- auth ---
def test_health():
    r = requests.get(f"{BASE}/api/health", timeout=10)
    assert r.status_code == 200 and r.json().get("ok") is True

def test_register_new():
    email = f"test_{uuid.uuid4().hex[:8]}@demo.com"
    r = requests.post(f"{BASE}/api/auth/register", json={"email": email, "password": "pass1234", "name": "T"}, timeout=20)
    assert r.status_code == 200
    d = r.json(); assert "token" in d and d["user"]["email"] == email

def test_login(token):
    assert isinstance(token, str) and len(token) > 20

def test_me(h):
    r = requests.get(f"{BASE}/api/auth/me", headers=h, timeout=20)
    assert r.status_code == 200 and r.json()["email"] == "trader@demo.com"

def test_me_unauth():
    r = requests.get(f"{BASE}/api/auth/me", timeout=10)
    assert r.status_code == 401

# --- market/signals ---
def test_signals(h):
    r = requests.get(f"{BASE}/api/signals?interval=5m", headers=h, timeout=60)
    assert r.status_code == 200
    d = r.json(); assert "signals" in d and isinstance(d["signals"], list)
    if d["signals"]:
        s = d["signals"][0]
        for k in ["symbol","price","signal","confidence","smc_score","reasons","entry","sl","tp"]:
            assert k in s, f"missing {k}"

def test_chart_candles(h):
    r = requests.get(f"{BASE}/api/chart-candles?symbol=BTCUSDT&interval=5m&limit=200", headers=h, timeout=30)
    assert r.status_code == 200
    d = r.json(); assert d.get("ok") is True and len(d["data"]) > 10

# --- settings ---
def test_settings_flow(h):
    r = requests.get(f"{BASE}/api/settings", headers=h, timeout=20); assert r.status_code == 200
    cfg = r.json(); assert "symbols" in cfg and "trading_mode" in cfg
    r2 = requests.post(f"{BASE}/api/settings", headers=h, json={"trading_mode": "testnet", "min_confidence": 70}, timeout=20)
    assert r2.status_code == 200
    d2 = r2.json(); assert d2["trading_mode"] == "testnet" and d2["min_confidence"] == 70
    # revert
    requests.post(f"{BASE}/api/settings", headers=h, json={"trading_mode": "local_paper", "min_confidence": 75}, timeout=20)

# --- backtest ---
@pytest.fixture(scope="session")
def bt_run(h):
    r = requests.post(f"{BASE}/api/backtest", headers=h, json={
        "symbol": "BTCUSDT", "interval": "5m", "strategy": "bot", "limit": 300, "starting_balance": 1000
    }, timeout=90)
    assert r.status_code == 200, r.text
    d = r.json(); assert d.get("ok") and "summary" in d and "trades" in d and "id" in d
    return d

def test_backtest(bt_run):
    s = bt_run["summary"]
    for k in ["starting_balance","final_balance","net_pnl","total_trades","win_rate"]:
        assert k in s

def test_backtest_runs_list(h, bt_run):
    r = requests.get(f"{BASE}/api/backtest-runs", headers=h, timeout=20)
    assert r.status_code == 200 and any(run["id"] == bt_run["id"] for run in r.json())

def test_backtest_run_detail(h, bt_run):
    r = requests.get(f"{BASE}/api/backtest-runs/{bt_run['id']}", headers=h, timeout=20)
    assert r.status_code == 200 and r.json()["symbol"] == "BTCUSDT"

# --- journal ---
def test_journal_crud(h):
    create = requests.post(f"{BASE}/api/journal", headers=h, json={
        "symbol":"BTCUSDT","side":"BUY","entry":100,"exit":110,"pnl":10,"mood":"good","tags":["TEST"],"notes":"TEST_entry"
    }, timeout=20)
    assert create.status_code == 200
    eid = create.json()["id"]
    lst = requests.get(f"{BASE}/api/journal", headers=h, timeout=20).json()
    assert any(e["id"] == eid for e in lst)
    d = requests.delete(f"{BASE}/api/journal/{eid}", headers=h, timeout=20)
    assert d.status_code == 200
    lst2 = requests.get(f"{BASE}/api/journal", headers=h, timeout=20).json()
    assert not any(e["id"] == eid for e in lst2)

# --- paper trades ---
def test_trade_flow(h):
    r = requests.post(f"{BASE}/api/trades", headers=h, json={"symbol":"BTCUSDT","side":"BUY"}, timeout=30)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    lst = requests.get(f"{BASE}/api/trades", headers=h, timeout=20).json()
    assert any(t["id"] == tid for t in lst)
    c = requests.post(f"{BASE}/api/trades/{tid}/close", headers=h, timeout=30)
    assert c.status_code == 200 and "pnl" in c.json()

def test_stats(h):
    r = requests.get(f"{BASE}/api/stats", headers=h, timeout=20)
    assert r.status_code == 200 and "balance" in r.json()

def test_equity(h):
    r = requests.get(f"{BASE}/api/equity", headers=h, timeout=20)
    assert r.status_code == 200 and isinstance(r.json(), list)

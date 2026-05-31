#!/usr/bin/env python3
"""
PDH Sweep OOS diagnostic battery.

Runs:
  - 6 backtests  : SPY / QQQ / AAPL × 180d / 365d
  - 3 walk-forwards : SPY / QQQ / AAPL × 365d, 4 windows

Usage
-----
    set TRADING_API_URL=https://eg-on9b.onrender.com
    set TRADING_TOKEN=<your JWT from DevTools → Application → Local Storage>
    python pdh_battery.py

The token is read once from the environment and is NEVER printed,
logged, or included in any output produced by this script.

Pre-committed PASS bar (evaluated in Step 4):
    OOS profit factor >= 1.3 on majority of symbols
    p-value < 0.05 (SIGNIFICANT) on majority of symbols
    Walk-forward STABLE on majority of symbols
    >= 100 aggregated OOS trades across all symbols/periods
"""

import os
import sys
import time
import warnings
import requests
from urllib3.exceptions import InsecureRequestWarning
warnings.filterwarnings("ignore", category=InsecureRequestWarning)

# ── Auth — environment only, never echoed ────────────────────────────────────
_API_BASE = os.environ.get("TRADING_API_URL", "").rstrip("/")
_TOKEN    = os.environ.get("TRADING_TOKEN",   "")

if not _API_BASE:
    sys.exit("ERROR: set TRADING_API_URL  (e.g. https://eg-on9b.onrender.com)")
if not _TOKEN:
    sys.exit("ERROR: set TRADING_TOKEN to your JWT — do not paste it here")

_HEADERS = {
    "Authorization": f"Bearer {_TOKEN}",
    "Content-Type":  "application/json",
}

# ── Test matrix ───────────────────────────────────────────────────────────────
SYMBOLS  = ["SPY", "QQQ", "AAPL"]
PERIODS  = [180, 365]

BT_BASE = dict(
    strategy         = "pdh_sweep",
    interval         = "5m",
    train_pct        = 0.70,
    starting_balance = 10_000,
    fee_percent      = 0.04,
    slippage_percent = 0.02,
    random_window    = False,
)

WF_BASE = dict(
    strategy         = "pdh_sweep",
    period_days      = 365,
    n_windows        = 4,
    train_pct        = 0.70,
    starting_balance = 10_000,
    fee_percent      = 0.04,
    slippage_percent = 0.02,
)

# ── HTTP helper ───────────────────────────────────────────────────────────────
def post(endpoint, body, timeout=300, retries=2):
    url = f"{_API_BASE}{endpoint}"
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, headers=_HEADERS, json=body,
                              timeout=timeout, verify=False)
            return r.status_code, r.json()
        except requests.exceptions.Timeout:
            if attempt < retries:
                print(f"    timeout, retrying ({attempt+1}/{retries})…", flush=True)
                time.sleep(10)
            else:
                return 0, {"error": "timeout after retries"}
        except Exception as e:
            return 0, {"error": str(e)}

# ── Run battery ───────────────────────────────────────────────────────────────
n_bt = len(SYMBOLS) * len(PERIODS)
n_wf = len(SYMBOLS)
print(f"\nPDH Sweep OOS diagnostic battery")
print(f"{n_bt} backtests  +  {n_wf} walk-forwards  =  {n_bt + n_wf} total calls")
print("Note: first call per symbol will fetch ~7 pages from Twelve Data (~56s fetch + sleep)")
print("=" * 80)

bt_rows = []
wf_rows = {}

# ── Backtests ─────────────────────────────────────────────────────────────────
print("\n[BACKTESTS]")
for sym in SYMBOLS:
    for days in PERIODS:
        body = {**BT_BASE, "symbol": sym, "period_days": days}
        print(f"  BT  {sym:<5} {days:>3}d … ", end="", flush=True)
        code, data = post("/api/backtest", body, timeout=360)

        if code != 200 or "error" in data:
            err = data.get("error", f"HTTP {code}")[:80]
            print(f"FAIL  {err}")
            bt_rows.append(dict(symbol=sym, days=days, error=err))
            time.sleep(1)
            continue

        te  = data.get("test_summary") or {}
        row = dict(
            symbol     = sym,
            days       = days,
            oos_trades = te.get("total_trades",  0),
            oos_wr     = te.get("win_rate",       0.0),
            oos_pf     = te.get("profit_factor",  0.0),
            oos_pnl    = te.get("net_pnl",        0.0),
            p_value    = te.get("p_value"),
            sig        = te.get("significant",    False),
            low_sample = data.get("low_sample_warning", False),
        )
        bt_rows.append(row)

        pv  = f"p={row['p_value']:.4f}" if row["p_value"] is not None else "p=n/a"
        sig = "SIG" if row["sig"] else "not-sig"
        lw  = "  ⚠ low-sample" if row["low_sample"] else ""
        print(
            f"trades={row['oos_trades']:>3}  WR={row['oos_wr']:>5.1f}%  "
            f"PF={row['oos_pf']:>5.2f}  PnL={row['oos_pnl']:>+9.2f}  "
            f"{pv}  {sig}{lw}"
        )
        time.sleep(1)

# ── Walk-forwards ─────────────────────────────────────────────────────────────
print("\n[WALK-FORWARDS  (365d, 4 windows each)]")
for sym in SYMBOLS:
    body = {**WF_BASE, "symbol": sym}
    print(f"  WF  {sym:<5} 365d … ", end="", flush=True)
    code, data = post("/api/walkforward", body, timeout=480)

    if code != 200 or "error" in data:
        err = data.get("error", f"HTTP {code}")[:80]
        print(f"FAIL  {err}")
        wf_rows[sym] = dict(error=err)
        time.sleep(1)
        continue

    agg = data.get("aggregate") or {}
    wf_rows[sym] = dict(
        verdict = agg.get("verdict",           "?"),
        consist = agg.get("consistency_pct",    0.0),
        w_prof  = agg.get("windows_profitable", 0),
        w_tot   = agg.get("windows_total",      0),
        trades  = agg.get("total_trades",       0),
        wr      = agg.get("win_rate",           0.0),
        pf      = agg.get("profit_factor",      0.0),
        pnl     = agg.get("net_pnl",            0.0),
        p_value = agg.get("p_value"),
        sig     = agg.get("significant",        False),
    )
    wf = wf_rows[sym]
    pv  = f"p={wf['p_value']:.4f}" if wf["p_value"] is not None else "p=n/a"
    sig = "SIG" if wf["sig"] else "not-sig"
    print(
        f"{wf['verdict']:<10}  {wf['w_prof']}/{wf['w_tot']} windows profitable  "
        f"PF={wf['pf']:>5.2f}  {pv}  {sig}"
    )
    time.sleep(1)

# ── Results table ─────────────────────────────────────────────────────────────
SEP  = "=" * 110
SEP2 = "-" * 110
COL  = "{:<6} {:>5}  {:>9}  {:>8}  {:>8}  {:>11}  {:>8}  {:>7}  {:>11}  {}"

print(f"\n\n{SEP}")
print("PDH SWEEP — FULL OOS BACKTEST RESULTS")
print(SEP)
print(COL.format(
    "SYMBOL", "DAYS",
    "OOS TRD", "OOS WR%", "OOS PF", "OOS PnL($)",
    "P-VALUE", "SIG?", "WF VERDICT", "NOTES",
))
print(SEP2)

total_oos_trades = 0
for row in bt_rows:
    sym = row["symbol"]
    wf  = wf_rows.get(sym, {})

    if "error" in row:
        print(COL.format(
            sym, row["days"],
            "—", "—", "—", "—", "—", "—", "—",
            f"ERROR: {row['error'][:45]}",
        ))
        continue

    total_oos_trades += row["oos_trades"]
    wf_str = wf.get("verdict", "—") if row["days"] == 365 else "—"
    pv_str = f"{row['p_value']:.4f}" if row["p_value"] is not None else "n/a"
    notes  = []
    if row["low_sample"]:
        notes.append("low-sample")
    if "error" in wf and row["days"] == 365:
        notes.append(f"WF-ERR:{wf['error'][:30]}")

    print(COL.format(
        sym, row["days"],
        row["oos_trades"],
        f"{row['oos_wr']:.1f}%",
        f"{row['oos_pf']:.2f}",
        f"{row['oos_pnl']:+.2f}",
        pv_str,
        "YES" if row["sig"] else "no",
        wf_str,
        ", ".join(notes),
    ))

print(SEP2)
print(f"Total OOS trades across all rows: {total_oos_trades}")

# ── Walk-forward detail ───────────────────────────────────────────────────────
WF_COL = "{:<6} {:<11} {:>9}  {:>8}  {:>8}  {:>8}  {:>11}  {:>8}  {:>7}"

print(f"\n{SEP}")
print("WALK-FORWARD DETAIL  (365d, 4 windows, pdh_sweep)")
print(SEP)
print(WF_COL.format(
    "SYMBOL", "VERDICT", "CONSIST%",
    "OOS TRD", "OOS WR%", "OOS PF", "OOS PnL($)",
    "P-VALUE", "SIG?",
))
print(SEP2)

for sym in SYMBOLS:
    wf = wf_rows.get(sym, {})
    if "error" in wf:
        print(f"{sym:<6}  ERROR: {wf['error'][:80]}")
        continue
    pv_str = f"{wf['p_value']:.4f}" if wf["p_value"] is not None else "n/a"
    print(WF_COL.format(
        sym,
        wf["verdict"],
        f"{wf['consist']:.1f}%",
        wf["trades"],
        f"{wf['wr']:.1f}%",
        f"{wf['pf']:.2f}",
        f"{wf['pnl']:+.2f}",
        pv_str,
        "YES" if wf["sig"] else "no",
    ))

print(f"{SEP2}\n")
print("Battery complete. Paste the full output above back to Claude for Step 4 verdict.")

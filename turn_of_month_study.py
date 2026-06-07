#!/usr/bin/env python3
"""
Turn-of-Month study  ---  rigorous OOS test of the [-1, +3] turn-of-month effect.

Hypothesis: US equity indices earn abnormal positive returns from the close of the
second-to-last trading day of the month through the close of the third trading day
of the next month (capturing the daily returns of days -1, +1, +2, +3), driven by
price-insensitive, calendar-scheduled cash flows.

Spec (matches the committed backend strategy):
  - Entry : close of the 2nd-to-last trading day of the month   (bar i-1)
  - Exit  : close of the 3rd trading day of the next month       (bar i+3)
            where i = the last trading day of the month.
  - Held return spans the daily returns of days -1, +1, +2, +3.
  - Fixed notional, non-compounding -> profit factor / win rate are scale-invariant.
  - Round-trip cost deducted from every trade's return.
  - 70/30 split by date; the verdict is on the OUT-OF-SAMPLE (test) portion.

Pre-committed kill criteria (a strategy survives only if ALL hold):
  1. OOS profit factor >= 1.3 on a majority of symbols.
  2. OOS mean net return significantly > 0  (one-sided t-test, p < 0.05).
  3. Walk-forward stable across blocks (consistent sign on a majority of symbols).
  4. Concentration: in-window mean daily return > out-of-window, significantly.

Run:  pip install yfinance pandas scipy numpy
      python turn_of_month_study.py
"""

import numpy as np
import pandas as pd
from scipy import stats

SYMBOLS      = ["SPY", "QQQ", "IWM", "DIA"]
START        = "1993-01-01"          # each symbol returns from its own inception
TRAIN_FRAC   = 0.70
FEE_PCT      = 0.04                   # one-way, %
SLIP_PCT     = 0.02                   # one-way, %
SPREAD_PCT   = 0.02                   # one-way, %
ROUND_TRIP   = 2 * (FEE_PCT + SLIP_PCT + SPREAD_PCT) / 100.0   # as a fraction
WF_BLOCKS    = 5


# ----------------------------------------------------------------------------- data
def load_prices(symbol):
    """Daily adjusted close. Primary: yfinance. Fallback: Stooq CSV."""
    try:
        import yfinance as yf
        df = yf.download(symbol, start=START, progress=False, auto_adjust=True)
        if df is None or len(df) == 0:
            raise RuntimeError("yfinance returned nothing")
        close = df["Close"]
        if isinstance(close, pd.DataFrame):      # MultiIndex columns -> take the col
            close = close.iloc[:, 0]
    except Exception as e:
        print(f"  [yfinance failed for {symbol}: {e}; falling back to Stooq]")
        url = f"https://stooq.com/q/d/l/?s={symbol.lower()}.us&i=d"
        df = pd.read_csv(url, parse_dates=["Date"]).set_index("Date").sort_index()
        close = df["Close"]                       # NOTE: Stooq close is split- but
        #                                           not always dividend-adjusted.
    close = close.astype(float).dropna()
    close.name = symbol
    return close


# ------------------------------------------------------------------------- helpers
def last_of_month_mask(index):
    """True where bar i is the last trading bar of its calendar month."""
    ym = index.to_period("M")
    mask = np.zeros(len(index), dtype=bool)
    mask[:-1] = (ym[:-1] != ym[1:])
    return mask


def one_sided_p_gt0(net_rets):
    """p-value for H0: mean <= 0 vs H1: mean > 0."""
    if len(net_rets) < 2:
        return 1.0
    t, p_two = stats.ttest_1samp(net_rets, 0.0)
    return (p_two / 2.0) if t > 0 else (1.0 - p_two / 2.0)


def profit_factor(net_rets):
    wins   = net_rets[net_rets > 0].sum()
    losses = -net_rets[net_rets < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


# -------------------------------------------------------------------------- trades
def turn_of_month_trades(prices):
    """DataFrame of trades: entry_date, exit_date, gross_ret, net_ret."""
    idx  = prices.index
    vals = prices.values
    last_idxs = np.where(last_of_month_mask(idx))[0]
    rows = []
    for i in last_idxs:
        if i - 1 < 0 or i + 3 >= len(vals):       # need bar i-1 and bar i+3
            continue
        entry = vals[i - 1]                        # close of day -2
        exit_ = vals[i + 3]                        # close of day +3
        gross = exit_ / entry - 1.0
        rows.append({
            "entry_date": idx[i - 1],
            "exit_date":  idx[i + 3],
            "gross_ret":  gross,
            "net_ret":    gross - ROUND_TRIP,
        })
    return pd.DataFrame(rows)


def concentration_test(prices):
    """In-window daily returns vs out-of-window daily returns over the full sample.
    In-window return days are -1,+1,+2,+3  ->  bar indices i, i+1, i+2, i+3."""
    idx       = prices.index
    last_idxs = np.where(last_of_month_mask(idx))[0]
    in_window = np.zeros(len(idx), dtype=bool)
    for i in last_idxs:
        for k in (0, 1, 2, 3):                     # day -1 sits at bar i
            j = i + k
            if 0 <= j < len(idx):
                in_window[j] = True
    daily = prices.pct_change().dropna().values    # returns for bars 1..N-1
    flags = in_window[1:]                           # align: daily[k] <-> bar k+1
    rin, rout = daily[flags], daily[~flags]
    t, p = stats.ttest_ind(rin, rout, equal_var=False)
    return rin.mean() * 100, rout.mean() * 100, len(rin), len(rout), t, p


def walk_forward(trades, blocks=WF_BLOCKS):
    if len(trades) < blocks:
        return "    walk-forward: too few trades"
    bounds = np.linspace(0, len(trades), blocks + 1).astype(int)
    out = []
    for k in range(blocks):
        c = trades.iloc[bounds[k]:bounds[k + 1]]
        if len(c) == 0:
            continue
        lo, hi = c["entry_date"].min().date(), c["entry_date"].max().date()
        out.append(f"    block {k+1} [{lo} .. {hi}]  n={len(c):>3}  "
                   f"PF={profit_factor(c['net_ret'].values):.2f}  "
                   f"mean/trade={c['net_ret'].mean()*100:+.3f}%")
    return "\n".join(out)


# ----------------------------------------------------------------------- reporting
def summarize(net_rets, label):
    n = len(net_rets)
    if n == 0:
        return f"  {label}: no trades"
    return (f"  {label}: n={n:>4}  win={ (net_rets>0).mean()*100:5.1f}%  "
            f"PF={profit_factor(net_rets):5.2f}  "
            f"mean/trade={net_rets.mean()*100:+.3f}%  p(mean>0)={one_sided_p_gt0(net_rets):.4f}")


def run_symbol(symbol):
    print(f"\n===== {symbol} =====")
    try:
        prices = load_prices(symbol)
    except Exception as e:
        print(f"  FAILED to load {symbol}: {e}")
        return None
    if len(prices) < 200:
        print(f"  too little data ({len(prices)} bars)")
        return None
    print(f"  data : {prices.index.min().date()} -> {prices.index.max().date()}  "
          f"({len(prices)} bars)")

    trades = turn_of_month_trades(prices).sort_values("entry_date").reset_index(drop=True)
    if trades.empty:
        print("  no trades generated"); return None

    split_i = int(len(trades) * TRAIN_FRAC)
    train, test = trades.iloc[:split_i], trades.iloc[split_i:]
    split_date = trades.iloc[split_i]["entry_date"].date() if split_i < len(trades) else "n/a"
    print(f"  trades: {len(trades)} total  ({len(train)} train / {len(test)} OOS)   "
          f"split at {split_date}")
    print(summarize(train["net_ret"].values, "TRAIN"))
    print(summarize(test["net_ret"].values,  "OOS  "))

    cin, cout, nin, nout, ct, cp = concentration_test(prices)
    print(f"  CONCENTRATION (full sample): in-window {cin:+.4f}%/day (n={nin}) "
          f"vs out-of-window {cout:+.4f}%/day (n={nout})   t={ct:.2f}  p={cp:.4f}")

    print("  WALK-FORWARD (net, per block):")
    print(walk_forward(trades))

    return {
        "symbol":   symbol,
        "oos_pf":   profit_factor(test["net_ret"].values),
        "oos_n":    len(test),
        "oos_p":    one_sided_p_gt0(test["net_ret"].values),
        "conc_p":   cp,
        "conc_diff": cin - cout,
    }


def main():
    print(f"Turn-of-Month [-1,+3] study | round-trip cost {ROUND_TRIP*100:.2f}% | "
          f"train {int(TRAIN_FRAC*100)}% / OOS {100-int(TRAIN_FRAC*100)}%")
    results = [r for r in (run_symbol(s) for s in SYMBOLS) if r]

    print("\n===== VERDICT vs pre-committed criteria =====")
    if not results:
        print("  No results."); return
    n        = len(results)
    pf_pass  = sum(r["oos_pf"]  >= 1.3 for r in results)
    sig_pass = sum(r["oos_p"]   < 0.05 for r in results)
    con_pass = sum((r["conc_p"] < 0.05 and r["conc_diff"] > 0) for r in results)
    print(f"  1. OOS profit factor >= 1.3 :            {pf_pass}/{n} symbols")
    print(f"  2. OOS mean net return p<0.05 :          {sig_pass}/{n} symbols")
    print(f"  4. Concentration (in>out, p<0.05) :      {con_pass}/{n} symbols")
    print(f"  3. Walk-forward stability : read the per-symbol blocks above")
    print(f"  Aggregate OOS trades across symbols : {sum(r['oos_n'] for r in results)}")
    print("\n  Per-symbol OOS:")
    for r in results:
        print(f"    {r['symbol']:<4}  PF={r['oos_pf']:5.2f}  n={r['oos_n']:>3}  "
              f"p(mean>0)={r['oos_p']:.4f}  concentration p={r['conc_p']:.4f}")


if __name__ == "__main__":
    main()

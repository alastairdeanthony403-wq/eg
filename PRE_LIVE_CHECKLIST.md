# Pre-Live Trading Checklist

> **This checklist must be completed in full before funding any account or enabling live-order execution.**
> It is a written gate — not a formality. Every item must be signed off with a date and supporting data.

---

## 1. Paper Trading Duration

| Requirement | Minimum | Your Result | Met? |
|-------------|---------|-------------|------|
| Continuous paper trading period | **90 calendar days** | | ☐ |
| Active markets covered (not all on same symbol) | **≥ 3 symbols** | | ☐ |
| Market regimes sampled (trend + range + volatile) | **All three** | | ☐ |

**Rationale:** 90 days is long enough to cross at least two monthly expiries and capture several distinct macro regimes. Shorter periods routinely over-represent a single regime.

---

## 2. Required Sample Size

| Requirement | Minimum | Your Result | Met? |
|-------------|---------|-------------|------|
| Total closed paper trades | **≥ 100** | | ☐ |
| Trades per symbol (for any symbol you intend to trade live) | **≥ 30** | | ☐ |
| Trades while kill-switch was NOT halted | Must be ≥ 80% of total | | ☐ |

**Rationale:** Below 100 trades, win-rate confidence intervals are too wide to distinguish edge from noise. The 30-per-symbol floor ensures each instrument is independently validated.

---

## 3. Paper vs. Backtest Divergence

Run `/api/fill-reconciliation` and compare to backtest summary. All figures are absolute values.

| Metric | Acceptable Threshold | Your Result | Met? |
|--------|---------------------|-------------|------|
| Mean entry slippage (paper vs. expected) | **≤ 0.15%** | | ☐ |
| Max single-trade entry slippage | **≤ 0.50%** | | ☐ |
| Paper win rate vs. backtest win rate (same period) | **Within ±10 percentage points** | | ☐ |
| Paper profit factor vs. backtest profit factor | **Paper ≥ backtest × 0.70** (≤ 30% decay) | | ☐ |
| Trades where actual fill missed expected level by > 0.5% | **≤ 5% of total** | | ☐ |

**If paper/backtest profit factor is below 70% of backtest:** do NOT proceed. The strategy likely has look-ahead bias, spread underestimation, or execution assumptions that don't hold in real time.

---

## 4. Drawdown Limits

These limits apply to paper trading evaluation **and** must become the live account hard limits before funding.

| Rule | Threshold | Enforcement |
|------|-----------|-------------|
| Maximum intraday drawdown | **2% of starting balance** | Kill-switch (`max_daily_loss_percent` in config) |
| Maximum total account drawdown | **5% of peak balance** | Kill-switch (`max_account_drawdown_pct` in config) |
| Maximum weekly loss | **0.8% of starting balance** | Weekly pause gate (existing) |
| Paper account hit max drawdown during evaluation | **Zero tolerance** — reset and restart 90-day clock | Manual review |

**Prop / funded account note:** Most prop firms use a 5% trailing drawdown on the funded balance. The bot's `max_account_drawdown_pct` must be set to **at most 4%** to give a 1% buffer against broker spread and timing.

---

## 5. Strategy Stability (Walk-Forward)

Before going live on any strategy, run `/api/walkforward` with the default settings (4 windows, 120 days).

| Requirement | Threshold | Your Result | Met? |
|-------------|-----------|-------------|------|
| Walk-forward verdict | **STABLE** | | ☐ |
| Percentage of OOS windows with profit factor > 1 | **≥ 75%** | | ☐ |
| OOS profit factor (aggregate) | **≥ 1.20** | | ☐ |

---

## 6. Infrastructure Checks

| Item | Requirement | Met? |
|------|-------------|------|
| `LIVE_MODE_ENABLED` env var | Must remain `false` until all other items are checked | ☐ |
| Risk backstop configured | `max_account_drawdown_pct` set ≤ 5% | ☐ |
| Kill-switch tested | Manually triggered and confirmed it halts new trades | ☐ |
| Fill reconciliation reviewed | `/api/fill-reconciliation` output reviewed and acceptable | ☐ |
| Emergency stop tested | `POST /api/bot/stop` confirmed to stop bot scan | ☐ |
| Broker API integration reviewed | **Not yet implemented** — must be built and security-audited before enabling | ☐ |

---

## 7. Sign-Off

This section must be completed by hand before `LIVE_MODE_ENABLED=true` is set on any server.

```
Paper trading start date:  _______________
Paper trading end date:    _______________
Total paper trades:        _______________
Paper profit factor:       _______________
Backtest profit factor:    _______________
Divergence acceptable:     YES / NO
Walk-forward verdict:      STABLE / MIXED / UNSTABLE
Max drawdown observed:     _______________  (must be < 5%)
Kill-switch tested:        YES / NO

Decision: APPROVED / NOT APPROVED

Notes:
_______________________________________________________________
_______________________________________________________________
```

---

> **Reminder:** Enabling live trading without completing this checklist exposes real capital to a strategy that may not perform as the backtester suggests. The backtester uses historical data with pessimistic assumptions — real fills, spreads, and latency will always be worse than simulation. Budget for this.

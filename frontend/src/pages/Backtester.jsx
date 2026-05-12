import { useState, useRef, useEffect } from "react";
import api from "@/lib/api";
import { createChart, CandlestickSeries, LineSeries } from "lightweight-charts";
import {
  Play, RotateCcw, TrendingUp, TrendingDown, AlertCircle,
  CheckCircle, Clock, BarChart2, Shuffle, Calendar,
} from "lucide-react";

// ── Canonical symbol list — must match backend ALL_SYMBOLS ──────────────────
const MARKET_GROUPS = {
  Crypto:      ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
  Forex:       ["EURUSD",  "GBPUSD",  "USDJPY",  "AUDUSD",  "USDCAD"],
  Stocks:      ["AAPL",    "TSLA",    "NVDA",    "MSFT",    "AMZN", "SPY"],
  Commodities: ["XAUUSD",  "XAGUSD",  "USOIL",   "UKOIL"],
};

// Flat list in the same order as the backend
const ALL_SYMBOLS = Object.values(MARKET_GROUPS).flat();

const INTERVALS   = ["1m", "5m", "15m", "1h", "4h"];
const STRATEGIES  = [
  { value: "unified_bot", label: "Unified Bot (SMC Session)",
    desc: "ICT/SMC — Asian range, London sweep, NY reversal. Daily limits: 3 wins max, 1 loss max." },
  { value: "orb_0dte",    label: "0DTE Opening Range Breakout",
    desc: "SPY options simulation. Mon/Wed/Fri only. 5-min ORB with +100% TP / -50% SL. 2% risk." },
  { value: "vwap_ema",    label: "VWAP + EMA Trend",
    desc: "9/21 EMA cross after 10:30 ET, VWAP support/resistance filter. 2-part scaling: 50% at 75% ADR, trail remainder at 1×ATR. 2% risk." },
  { value: "simple_ma",   label: "Simple MA Crossover",
    desc: "10/30 SMA crossover baseline strategy." },
];

// ── Price formatter matching backend format_price() ─────────────────────────
function formatPrice(price, symbol) {
  if (price == null || price === 0) return "—";
  if (symbol?.endsWith("USDT")) {
    if (price >= 1000)  return price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (price >= 1)     return price.toFixed(4);
    return price.toFixed(6);
  }
  // forex
  const forexSyms = ["EURUSD","GBPUSD","AUDUSD","USDCAD"];
  if (forexSyms.includes(symbol))   return price.toFixed(5);
  if (symbol === "USDJPY")           return price.toFixed(3);
  // commodities
  if (["XAUUSD","XAGUSD","USOIL","UKOIL"].includes(symbol))
    return price < 100 ? price.toFixed(3) : price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  // stocks
  return price.toFixed(2);
}

// ── Market label for a symbol ────────────────────────────────────────────────
function getMarket(sym) {
  for (const [m, syms] of Object.entries(MARKET_GROUPS)) {
    if (syms.includes(sym)) return m;
  }
  return "Unknown";
}

// ── Stat card ────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color }) {
  return (
    <div className="panel p-4">
      <div className="text-xs text-[var(--text-mute)] mb-1">{label}</div>
      <div className={`mono text-xl font-bold ${color || ""}`}>{value ?? "—"}</div>
      {sub && <div className="text-xs text-[var(--text-dim)] mt-1">{sub}</div>}
    </div>
  );
}

// ── Trade row ────────────────────────────────────────────────────────────────
function TradeRow({ t, symbol }) {
  const win = t.pnl > 0;
  return (
    <tr>
      <td><span className={`pill ${t.side === "BUY" ? "pill-buy" : "pill-sell"}`}>{t.side}</span></td>
      <td className="mono text-xs">{t.entry_time}</td>
      <td className="mono text-xs">{t.exit_time}</td>
      <td className="mono">{formatPrice(t.entry, symbol)}</td>
      <td className="mono">{formatPrice(t.exit,  symbol)}</td>
      <td className={`mono font-semibold ${win ? "num-pos" : "num-neg"}`}>
        {win ? "+" : ""}{typeof t.pnl === "number" ? t.pnl.toFixed(2) : t.pnl}
      </td>
      <td className="text-xs text-[var(--text-mute)]">{t.reason}</td>
    </tr>
  );
}

// ── Equity curve chart ────────────────────────────────────────────────────────
function EquityCurve({ trades, startingBalance }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current || !trades?.length) return;
    const chart = createChart(ref.current, {
      layout:     { background: { color: "transparent" }, textColor: "#8a96a3" },
      grid:       { vertLines: { color: "#1a212a" }, horzLines: { color: "#1a212a" } },
      timeScale:  { borderColor: "#1f2730", timeVisible: true },
      rightPriceScale: { borderColor: "#1f2730" },
      width:  ref.current.clientWidth,
      height: 200,
    });

    const series = chart.addSeries(LineSeries, {
      color:     "#00ffa3",
      lineWidth: 2,
    });

    let bal  = startingBalance;
    const pts = [{ time: Math.floor(Date.now() / 1000) - trades.length * 300, value: bal }];
    trades.forEach((t, i) => {
      bal += t.pnl;
      pts.push({ time: Math.floor(Date.now() / 1000) - (trades.length - i - 1) * 300, value: round2(bal) });
    });
    series.setData(pts);
    chart.timeScale().fitContent();

    const onResize = () => chart.applyOptions({ width: ref.current.clientWidth });
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [trades, startingBalance]);

  return <div ref={ref} className="rounded-lg overflow-hidden mt-3" />;
}

function round2(n) { return Math.round(n * 100) / 100; }

// ── Main component ────────────────────────────────────────────────────────────
export default function Backtester() {
  const [symbol,     setSymbol]     = useState("BTCUSDT");
  const [interval,   setInterval_]  = useState("5m");
  const [strategy,   setStrategy]   = useState("unified_bot");
  const [periodDays, setPeriodDays] = useState(7);
  const [randWindow, setRandWindow] = useState(true);
  const [startBal,   setStartBal]   = useState(1000);

  const [loading,    setLoading]    = useState(false);
  const [result,     setResult]     = useState(null);
  const [error,      setError]      = useState(null);
  const [debugInfo,  setDebugInfo]  = useState(null);

  const market = getMarket(symbol);

  const run = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setDebugInfo(null);

    const payload = {
      symbol,
      interval,
      strategy,
      period_days:      periodDays,
      random_window:    randWindow,
      starting_balance: startBal,
      fee_percent:      0.04,
      slippage_percent: 0.02,
    };

    try {
      const { data } = await api.post("/backtest", payload);

      if (!data.ok) {
        setError(data.error || "Backend returned ok=false with no message.");
        return;
      }

      setResult(data);
      setDebugInfo({
        candles:  data.candles_used,
        interval: data.interval,
        start:    data.start_date,
        end:      data.end_date,
        market:   data.market,
        strategy: data.strategy,
      });
    } catch (err) {
      const msg =
        err?.response?.data?.error ||
        err?.message ||
        "Unknown error — check the browser console and backend logs.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setResult(null);
    setError(null);
    setDebugInfo(null);
  };

  const summary = result?.summary;
  const trades  = result?.trades || [];

  return (
    <div className="space-y-6 fade-up max-w-7xl" data-testid="backtester-page">

      {/* ── Header ── */}
      <div>
        <div className="section-title">Strategy Lab</div>
        <h1 className="text-3xl font-bold mt-1">Backtester</h1>
        <p className="text-[var(--text-dim)] text-sm mt-1">
          Run strategy simulations on real historical candle data across all supported markets.
          Use <strong>Random window</strong> to test a surprise date range.
        </p>
      </div>

      {/* ── Controls ── */}
      <div className="panel p-6">
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">

          {/* Symbol — grouped select */}
          <div>
            <label className="text-xs text-[var(--text-mute)] mb-1 block">Symbol</label>
            <select
              className="input"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              data-testid="bt-symbol"
            >
              {Object.entries(MARKET_GROUPS).map(([mkt, syms]) => (
                <optgroup key={mkt} label={mkt}>
                  {syms.map((s) => <option key={s} value={s}>{s}</option>)}
                </optgroup>
              ))}
            </select>
            <div className="text-xs text-[var(--text-mute)] mt-1">{market}</div>
          </div>

          {/* Interval */}
          <div>
            <label className="text-xs text-[var(--text-mute)] mb-1 block">Interval</label>
            <select
              className="input"
              value={interval}
              onChange={(e) => setInterval_(e.target.value)}
              data-testid="bt-interval"
            >
              {INTERVALS.map((i) => <option key={i} value={i}>{i}</option>)}
            </select>
            {market !== "Crypto" && (
              <div className="text-xs text-[var(--accent-2)] mt-1">
                ℹ Non-crypto uses daily candles to avoid rate limits
              </div>
            )}
            {market === "Crypto" && interval === "1m" && (
              <div className="text-xs text-[var(--warn)] mt-1">
                ⚠ 1m auto-upgrades to 5m for non-crypto
              </div>
            )}
          </div>

          {/* Strategy */}
          <div>
            <label className="text-xs text-[var(--text-mute)] mb-1 block">Strategy</label>
            <select
              className="input"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              data-testid="bt-strategy"
            >
              {STRATEGIES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
            <div className="text-xs text-[var(--text-dim)] mt-1">
              {STRATEGIES.find(s => s.value === strategy)?.desc}
            </div>
            {strategy === "orb_0dte" && market !== "Stocks" && (
              <div className="text-xs text-[var(--warn)] mt-1">
                ⚠ ORB is designed for SPY — select SPY from Stocks
              </div>
            )}
            {strategy === "vwap_ema" && (
              <div className="text-xs text-[var(--accent-2)] mt-1">
                ℹ Best with 5m interval and stock symbols (SPY, AAPL, TSLA)
              </div>
            )}
          </div>

          {/* Period */}
          <div>
            <label className="text-xs text-[var(--text-mute)] mb-1 block">
              Period (days)
            </label>
            <input
              className="input mono"
              type="number"
              min={2}
              max={60}
              value={periodDays}
              onChange={(e) => setPeriodDays(Math.max(2, parseInt(e.target.value) || 7))}
              data-testid="bt-period"
            />
            {/* Warn if unified bot won't have enough candles */}
            {strategy === "unified_bot" && (() => {
              const ivMin = {"1m":1,"5m":5,"15m":15,"1h":60,"4h":240}[interval] || 5;
              const est = Math.floor((periodDays * 24 * 60) / ivMin);
              if (est < 150) {
                const minDays = Math.ceil((150 * ivMin) / (24 * 60)) + 1;
                return (
                  <div className="text-xs text-[var(--warn)] mt-1">
                    ⚠ ~{est} candles — need ≥150. Use ≥{minDays}d or a shorter interval.
                  </div>
                );
              }
              return null;
            })()}
          </div>

          {/* Starting balance */}
          <div>
            <label className="text-xs text-[var(--text-mute)] mb-1 block">
              Starting balance ($)
            </label>
            <input
              className="input mono"
              type="number"
              min={100}
              value={startBal}
              onChange={(e) => setStartBal(parseFloat(e.target.value) || 1000)}
              data-testid="bt-balance"
            />
          </div>

          {/* Random window toggle */}
          <div className="flex flex-col justify-end">
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                className="w-4 h-4 accent-[var(--accent)]"
                checked={randWindow}
                onChange={(e) => setRandWindow(e.target.checked)}
                data-testid="bt-random"
              />
              <span className="flex items-center gap-1">
                <Shuffle size={13} className="text-[var(--accent-2)]" />
                Random historical window
              </span>
            </label>
            <div className="text-xs text-[var(--text-mute)] mt-1">
              {randWindow
                ? "Picks a surprise date range from the past"
                : "Uses the most recent data"}
            </div>
          </div>

          {/* Run button */}
          <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-1">
            <button
              className="btn btn-primary flex-1"
              onClick={run}
              disabled={loading}
              data-testid="bt-run"
            >
              {loading
                ? <><Clock size={14} className="animate-spin" /> Running…</>
                : <><Play  size={14} /> Run backtest</>}
            </button>
            {result && (
              <button className="btn btn-ghost" onClick={reset} data-testid="bt-reset">
                <RotateCcw size={14} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Error panel ── */}
      {error && (
        <div className="panel border-[var(--sell)] p-5 flex gap-3" data-testid="bt-error">
          <AlertCircle size={18} className="text-[var(--sell)] shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold mb-1 text-[var(--sell)]">Backtest failed</div>
            <pre className="text-xs text-[var(--text-dim)] whitespace-pre-wrap font-mono">
              {error}
            </pre>
          </div>
        </div>
      )}

      {/* ── Debug / meta info ── */}
      {debugInfo && (
        <div className="panel-flat p-4 flex flex-wrap gap-4 text-xs text-[var(--text-mute)]"
             data-testid="bt-debug">
          <span><Calendar size={11} className="inline mr-1" />
            <strong>{debugInfo.start}</strong> → <strong>{debugInfo.end}</strong>
          </span>
          <span>Market: <strong>{debugInfo.market}</strong></span>
          <span>Interval: <strong>{debugInfo.interval}</strong></span>
          <span>Candles: <strong>{debugInfo.candles}</strong></span>
          <span>Strategy: <strong>{debugInfo.strategy}</strong></span>
        </div>
      )}

      {/* ── Results ── */}
      {result && summary && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4"
               data-testid="bt-summary">
            <StatCard
              label="Net PnL"
              value={`${summary.net_pnl >= 0 ? "+" : ""}$${summary.net_pnl.toFixed(2)}`}
              sub={`${summary.net_pnl >= 0 ? "+" : ""}${
                ((summary.net_pnl / summary.starting_balance) * 100).toFixed(1)
              }%`}
              color={summary.net_pnl >= 0 ? "num-pos" : "num-neg"}
            />
            <StatCard
              label="Final balance"
              value={`$${summary.final_balance.toFixed(2)}`}
              sub={`Started $${summary.starting_balance}`}
            />
            <StatCard
              label="Win rate"
              value={`${summary.win_rate.toFixed(1)}%`}
              sub={`${summary.wins}W · ${summary.losses}L`}
              color={summary.win_rate >= 50 ? "num-pos" : "num-neg"}
            />
            <StatCard
              label="Total trades"
              value={summary.total_trades}
              sub={`${summary.trades_per_day ?? "—"}/day`}
            />
            <StatCard
              label="Profit factor"
              value={summary.profit_factor?.toFixed(2) ?? "—"}
              color={summary.profit_factor >= 1 ? "num-pos" : "num-neg"}
            />
            <StatCard label="Period"  value={`${periodDays}d`}  sub={`${summary.start_date} → ${summary.end_date}`} />
            <StatCard label="Candles" value={summary.candles_used} sub={summary.actual_interval} />
          </div>

          {/* Zero-trade warning */}
          {summary.total_trades === 0 && (
            <div className="panel border-[var(--warn)] p-5 flex gap-3" data-testid="bt-zero-trades">
              <AlertCircle size={18} className="text-[var(--warn)] shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold mb-1 text-[var(--warn)]">No trades generated</div>
                <p className="text-xs text-[var(--text-dim)]">
                  The strategy found no entry signals in this window ({summary.candles_used} candles, {summary.actual_interval}).
                  Try a longer period, a different interval, or switch to <strong>Simple MA Crossover</strong>.
                </p>
              </div>
            </div>
          )}

          {/* Equity curve */}
          {trades.length > 0 && (
            <div className="panel p-5" data-testid="bt-equity">
              <div className="section-title mb-1">Equity curve</div>
              <EquityCurve trades={trades} startingBalance={summary.starting_balance} />
            </div>
          )}

          {/* Trade log */}
          {trades.length > 0 && (
            <div className="panel p-5" data-testid="bt-trades">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <div className="section-title">Trade log</div>
                  <div className="text-lg font-bold mt-1">
                    {trades.length} trades · {symbol} · {result.interval}
                  </div>
                </div>
                <div className="flex items-center gap-3 text-xs">
                  <span className="num-pos flex items-center gap-1">
                    <CheckCircle size={12} /> {summary.wins} wins
                  </span>
                  <span className="num-neg flex items-center gap-1">
                    <TrendingDown size={12} /> {summary.losses} losses
                  </span>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="tbl" data-testid="bt-trade-table">
                  <thead>
                    <tr>
                      <th>Side</th>
                      <th>Entry time</th>
                      <th>Exit time</th>
                      <th>Entry price</th>
                      <th>Exit price</th>
                      <th>PnL ($)</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <TradeRow key={i} t={t} symbol={symbol} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Empty state ── */}
      {!result && !error && !loading && (
        <div className="panel p-12 text-center" data-testid="bt-empty">
          <BarChart2 size={48} className="text-[var(--text-mute)] mx-auto mb-4" />
          <div className="text-lg font-semibold mb-2">Ready to backtest</div>
          <p className="text-sm text-[var(--text-dim)] max-w-md mx-auto">
            Choose a symbol, interval, and strategy above, then click <strong>Run backtest</strong>.
            Works for Crypto (Binance data), Forex, Stocks, and Commodities (TwelveData).
          </p>
          <div className="mt-6 grid sm:grid-cols-2 gap-3 max-w-lg mx-auto text-left text-xs text-[var(--text-dim)]">
            {[
              ["Unified Bot (SMC)",        "Asian range + London sweep + NY reversal. 1 loss = stop. 3 wins = stop."],
              ["0DTE ORB",                 "SPY options. Mon/Wed/Fri. 5-min opening range breakout. +100% TP / -50% SL."],
              ["VWAP + EMA Trend",         "9/21 EMA cross after 10:30 ET + VWAP filter. 2-part scale-out with trail."],
              ["Simple MA",               "10/30 SMA crossover baseline. Works on all markets."],
            ].map(([strat, desc]) => (
              <div key={strat} className="panel-flat p-3 rounded-lg">
                <div className="font-semibold text-[var(--text)] mb-1">{strat}</div>
                {desc}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

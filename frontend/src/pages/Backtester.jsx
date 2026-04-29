import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Play, FlaskConical, History } from "lucide-react";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"];
const INTERVALS = ["1m", "5m", "15m", "1h", "4h"];
const STRATS = [
  { v: "bot", n: "Smart Money (default)" },
  { v: "smart_money", n: "Smart Money" },
  { v: "ema_rsi", n: "EMA Crossover" },
  { v: "basic", n: "Basic Momentum" },
];

export default function Backtester() {
  const [params, setParams] = useState({ symbol: "BTCUSDT", interval: "5m", strategy: "bot",
    limit: 500, starting_balance: 1000, fee_percent: 0.04, slippage_percent: 0.02 });
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [err, setErr] = useState("");

  const loadHistory = useCallback(async () => {
    try { const { data } = await api.get("/backtest-runs"); setHistory(data || []); }
    catch (err) { console.error("history load failed:", err); }
  }, []);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  const run = async () => {
    setRunning(true); setErr(""); setResult(null);
    try {
      const { data } = await api.post("/backtest", params);
      setResult(data); loadHistory();
    } catch (e) {
      console.error("backtest failed:", e);
      setErr(e?.response?.data?.error || "Backtest failed");
    } finally { setRunning(false); }
  };

  const loadRun = async (id) => {
    try {
      const { data } = await api.get(`/backtest-runs/${id}`);
      setResult({ summary: data.summary, trades: data.trades, signals: [] });
    } catch (err) { console.error("load run failed:", err); }
  };

  const sm = result?.summary;

  return (
    <div className="space-y-6 fade-up" data-testid="backtester-page">
      <div>
        <div className="section-title">Strategy lab</div>
        <h1 className="text-3xl font-bold mt-1">Backtester</h1>
        <p className="text-[var(--text-dim)] text-sm mt-1">Run your strategy across historical candles with fees and slippage.</p>
      </div>

      <div className="grid lg:grid-cols-4 gap-6">
        {/* form */}
        <div className="panel p-5 lg:col-span-1 space-y-3">
          <div className="flex items-center gap-2 mb-2"><FlaskConical size={16} className="text-[var(--accent)]" /><div className="section-title">Configure</div></div>
          {[
            { k: "symbol", l: "Symbol", opts: SYMBOLS },
            { k: "interval", l: "Interval", opts: INTERVALS },
          ].map((f) => (
            <div key={f.k}>
              <label className="text-xs text-[var(--text-mute)] mb-1 block">{f.l}</label>
              <select className="input mono" value={params[f.k]} onChange={(e) => setParams({ ...params, [f.k]: e.target.value })} data-testid={`bt-${f.k}`}>
                {f.opts.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          ))}
          <div>
            <label className="text-xs text-[var(--text-mute)] mb-1 block">Strategy</label>
            <select className="input" value={params.strategy} onChange={(e) => setParams({ ...params, strategy: e.target.value })} data-testid="bt-strategy">
              {STRATS.map((s) => <option key={s.v} value={s.v}>{s.n}</option>)}
            </select>
          </div>
          {[
            { k: "limit", l: "Candles (100-1000)", t: "number" },
            { k: "starting_balance", l: "Starting balance ($)", t: "number" },
            { k: "fee_percent", l: "Fee %", t: "number", step: "0.01" },
            { k: "slippage_percent", l: "Slippage %", t: "number", step: "0.01" },
          ].map((f) => (
            <div key={f.k}>
              <label className="text-xs text-[var(--text-mute)] mb-1 block">{f.l}</label>
              <input className="input mono" type={f.t} step={f.step} value={params[f.k]}
                onChange={(e) => setParams({ ...params, [f.k]: parseFloat(e.target.value) || 0 })} data-testid={`bt-${f.k}`}/>
            </div>
          ))}
          <button className="btn btn-primary w-full" onClick={run} disabled={running} data-testid="bt-run-btn">
            <Play size={14} /> {running ? "Running..." : "Run backtest"}
          </button>
          {err && <div className="text-sm text-[var(--sell)]" data-testid="bt-error">{err}</div>}
        </div>

        {/* result */}
        <div className="lg:col-span-3 space-y-4">
          {!sm && (
            <div className="panel p-10 text-center text-[var(--text-mute)]" data-testid="bt-empty">
              <FlaskConical size={32} className="mx-auto mb-3 opacity-50" />
              <div>Configure a strategy on the left and run a backtest to see results.</div>
            </div>
          )}
          {sm && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="bt-summary">
                {[
                  { l: "Net PnL", v: `${sm.net_pnl >= 0 ? "+" : ""}$${sm.net_pnl}`, k: sm.net_pnl >= 0 ? "num-pos" : "num-neg" },
                  { l: "Win rate", v: `${sm.win_rate}%` },
                  { l: "Profit factor", v: sm.profit_factor },
                  { l: "Max drawdown", v: `${sm.max_drawdown_percent}%`, k: "num-neg" },
                  { l: "Total trades", v: sm.total_trades },
                  { l: "Wins / Losses", v: `${sm.wins} / ${sm.losses}` },
                  { l: "Best / worst", v: `+$${sm.best_trade} / $${sm.worst_trade}` },
                  { l: "Fees + slippage", v: `$${(sm.fees_paid + sm.slippage_paid).toFixed(2)}` },
                ].map((k, i) => (
                  <div key={i} className="panel p-4">
                    <div className="text-xs text-[var(--text-mute)]">{k.l}</div>
                    <div className={`mono text-xl font-bold mt-1 ${k.k || ""}`}>{k.v}</div>
                  </div>
                ))}
              </div>

              <div className="panel p-5">
                <div className="section-title mb-3">Session performance</div>
                <div className="grid grid-cols-3 gap-3">
                  {Object.entries(sm.session_performance || {}).map(([s, v]) => (
                    <div key={s} className="panel-flat p-3">
                      <div className="text-xs text-[var(--text-mute)]">{s}</div>
                      <div className={`mono text-lg font-bold ${v >= 0 ? "num-pos" : "num-neg"}`}>{v >= 0 ? "+" : ""}${v}</div>
                    </div>
                  ))}
                </div>
              </div>

              {result.trades?.length > 0 && (
                <div className="panel p-5 overflow-x-auto" data-testid="bt-trades">
                  <div className="section-title mb-3">Trades ({result.trades.length})</div>
                  <table className="tbl">
                    <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr></thead>
                    <tbody>
                      {result.trades.slice(0, 50).map((t, i) => (
                        <tr key={i}>
                          <td className="mono text-xs text-[var(--text-mute)]">{t.entry_time}</td>
                          <td>{t.symbol}</td>
                          <td><span className={`pill ${t.side === "BUY" ? "pill-buy" : "pill-sell"}`}>{t.side}</span></td>
                          <td className="mono">{t.entry_price}</td>
                          <td className="mono">{t.exit_price}</td>
                          <td className={`mono font-semibold ${t.pnl >= 0 ? "num-pos" : "num-neg"}`}>{t.pnl >= 0 ? "+" : ""}{t.pnl}</td>
                          <td className="text-xs text-[var(--text-dim)]">{t.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="panel p-5" data-testid="bt-history">
        <div className="flex items-center gap-2 mb-3"><History size={16} className="text-[var(--accent-2)]" /><div className="section-title">Recent runs</div></div>
        {history.length === 0 ? (
          <div className="text-sm text-[var(--text-mute)] py-3">No runs yet.</div>
        ) : (
          <table className="tbl">
            <thead><tr><th>Date</th><th>Symbol</th><th>Interval</th><th>Strategy</th><th>Trades</th><th>Net PnL</th><th>Win%</th><th>PF</th><th>DD%</th><th></th></tr></thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td className="mono text-xs text-[var(--text-mute)]">{r.created_at}</td>
                  <td>{r.symbol}</td><td className="mono">{r.interval}</td><td>{r.strategy}</td>
                  <td className="mono">{r.total_trades}</td>
                  <td className={`mono font-semibold ${r.net_pnl >= 0 ? "num-pos" : "num-neg"}`}>{r.net_pnl >= 0 ? "+" : ""}{r.net_pnl}</td>
                  <td className="mono">{r.win_rate}%</td>
                  <td className="mono">{r.profit_factor}</td>
                  <td className="mono num-neg">{r.max_drawdown_percent}%</td>
                  <td><button className="btn btn-ghost" onClick={() => loadRun(r.id)} data-testid={`bt-load-${r.id}`}>View</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

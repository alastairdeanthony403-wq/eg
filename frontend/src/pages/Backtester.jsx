/**
 * Backtester.jsx — v2
 * Full backtest UI: equity curve, drawdown, daily PnL, trade breakdown table,
 * strategy comparison, and Learn from Mistakes panel.
 */
import React, { useState, useCallback } from "react";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine, Legend,
} from "recharts";

/* ══════════════════════════════════════════════════════
   THEME
══════════════════════════════════════════════════════ */
const C = {
  bg0: "#020917", bg1: "#071428", bg2: "#0c1d3a", bg3: "#11264a",
  bdr: "#1a3356",
  buy: "#00e5a0", sell: "#ff4266", hold: "#4a9eff", gold: "#f59e0b",
  t0: "#ddeeff", t1: "#7aadda", t2: "#3d6a8a",
  mono: "'JetBrains Mono','Cascadia Code',monospace",
  ui:   "'Outfit','DM Sans',system-ui,sans-serif",
};

const api = (url, opts = {}) => {
  const tok = localStorage.getItem("token") || "";
  return fetch(url, {
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${tok}`, ...opts.headers },
    ...opts,
  });
};

const fn  = (v, d = 2) => v == null ? "—" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtDur = (e, x) => {
  if (!e || !x) return "—";
  try {
    const ms = new Date(x.replace(" ", "T") + "Z") - new Date(e.replace(" ", "T") + "Z");
    const h  = Math.floor(ms / 3600000);
    const m  = Math.floor((ms % 3600000) / 60000);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  } catch { return "—"; }
};
const sessionOf = timeStr => {
  if (!timeStr) return "—";
  const h = new Date(timeStr.replace(" ","T")+"Z").getUTCHours();
  return h >= 7 && h < 12 ? "London" : h >= 12 && h < 21 ? "New York" : "Asia";
};

/* ══════════════════════════════════════════════════════
   DATA TRANSFORMERS
══════════════════════════════════════════════════════ */
const buildEquity = (trades, start) => {
  let bal = start;
  const pts = [{ n: 0, equity: bal, pnl: 0, label: "Start" }];
  trades.forEach((t, i) => {
    bal += t.pnl || 0;
    pts.push({ n: i + 1, equity: bal, pnl: t.pnl || 0,
               label: `${t.side || ""} ${t.exit_time?.slice(0, 10) || ""}` });
  });
  return pts;
};

const buildDrawdown = equity => {
  let peak = equity[0]?.equity || 0;
  return equity.map(p => {
    if (p.equity > peak) peak = p.equity;
    const dd = peak > 0 ? ((p.equity - peak) / peak) * 100 : 0;
    return { ...p, drawdown: parseFloat(dd.toFixed(2)) };
  });
};

const buildDailyPnL = trades => {
  const m = {};
  trades.forEach(t => {
    const d = (t.entry_time || "").slice(0, 10) || "?";
    m[d] = (m[d] || 0) + (t.pnl || 0);
  });
  return Object.entries(m)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, pnl]) => ({ day, pnl: parseFloat(pnl.toFixed(2)) }));
};

const maxDrawdown = equity => {
  let peak = equity[0]?.equity || 0;
  let maxDD = 0;
  equity.forEach(p => {
    if (p.equity > peak) peak = p.equity;
    const dd = peak > 0 ? (peak - p.equity) / peak * 100 : 0;
    if (dd > maxDD) maxDD = dd;
  });
  return maxDD.toFixed(2);
};

/* ══════════════════════════════════════════════════════
   ATOMS / SUB-COMPONENTS
══════════════════════════════════════════════════════ */
const SCard = ({ label, value, sub, color }) => (
  <div style={{
    background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8,
    padding: "12px 16px", flex: "1 1 110px",
  }}>
    <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, letterSpacing: ".08em" }}>{label}</div>
    <div style={{ fontFamily: C.mono, fontSize: 22, fontWeight: 800, color: color || C.t0, marginTop: 3 }}>
      {value}
    </div>
    {sub && <div style={{ fontFamily: C.mono, fontSize: 9, color: C.t2, marginTop: 2 }}>{sub}</div>}
  </div>
);

const SLabel = ({ children }) => (
  <div style={{ fontFamily: C.mono, fontSize: 10, fontWeight: 700, color: C.t1,
    letterSpacing: ".08em", marginBottom: 10, marginTop: 4 }}>
    {children}
  </div>
);

const CustomTip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: C.bg2, border: `1px solid ${C.bdr}`, borderRadius: 6, padding: "8px 12px" }}>
      {payload.map((p, i) => (
        <div key={i} style={{ fontFamily: C.mono, fontSize: 10, color: p.color }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(2) : p.value}
        </div>
      ))}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   EQUITY CURVE + DRAWDOWN + DAILY PnL
══════════════════════════════════════════════════════ */
const Charts = ({ trades, startBalance }) => {
  const equity = buildEquity(trades, startBalance);
  const withDD = buildDrawdown(equity);
  const daily  = buildDailyPnL(trades);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Equity curve */}
      <div style={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, padding: 16 }}>
        <SLabel>📈 EQUITY CURVE</SLabel>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={equity} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="eq-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor={C.buy} stopOpacity={0.4} />
                <stop offset="100%" stopColor={C.buy} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={C.bdr} strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="n" hide />
            <YAxis tick={{ fontFamily: C.mono, fontSize: 9, fill: C.t2 }} width={60}
              tickFormatter={v => "$" + fn(v, 0)} />
            <ReferenceLine y={startBalance} stroke={C.t2} strokeDasharray="4 2" />
            <Tooltip content={<CustomTip />} />
            <Area type="monotone" dataKey="equity" name="Balance"
              stroke={C.buy} strokeWidth={2} fill="url(#eq-grad)"
              dot={false} isAnimationActive />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        {/* Drawdown */}
        <div style={{ flex: 1, background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, padding: 16 }}>
          <SLabel>📉 DRAWDOWN %</SLabel>
          <ResponsiveContainer width="100%" height={130}>
            <AreaChart data={withDD} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="dd-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor={C.sell} stopOpacity={0.5} />
                  <stop offset="100%" stopColor={C.sell} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={C.bdr} strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="n" hide />
              <YAxis tick={{ fontFamily: C.mono, fontSize: 9, fill: C.t2 }} width={40}
                tickFormatter={v => v + "%"} />
              <Tooltip content={<CustomTip />} />
              <Area type="monotone" dataKey="drawdown" name="Drawdown %"
                stroke={C.sell} strokeWidth={1.5} fill="url(#dd-grad)"
                dot={false} isAnimationActive />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Daily PnL */}
        <div style={{ flex: 1, background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, padding: 16 }}>
          <SLabel>📊 DAILY PnL</SLabel>
          <ResponsiveContainer width="100%" height={130}>
            <BarChart data={daily} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid stroke={C.bdr} strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="day" hide />
              <YAxis tick={{ fontFamily: C.mono, fontSize: 9, fill: C.t2 }} width={50}
                tickFormatter={v => "$" + v} />
              <Tooltip content={<CustomTip />} />
              <Bar dataKey="pnl" name="Daily PnL"
                fill={C.buy}
                // negative bars appear red
                label={false}
                isAnimationActive
              >
                {daily.map((d, i) => (
                  <rect key={i} fill={d.pnl >= 0 ? C.buy : C.sell} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   TRADE TABLE
══════════════════════════════════════════════════════ */
const TradeTable = ({ trades }) => {
  const [sortKey, setSortKey] = useState("entry_time");
  const [sortDir, setSortDir] = useState(-1);
  const [page,    setPage]    = useState(0);
  const PER = 20;

  const sorted = [...trades].sort((a, b) => {
    const av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0;
    return av < bv ? sortDir : av > bv ? -sortDir : 0;
  });
  const paged = sorted.slice(page * PER, (page + 1) * PER);

  const TH = ({ k, label }) => (
    <th onClick={() => { setSortKey(k); setSortDir(k === sortKey ? -sortDir : -1); }}
      style={{
        fontFamily: C.mono, fontSize: 8, fontWeight: 700, color: C.t2,
        padding: "8px 8px", textAlign: "left", letterSpacing: ".06em",
        cursor: "pointer", background: C.bg2, position: "sticky", top: 0,
        borderBottom: `1px solid ${C.bdr}`,
        color: sortKey === k ? C.t0 : C.t2,
      }}>
      {label}{sortKey === k ? (sortDir < 0 ? " ↓" : " ↑") : ""}
    </th>
  );

  const cols = [
    { k: "side",       l: "SIDE" },
    { k: "entry",      l: "ENTRY" },
    { k: "exit",       l: "EXIT" },
    { k: "pnl",        l: "PnL" },
    { k: "entry_time", l: "OPEN" },
    { k: "exit_time",  l: "CLOSE" },
    { k: "reason",     l: "REASON" },
  ];

  return (
    <div style={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, overflow: "hidden" }}>
      <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.bdr}`,
        display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <SLabel>📋 TRADE LOG — {trades.length} trades</SLabel>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
            style={{ ...btnSty, opacity: page === 0 ? .4 : 1 }}>← Prev</button>
          <span style={{ fontFamily: C.mono, fontSize: 9, color: C.t2, padding: "4px 8px" }}>
            {page * PER + 1}–{Math.min((page + 1) * PER, trades.length)} of {trades.length}
          </span>
          <button onClick={() => setPage(p => p + 1)} disabled={(page + 1) * PER >= trades.length}
            style={{ ...btnSty, opacity: (page + 1) * PER >= trades.length ? .4 : 1 }}>Next →</button>
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {cols.map(c => <TH key={c.k} k={c.k} label={c.l} />)}
              <th style={{ ...thSty }}>DURATION</th>
              <th style={{ ...thSty }}>SESSION</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((t, i) => {
              const pos   = (t.pnl || 0) >= 0;
              const sess  = sessionOf(t.entry_time);
              const sessC = sess === "London" ? C.gold : sess === "New York" ? C.buy : "#818cf8";
              return (
                <tr key={i} style={{ borderBottom: `1px solid ${C.bdr}44`,
                  background: i % 2 === 0 ? "transparent" : C.bg2 + "44" }}>
                  <td style={{ ...tdSty, color: t.side === "BUY" ? C.buy : C.sell, fontWeight: 700 }}>
                    {t.side === "BUY" ? "▲" : "▼"} {t.side}
                  </td>
                  <td style={{ ...tdSty }}>{fn(t.entry, 5)}</td>
                  <td style={{ ...tdSty }}>{fn(t.exit, 5)}</td>
                  <td style={{ ...tdSty, color: pos ? C.buy : C.sell, fontWeight: 700 }}>
                    {pos ? "+" : ""}{fn(t.pnl, 2)}
                  </td>
                  <td style={{ ...tdSty, color: C.t2, fontSize: 9 }}>
                    {(t.entry_time || "").slice(0, 16)}
                  </td>
                  <td style={{ ...tdSty, color: C.t2, fontSize: 9 }}>
                    {(t.exit_time || "").slice(0, 16)}
                  </td>
                  <td style={{ ...tdSty }}>
                    <span style={{
                      fontFamily: C.mono, fontSize: 8, padding: "2px 6px", borderRadius: 3,
                      background: t.reason?.includes("profit") ? C.buy + "18"
                                : t.reason?.includes("stop")   ? C.sell + "18"
                                : t.reason?.includes("Trail")  ? C.gold + "18" : C.bg3,
                      color:      t.reason?.includes("profit") ? C.buy
                                : t.reason?.includes("stop")   ? C.sell
                                : t.reason?.includes("Trail")  ? C.gold : C.t2,
                    }}>
                      {t.reason || "—"}
                    </span>
                  </td>
                  <td style={{ ...tdSty, fontFamily: C.mono, fontSize: 9, color: C.t2 }}>
                    {fmtDur(t.entry_time, t.exit_time)}
                  </td>
                  <td style={{ ...tdSty }}>
                    <span style={{ fontFamily: C.mono, fontSize: 8, padding: "1px 5px", borderRadius: 3,
                      background: sessC + "20", color: sessC }}>
                      {sess}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const btnSty = {
  fontFamily: "'JetBrains Mono',monospace", fontSize: 9, padding: "4px 10px",
  borderRadius: 5, cursor: "pointer",
  background: "#11264a", border: "1px solid #1a3356", color: "#7aadda",
};
const thSty = {
  fontFamily: "'JetBrains Mono',monospace", fontSize: 8, fontWeight: 700,
  color: "#3d6a8a", padding: "8px 8px", textAlign: "left",
  background: "#0c1d3a", borderBottom: "1px solid #1a3356", position: "sticky", top: 0,
};
const tdSty = {
  fontFamily: "'JetBrains Mono',monospace", fontSize: 10,
  color: "#ddeeff", padding: "7px 8px",
};

/* ══════════════════════════════════════════════════════
   STRATEGY COMPARISON
══════════════════════════════════════════════════════ */
const StrategyComparison = ({ symbol, period, balance, fee, slip }) => {
  const [results, setResults] = useState([]);
  const [running, setRunning] = useState(false);

  const strategies = [
    { key: "unified_bot", label: "SMC Unified Bot" },
    { key: "simple_ma",   label: "Simple MA Cross" },
    { key: "vwap_ema",    label: "VWAP + EMA" },
    { key: "orb_0dte",    label: "ORB 0DTE" },
  ];

  const run = async () => {
    setRunning(true); setResults([]);
    const out = [];
    for (const s of strategies) {
      try {
        const r = await api("/api/backtest", {
          method: "POST",
          body: JSON.stringify({
            symbol, strategy: s.key,
            period_days: period,
            starting_balance: balance,
            fee_percent: fee,
            slippage_percent: slip,
            random_window: false,
          }),
        });
        const d = await r.json();
        if (d.ok) {
          out.push({
            label:    s.label,
            net_pnl:  d.net_pnl,
            win_rate: d.win_rate,
            pf:       d.profit_factor,
            trades:   d.total_trades,
            dates:    `${d.start_date} → ${d.end_date}`,
          });
        } else {
          out.push({ label: s.label, error: d.error });
        }
      } catch (e) {
        out.push({ label: s.label, error: e.message });
      }
    }
    setResults(out);
    setRunning(false);
  };

  const chartData = results.filter(r => !r.error).map(r => ({
    name: r.label.split(" ").slice(-2).join(" "),
    "Net PnL": r.net_pnl,
    "Win %":   r.win_rate,
  }));

  return (
    <div style={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <SLabel>⚔️ STRATEGY COMPARISON — {symbol} · {period}d</SLabel>
        <button onClick={run} disabled={running} style={{
          ...btnSty,
          background: running ? C.bg3 : C.buy + "22",
          color: running ? C.t2 : C.buy,
          border: `1px solid ${C.buy}44`,
        }}>
          {running ? "Running all 4 strategies…" : "▶ Compare All Strategies"}
        </button>
      </div>

      {results.length > 0 && (
        <>
          <div style={{ overflowX: "auto", marginBottom: 14 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {["Strategy","Net PnL","Win Rate","Profit Factor","Trades","Period"].map(h => (
                    <th key={h} style={{ ...thSty }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${C.bdr}44` }}>
                    <td style={{ ...tdSty, fontWeight: 700 }}>{r.label}</td>
                    {r.error ? (
                      <td colSpan={5} style={{ ...tdSty, color: C.sell, fontSize: 9 }}>{r.error}</td>
                    ) : (
                      <>
                        <td style={{ ...tdSty, color: r.net_pnl >= 0 ? C.buy : C.sell, fontWeight: 700 }}>
                          {r.net_pnl >= 0 ? "+" : ""}{fn(r.net_pnl)}
                        </td>
                        <td style={{ ...tdSty, color: r.win_rate >= 50 ? C.buy : C.t1 }}>
                          {r.win_rate?.toFixed(1)}%
                        </td>
                        <td style={{ ...tdSty, color: r.pf >= 1 ? C.buy : C.sell }}>
                          {r.pf?.toFixed(2)}
                        </td>
                        <td style={{ ...tdSty }}>{r.trades}</td>
                        <td style={{ ...tdSty, color: C.t2, fontSize: 9 }}>{r.dates}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {chartData.length > 0 && (
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={C.bdr} strokeDasharray="3 3" opacity={0.4} />
                <XAxis dataKey="name" tick={{ fontFamily: C.mono, fontSize: 8, fill: C.t2 }} />
                <YAxis tick={{ fontFamily: C.mono, fontSize: 8, fill: C.t2 }} />
                <Tooltip content={<CustomTip />} />
                <Bar dataKey="Net PnL" fill={C.buy} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </>
      )}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   LEARN FROM MISTAKES PANEL
══════════════════════════════════════════════════════ */
const LearnPanel = ({ hasRuns }) => {
  const [result,   setResult]  = useState(null);
  const [history,  setHistory] = useState([]);
  const [loading,  setLoading] = useState(false);
  const [showHist, setShowHist] = useState(false);
  const [error,    setError]   = useState(null);

  const run = async () => {
    setLoading(true); setError(null); setResult(null);
    try {
      const r = await api("/api/learn", {
        method: "POST",
        body: JSON.stringify({ n_runs: 5, auto_apply: true }),
      });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error);
      setResult(d);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadHistory = async () => {
    try {
      const r = await api("/api/learn/history");
      const d = await r.json();
      setHistory(Array.isArray(d) ? d : []);
      setShowHist(true);
    } catch {}
  };

  return (
    <div style={{ background: C.bg1, border: `1px solid #7c3aed55`, borderRadius: 8, padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <SLabel>🧠 LEARN FROM MISTAKES</SLabel>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={run} disabled={loading || !hasRuns} style={{
            ...btnSty,
            background: "#7c3aed22",
            color: loading || !hasRuns ? C.t2 : "#a78bfa",
            border: "1px solid #7c3aed55",
          }}>
            {loading ? "Analyzing…" : "🧠 Analyze & Auto-Apply"}
          </button>
          <button onClick={loadHistory} style={{
            ...btnSty,
            background: "transparent",
          }}>
            📋 History
          </button>
        </div>
      </div>

      {!hasRuns && (
        <div style={{ fontFamily: C.mono, fontSize: 10, color: C.t2, padding: "8px 0" }}>
          Run at least 1 backtest to enable learning analysis.
        </div>
      )}

      {error && (
        <div style={{ fontFamily: C.mono, fontSize: 10, color: C.sell, marginBottom: 10 }}>
          ⚠ {error}
        </div>
      )}

      {result && (
        <div>
          <div style={{ fontFamily: C.mono, fontSize: 9, color: C.t2, marginBottom: 8 }}>
            Analyzed {result.runs_analyzed} runs · {result.trades_analyzed} losing trades ·
            Avg win rate before: {result.win_rate_before}%
          </div>

          <div style={{ marginBottom: 10 }}>
            <div style={{ fontFamily: C.mono, fontSize: 9, color: C.t1, marginBottom: 6, fontWeight: 700 }}>PATTERNS FOUND</div>
            {result.patterns.map((p, i) => (
              <div key={i} style={{ fontFamily: C.mono, fontSize: 9, color: C.t0,
                padding: "4px 8px", borderLeft: `2px solid #a78bfa`,
                background: C.bg2, marginBottom: 3, borderRadius: "0 4px 4px 0" }}>
                {p}
              </div>
            ))}
          </div>

          {Object.keys(result.diff || {}).length > 0 && (
            <div>
              <div style={{ fontFamily: C.mono, fontSize: 9, color: C.t1, marginBottom: 6, fontWeight: 700 }}>
                CONFIG CHANGES {result.applied ? "✅ APPLIED" : "(not applied)"}
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>{["Setting","Before","After","Reason"].map(h => <th key={h} style={{ ...thSty }}>{h}</th>)}</tr>
                </thead>
                <tbody>
                  {Object.entries(result.diff).map(([k, v]) => (
                    <tr key={k} style={{ borderBottom: `1px solid ${C.bdr}44` }}>
                      <td style={{ ...tdSty, color: "#a78bfa", fontSize: 9 }}>{k}</td>
                      <td style={{ ...tdSty, color: C.sell, fontSize: 9 }}>{JSON.stringify(v.before)}</td>
                      <td style={{ ...tdSty, color: C.buy, fontSize: 9 }}>{JSON.stringify(v.after)}</td>
                      <td style={{ ...tdSty, color: C.t2, fontSize: 8 }}>{result.reasons?.[k] || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {showHist && history.length > 0 && (
        <div style={{ marginTop: 12, borderTop: `1px solid ${C.bdr}`, paddingTop: 12 }}>
          <div style={{ fontFamily: C.mono, fontSize: 9, color: C.t1, fontWeight: 700, marginBottom: 8 }}>
            LEARNING HISTORY ({history.length})
          </div>
          {history.slice(0, 5).map(e => (
            <div key={e.id} style={{ marginBottom: 8, padding: "8px 10px",
              background: C.bg2, borderRadius: 6, border: `1px solid ${C.bdr}` }}>
              <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 4 }}>
                {e.created_at} · {e.symbol} · {e.trades_analyzed} losing trades analyzed
              </div>
              {(e.patterns || []).slice(0, 2).map((p, i) => (
                <div key={i} style={{ fontFamily: C.mono, fontSize: 9, color: C.t1 }}>• {p}</div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   MAIN BACKTESTER
══════════════════════════════════════════════════════ */
const SYMBOLS = [
  "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT",
  "EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD",
  "AAPL","TSLA","NVDA","MSFT","AMZN","SPY",
  "XAUUSD","XAGUSD","USOIL","UKOIL",
];

export default function Backtester() {
  const [form, setForm] = useState({
    symbol: "BTCUSDT", strategy: "unified_bot",
    period_days: 30, random_window: false,
    starting_balance: 10000, fee_percent: 0.04, slippage_percent: 0.02,
  });
  const [result,    setResult]    = useState(null);
  const [running,   setRunning]   = useState(false);
  const [error,     setError]     = useState(null);
  const [runsList,  setRunsList]  = useState([]);
  const [activeTab, setActiveTab] = useState("results");

  const upd = k => e => setForm(f => ({ ...f, [k]: e.target.value }));
  const updNum = k => e => setForm(f => ({ ...f, [k]: parseFloat(e.target.value) || 0 }));

  const runBacktest = async () => {
    setRunning(true); setError(null);
    try {
      const r = await api("/api/backtest", { method: "POST", body: JSON.stringify(form) });
      const d = await r.json();
      if (!d.ok && d.error) throw new Error(d.error);
      setResult(d);
      setActiveTab("results");
      loadRuns();
    } catch (e) { setError(e.message); }
    finally { setRunning(false); }
  };

  const loadRuns = useCallback(async () => {
    try {
      const r = await api("/api/backtest-runs");
      const d = await r.json();
      setRunsList(Array.isArray(d) ? d : []);
    } catch {}
  }, []);

  React.useEffect(() => { loadRuns(); }, [loadRuns]);

  const equity = result ? buildEquity(result.trades || [], result.summary?.starting_balance || form.starting_balance) : [];
  const dd     = equity.length ? maxDrawdown(equity) : "0.00";

  const InSelect = ({ k, opts, label }) => (
    <div style={{ flex: 1, minWidth: 100 }}>
      <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 4 }}>{label}</div>
      <select value={form[k]} onChange={upd(k)} style={{
        width: "100%", fontFamily: C.mono, fontSize: 10, padding: "6px 8px",
        borderRadius: 6, background: C.bg3, border: `1px solid ${C.bdr}`,
        color: C.t0, cursor: "pointer",
      }}>
        {opts.map(o => <option key={o.v || o} value={o.v || o}>{o.l || o}</option>)}
      </select>
    </div>
  );

  const InNum = ({ k, label, step, min, max }) => (
    <div style={{ flex: 1, minWidth: 100 }}>
      <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 4 }}>{label}</div>
      <input type="number" value={form[k]} onChange={updNum(k)}
        step={step || 1} min={min} max={max}
        style={{
          width: "100%", fontFamily: C.mono, fontSize: 10, padding: "6px 8px",
          borderRadius: 6, background: C.bg3, border: `1px solid ${C.bdr}`,
          color: C.t0,
        }}
      />
    </div>
  );

  const tabs = ["results","trades","compare","learn","history"];

  return (
    <div style={{ background: C.bg0, minHeight: "100vh", fontFamily: C.ui }}>
      {/* Header */}
      <div style={{ background: C.bg1, borderBottom: `1px solid ${C.bdr}`,
        padding: "10px 20px", fontFamily: C.mono, fontSize: 14, fontWeight: 800, color: C.t0 }}>
        <span style={{ color: C.gold }}>▸</span> BACKTESTER
      </div>

      <div style={{ padding: 20, maxWidth: 1400 }}>
        {/* Config form */}
        <div style={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <SLabel>⚙ BACKTEST CONFIGURATION</SLabel>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
            <InSelect k="symbol" label="SYMBOL" opts={SYMBOLS} />
            <InSelect k="strategy" label="STRATEGY" opts={[
              { v: "unified_bot", l: "SMC Unified Bot" },
              { v: "simple_ma",   l: "Simple MA Cross" },
              { v: "vwap_ema",    l: "VWAP + EMA" },
              { v: "orb_0dte",    l: "ORB 0DTE" },
            ]} />
            <InSelect k="period_days" label="PERIOD" opts={[
              { v: 7, l: "7 Days" }, { v: 14, l: "14 Days" },
              { v: 30, l: "30 Days" }, { v: 60, l: "60 Days" }, { v: 90, l: "90 Days" },
            ]} />
            <InNum k="starting_balance" label="BALANCE ($)" step={100} min={100} />
            <InNum k="fee_percent"     label="FEE (%)"     step={0.01} min={0} max={2} />
            <InNum k="slippage_percent" label="SLIPPAGE (%)" step={0.01} min={0} max={2} />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <label style={{ fontFamily: C.mono, fontSize: 9, color: C.t1, display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <input type="checkbox" checked={form.random_window}
                onChange={e => setForm(f => ({ ...f, random_window: e.target.checked }))}
                style={{ accentColor: C.buy }} />
              Random historical window
            </label>
            <button onClick={runBacktest} disabled={running} style={{
              fontFamily: C.mono, fontSize: 11, fontWeight: 700,
              padding: "8px 24px", borderRadius: 7, cursor: running ? "wait" : "pointer",
              background: running ? C.bg3 : C.buy + "22",
              border: `1px solid ${running ? C.bdr : C.buy + "55"}`,
              color: running ? C.t2 : C.buy,
              transition: "all .15s",
            }}>
              {running ? "⟳ Running…" : "▶ Run Backtest"}
            </button>
          </div>
        </div>

        {error && (
          <div style={{ padding: "10px 14px", borderRadius: 7, marginBottom: 14,
            background: C.sell + "12", border: `1px solid ${C.sell}40`,
            fontFamily: C.mono, fontSize: 10, color: C.sell }}>⚠ {error}</div>
        )}

        {/* Tabs */}
        <div style={{ display: "flex", gap: 2, marginBottom: 14 }}>
          {tabs.map(t => (
            <button key={t} onClick={() => setActiveTab(t)} style={{
              fontFamily: C.mono, fontSize: 9, fontWeight: 600,
              padding: "6px 14px", borderRadius: "6px 6px 0 0", cursor: "pointer",
              background: activeTab === t ? C.bg1 : "transparent",
              border: `1px solid ${activeTab === t ? C.bdr : "transparent"}`,
              borderBottom: activeTab === t ? `1px solid ${C.bg1}` : `1px solid ${C.bdr}`,
              color: activeTab === t ? C.t0 : C.t2,
            }}>
              {t.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Results tab */}
        {activeTab === "results" && result && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Info bar */}
            <div style={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, padding: "10px 14px",
              fontFamily: C.mono, fontSize: 9, color: C.t2, display: "flex", gap: 20, flexWrap: "wrap" }}>
              <span>📅 {result.start_date} → {result.end_date}</span>
              <span>📊 {result.candles_used} candles</span>
              <span>📡 {result.market?.toUpperCase()} data</span>
              <span>⏱ {result.interval}</span>
              <span>🔀 {form.random_window ? "Random window" : "Most recent period"}</span>
            </div>

            {/* Summary cards */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <SCard label="NET PnL"   value={`${result.net_pnl >= 0 ? "+" : ""}$${fn(result.net_pnl)}`}
                color={result.net_pnl >= 0 ? C.buy : C.sell}
                sub={`${result.net_pnl >= 0 ? "+" : ""}${fn(result.net_pnl / form.starting_balance * 100)}%`} />
              <SCard label="WIN RATE"  value={`${result.win_rate?.toFixed(1)}%`}
                color={result.win_rate >= 50 ? C.buy : C.sell}
                sub={`${result.summary?.wins || 0}W / ${result.summary?.losses || 0}L`} />
              <SCard label="PROF FACTOR" value={fn(result.profit_factor, 2)}
                color={result.profit_factor >= 1 ? C.buy : C.sell} />
              <SCard label="MAX DRAWDOWN" value={`-${dd}%`} color={C.sell} />
              <SCard label="TOTAL TRADES" value={result.total_trades}
                sub={`${fn(result.trades_per_day, 1)} / day`} />
              <SCard label="FINAL BAL" value={`$${fn(result.summary?.final_balance)}`}
                color={result.summary?.final_balance > form.starting_balance ? C.buy : C.sell} />
            </div>

            <Charts trades={result.trades || []} startBalance={result.summary?.starting_balance || form.starting_balance} />
          </div>
        )}

        {activeTab === "results" && !result && (
          <div style={{ textAlign: "center", padding: 60, fontFamily: C.mono, color: C.t2 }}>
            Run a backtest to see results.
          </div>
        )}

        {activeTab === "trades" && result && (
          <TradeTable trades={result.trades || []} />
        )}

        {activeTab === "compare" && (
          <StrategyComparison
            symbol={form.symbol} period={form.period_days}
            balance={form.starting_balance} fee={form.fee_percent} slip={form.slippage_percent}
          />
        )}

        {activeTab === "learn" && (
          <LearnPanel hasRuns={runsList.length > 0} />
        )}

        {activeTab === "history" && (
          <div style={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, overflow: "hidden" }}>
            <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.bdr}` }}>
              <SLabel>🕒 PAST BACKTEST RUNS</SLabel>
            </div>
            {runsList.length === 0 ? (
              <div style={{ padding: 30, textAlign: "center", fontFamily: C.mono, fontSize: 10, color: C.t2 }}>
                No runs yet.
              </div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>{["Symbol","Strategy","Interval","Trades","Net PnL","Win Rate","P/F","Date"].map(h => (
                    <th key={h} style={{ ...thSty }}>{h}</th>
                  ))}</tr>
                </thead>
                <tbody>
                  {runsList.map(r => (
                    <tr key={r.id} style={{ borderBottom: `1px solid ${C.bdr}44` }}>
                      <td style={{ ...tdSty, fontWeight: 700 }}>{r.symbol}</td>
                      <td style={{ ...tdSty, fontSize: 9, color: C.t1 }}>{r.strategy}</td>
                      <td style={{ ...tdSty, fontSize: 9 }}>{r.interval}</td>
                      <td style={{ ...tdSty }}>{r.total_trades}</td>
                      <td style={{ ...tdSty, color: r.net_pnl >= 0 ? C.buy : C.sell, fontWeight: 700 }}>
                        {r.net_pnl >= 0 ? "+" : ""}${fn(r.net_pnl)}
                      </td>
                      <td style={{ ...tdSty, color: r.win_rate >= 50 ? C.buy : C.t1 }}>
                        {r.win_rate?.toFixed(1)}%
                      </td>
                      <td style={{ ...tdSty, color: r.profit_factor >= 1 ? C.buy : C.sell }}>
                        {fn(r.profit_factor, 2)}
                      </td>
                      <td style={{ ...tdSty, fontSize: 8, color: C.t2 }}>{(r.created_at || "").slice(0, 16)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

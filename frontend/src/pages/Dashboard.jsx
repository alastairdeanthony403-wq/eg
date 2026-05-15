/**
 * Dashboard.jsx — v2 Institutional Trading Terminal
 * Live signal cards with AI reasoning, ADX/RSI/EMA/SMC visibility,
 * expandable analysis panels, and a premium dark terminal aesthetic.
 */
import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";

/* ══════════════════════════════════════════════════════
   THEME
══════════════════════════════════════════════════════ */
const C = {
  bg0:  "#020917",   // page
  bg1:  "#071428",   // card
  bg2:  "#0c1d3a",   // elevated
  bg3:  "#11264a",   // hover / pill
  bdr:  "#1a3356",
  buy:  "#00e5a0",
  sell: "#ff4266",
  hold: "#4a9eff",
  gold: "#f59e0b",
  t0:   "#ddeeff",
  t1:   "#7aadda",
  t2:   "#3d6a8a",
  mono: "'JetBrains Mono','Cascadia Code','Fira Code',monospace",
  ui:   "'Outfit','DM Sans',system-ui,sans-serif",
};

/* Inject fonts + global keyframes once */
let _injected = false;
const injectGlobals = () => {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const lnk = document.createElement("link");
  lnk.rel = "stylesheet";
  lnk.href =
    "https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&" +
    "family=JetBrains+Mono:wght@400;500;700&display=swap";
  document.head.appendChild(lnk);
  const sty = document.createElement("style");
  sty.textContent = `
    @keyframes pulse-buy  { 0%,100%{box-shadow:0 0 14px rgba(0,229,160,.2),0 0 0 1px rgba(0,229,160,.3)}  50%{box-shadow:0 0 30px rgba(0,229,160,.38),0 0 0 1px rgba(0,229,160,.5)} }
    @keyframes pulse-sell { 0%,100%{box-shadow:0 0 14px rgba(255,66,102,.2),0 0 0 1px rgba(255,66,102,.3)} 50%{box-shadow:0 0 30px rgba(255,66,102,.38),0 0 0 1px rgba(255,66,102,.5)} }
    @keyframes fadeDown   { from{opacity:0;transform:translateY(-8px)} to{opacity:1;transform:translateY(0)} }
    @keyframes spin       { to{transform:rotate(360deg)} }
    @keyframes priceUp    { 0%{background:rgba(0,229,160,.18)} 100%{background:transparent} }
    @keyframes priceDown  { 0%{background:rgba(255,66,102,.18)} 100%{background:transparent} }
    @keyframes blink      { 0%,100%{opacity:1} 50%{opacity:.3} }
    .buy-glow  { animation: pulse-buy  3s ease-in-out infinite; }
    .sell-glow { animation: pulse-sell 3s ease-in-out infinite; }
    .slide-in  { animation: fadeDown 0.28s ease; }
    .price-up  { animation: priceUp   0.9s ease; }
    .price-down{ animation: priceDown 0.9s ease; }
    .live-dot  { animation: blink 1.4s ease-in-out infinite; }
    *  { box-sizing:border-box; }
    ::-webkit-scrollbar       { width:5px; height:5px; }
    ::-webkit-scrollbar-track { background:#071428; }
    ::-webkit-scrollbar-thumb { background:#1a3356; border-radius:3px; }
  `;
  document.head.appendChild(sty);
};

/* ══════════════════════════════════════════════════════
   HELPERS
══════════════════════════════════════════════════════ */
const api = (url, opts = {}) => {
  const tok = localStorage.getItem("token") || "";
  return fetch(url, {
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${tok}`, ...opts.headers },
    ...opts,
  });
};

const qualityInfo = (conf, smc) => {
  if (conf >= 88 && smc >= 8) return { label: "A+", bg: "#064533", col: "#00e5a0" };
  if (conf >= 80 && smc >= 7) return { label: "A",  bg: "#065240", col: "#10d98a" };
  if (conf >= 70 && smc >= 6) return { label: "B",  bg: "#1e3a8a", col: "#60a5fa" };
  if (conf >= 60)              return { label: "C",  bg: "#7c3403", col: "#fbbf24" };
  return                              { label: "D",  bg: "#1c1917", col: "#6b7280" };
};

const sessionCol = s =>
  s === "London" ? "#f59e0b" : s === "New York" ? "#34d399" : "#818cf8";

const mktEmoji = m =>
  ({ crypto: "₿", forex: "FX", stocks: "EQ", commodities: "AU" }[m] || "—");

const fn = (v, d = 2) => {
  if (v == null || isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
};

const fmtChg = v => {
  const n = parseFloat(v);
  return isNaN(n) ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
};

/* ══════════════════════════════════════════════════════
   ATOMS
══════════════════════════════════════════════════════ */
const Tag = ({ label, active, small }) => (
  <span style={{
    fontFamily: C.mono,
    fontSize: small ? 8 : 9,
    fontWeight: 600,
    padding: small ? "1px 5px" : "2px 7px",
    borderRadius: 4,
    background: active ? C.buy + "16" : C.bg3,
    color:       active ? C.buy      : C.t2,
    border:      `1px solid ${active ? C.buy + "40" : C.bdr}`,
  }}>
    {active ? "✓" : "✗"} {label}
  </span>
);

const Pill = ({ label, value, color }) => (
  <div style={{
    flex: 1, textAlign: "center",
    padding: "5px 2px",
    background: C.bg3, borderRadius: 6, border: `1px solid ${C.bdr}`,
    minWidth: 0,
  }}>
    <div style={{ fontFamily: C.mono, fontSize: 12, fontWeight: 700, color: color || C.t0 }}>
      {value ?? "—"}
    </div>
    <div style={{ fontFamily: C.ui, fontSize: 8, color: C.t2, marginTop: 1 }}>{label}</div>
  </div>
);

const ConfBar = ({ value }) => {
  const pct = Math.max(0, Math.min(100, value || 0));
  const col = pct >= 80 ? C.buy : pct >= 65 ? C.gold : pct >= 50 ? C.hold : C.sell;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
        <span style={{ fontFamily: C.mono, fontSize: 9, color: C.t2 }}>CONFIDENCE</span>
        <span style={{ fontFamily: C.mono, fontSize: 11, fontWeight: 700, color: col }}>{pct}%</span>
      </div>
      <div style={{ height: 4, background: C.bg3, borderRadius: 99, overflow: "hidden" }}>
        <div style={{
          height: "100%", width: `${pct}%`, borderRadius: 99,
          background: `linear-gradient(90deg,${col}66,${col})`,
          transition: "width .7s ease",
          boxShadow: `0 0 6px ${col}88`,
        }} />
      </div>
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   MINI PRICE CHART (lazy-loaded on card expand)
══════════════════════════════════════════════════════ */
const MiniChart = ({ symbol, entry, sl, tp, signal }) => {
  const [data, setData] = useState([]);
  useEffect(() => {
    api(`/api/chart-candles?symbol=${symbol}&interval=5m&limit=80`)
      .then(r => r.json())
      .then(d => {
        if (d.ok && d.data) setData(d.data.map((c, i) => ({ i, v: c.close })));
      })
      .catch(() => {});
  }, [symbol]);

  if (!data.length) return (
    <div style={{ height: 90, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <span style={{ fontFamily: C.mono, fontSize: 10, color: C.t2 }}>Loading chart…</span>
    </div>
  );

  const col = signal === "BUY" ? C.buy : signal === "SELL" ? C.sell : C.hold;
  const gradId = `grad-${symbol}`;

  return (
    <div style={{ height: 90, marginTop: 6 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={col} stopOpacity={0.3} />
              <stop offset="100%" stopColor={col} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="v" stroke={col} strokeWidth={1.5}
            fill={`url(#${gradId})`} dot={false} isAnimationActive={false} />
          {entry && <ReferenceLine y={entry} stroke={col}     strokeDasharray="4 2" strokeWidth={1} label={{ value: "E", fill: col,  fontSize: 8, fontFamily: C.mono }} />}
          {sl    && <ReferenceLine y={sl}    stroke={C.sell}  strokeDasharray="4 2" strokeWidth={1} label={{ value: "SL", fill: C.sell, fontSize: 8, fontFamily: C.mono }} />}
          {tp    && <ReferenceLine y={tp}    stroke={C.gold}  strokeDasharray="4 2" strokeWidth={1} label={{ value: "TP", fill: C.gold, fontSize: 8, fontFamily: C.mono }} />}
          <YAxis hide domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 6, fontFamily: C.mono, fontSize: 9 }}
            formatter={v => [fn(v, 5), "Price"]}
            labelFormatter={() => ""}
          />
        </AreaChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 4 }}>
        {[["E", col], ["SL", C.sell], ["TP", C.gold]].map(([l, c]) => (
          <span key={l} style={{ fontFamily: C.mono, fontSize: 8, color: c }}>— {l}</span>
        ))}
      </div>
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   AI ANALYSIS PANEL
══════════════════════════════════════════════════════ */
const AIPanel = ({ s }) => {
  const passing = (s.reasons || []).filter(r => r.startsWith("✓")).length;
  const total   = (s.reasons || []).length;
  const setupType = s.smc_score >= s.min_smc_score
    ? "Full ICT / SMC Setup"
    : s.signal !== "HOLD"
    ? "Fallback EMA + ADX Trend-Follow"
    : "No valid setup — signal blocked";

  return (
    <div className="slide-in" style={{
      marginTop: 10, padding: 14, borderRadius: 8,
      background: C.bg0, border: `1px solid ${C.bdr}`,
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontFamily: C.mono, fontSize: 10, fontWeight: 700, color: C.t1, letterSpacing: ".06em" }}>
          🤖 AI ANALYSIS
        </span>
        <span style={{ fontFamily: C.mono, fontSize: 9, color: C.t2 }}>{passing}/{total} confirmations</span>
      </div>

      {/* Setup type */}
      <div style={{
        padding: "7px 10px", borderRadius: 6, marginBottom: 10,
        background: C.bg2, borderLeft: `3px solid ${C.hold}`,
      }}>
        <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 2 }}>SETUP TYPE</div>
        <div style={{ fontFamily: C.ui, fontSize: 11, fontWeight: 600, color: C.t0 }}>{setupType}</div>
      </div>

      {/* Trade idea */}
      {s.trade_idea && s.trade_idea !== "Wait for clearer confirmation" && (
        <div style={{
          padding: "7px 10px", borderRadius: 6, marginBottom: 10,
          background: C.bg2, borderLeft: `3px solid ${s.signal === "BUY" ? C.buy : C.sell}`,
        }}>
          <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 2 }}>TRADE IDEA</div>
          <div style={{ fontFamily: C.ui, fontSize: 11, color: C.t0 }}>{s.trade_idea}</div>
        </div>
      )}

      {/* Context grid */}
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 10 }}>
        {[
          { l: "Regime",    v: s.regime },
          { l: "Structure", v: s.structure },
          { l: "HTF",       v: s.higher_tf_bias },
          { l: "Session",   v: s.session },
          { l: "ADX",       v: s.adx ? s.adx.toFixed(1) : "—" },
          { l: "RSI",       v: s.rsi ? s.rsi.toFixed(0) : "—" },
          { l: "EMA",       v: s.ema_alignment },
          { l: "SMC",       v: `${s.smc_score}/9` },
        ].map(({ l, v }) => (
          <span key={l} style={{
            fontFamily: C.mono, fontSize: 9, padding: "2px 7px", borderRadius: 4,
            background: C.bg3, border: `1px solid ${C.bdr}`, color: C.t1,
          }}>
            <span style={{ color: C.t2 }}>{l}: </span>{v || "—"}
          </span>
        ))}
      </div>

      {/* Reason checklist */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {(s.reasons || []).map((r, i) => {
          const pass = r.startsWith("✓");
          return (
            <div key={i} style={{
              fontFamily: C.mono, fontSize: 10,
              color: pass ? C.buy : C.t2,
              padding: "3px 6px",
              borderRadius: 4,
              background: pass ? C.buy + "08" : "transparent",
              borderBottom: i < s.reasons.length - 1 ? `1px solid ${C.bdr}44` : "none",
            }}>
              {r}
            </div>
          );
        })}
      </div>

      {/* Why confidence is high/low */}
      <div style={{ marginTop: 10, padding: "8px 10px", background: C.bg2, borderRadius: 6 }}>
        <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 4 }}>WHY CONFIDENCE IS {s.confidence >= 70 ? "HIGH" : s.confidence >= 50 ? "MODERATE" : "LOW"}</div>
        <div style={{ fontFamily: C.ui, fontSize: 10, color: C.t1, lineHeight: 1.6 }}>
          {s.confidence >= 80
            ? `Strong ${s.signal === "BUY" ? "bullish" : "bearish"} alignment across all timeframes. 
               ADX ${s.adx?.toFixed(0) || "?"} confirms trending conditions. 
               ${s.smc_score}/${s.min_smc_score} SMC threshold met — high conviction entry.`
            : s.confidence >= 65
            ? `Moderate confluence. ${passing}/${total} checks passed. 
               ${s.adx < 25 ? "ADX is low — trend may be weak. " : ""}
               ${s.rsi && s.rsi > 65 ? "RSI approaching overbought — watch for exhaustion. " : ""}
               Confidence acceptable but not optimal.`
            : `Low confluence. Only ${passing}/${total} SMC checks aligned. 
               ${s.adx < 20 ? "ADX below 20 — no strong trend. " : ""}
               Consider waiting for a higher quality setup.`}
        </div>
      </div>
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   SIGNAL CARD
══════════════════════════════════════════════════════ */
const SignalCard = ({ s }) => {
  const [expanded, setExpanded] = useState(false);
  const [showChart, setShowChart] = useState(false);
  const prevPriceRef = useRef(s.price);
  const [flashCls, setFlashCls] = useState("");

  useEffect(() => {
    if (s.price !== prevPriceRef.current) {
      setFlashCls(s.price > prevPriceRef.current ? "price-up" : "price-down");
      prevPriceRef.current = s.price;
      const t = setTimeout(() => setFlashCls(""), 900);
      return () => clearTimeout(t);
    }
  }, [s.price]);

  const rrDisp  = s.rr ? `1:${s.rr}` : "—";
  const sigCol  = s.signal === "BUY" ? C.buy : s.signal === "SELL" ? C.sell : C.hold;
  const glowCls = s.signal === "BUY" ? "buy-glow" : s.signal === "SELL" ? "sell-glow" : "";
  const q       = qualityInfo(s.confidence, s.smc_score);

  const adxColor = s.adx > 30 ? C.buy : s.adx > 20 ? C.gold : C.sell;
  const rsiColor = s.rsi > 70  ? C.sell : s.rsi < 30  ? C.buy  : C.gold;

  return (
    <div className={glowCls} style={{
      background: C.bg1,
      border: `1px solid ${sigCol}44`,
      borderRadius: 12,
      padding: 16,
      display: "flex", flexDirection: "column", gap: 9,
      transition: "transform .15s",
      fontFamily: C.ui,
    }}>

      {/* ── Row 1: Symbol + badges ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontFamily: C.mono, fontSize: 15, fontWeight: 800, color: C.t0 }}>
            <span style={{ fontSize: 10, marginRight: 5, background: C.bg3, padding: "1px 6px", borderRadius: 3, color: C.t2 }}>
              {mktEmoji(s.market)}
            </span>
            {s.symbol}
          </div>
          <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginTop: 1 }}>
            {s.market?.toUpperCase()} • HTF {s.higher_tf?.toUpperCase()}
          </div>
        </div>
        <div style={{ display: "flex", gap: 5, flexWrap: "wrap", justifyContent: "flex-end" }}>
          {/* Quality badge */}
          <span style={{
            fontFamily: C.mono, fontSize: 11, fontWeight: 900,
            padding: "2px 8px", borderRadius: 4,
            background: q.bg, color: q.col,
            border: `1px solid ${q.col}40`,
          }}>{q.label}</span>
          {/* Session */}
          <span style={{
            fontFamily: C.mono, fontSize: 9, fontWeight: 700,
            padding: "2px 7px", borderRadius: 4,
            background: sessionCol(s.session) + "20",
            color: sessionCol(s.session),
            border: `1px solid ${sessionCol(s.session)}44`,
          }}>{s.session || "—"}</span>
        </div>
      </div>

      {/* ── Row 2: Price ── */}
      <div className={flashCls} style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "9px 12px", borderRadius: 8,
        background: C.bg0, border: `1px solid ${C.bdr}`,
        transition: "background .25s",
      }}>
        <span style={{ fontFamily: C.mono, fontSize: 19, fontWeight: 700, color: C.t0 }}>
          {s.price_display || fn(s.price, 4)}
        </span>
        <div style={{ textAlign: "right" }}>
          <div style={{
            fontFamily: C.mono, fontSize: 11, fontWeight: 600,
            color: parseFloat(s.change_pct) >= 0 ? C.buy : C.sell,
          }}>
            {fmtChg(s.change_pct)}
          </div>
          <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2 }}>24h</div>
        </div>
      </div>

      {/* ── Row 3: Signal + bias ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{
          fontFamily: C.mono, fontSize: 14, fontWeight: 900,
          padding: "5px 14px", borderRadius: 7,
          background: sigCol + "18", color: sigCol,
          border: `1px solid ${sigCol}55`,
          letterSpacing: ".1em",
        }}>
          {s.signal === "BUY" ? "▲ BUY" : s.signal === "SELL" ? "▼ SELL" : "◼ HOLD"}
        </span>
        <span style={{ fontFamily: C.mono, fontSize: 9, color: C.t2 }}>
          {s.bias} · {s.structure}
        </span>
      </div>

      {/* ── Confidence bar ── */}
      <ConfBar value={s.confidence} />

      {/* ── Row 4: Metrics ── */}
      <div style={{ display: "flex", gap: 4 }}>
        <Pill label="ADX"   value={s.adx  ? s.adx.toFixed(1)  : "—"} color={adxColor} />
        <Pill label="RSI"   value={s.rsi  ? s.rsi.toFixed(0)  : "—"} color={rsiColor} />
        <Pill label="SMC"   value={`${s.smc_score}/9`}                color={s.smc_score >= 7 ? C.buy : s.smc_score >= 5 ? C.gold : C.sell} />
        <Pill label="R:R"   value={rrDisp}                            color={C.t0} />
      </div>

      {/* ── EMA alignment ── */}
      <div style={{
        fontFamily: C.mono, fontSize: 9, padding: "4px 9px", borderRadius: 5,
        background: C.bg3,
        color: s.ema_alignment?.startsWith("Bull") ? C.buy
             : s.ema_alignment?.startsWith("Bear") ? C.sell : C.t1,
      }}>
        EMA: {s.ema_alignment || "—"}
      </div>

      {/* ── SMC check tags ── */}
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        <Tag label="SWEEP"   active={!!s.liquidity_sweep} small />
        <Tag label="BOS"     active={!!s.bos} small />
        <Tag label="FVG"     active={!!s.fvg_detected} small />
        <Tag label="HTF BUL" active={s.higher_tf_bias === "Bullish"} small />
        <Tag label="HTF BEA" active={s.higher_tf_bias === "Bearish"} small />
        <Tag label="SESSION" active={!!s.session && s.session !== "—"} small />
      </div>

      {/* ── Trade levels ── */}
      {s.signal !== "HOLD" && (
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
          gap: 4, borderTop: `1px solid ${C.bdr}`, paddingTop: 9,
        }}>
          {[
            { l: "ENTRY",  v: s.entry, c: C.t0 },
            { l: "STOP",   v: s.sl,    c: C.sell },
            { l: "TARGET", v: s.tp,    c: C.buy },
          ].map(({ l, v, c }) => (
            <div key={l} style={{ textAlign: "center" }}>
              <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 2 }}>{l}</div>
              <div style={{ fontFamily: C.mono, fontSize: 10, fontWeight: 700, color: c }}>
                {fn(v, 4)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Action buttons ── */}
      <div style={{ display: "flex", gap: 5, borderTop: `1px solid ${C.bdr}`, paddingTop: 8 }}>
        <button onClick={() => setExpanded(x => !x)} style={{
          flex: 2, fontFamily: C.mono, fontSize: 9, fontWeight: 600,
          padding: "6px 0", borderRadius: 6, cursor: "pointer",
          background: expanded ? C.bg3 : "transparent",
          border: `1px solid ${C.bdr}`,
          color: expanded ? C.t0 : C.t1,
          transition: "all .15s",
        }}>
          {expanded ? "▲ Close Analysis" : "▼ AI Analysis"}
        </button>
        <button onClick={() => setShowChart(x => !x)} style={{
          flex: 1, fontFamily: C.mono, fontSize: 9, fontWeight: 600,
          padding: "6px 0", borderRadius: 6, cursor: "pointer",
          background: showChart ? C.bg3 : "transparent",
          border: `1px solid ${C.bdr}`,
          color: showChart ? C.t0 : C.t1,
          transition: "all .15s",
        }}>
          📈 Chart
        </button>
      </div>

      {/* ── Expanded: AI panel ── */}
      {expanded && <AIPanel s={s} />}

      {/* ── Expanded: Mini chart ── */}
      {showChart && (
        <div className="slide-in">
          <MiniChart symbol={s.symbol} entry={s.entry} sl={s.sl} tp={s.tp} signal={s.signal} />
        </div>
      )}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   STATS BAR
══════════════════════════════════════════════════════ */
const StatsBar = ({ signals }) => {
  const total   = signals.length;
  const buys    = signals.filter(s => s.signal === "BUY").length;
  const sells   = signals.filter(s => s.signal === "SELL").length;
  const avgConf = total ? Math.round(signals.reduce((a, s) => a + (s.confidence || 0), 0) / total) : 0;
  const aPlus   = signals.filter(s => qualityInfo(s.confidence, s.smc_score).label === "A+").length;
  const avgAdx  = total ? (signals.reduce((a, s) => a + (s.adx || 0), 0) / total).toFixed(1) : "0";

  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
      {[
        { l: "SIGNALS", v: total, c: C.t0 },
        { l: "BUY",     v: buys,  c: C.buy },
        { l: "SELL",    v: sells, c: C.sell },
        { l: "AVG CONF",v: `${avgConf}%`, c: avgConf >= 70 ? C.buy : C.gold },
        { l: "A+ GRADE",v: aPlus, c: C.gold },
        { l: "AVG ADX", v: avgAdx, c: parseFloat(avgAdx) >= 25 ? C.buy : C.t1 },
      ].map(({ l, v, c }) => (
        <div key={l} style={{
          flex: "1 1 90px",
          background: C.bg1, border: `1px solid ${C.bdr}`,
          borderRadius: 8, padding: "10px 14px",
        }}>
          <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, letterSpacing: ".08em" }}>{l}</div>
          <div style={{ fontFamily: C.mono, fontSize: 22, fontWeight: 800, color: c, marginTop: 2 }}>{v}</div>
        </div>
      ))}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   FILTER BAR
══════════════════════════════════════════════════════ */
const FilterBar = ({ filters, onChange }) => {
  const Btn = ({ v, active, onClick }) => (
    <button onClick={onClick} style={{
      fontFamily: C.mono, fontSize: 9, fontWeight: active ? 700 : 400,
      padding: "4px 10px", borderRadius: 5, cursor: "pointer",
      background: active ? C.bg3 : "transparent",
      border:  `1px solid ${active ? C.bdr : "transparent"}`,
      color:   active ? C.t0 : C.t2,
      transition: "all .12s",
    }}>{v.toUpperCase()}</button>
  );

  return (
    <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 14 }}>
      <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
        <span style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginRight: 3 }}>MKT</span>
        {["All","crypto","forex","stocks","commodities"].map(m => (
          <Btn key={m} v={m} active={filters.market === m}
            onClick={() => onChange({ ...filters, market: m })} />
        ))}
      </div>
      <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
        <span style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginRight: 3 }}>SIG</span>
        {["All","BUY","SELL","HOLD"].map(s => (
          <Btn key={s} v={s} active={filters.signal === s}
            onClick={() => onChange({ ...filters, signal: s })} />
        ))}
      </div>
      <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
        <span style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginRight: 3 }}>GRADE</span>
        {["All","A+","A","B","C"].map(g => (
          <Btn key={g} v={g} active={filters.grade === g}
            onClick={() => onChange({ ...filters, grade: g })} />
        ))}
      </div>
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   MAIN DASHBOARD
══════════════════════════════════════════════════════ */
export default function Dashboard() {
  const [signals,   setSignals]   = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState(null);
  const [lastUpd,   setLastUpd]   = useState(null);
  const [countdown, setCountdown] = useState(30);
  const [strategy,  setStrategy]  = useState("bot");
  const [filters,   setFilters]   = useState({ market: "All", signal: "All", grade: "All" });

  useEffect(() => { injectGlobals(); }, []);

  const fetchSignals = useCallback(async () => {
    try {
      const r = await api(`/api/signals?strategy=${strategy}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setSignals(d.signals || []);
      setLastUpd(new Date().toLocaleTimeString());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      setCountdown(30);
    }
  }, [strategy]);

  useEffect(() => {
    fetchSignals();
    const iv = setInterval(fetchSignals, 30_000);
    return () => clearInterval(iv);
  }, [fetchSignals]);

  useEffect(() => {
    const t = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000);
    return () => clearInterval(t);
  }, []);

  const [utc, setUtc] = useState("");
  useEffect(() => {
    const upd = () => setUtc(new Date().toUTCString().slice(17, 25));
    upd();
    const t = setInterval(upd, 1000);
    return () => clearInterval(t);
  }, []);

  const hour = new Date().getUTCHours();
  const currentSession = hour >= 7 && hour < 12 ? "London"
    : hour >= 12 && hour < 21 ? "New York" : "Asia";

  const filtered = signals.filter(s => {
    if (filters.market !== "All" && s.market !== filters.market) return false;
    if (filters.signal !== "All" && s.signal !== filters.signal) return false;
    if (filters.grade  !== "All" && s.quality !== filters.grade) return false;
    return true;
  });

  return (
    <div style={{ background: C.bg0, minHeight: "100vh", fontFamily: C.ui }}>

      {/* ── Sticky header ── */}
      <div style={{
        background: C.bg1, borderBottom: `1px solid ${C.bdr}`,
        padding: "10px 20px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        position: "sticky", top: 0, zIndex: 200,
        backdropFilter: "blur(8px)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ fontFamily: C.mono, fontSize: 14, fontWeight: 800, color: C.t0 }}>
            <span style={{ color: C.buy }}>▸</span> TRADING TERMINAL
          </div>
          {/* Live dot */}
          <span className="live-dot" style={{
            display: "inline-block", width: 6, height: 6, borderRadius: "50%",
            background: C.buy,
          }} />
          <select value={strategy} onChange={e => setStrategy(e.target.value)} style={{
            fontFamily: C.mono, fontSize: 9, padding: "4px 8px", borderRadius: 5,
            background: C.bg3, border: `1px solid ${C.bdr}`, color: C.t1,
            cursor: "pointer",
          }}>
            <option value="bot">SMC Bot</option>
            <option value="basic">Basic Momentum</option>
            <option value="ema_rsi">EMA / RSI</option>
          </select>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{
            fontFamily: C.mono, fontSize: 9,
            padding: "3px 8px", borderRadius: 4,
            background: sessionCol(currentSession) + "22",
            color: sessionCol(currentSession),
            border: `1px solid ${sessionCol(currentSession)}40`,
          }}>{currentSession}</span>
          <span style={{ fontFamily: C.mono, fontSize: 10, color: C.t2 }}>{utc} UTC</span>
          <span style={{ fontFamily: C.mono, fontSize: 9, color: loading ? C.gold : C.t2 }}>
            {loading ? "Updating…" : `↻ ${countdown}s`}
          </span>
          <button onClick={fetchSignals} disabled={loading} style={{
            fontFamily: C.mono, fontSize: 9, padding: "5px 12px", borderRadius: 5,
            background: C.bg3, border: `1px solid ${C.bdr}`, color: C.t1,
            cursor: loading ? "wait" : "pointer",
          }}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* ── Content ── */}
      <div style={{ padding: "18px 20px", maxWidth: 1800 }}>
        {error && (
          <div style={{
            padding: "10px 14px", borderRadius: 7, marginBottom: 14,
            background: C.sell + "12", border: `1px solid ${C.sell}40`,
            fontFamily: C.mono, fontSize: 10, color: C.sell,
          }}>⚠ {error}</div>
        )}

        <StatsBar signals={signals} />
        <FilterBar filters={filters} onChange={setFilters} />

        {loading && !signals.length ? (
          <div style={{ textAlign: "center", padding: 60, fontFamily: C.mono, color: C.t2 }}>
            <div style={{ fontSize: 28, animation: "spin 1s linear infinite", display: "inline-block", marginBottom: 10 }}>⟳</div>
            <div>Fetching live signals…</div>
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40, fontFamily: C.mono, color: C.t2 }}>
            No signals match current filters.
          </div>
        ) : (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(310px, 1fr))",
            gap: 12,
          }}>
            {filtered.map(s => <SignalCard key={s.symbol} s={s} />)}
          </div>
        )}

        {lastUpd && (
          <div style={{ textAlign: "right", marginTop: 14, fontFamily: C.mono, fontSize: 9, color: C.t2 }}>
            Last updated: {lastUpd}
          </div>
        )}
      </div>
    </div>
  );
}

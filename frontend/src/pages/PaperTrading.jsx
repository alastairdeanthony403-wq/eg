/**
 * PaperTrading.jsx — NexusBot
 * Live paper trading page: bot auto-trader, open positions, signal scanner,
 * equity curve, activity feed, and closed trade history.
 */
import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "../lib/api";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from "recharts";
import {
  Play, Square, RefreshCw, Zap, TrendingUp, TrendingDown,
  AlertTriangle, CheckCircle, Activity, RotateCcw,
  ArrowUpRight, ArrowDownRight, Clock, Database,
  ChevronUp, ChevronDown, X,
} from "lucide-react";

// ── Design tokens (match rest of app) ────────────────────────────────────────
const T = {
  bg:     "#050914", bg2: "#08111f", bg3: "#0d1a2e", bg4: "#111f38",
  border: "#162036", b2: "#1e3060",
  text:   "#c8d8f0", t2: "#6a8aaa", t3: "#2a4060",
  green:  "#00ffa3", red: "#ff2d55", gold: "#ffc107",
  blue:   "#4facfe", purple: "#9f7aea", cyan: "#22d3ee",
  orange: "#ff8c00",
};
const MONO = "'JetBrains Mono','Cascadia Code','Courier New',monospace";
const UI   = "'Rajdhani','Segoe UI',system-ui,sans-serif";

const GS = `
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap');
*{box-sizing:border-box}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:#050914}
::-webkit-scrollbar-thumb{background:#162036;border-radius:3px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes slide{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
@keyframes pulse-green{0%,100%{box-shadow:0 0 0 0 #00ffa340}50%{box-shadow:0 0 0 6px #00ffa300}}
`;

const fmt    = (n, d = 2) => n == null ? "—" : Number(n).toFixed(d);
const fmtPnl = (n)       => n == null ? "—" : (n >= 0 ? "+" : "") + fmt(n, 2);
const fmtPct = (n)       => n == null ? "—" : fmt(n, 1) + "%";
const sigColor = (s)     => s === "BUY" ? T.green : s === "SELL" ? T.red : T.t2;

const ALL_WATCHLIST = [
  "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT",
  "EURUSD","GBPUSD","USDJPY",
  "AAPL","TSLA","NVDA","SPY",
  "XAUUSD",
];

// ── MAIN COMPONENT ─────────────────────────────────────────────────────────────
export default function PaperTrading() {
  // Account state
  const [summary,    setSummary]   = useState(null);
  const [equity,     setEquity]    = useState([]);
  const [positions,  setPositions] = useState([]);
  const [closed,     setClosed]    = useState([]);
  const [alerts,     setAlerts]    = useState([]);

  // Scanner state
  const [scanResult, setScanResult] = useState(null);
  const [scanning,   setScanning]   = useState(false);

  // Bot state
  const [botActive,  setBotActive]  = useState(false);
  const [togglingBot,setTogglingBot]= useState(false);

  // Manual trade state
  const [manualSym,  setManualSym]  = useState("BTCUSDT");
  const [manualSide, setManualSide] = useState("BUY");
  const [opening,    setOpening]    = useState(false);

  // UI state
  const [closingId,  setClosingId]  = useState(null);
  const [resetting,  setResetting]  = useState(false);
  const [error,      setError]      = useState(null);
  const [notice,     setNotice]     = useState(null);
  const [activeTab,  setActiveTab]  = useState("positions");

  const pollRef = useRef(null);
  const botRef  = useRef(botActive);
  botRef.current = botActive;

  // ── Loaders ───────────────────────────────────────────────────────────────
  const loadSummary = useCallback(async () => {
    try {
      const d = await apiFetch("/api/paper/summary");
      setSummary(d);
      setBotActive(d.bot_active || false);
    } catch {}
  }, []);

  const loadPositions = useCallback(async () => {
    try {
      const d = await apiFetch("/api/paper/positions");
      setPositions(Array.isArray(d) ? d : []);
    } catch {}
  }, []);

  const loadClosed = useCallback(async () => {
    try {
      const d = await apiFetch("/api/trades");
      setClosed((Array.isArray(d) ? d : []).filter(t => t.status === "CLOSED").slice(0, 50));
    } catch {}
  }, []);

  const loadEquity = useCallback(async () => {
    try {
      const d = await apiFetch("/api/equity");
      setEquity(Array.isArray(d) ? d.slice(-60) : []);
    } catch {}
  }, []);

  const loadAlerts = useCallback(async () => {
    try {
      const d = await apiFetch("/api/alerts");
      setAlerts(Array.isArray(d) ? d.slice(0, 30) : []);
    } catch {}
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([
      loadSummary(), loadPositions(), loadEquity(),
      loadClosed(),  loadAlerts(),
    ]);
  }, [loadSummary, loadPositions, loadEquity, loadClosed, loadAlerts]);

  // ── Polling: positions every 30s, bot-scan every 60s when active ──────────
  useEffect(() => {
    refreshAll();
    const positionPoll = setInterval(() => {
      loadPositions();
      loadSummary();
      loadAlerts();
    }, 30_000);

    pollRef.current = setInterval(async () => {
      if (!botRef.current) return;
      try {
        const d = await apiFetch("/api/paper/bot-scan", { method: "POST",
          body: JSON.stringify({}) });
        if (d.opened?.length) {
          setNotice(`Bot opened ${d.opened.length} trade(s): ${d.opened.map(o=>o.symbol).join(", ")}`);
          loadPositions(); loadSummary(); loadAlerts(); loadEquity();
        }
      } catch {}
    }, 60_000);

    return () => { clearInterval(positionPoll); clearInterval(pollRef.current); };
  }, [refreshAll, loadPositions, loadSummary, loadAlerts, loadEquity]);

  // ── Bot toggle ────────────────────────────────────────────────────────────
  const toggleBot = async () => {
    setTogglingBot(true);
    try {
      const path = botActive ? "/api/paper/stop-auto" : "/api/paper/start-auto";
      const d = await apiFetch(path, { method: "POST", body: "{}" });
      setBotActive(d.enabled);
      setNotice(d.enabled ? "Bot started — scanning every 60s" : "Bot stopped");
    } catch(e) { setError(e.message); }
    finally { setTogglingBot(false); }
  };

  // ── Manual scan ───────────────────────────────────────────────────────────
  const runScan = async (force = false) => {
    setScanning(true); setScanResult(null);
    try {
      const d = await apiFetch("/api/paper/bot-scan", {
        method: "POST", body: JSON.stringify({ force }),
      });
      setScanResult(d);
      if (d.opened?.length) {
        setNotice(`Opened ${d.opened.length} trade(s): ${d.opened.map(o=>o.symbol).join(", ")}`);
        loadPositions(); loadSummary(); loadEquity(); loadAlerts();
      } else if (force) {
        setNotice("Scan complete — no qualifying signals at this time.");
      }
    } catch(e) { setError(e.message); }
    finally { setScanning(false); }
  };

  // ── Manual trade ──────────────────────────────────────────────────────────
  const openManualTrade = async () => {
    setOpening(true); setError(null);
    try {
      const d = await apiFetch("/api/trades", {
        method: "POST",
        body: JSON.stringify({ symbol: manualSym, side: manualSide }),
      });
      if (!d.ok) throw new Error(d.error || "Open failed");
      setNotice(`Opened ${manualSide} ${manualSym} @ ${fmt(d.entry, 6)}`);
      loadPositions(); loadSummary(); loadAlerts();
    } catch(e) { setError(e.message); }
    finally { setOpening(false); }
  };

  // ── Close trade ───────────────────────────────────────────────────────────
  const closeTrade = async (tid) => {
    setClosingId(tid);
    try {
      const d = await apiFetch(`/api/trades/${tid}/close`, { method: "POST", body: "{}" });
      setNotice(`Closed trade — P&L: ${fmtPnl(d.pnl)}`);
      loadPositions(); loadSummary(); loadEquity(); loadClosed(); loadAlerts();
    } catch(e) { setError(e.message); }
    finally { setClosingId(null); }
  };

  // ── Reset account ─────────────────────────────────────────────────────────
  const resetAccount = async () => {
    if (!window.confirm("Reset paper trading account? All trades will be deleted.")) return;
    setResetting(true);
    try {
      await apiFetch("/api/paper/reset", { method: "POST", body: "{}" });
      setBotActive(false);
      setNotice("Account reset — starting fresh.");
      refreshAll();
    } catch(e) { setError(e.message); }
    finally { setResetting(false); }
  };

  const unrealizedPnl = positions.reduce((s, p) => s + (p.pnl || 0), 0);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{minHeight:"100vh",background:T.bg,fontFamily:UI,color:T.text}}>
      <style>{GS}</style>

      {/* Page header */}
      <div style={{padding:"22px 24px 0",borderBottom:`1px solid ${T.border}`,marginBottom:20}}>
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:12,marginBottom:18}}>
          <div>
            <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:4}}>
              <Activity size={20} style={{color:T.green}}/>
              <h1 style={{margin:0,fontSize:22,fontWeight:700,letterSpacing:1}}>PAPER TRADING</h1>
              {botActive&&(
                <span style={{fontFamily:MONO,fontSize:9,background:`${T.green}18`,
                  border:`1px solid ${T.green}44`,borderRadius:3,padding:"2px 8px",
                  color:T.green,letterSpacing:2,animation:"pulse-green 2s infinite"}}>
                  BOT LIVE
                </span>
              )}
            </div>
            <p style={{margin:0,fontSize:13,color:T.t2}}>
              Virtual account · no real money · powered by live market data
            </p>
          </div>
          <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
            <button onClick={refreshAll}
              style={{background:T.bg3,border:`1px solid ${T.border}`,color:T.t2,
                borderRadius:4,padding:"7px 14px",cursor:"pointer",fontFamily:MONO,
                fontSize:10,display:"flex",alignItems:"center",gap:5}}>
              <RefreshCw size={11}/>REFRESH
            </button>
            <button onClick={resetAccount} disabled={resetting}
              style={{background:`${T.red}10`,border:`1px solid ${T.red}33`,color:T.red,
                borderRadius:4,padding:"7px 14px",cursor:"pointer",fontFamily:MONO,
                fontSize:10,display:"flex",alignItems:"center",gap:5}}>
              <RotateCcw size={11}/>{resetting?"RESETTING…":"RESET"}
            </button>
          </div>
        </div>
      </div>

      <div style={{padding:"0 24px 40px"}}>

        {/* Error / Notice banners */}
        {error&&(
          <div style={{background:`${T.red}12`,border:`1px solid ${T.red}40`,borderRadius:5,
            padding:"9px 14px",marginBottom:14,color:T.red,fontFamily:MONO,fontSize:12,
            display:"flex",alignItems:"center",gap:10}}>
            <AlertTriangle size={13}/>
            <span style={{flex:1}}>{error}</span>
            <button onClick={()=>setError(null)} style={{background:"none",border:"none",color:T.t2,cursor:"pointer"}}>×</button>
          </div>
        )}
        {notice&&(
          <div style={{background:`${T.green}10`,border:`1px solid ${T.green}33`,borderRadius:5,
            padding:"9px 14px",marginBottom:14,color:T.green,fontFamily:MONO,fontSize:12,
            display:"flex",alignItems:"center",gap:10,animation:"slide .2s ease"}}>
            <CheckCircle size={13}/>
            <span style={{flex:1}}>{notice}</span>
            <button onClick={()=>setNotice(null)} style={{background:"none",border:"none",color:T.t2,cursor:"pointer"}}>×</button>
          </div>
        )}

        {/* ── Account stats strip ── */}
        <AccountStrip summary={summary} unrealizedPnl={unrealizedPnl}/>

        {/* ── Bot controls + Manual trade ── */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,marginBottom:20}}>

          {/* Bot control */}
          <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,padding:16}}>
            <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
              <Zap size={14} style={{color:botActive?T.green:T.t2}}/>
              <span style={{fontFamily:MONO,fontSize:11,color:botActive?T.green:T.t2,letterSpacing:2}}>
                BOT AUTO-TRADER
              </span>
            </div>
            <p style={{margin:"0 0 14px",fontSize:12,color:T.t2,lineHeight:1.6}}>
              When active, the bot scans your watchlist every 60 seconds and automatically
              opens trades when signals pass confidence + R:R gates.
            </p>
            <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
              <button onClick={toggleBot} disabled={togglingBot}
                style={{flex:1,background:botActive?`${T.red}14`:`${T.green}14`,
                  border:`1px solid ${botActive?T.red:T.green}44`,
                  color:botActive?T.red:T.green,borderRadius:4,padding:"9px 0",
                  cursor:"pointer",fontFamily:MONO,fontSize:11,letterSpacing:1,
                  display:"flex",alignItems:"center",justifyContent:"center",gap:6}}>
                {togglingBot
                  ? <><Spinner c={botActive?T.red:T.green}/>TOGGLING…</>
                  : botActive
                    ? <><Square size={11}/>STOP BOT</>
                    : <><Play  size={11}/>START BOT</>
                }
              </button>
              <button onClick={()=>runScan(true)} disabled={scanning}
                style={{flex:1,background:`${T.blue}12`,border:`1px solid ${T.blue}44`,
                  color:T.blue,borderRadius:4,padding:"9px 0",cursor:"pointer",
                  fontFamily:MONO,fontSize:11,letterSpacing:1,
                  display:"flex",alignItems:"center",justifyContent:"center",gap:6}}>
                {scanning
                  ? <><Spinner c={T.blue}/>SCANNING…</>
                  : <><RefreshCw size={11}/>SCAN NOW</>
                }
              </button>
            </div>
          </div>

          {/* Manual trade */}
          <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,padding:16}}>
            <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
              <TrendingUp size={14} style={{color:T.blue}}/>
              <span style={{fontFamily:MONO,fontSize:11,color:T.blue,letterSpacing:2}}>
                MANUAL TRADE
              </span>
            </div>
            <p style={{margin:"0 0 14px",fontSize:12,color:T.t2,lineHeight:1.6}}>
              Open a paper trade using the bot's live signal levels (entry, SL, TP)
              for any supported symbol.
            </p>
            <div style={{display:"flex",gap:8}}>
              <select value={manualSym} onChange={e=>setManualSym(e.target.value)}
                style={{flex:2,background:T.bg2,border:`1px solid ${T.border}`,color:T.text,
                  borderRadius:4,padding:"8px 10px",fontFamily:MONO,fontSize:11,outline:"none"}}>
                {ALL_WATCHLIST.map(s=><option key={s} value={s}>{s}</option>)}
              </select>
              <button onClick={()=>setManualSide("BUY")}
                style={{flex:1,background:manualSide==="BUY"?`${T.green}22`:"transparent",
                  border:`1px solid ${manualSide==="BUY"?T.green:T.border}`,
                  color:manualSide==="BUY"?T.green:T.t2,borderRadius:4,cursor:"pointer",
                  fontFamily:MONO,fontSize:11,padding:"8px 0"}}>
                BUY
              </button>
              <button onClick={()=>setManualSide("SELL")}
                style={{flex:1,background:manualSide==="SELL"?`${T.red}22`:"transparent",
                  border:`1px solid ${manualSide==="SELL"?T.red:T.border}`,
                  color:manualSide==="SELL"?T.red:T.t2,borderRadius:4,cursor:"pointer",
                  fontFamily:MONO,fontSize:11,padding:"8px 0"}}>
                SELL
              </button>
              <button onClick={openManualTrade} disabled={opening}
                style={{flex:1,background:`${T.blue}18`,border:`1px solid ${T.blue}44`,
                  color:T.blue,borderRadius:4,cursor:"pointer",fontFamily:MONO,fontSize:11,padding:"8px 0"}}>
                {opening?<Spinner c={T.blue}/>:"OPEN"}
              </button>
            </div>
          </div>
        </div>

        {/* ── Scan results (if ran) ── */}
        {scanResult&&<ScanResults data={scanResult} onDismiss={()=>setScanResult(null)}/>}

        {/* ── Main grid: positions + equity + signals ── */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 340px",gap:14,marginBottom:20}}>

          {/* Left — positions / history */}
          <div>
            {/* Tab bar */}
            <div style={{display:"flex",gap:0,borderBottom:`1px solid ${T.border}`,marginBottom:0}}>
              {["positions","history"].map(t=>(
                <button key={t} onClick={()=>setActiveTab(t)}
                  style={{padding:"9px 18px",background:"none",border:"none",
                    borderBottom:`2px solid ${activeTab===t?T.blue:"transparent"}`,
                    color:activeTab===t?T.blue:T.t2,cursor:"pointer",fontFamily:MONO,
                    fontSize:10,letterSpacing:2,textTransform:"uppercase"}}>
                  {t}{t==="positions"&&positions.length>0&&(
                    <span style={{marginLeft:6,background:T.blue,color:"#000",
                      borderRadius:10,padding:"1px 6px",fontSize:9}}>
                      {positions.length}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {activeTab==="positions"&&(
              positions.length===0
                ? <EmptyPanel text="No open positions. Start the bot or open a manual trade." icon={<Activity size={28} style={{color:T.t3}}/>}/>
                : <div>
                    {positions.map(p=>(
                      <PositionRow key={p.id} pos={p}
                        closing={closingId===p.id}
                        onClose={()=>closeTrade(p.id)}/>
                    ))}
                  </div>
            )}

            {activeTab==="history"&&(
              closed.length===0
                ? <EmptyPanel text="No closed trades yet." icon={<Clock size={28} style={{color:T.t3}}/>}/>
                : <div style={{overflowX:"auto"}}>
                    <table style={{width:"100%",borderCollapse:"collapse",fontFamily:MONO,fontSize:10}}>
                      <thead>
                        <tr>
                          {["SYMBOL","SIDE","ENTRY","EXIT","P&L","TIME"].map(h=>(
                            <th key={h} style={{padding:"9px 12px",textAlign:"left",fontFamily:MONO,
                              fontSize:8,color:T.t2,borderBottom:`1px solid ${T.border}`,
                              background:T.bg2,letterSpacing:1}}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {closed.map((t,i)=>(
                          <tr key={t.id} style={{background:i%2===0?T.bg3:T.bg2,
                            borderBottom:`1px solid ${T.border}`}}>
                            <td style={{padding:"8px 12px",color:T.text,fontWeight:600}}>{t.symbol}</td>
                            <td style={{padding:"8px 12px",color:t.side==="BUY"?T.green:T.red}}>
                              {t.side}
                            </td>
                            <td style={{padding:"8px 12px",color:T.text}}>{fmt(t.entry,6)}</td>
                            <td style={{padding:"8px 12px",color:T.text}}>{fmt(t.exit,6)}</td>
                            <td style={{padding:"8px 12px",fontWeight:600,
                              color:(t.pnl||0)>=0?T.green:T.red}}>
                              {fmtPnl(t.pnl)}
                            </td>
                            <td style={{padding:"8px 12px",color:T.t2,fontSize:9}}>
                              {String(t.time||"").slice(0,16)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
            )}
          </div>

          {/* Right — equity curve + activity */}
          <div style={{display:"flex",flexDirection:"column",gap:14}}>
            <EquityPanel equity={equity} summary={summary}/>
            <ActivityFeed alerts={alerts}/>
          </div>
        </div>

      </div>
    </div>
  );
}

// ── ACCOUNT STATS STRIP ────────────────────────────────────────────────────────
function AccountStrip({ summary: s, unrealizedPnl }) {
  if (!s) return (
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,
      padding:16,marginBottom:20,display:"flex",gap:20,flexWrap:"wrap"}}>
      {[1,2,3,4,5,6].map(i=>(
        <div key={i} style={{width:120,height:38,background:T.bg4,borderRadius:4,opacity:0.4}}/>
      ))}
    </div>
  );

  const balChange = s.current_balance - s.starting_balance;
  const balPct    = s.starting_balance ? (balChange / s.starting_balance * 100) : 0;

  const stats = [
    { label:"VIRTUAL BALANCE",  val: `$${s.current_balance?.toLocaleString("en",{minimumFractionDigits:2})}`,
      color: T.text, big: true },
    { label:"REALIZED P&L",     val: fmtPnl(s.realized_pnl)+" $",
      color: (s.realized_pnl||0)>=0?T.green:T.red },
    { label:"UNREALIZED",       val: fmtPnl(unrealizedPnl)+" $",
      color: unrealizedPnl>=0?T.green:T.red },
    { label:"RETURN",           val: (balPct>=0?"+":"")+fmt(balPct,2)+"%",
      color: balPct>=0?T.green:T.red },
    { label:"WIN RATE",         val: fmtPct(s.win_rate),        color: T.gold },
    { label:"PROFIT FACTOR",    val: fmt(s.profit_factor),      color: T.blue },
    { label:"CLOSED TRADES",    val: s.total_closed||0,         color: T.text },
    { label:"OPEN POSITIONS",   val: s.open_positions||0,       color: T.cyan },
  ];

  return (
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,
      padding:"14px 18px",marginBottom:20,display:"flex",gap:24,flexWrap:"wrap",
      alignItems:"center"}}>
      {stats.map(({label,val,color,big})=>(
        <div key={label}>
          <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:3}}>
            {label}
          </div>
          <div style={{fontFamily:MONO,fontSize:big?18:13,color,fontWeight:big?700:500}}>
            {val}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── POSITION ROW ───────────────────────────────────────────────────────────────
function PositionRow({ pos: p, closing, onClose }) {
  const pnlPos = (p.pnl || 0) >= 0;
  return (
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,
      padding:"12px 16px",marginBottom:8,animation:"slide .2s ease",
      borderLeft:`3px solid ${p.side==="BUY"?T.green:T.red}`}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>

        {/* Symbol + side */}
        <div style={{display:"flex",alignItems:"center",gap:10,minWidth:140}}>
          <div style={{background:p.side==="BUY"?`${T.green}18`:`${T.red}18`,
            border:`1px solid ${p.side==="BUY"?T.green:T.red}44`,
            borderRadius:3,padding:"3px 8px",fontFamily:MONO,fontSize:10,
            color:p.side==="BUY"?T.green:T.red,fontWeight:700}}>
            {p.side}
          </div>
          <span style={{fontFamily:MONO,fontSize:14,fontWeight:700,color:T.text}}>
            {p.symbol}
          </span>
        </div>

        {/* Levels */}
        <div style={{display:"flex",gap:18,flexWrap:"wrap"}}>
          <StatCell label="ENTRY"   val={fmt(p.entry,6)}         color={T.text}/>
          <StatCell label="PRICE"   val={fmt(p.current_price,6)} color={T.text}/>
          <StatCell label="SL"      val={fmt(p.sl,6)}            color={T.red}/>
          <StatCell label="TP"      val={fmt(p.tp,6)}            color={T.green}/>
          <StatCell label="SIZE"    val={fmt(p.size,4)}          color={T.t2}/>
          <StatCell label="P&L $"   val={fmtPnl(p.pnl)}         color={pnlPos?T.green:T.red}/>
          <StatCell label="P&L %"   val={(p.pnl_pct>=0?"+":"")+fmt(p.pnl_pct,2)+"%"}
                                                                  color={pnlPos?T.green:T.red}/>
        </div>

        {/* Close button */}
        <button onClick={onClose} disabled={closing}
          style={{background:`${T.red}14`,border:`1px solid ${T.red}44`,color:T.red,
            borderRadius:4,padding:"7px 14px",cursor:"pointer",fontFamily:MONO,
            fontSize:10,display:"flex",alignItems:"center",gap:5,whiteSpace:"nowrap"}}>
          {closing?<Spinner c={T.red}/>:<X size={11}/>}
          CLOSE
        </button>
      </div>

      <div style={{marginTop:6,fontFamily:MONO,fontSize:9,color:T.t2}}>
        Opened {String(p.time||"").slice(0,16)}
      </div>
    </div>
  );
}

// ── EQUITY PANEL ───────────────────────────────────────────────────────────────
function EquityPanel({ equity, summary: s }) {
  const last  = equity[equity.length - 1]?.equity ?? s?.current_balance ?? 0;
  const first = equity[0]?.equity ?? s?.starting_balance ?? last;
  const up    = last >= first;

  return (
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,padding:14}}>
      <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:10}}>
        <Database size={12} style={{color:T.blue}}/>
        <span style={{fontFamily:MONO,fontSize:9,color:T.blue,letterSpacing:2}}>EQUITY CURVE</span>
        <span style={{marginLeft:"auto",fontFamily:MONO,fontSize:11,
          color:up?T.green:T.red,fontWeight:600}}>
          ${last?.toFixed(2)}
        </span>
      </div>
      {equity.length >= 2 ? (
        <ResponsiveContainer width="100%" height={130}>
          <AreaChart data={equity} margin={{top:4,right:4,left:-20,bottom:0}}>
            <defs>
              <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={up?T.green:T.red} stopOpacity={0.3}/>
                <stop offset="95%" stopColor={up?T.green:T.red} stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={T.border}/>
            <XAxis dataKey="time" hide tick={{fill:T.t2,fontSize:8,fontFamily:MONO}}/>
            <YAxis tick={{fill:T.t2,fontSize:8,fontFamily:MONO}} tickLine={false}/>
            <Tooltip
              contentStyle={{background:T.bg2,border:`1px solid ${T.border}`,
                fontFamily:MONO,fontSize:10}}
              formatter={v=>[`$${Number(v).toFixed(2)}`,"Equity"]}/>
            <Area type="monotone" dataKey="equity"
              stroke={up?T.green:T.red} strokeWidth={1.5}
              fill="url(#eqGrad)" dot={false}/>
          </AreaChart>
        </ResponsiveContainer>
      ) : (
        <div style={{height:130,display:"flex",alignItems:"center",justifyContent:"center",
          color:T.t2,fontFamily:MONO,fontSize:11}}>
          No trades closed yet
        </div>
      )}
    </div>
  );
}

// ── ACTIVITY FEED ─────────────────────────────────────────────────────────────
function ActivityFeed({ alerts }) {
  return (
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,
      padding:14,flex:1,maxHeight:280,overflowY:"auto"}}>
      <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:10}}>
        <Activity size={12} style={{color:T.purple}}/>
        <span style={{fontFamily:MONO,fontSize:9,color:T.purple,letterSpacing:2}}>ACTIVITY</span>
      </div>
      {alerts.length === 0
        ? <div style={{color:T.t2,fontFamily:MONO,fontSize:11,textAlign:"center",paddingTop:20}}>
            No activity yet
          </div>
        : alerts.map((a,i)=>(
            <div key={i} style={{display:"flex",gap:8,marginBottom:7,
              borderBottom:`1px solid ${T.border}`,paddingBottom:7}}>
              <span style={{fontFamily:MONO,fontSize:9,color:T.t2,whiteSpace:"nowrap",flexShrink:0}}>
                {String(a.time||"").slice(11,16)}
              </span>
              <span style={{fontFamily:MONO,fontSize:10,color:
                a.message?.includes("OPEN")?T.green:
                a.message?.includes("CLOSE")?T.red:T.text,
                lineHeight:1.5}}>
                {a.message}
              </span>
            </div>
          ))
      }
    </div>
  );
}

// ── SCAN RESULTS ──────────────────────────────────────────────────────────────
function ScanResults({ data: d, onDismiss }) {
  return (
    <div style={{background:T.bg3,border:`1px solid ${T.cyan}40`,borderRadius:6,padding:16,
      marginBottom:20,animation:"slide .25s ease"}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:12}}>
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <Zap size={14} style={{color:T.cyan}}/>
          <span style={{fontFamily:MONO,fontSize:11,color:T.cyan,letterSpacing:1}}>
            SCAN COMPLETE — {d.scanned} SYMBOLS
          </span>
          {d.opened?.length>0&&(
            <span style={{fontFamily:MONO,fontSize:9,background:`${T.green}18`,
              border:`1px solid ${T.green}44`,borderRadius:3,padding:"2px 7px",color:T.green}}>
              {d.opened.length} TRADE{d.opened.length!==1?"S":""} OPENED
            </span>
          )}
        </div>
        <button onClick={onDismiss}
          style={{background:"none",border:"none",color:T.t2,cursor:"pointer",fontSize:16}}>×</button>
      </div>
      <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
        {d.signals?.map((s,i)=>(
          <div key={i} style={{background:T.bg2,border:`1px solid ${T.border}`,borderRadius:4,
            padding:"7px 12px",minWidth:110}}>
            <div style={{fontFamily:MONO,fontSize:10,color:T.text,marginBottom:3}}>{s.symbol}</div>
            <div style={{display:"flex",alignItems:"center",gap:6}}>
              <span style={{fontFamily:MONO,fontSize:11,fontWeight:700,color:sigColor(s.signal)}}>
                {s.signal}
              </span>
              {s.confidence>0&&(
                <span style={{fontFamily:MONO,fontSize:9,color:T.t2}}>{fmt(s.confidence,0)}%</span>
              )}
            </div>
          </div>
        ))}
      </div>
      {d.opened?.length>0&&(
        <div style={{marginTop:10,paddingTop:10,borderTop:`1px solid ${T.border}`}}>
          <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:6}}>OPENED</div>
          {d.opened.map((o,i)=>(
            <div key={i} style={{fontFamily:MONO,fontSize:11,color:T.green,marginBottom:3}}>
              ✓ {o.side} {o.symbol} @ {fmt(o.entry,6)} — SL {fmt(o.sl,6)} / TP {fmt(o.tp,6)}
            </div>
          ))}
        </div>
      )}
      {d.skipped?.length>0&&(
        <div style={{marginTop:8,display:"flex",gap:6,flexWrap:"wrap"}}>
          {d.skipped.map((s,i)=>(
            <span key={i} style={{fontFamily:MONO,fontSize:9,color:T.t2,
              background:T.bg2,border:`1px solid ${T.border}`,borderRadius:3,padding:"2px 7px"}}>
              {s.symbol} skipped ({s.reason?.replace(/_/g," ")})
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── HELPERS ───────────────────────────────────────────────────────────────────
function StatCell({ label, val, color }) {
  return (
    <div>
      <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{label}</div>
      <div style={{fontFamily:MONO,fontSize:11,color:color||T.text}}>{val||"—"}</div>
    </div>
  );
}

function EmptyPanel({ text, icon }) {
  return (
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,
      padding:40,textAlign:"center",color:T.t2}}>
      <div style={{marginBottom:10}}>{icon}</div>
      <div style={{fontFamily:MONO,fontSize:12}}>{text}</div>
    </div>
  );
}

function Spinner({ c }) {
  return (
    <div style={{width:11,height:11,border:`2px solid ${T.t2}33`,
      borderTop:`2px solid ${c||T.blue}`,borderRadius:"50%",
      animation:"spin 1s linear infinite",display:"inline-block"}}/>
  );
}

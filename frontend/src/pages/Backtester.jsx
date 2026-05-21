/**
 * Backtester.jsx — NexusBot v2
 * Full-featured backtester: equity curve, detailed trade table,
 * strategy comparison, learn-from-mistakes panel, historical metadata.
 * FIX: response body is read exactly once — no "body stream already read" error.
 */
import { apiFetch } from "../lib/api";
import { useState, useEffect, useCallback } from "react";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, Legend, ComposedChart, Line,
} from "recharts";
import {
  Play, ChevronDown, ChevronUp, TrendingUp, TrendingDown,
  BarChart2, RefreshCw, Brain, Clock, Calendar, Database,
  AlertTriangle, CheckCircle, Zap, ArrowUpRight, ArrowDownRight,
} from "lucide-react";

// ── Design tokens (match Dashboard) ──────────────────────────────────────────
const T = {
  bg:"#050914", bg2:"#08111f", bg3:"#0d1a2e", bg4:"#111f38",
  border:"#162036", b2:"#1e3060",
  text:"#c8d8f0", t2:"#6a8aaa", t3:"#2a4060",
  green:"#00ffa3", red:"#ff2d55", gold:"#ffc107",
  blue:"#4facfe", purple:"#9f7aea", cyan:"#22d3ee",
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
`;

const fmt    = (n,d=2) => n==null?"—":Number(n).toFixed(d);
const fmtPnl = (n)    => n==null?"—":(n>=0?"+":"")+fmt(n,2);
const fmtPct = (n)    => n==null?"—":fmt(n,1)+"%";
const durStr  = (s)   => {
  if(!s) return"—";
  const m=Math.round(s/60); if(m<60) return`${m}m`;
  const h=Math.floor(m/60), rm=m%60; return rm?`${h}h ${rm}m`:`${h}h`;
};

const STRATEGIES = [
  {value:"unified_bot", label:"SMC Unified Bot"},
  {value:"basic",       label:"Basic SMC"},
  {value:"ema_rsi",     label:"EMA + RSI"},
  {value:"sma_cross",   label:"SMA Crossover"},
];

// ── MAIN COMPONENT ────────────────────────────────────────────────────────────
export default function Backtester() {
  // Config
  const [symbol,    setSymbol]   = useState("BTCUSDT");
  const [strategy,  setStrategy] = useState("bot");
  const [days,      setDays]     = useState(30);
  const [balance,   setBalance]  = useState(10000);
  const [fee,       setFee]      = useState(0.04);
  const [slip,      setSlip]     = useState(0.02);
  const [rndWindow, setRndWindow]= useState(false);

  // Results
  const [result,    setResult]   = useState(null);
  const [running,   setRunning]  = useState(false);
  const [error,     setError]    = useState(null);
  const [tab,       setTab]      = useState("results");

  // Sub-features
  const [history,     setHistory]   = useState([]);
  const [compareData, setCompare]   = useState(null);
  const [comparing,   setComparing] = useState(false);
  const [learning,    setLearning]  = useState(false);
  const [learnResult, setLearnResult]= useState(null);
  const [learnHistory,setLearnHistory]=useState([]);
  const [sortField,   setSortField] = useState("open_time");
  const [sortDir,     setSortDir]   = useState("desc");
  const [page,        setPage]      = useState(0);
  const PAGE = 20;

  // ── Run backtest ────────────────────────────────────────────────────────────
  const run = async () => {
    setRunning(true); setError(null); setResult(null);
    setCompare(null); setLearnResult(null); setPage(0);
    try {
      const d = await apiFetch("/api/backtest", {
        method:"POST",
        body:JSON.stringify({ symbol, strategy, period_days:Number(days),
          starting_balance:Number(balance), fee_percent:Number(fee),
          slippage_percent:Number(slip), random_window:rndWindow }),
      });
      // ← read body ONCE
      setResult(d);
      loadHistory();
    } catch(e){ setError(e.message); }
    finally{ setRunning(false); }
  };

  // ── Load run history ────────────────────────────────────────────────────────
  const loadHistory = useCallback(async () => {
    try {
      const r = await apiFetch("/api/backtest-runs");
      setHistory(Array.isArray(r) ? r : []);
    } catch{}
  }, []);

  // ── Load learn history ──────────────────────────────────────────────────────
  const loadLearnHistory = useCallback(async () => {
    try {
      const r = await apiFetch("/api/learn/history");
      setLearnHistory(r.history || []);
    } catch{}
  }, []);

  // ── Strategy comparison ─────────────────────────────────────────────────────
  const runCompare = async () => {
    setComparing(true);
    setCompare(null);

    const results = {};

    for (const s of STRATEGIES) {
      try {
        const d = await apiFetch("/api/backtest", {
          method: "POST",
          body: JSON.stringify({
            symbol,
            strategy: s.value,
            period_days: Number(days),
            starting_balance: Number(balance),
            fee_percent: Number(fee),
            slippage_percent: Number(slip),
            random_window: rndWindow
          }),
        });

        results[s.value] = {
          ...d.summary,
          label: s.label,
        };

      } catch (e) {
        console.error(e);
      }
    }

    setCompare(results);
    setComparing(false);
  };

  // ── Learn from mistakes ─────────────────────────────────────────────────────
  const handleRunLearn = async () => {
  setLearning(true);
  try {
    const d = await apiFetch("/api/learn", {
      method: "POST",
      body: JSON.stringify({ auto_apply: true, symbol }),
    });

    setLearnResult(d);
    loadLearnHistory();
  } catch(e) {
    setError(e.message);
  } finally {
    setLearning(false);
  }
};

  useEffect(() => {
    loadHistory();
    loadLearnHistory();
  }, [loadHistory, loadLearnHistory]);

  // ── Derived data ────────────────────────────────────────────────────────────
  const trades    = result?.trades || [];
  const summary   = result?.summary || {};

  const equityCurve = buildEquity(trades, summary.starting_balance||Number(balance));
  const drawdown    = buildDrawdown(equityCurve);
  const dailyPnl    = buildDailyPnl(trades);

  const sortedTrades = [...trades].sort((a,b)=>{
    const va=a[sortField], vb=b[sortField];
    return sortDir==="asc"?(va>vb?1:-1):(va<vb?1:-1);
  });
  const paginated = sortedTrades.slice(page*PAGE, (page+1)*PAGE);
  const totalPages = Math.ceil(sortedTrades.length/PAGE);

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div style={{background:T.bg,minHeight:"100vh",fontFamily:UI,color:T.text,padding:0}}>
      <style>{GS}</style>

      {/* Page header */}
      <div style={{background:T.bg2,borderBottom:`1px solid ${T.border}`,padding:"12px 20px",
        display:"flex",alignItems:"center",gap:14}}>
        <BarChart2 size={18} style={{color:T.blue}}/>
        <span style={{fontFamily:MONO,fontSize:14,letterSpacing:3,color:T.text}}>BACKTESTER</span>
      </div>

      {/* Config panel */}
      <div style={{margin:"18px 20px",background:T.bg3,border:`1px solid ${T.border}`,
        borderRadius:6,padding:"16px 18px"}}>
        <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:14}}>
          <Zap size={13} style={{color:T.gold}}/>
          <span style={{fontFamily:MONO,fontSize:10,letterSpacing:2,color:T.gold}}>
            BACKTEST CONFIGURATION
          </span>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(160px,1fr))",gap:12}}>
          <Field label="SYMBOL">
            <select value={symbol} onChange={e=>setSymbol(e.target.value)} style={selStyle}>
              <optgroup label="Crypto">
                {["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT"].map(s=><option key={s} value={s}>{s}</option>)}
              </optgroup>
              <optgroup label="Forex">
                {["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD"].map(s=><option key={s} value={s}>{s}</option>)}
              </optgroup>
              <optgroup label="Stocks">
                {["AAPL","TSLA","NVDA","MSFT","AMZN","SPY"].map(s=><option key={s} value={s}>{s}</option>)}
              </optgroup>
              <optgroup label="Commodities">
                {["XAUUSD","XAGUSD","USOIL","UKOIL"].map(s=><option key={s} value={s}>{s}</option>)}
              </optgroup>
            </select>
          </Field>
          <Field label="STRATEGY">
            <select value={strategy} onChange={e=>setStrategy(e.target.value)} style={selStyle}>
              {STRATEGIES.map(s=><option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="PERIOD">
            <select value={days} onChange={e=>setDays(e.target.value)} style={selStyle}>
              {[7,14,30,60,90].map(d=><option key={d} value={d}>{d} Days</option>)}
            </select>
          </Field>
          <Field label="BALANCE ($)">
            <input type="number" value={balance} onChange={e=>setBalance(e.target.value)} style={inpStyle}/>
          </Field>
          <Field label="FEE (%)">
            <input type="number" value={fee} step="0.01" onChange={e=>setFee(e.target.value)} style={inpStyle}/>
          </Field>
          <Field label="SLIPPAGE (%)">
            <input type="number" value={slip} step="0.01" onChange={e=>setSlip(e.target.value)} style={inpStyle}/>
          </Field>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:18,marginTop:14}}>
          <label style={{display:"flex",alignItems:"center",gap:8,cursor:"pointer",fontSize:12,color:T.t2,fontFamily:MONO}}>
            <input type="checkbox" checked={rndWindow} onChange={e=>setRndWindow(e.target.checked)}
              style={{accentColor:T.blue}}/>
            Random historical window
          </label>
          <button onClick={run} disabled={running}
            style={{background:running?T.bg4:`${T.green}20`,border:`1px solid ${running?T.border:T.green}`,
              color:running?T.t2:T.green,borderRadius:4,padding:"8px 22px",cursor:"pointer",
              fontFamily:MONO,fontSize:12,fontWeight:700,letterSpacing:2,
              display:"flex",alignItems:"center",gap:7}}>
            {running
              ? <><div style={{width:12,height:12,border:`2px solid ${T.t2}`,borderTop:`2px solid ${T.blue}`,borderRadius:"50%",animation:"spin 1s linear infinite"}}/>RUNNING…</>
              : <><Play size={12}/>RUN BACKTEST</>}
          </button>
        </div>
      </div>

      {/* Error */}
      {error&&<div style={{margin:"0 20px 16px",background:`${T.red}12`,border:`1px solid ${T.red}40`,borderRadius:5,padding:"10px 14px",color:T.red,fontFamily:MONO,fontSize:12}}>⚠ {error}</div>}

      {/* Tabs */}
      <div style={{margin:"0 20px",borderBottom:`1px solid ${T.border}`,display:"flex",gap:0}}>
        {["results","trades","compare","learn","history"].map(t=>(
          <button key={t} onClick={()=>setTab(t)}
            style={{padding:"9px 18px",background:"none",border:"none",borderBottom:`2px solid ${tab===t?T.blue:"transparent"}`,
              color:tab===t?T.blue:T.t2,cursor:"pointer",fontFamily:MONO,fontSize:10,
              letterSpacing:2,textTransform:"uppercase"}}>
            {t}
          </button>
        ))}
      </div>

      <div style={{padding:"18px 20px"}}>
        {/* RESULTS TAB */}
        {tab==="results"&&(
          !result
            ? <EmptyState text="Run a backtest to see results."/>
            : <div style={{animation:"slide .25s ease"}}>
                {/* Test metadata banner */}
                <TestMeta result={result}/>
                {/* Summary cards */}
                <SummaryCards summary={summary}/>
                {/* Equity curve */}
                <div style={{marginTop:16}}>
                  <ChartTitle>EQUITY CURVE</ChartTitle>
                  <EquityCurveChart data={equityCurve}/>
                </div>
                {/* Drawdown */}
                <div style={{marginTop:14}}>
                  <ChartTitle>DRAWDOWN %</ChartTitle>
                  <DrawdownChart data={drawdown}/>
                </div>
                {/* Daily PnL */}
                <div style={{marginTop:14}}>
                  <ChartTitle>DAILY P&L</ChartTitle>
                  <DailyPnlChart data={dailyPnl}/>
                </div>
              </div>
        )}

        {/* TRADES TAB */}
        {tab==="trades"&&(
          !result
            ? <EmptyState text="Run a backtest to see trades."/>
            : <div style={{animation:"slide .25s ease"}}>
                <div style={{marginBottom:12,display:"flex",alignItems:"center",justifyContent:"space-between"}}>
                  <span style={{fontFamily:MONO,fontSize:10,color:T.t2,letterSpacing:2}}>
                    {trades.length} TOTAL TRADES
                  </span>
                  <span style={{fontFamily:MONO,fontSize:10,color:T.t2}}>
                    Page {page+1} / {totalPages||1}
                  </span>
                </div>
                <TradeTable trades={paginated} sortField={sortField} sortDir={sortDir}
                  onSort={(f)=>{ setSortDir(sortField===f&&sortDir==="desc"?"asc":"desc"); setSortField(f); }}/>
                {/* Pagination */}
                {totalPages>1&&(
                  <div style={{display:"flex",justifyContent:"center",gap:8,marginTop:14}}>
                    <NavBtn label="← PREV" disabled={page===0} onClick={()=>setPage(p=>p-1)}/>
                    <NavBtn label="NEXT →" disabled={page>=totalPages-1} onClick={()=>setPage(p=>p+1)}/>
                  </div>
                )}
              </div>
        )}

        {/* COMPARE TAB */}
        {tab==="compare"&&(
          <div style={{animation:"slide .25s ease"}}>
            <div style={{display:"flex",alignItems:"center",gap:14,marginBottom:16}}>
              <p style={{margin:0,fontSize:13,color:T.t2,fontFamily:UI}}>
                Runs all 4 strategies on the same symbol &amp; period, then compares key metrics side-by-side.
              </p>
              <button onClick={runCompare} disabled={comparing}
                style={{background:`${T.blue}18`,border:`1px solid ${T.blue}44`,color:T.blue,
                  borderRadius:4,padding:"7px 18px",cursor:"pointer",fontFamily:MONO,
                  fontSize:11,letterSpacing:1,whiteSpace:"nowrap",flexShrink:0,
                  display:"flex",alignItems:"center",gap:6}}>
                {comparing?<><div style={{width:11,height:11,border:`2px solid ${T.t2}`,borderTop:`2px solid ${T.blue}`,borderRadius:"50%",animation:"spin 1s linear infinite"}}/>COMPARING…</>:<><BarChart2 size={12}/>COMPARE STRATEGIES</>}
              </button>
            </div>
            {compareData&&<ComparePanel data={compareData}/>}
          </div>
        )}

        {/* LEARN TAB */}
        {tab==="learn"&&(
          <div style={{animation:"slide .25s ease"}}>
            <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,padding:16,marginBottom:16}}>
              <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",gap:16}}>
                <div>
                  <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:8}}>
                    <Brain size={16} style={{color:T.purple}}/>
                    <span style={{fontFamily:MONO,fontSize:12,color:T.purple,letterSpacing:2}}>
                      LEARN FROM MISTAKES
                    </span>
                  </div>
                  <p style={{margin:0,fontSize:13,color:T.t2,lineHeight:1.65,maxWidth:520}}>
                    Analyses your losing trades and automatically adjusts bot config parameters —
                    confidence threshold, ADX minimum, session filters, and more —
                    to reduce future losses.
                  </p>
                </div>
                <button onClick={handleRunLearn} disabled={learning}
                  style={{background:`${T.purple}18`,border:`1px solid ${T.purple}44`,color:T.purple,
                    borderRadius:4,padding:"9px 20px",cursor:"pointer",fontFamily:MONO,fontSize:11,
                    letterSpacing:1,whiteSpace:"nowrap",flexShrink:0,display:"flex",alignItems:"center",gap:6}}>
                  {learning?<><div style={{width:11,height:11,border:`2px solid ${T.t2}`,borderTop:`2px solid ${T.purple}`,borderRadius:"50%",animation:"spin 1s linear infinite"}}/>ANALYSING…</>:<><Brain size={12}/>ANALYSE &amp; APPLY</>}
                </button>
              </div>
            </div>
            {learnResult&&<LearnResult data={learnResult}/>}
          </div>
        )}

        {/* HISTORY TAB */}
        {tab==="history"&&(
          <div style={{animation:"slide .25s ease"}}>
            {learnHistory.length>0&&(
              <div style={{marginBottom:20}}>
                <SectionHeader>LEARN HISTORY</SectionHeader>
                {learnHistory.map((l,i)=>(
                  <div key={i} style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:4,
                    padding:"10px 14px",marginBottom:8,display:"flex",gap:14,alignItems:"center"}}>
                    <span style={{fontFamily:MONO,fontSize:10,color:T.t2}}>{l.created_at?.slice(0,16)||"—"}</span>
                    <span style={{fontFamily:MONO,fontSize:11,color:T.purple}}>{l.patterns_found||0} patterns</span>
                    <span style={{fontFamily:MONO,fontSize:11,color:T.t2}}>{l.summary||"Applied"}</span>
                  </div>
                ))}
              </div>
            )}
            <SectionHeader>BACKTEST RUNS</SectionHeader>
            {history.length===0
              ? <EmptyState text="No runs yet."/>
              : history.map(h=>(
                  <div key={h.id} style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:4,
                    padding:"10px 14px",marginBottom:8,display:"grid",
                    gridTemplateColumns:"1fr 80px 80px 80px 80px 100px",gap:10,alignItems:"center"}}>
                    <div>
                      <span style={{fontFamily:MONO,fontSize:12,color:T.text}}>{h.symbol}</span>
                      <span style={{fontFamily:MONO,fontSize:10,color:T.t2,marginLeft:8}}>{h.strategy}</span>
                    </div>
                    <Stat label="TRADES" val={h.total_trades} color={T.text}/>
                    <Stat label="WIN%" val={fmtPct(h.win_rate)} color={T.gold}/>
                    <Stat label="PF" val={fmt(h.profit_factor)} color={T.blue}/>
                    <Stat label="NET" val={fmtPnl(h.net_pnl)} color={h.net_pnl>=0?T.green:T.red}/>
                    <span style={{fontFamily:MONO,fontSize:9,color:T.t2,textAlign:"right"}}>
                      {h.created_at?.slice(0,16)}
                    </span>
                  </div>
                ))
            }
          </div>
        )}
      </div>
    </div>
  );
}

// ── TEST METADATA BANNER ──────────────────────────────────────────────────────
function TestMeta({result}){
  const items=[
    ["SYMBOL",result.symbol],["MARKET",result.market||"—"],
    ["INTERVAL",result.interval],["STRATEGY",result.strategy],
    ["START",result.start_date?.slice(0,10)],["END",result.end_date?.slice(0,10)],
    ["CANDLES",result.candles_used?.toLocaleString()],
    ["WINDOW",result.summary?.random_window?"Random":"Fixed"],
  ];
  return(
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,padding:"10px 14px",marginBottom:14}}>
      <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:8}}>
        <Database size={12} style={{color:T.blue}}/>
        <span style={{fontFamily:MONO,fontSize:9,color:T.blue,letterSpacing:2}}>TEST METADATA</span>
      </div>
      <div style={{display:"flex",gap:20,flexWrap:"wrap"}}>
        {items.map(([l,v])=>(
          <div key={l}>
            <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{l}</div>
            <div style={{fontFamily:MONO,fontSize:11,color:T.text}}>{v||"—"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── SUMMARY CARDS ─────────────────────────────────────────────────────────────
function SummaryCards({summary:s}){
  const pnlPositive = (s.net_pnl||0)>=0;
  const mdd = s.max_drawdown_pct ?? buildMaxDD(null);
  const cards = [
    {label:"NET P&L", val:fmtPnl(s.net_pnl)+" $", color:pnlPositive?T.green:T.red, icon:pnlPositive?<ArrowUpRight size={16}/>:<ArrowDownRight size={16}/>},
    {label:"WIN RATE", val:fmtPct(s.win_rate), color:T.gold},
    {label:"PROFIT FACTOR", val:fmt(s.profit_factor), color:T.blue},
    {label:"MAX DRAWDOWN", val:s.max_drawdown?fmt(s.max_drawdown)+"%":"—", color:T.red},
    {label:"TOTAL TRADES", val:s.total_trades||0, color:T.text},
    {label:"FINAL BALANCE", val:"$"+(s.final_balance||0).toLocaleString(undefined,{maximumFractionDigits:2}), color:pnlPositive?T.green:T.red},
    {label:"TRADES/DAY", val:fmt(s.trades_per_day,1), color:T.t2},
    {label:"WINS/LOSSES", val:`${s.wins||0}/${s.losses||0}`, color:T.text},
  ];
  return(
    <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(150px,1fr))",gap:10}}>
      {cards.map(c=>(
        <div key={c.label} style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,padding:"11px 14px"}}>
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:5}}>
            <span style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1}}>{c.label}</span>
            {c.icon&&<span style={{color:c.color}}>{c.icon}</span>}
          </div>
          <div style={{fontFamily:MONO,fontSize:20,color:c.color,fontWeight:500}}>{c.val}</div>
        </div>
      ))}
    </div>
  );
}

// ── EQUITY CURVE CHART ────────────────────────────────────────────────────────
function EquityCurveChart({data}){
  if(!data?.length) return null;
  const start = data[0]?.equity||0;
  const CustomTooltip=({active,payload,label})=>{
    if(!active||!payload?.length) return null;
    const v=payload[0].value;
    return(
      <div style={{background:T.bg2,border:`1px solid ${T.border}`,borderRadius:4,padding:"8px 12px"}}>
        <div style={{fontFamily:MONO,fontSize:10,color:T.t2,marginBottom:4}}>{label}</div>
        <div style={{fontFamily:MONO,fontSize:13,color:v>=start?T.green:T.red}}>
          ${v?.toLocaleString(undefined,{maximumFractionDigits:2})}
        </div>
        <div style={{fontFamily:MONO,fontSize:10,color:T.t2}}>
          {v>=start?"↑ ":""}{(((v-start)/start)*100).toFixed(2)}%
        </div>
      </div>
    );
  };
  return(
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,padding:"14px 10px 10px"}}>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data} margin={{top:5,right:10,left:0,bottom:0}}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={T.green} stopOpacity={0.35}/>
              <stop offset="95%" stopColor={T.green} stopOpacity={0.03}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={T.border} vertical={false}/>
          <XAxis dataKey="date" tick={{fill:T.t2,fontSize:9,fontFamily:MONO}} tickLine={false}
            interval="preserveStartEnd"/>
          <YAxis tick={{fill:T.t2,fontSize:9,fontFamily:MONO}} tickLine={false} axisLine={false}
            tickFormatter={v=>"$"+v.toLocaleString(undefined,{maximumFractionDigits:0})}/>
          <Tooltip content={<CustomTooltip/>}/>
          <ReferenceLine y={start} stroke={T.t2} strokeDasharray="4 4" strokeWidth={1}/>
          <Area type="monotone" dataKey="equity" stroke={T.green} strokeWidth={1.5}
            fill="url(#eq)" dot={false} activeDot={{r:4,fill:T.green}}/>
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── DRAWDOWN CHART ────────────────────────────────────────────────────────────
function DrawdownChart({data}){
  if(!data?.length) return null;
  return(
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,padding:"14px 10px 10px"}}>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={data} margin={{top:5,right:10,left:0,bottom:0}}>
          <defs>
            <linearGradient id="dd" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={T.red} stopOpacity={0.5}/>
              <stop offset="95%" stopColor={T.red} stopOpacity={0.05}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={T.border} vertical={false}/>
          <XAxis dataKey="date" tick={{fill:T.t2,fontSize:9,fontFamily:MONO}} tickLine={false}
            interval="preserveStartEnd"/>
          <YAxis tick={{fill:T.t2,fontSize:9,fontFamily:MONO}} tickLine={false} axisLine={false}
            tickFormatter={v=>v+"%"}/>
          <Tooltip formatter={(v)=>[v.toFixed(2)+"%","Drawdown"]}
            contentStyle={{background:T.bg2,border:`1px solid ${T.border}`,borderRadius:4,fontFamily:MONO,fontSize:11}}/>
          <Area type="monotone" dataKey="dd" stroke={T.red} strokeWidth={1.5}
            fill="url(#dd)" dot={false}/>
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── DAILY PNL CHART ───────────────────────────────────────────────────────────
function DailyPnlChart({data}){
  if(!data?.length) return null;
  return(
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,padding:"14px 10px 10px"}}>
      <ResponsiveContainer width="100%" height={130}>
        <BarChart data={data} margin={{top:5,right:10,left:0,bottom:0}}>
          <CartesianGrid strokeDasharray="3 3" stroke={T.border} vertical={false}/>
          <XAxis dataKey="date" tick={{fill:T.t2,fontSize:9,fontFamily:MONO}} tickLine={false}
            interval="preserveStartEnd"/>
          <YAxis tick={{fill:T.t2,fontSize:9,fontFamily:MONO}} tickLine={false} axisLine={false}/>
          <Tooltip formatter={(v)=>[fmtPnl(v),"PnL"]}
            contentStyle={{background:T.bg2,border:`1px solid ${T.border}`,borderRadius:4,fontFamily:MONO,fontSize:11}}/>
          <ReferenceLine y={0} stroke={T.border}/>
          <Bar dataKey="pnl" radius={[2,2,0,0]}
            fill={T.green}
            label={false}
            // colour each bar individually
            shape={({x,y,width,height,value})=>(
              <rect x={x} y={value>=0?y:y+height} width={Math.max(width,1)}
                height={Math.abs(height)} fill={value>=0?T.green:T.red} rx={2}/>
            )}/>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── TRADE TABLE ───────────────────────────────────────────────────────────────
function TradeTable({trades,sortField,sortDir,onSort}){
  if(!trades.length) return <EmptyState text="No trades in this page."/>;
  const TH=({f,label})=>(
    <th onClick={()=>onSort(f)}
      style={{padding:"8px 10px",textAlign:"left",cursor:"pointer",userSelect:"none",
        fontFamily:MONO,fontSize:9,color:sortField===f?T.blue:T.t2,letterSpacing:1,
        borderBottom:`1px solid ${T.border}`,background:T.bg2,whiteSpace:"nowrap"}}>
      {label} {sortField===f?(sortDir==="asc"?"↑":"↓"):""}
    </th>
  );

  const exitColor=(r)=>{
    if(!r) return T.t2;
    const rr=r.toLowerCase();
    if(rr.includes("tp")||rr.includes("target")) return T.green;
    if(rr.includes("sl")||rr.includes("stop")&&!rr.includes("trail")) return T.red;
    if(rr.includes("trail")) return T.gold;
    return T.t2;
  };

  return(
    <div style={{overflowX:"auto"}}>
      <table style={{width:"100%",borderCollapse:"collapse",fontSize:11,fontFamily:MONO}}>
        <thead>
          <tr>
            <TH f="side"      label="SIDE"/>
            <TH f="entry"     label="ENTRY"/>
            <TH f="exit"      label="EXIT"/>
            <TH f="pnl"       label="P&L"/>
            <TH f="open_time" label="OPENED"/>
            <TH f="close_time"label="CLOSED"/>
            <TH f="duration"  label="DURATION"/>
            <TH f="exit_reason"label="EXIT REASON"/>
            <TH f="session"   label="SESSION"/>
            <TH f="confidence"label="CONF"/>
            <TH f="smc_score" label="SMC"/>
            <TH f="rr"        label="R:R"/>
          </tr>
        </thead>
        <tbody>
          {trades.map((t,i)=>(
            <tr key={i} style={{background:i%2===0?T.bg3:T.bg2,
              borderBottom:`1px solid ${T.border}`}}>
              <td style={{padding:"7px 10px"}}>
                <span style={{color:t.side==="BUY"?T.green:T.red,fontWeight:600}}>
                  {t.side==="BUY"?"▲":"▼"} {t.side}
                </span>
              </td>
              <td style={{padding:"7px 10px",color:T.text}}>{fmt(t.entry,4)}</td>
              <td style={{padding:"7px 10px",color:T.text}}>{fmt(t.exit,4)}</td>
              <td style={{padding:"7px 10px",color:(t.pnl||0)>=0?T.green:T.red,fontWeight:600}}>
                {fmtPnl(t.pnl)}
              </td>
              <td style={{padding:"7px 10px",color:T.t2,fontSize:10}}>{t.open_time?.slice(0,16)||"—"}</td>
              <td style={{padding:"7px 10px",color:T.t2,fontSize:10}}>{t.close_time?.slice(0,16)||"—"}</td>
              <td style={{padding:"7px 10px",color:T.t2}}>{durStr(t.duration_seconds)}</td>
              <td style={{padding:"7px 10px"}}>
                <span style={{color:exitColor(t.exit_reason),fontSize:10}}>
                  {t.exit_reason||"—"}
                </span>
              </td>
              <td style={{padding:"7px 10px",color:T.cyan,fontSize:10}}>{t.session||"—"}</td>
              <td style={{padding:"7px 10px",color:T.gold}}>{t.confidence?t.confidence+"%":"—"}</td>
              <td style={{padding:"7px 10px",color:T.t2}}>{t.smc_score!=null?`${t.smc_score}/11`:"—"}</td>
              <td style={{padding:"7px 10px",color:T.gold}}>{t.rr?fmt(t.rr,1)+"R":"—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── STRATEGY COMPARISON ───────────────────────────────────────────────────────
function ComparePanel({data}){
  const rows = Object.values(data);
  const metrics = [
    {key:"net_pnl",      label:"NET P&L",     fmt:v=>(v>=0?"+":"")+fmt(v)+" $", better:"high"},
    {key:"win_rate",     label:"WIN RATE",    fmt:fmtPct, better:"high"},
    {key:"profit_factor",label:"PROFIT FACTOR",fmt:fmt,   better:"high"},
    {key:"max_drawdown", label:"MAX DRAWDOWN",fmt:v=>fmt(v)+"%", better:"low"},
    {key:"total_trades", label:"TOTAL TRADES",fmt:v=>v,  better:"high"},
    {key:"trades_per_day",label:"TRADES/DAY", fmt:v=>fmt(v,1), better:"neutral"},
  ];

  // Recharts bar data
  const barData = metrics.map(m=>({
    metric:m.label,
    ...Object.fromEntries(rows.map(r=>[r.label||"?", r[m.key]||0]))
  }));

  const COLORS=[T.green,T.blue,T.gold,T.purple];

  return(
    <div>
      {/* Table */}
      <div style={{overflowX:"auto",marginBottom:18}}>
        <table style={{width:"100%",borderCollapse:"collapse",fontFamily:MONO,fontSize:11}}>
          <thead>
            <tr>
              <th style={{padding:"8px 12px",textAlign:"left",fontFamily:MONO,fontSize:9,
                color:T.t2,borderBottom:`1px solid ${T.border}`,background:T.bg2,letterSpacing:1}}>
                METRIC
              </th>
              {rows.map((r,i)=>(
                <th key={i} style={{padding:"8px 12px",textAlign:"center",fontFamily:MONO,fontSize:9,
                  color:COLORS[i]||T.t2,borderBottom:`1px solid ${T.border}`,background:T.bg2,letterSpacing:1}}>
                  {r.label||"—"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map(m=>{
              const vals = rows.map(r=>r[m.key]??null);
              const best = m.better==="high"?Math.max(...vals.filter(v=>v!=null)):
                           m.better==="low" ?Math.min(...vals.filter(v=>v!=null)):null;
              return(
                <tr key={m.key} style={{borderBottom:`1px solid ${T.border}`}}>
                  <td style={{padding:"8px 12px",color:T.t2,background:T.bg3,fontFamily:MONO,fontSize:10,letterSpacing:1}}>
                    {m.label}
                  </td>
                  {rows.map((r,i)=>{
                    const v=r[m.key]??null;
                    const isBest=best!=null&&v===best;
                    return(
                      <td key={i} style={{padding:"8px 12px",textAlign:"center",
                        background:i%2===0?T.bg3:T.bg2,
                        color:isBest?COLORS[i]||T.text:T.text,
                        fontWeight:isBest?700:400}}>
                        {v!=null?m.fmt(v):"—"}
                        {isBest&&<span style={{fontSize:8,marginLeft:4}}>★</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Net PnL bar chart */}
      <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,padding:"14px 10px 10px"}}>
        <div style={{fontFamily:MONO,fontSize:9,color:T.t2,letterSpacing:2,marginBottom:10}}>NET P&L BY STRATEGY</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={[{
            name:"Net P&L",
            ...Object.fromEntries(rows.map(r=>[r.label||"?",r.net_pnl||0]))
          }]} margin={{top:5,right:10,left:0,bottom:0}}>
            <CartesianGrid strokeDasharray="3 3" stroke={T.border} horizontal={false}/>
            <XAxis dataKey="name" tick={{fill:T.t2,fontSize:9,fontFamily:MONO}}/>
            <YAxis tick={{fill:T.t2,fontSize:9,fontFamily:MONO}} tickLine={false}/>
            <Tooltip contentStyle={{background:T.bg2,border:`1px solid ${T.border}`,fontFamily:MONO,fontSize:11}}/>
            {rows.map((r,i)=>(
              <Bar key={i} dataKey={r.label||"?"} fill={COLORS[i]||T.t2} radius={[3,3,0,0]}/>
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── LEARN RESULT ──────────────────────────────────────────────────────────────
function LearnResult({data:d}){
  return(
    <div style={{background:T.bg3,border:`1px solid ${T.purple}40`,borderRadius:6,padding:16,animation:"slide .25s ease"}}>
      <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
        <CheckCircle size={14} style={{color:T.green}}/>
        <span style={{fontFamily:MONO,fontSize:11,color:T.green,letterSpacing:1}}>
          ANALYSIS COMPLETE — {d.patterns_found||0} PATTERNS FOUND
        </span>
      </div>

      {/* Patterns */}
      {d.patterns&&d.patterns.length>0&&(
        <div style={{marginBottom:14}}>
          <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:8}}>IDENTIFIED PATTERNS</div>
          {d.patterns.map((p,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",gap:8,marginBottom:5,
              fontFamily:MONO,fontSize:11,color:T.text}}>
              <AlertTriangle size={11} style={{color:T.gold,flexShrink:0}}/>
              {p}
            </div>
          ))}
        </div>
      )}

      {/* Config diff */}
      {d.config_changes&&Object.keys(d.config_changes).length>0&&(
        <div>
          <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:8}}>
            CONFIG ADJUSTMENTS APPLIED
          </div>
          <div style={{overflowX:"auto"}}>
            <table style={{width:"100%",borderCollapse:"collapse",fontFamily:MONO,fontSize:11}}>
              <thead>
                <tr>
                  {["PARAMETER","BEFORE","AFTER","REASON"].map(h=>(
                    <th key={h} style={{padding:"6px 10px",textAlign:"left",fontFamily:MONO,
                      fontSize:8,color:T.t2,borderBottom:`1px solid ${T.border}`,
                      background:T.bg2,letterSpacing:1}}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(d.config_changes).map(([k,v],i)=>(
                  <tr key={k} style={{background:i%2===0?T.bg3:T.bg2,borderBottom:`1px solid ${T.border}`}}>
                    <td style={{padding:"6px 10px",color:T.text}}>{k}</td>
                    <td style={{padding:"6px 10px",color:T.red}}>{String(v.before??v.old??v)}</td>
                    <td style={{padding:"6px 10px",color:T.green}}>{String(v.after??v.new??v)}</td>
                    <td style={{padding:"6px 10px",color:T.t2,fontSize:10}}>{v.reason||"Pattern-based"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── DATA BUILDERS ─────────────────────────────────────────────────────────────
function buildEquity(trades, start=10000){
  let bal=start, peak=start;
  const out=[{date:"Start",equity:round(start,2)}];
  trades.forEach(t=>{
    bal+=t.pnl||0;
    peak=Math.max(peak,bal);
    out.push({
      date:t.close_time?.slice(0,10)||"",
      equity:round(bal,2),
    });
  });
  return out;
}

function buildDrawdown(equity){
  let peak=equity[0]?.equity||0;
  return equity.map(p=>{
    peak=Math.max(peak,p.equity);
    const dd=peak>0?round(((peak-p.equity)/peak)*100,2):0;
    return{date:p.date, dd:-dd};
  });
}

function buildDailyPnl(trades){
  const map={};
  trades.forEach(t=>{
    const d=t.close_time?.slice(0,10)||"?";
    map[d]=(map[d]||0)+(t.pnl||0);
  });
  return Object.entries(map).sort(([a],[b])=>a>b?1:-1).map(([date,pnl])=>({date,pnl:round(pnl,2)}));
}

function buildMaxDD(equity){
  if(!equity?.length) return "0.00%";
  let peak=equity[0]?.equity||0, maxDD=0;
  equity.forEach(p=>{ peak=Math.max(peak,p.equity); maxDD=Math.max(maxDD,(peak-p.equity)/peak*100); });
  return maxDD.toFixed(2)+"%";
}

const round=(n,d)=>Math.round(n*10**d)/10**d;

// ── TINY HELPERS ──────────────────────────────────────────────────────────────
const selStyle={background:T.bg2,border:`1px solid ${T.border}`,color:T.text,
  borderRadius:3,padding:"6px 10px",width:"100%",fontFamily:MONO,fontSize:11};
const inpStyle={background:T.bg2,border:`1px solid ${T.border}`,color:T.text,
  borderRadius:3,padding:"6px 10px",width:"100%",fontFamily:MONO,fontSize:11};

function Field({label,children}){
  return(
    <div>
      <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:5}}>{label}</div>
      {children}
    </div>
  );
}

function Stat({label,val,color}){
  return(
    <div style={{textAlign:"center"}}>
      <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{label}</div>
      <div style={{fontFamily:MONO,fontSize:12,color}}>{val}</div>
    </div>
  );
}

function NavBtn({label,disabled,onClick}){
  return(
    <button onClick={onClick} disabled={disabled}
      style={{background:T.bg3,border:`1px solid ${T.border}`,color:disabled?T.t3:T.t2,
        borderRadius:3,padding:"6px 16px",cursor:disabled?"not-allowed":"pointer",
        fontFamily:MONO,fontSize:10,letterSpacing:1}}>
      {label}
    </button>
  );
}

function ChartTitle({children}){
  return(
    <div style={{fontFamily:MONO,fontSize:9,color:T.t2,letterSpacing:2,marginBottom:8}}>{children}</div>
  );
}

function SectionHeader({children}){
  return(
    <div style={{fontFamily:MONO,fontSize:9,color:T.t2,letterSpacing:2,marginBottom:10,
      paddingBottom:6,borderBottom:`1px solid ${T.border}`}}>{children}</div>
  );
}

function EmptyState({text}){
  return(
    <div style={{textAlign:"center",padding:60,color:T.t2,fontFamily:MONO,fontSize:12}}>{text}</div>
  );
}

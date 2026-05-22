/**
 * Backtester.jsx — NexusBot v2
 * Full-featured backtester: equity curve, detailed trade table,
 * strategy comparison, learn-from-mistakes panel, historical metadata.
 * FIX: response body is read exactly once — no "body stream already read" error.
 */
import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../lib/api";
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
  {value:"unified_bot",     label:"SMC Unified Bot"},
  {value:"lean_confluence", label:"Lean Confluence (3-Signal)"},
  {value:"vwap_ema",        label:"VWAP + EMA"},
  {value:"orb_0dte",        label:"ORB / 0DTE"},
  {value:"basic",           label:"Simple MA"},
];

// ── MAIN COMPONENT ────────────────────────────────────────────────────────────
export default function Backtester() {
  // Config
  const [symbol,    setSymbol]   = useState("BTCUSDT");
  const [strategy,  setStrategy] = useState("unified_bot");
  const [days,      setDays]     = useState(30);
  const [balance,   setBalance]  = useState(10000);
  const [fee,       setFee]      = useState(0.04);
  const [slip,      setSlip]     = useState(0.02);
  const [rndWindow, setRndWindow]= useState(false);
  const [trainPct,  setTrainPct] = useState(70);  // % of candles used for training

  // Results
  const [result,    setResult]   = useState(null);
  const [running,   setRunning]  = useState(false);
  const [error,     setError]    = useState(null);
  const [tab,       setTab]      = useState("results");
  const [chartCandles, setChartCandles] = useState([]);

  // Sub-features
  const [history,       setHistory]      = useState([]);
  const [compareData,   setCompare]      = useState(null);
  const [comparing,     setComparing]    = useState(false);
  const [learning,      setLearning]     = useState(false);
  const [learnResult,   setLearnResult]  = useState(null);
  const [learnHistory,  setLearnHistory] = useState([]);
  const [autoLearnNote, setAutoLearnNote]= useState(null);
  const [optimizing,    setOptimizing]   = useState(false);
  const [optResult,     setOptResult]    = useState(null);
  const [sortField,     setSortField]    = useState("open_time");
  const [sortDir,       setSortDir]      = useState("desc");
  const [page,          setPage]         = useState(0);
  const PAGE = 20;

  // Walk-forward
  const [wfDays,    setWfDays]    = useState(120);
  const [wfWindows, setWfWindows] = useState(4);
  const [wfRunning, setWfRunning] = useState(false);
  const [wfResult,  setWfResult]  = useState(null);

  // Apply-config (for suggestions from learn/optimise)
  const [applyingCfg, setApplyingCfg] = useState(false);

  // ── Run backtest ────────────────────────────────────────────────────────────
  const run = async () => {
    setRunning(true); setError(null); setResult(null);
    setCompare(null); setLearnResult(null); setAutoLearnNote(null); setPage(0);
    try {
      const d = await apiFetch("/api/backtest", {
        method:"POST",
        body:JSON.stringify({
          symbol, strategy, period_days:Number(days),
          starting_balance:Number(balance), fee_percent:Number(fee),
          slippage_percent:Number(slip), random_window:rndWindow,
          train_pct: Number(trainPct) / 100,
        }),
      });
      setResult(d);
      setChartCandles(d.candles_chart || []);
      // Show suggestion banner when auto-learn found something (never auto-applied)
      const al = d.auto_learn;
      if (al && al.suggested && Object.keys(al.suggested).length > 0) {
        setAutoLearnNote(al);
      }
      loadHistory();
    } catch(e){ setError(e.message); }
    finally{ setRunning(false); }
  };

  // ── Apply suggested config changes ──────────────────────────────────────────
  const handleApplyConfig = async (changes) => {
    setApplyingCfg(true);
    try {
      await apiFetch("/api/apply-config", {
        method:"POST",
        body:JSON.stringify({ changes }),
      });
      setAutoLearnNote(null);
    } catch(e){ setError(e.message); }
    finally { setApplyingCfg(false); }
  };

  // ── Walk-forward analysis ────────────────────────────────────────────────────
  const handleWalkForward = async () => {
    setWfRunning(true); setWfResult(null); setError(null);
    try {
      const d = await apiFetch("/api/walkforward", {
        method:"POST",
        body:JSON.stringify({
          symbol, strategy,
          period_days:Number(wfDays), n_windows:Number(wfWindows),
          train_pct:Number(trainPct)/100,
          starting_balance:Number(balance),
          fee_percent:Number(fee), slippage_percent:Number(slip),
        }),
      });
      setWfResult(d);
    } catch(e){ setError(e.message); }
    finally { setWfRunning(false); }
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

  // ── Parameter grid search ────────────────────────────────────────────────────
  const handleOptimize = async () => {
    setOptimizing(true); setOptResult(null);
    try {
      const d = await apiFetch("/api/optimize", {
        method: "POST",
        body: JSON.stringify({
          symbol, period_days: Number(days),
          starting_balance: Number(balance),
          fee_percent: Number(fee),
          slippage_percent: Number(slip),
        }),
      });
      setOptResult(d);
    } catch(e) {
      setError(e.message);
    } finally {
      setOptimizing(false);
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
                {["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT",
                  "XRPUSDT","ADAUSDT","AVAXUSDT","DOGEUSDT",
                  "DOTUSDT","LINKUSDT","LTCUSDT","UNIUSDT",
                  "ATOMUSDT","NEARUSDT","APTUSDT","ARBUSDT",
                ].map(s=><option key={s} value={s}>{s}</option>)}
              </optgroup>
              <optgroup label="Forex">
                {["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD",
                  "NZDUSD","USDCHF","EURGBP","EURJPY","GBPJPY",
                  "AUDCAD","AUDJPY","CADJPY","CHFJPY",
                ].map(s=><option key={s} value={s}>{s}</option>)}
              </optgroup>
              <optgroup label="Stocks &amp; ETFs">
                {["AAPL","TSLA","NVDA","MSFT","AMZN","SPY",
                  "GOOGL","META","NFLX","AMD","QQQ",
                  "JPM","BAC","V","MA",
                ].map(s=><option key={s} value={s}>{s}</option>)}
              </optgroup>
              <optgroup label="Commodities">
                {["XAUUSD","XAGUSD","USOIL","UKOIL","NATGAS","COPPER"].map(s=><option key={s} value={s}>{s}</option>)}
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
          <Field label="TRAIN SPLIT (%)">
            <select value={trainPct} onChange={e=>setTrainPct(Number(e.target.value))} style={selStyle}>
              {[50,60,70,80].map(v=><option key={v} value={v}>{v}% train / {100-v}% test</option>)}
            </select>
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

      {/* Auto-learn notification */}
      {autoLearnNote&&(
        <div style={{margin:"0 20px 12px",background:`${T.purple}12`,border:`1px solid ${T.purple}44`,
          borderRadius:5,padding:"9px 14px",display:"flex",alignItems:"flex-start",gap:10,animation:"slide .25s ease"}}>
          <Brain size={14} style={{color:T.purple,flexShrink:0,marginTop:1}}/>
          <div style={{flex:1}}>
            <span style={{fontFamily:MONO,fontSize:10,color:T.purple,letterSpacing:2}}>
              AUTO-LEARN SUGGESTION · {Object.keys(autoLearnNote.suggested||{}).length} param change{Object.keys(autoLearnNote.suggested||{}).length!==1?"s":""} recommended
            </span>
            <div style={{marginTop:4,display:"flex",flexWrap:"wrap",gap:6,alignItems:"center"}}>
              {Object.entries(autoLearnNote.suggested||{}).map(([k,v])=>(
                <span key={k} style={{fontFamily:MONO,fontSize:9,background:`${T.purple}18`,
                  border:`1px solid ${T.purple}33`,borderRadius:3,padding:"2px 7px",color:T.purple}}>
                  {k.replace(/_/g," ")} → {String(v)}
                </span>
              ))}
              <button onClick={()=>handleApplyConfig(autoLearnNote.suggested||{})}
                disabled={applyingCfg}
                style={{marginLeft:6,background:`${T.purple}28`,border:`1px solid ${T.purple}66`,
                  color:T.purple,borderRadius:3,padding:"3px 12px",cursor:"pointer",
                  fontFamily:MONO,fontSize:9,letterSpacing:1}}>
                {applyingCfg?"APPLYING…":"✓ APPLY"}
              </button>
            </div>
          </div>
          <button onClick={()=>setAutoLearnNote(null)}
            style={{background:"none",border:"none",color:T.t2,cursor:"pointer",fontSize:14,lineHeight:1,flexShrink:0}}>×</button>
        </div>
      )}

      {/* Tabs */}
      <div style={{margin:"0 20px",borderBottom:`1px solid ${T.border}`,display:"flex",gap:0}}>
        {["results","chart","trades","compare","learn","walkforward","history"].map(t=>(
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
                {/* Out-of-sample validation panel */}
                <OOSPanel summary={summary}/>
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

        {/* CHART TAB */}
        {tab==="chart"&&(
          !result
            ? <EmptyState text="Run a backtest to see the price chart."/>
            : <div style={{animation:"slide .25s ease"}}>
                <TestMeta result={result}/>
                <BacktestChart candles={chartCandles} trades={trades} symbol={result.symbol}/>
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

            {/* ── Learn From Mistakes ── */}
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
                    <br/>
                    <span style={{fontSize:11,color:T.purple}}>
                      ✦ Also runs automatically every time you finish a backtest.
                    </span>
                  </p>
                </div>
                <button onClick={handleRunLearn} disabled={learning}
                  style={{background:`${T.purple}18`,border:`1px solid ${T.purple}44`,color:T.purple,
                    borderRadius:4,padding:"9px 20px",cursor:"pointer",fontFamily:MONO,fontSize:11,
                    letterSpacing:1,whiteSpace:"nowrap",flexShrink:0,display:"flex",alignItems:"center",gap:6}}>
                  {learning
                    ?<><div style={{width:11,height:11,border:`2px solid ${T.t2}`,borderTop:`2px solid ${T.purple}`,borderRadius:"50%",animation:"spin 1s linear infinite"}}/>ANALYSING…</>
                    :<><Brain size={12}/>ANALYSE &amp; APPLY</>}
                </button>
              </div>
            </div>
            {learnResult&&<LearnResult data={learnResult} onApply={handleApplyConfig} applying={applyingCfg}/>}

            {/* ── Parameter Grid Search ── */}
            <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,padding:16,marginTop:20,marginBottom:16}}>
              <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",gap:16}}>
                <div>
                  <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:8}}>
                    <Zap size={16} style={{color:T.cyan}}/>
                    <span style={{fontFamily:MONO,fontSize:12,color:T.cyan,letterSpacing:2}}>
                      PARAMETER OPTIMISER
                    </span>
                  </div>
                  <p style={{margin:0,fontSize:13,color:T.t2,lineHeight:1.65,maxWidth:520}}>
                    Runs a full grid search across <strong style={{color:T.text}}>60 combinations</strong> of
                    confluence threshold, risk/reward ratio, and displacement body ratio — using
                    the current symbol &amp; time window. Automatically applies the best-scoring
                    parameters to your bot config.
                  </p>
                </div>
                <button onClick={handleOptimize} disabled={optimizing}
                  style={{background:`${T.cyan}12`,border:`1px solid ${T.cyan}44`,color:T.cyan,
                    borderRadius:4,padding:"9px 20px",cursor:"pointer",fontFamily:MONO,fontSize:11,
                    letterSpacing:1,whiteSpace:"nowrap",flexShrink:0,display:"flex",alignItems:"center",gap:6}}>
                  {optimizing
                    ?<><div style={{width:11,height:11,border:`2px solid ${T.t2}`,borderTop:`2px solid ${T.cyan}`,borderRadius:"50%",animation:"spin 1s linear infinite"}}/>OPTIMISING…</>
                    :<><Zap size={12}/>RUN OPTIMISER</>}
                </button>
              </div>
            </div>
            {optResult&&<OptimizeResult data={optResult} onApply={handleApplyConfig} applying={applyingCfg}/>}

          </div>
        )}

        {/* WALK-FORWARD TAB */}
        {tab==="walkforward"&&(
          <div style={{animation:"slide .25s ease"}}>
            <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,padding:16,marginBottom:16}}>
              <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",gap:16,flexWrap:"wrap"}}>
                <div>
                  <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:8}}>
                    <TrendingUp size={16} style={{color:T.cyan}}/>
                    <span style={{fontFamily:MONO,fontSize:12,color:T.cyan,letterSpacing:2}}>WALK-FORWARD ANALYSIS</span>
                  </div>
                  <p style={{margin:0,fontSize:13,color:T.t2,lineHeight:1.65,maxWidth:540}}>
                    Splits history into <strong style={{color:T.text}}>N rolling windows</strong>.
                    {strategy==="lean_confluence"
                      ? <> <strong style={{color:T.green}}>Lean Confluence</strong> has no free parameters — each window runs directly on out-of-sample candles. Tells you whether the fixed signal set is stable across time.</>
                      : <> Each window: grid-search best params on the <em>in-sample</em> portion, then apply them to the <em>out-of-sample</em> portion. Tells you whether the edge is stable or curve-fitted.</>
                    }
                  </p>
                  <div style={{marginTop:8,fontSize:11,color:T.t2,fontFamily:MONO}}>
                    STRATEGY: <span style={{color:T.cyan}}>{STRATEGIES.find(s=>s.value===strategy)?.label||strategy}</span>
                    &nbsp;·&nbsp;SYMBOL: <span style={{color:T.cyan}}>{symbol}</span>
                  </div>
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:8,minWidth:200}}>
                  <Field label="TOTAL PERIOD (DAYS)">
                    <select value={wfDays} onChange={e=>setWfDays(Number(e.target.value))} style={selStyle}>
                      {[60,90,120,180,240,365].map(d=><option key={d} value={d}>{d} days</option>)}
                    </select>
                  </Field>
                  <Field label="NUMBER OF WINDOWS">
                    <select value={wfWindows} onChange={e=>setWfWindows(Number(e.target.value))} style={selStyle}>
                      {[2,3,4,5,6].map(n=><option key={n} value={n}>{n} windows</option>)}
                    </select>
                  </Field>
                  <button onClick={handleWalkForward} disabled={wfRunning}
                    style={{background:`${T.cyan}12`,border:`1px solid ${T.cyan}44`,color:T.cyan,
                      borderRadius:4,padding:"9px 20px",cursor:"pointer",fontFamily:MONO,
                      fontSize:11,letterSpacing:1,display:"flex",alignItems:"center",gap:6,marginTop:4}}>
                    {wfRunning
                      ?<><div style={{width:11,height:11,border:`2px solid ${T.t2}`,borderTop:`2px solid ${T.cyan}`,borderRadius:"50%",animation:"spin 1s linear infinite"}}/>RUNNING…</>
                      :<><TrendingUp size={12}/>RUN WALK-FORWARD</>}
                  </button>
                </div>
              </div>
            </div>
            {wfResult&&<WalkForwardResult data={wfResult} onApply={handleApplyConfig} applying={applyingCfg}/>}
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
            <TH f="confluence" label="SIGNALS"/>
            <TH f="sl_pct"    label="SL%"/>
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
              <td style={{padding:"7px 10px",color:T.cyan}}>
                {t.confluence>0?`${t.confluence}/9`:"—"}
              </td>
              <td style={{padding:"7px 10px",color:T.t2}}>{t.sl_pct?fmt(t.sl_pct,2)+"%":"—"}</td>
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
function LearnResult({data:d, onApply, applying}){
  // config_changes may be "suggested" (not applied) when auto_apply=false
  const changes  = d.config_changes || d.suggested || {};
  const isApplied = d.applied === true;
  const hasSuggestions = !isApplied && Object.keys(changes).length > 0;

  return(
    <div style={{background:T.bg3,border:`1px solid ${T.purple}40`,borderRadius:6,padding:16,animation:"slide .25s ease"}}>
      <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
        <CheckCircle size={14} style={{color:T.green}}/>
        <span style={{fontFamily:MONO,fontSize:11,color:T.green,letterSpacing:1}}>
          ANALYSIS COMPLETE — {d.patterns_found||0} PATTERNS FOUND
        </span>
        {isApplied&&(
          <span style={{marginLeft:"auto",fontFamily:MONO,fontSize:9,
            background:`${T.green}18`,border:`1px solid ${T.green}44`,
            borderRadius:3,padding:"2px 8px",color:T.green}}>APPLIED</span>
        )}
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

      {/* Config changes / suggestions */}
      {Object.keys(changes).length>0&&(
        <div>
          <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8}}>
            <span style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2}}>
              {isApplied?"CONFIG ADJUSTMENTS APPLIED":"SUGGESTED CONFIG CHANGES"}
            </span>
            {hasSuggestions&&onApply&&(
              <button onClick={()=>onApply(
                  // normalise: extract "after" value if it's an object {before,after}
                  Object.fromEntries(
                    Object.entries(changes).map(([k,v])=>[k, typeof v==="object"&&v!==null?(v.after??v.new??v):v])
                  )
                )}
                disabled={applying}
                style={{marginLeft:"auto",background:`${T.purple}22`,border:`1px solid ${T.purple}66`,
                  color:T.purple,borderRadius:3,padding:"4px 14px",cursor:"pointer",
                  fontFamily:MONO,fontSize:9,letterSpacing:1}}>
                {applying?"APPLYING…":"✓ APPLY SUGGESTION"}
              </button>
            )}
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
                {Object.entries(changes).map(([k,v],i)=>(
                  <tr key={k} style={{background:i%2===0?T.bg3:T.bg2,borderBottom:`1px solid ${T.border}`}}>
                    <td style={{padding:"6px 10px",color:T.text}}>{k}</td>
                    <td style={{padding:"6px 10px",color:T.red}}>
                      {typeof v==="object"&&v!==null?String(v.before??v.old??"—"):"—"}
                    </td>
                    <td style={{padding:"6px 10px",color:isApplied?T.green:T.gold}}>
                      {typeof v==="object"&&v!==null?String(v.after??v.new??v):String(v)}
                    </td>
                    <td style={{padding:"6px 10px",color:T.t2,fontSize:10}}>
                      {(typeof v==="object"&&v!==null&&v.reason)||"Pattern-based"}
                    </td>
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

// ── OPTIMIZE RESULT ───────────────────────────────────────────────────────────
function OptimizeResult({ data: d, onApply, applying }) {
  const paramLabels = {
    confluence_min:  "Confluence",
    risk_reward:     "Risk/Reward",
    disp_body_ratio: "Disp Body",
    atr_multiplier:  "ATR Mult",
  };
  return (
    <div style={{background:T.bg3,border:`1px solid ${T.cyan}40`,borderRadius:6,padding:16,animation:"slide .25s ease"}}>
      <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12,flexWrap:"wrap"}}>
        <CheckCircle size={14} style={{color:T.green}}/>
        <span style={{fontFamily:MONO,fontSize:11,color:T.green,letterSpacing:1}}>
          OPTIMISATION COMPLETE — {d.combos_tested} COMBINATIONS TESTED
        </span>
        {d.applied&&(
          <span style={{fontFamily:MONO,fontSize:9,
            background:`${T.green}18`,border:`1px solid ${T.green}44`,
            borderRadius:3,padding:"2px 8px",color:T.green}}>
            PARAMS APPLIED
          </span>
        )}
        {!d.applied&&d.suggested_params&&onApply&&(
          <button onClick={()=>onApply(d.suggested_params)} disabled={applying}
            style={{marginLeft:"auto",background:`${T.cyan}20`,border:`1px solid ${T.cyan}66`,
              color:T.cyan,borderRadius:3,padding:"4px 14px",cursor:"pointer",
              fontFamily:MONO,fontSize:9,letterSpacing:1}}>
            {applying?"APPLYING…":"✓ APPLY SUGGESTION"}
          </button>
        )}
      </div>

      {/* Best result highlight */}
      {d.best&&(
        <div style={{background:`${T.cyan}08`,border:`1px solid ${T.cyan}33`,borderRadius:5,
          padding:"12px 14px",marginBottom:14}}>
          <div style={{fontFamily:MONO,fontSize:8,color:T.cyan,letterSpacing:2,marginBottom:10}}>
            BEST CONFIGURATION — SCORE {d.best.score}
          </div>
          <div style={{display:"flex",flexWrap:"wrap",gap:10,marginBottom:10}}>
            {Object.entries(d.best.params).map(([k,v])=>(
              <div key={k} style={{background:T.bg2,border:`1px solid ${T.border}`,borderRadius:4,padding:"6px 12px"}}>
                <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:3}}>
                  {paramLabels[k]||k.replace(/_/g," ").toUpperCase()}
                </div>
                <div style={{fontFamily:MONO,fontSize:14,color:T.cyan,fontWeight:600}}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{display:"flex",gap:20,flexWrap:"wrap"}}>
            <div>
              <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>TRADES</div>
              <div style={{fontFamily:MONO,fontSize:12,color:T.text}}>{d.best.total_trades}</div>
            </div>
            <div>
              <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>WIN RATE</div>
              <div style={{fontFamily:MONO,fontSize:12,color:T.gold}}>{d.best.win_rate}%</div>
            </div>
            <div>
              <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>PROFIT FACTOR</div>
              <div style={{fontFamily:MONO,fontSize:12,color:T.blue}}>{d.best.profit_factor}</div>
            </div>
            <div>
              <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>NET P&L</div>
              <div style={{fontFamily:MONO,fontSize:12,color:d.best.net_pnl>=0?T.green:T.red}}>
                {d.best.net_pnl>=0?"+":""}{d.best.net_pnl}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Top 5 table */}
      {d.top5?.length>1&&(
        <div>
          <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:8}}>TOP 5 COMBINATIONS</div>
          <div style={{overflowX:"auto"}}>
            <table style={{width:"100%",borderCollapse:"collapse",fontFamily:MONO,fontSize:10}}>
              <thead>
                <tr>
                  {["#","Confluence","R:R","Disp Body","Trades","Win %","PF","Net P&L","Score"].map(h=>(
                    <th key={h} style={{padding:"6px 10px",textAlign:h==="#"?"center":"right",
                      fontFamily:MONO,fontSize:8,color:T.t2,borderBottom:`1px solid ${T.border}`,
                      background:T.bg2,letterSpacing:1,whiteSpace:"nowrap"}}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.top5.map((r,i)=>(
                  <tr key={i} style={{background:i%2===0?T.bg3:T.bg2,borderBottom:`1px solid ${T.border}`,
                    opacity:i===0?1:0.75}}>
                    <td style={{padding:"6px 10px",textAlign:"center",color:i===0?T.cyan:T.t2,fontWeight:i===0?700:400}}>
                      {i===0?"★":i+1}
                    </td>
                    <td style={{padding:"6px 10px",textAlign:"right",color:T.text}}>{r.params.confluence_min??"-"}</td>
                    <td style={{padding:"6px 10px",textAlign:"right",color:T.text}}>{r.params.risk_reward??"-"}</td>
                    <td style={{padding:"6px 10px",textAlign:"right",color:T.text}}>{r.params.disp_body_ratio??"-"}</td>
                    <td style={{padding:"6px 10px",textAlign:"right",color:T.text}}>{r.total_trades}</td>
                    <td style={{padding:"6px 10px",textAlign:"right",color:T.gold}}>{r.win_rate}%</td>
                    <td style={{padding:"6px 10px",textAlign:"right",color:T.blue}}>{r.profit_factor}</td>
                    <td style={{padding:"6px 10px",textAlign:"right",
                      color:r.net_pnl>=0?T.green:T.red}}>
                      {r.net_pnl>=0?"+":""}{r.net_pnl}
                    </td>
                    <td style={{padding:"6px 10px",textAlign:"right",
                      color:i===0?T.cyan:T.t2,fontWeight:i===0?700:400}}>{r.score}</td>
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

// ── OUT-OF-SAMPLE PANEL ───────────────────────────────────────────────────────
function OOSPanel({summary:s}){
  if(!s||!s.test_summary) return null;
  const tr   = s.train_summary || {};
  const te   = s.test_summary  || {};
  const warn = s.low_sample_warning;
  const msg  = s.low_sample_msg;
  const split = s.split_date || "—";
  const tp    = s.train_pct != null ? Math.round(s.train_pct * 100) : 70;

  const MetaBox = ({label, m, accent}) => (
    <div style={{flex:1,minWidth:200,background:T.bg2,border:`1px solid ${accent}44`,
      borderRadius:5,padding:"12px 14px"}}>
      <div style={{fontFamily:MONO,fontSize:8,color:accent,letterSpacing:2,marginBottom:10}}>{label}</div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
        {[
          ["TRADES",        m.total_trades ?? "—",                                                T.text],
          ["WIN RATE",      (m.total_trades||0)>=1 ? fmtPct(m.win_rate)    : "—",                T.gold],
          ["PROFIT FACTOR", (m.total_trades||0)>=1 ? fmt(m.profit_factor)  : "—",                T.blue],
          ["NET P&L",       (m.total_trades||0)>=1 ? fmtPnl(m.net_pnl)+"$": "—", (m.net_pnl||0)>=0?T.green:T.red],
        ].map(([lbl,val,col])=>(
          <div key={lbl}>
            <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{lbl}</div>
            <div style={{fontFamily:MONO,fontSize:14,color:col,fontWeight:500}}>{val}</div>
          </div>
        ))}
      </div>
    </div>
  );

  return(
    <div style={{marginBottom:14,background:T.bg3,border:`1px solid ${T.border}`,
      borderRadius:6,padding:"12px 14px"}}>
      <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:10}}>
        <Calendar size={12} style={{color:T.cyan}}/>
        <span style={{fontFamily:MONO,fontSize:9,color:T.cyan,letterSpacing:2}}>
          OUT-OF-SAMPLE VALIDATION
        </span>
        <span style={{fontFamily:MONO,fontSize:9,color:T.t2,marginLeft:8}}>
          Split: {tp}% train / {100-tp}% test · Split date: {split}
        </span>
      </div>
      <div style={{display:"flex",gap:10,flexWrap:"wrap"}}>
        <MetaBox label="TRAINING (IN-SAMPLE)"  m={tr} accent={T.blue}/>
        <MetaBox label="TEST (OUT-OF-SAMPLE)"  m={te} accent={warn?T.gold:T.green}/>
      </div>
      {warn&&(
        <div style={{marginTop:10,background:`${T.gold}12`,border:`1px solid ${T.gold}44`,
          borderRadius:4,padding:"8px 12px",display:"flex",alignItems:"center",gap:8}}>
          <AlertTriangle size={13} style={{color:T.gold,flexShrink:0}}/>
          <span style={{fontFamily:MONO,fontSize:10,color:T.gold}}>
            {msg||"Insufficient test trades — win rate and profit factor may not be statistically meaningful."}
          </span>
        </div>
      )}
    </div>
  );
}

// ── WALK-FORWARD RESULT ───────────────────────────────────────────────────────
function WalkForwardResult({data:d, onApply, applying}){
  if(!d) return null;

  // Backend returns aggregate metrics under d.aggregate, per-window under d.windows
  const agg     = d.aggregate || {};
  const verdict = agg.verdict;
  const isLean  = d.strategy === "lean_confluence";
  const VERDICT_COLOR = {STABLE:T.green, MIXED:T.gold, UNSTABLE:T.red};
  const vc = VERDICT_COLOR[verdict] || T.t2;

  // For non-lean strategies: derive "best overall params" from the window
  // that produced the highest OOS profit factor, then offer Apply.
  const bestParamsOverall = !isLean && d.windows?.length > 0
    ? (()=>{
        const best = d.windows.reduce((a,b)=>
          ((b.oos?.profit_factor)||0) > ((a.oos?.profit_factor)||0) ? b : a,
          d.windows[0]
        );
        const p = best?.best_is_params;
        return p && Object.keys(p).length > 0 ? p : null;
      })()
    : null;

  return(
    <div style={{background:T.bg3,border:`1px solid ${T.cyan}44`,borderRadius:6,padding:16,
      animation:"slide .25s ease"}}>

      {/* Header + verdict badge */}
      <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:16,flexWrap:"wrap"}}>
        <CheckCircle size={14} style={{color:T.green}}/>
        <span style={{fontFamily:MONO,fontSize:11,color:T.green,letterSpacing:1}}>
          WALK-FORWARD COMPLETE — {d.n_windows||0} WINDOWS
          {d.strategy && <span style={{color:T.t2}}> · {d.strategy.replace(/_/g," ").toUpperCase()}</span>}
        </span>
        <span style={{marginLeft:"auto",fontFamily:MONO,fontSize:11,letterSpacing:2,
          background:`${vc}18`,border:`1px solid ${vc}55`,borderRadius:4,padding:"4px 14px",
          color:vc,fontWeight:700}}>
          {verdict||"—"}
        </span>
      </div>

      {/* Aggregate stats — sourced from d.aggregate */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(130px,1fr))",gap:8,marginBottom:16}}>
        {[
          ["WINDOWS",        d.n_windows||0,                                              T.text],
          ["PROFITABLE",     `${agg.windows_profitable||0}/${agg.windows_total||d.n_windows||0}`, T.green],
          ["CONSISTENCY",    fmtPct(agg.consistency_pct),                                vc],
          ["OOS PROF FACTOR",fmt(agg.profit_factor),                                     T.blue],
          ["OOS WIN RATE",   fmtPct(agg.win_rate),                                       T.gold],
          ["TOTAL OOS TRADES",agg.total_trades||0,                                       T.text],
        ].map(([lbl,val,col])=>(
          <div key={lbl} style={{background:T.bg2,border:`1px solid ${T.border}`,borderRadius:4,padding:"8px 12px"}}>
            <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:3}}>{lbl}</div>
            <div style={{fontFamily:MONO,fontSize:14,color:col,fontWeight:500}}>{val}</div>
          </div>
        ))}
      </div>

      {/* Per-window table */}
      {d.windows?.length>0&&(
        <div style={{overflowX:"auto",marginBottom:16}}>
          <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:8}}>PER-WINDOW RESULTS</div>
          <table style={{width:"100%",borderCollapse:"collapse",fontFamily:MONO,fontSize:10}}>
            <thead>
              <tr>
                {["WIN#","TRAIN PERIOD","TEST PERIOD","IS SCORE","OOS PF","OOS WIN%","OOS TRADES","PARAMS","OUTCOME"].map(h=>(
                  <th key={h} style={{padding:"6px 10px",textAlign:"left",fontFamily:MONO,fontSize:8,
                    color:T.t2,borderBottom:`1px solid ${T.border}`,background:T.bg2,
                    letterSpacing:1,whiteSpace:"nowrap"}}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.windows.map((w,i)=>{
                // Backend field names: train_start, train_end, test_end, is_score, best_is_params, oos{}
                const oospf     = w.oos?.profit_factor ?? 0;
                const profitable = oospf > 1;
                const oc = profitable ? T.green : T.red;
                const bp = w.best_is_params || {};
                const bpStr = Object.keys(bp).length > 0
                  ? Object.entries(bp).map(([k,v])=>`${k.replace("_"," ")}=${v}`).join(" ")
                  : isLean ? "fixed" : "—";
                return(
                  <tr key={i} style={{background:i%2===0?T.bg3:T.bg2,borderBottom:`1px solid ${T.border}`}}>
                    <td style={{padding:"6px 10px",color:T.t2,textAlign:"center"}}>{w.window||i+1}</td>
                    <td style={{padding:"6px 10px",color:T.t2,fontSize:9,whiteSpace:"nowrap"}}>
                      {(w.train_start||"—").slice(0,10)} → {(w.train_end||"—").slice(0,10)}
                    </td>
                    <td style={{padding:"6px 10px",color:T.t2,fontSize:9,whiteSpace:"nowrap"}}>
                      {(w.train_end||"—").slice(0,10)} → {(w.test_end||"—").slice(0,10)}
                    </td>
                    <td style={{padding:"6px 10px",color:T.blue}}>{fmt(w.is_score,3)}</td>
                    <td style={{padding:"6px 10px",color:oc,fontWeight:profitable?700:400}}>{fmt(oospf)}</td>
                    <td style={{padding:"6px 10px",color:T.gold}}>{fmtPct(w.oos?.win_rate)}</td>
                    <td style={{padding:"6px 10px",color:T.text}}>{w.oos?.total_trades||0}</td>
                    <td style={{padding:"6px 10px",color:T.cyan,fontSize:9}}>{bpStr}</td>
                    <td style={{padding:"6px 10px"}}>
                      <span style={{fontFamily:MONO,fontSize:8,color:oc,
                        background:`${oc}18`,border:`1px solid ${oc}44`,
                        borderRadius:3,padding:"2px 7px"}}>
                        {profitable?"PROFIT":"LOSS"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Low sample warning */}
      {agg.low_sample_warning&&(
        <div style={{background:`${T.gold}12`,border:`1px solid ${T.gold}44`,borderRadius:4,
          padding:"8px 12px",display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
          <AlertTriangle size={13} style={{color:T.gold,flexShrink:0}}/>
          <span style={{fontFamily:MONO,fontSize:10,color:T.gold}}>
            Low OOS trade count — results may not be statistically meaningful.
          </span>
        </div>
      )}

      {/* Lean confluence info note */}
      {isLean&&(
        <div style={{background:`${T.green}08`,border:`1px solid ${T.green}33`,borderRadius:4,
          padding:"8px 12px",fontFamily:MONO,fontSize:10,color:T.green,marginBottom:12}}>
          ✓ Lean Confluence uses fixed parameters (R:R=2.0, Risk=1%, no grid search).
          The edge shown is purely from signal quality — not from curve-fitting.
        </div>
      )}

      {/* Best params overall + Apply button (unified_bot only) */}
      {bestParamsOverall&&onApply&&(
        <div style={{background:`${T.cyan}08`,border:`1px solid ${T.cyan}33`,borderRadius:5,
          padding:"12px 14px",display:"flex",alignItems:"center",gap:12,flexWrap:"wrap"}}>
          <div style={{flex:1}}>
            <div style={{fontFamily:MONO,fontSize:8,color:T.cyan,letterSpacing:2,marginBottom:6}}>
              BEST OOS WINDOW PARAMS — APPLY TO BOT CONFIG
            </div>
            <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
              {Object.entries(bestParamsOverall).map(([k,v])=>(
                <span key={k} style={{fontFamily:MONO,fontSize:9,background:`${T.cyan}18`,
                  border:`1px solid ${T.cyan}33`,borderRadius:3,padding:"2px 8px",color:T.cyan}}>
                  {k.replace(/_/g," ")} = {v}
                </span>
              ))}
            </div>
          </div>
          <button onClick={()=>onApply(bestParamsOverall)} disabled={applying}
            style={{background:`${T.cyan}20`,border:`1px solid ${T.cyan}66`,color:T.cyan,
              borderRadius:4,padding:"8px 18px",cursor:"pointer",fontFamily:MONO,
              fontSize:10,letterSpacing:1,whiteSpace:"nowrap",flexShrink:0}}>
            {applying?"APPLYING…":"✓ APPLY TO BOT CONFIG"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── BACKTEST PRICE CHART ──────────────────────────────────────────────────────
function parseTradeTime(str) {
  if (!str) return 0;
  // "YYYY-MM-DD HH:MM" or "YYYY-MM-DD HH:MM:SS"
  const d = new Date(str.replace(" ", "T") + (str.length <= 16 ? ":00Z" : "Z"));
  return isNaN(d.getTime()) ? 0 : d.getTime();
}

function BacktestChart({ candles, trades, symbol }) {
  // ── ALL hooks must be called before any early return ──────────────────
  const [hovered,       setHovered]       = React.useState(null);
  const [annotationsOn, setAnnotationsOn] = React.useState(false);

  if (!candles?.length) return (
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:5,
      padding:40,textAlign:"center",color:T.t2,fontFamily:MONO,fontSize:12}}>
      Chart data unavailable for this run.
    </div>
  );

  // Map trades to chart entries/exits (include sl/tp for annotations)
  const tradeMarkers = trades.map((t, i) => {
    const tEntry = parseTradeTime(t.open_time  || t.entry_time);
    const tExit  = parseTradeTime(t.close_time || t.exit_time);
    const win = (t.pnl || 0) > 0;
    return {
      id: i, tEntry, tExit,
      entry: t.entry, exit: t.exit,
      sl: t.sl, tp: t.tp,
      side: t.side, pnl: t.pnl, win,
      reason:  t.exit_reason || t.reason || "—",
      session: t.session || "—",
      confluence: t.confluence || 0,
    };
  });

  const minT  = candles[0]?.t || 0;
  const maxT  = candles[candles.length - 1]?.t || 1;
  const tSpan = maxT - minT || 1;

  // Price range: include all OHLC + SL/TP levels from trades
  const allPrices = candles.flatMap(c => [c.h, c.l]);
  tradeMarkers.forEach(m => {
    if (m.sl) allPrices.push(m.sl);
    if (m.tp) allPrices.push(m.tp);
  });
  const minP  = Math.min(...allPrices) * 0.9995;
  const maxP  = Math.max(...allPrices) * 1.0005;
  const pSpan = maxP - minP || 1;

  // SVG dimensions
  const W = 900; const H = 380;
  const PAD = { top: 20, right: 20, bottom: 36, left: 72 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top  - PAD.bottom;

  const tx = t => PAD.left + ((t - minT) / tSpan) * cW;
  const ty = p => PAD.top  + cH - ((p - minP) / pSpan) * cH;

  // Candlestick geometry
  const spacing   = cW / candles.length;
  const bodyW     = Math.max(1, spacing * 0.7);
  const halfBody  = bodyW / 2;

  // Y-axis ticks
  const yTicks = 5;
  const yTickVals = Array.from({length: yTicks}, (_, i) =>
    minP + (pSpan * i / (yTicks - 1))
  );

  // X-axis ticks
  const xTickStep = Math.max(1, Math.floor(candles.length / 6));
  const xTicks    = candles.filter((_, i) => i % xTickStep === 0);

  const fmtLbl = v => v >= 1000
    ? v.toLocaleString("en", {maximumFractionDigits: 0})
    : v < 0.01 ? v.toExponential(2)
    : v.toFixed(v < 1 ? 5 : 2);

  return (
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,
      padding:"16px 10px 10px",marginBottom:14}}>
      {/* Header + legend + annotation toggle */}
      <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:12,padding:"0 10px",flexWrap:"wrap"}}>
        <span style={{fontFamily:MONO,fontSize:10,color:T.blue,letterSpacing:2}}>
          CANDLESTICK CHART — {symbol}
        </span>
        <span style={{fontFamily:MONO,fontSize:9,color:T.t2}}>
          {candles.length} candles
        </span>
        <div style={{marginLeft:"auto",display:"flex",gap:12,alignItems:"center",flexWrap:"wrap"}}>
          <span style={{fontFamily:MONO,fontSize:9,color:T.green}}>▲ BUY</span>
          <span style={{fontFamily:MONO,fontSize:9,color:T.red}}>▼ SELL</span>
          <span style={{fontFamily:MONO,fontSize:9,color:T.green}}>◆ Win</span>
          <span style={{fontFamily:MONO,fontSize:9,color:T.red}}>◆ Loss</span>
          <button onClick={() => setAnnotationsOn(a => !a)}
            style={{fontFamily:MONO,fontSize:9,letterSpacing:1,
              background: annotationsOn ? `${T.gold}22` : T.bg2,
              border: `1px solid ${annotationsOn ? T.gold : T.border}`,
              color: annotationsOn ? T.gold : T.t2,
              borderRadius:3,padding:"3px 10px",cursor:"pointer"}}>
            {annotationsOn ? "HIDE ANNOTATIONS" : "SHOW ANNOTATIONS"}
          </button>
        </div>
      </div>

      <div style={{width:"100%",overflowX:"auto"}}>
        <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:"block",minWidth:400}}>
          {/* Background + clip */}
          <defs>
            <clipPath id="chartClip">
              <rect x={PAD.left} y={PAD.top} width={cW} height={cH}/>
            </clipPath>
          </defs>
          <rect x={PAD.left} y={PAD.top} width={cW} height={cH} fill={T.bg2} rx="3"/>

          {/* Y-axis grid + labels */}
          {yTickVals.map((v, i) => {
            const yy = ty(v);
            return (
              <g key={i}>
                <line x1={PAD.left} y1={yy} x2={PAD.left + cW} y2={yy}
                  stroke={T.border} strokeDasharray="3 3" strokeWidth="0.5"/>
                <text x={PAD.left - 5} y={yy + 4} textAnchor="end"
                  fill={T.t2} fontSize="9" fontFamily={MONO}>{fmtLbl(v)}</text>
              </g>
            );
          })}

          {/* X-axis labels */}
          {xTicks.map((c, i) => (
            <text key={i} x={tx(c.t)} y={H - PAD.bottom + 14} textAnchor="middle"
              fill={T.t2} fontSize="9" fontFamily={MONO}>
              {new Date(c.t).toLocaleDateString("en-GB",{month:"short",day:"numeric"})}
            </text>
          ))}

          {/* ── OHLC Candlesticks ── */}
          <g clipPath="url(#chartClip)">
            {candles.map((c, i) => {
              const x   = PAD.left + (i / (candles.length - 1 || 1)) * cW;
              const yo  = ty(c.o); const yc = ty(c.c);
              const yh  = ty(c.h); const yl = ty(c.l);
              const bull = c.c >= c.o;
              const col  = bull ? T.green : T.red;
              const bTop = Math.min(yo, yc);
              const bHt  = Math.max(Math.abs(yo - yc), 1);
              return (
                <g key={i}>
                  {/* Wick */}
                  <line x1={x} y1={yh} x2={x} y2={yl}
                    stroke={col} strokeWidth="0.7" strokeOpacity="0.7"/>
                  {/* Body */}
                  <rect x={x - halfBody} y={bTop} width={bodyW} height={bHt}
                    fill={bull ? `${T.green}88` : `${T.red}88`}
                    stroke={col} strokeWidth="0.4"/>
                </g>
              );
            })}
          </g>

          {/* ── Annotation overlay (SL/TP zone rectangles + level lines) ── */}
          {annotationsOn && (
            <g clipPath="url(#chartClip)">
              {tradeMarkers.filter(m => m.sl && m.tp && m.tEntry && m.tExit).map(m => {
                const x1 = tx(m.tEntry); const x2 = tx(m.tExit);
                const yEntry = ty(m.entry);
                const ySL    = ty(m.sl);
                const yTP    = ty(m.tp);
                const col    = m.win ? T.green : T.red;
                const rectTop    = Math.min(ySL, yTP);
                const rectBottom = Math.max(ySL, yTP);
                const rectH  = Math.max(rectBottom - rectTop, 2);
                return (
                  <g key={m.id}>
                    {/* SL–TP zone rectangle */}
                    <rect x={x1} y={rectTop} width={Math.max(x2 - x1, 2)} height={rectH}
                      fill={`${col}0D`} stroke={`${col}30`} strokeWidth="0.5"
                      strokeDasharray="3 2"/>
                    {/* Entry price line */}
                    <line x1={x1} y1={yEntry} x2={x2} y2={yEntry}
                      stroke={m.side === "BUY" ? T.green : T.red}
                      strokeWidth="1.2" strokeDasharray="5 3"/>
                    {/* SL line */}
                    <line x1={x1} y1={ySL} x2={x2} y2={ySL}
                      stroke={T.red} strokeWidth="0.8" strokeDasharray="3 3" strokeOpacity="0.7"/>
                    {/* TP line */}
                    <line x1={x1} y1={yTP} x2={x2} y2={yTP}
                      stroke={T.green} strokeWidth="0.8" strokeDasharray="3 3" strokeOpacity="0.7"/>
                    {/* SL label */}
                    <text x={x2 + 3} y={ySL + 3} fill={T.red}
                      fontSize="7" fontFamily={MONO} clipPath="url(#chartClip)">SL</text>
                    {/* TP label */}
                    <text x={x2 + 3} y={yTP + 3} fill={T.green}
                      fontSize="7" fontFamily={MONO} clipPath="url(#chartClip)">TP</text>
                  </g>
                );
              })}
            </g>
          )}

          {/* Trade entry/exit markers */}
          {tradeMarkers.map(m => {
            const xe = tx(m.tEntry);
            const xx = tx(m.tExit);
            const ye = ty(m.entry);
            const yx = ty(m.exit);
            const isBuy  = m.side === "BUY";
            const eColor = isBuy ? T.green : T.red;
            const xColor = m.win  ? T.green : T.red;
            const inBounds = (v) => v >= PAD.left && v <= PAD.left + cW;
            return (
              <g key={m.id} clipPath="url(#chartClip)">
                {/* Thin connector line entry→exit */}
                {inBounds(xe) && inBounds(xx) && (
                  <line x1={xe} y1={ye} x2={xx} y2={yx}
                    stroke={xColor} strokeWidth="0.8" strokeDasharray="4 2" strokeOpacity="0.5"/>
                )}
                {/* Entry vertical tick */}
                {inBounds(xe) && (
                  <line x1={xe} y1={PAD.top} x2={xe} y2={PAD.top + cH}
                    stroke={eColor} strokeWidth="1" strokeOpacity="0.3"/>
                )}
                {/* Entry triangle */}
                {inBounds(xe) && (
                  <polygon
                    points={isBuy
                      ? `${xe},${ye-10} ${xe-6},${ye+2} ${xe+6},${ye+2}`
                      : `${xe},${ye+10} ${xe-6},${ye-2} ${xe+6},${ye-2}`}
                    fill={eColor}
                    opacity="0.9"
                    style={{cursor:"pointer"}}
                    onMouseEnter={() => setHovered({...m, kind:"entry", x:xe, y:ye})}
                    onMouseLeave={() => setHovered(null)}
                  />
                )}
                {/* Exit diamond */}
                {inBounds(xx) && (
                  <polygon
                    points={`${xx},${yx-7} ${xx+7},${yx} ${xx},${yx+7} ${xx-7},${yx}`}
                    fill={xColor} opacity="0.85"
                    style={{cursor:"pointer"}}
                    onMouseEnter={() => setHovered({...m, kind:"exit", x:xx, y:yx})}
                    onMouseLeave={() => setHovered(null)}
                  />
                )}
              </g>
            );
          })}

          {/* Hover tooltip */}
          {hovered && (() => {
            const bx = Math.min(hovered.x + 12, W - 165);
            const by = Math.max(hovered.y - 60, PAD.top + 4);
            const lines = hovered.kind === "entry"
              ? [`${hovered.side} @ ${fmt(hovered.entry,4)}`,
                 `Session: ${hovered.session}`,
                 `PnL: ${fmtPnl(hovered.pnl)}`]
              : [`Exit @ ${fmt(hovered.exit,4)}`,
                 `${hovered.reason}`,
                 `PnL: ${fmtPnl(hovered.pnl)}`];
            return (
              <g>
                <rect x={bx} y={by} width="155" height={lines.length*16+12}
                  rx="3" fill={T.bg2} stroke={T.border} strokeWidth="1"/>
                {lines.map((l,i)=>(
                  <text key={i} x={bx+8} y={by+16+i*16}
                    fill={i===2?(hovered.pnl>0?T.green:T.red):T.text}
                    fontSize="10" fontFamily={MONO}>{l}</text>
                ))}
              </g>
            );
          })()}

          {/* Axes borders */}
          <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top+cH}
            stroke={T.border} strokeWidth="1"/>
          <line x1={PAD.left} y1={PAD.top+cH} x2={PAD.left+cW} y2={PAD.top+cH}
            stroke={T.border} strokeWidth="1"/>
        </svg>
      </div>

      {/* Trade summary strip below chart */}
      {trades.length > 0 && (
        <div style={{display:"flex",gap:8,flexWrap:"wrap",padding:"10px 10px 0",
          borderTop:`1px solid ${T.border}`,marginTop:8}}>
          {trades.map((t,i)=>(
            <div key={i} title={`${t.side} @ ${fmt(t.entry,4)} → ${fmtPnl(t.pnl)}`}
              style={{background:(t.pnl||0)>0?`${T.green}18`:`${T.red}18`,
                border:`1px solid ${(t.pnl||0)>0?T.green:T.red}44`,
                borderRadius:3,padding:"3px 8px",
                fontFamily:MONO,fontSize:9,
                color:(t.pnl||0)>0?T.green:T.red,cursor:"default",whiteSpace:"nowrap"}}>
              {t.side==="BUY"?"▲":"▼"} {fmtPnl(t.pnl)}
            </div>
          ))}
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

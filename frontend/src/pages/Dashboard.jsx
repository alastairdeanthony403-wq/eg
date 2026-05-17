/**
 * Dashboard.jsx — NexusBot Trading Terminal v2
 * Professional institutional-grade live signal dashboard.
 * Shows: signal cards, AI analysis, confidence logic, SMC checks, trade levels.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { RefreshCw, ChevronDown, ChevronUp, CheckCircle, XCircle } from "lucide-react";

// ── Design tokens ────────────────────────────────────────────────────────────
const T = {
  bg:"#050914", bg2:"#08111f", bg3:"#0d1a2e", bg4:"#111f38",
  border:"#162036", b2:"#1e3060",
  text:"#c8d8f0", t2:"#6a8aaa", t3:"#2a4060",
  green:"#00ffa3", red:"#ff2d55", gold:"#ffc107",
  blue:"#4facfe", purple:"#9f7aea", cyan:"#22d3ee",
};
const MONO = "'JetBrains Mono','Cascadia Code','Courier New',monospace";
const UI   = "'Rajdhani','Segoe UI',system-ui,sans-serif";

// ── Helpers ──────────────────────────────────────────────────────────────────
const fmt   = (n,d=2)  => n==null?"—":Number(n).toFixed(d);
const fmtP  = (n)      => n==null?"—":n>=1000?n.toLocaleString(undefined,{maximumFractionDigits:2}):n>=1?fmt(n,4):fmt(n,6);
const qColor= (q)      => ({"A+":T.green,A:"#7fff6e",B:T.gold,C:"#ff8c42",D:T.red})[q]||T.t2;
const getRR = (e,s,t)  => {if(!e||!s||!t)return"—";const r=Math.abs(e-s),w=Math.abs(t-e);return r>0?(w/r).toFixed(1)+"R":"—";};

function getSession(){
  const h=new Date().getUTCHours();
  if(h>=7&&h<12) return{name:"London",  color:"#4facfe"};
  if(h>=12&&h<21)return{name:"New York",color:"#ff6b9d"};
  if(h>=0&&h<7)  return{name:"Asia",    color:"#ffd93d"};
  return{name:"Off-Hours",color:T.t2};
}

const GS = `
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap');
*{box-sizing:border-box}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:#050914}
::-webkit-scrollbar-thumb{background:#162036;border-radius:3px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes slide{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
@keyframes flash{0%,100%{opacity:1}40%{opacity:.3}}
`;

// ── MAIN COMPONENT ────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [signals,    setSignals]    = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error,      setError]      = useState(null);
  const [filter,     setFilter]     = useState("all");
  const [strategy,   setStrategy]   = useState("bot");
  const [expanded,   setExpanded]   = useState(null);
  const [session,    setSession]    = useState(getSession());
  const [lastUpd,    setLastUpd]    = useState(null);
  const [flashing,   setFlashing]   = useState({});
  const prevPx = useRef({});

  const token   = localStorage.getItem("token");
  const hdrs    = { Authorization:`Bearer ${token}` };

  const load = useCallback(async (silent=false) => {
    if(!silent) setLoading(true); else setRefreshing(true);
    setError(null);
    try {
      const r = await fetch(`/api/signals?strategy=${strategy}`, {headers:hdrs});
      const d = await r.json();
      if(!r.ok) throw new Error(d.error||"Failed");
      const sigs = d.signals||[];
      const fl={};
      sigs.forEach(s=>{
        const p=prevPx.current[s.symbol];
        if(p&&p!==s.price) fl[s.symbol]=s.price>p?"up":"dn";
        prevPx.current[s.symbol]=s.price;
      });
      setFlashing(fl);
      setTimeout(()=>setFlashing({}),900);
      setSignals(sigs); setLastUpd(new Date()); setSession(getSession());
    } catch(e){setError(e.message);}
    finally{setLoading(false);setRefreshing(false);}
  },[strategy]);

  useEffect(()=>{ load(); const iv=setInterval(()=>load(true),30000); return()=>clearInterval(iv); },[load]);

  const shown = signals.filter(s=>filter==="all"||s.market===filter);
  const buys  = signals.filter(s=>s.signal==="BUY").length;
  const sells = signals.filter(s=>s.signal==="SELL").length;

  return (
    <div style={{background:T.bg,minHeight:"100vh",fontFamily:UI,color:T.text}}>
      <style>{GS}</style>

      {/* TOP BAR */}
      <div style={{background:T.bg2,borderBottom:`1px solid ${T.border}`,padding:"10px 20px",
        display:"flex",alignItems:"center",justifyContent:"space-between",
        position:"sticky",top:0,zIndex:200,flexWrap:"wrap",gap:12}}>
        <div style={{display:"flex",alignItems:"center",gap:18}}>
          <span style={{fontFamily:MONO,fontSize:16,letterSpacing:3,color:T.text}}>
            ⬡<span style={{color:T.green}}>NEXUS</span>BOT
          </span>
          {/* Session indicator */}
          <div style={{display:"flex",alignItems:"center",gap:7,background:T.bg3,
            border:`1px solid ${T.border}`,borderRadius:4,padding:"4px 11px"}}>
            <div style={{width:7,height:7,borderRadius:"50%",background:session.color,
              boxShadow:`0 0 7px ${session.color}`,animation:"pulse 2s infinite"}}/>
            <span style={{fontFamily:MONO,fontSize:11,color:session.color,letterSpacing:1}}>
              {session.name.toUpperCase()} SESSION
            </span>
          </div>
          {/* Market sentiment pills */}
          {[["▲",buys,T.green],["▼",sells,T.red]].map(([sym,n,c])=>(
            <span key={sym} style={{fontFamily:MONO,fontSize:11,padding:"2px 9px",borderRadius:3,
              background:`${c}18`,border:`1px solid ${c}40`,color:c}}>
              {sym} {n}
            </span>
          ))}
        </div>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          {lastUpd&&<span style={{fontFamily:MONO,fontSize:10,color:T.t2}}>{lastUpd.toLocaleTimeString()}</span>}
          <button onClick={()=>load(true)} disabled={refreshing}
            style={{background:T.bg3,border:`1px solid ${T.border}`,color:refreshing?T.t2:T.text,
              borderRadius:3,padding:"5px 12px",cursor:"pointer",fontFamily:MONO,fontSize:10,letterSpacing:1,
              display:"flex",alignItems:"center",gap:5}}>
            <RefreshCw size={11} style={{animation:refreshing?"spin 1s linear infinite":"none"}}/>
            {refreshing?"…":"REFRESH"}
          </button>
        </div>
      </div>

      {/* FILTER BAR */}
      <div style={{background:T.bg2,borderBottom:`1px solid ${T.border}`,
        padding:"8px 20px",display:"flex",gap:10,flexWrap:"wrap",alignItems:"center"}}>
        <div style={{display:"flex",gap:3}}>
          {["all","crypto","forex","stocks","commodities"].map(f=>(
            <FBtn key={f} label={f.toUpperCase()} active={filter===f} color={T.blue} onClick={()=>setFilter(f)}/>
          ))}
        </div>
        <div style={{width:1,height:18,background:T.border}}/>
        <div style={{display:"flex",gap:3}}>
          {[["bot","SMC BOT"],["basic","BASIC"],["ema_rsi","EMA/RSI"]].map(([v,l])=>(
            <FBtn key={v} label={l} active={strategy===v} color={T.purple} onClick={()=>setStrategy(v)}/>
          ))}
        </div>
        <span style={{marginLeft:"auto",fontFamily:MONO,fontSize:10,color:T.t2}}>
          {shown.length} SIGNALS
        </span>
      </div>

      {/* SIGNAL GRID */}
      <div style={{padding:"18px 20px"}}>
        {loading&&<Spinner/>}
        {error&&<ErrBox msg={error}/>}
        {!loading&&!error&&(
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(345px,1fr))",gap:14}}>
            {shown.map(s=>(
              <SignalCard key={s.symbol} s={s}
                expanded={expanded===s.symbol}
                flash={flashing[s.symbol]}
                onExpand={()=>setExpanded(expanded===s.symbol?null:s.symbol)}/>
            ))}
            {shown.length===0&&(
              <div style={{gridColumn:"1/-1",textAlign:"center",padding:60,
                color:T.t2,fontFamily:MONO,fontSize:12}}>
                NO SIGNALS MATCH FILTER
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── SIGNAL CARD ───────────────────────────────────────────────────────────────
function SignalCard({s, expanded, onExpand, flash}){
  const buy  = s.signal==="BUY";
  const sell = s.signal==="SELL";
  const dir  = buy?T.green:sell?T.red:T.border;
  const qc   = qColor(s.quality);
  const fc   = flash==="up"?T.green:flash==="dn"?T.red:null;

  return (
    <div style={{background:T.bg3,border:`1px solid ${dir}44`,borderLeft:`3px solid ${buy||sell?dir:T.border}`,
      borderRadius:6,overflow:"hidden",
      boxShadow:buy||sell?`0 0 22px ${dir}15`:"none",transition:"box-shadow .3s"}}>

      {/* Header row */}
      <div style={{padding:"13px 15px",display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}>
        <div>
          <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:5}}>
            <span style={{fontFamily:MONO,fontSize:17,color:T.text}}>
              {s.symbol.replace("USDT","")}<span style={{color:T.t2,fontSize:12}}>{s.symbol.endsWith("USDT")?"/USDT":""}</span>
            </span>
            <MBadge market={s.market}/>
          </div>
          <div style={{display:"flex",gap:5}}>
            <Chip label={s.regime||"—"} color={T.t2}/>
            <Chip label={s.session||"—"} color={T.cyan}/>
            {s.ema_alignment&&<Chip label={s.ema_alignment.split(" ")[0]} color={buy?T.green:sell?T.red:T.t2}/>}
          </div>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:9}}>
          <span style={{fontFamily:MONO,fontSize:20,fontWeight:700,color:qc,textShadow:`0 0 10px ${qc}`}}>
            {s.quality||"—"}
          </span>
          <SigBadge signal={s.signal} dir={dir}/>
        </div>
      </div>

      {/* Live price */}
      <div style={{padding:"0 15px 10px",display:"flex",alignItems:"baseline",gap:10}}>
        <span style={{fontFamily:MONO,fontSize:22,color:fc||T.text,
          textShadow:fc?`0 0 12px ${fc}`:"none",transition:"color .4s,text-shadow .4s",
          animation:flash?"flash .6s ease":"none"}}>
          {s.price_display||fmtP(s.price)}
        </span>
        <span style={{fontFamily:MONO,fontSize:12,color:s.change_pct>=0?T.green:T.red}}>
          {s.change_pct>=0?"+":""}{fmt(s.change_pct,2)}%
        </span>
      </div>

      {/* Confidence bar */}
      <div style={{padding:"0 15px 11px"}}>
        <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
          <span style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2}}>CONFIDENCE</span>
          <span style={{fontFamily:MONO,fontSize:11,color:dir,fontWeight:600}}>{s.confidence}%</span>
        </div>
        <div style={{height:3,background:T.bg2,borderRadius:2}}>
          <div style={{height:"100%",width:`${s.confidence||0}%`,
            background:`linear-gradient(90deg,${dir}55,${dir})`,borderRadius:2,transition:"width .6s"}}/>
        </div>
      </div>

      {/* 4-stat strip */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",
        borderTop:`1px solid ${T.border}`,borderBottom:`1px solid ${T.border}`}}>
        {[
          ["ADX", fmt(s.adx,1), s.adx>=25?T.green:s.adx>=20?T.gold:T.red,    s.adx>=25?"STRONG":s.adx>=20?"TREND":"WEAK"],
          ["RSI", fmt(s.rsi,1), s.rsi>70?T.red:s.rsi<30?T.green:T.text,       s.rsi>70?"OB":s.rsi<30?"OS":"NEUTRAL"],
          ["SMC", `${s.smc_score}/9`, s.smc_score>=7?T.green:s.smc_score>=5?T.gold:T.t2, "SCORE"],
          ["RR",  getRR(s.entry,s.sl,s.tp), T.gold, "RATIO"],
        ].map(([lbl,val,c,sub],i)=>(
          <div key={lbl} style={{background:i%2===0?T.bg2:T.bg3,padding:"7px 8px",textAlign:"center"}}>
            <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{lbl}</div>
            <div style={{fontFamily:MONO,fontSize:13,color:c,fontWeight:500}}>{val}</div>
            <div style={{fontFamily:MONO,fontSize:7,color:T.t3,marginTop:1}}>{sub}</div>
          </div>
        ))}
      </div>

      {/* SMC confirmation pills */}
      <div style={{padding:"9px 15px",display:"flex",gap:4,flexWrap:"wrap"}}>
        <CPill label="SWEEP"   active={!!s.liquidity_sweep} color={T.blue}/>
        <CPill label="BOS"     active={!!s.bos}             color={T.purple}/>
        <CPill label="FVG"     active={!!s.fvg_detected}    color={T.gold}/>
        <CPill label="HTF ALN" active={s.higher_tf_bias===s.bias&&s.bias!=="Neutral"} color={T.cyan}/>
        <CPill label="SESSION" active={s.session!=="Closed"&&s.session!=="Off-Hours"} color={T.green}/>
      </div>

      {/* Trade levels */}
      {s.entry&&s.signal!=="HOLD"&&(
        <div style={{padding:"8px 15px 10px",borderTop:`1px solid ${T.border}`}}>
          <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:7}}>TRADE LEVELS</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:5}}>
            <LBox label="ENTRY"  val={fmtP(s.entry)} color={T.text}/>
            <LBox label="STOP"   val={fmtP(s.sl)}    color={T.red}/>
            <LBox label="TARGET" val={fmtP(s.tp)}    color={T.green}/>
            <LBox label="R:R"    val={getRR(s.entry,s.sl,s.tp)} color={T.gold}/>
          </div>
        </div>
      )}

      {/* Trade idea */}
      {s.trade_idea&&s.signal!=="HOLD"&&(
        <div style={{padding:"7px 15px",borderTop:`1px solid ${T.border}`,
          fontFamily:MONO,fontSize:10,color:T.t2,letterSpacing:.5}}>
          ↳ {s.trade_idea}
        </div>
      )}

      {/* AI expand button */}
      <button onClick={onExpand}
        style={{width:"100%",padding:"9px",background:T.bg2,border:"none",
          borderTop:`1px solid ${T.border}`,color:T.t2,cursor:"pointer",
          display:"flex",alignItems:"center",justifyContent:"center",gap:5,
          fontFamily:MONO,fontSize:10,letterSpacing:1,transition:"background .15s,color .15s"}}
        onMouseEnter={e=>{e.currentTarget.style.background=T.bg4;e.currentTarget.style.color=T.text}}
        onMouseLeave={e=>{e.currentTarget.style.background=T.bg2;e.currentTarget.style.color=T.t2}}>
        {expanded?<ChevronUp size={12}/>:<ChevronDown size={12}/>}
        {expanded?"HIDE AI ANALYSIS":"SHOW AI ANALYSIS"}
      </button>

      {expanded&&(
        <div style={{animation:"slide .2s ease",borderTop:`1px solid ${T.border}`}}>
          <AIPanel s={s}/>
        </div>
      )}
    </div>
  );
}

// ── AI ANALYSIS PANEL ─────────────────────────────────────────────────────────
function AIPanel({s}){
  const buy     = s.signal==="BUY";
  const dir     = buy?T.green:T.red;
  const passing = (s.reasons||[]).filter(r=>r.startsWith("✓"));
  const failing = (s.reasons||[]).filter(r=>r.startsWith("✗"));
  const engine  = s.smc_score>0?"ICT / SMC SETUP":"EMA + ADX FALLBACK";

  return (
    <div style={{background:T.bg2,padding:15}}>
      {/* Engine + count */}
      <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
        <span style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2}}>ENGINE</span>
        <span style={{fontFamily:MONO,fontSize:9,padding:"2px 8px",borderRadius:2,
          background:`${T.purple}20`,border:`1px solid ${T.purple}40`,color:T.purple}}>
          {engine}
        </span>
        <span style={{marginLeft:"auto",fontFamily:MONO,fontSize:9,color:T.t2}}>
          {passing.length}/{passing.length+failing.length} CHECKS PASSED
        </span>
      </div>

      {/* Plain-English explanation */}
      <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:4,
        padding:"10px 12px",marginBottom:12}}>
        <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:7}}>
          WHY THIS SETUP
        </div>
        <p style={{margin:0,fontSize:12,color:T.text,lineHeight:1.75,fontFamily:UI}}>
          {buildExpl(s)}
        </p>
      </div>

      {/* Confirmations grid */}
      <div style={{marginBottom:12}}>
        <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:7}}>
          CONFIRMATION CHECKLIST
        </div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:4}}>
          {passing.map((r,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",gap:5,fontFamily:MONO,fontSize:10,color:T.green}}>
              <CheckCircle size={11}/>{r.slice(2)}
            </div>
          ))}
          {failing.map((r,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",gap:5,fontFamily:MONO,fontSize:10,color:T.t3}}>
              <XCircle size={11}/>{r.slice(2)}
            </div>
          ))}
        </div>
      </div>

      {/* Confidence breakdown */}
      <div style={{marginBottom:12}}>
        <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:7}}>
          CONFIDENCE SCORE BREAKDOWN
        </div>
        <CBar label="SMC Alignment (0–20)"  val={Math.round((s.smc_score/9)*20)} max={20} color={dir}/>
        <CBar label="ADX Strength (0–10)"   val={s.adx>=30?10:s.adx>=25?7:s.adx>=20?4:0} max={10} color={T.blue}/>
        <CBar label="Volume Surge (0–10)"   val={s.confidence>78?9:s.confidence>70?6:4} max={10} color={T.gold}/>
        <CBar label="Candle Body (0–10)"    val={s.confidence>82?10:7} max={10} color={T.purple}/>
        <CBar label="EMA Alignment (0–10)"  val={
          (s.ema_alignment?.startsWith("Bull")&&buy)||(s.ema_alignment?.startsWith("Bear")&&!buy)?10:0
        } max={10} color={T.cyan}/>
      </div>

      {/* Sweep / BOS / FVG cards */}
      {(s.liquidity_sweep||s.bos||s.fvg_detected)&&(
        <div style={{display:"flex",gap:5,marginBottom:12}}>
          {s.liquidity_sweep&&(
            <div style={{flex:1,background:T.bg3,borderRadius:3,padding:"7px 10px",border:`1px solid ${T.blue}35`}}>
              <div style={{fontFamily:MONO,fontSize:7,color:T.t2,letterSpacing:1,marginBottom:3}}>LIQUIDITY SWEEP</div>
              <div style={{fontFamily:MONO,fontSize:11,color:T.blue}}>
                {s.liquidity_sweep==="BUY_SWEEP"?"↗ Buy-Side":"↘ Sell-Side"}
              </div>
            </div>
          )}
          {s.bos&&(
            <div style={{flex:1,background:T.bg3,borderRadius:3,padding:"7px 10px",border:`1px solid ${T.purple}35`}}>
              <div style={{fontFamily:MONO,fontSize:7,color:T.t2,letterSpacing:1,marginBottom:3}}>BREAK OF STRUCTURE</div>
              <div style={{fontFamily:MONO,fontSize:11,color:T.purple}}>
                {s.bos==="BULLISH_BOS"?"↑ Bullish BOS":"↓ Bearish BOS"}
              </div>
            </div>
          )}
          {s.fvg_detected&&(
            <div style={{flex:1,background:T.bg3,borderRadius:3,padding:"7px 10px",border:`1px solid ${T.gold}35`}}>
              <div style={{fontFamily:MONO,fontSize:7,color:T.t2,letterSpacing:1,marginBottom:3}}>FAIR VALUE GAP</div>
              <div style={{fontFamily:MONO,fontSize:11,color:T.gold}}>
                {s.fvg_direction==="BUY"?"↗ Bullish FVG":"↘ Bearish FVG"}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Context row */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:5}}>
        <IBox label="SESSION"   val={s.session||"—"}/>
        <IBox label="STRUCTURE" val={(s.structure||"—").replace(" Structure","")}/>
        <IBox label="HTF BIAS"  val={s.higher_tf_bias||"—"}/>
        <IBox label="REGIME"    val={s.regime||"—"}/>
      </div>
    </div>
  );
}

// ── EXPLANATION BUILDER ───────────────────────────────────────────────────────
function buildExpl(s){
  const {signal,regime,higher_tf_bias,liquidity_sweep,bos,smc_score,adx,rsi,
         ema_alignment,confidence,session,quality,min_smc_score}=s;
  if(signal==="HOLD"){
    if((adx||0)<20) return`ADX is ${(adx||0).toFixed(1)} — the market has no directional trend. The bot requires ADX ≥ 20 before entering. This filter protects capital in choppy sideways conditions.`;
    return`Only ${smc_score}/9 SMC conditions aligned (threshold: ${min_smc_score||6}). Missing key confirmations — waiting for a higher-quality setup before risking capital.`;
  }
  const dir=signal==="BUY"?"long":"short";
  const parts=[];
  if(higher_tf_bias) parts.push(`${s.higher_tf||"higher timeframe"} shows ${higher_tf_bias.toLowerCase()} momentum`);
  if(liquidity_sweep) parts.push(`a ${liquidity_sweep==="BUY_SWEEP"?"buy-side":"sell-side"} liquidity sweep confirmed institutional interest`);
  if(bos) parts.push(`a ${bos==="BULLISH_BOS"?"bullish":"bearish"} break of structure validated the directional bias`);
  if(regime) parts.push(`market is in a "${regime}" regime`);
  const ctx=parts.length?parts.map((p,i)=>i===0?p[0].toUpperCase()+p.slice(1):p).join(", ")+". ":"";
  const conf=confidence>=85?"High-conviction setup":confidence>=75?"Moderate-confidence setup":"Lower-confidence — reduce position size";
  const ema=ema_alignment?.startsWith("Bull")?"EMAs stack bullishly (9>21>50) confirming uptrend.":ema_alignment?.startsWith("Bear")?"EMAs stack bearishly (9<21<50) confirming downtrend.":"EMAs in mixed alignment — trend is developing.";
  const rsiV=(rsi||50);
  const rsiStr=rsiV>70?`RSI ${rsiV.toFixed(0)} is overbought — expect the move to be pullback/corrective.`:rsiV<30?`RSI ${rsiV.toFixed(0)} is oversold — potential bounce or reversal.`:`RSI ${rsiV.toFixed(0)} is neutral — momentum aligned with ${dir} direction.`;
  const adxV=(adx||0);
  const adxStr=adxV>=25?`ADX ${adxV.toFixed(1)} confirms strong trend.`:adxV>=20?`ADX ${adxV.toFixed(1)} confirms trend is present but still developing.`:`ADX ${adxV.toFixed(1)} is at minimum threshold — reduce trade size.`;
  return`${ctx}${conf} — ${smc_score}/9 SMC confirmations (${quality||"—"} grade). ${ema} ${rsiStr} ${adxStr} Active session: ${session||"Unknown"}.`;
}

// ── SMALL COMPONENTS ──────────────────────────────────────────────────────────
const FBtn=({label,active,color,onClick})=>(
  <button onClick={onClick} style={{padding:"4px 11px",borderRadius:3,cursor:"pointer",
    border:`1px solid ${active?color:T.border}`,background:active?`${color}20`:"transparent",
    color:active?color:T.t2,fontFamily:MONO,fontSize:10,fontWeight:700,letterSpacing:1}}>
    {label}
  </button>
);

const MBadge=({market})=>{
  const c={crypto:T.gold,forex:T.blue,stocks:T.green,commodities:T.purple}[market]||T.t2;
  return<span style={{fontFamily:MONO,fontSize:8,padding:"2px 6px",borderRadius:2,letterSpacing:1,
    background:`${c}18`,border:`1px solid ${c}44`,color:c}}>{(market||"").toUpperCase()}</span>;
};

const SigBadge=({signal,dir})=>(
  <div style={{padding:"4px 12px",borderRadius:3,fontFamily:MONO,fontWeight:700,fontSize:12,letterSpacing:2,
    background:signal==="HOLD"?`${T.t2}15`:`${dir}20`,
    border:`1px solid ${signal==="HOLD"?T.border:dir+"55"}`,
    color:signal==="HOLD"?T.t2:dir,
    textShadow:signal==="HOLD"?"none":`0 0 8px ${dir}`}}>
    {signal==="BUY"?"▲ BUY":signal==="SELL"?"▼ SELL":"— HOLD"}
  </div>
);

const Chip=({label,color})=>(
  <span style={{fontFamily:MONO,fontSize:8,padding:"1px 5px",borderRadius:2,letterSpacing:1,
    background:`${color}15`,border:`1px solid ${color}35`,color}}>{label}</span>
);

const CPill=({label,active,color})=>(
  <span style={{fontFamily:MONO,fontSize:8,padding:"2px 7px",borderRadius:2,letterSpacing:1,
    background:active?`${color}18`:T.bg,border:`1px solid ${active?color+"50":T.border}`,
    color:active?color:T.t3}}>
    {active?"✓":"✗"} {label}
  </span>
);

const LBox=({label,val,color})=>(
  <div style={{background:T.bg,borderRadius:3,padding:"5px 7px",textAlign:"center"}}>
    <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{label}</div>
    <div style={{fontFamily:MONO,fontSize:11,color,fontWeight:500}}>{val}</div>
  </div>
);

const CBar=({label,val,max,color})=>(
  <div style={{display:"flex",alignItems:"center",gap:9,marginBottom:5}}>
    <span style={{fontFamily:MONO,fontSize:9,color:T.t2,width:160,flexShrink:0}}>{label}</span>
    <div style={{flex:1,height:3,background:T.bg,borderRadius:2}}>
      <div style={{height:"100%",width:`${Math.max(0,Math.min(100,(val/max)*100))}%`,
        background:color,borderRadius:2,transition:"width .5s"}}/>
    </div>
    <span style={{fontFamily:MONO,fontSize:9,color,width:30,textAlign:"right"}}>{val}/{max}</span>
  </div>
);

const IBox=({label,val})=>(
  <div style={{background:T.bg,borderRadius:3,padding:"6px 8px",textAlign:"center"}}>
    <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{label}</div>
    <div style={{fontFamily:MONO,fontSize:10,color:T.t2}}>{val}</div>
  </div>
);

const Spinner=()=>(
  <div style={{display:"flex",flexDirection:"column",alignItems:"center",
    justifyContent:"center",height:280,gap:14,color:T.t2}}>
    <div style={{width:36,height:36,border:`2px solid ${T.border}`,
      borderTop:`2px solid ${T.blue}`,borderRadius:"50%",animation:"spin 1s linear infinite"}}/>
    <span style={{fontFamily:MONO,fontSize:11,letterSpacing:3}}>FETCHING SIGNALS…</span>
  </div>
);

const ErrBox=({msg})=>(
  <div style={{background:`${T.red}12`,border:`1px solid ${T.red}40`,borderRadius:5,
    padding:14,color:T.red,fontFamily:MONO,fontSize:12}}>⚠ {msg}</div>
);

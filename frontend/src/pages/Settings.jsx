/**
 * Settings.jsx — NexusBot v2
 * Full bot configuration: AI aggressiveness, thresholds, session
 * filters, ATR multiplier, risk, trailing stop, fallback strategy,
 * market toggles, daily limits.
 */
import { useState, useEffect, useCallback } from "react";
import { Save, RefreshCw, AlertTriangle, CheckCircle, Settings as SettingsIcon } from "lucide-react";

// ── Design tokens ─────────────────────────────────────────────────────────────
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
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:#050914}
::-webkit-scrollbar-thumb{background:#162036;border-radius:3px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes slide{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
`;

// ── CONFIG DEFAULTS (mirrors backend DEFAULT_CONFIG) ─────────────────────────
const DEFAULTS = {
  // AI / Signal quality
  min_confidence:    65,
  min_smc_score:     6,
  adx_min:           20,
  risk_reward:       2.0,
  atr_multiplier:    1.5,
  // Risk
  risk_percentage:   1.0,
  daily_trade_limit: 5,
  // Features
  enable_trailing_stop:    true,
  enable_fallback_strategy:true,
  enable_breakeven_stop:   true,
  // Session filters
  blocked_hours: [],
  blocked_sessions: [],
  // Markets
  markets: ["crypto","forex","stocks","commodities"],
};

const SESSIONS = ["Asia","London","New York"];
const MARKETS  = ["crypto","forex","stocks","commodities"];

// ── MAIN COMPONENT ────────────────────────────────────────────────────────────
export default function Settings() {
  const [cfg,     setCfg]     = useState(DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saving,  setSaving]  = useState(false);
  const [saved,   setSaved]   = useState(false);
  const [error,   setError]   = useState(null);

  const token = localStorage.getItem("token");
  const hdrs  = { "Content-Type":"application/json", Authorization:`Bearer ${token}` };

  // ── Load config ─────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/settings", {headers:hdrs});
      const d = await r.json();
      if(r.ok) setCfg(prev=>({...DEFAULTS,...prev,...(d.config||d)}));
    } catch{}
    finally{ setLoading(false); }
  },[]);

  useEffect(()=>{ load(); },[load]);

  // ── Save config ─────────────────────────────────────────────────────────────
  const save = async () => {
    setSaving(true); setError(null); setSaved(false);
    try {
      const r = await fetch("/api/settings", {
        method:"POST", headers:hdrs,
        body:JSON.stringify(cfg),
      });
      const d = await r.json();
      if(!r.ok) throw new Error(d.error||"Save failed");
      setSaved(true);
      setTimeout(()=>setSaved(false),3000);
    } catch(e){ setError(e.message); }
    finally{ setSaving(false); }
  };

  const set = (key,val) => setCfg(prev=>({...prev,[key]:val}));

  const toggleBlockedSession = (s) => {
    const cur = cfg.blocked_sessions||[];
    setCfg(prev=>({...prev,
      blocked_sessions: cur.includes(s)?cur.filter(x=>x!==s):[...cur,s]
    }));
  };

  const toggleMarket = (m) => {
    const cur = cfg.markets||[];
    setCfg(prev=>({...prev,
      markets: cur.includes(m)?cur.filter(x=>x!==m):[...cur,m]
    }));
  };

  // ── AI Aggressiveness helper ─────────────────────────────────────────────────
  const aggressiveness = () => {
    const conf = cfg.min_confidence||65;
    const smc  = cfg.min_smc_score||6;
    if(conf<=60&&smc<=4) return{label:"VERY AGGRESSIVE",color:T.red};
    if(conf<=70&&smc<=5) return{label:"AGGRESSIVE",color:"#ff8c42"};
    if(conf<=78&&smc<=7) return{label:"BALANCED",color:T.gold};
    return{label:"CONSERVATIVE",color:T.green};
  };
  const agg = aggressiveness();

  if(loading) return(
    <div style={{background:T.bg,minHeight:"100vh",display:"flex",alignItems:"center",
      justifyContent:"center",gap:14,color:T.t2}}>
      <div style={{width:30,height:30,border:`2px solid ${T.border}`,borderTop:`2px solid ${T.blue}`,
        borderRadius:"50%",animation:"spin 1s linear infinite"}}/>
      <span style={{fontFamily:MONO,fontSize:12,letterSpacing:2}}>LOADING CONFIG…</span>
    </div>
  );

  return (
    <div style={{background:T.bg,minHeight:"100vh",fontFamily:UI,color:T.text}}>
      <style>{GS}</style>

      {/* Header */}
      <div style={{background:T.bg2,borderBottom:`1px solid ${T.border}`,padding:"12px 20px",
        display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <SettingsIcon size={16} style={{color:T.purple}}/>
          <span style={{fontFamily:MONO,fontSize:14,letterSpacing:3,color:T.text}}>BOT SETTINGS</span>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          {saved&&(
            <div style={{display:"flex",alignItems:"center",gap:6,
              fontFamily:MONO,fontSize:11,color:T.green,animation:"slide .2s ease"}}>
              <CheckCircle size={13}/>SAVED
            </div>
          )}
          {error&&(
            <div style={{fontFamily:MONO,fontSize:11,color:T.red}}>⚠ {error}</div>
          )}
          <button onClick={load}
            style={{background:T.bg3,border:`1px solid ${T.border}`,color:T.t2,
              borderRadius:3,padding:"5px 12px",cursor:"pointer",fontFamily:MONO,fontSize:10,
              letterSpacing:1,display:"flex",alignItems:"center",gap:5}}>
            <RefreshCw size={11}/>RELOAD
          </button>
          <button onClick={save} disabled={saving}
            style={{background:`${T.blue}20`,border:`1px solid ${T.blue}50`,color:T.blue,
              borderRadius:4,padding:"7px 18px",cursor:"pointer",fontFamily:MONO,fontSize:11,
              letterSpacing:1,display:"flex",alignItems:"center",gap:6,opacity:saving?0.7:1}}>
            <Save size={13}/>{saving?"SAVING…":"SAVE ALL"}
          </button>
        </div>
      </div>

      {/* Aggressiveness indicator */}
      <div style={{background:T.bg3,borderBottom:`1px solid ${T.border}`,padding:"10px 20px",
        display:"flex",alignItems:"center",gap:14}}>
        <span style={{fontFamily:MONO,fontSize:9,color:T.t2,letterSpacing:2}}>BOT AGGRESSIVENESS</span>
        <div style={{flex:1,maxWidth:300,height:3,background:T.bg2,borderRadius:2}}>
          <div style={{
            height:"100%",
            width:`${Math.max(10,Math.min(100,100-((cfg.min_confidence||65)-50)*2))}%`,
            background:agg.color,borderRadius:2,transition:"width .4s,background .4s"
          }}/>
        </div>
        <span style={{fontFamily:MONO,fontSize:11,color:agg.color,fontWeight:700,letterSpacing:1}}>
          {agg.label}
        </span>
        <span style={{fontFamily:MONO,fontSize:10,color:T.t2,marginLeft:8}}>
          Conf ≥{cfg.min_confidence}% · SMC ≥{cfg.min_smc_score}/9 · ADX ≥{cfg.adx_min}
        </span>
      </div>

      <div style={{padding:"20px",display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(360px,1fr))",gap:16}}>

        {/* ── Signal Quality ── */}
        <Section title="AI SIGNAL QUALITY" color={T.blue} icon="🎯">
          <Slider label="Minimum Confidence %" min={40} max={95} step={1}
            val={cfg.min_confidence} onChange={v=>set("min_confidence",v)}
            help="Signals below this confidence are shown as HOLD. Higher = fewer but better trades."
            color={cfg.min_confidence>=80?T.green:cfg.min_confidence>=65?T.gold:T.red}/>
          <Slider label="Minimum SMC Score" min={2} max={9} step={1}
            val={cfg.min_smc_score} onChange={v=>set("min_smc_score",v)}
            help="Number of SMC checks that must pass (out of 9). Higher = stricter setup requirements."
            color={T.purple}/>
          <Slider label="ADX Minimum" min={15} max={40} step={1}
            val={cfg.adx_min} onChange={v=>set("adx_min",v)}
            help="Minimum ADX value required. Below this, the market is too choppy to trade."
            color={cfg.adx_min>=25?T.green:T.gold}/>
          <Slider label="Risk : Reward Ratio" min={1} max={5} step={0.5}
            val={cfg.risk_reward} onChange={v=>set("risk_reward",v)}
            help="Minimum R:R before a trade is taken. 2.0 means the target is 2× the stop distance."
            color={T.cyan} fmt={v=>v+"R"}/>
          <Slider label="ATR Multiplier (stop distance)" min={0.5} max={4} step={0.25}
            val={cfg.atr_multiplier} onChange={v=>set("atr_multiplier",v)}
            help="Stop loss distance = ATR × this multiplier. Higher = wider stops, fewer stopped-out early."
            color={T.gold} fmt={v=>`${v}×`}/>
        </Section>

        {/* ── Risk Management ── */}
        <Section title="RISK MANAGEMENT" color={T.red} icon="🛡️">
          <Slider label="Risk Per Trade (%)" min={0.25} max={5} step={0.25}
            val={cfg.risk_percentage} onChange={v=>set("risk_percentage",v)}
            help="What % of your account to risk on each trade. 1% is professional standard."
            color={cfg.risk_percentage<=1?T.green:cfg.risk_percentage<=2?T.gold:T.red} fmt={v=>v+"%"}/>
          <Slider label="Max Trades Per Day" min={1} max={20} step={1}
            val={cfg.daily_trade_limit} onChange={v=>set("daily_trade_limit",v)}
            help="Bot won't enter new trades once this count is reached for the day."
            color={T.text}/>
          <Toggle label="Enable Trailing Stop"
            val={cfg.enable_trailing_stop} onChange={v=>set("enable_trailing_stop",v)}
            help="Once price moves 1R in profit, the stop loss trails to lock in gains."/>
          <Toggle label="Enable Breakeven Stop"
            val={cfg.enable_breakeven_stop} onChange={v=>set("enable_breakeven_stop",v)}
            help="Move stop to entry price once trade is 0.5R in profit."/>
          <Toggle label="Enable Fallback Strategy (EMA+ADX)"
            val={cfg.enable_fallback_strategy} onChange={v=>set("enable_fallback_strategy",v)}
            help="When SMC conditions don't align, fall back to the simpler EMA+ADX trend strategy."/>
        </Section>

        {/* ── Session Filters ── */}
        <Section title="SESSION FILTERS" color={T.gold} icon="🕐">
          <div style={{marginBottom:14}}>
            <div style={{fontFamily:MONO,fontSize:9,color:T.t2,letterSpacing:1,marginBottom:8}}>
              BLOCKED SESSIONS (no trades taken)
            </div>
            <div style={{display:"flex",gap:8}}>
              {SESSIONS.map(s=>{
                const blocked=(cfg.blocked_sessions||[]).includes(s);
                return(
                  <button key={s} onClick={()=>toggleBlockedSession(s)}
                    style={{padding:"7px 16px",borderRadius:4,cursor:"pointer",
                      border:`1px solid ${blocked?T.red+"60":T.border}`,
                      background:blocked?`${T.red}18`:T.bg2,
                      color:blocked?T.red:T.t2,fontFamily:MONO,fontSize:10,letterSpacing:1}}>
                    {blocked?"✗":"✓"} {s}
                  </button>
                );
              })}
            </div>
            <div style={{fontFamily:MONO,fontSize:9,color:T.t2,marginTop:7,lineHeight:1.5}}>
              Asia: 00:00–07:00 UTC · London: 07:00–12:00 UTC · New York: 12:00–21:00 UTC
            </div>
          </div>

          <div>
            <div style={{fontFamily:MONO,fontSize:9,color:T.t2,letterSpacing:1,marginBottom:8}}>
              BLOCKED HOURS (UTC, comma separated e.g. "0,1,2,22,23")
            </div>
            <input
              value={(cfg.blocked_hours||[]).join(",")}
              onChange={e=>{
                const vals = e.target.value.split(",").map(v=>parseInt(v.trim())).filter(v=>!isNaN(v)&&v>=0&&v<24);
                set("blocked_hours",vals);
              }}
              placeholder="e.g. 0,1,2,22,23"
              style={{...inpStyle,width:"100%"}}/>
            <div style={{fontFamily:MONO,fontSize:9,color:T.t2,marginTop:5}}>
              Currently blocked: {(cfg.blocked_hours||[]).length===0?"None":(cfg.blocked_hours||[]).map(h=>h+":00").join(", ")}
            </div>
          </div>
        </Section>

        {/* ── Active Markets ── */}
        <Section title="ACTIVE MARKETS" color={T.green} icon="📊">
          <div style={{fontFamily:MONO,fontSize:9,color:T.t2,letterSpacing:1,marginBottom:10}}>
            SELECT WHICH MARKETS TO SCAN FOR SIGNALS
          </div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
            {MARKETS.map(m=>{
              const active=(cfg.markets||[]).includes(m);
              const mc={crypto:T.gold,forex:T.blue,stocks:T.green,commodities:T.purple}[m]||T.t2;
              return(
                <button key={m} onClick={()=>toggleMarket(m)}
                  style={{padding:"10px 14px",borderRadius:4,cursor:"pointer",
                    border:`1px solid ${active?mc+"60":T.border}`,
                    background:active?`${mc}15`:T.bg2,
                    color:active?mc:T.t2,fontFamily:MONO,fontSize:11,
                    textTransform:"uppercase",letterSpacing:1,
                    display:"flex",alignItems:"center",gap:8,textAlign:"left"}}>
                  <div style={{width:8,height:8,borderRadius:"50%",
                    background:active?mc:T.t3,
                    boxShadow:active?`0 0 6px ${mc}`:"none"}}/>
                  {m.charAt(0).toUpperCase()+m.slice(1)}
                </button>
              );
            })}
          </div>
          <div style={{marginTop:12,fontFamily:MONO,fontSize:9,color:T.t2,lineHeight:1.6}}>
            Active: {(cfg.markets||[]).length===0?"None":(cfg.markets||[]).map(m=>m.charAt(0).toUpperCase()+m.slice(1)).join(", ")}
          </div>
        </Section>

      </div>

      {/* Bottom save bar */}
      <div style={{position:"sticky",bottom:0,background:T.bg2,borderTop:`1px solid ${T.border}`,
        padding:"12px 20px",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{fontFamily:MONO,fontSize:10,color:T.t2}}>
          Changes take effect on the next signal scan.
        </div>
        <div style={{display:"flex",gap:10,alignItems:"center"}}>
          {saved&&<span style={{fontFamily:MONO,fontSize:11,color:T.green,animation:"slide .2s ease"}}>✓ Saved</span>}
          {error&&<span style={{fontFamily:MONO,fontSize:11,color:T.red}}>⚠ {error}</span>}
          <button onClick={save} disabled={saving}
            style={{background:`${T.blue}20`,border:`1px solid ${T.blue}50`,color:T.blue,
              borderRadius:4,padding:"8px 24px",cursor:"pointer",fontFamily:MONO,fontSize:12,
              letterSpacing:2,display:"flex",alignItems:"center",gap:7,opacity:saving?0.7:1}}>
            <Save size={13}/>{saving?"SAVING…":"SAVE ALL SETTINGS"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── SUB-COMPONENTS ────────────────────────────────────────────────────────────
function Section({title,color,icon,children}){
  return(
    <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:6,padding:16}}>
      <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:16,
        paddingBottom:10,borderBottom:`1px solid ${T.border}`}}>
        <span style={{fontSize:14}}>{icon}</span>
        <span style={{fontFamily:MONO,fontSize:10,color,letterSpacing:2}}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function Slider({label,min,max,step,val,onChange,help,color,fmt:fmtFn}){
  const display = fmtFn ? fmtFn(val) : String(val);
  const pct     = ((val-min)/(max-min))*100;
  return(
    <div style={{marginBottom:16}}>
      <div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}>
        <span style={{fontFamily:MONO,fontSize:10,color:T.text}}>{label}</span>
        <span style={{fontFamily:MONO,fontSize:12,color,fontWeight:600}}>{display}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={val}
        onChange={e=>onChange(Number(e.target.value))}
        style={{width:"100%",accentColor:color,cursor:"pointer"}}/>
      <div style={{display:"flex",justifyContent:"space-between",marginTop:3}}>
        <span style={{fontFamily:MONO,fontSize:8,color:T.t2}}>{fmtFn?fmtFn(min):min}</span>
        <span style={{fontFamily:MONO,fontSize:8,color:T.t2}}>{fmtFn?fmtFn(max):max}</span>
      </div>
      {help&&<div style={{fontFamily:UI,fontSize:11,color:T.t2,marginTop:5,lineHeight:1.5}}>{help}</div>}
    </div>
  );
}

function Toggle({label,val,onChange,help}){
  return(
    <div style={{marginBottom:14,display:"flex",alignItems:"flex-start",gap:12}}>
      <button onClick={()=>onChange(!val)}
        style={{flexShrink:0,width:42,height:22,borderRadius:11,border:"none",cursor:"pointer",
          background:val?T.green:T.t3,position:"relative",transition:"background .2s"}}>
        <div style={{position:"absolute",top:3,left:val?22:3,width:16,height:16,
          borderRadius:"50%",background:"#fff",transition:"left .2s"}}/>
      </button>
      <div>
        <div style={{fontFamily:MONO,fontSize:10,color:T.text,marginBottom:3}}>{label}</div>
        {help&&<div style={{fontFamily:UI,fontSize:11,color:T.t2,lineHeight:1.5}}>{help}</div>}
      </div>
    </div>
  );
}

const inpStyle = {
  background:T.bg2, border:`1px solid ${T.border}`, color:T.text,
  borderRadius:3, padding:"6px 10px", fontFamily:MONO, fontSize:11,
};

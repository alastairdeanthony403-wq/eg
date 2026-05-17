/**
 * Journal.jsx — NexusBot v2
 * Trade journal: stores AI reasoning, confidence, SMC score,
 * emotional notes, strategy, market type. Full filters.
 */
import { useState, useEffect, useCallback } from "react";
import {
  Plus, X, ChevronDown, ChevronUp, Search,
  BookOpen, TrendingUp, TrendingDown, Brain,
} from "lucide-react";

// ── Design tokens ─────────────────────────────────────────────────────────────
const T = {
  bg:"#050914", bg2:"#08111f", bg3:"#0d1a2e", bg4:"#111f38",
  border:"#162036",
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
@keyframes slide{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
`;

const fmt  = (n,d=2) => n==null?"—":Number(n).toFixed(d);

const MOODS = [
  {val:"confident",    label:"😤 Confident"},
  {val:"neutral",      label:"😐 Neutral"},
  {val:"anxious",      label:"😰 Anxious"},
  {val:"fomo",         label:"🚀 FOMO"},
  {val:"disciplined",  label:"🎯 Disciplined"},
  {val:"uncertain",    label:"😕 Uncertain"},
  {val:"excited",      label:"⚡ Excited"},
];

const STRATEGIES = ["SMC Unified Bot","Basic SMC","EMA + RSI","SMA Crossover","Manual"];

// ── MAIN COMPONENT ────────────────────────────────────────────────────────────
export default function Journal() {
  const [entries,    setEntries]   = useState([]);
  const [loading,    setLoading]   = useState(true);
  const [showForm,   setShowForm]  = useState(false);
  const [expanded,   setExpanded]  = useState(null);
  const [filter,     setFilter]    = useState({side:"all",result:"all",strategy:"all",search:""});
  const [stats,      setStats]     = useState({});

  // Form state
  const [form, setForm] = useState({
    symbol:"", side:"BUY", entry:"", exit:"", pnl:"",
    strategy:"SMC Unified Bot", confidence:"", smc_score:"",
    mood:"neutral", tags:"", ai_reasoning:"", notes:"",
  });
  const [saving, setSaving] = useState(false);

  const token = localStorage.getItem("token");
  const hdrs  = { "Content-Type":"application/json", Authorization:`Bearer ${token}` };

  // ── Load entries ────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/journal", {headers:hdrs});
      const d = await r.json();
      if(r.ok){
        const items = d.entries||d||[];
        setEntries(items);
        computeStats(items);
      }
    } catch{}
    finally{ setLoading(false); }
  },[]);

  useEffect(()=>{ load(); },[load]);

  // ── Save new entry ──────────────────────────────────────────────────────────
  const save = async () => {
    if(!form.symbol) return;
    setSaving(true);
    // Pack extra metadata into notes field for backends that only have one notes column
    const packed = [
      form.ai_reasoning ? `[AI REASONING]\n${form.ai_reasoning}` : "",
      form.confidence   ? `[CONFIDENCE] ${form.confidence}%`     : "",
      form.smc_score    ? `[SMC SCORE] ${form.smc_score}/9`      : "",
      form.strategy     ? `[STRATEGY] ${form.strategy}`          : "",
      form.mood         ? `[MOOD] ${form.mood}`                  : "",
      form.tags         ? `[TAGS] ${form.tags}`                  : "",
      form.notes        ? `[NOTES]\n${form.notes}`               : "",
    ].filter(Boolean).join("\n");

    try {
      const r = await fetch("/api/journal", {
        method:"POST", headers:hdrs,
        body:JSON.stringify({
          symbol:form.symbol.toUpperCase(),
          side:form.side,
          entry:Number(form.entry)||null,
          exit:Number(form.exit)||null,
          pnl:Number(form.pnl)||null,
          notes:packed,
        }),
      });
      const d = await r.json();
      if(!r.ok) throw new Error(d.error||"Save failed");
      setShowForm(false);
      setForm({symbol:"",side:"BUY",entry:"",exit:"",pnl:"",
        strategy:"SMC Unified Bot",confidence:"",smc_score:"",
        mood:"neutral",tags:"",ai_reasoning:"",notes:""});
      load();
    } catch(e){ alert(e.message); }
    finally{ setSaving(false); }
  };

  // ── Delete ──────────────────────────────────────────────────────────────────
  const del = async (id) => {
    if(!window.confirm("Delete this entry?")) return;
    try {
      const r = await fetch(`/api/journal/${id}`, {method:"DELETE",headers:hdrs});
      if(r.ok) load();
    } catch{}
  };

  // ── Stats ───────────────────────────────────────────────────────────────────
  function computeStats(items){
    const wins   = items.filter(e=>parseFloat(e.pnl)>0);
    const losses = items.filter(e=>parseFloat(e.pnl)<0);
    const netPnl = items.reduce((s,e)=>s+(parseFloat(e.pnl)||0),0);
    setStats({
      total:items.length, wins:wins.length, losses:losses.length,
      winRate:items.length?((wins.length/items.length)*100).toFixed(1):0,
      netPnl:netPnl.toFixed(2),
    });
  }

  // ── Filter ──────────────────────────────────────────────────────────────────
  const shown = entries.filter(e=>{
    const side   = filter.side==="all"||e.side===filter.side;
    const result = filter.result==="all"||
      (filter.result==="wins"&&parseFloat(e.pnl)>0)||
      (filter.result==="losses"&&parseFloat(e.pnl)<0);
    const strat  = filter.strategy==="all"||
      (e.notes||"").includes(`[STRATEGY] ${filter.strategy}`);
    const search = !filter.search||
      (e.symbol||"").toLowerCase().includes(filter.search.toLowerCase())||
      (e.notes||"").toLowerCase().includes(filter.search.toLowerCase());
    return side&&result&&strat&&search;
  });

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div style={{background:T.bg,minHeight:"100vh",fontFamily:UI,color:T.text}}>
      <style>{GS}</style>

      {/* Header */}
      <div style={{background:T.bg2,borderBottom:`1px solid ${T.border}`,padding:"12px 20px",
        display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <BookOpen size={16} style={{color:T.blue}}/>
          <span style={{fontFamily:MONO,fontSize:14,letterSpacing:3,color:T.text}}>TRADE JOURNAL</span>
        </div>
        <button onClick={()=>setShowForm(!showForm)}
          style={{background:`${T.green}18`,border:`1px solid ${T.green}50`,color:T.green,
            borderRadius:4,padding:"7px 16px",cursor:"pointer",fontFamily:MONO,fontSize:11,
            letterSpacing:1,display:"flex",alignItems:"center",gap:6}}>
          <Plus size={13}/>{showForm?"CANCEL":"LOG TRADE"}
        </button>
      </div>

      {/* Stats strip */}
      <div style={{background:T.bg3,borderBottom:`1px solid ${T.border}`,padding:"10px 20px",
        display:"flex",gap:20,flexWrap:"wrap"}}>
        {[
          {label:"TOTAL",    val:stats.total||0,   color:T.text},
          {label:"WINS",     val:stats.wins||0,    color:T.green},
          {label:"LOSSES",   val:stats.losses||0,  color:T.red},
          {label:"WIN RATE", val:(stats.winRate||0)+"%", color:T.gold},
          {label:"NET P&L",  val:(parseFloat(stats.netPnl||0)>=0?"+ $":"- $")+Math.abs(stats.netPnl||0).toFixed(2),
            color:parseFloat(stats.netPnl||0)>=0?T.green:T.red},
        ].map(s=>(
          <div key={s.label}>
            <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{s.label}</div>
            <div style={{fontFamily:MONO,fontSize:18,color:s.color,fontWeight:500}}>{s.val}</div>
          </div>
        ))}
      </div>

      {/* Add Trade Form */}
      {showForm&&(
        <div style={{margin:"16px 20px",background:T.bg3,border:`1px solid ${T.border}`,
          borderRadius:6,padding:"18px 18px",animation:"slide .2s ease"}}>
          <div style={{fontFamily:MONO,fontSize:10,color:T.gold,letterSpacing:2,marginBottom:16,
            display:"flex",alignItems:"center",gap:8}}>
            <Brain size={13}/> LOG NEW TRADE
          </div>

          {/* Row 1: Symbol, Side, Entry, Exit, PnL */}
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(130px,1fr))",gap:12,marginBottom:12}}>
            <FormField label="SYMBOL">
              <input value={form.symbol} onChange={e=>setForm({...form,symbol:e.target.value.toUpperCase()})}
                placeholder="BTCUSDT" style={inp}/>
            </FormField>
            <FormField label="SIDE">
              <select value={form.side} onChange={e=>setForm({...form,side:e.target.value})} style={sel}>
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
            </FormField>
            <FormField label="ENTRY PRICE">
              <input type="number" value={form.entry} onChange={e=>setForm({...form,entry:e.target.value})} style={inp}/>
            </FormField>
            <FormField label="EXIT PRICE">
              <input type="number" value={form.exit} onChange={e=>setForm({...form,exit:e.target.value})} style={inp}/>
            </FormField>
            <FormField label="P&L ($)">
              <input type="number" value={form.pnl} onChange={e=>setForm({...form,pnl:e.target.value})} style={inp}/>
            </FormField>
          </div>

          {/* Row 2: Strategy, Confidence, SMC Score */}
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(150px,1fr))",gap:12,marginBottom:12}}>
            <FormField label="STRATEGY">
              <select value={form.strategy} onChange={e=>setForm({...form,strategy:e.target.value})} style={sel}>
                {STRATEGIES.map(s=><option key={s} value={s}>{s}</option>)}
              </select>
            </FormField>
            <FormField label="CONFIDENCE (%)">
              <input type="number" value={form.confidence} onChange={e=>setForm({...form,confidence:e.target.value})} style={inp} min={0} max={100}/>
            </FormField>
            <FormField label="SMC SCORE (0-9)">
              <input type="number" value={form.smc_score} onChange={e=>setForm({...form,smc_score:e.target.value})} style={inp} min={0} max={9}/>
            </FormField>
            <FormField label="EMOTIONAL STATE">
              <select value={form.mood} onChange={e=>setForm({...form,mood:e.target.value})} style={sel}>
                {MOODS.map(m=><option key={m.val} value={m.val}>{m.label}</option>)}
              </select>
            </FormField>
            <FormField label="TAGS (comma separated)">
              <input value={form.tags} onChange={e=>setForm({...form,tags:e.target.value})}
                placeholder="fvg, sweep, london..." style={inp}/>
            </FormField>
          </div>

          {/* Row 3: AI Reasoning, Notes */}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:14}}>
            <FormField label="AI REASONING / SETUP NOTES">
              <textarea value={form.ai_reasoning} onChange={e=>setForm({...form,ai_reasoning:e.target.value})}
                rows={4} placeholder="Why did the bot take this trade? What confirmations aligned?"
                style={{...inp,resize:"vertical",lineHeight:1.6}}/>
            </FormField>
            <FormField label="EMOTIONAL NOTES">
              <textarea value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}
                rows={4} placeholder="How did you feel during this trade? Any FOMO? Did you follow the plan?"
                style={{...inp,resize:"vertical",lineHeight:1.6}}/>
            </FormField>
          </div>

          <div style={{display:"flex",gap:10}}>
            <button onClick={save} disabled={saving||!form.symbol}
              style={{background:`${T.green}20`,border:`1px solid ${T.green}50`,color:T.green,
                borderRadius:4,padding:"8px 22px",cursor:"pointer",fontFamily:MONO,fontSize:11,
                letterSpacing:1,opacity:saving||!form.symbol?.trim()?0.5:1}}>
              {saving?"SAVING…":"SAVE ENTRY"}
            </button>
            <button onClick={()=>setShowForm(false)}
              style={{background:"transparent",border:`1px solid ${T.border}`,color:T.t2,
                borderRadius:4,padding:"8px 16px",cursor:"pointer",fontFamily:MONO,fontSize:11,letterSpacing:1}}>
              CANCEL
            </button>
          </div>
        </div>
      )}

      {/* Filter bar */}
      <div style={{padding:"10px 20px",display:"flex",gap:10,flexWrap:"wrap",alignItems:"center",
        borderBottom:`1px solid ${T.border}`}}>
        {/* Side */}
        <div style={{display:"flex",gap:3}}>
          {["all","BUY","SELL"].map(f=>(
            <FBtn key={f} label={f==="all"?"ALL":f} active={filter.side===f}
              color={f==="BUY"?T.green:f==="SELL"?T.red:T.blue}
              onClick={()=>setFilter({...filter,side:f})}/>
          ))}
        </div>
        <div style={{width:1,height:18,background:T.border}}/>
        {/* Result */}
        <div style={{display:"flex",gap:3}}>
          {[["all","ALL"],["wins","WINS"],["losses","LOSSES"]].map(([v,l])=>(
            <FBtn key={v} label={l} active={filter.result===v}
              color={v==="wins"?T.green:v==="losses"?T.red:T.blue}
              onClick={()=>setFilter({...filter,result:v})}/>
          ))}
        </div>
        <div style={{width:1,height:18,background:T.border}}/>
        {/* Strategy */}
        <select value={filter.strategy} onChange={e=>setFilter({...filter,strategy:e.target.value})}
          style={{...sel,width:160,padding:"4px 8px",fontSize:10}}>
          <option value="all">All Strategies</option>
          {STRATEGIES.map(s=><option key={s} value={s}>{s}</option>)}
        </select>
        {/* Search */}
        <div style={{position:"relative",marginLeft:"auto"}}>
          <Search size={11} style={{position:"absolute",left:9,top:"50%",transform:"translateY(-50%)",color:T.t2}}/>
          <input value={filter.search} onChange={e=>setFilter({...filter,search:e.target.value})}
            placeholder="Search symbol, tag, note…"
            style={{...inp,paddingLeft:28,width:200,padding:"5px 10px 5px 28px"}}/>
        </div>
        <span style={{fontFamily:MONO,fontSize:10,color:T.t2}}>{shown.length} ENTRIES</span>
      </div>

      {/* Entries list */}
      <div style={{padding:"16px 20px"}}>
        {loading&&<Spinner/>}
        {!loading&&shown.length===0&&(
          <div style={{textAlign:"center",padding:60,color:T.t2,fontFamily:MONO,fontSize:12}}>
            NO JOURNAL ENTRIES YET. LOG YOUR FIRST TRADE ABOVE.
          </div>
        )}
        {!loading&&shown.map(e=>(
          <JournalCard key={e.id} entry={e}
            expanded={expanded===e.id}
            onExpand={()=>setExpanded(expanded===e.id?null:e.id)}
            onDelete={()=>del(e.id)}/>
        ))}
      </div>
    </div>
  );
}

// ── JOURNAL CARD ──────────────────────────────────────────────────────────────
function JournalCard({entry:e, expanded, onExpand, onDelete}){
  const pnl     = parseFloat(e.pnl||0);
  const win     = pnl>0;
  const lose    = pnl<0;
  const pnlColor= win?T.green:lose?T.red:T.t2;
  const notes   = e.notes||"";

  // Parse packed metadata
  const ai       = extractSection(notes,"[AI REASONING]");
  const conf     = extractTag(notes,"[CONFIDENCE]");
  const smc      = extractTag(notes,"[SMC SCORE]");
  const strat    = extractTag(notes,"[STRATEGY]");
  const mood     = extractTag(notes,"[MOOD]");
  const tags     = extractTag(notes,"[TAGS]");
  const emoNotes = extractSection(notes,"[NOTES]");

  const moodEmoji = MOODS.find(m=>m.val===mood)?.label||mood;

  return (
    <div style={{background:T.bg3,border:`1px solid ${win?T.green+"30":lose?T.red+"30":T.border}`,
      borderLeft:`3px solid ${win?T.green:lose?T.red:T.border}`,
      borderRadius:5,marginBottom:10,overflow:"hidden"}}>

      {/* Main row */}
      <div style={{padding:"12px 15px",display:"flex",alignItems:"center",gap:16,flexWrap:"wrap"}}>
        {/* Symbol + side */}
        <div style={{display:"flex",alignItems:"center",gap:10,minWidth:120}}>
          <span style={{fontFamily:MONO,fontSize:16,color:T.text}}>{e.symbol||"—"}</span>
          <span style={{fontFamily:MONO,fontSize:11,padding:"2px 10px",borderRadius:3,
            background:e.side==="BUY"?`${T.green}18`:`${T.red}18`,
            border:`1px solid ${e.side==="BUY"?T.green+"40":T.red+"40"}`,
            color:e.side==="BUY"?T.green:T.red}}>
            {e.side==="BUY"?"▲ BUY":"▼ SELL"}
          </span>
        </div>
        {/* Prices */}
        <div style={{display:"flex",gap:16}}>
          <MiniStat label="ENTRY" val={e.entry?fmt(e.entry,4):"—"} color={T.text}/>
          <MiniStat label="EXIT"  val={e.exit?fmt(e.exit,4):"—"}   color={T.text}/>
          <MiniStat label="P&L"   val={(pnl>=0?"+":"")+pnl.toFixed(2)} color={pnlColor}/>
        </div>
        {/* Badges */}
        <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
          {conf&&<Badge label={conf} color={T.gold}/>}
          {smc&&<Badge label={smc}  color={T.purple}/>}
          {strat&&<Badge label={strat} color={T.blue}/>}
          {mood&&<Badge label={moodEmoji} color={T.cyan}/>}
        </div>
        {/* Tags */}
        {tags&&(
          <div style={{display:"flex",gap:4,flexWrap:"wrap"}}>
            {tags.split(",").map(t=>(
              <span key={t} style={{fontFamily:MONO,fontSize:9,padding:"1px 7px",borderRadius:2,
                background:`${T.t2}18`,border:`1px solid ${T.t2}30`,color:T.t2}}>
                #{t.trim()}
              </span>
            ))}
          </div>
        )}
        {/* Date + actions */}
        <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:10}}>
          <span style={{fontFamily:MONO,fontSize:10,color:T.t2}}>
            {e.created_at?.slice(0,16)||"—"}
          </span>
          <button onClick={onExpand}
            style={{background:T.bg2,border:`1px solid ${T.border}`,color:T.t2,
              borderRadius:3,padding:"4px 9px",cursor:"pointer",display:"flex",alignItems:"center",gap:4,
              fontFamily:MONO,fontSize:9}}>
            {expanded?<ChevronUp size={11}/>:<ChevronDown size={11}/>}
            DETAIL
          </button>
          <button onClick={onDelete}
            style={{background:`${T.red}10`,border:`1px solid ${T.red}30`,color:T.red,
              borderRadius:3,padding:"4px 9px",cursor:"pointer",fontFamily:MONO,fontSize:9}}>
            <X size={11}/>
          </button>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded&&(
        <div style={{borderTop:`1px solid ${T.border}`,background:T.bg2,
          padding:"14px 15px",animation:"slide .2s ease"}}>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}>
            {/* AI reasoning */}
            {ai&&(
              <div>
                <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:8}}>
                  <Brain size={12} style={{color:T.purple}}/>
                  <span style={{fontFamily:MONO,fontSize:8,color:T.purple,letterSpacing:2}}>
                    AI REASONING / SETUP NOTES
                  </span>
                </div>
                <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:4,
                  padding:"10px 12px",fontSize:12,color:T.text,lineHeight:1.7,fontFamily:UI}}>
                  {ai}
                </div>
              </div>
            )}
            {/* Emotional notes */}
            {emoNotes&&(
              <div>
                <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:8}}>
                  <span style={{fontFamily:MONO,fontSize:8,color:T.cyan,letterSpacing:2}}>
                    EMOTIONAL / PROCESS NOTES
                  </span>
                </div>
                <div style={{background:T.bg3,border:`1px solid ${T.border}`,borderRadius:4,
                  padding:"10px 12px",fontSize:12,color:T.text,lineHeight:1.7,fontFamily:UI}}>
                  {emoNotes}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── HELPERS ───────────────────────────────────────────────────────────────────
function extractSection(notes, tag){
  if(!notes||!notes.includes(tag)) return "";
  const after = notes.split(tag)[1]||"";
  // Stop at next [TAG]
  const nextTag = after.indexOf("\n[");
  return (nextTag>=0 ? after.slice(0,nextTag) : after).trim();
}
function extractTag(notes, tag){
  if(!notes||!notes.includes(tag)) return "";
  const after = notes.split(tag)[1]||"";
  return after.split("\n")[0].trim();
}

const MiniStat=({label,val,color})=>(
  <div>
    <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:1,marginBottom:2}}>{label}</div>
    <div style={{fontFamily:MONO,fontSize:12,color}}>{val}</div>
  </div>
);

const Badge=({label,color})=>(
  <span style={{fontFamily:MONO,fontSize:9,padding:"2px 8px",borderRadius:2,
    background:`${color}18`,border:`1px solid ${color}40`,color}}>{label}</span>
);

const FBtn=({label,active,color,onClick})=>(
  <button onClick={onClick}
    style={{padding:"4px 11px",borderRadius:3,cursor:"pointer",
      border:`1px solid ${active?color:T.border}`,
      background:active?`${color}20`:"transparent",
      color:active?color:T.t2,fontFamily:MONO,fontSize:10,fontWeight:700,letterSpacing:1}}>
    {label}
  </button>
);

function FormField({label,children}){
  return(
    <div>
      <div style={{fontFamily:MONO,fontSize:8,color:T.t2,letterSpacing:2,marginBottom:5}}>{label}</div>
      {children}
    </div>
  );
}

const inp={background:T.bg2,border:`1px solid ${T.border}`,color:T.text,
  borderRadius:3,padding:"6px 10px",width:"100%",fontFamily:MONO,fontSize:11};
const sel={background:T.bg2,border:`1px solid ${T.border}`,color:T.text,
  borderRadius:3,padding:"6px 10px",width:"100%",fontFamily:MONO,fontSize:11};

function Spinner(){
  return(
    <div style={{display:"flex",justifyContent:"center",alignItems:"center",height:200,gap:12,color:T.t2}}>
      <div style={{width:30,height:30,border:`2px solid ${T.border}`,
        borderTop:`2px solid ${T.blue}`,borderRadius:"50%",animation:"spin 1s linear infinite"}}/>
      <span style={{fontFamily:MONO,fontSize:11,letterSpacing:2}}>LOADING JOURNAL…</span>
    </div>
  );
}

/**
 * Journal.jsx — v2
 * Trade journal with AI reasoning storage, confidence display,
 * emotional notes, and strategy/market filters.
 */
import React, { useState, useEffect, useCallback } from "react";

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
const inp = { width: "100%", fontFamily: C.mono, fontSize: 10, padding: "7px 10px",
              borderRadius: 6, background: C.bg3, border: `1px solid ${C.bdr}`,
              color: C.t0, outline: "none" };

const MOODS   = ["😊 Great","😐 Neutral","😰 Anxious","🎯 Focused","🎲 FOMO","😤 Frustrated","🤑 Greedy"];
const MARKETS = ["crypto","forex","stocks","commodities"];
const STRATS  = ["unified_bot","simple_ma","vwap_ema","orb_0dte","manual"];

/* ══════════════════════════════════════════════════════
   NEW ENTRY FORM
══════════════════════════════════════════════════════ */
const NewEntry = ({ onSaved, prefill }) => {
  const blank = {
    symbol: "BTCUSDT", side: "BUY",
    entry: "", exit: "", pnl: "",
    mood: "😐 Neutral",
    strategy: "unified_bot",
    confidence: "", smc_score: "",
    tags: "", notes: "",
    ai_reasoning: "",
  };
  const [form, setForm] = useState({ ...blank, ...(prefill || {}) });
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);

  const upd = k => e => setForm(f => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      const tags = form.tags ? form.tags.split(",").map(t => t.trim()).filter(Boolean) : [];
      const notes = [
        form.notes,
        form.ai_reasoning ? `\n[AI REASONING]\n${form.ai_reasoning}` : "",
        form.confidence    ? `\n[CONFIDENCE] ${form.confidence}%` : "",
        form.smc_score     ? `\n[SMC SCORE] ${form.smc_score}/9` : "",
        form.strategy      ? `\n[STRATEGY] ${form.strategy}` : "",
      ].filter(Boolean).join("");

      await api("/api/journal", {
        method: "POST",
        body: JSON.stringify({
          symbol: form.symbol.toUpperCase(),
          side: form.side,
          entry: parseFloat(form.entry) || 0,
          exit:  parseFloat(form.exit)  || 0,
          pnl:   parseFloat(form.pnl)   || 0,
          mood:  form.mood,
          tags, notes,
        }),
      });
      setForm(blank);
      setOpen(false);
      onSaved?.();
    } finally { setSaving(false); }
  };

  const Label = ({ children }) => (
    <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 4 }}>{children}</div>
  );

  return (
    <div style={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8, marginBottom: 16 }}>
      <button onClick={() => setOpen(x => !x)} style={{
        width: "100%", fontFamily: C.mono, fontSize: 10, fontWeight: 700,
        padding: "12px 16px", background: "transparent",
        border: "none", cursor: "pointer",
        color: open ? C.t0 : C.t1, textAlign: "left",
        display: "flex", justifyContent: "space-between",
      }}>
        <span>{open ? "▼" : "▶"} LOG NEW TRADE</span>
        {!open && <span style={{ color: C.t2, fontWeight: 400 }}>Click to expand</span>}
      </button>

      {open && (
        <div style={{ padding: "0 16px 16px" }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
            <div style={{ flex: 1, minWidth: 100 }}>
              <Label>SYMBOL</Label>
              <input value={form.symbol} onChange={upd("symbol")} style={{ ...inp }} />
            </div>
            <div style={{ flex: 1, minWidth: 80 }}>
              <Label>SIDE</Label>
              <select value={form.side} onChange={upd("side")} style={{ ...inp }}>
                <option>BUY</option><option>SELL</option>
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 100 }}>
              <Label>ENTRY PRICE</Label>
              <input type="number" value={form.entry} onChange={upd("entry")} style={{ ...inp }} />
            </div>
            <div style={{ flex: 1, minWidth: 100 }}>
              <Label>EXIT PRICE</Label>
              <input type="number" value={form.exit} onChange={upd("exit")} style={{ ...inp }} />
            </div>
            <div style={{ flex: 1, minWidth: 80 }}>
              <Label>PnL ($)</Label>
              <input type="number" value={form.pnl} onChange={upd("pnl")} style={{ ...inp }} />
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
            <div style={{ flex: 1, minWidth: 120 }}>
              <Label>STRATEGY</Label>
              <select value={form.strategy} onChange={upd("strategy")} style={{ ...inp }}>
                {STRATS.map(s => <option key={s}>{s}</option>)}
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 80 }}>
              <Label>CONFIDENCE %</Label>
              <input type="number" min={0} max={100} value={form.confidence} onChange={upd("confidence")} style={{ ...inp }} />
            </div>
            <div style={{ flex: 1, minWidth: 80 }}>
              <Label>SMC SCORE /9</Label>
              <input type="number" min={0} max={9} value={form.smc_score} onChange={upd("smc_score")} style={{ ...inp }} />
            </div>
            <div style={{ flex: 1, minWidth: 150 }}>
              <Label>EMOTIONAL STATE</Label>
              <select value={form.mood} onChange={upd("mood")} style={{ ...inp }}>
                {MOODS.map(m => <option key={m}>{m}</option>)}
              </select>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
            <div style={{ flex: 1 }}>
              <Label>TAGS (comma-separated)</Label>
              <input value={form.tags} onChange={upd("tags")} placeholder="e.g. fvg, london, sweep"
                style={{ ...inp }} />
            </div>
          </div>

          <div style={{ marginBottom: 10 }}>
            <Label>AI REASONING / TRADE NOTES</Label>
            <textarea value={form.ai_reasoning} onChange={upd("ai_reasoning")}
              rows={3} placeholder="Why did the bot take this trade? What confirmations aligned?"
              style={{ ...inp, resize: "vertical" }} />
          </div>

          <div style={{ marginBottom: 12 }}>
            <Label>EMOTIONAL NOTES</Label>
            <textarea value={form.notes} onChange={upd("notes")}
              rows={2} placeholder="How were you feeling? Did you override the bot?"
              style={{ ...inp, resize: "vertical" }} />
          </div>

          <button onClick={save} disabled={saving} style={{
            fontFamily: C.mono, fontSize: 10, fontWeight: 700,
            padding: "8px 20px", borderRadius: 7, cursor: saving ? "wait" : "pointer",
            background: C.buy + "22", border: `1px solid ${C.buy}55`, color: C.buy,
          }}>
            {saving ? "Saving…" : "💾 Save Trade"}
          </button>
        </div>
      )}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   JOURNAL CARD
══════════════════════════════════════════════════════ */
const JournalCard = ({ entry, onDelete }) => {
  const [expanded, setExpanded] = useState(false);
  const pos   = entry.pnl >= 0;
  const sigC  = entry.side === "BUY" ? C.buy : C.sell;
  const notes = entry.notes || "";

  // Parse embedded metadata from notes
  const confMatch  = notes.match(/\[CONFIDENCE\]\s*(\d+)%/);
  const smcMatch   = notes.match(/\[SMC SCORE\]\s*([\d]+)\/9/);
  const stratMatch = notes.match(/\[STRATEGY\]\s*(.+?)(\n|$)/);
  const reasonMatch = notes.match(/\[AI REASONING\]\n([\s\S]+?)(?:\[|$)/);

  const confidence = confMatch  ? parseInt(confMatch[1])  : null;
  const smcScore   = smcMatch   ? smcMatch[1]              : null;
  const strategy   = stratMatch ? stratMatch[1].trim()     : null;
  const aiReason   = reasonMatch ? reasonMatch[1].trim()   : null;
  const cleanNotes = notes
    .replace(/\[AI REASONING\][\s\S]*?(?=\[|$)/g, "")
    .replace(/\[CONFIDENCE\][^\n]*/g, "")
    .replace(/\[SMC SCORE\][^\n]*/g, "")
    .replace(/\[STRATEGY\][^\n]*/g, "")
    .trim();

  return (
    <div style={{
      background: C.bg1, border: `1px solid ${sigC}33`,
      borderRadius: 10, padding: 14, fontFamily: C.ui,
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <div style={{ fontFamily: C.mono, fontSize: 14, fontWeight: 800, color: C.t0 }}>
            {entry.symbol}
          </div>
          <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginTop: 1 }}>
            {(entry.created_at || "").slice(0, 16)}
          </div>
        </div>
        <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
          {strategy && (
            <span style={{ fontFamily: C.mono, fontSize: 8, padding: "2px 6px", borderRadius: 3,
              background: C.bg3, color: C.t2, border: `1px solid ${C.bdr}` }}>
              {strategy}
            </span>
          )}
          <span style={{ fontFamily: C.mono, fontSize: 11, fontWeight: 700,
            padding: "3px 10px", borderRadius: 5,
            background: sigC + "18", color: sigC,
            border: `1px solid ${sigC}44` }}>
            {entry.side === "BUY" ? "▲" : "▼"} {entry.side}
          </span>
        </div>
      </div>

      {/* Price + PnL */}
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <div style={{ flex: 1, background: C.bg2, borderRadius: 6, padding: "8px 10px" }}>
          <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 2 }}>ENTRY → EXIT</div>
          <div style={{ fontFamily: C.mono, fontSize: 12, color: C.t0 }}>
            {fn(entry.entry, 4)} → {fn(entry.exit, 4)}
          </div>
        </div>
        <div style={{
          padding: "8px 14px", borderRadius: 6,
          background: pos ? C.buy + "18" : C.sell + "18",
          border: `1px solid ${pos ? C.buy : C.sell}33`,
        }}>
          <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginBottom: 2 }}>PnL</div>
          <div style={{ fontFamily: C.mono, fontSize: 16, fontWeight: 800,
            color: pos ? C.buy : C.sell }}>
            {pos ? "+" : ""}${fn(entry.pnl)}
          </div>
        </div>
      </div>

      {/* Metrics row */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
        {confidence !== null && (
          <span style={{ fontFamily: C.mono, fontSize: 9, padding: "2px 8px", borderRadius: 4,
            background: confidence >= 70 ? C.buy + "18" : C.gold + "18",
            color: confidence >= 70 ? C.buy : C.gold,
            border: `1px solid ${confidence >= 70 ? C.buy : C.gold}40` }}>
            Conf: {confidence}%
          </span>
        )}
        {smcScore !== null && (
          <span style={{ fontFamily: C.mono, fontSize: 9, padding: "2px 8px", borderRadius: 4,
            background: C.bg3, color: C.t1, border: `1px solid ${C.bdr}` }}>
            SMC: {smcScore}/9
          </span>
        )}
        <span style={{ fontFamily: C.mono, fontSize: 9, padding: "2px 8px", borderRadius: 4,
          background: C.bg3, color: C.t1, border: `1px solid ${C.bdr}` }}>
          {entry.mood || "—"}
        </span>
        {(entry.tags || []).map(t => (
          <span key={t} style={{ fontFamily: C.mono, fontSize: 8, padding: "2px 6px", borderRadius: 3,
            background: C.hold + "18", color: C.hold, border: `1px solid ${C.hold}33` }}>
            #{t}
          </span>
        ))}
      </div>

      {/* Notes preview */}
      {cleanNotes && (
        <div style={{ fontFamily: C.ui, fontSize: 10, color: C.t2,
          padding: "6px 8px", background: C.bg2, borderRadius: 5, marginBottom: 8,
          fontStyle: "italic" }}>
          "{cleanNotes.slice(0, 120)}{cleanNotes.length > 120 ? "…" : ""}"
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 6 }}>
        {aiReason && (
          <button onClick={() => setExpanded(x => !x)} style={{
            fontFamily: C.mono, fontSize: 9, padding: "5px 10px",
            borderRadius: 5, cursor: "pointer",
            background: expanded ? C.bg3 : "transparent",
            border: `1px solid ${C.bdr}`, color: C.t1,
          }}>
            {expanded ? "▲ Hide AI" : "▼ AI Reasoning"}
          </button>
        )}
        <button onClick={() => onDelete(entry.id)} style={{
          fontFamily: C.mono, fontSize: 9, padding: "5px 10px",
          borderRadius: 5, cursor: "pointer",
          background: "transparent", border: `1px solid ${C.bdr}`,
          color: C.t2, marginLeft: "auto",
        }}>
          🗑
        </button>
      </div>

      {/* AI reasoning expanded */}
      {expanded && aiReason && (
        <div style={{
          marginTop: 10, padding: 12, borderRadius: 7,
          background: C.bg0, border: `1px solid ${C.bdr}`,
          fontFamily: C.mono, fontSize: 9, color: C.t1, lineHeight: 1.7,
        }}>
          <div style={{ fontWeight: 700, color: C.t0, marginBottom: 6, fontSize: 10 }}>
            🤖 AI REASONING
          </div>
          {aiReason}
        </div>
      )}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   STATS SUMMARY
══════════════════════════════════════════════════════ */
const JournalStats = ({ entries }) => {
  const total   = entries.length;
  const wins    = entries.filter(e => e.pnl > 0).length;
  const net     = entries.reduce((a, e) => a + (e.pnl || 0), 0);
  const avgConf = (() => {
    const confEntries = entries.filter(e => {
      const m = (e.notes || "").match(/\[CONFIDENCE\]\s*(\d+)%/);
      return m;
    });
    if (!confEntries.length) return null;
    const sum = confEntries.reduce((a, e) => {
      const m = (e.notes || "").match(/\[CONFIDENCE\]\s*(\d+)%/);
      return a + parseInt(m[1]);
    }, 0);
    return Math.round(sum / confEntries.length);
  })();

  if (!total) return null;
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
      {[
        { l: "TRADES",    v: total, c: C.t0 },
        { l: "WINS",      v: wins,  c: C.buy },
        { l: "LOSSES",    v: total - wins, c: C.sell },
        { l: "WIN RATE",  v: total ? `${Math.round(wins / total * 100)}%` : "—",
          c: wins / total >= 0.5 ? C.buy : C.sell },
        { l: "NET PnL",   v: `${net >= 0 ? "+" : ""}$${fn(net)}`,
          c: net >= 0 ? C.buy : C.sell },
        ...(avgConf !== null ? [{ l: "AVG CONF", v: `${avgConf}%`, c: avgConf >= 70 ? C.buy : C.gold }] : []),
      ].map(({ l, v, c }) => (
        <div key={l} style={{ flex: "1 1 90px", background: C.bg1,
          border: `1px solid ${C.bdr}`, borderRadius: 8, padding: "10px 14px" }}>
          <div style={{ fontFamily: C.mono, fontSize: 8, color: C.t2 }}>{l}</div>
          <div style={{ fontFamily: C.mono, fontSize: 20, fontWeight: 800, color: c, marginTop: 2 }}>{v}</div>
        </div>
      ))}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   MAIN JOURNAL
══════════════════════════════════════════════════════ */
export default function Journal() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ side: "All", mood: "All", strategy: "All", pnl: "All" });
  const [search,  setSearch]  = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api("/api/journal");
      const d = await r.json();
      setEntries(Array.isArray(d) ? d : []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const del = async id => {
    if (!window.confirm("Delete this entry?")) return;
    await api(`/api/journal/${id}`, { method: "DELETE" });
    load();
  };

  const filtered = entries.filter(e => {
    if (filters.side     !== "All" && e.side !== filters.side) return false;
    if (filters.pnl      === "Wins" && e.pnl <= 0)             return false;
    if (filters.pnl      === "Losses" && e.pnl > 0)            return false;
    if (filters.strategy !== "All") {
      const m = (e.notes || "").match(/\[STRATEGY\]\s*(.+?)(\n|$)/);
      if (!m || m[1].trim() !== filters.strategy) return false;
    }
    if (search) {
      const q = search.toLowerCase();
      if (!e.symbol?.toLowerCase().includes(q) &&
          !e.notes?.toLowerCase().includes(q) &&
          !(e.tags || []).some(t => t.includes(q))) return false;
    }
    return true;
  });

  const FBtn = ({ label, active, onClick }) => (
    <button onClick={onClick} style={{
      fontFamily: C.mono, fontSize: 9, fontWeight: active ? 700 : 400,
      padding: "4px 10px", borderRadius: 5, cursor: "pointer",
      background: active ? C.bg3 : "transparent",
      border: `1px solid ${active ? C.bdr : "transparent"}`,
      color: active ? C.t0 : C.t2,
    }}>{label}</button>
  );

  return (
    <div style={{ background: C.bg0, minHeight: "100vh", fontFamily: C.ui }}>
      <div style={{ background: C.bg1, borderBottom: `1px solid ${C.bdr}`,
        padding: "10px 20px", fontFamily: C.mono, fontSize: 14, fontWeight: 800, color: C.t0 }}>
        <span style={{ color: C.gold }}>▸</span> TRADE JOURNAL
      </div>

      <div style={{ padding: 20, maxWidth: 1000 }}>
        <NewEntry onSaved={load} />

        <JournalStats entries={entries} />

        {/* Filters */}
        <div style={{ background: C.bg1, border: `1px solid ${C.bdr}`, borderRadius: 8,
          padding: "10px 14px", marginBottom: 14 }}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ display: "flex", gap: 3 }}>
              <span style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginRight: 3 }}>SIDE</span>
              {["All","BUY","SELL"].map(v => (
                <FBtn key={v} label={v} active={filters.side === v}
                  onClick={() => setFilters(f => ({ ...f, side: v }))} />
              ))}
            </div>
            <div style={{ display: "flex", gap: 3 }}>
              <span style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginRight: 3 }}>RESULT</span>
              {["All","Wins","Losses"].map(v => (
                <FBtn key={v} label={v} active={filters.pnl === v}
                  onClick={() => setFilters(f => ({ ...f, pnl: v }))} />
              ))}
            </div>
            <div style={{ display: "flex", gap: 3 }}>
              <span style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginRight: 3 }}>STRAT</span>
              {["All", ...STRATS].map(v => (
                <FBtn key={v} label={v === "All" ? "All" : v.replace("_", " ")}
                  active={filters.strategy === v}
                  onClick={() => setFilters(f => ({ ...f, strategy: v }))} />
              ))}
            </div>
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search symbol, tag, note…"
              style={{ ...inp, flex: 1, minWidth: 150, maxWidth: 260 }} />
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: 40, fontFamily: C.mono, color: C.t2 }}>
            Loading journal…
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40, fontFamily: C.mono, color: C.t2 }}>
            {entries.length === 0 ? "No entries yet. Log your first trade above." : "No entries match filters."}
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontFamily: C.mono, fontSize: 9, color: C.t2, marginBottom: 4 }}>
              Showing {filtered.length} of {entries.length} entries
            </div>
            {filtered.map(e => (
              <JournalCard key={e.id} entry={e} onDelete={del} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}



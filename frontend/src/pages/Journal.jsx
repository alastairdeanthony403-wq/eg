import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Plus, Trash2, BookOpen } from "lucide-react";

const MOODS = [
  { v: "confident", e: "🎯", l: "Confident" },
  { v: "neutral", e: "😐", l: "Neutral" },
  { v: "rushed", e: "⚡", l: "Rushed" },
  { v: "fearful", e: "😬", l: "Fearful" },
  { v: "fomo", e: "🚀", l: "FOMO" },
];

export default function Journal() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ symbol: "BTCUSDT", side: "BUY", entry: 0, exit: 0, pnl: 0, mood: "neutral", tags: "", notes: "" });

  const load = () => api.get("/journal").then(({ data }) => setItems(data || [])).catch(() => {});
  useEffect(() => { load(); }, []);

  const save = async () => {
    await api.post("/journal", { ...form, tags: form.tags.split(",").map((s) => s.trim()).filter(Boolean) });
    setOpen(false); setForm({ symbol: "BTCUSDT", side: "BUY", entry: 0, exit: 0, pnl: 0, mood: "neutral", tags: "", notes: "" });
    load();
  };

  const del = async (id) => { if (window.confirm("Delete entry?")) { await api.delete(`/journal/${id}`); load(); } };

  return (
    <div className="space-y-6 fade-up" data-testid="journal-page">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="section-title">Reflection</div>
          <h1 className="text-3xl font-bold mt-1">Trade Journal</h1>
          <p className="text-[var(--text-dim)] text-sm mt-1">Log every trade to find your edge — and your leaks.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setOpen(true)} data-testid="journal-new-btn"><Plus size={14}/>New entry</button>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setOpen(false)} data-testid="journal-modal">
          <div className="panel p-6 max-w-2xl w-full" onClick={(e) => e.stopPropagation()}>
            <div className="text-xl font-bold mb-4">New journal entry</div>
            <div className="grid sm:grid-cols-2 gap-3">
              <div><label className="text-xs text-[var(--text-mute)]">Symbol</label>
                <input className="input mono" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })} data-testid="j-symbol"/></div>
              <div><label className="text-xs text-[var(--text-mute)]">Side</label>
                <select className="input" value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })} data-testid="j-side">
                  <option value="BUY">BUY</option><option value="SELL">SELL</option></select></div>
              <div><label className="text-xs text-[var(--text-mute)]">Entry</label>
                <input className="input mono" type="number" step="0.01" value={form.entry} onChange={(e) => setForm({ ...form, entry: parseFloat(e.target.value) || 0 })} data-testid="j-entry"/></div>
              <div><label className="text-xs text-[var(--text-mute)]">Exit</label>
                <input className="input mono" type="number" step="0.01" value={form.exit} onChange={(e) => setForm({ ...form, exit: parseFloat(e.target.value) || 0 })} data-testid="j-exit"/></div>
              <div><label className="text-xs text-[var(--text-mute)]">PnL ($)</label>
                <input className="input mono" type="number" step="0.01" value={form.pnl} onChange={(e) => setForm({ ...form, pnl: parseFloat(e.target.value) || 0 })} data-testid="j-pnl"/></div>
              <div><label className="text-xs text-[var(--text-mute)]">Tags (comma)</label>
                <input className="input" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder="bos, sweep, NY" data-testid="j-tags"/></div>
            </div>
            <div className="mt-3">
              <label className="text-xs text-[var(--text-mute)]">Mood</label>
              <div className="flex gap-2 flex-wrap mt-1">
                {MOODS.map((m) => (
                  <button key={m.v} onClick={() => setForm({ ...form, mood: m.v })} data-testid={`j-mood-${m.v}`}
                    className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 border ${form.mood === m.v ? "border-[var(--accent)] text-[var(--accent)] bg-[rgba(0,255,163,0.06)]" : "border-[var(--line-2)] text-[var(--text-mute)]"}`}>
                    <span>{m.e}</span> {m.l}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-3">
              <label className="text-xs text-[var(--text-mute)]">Notes</label>
              <textarea className="input min-h-[100px]" rows={4} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} data-testid="j-notes"
                placeholder="What did you see? What did you feel? What would you do differently?"/>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button className="btn btn-ghost" onClick={() => setOpen(false)} data-testid="j-cancel">Cancel</button>
              <button className="btn btn-primary" onClick={save} data-testid="j-save">Save entry</button>
            </div>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div className="panel p-10 text-center text-[var(--text-mute)]" data-testid="journal-empty">
          <BookOpen size={32} className="mx-auto mb-3 opacity-50" />
          <div>No entries yet. Log your first trade to start spotting patterns.</div>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((e) => {
            const mood = MOODS.find((m) => m.v === e.mood);
            return (
              <div key={e.id} className="panel p-5" data-testid={`journal-entry-${e.id}`}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <div className="font-bold">{e.symbol}</div>
                    <span className={`pill ${e.side === "BUY" ? "pill-buy" : "pill-sell"}`}>{e.side}</span>
                  </div>
                  <button onClick={() => del(e.id)} className="text-[var(--text-mute)] hover:text-[var(--sell)]" data-testid={`j-del-${e.id}`}><Trash2 size={14}/></button>
                </div>
                <div className={`mono text-xl font-bold mb-2 ${e.pnl >= 0 ? "num-pos" : "num-neg"}`}>{e.pnl >= 0 ? "+" : ""}${e.pnl.toFixed(2)}</div>
                <div className="text-xs text-[var(--text-dim)] mono mb-3">Entry {e.entry} · Exit {e.exit}</div>
                {mood && <div className="text-sm mb-3">{mood.e} {mood.l}</div>}
                {e.notes && <div className="text-sm text-[var(--text-dim)] leading-relaxed mb-3">{e.notes}</div>}
                {e.tags?.length > 0 && (
                  <div className="flex gap-1 flex-wrap">
                    {e.tags.map((t, i) => <span key={i} className="text-[10px] mono px-2 py-0.5 rounded bg-[var(--bg-3)] text-[var(--text-dim)]">#{t}</span>)}
                  </div>
                )}
                <div className="text-[10px] mono text-[var(--text-mute)] mt-3">{e.created_at}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

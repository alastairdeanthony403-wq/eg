import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Save, Settings as SettingsIcon, Shield, Brain, Globe } from "lucide-react";

const ALL_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"];

export default function Settings() {
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => { api.get("/settings").then(({ data }) => setCfg(data)).catch(() => {}); }, []);

  if (!cfg) return <div className="text-[var(--text-mute)]">Loading...</div>;

  const set = (k, v) => setCfg({ ...cfg, [k]: v });
  const toggleSym = (s) => {
    const has = cfg.symbols.includes(s);
    set("symbols", has ? cfg.symbols.filter((x) => x !== s) : [...cfg.symbols, s]);
  };

  const save = async () => {
    setSaving(true);
    try { const { data } = await api.post("/settings", cfg); setCfg(data); setSavedAt(new Date()); }
    catch {} finally { setSaving(false); }
  };

  return (
    <div className="space-y-6 fade-up max-w-5xl" data-testid="settings-page">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="section-title">Configuration</div>
          <h1 className="text-3xl font-bold mt-1">Strategy & Risk</h1>
          <p className="text-[var(--text-dim)] text-sm mt-1">Tune signal filters, anti-overtrading limits, and trading mode.</p>
        </div>
        <button className="btn btn-primary" onClick={save} disabled={saving} data-testid="settings-save-btn">
          <Save size={14} /> {saving ? "Saving..." : "Save changes"}
        </button>
      </div>
      {savedAt && <div className="text-xs text-[var(--accent)]" data-testid="settings-saved">Saved {savedAt.toLocaleTimeString()}</div>}

      {/* Trading mode */}
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4"><Globe size={16} className="text-[var(--accent)]" /><div className="section-title">Trading mode</div></div>
        <div className="grid sm:grid-cols-2 gap-3">
          {[
            { v: "local_paper", t: "Local Paper", d: "Fully simulated. Virtual balance, zero exchange calls." },
            { v: "testnet", t: "Exchange Testnet", d: "Routes to Binance/Coinbase testnet. Requires API keys (configure in env)." },
          ].map((m) => (
            <button key={m.v} onClick={() => set("trading_mode", m.v)} data-testid={`mode-${m.v}`}
              className={`panel-flat p-4 text-left transition ${cfg.trading_mode === m.v ? "border-[var(--accent)]" : ""}`}
              style={cfg.trading_mode === m.v ? { borderColor: "var(--accent)", boxShadow: "var(--glow-mint)" } : {}}>
              <div className="font-bold mb-1">{m.t}</div>
              <div className="text-xs text-[var(--text-dim)]">{m.d}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Symbols */}
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4"><SettingsIcon size={16} className="text-[var(--accent-2)]" /><div className="section-title">Watched symbols</div></div>
        <div className="flex gap-2 flex-wrap">
          {ALL_SYMBOLS.map((s) => {
            const on = cfg.symbols.includes(s);
            return (
              <button key={s} onClick={() => toggleSym(s)} data-testid={`sym-toggle-${s}`}
                className={`px-4 py-2 rounded-lg mono text-sm font-semibold transition border ${on ? "border-[var(--accent)] text-[var(--accent)] bg-[rgba(0,255,163,0.06)]" : "border-[var(--line-2)] text-[var(--text-mute)]"}`}>
                {s}
              </button>
            );
          })}
        </div>
      </div>

      {/* Strategy */}
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4"><Brain size={16} className="text-[var(--accent)]" /><div className="section-title">Signal filters</div></div>
        <div className="grid sm:grid-cols-2 gap-4">
          {[
            { k: "min_confidence", l: "Min confidence (%)", min: 50, max: 95 },
            { k: "min_smc_score", l: "Min SMC score (0-9)", min: 0, max: 9 },
            { k: "risk_reward", l: "Risk/Reward ratio", step: 0.1 },
            { k: "min_volume_multiplier", l: "Min volume multiplier", step: 0.1 },
          ].map((f) => (
            <div key={f.k}>
              <label className="text-xs text-[var(--text-mute)] mb-1 block">{f.l}</label>
              <input className="input mono" type="number" step={f.step || 1}
                value={cfg[f.k]} onChange={(e) => set(f.k, parseFloat(e.target.value) || 0)} data-testid={`cfg-${f.k}`} />
            </div>
          ))}
        </div>
        <div className="flex gap-6 mt-4">
          {[
            { k: "avoid_quiet_market", l: "Avoid quiet markets" },
            { k: "avoid_sideways_market", l: "Avoid sideways markets" },
          ].map((t) => (
            <label key={t.k} className="flex items-center gap-2 cursor-pointer text-sm">
              <input type="checkbox" checked={cfg[t.k]} onChange={(e) => set(t.k, e.target.checked)} data-testid={`cfg-${t.k}`}
                className="w-4 h-4 accent-[var(--accent)]"/>
              {t.l}
            </label>
          ))}
        </div>
      </div>

      {/* Risk */}
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4"><Shield size={16} className="text-[var(--warn)]" /><div className="section-title">Risk management</div></div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            { k: "starting_balance", l: "Starting balance ($)" },
            { k: "risk_percent", l: "Risk per trade (%)", step: 0.1 },
            { k: "max_trades_per_day", l: "Max trades / day" },
            { k: "max_daily_loss_percent", l: "Max daily loss (%)" },
            { k: "max_consecutive_losses", l: "Max consecutive losses" },
          ].map((f) => (
            <div key={f.k}>
              <label className="text-xs text-[var(--text-mute)] mb-1 block">{f.l}</label>
              <input className="input mono" type="number" step={f.step || 1}
                value={cfg[f.k]} onChange={(e) => set(f.k, parseFloat(e.target.value) || 0)} data-testid={`cfg-${f.k}`}/>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

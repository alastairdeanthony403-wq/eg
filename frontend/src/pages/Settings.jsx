/**
 * Settings.jsx — v2
 * Full bot configuration UI: AI aggressiveness, confidence threshold,
 * session filters, ATR multiplier, risk management, trailing stop,
 * fallback strategy, market selection toggles.
 */
import React, { useState, useEffect, useCallback } from "react";

/* ══════════════════════════════════════════════════════
   THEME
══════════════════════════════════════════════════════ */
const C = {
  bg0: "#020917", bg1: "#071428", bg2: "#0c1d3a", bg3: "#11264a",
  bdr: "#1a3356",
  buy: "#00e5a0", sell: "#ff4266", hold: "#4a9eff", gold: "#f59e0b",
  purple: "#a78bfa",
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

/* ══════════════════════════════════════════════════════
   ATOMS
══════════════════════════════════════════════════════ */
const SectionTitle = ({ icon, title, subtitle }) => (
  <div style={{ marginBottom: 16 }}>
    <div style={{ fontFamily: C.mono, fontSize: 12, fontWeight: 800, color: C.t0, letterSpacing: ".06em" }}>
      {icon} {title}
    </div>
    {subtitle && (
      <div style={{ fontFamily: C.ui, fontSize: 10, color: C.t2, marginTop: 2 }}>{subtitle}</div>
    )}
  </div>
);

const SettingRow = ({ label, hint, children }) => (
  <div style={{
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "12px 0", borderBottom: `1px solid ${C.bdr}55`,
    gap: 16,
  }}>
    <div style={{ flex: 1 }}>
      <div style={{ fontFamily: C.mono, fontSize: 10, fontWeight: 600, color: C.t0 }}>{label}</div>
      {hint && <div style={{ fontFamily: C.ui, fontSize: 9, color: C.t2, marginTop: 2 }}>{hint}</div>}
    </div>
    <div style={{ flexShrink: 0 }}>{children}</div>
  </div>
);

const Toggle = ({ value, onChange, onColor, label }) => (
  <button onClick={() => onChange(!value)} style={{
    display: "flex", alignItems: "center", gap: 8,
    fontFamily: C.mono, fontSize: 9, fontWeight: 700,
    padding: "6px 12px", borderRadius: 20, cursor: "pointer",
    background: value ? (onColor || C.buy) + "22" : C.bg3,
    border: `1px solid ${value ? (onColor || C.buy) + "55" : C.bdr}`,
    color: value ? (onColor || C.buy) : C.t2,
    transition: "all .2s",
    minWidth: 100,
  }}>
    <span style={{
      width: 10, height: 10, borderRadius: "50%",
      background: value ? (onColor || C.buy) : C.t2,
      boxShadow: value ? `0 0 6px ${onColor || C.buy}` : "none",
      transition: "all .2s",
    }} />
    {value ? (label?.[1] || "ON") : (label?.[0] || "OFF")}
  </button>
);

const Slider = ({ value, min, max, step, onChange, color, unit }) => {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 200 }}>
      <input type="range" min={min} max={max} step={step || 1} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        style={{ flex: 1, accentColor: color || C.buy, cursor: "pointer" }}
      />
      <span style={{
        fontFamily: C.mono, fontSize: 11, fontWeight: 700,
        color: color || C.buy, minWidth: 48, textAlign: "right",
      }}>
        {value}{unit || ""}
      </span>
    </div>
  );
};

const NumInput = ({ value, onChange, min, max, step, unit }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
    <input type="number" value={value} min={min} max={max} step={step || 1}
      onChange={e => onChange(parseFloat(e.target.value) || 0)}
      style={{
        fontFamily: C.mono, fontSize: 11, fontWeight: 700,
        width: 80, padding: "5px 8px", borderRadius: 6,
        background: C.bg3, border: `1px solid ${C.bdr}`, color: C.t0,
        textAlign: "right",
      }}
    />
    {unit && <span style={{ fontFamily: C.mono, fontSize: 9, color: C.t2 }}>{unit}</span>}
  </div>
);

const Card = ({ children, accent }) => (
  <div style={{
    background: C.bg1,
    border: `1px solid ${accent ? accent + "44" : C.bdr}`,
    borderRadius: 10,
    padding: "16px 20px",
    marginBottom: 14,
    borderLeft: accent ? `3px solid ${accent}` : undefined,
  }}>
    {children}
  </div>
);

/* ══════════════════════════════════════════════════════
   SESSION FILTER
══════════════════════════════════════════════════════ */
const SessionFilter = ({ blocked, onChange }) => {
  const sessions = [
    { key: "Asia",     hours: "20:00–04:00 UTC", color: "#818cf8" },
    { key: "London",   hours: "07:00–12:00 UTC", color: C.gold },
    { key: "New York", hours: "12:00–21:00 UTC", color: C.buy },
  ];
  const toggle = s => {
    const next = blocked.includes(s)
      ? blocked.filter(x => x !== s)
      : [...blocked, s];
    onChange(next);
  };
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {sessions.map(s => {
        const active = !blocked.includes(s.key);
        return (
          <button key={s.key} onClick={() => toggle(s.key)} style={{
            display: "flex", flexDirection: "column",
            padding: "10px 14px", borderRadius: 8, cursor: "pointer",
            background: active ? s.color + "18" : C.bg3,
            border: `1px solid ${active ? s.color + "55" : C.bdr}`,
            color: active ? s.color : C.t2,
            transition: "all .15s",
          }}>
            <span style={{ fontFamily: C.mono, fontSize: 10, fontWeight: 700 }}>
              {active ? "✓" : "✗"} {s.key}
            </span>
            <span style={{ fontFamily: C.mono, fontSize: 8, color: C.t2, marginTop: 2 }}>
              {s.hours}
            </span>
          </button>
        );
      })}
    </div>
  );
};

/* ══════════════════════════════════════════════════════
   MARKET SELECTOR
══════════════════════════════════════════════════════ */
const MARKET_SYMBOLS = {
  crypto:       ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOTUSDT","AVAXUSDT"],
  forex:        ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","USDCHF","NZDUSD","GBPJPY"],
  stocks:       ["AAPL","TSLA","NVDA","MSFT","AMZN","META","GOOGL","SPY"],
  commodities:  ["XAUUSD","XAGUSD","USOIL","UKOIL","NATGAS"],
};
const MARKET_COLORS = {
  crypto: C.gold, forex: C.hold, stocks: C.buy, commodities: "#f97316",
};

const MarketSelector = ({ enabled, selected, onToggleMarket, onToggleSymbol }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
    {Object.entries(MARKET_SYMBOLS).map(([mkt, syms]) => {
      const mktOn = enabled[mkt] !== false;
      const col   = MARKET_COLORS[mkt];
      return (
        <div key={mkt} style={{
          background: C.bg2, borderRadius: 8, padding: 12,
          border: `1px solid ${mktOn ? col + "44" : C.bdr}`,
          opacity: mktOn ? 1 : 0.5, transition: "all .15s",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: mktOn ? 8 : 0 }}>
            <span style={{ fontFamily: C.mono, fontSize: 10, fontWeight: 700, color: mktOn ? col : C.t2 }}>
              {mkt.toUpperCase()}
            </span>
            <Toggle value={mktOn} onChange={v => onToggleMarket(mkt, v)} onColor={col}
              label={["DISABLED","ENABLED"]} />
          </div>
          {mktOn && (
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
              {syms.map(sym => {
                const on = (selected[mkt] || syms).includes(sym);
                return (
                  <button key={sym} onClick={() => onToggleSymbol(mkt, sym)} style={{
                    fontFamily: C.mono, fontSize: 8, fontWeight: 600,
                    padding: "2px 8px", borderRadius: 4, cursor: "pointer",
                    background: on ? col + "20" : C.bg3,
                    border: `1px solid ${on ? col + "55" : C.bdr}`,
                    color: on ? col : C.t2,
                    transition: "all .12s",
                  }}>
                    {on ? "✓" : "+"} {sym}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      );
    })}
  </div>
);

/* ══════════════════════════════════════════════════════
   AGGRESSIVENESS PRESET
══════════════════════════════════════════════════════ */
const PRESETS = [
  {
    key: "conservative",
    label: "Conservative",
    desc: "High confidence bar · Fewer but cleaner trades",
    icon: "🛡",
    color: C.buy,
    values: { min_confidence: 80, min_smc_score: 8, risk_percent: 0.5, max_trades_per_day: 2 },
  },
  {
    key: "balanced",
    label: "Balanced",
    desc: "Default settings · Good R:R with reasonable frequency",
    icon: "⚖",
    color: C.hold,
    values: { min_confidence: 70, min_smc_score: 6, risk_percent: 1.0, max_trades_per_day: 4 },
  },
  {
    key: "aggressive",
    label: "Aggressive",
    desc: "Lower bar · More signals · Higher risk",
    icon: "🔥",
    color: C.sell,
    values: { min_confidence: 55, min_smc_score: 4, risk_percent: 2.0, max_trades_per_day: 8 },
  },
];

const AggressivenessPreset = ({ current, onApply }) => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
    {PRESETS.map(p => {
      const isCurrent = current === p.key;
      return (
        <button key={p.key} onClick={() => onApply(p)} style={{
          flex: 1, minWidth: 150, padding: "12px 14px", borderRadius: 8, cursor: "pointer",
          background: isCurrent ? p.color + "18" : C.bg2,
          border: `2px solid ${isCurrent ? p.color : C.bdr}`,
          textAlign: "left", transition: "all .15s",
        }}>
          <div style={{ fontFamily: C.mono, fontSize: 12, fontWeight: 800,
            color: isCurrent ? p.color : C.t0, marginBottom: 4 }}>
            {p.icon} {p.label}
          </div>
          <div style={{ fontFamily: C.ui, fontSize: 10, color: C.t2, marginBottom: 6 }}>{p.desc}</div>
          {Object.entries(p.values).map(([k, v]) => (
            <div key={k} style={{ fontFamily: C.mono, fontSize: 8, color: isCurrent ? p.color : C.t2 }}>
              {k.replace(/_/g, " ")}: {v}
            </div>
          ))}
        </button>
      );
    })}
  </div>
);

/* ══════════════════════════════════════════════════════
   SAVE BUTTON + STATUS
══════════════════════════════════════════════════════ */
const SaveBar = ({ dirty, saving, onSave, onReset }) => (
  <div style={{
    position: "sticky", bottom: 0, zIndex: 100,
    background: C.bg1, borderTop: `1px solid ${C.bdr}`,
    padding: "12px 20px",
    display: "flex", justifyContent: "space-between", alignItems: "center",
  }}>
    <span style={{ fontFamily: C.mono, fontSize: 9, color: dirty ? C.gold : C.t2 }}>
      {dirty ? "⚠ Unsaved changes" : "✓ All settings saved"}
    </span>
    <div style={{ display: "flex", gap: 8 }}>
      <button onClick={onReset} disabled={!dirty} style={{
        fontFamily: C.mono, fontSize: 9, padding: "7px 16px", borderRadius: 6, cursor: dirty ? "pointer" : "default",
        background: "transparent", border: `1px solid ${C.bdr}`, color: dirty ? C.t1 : C.t2,
        opacity: dirty ? 1 : 0.4,
      }}>
        ↩ Reset
      </button>
      <button onClick={onSave} disabled={saving || !dirty} style={{
        fontFamily: C.mono, fontSize: 10, fontWeight: 700,
        padding: "7px 20px", borderRadius: 6, cursor: saving ? "wait" : dirty ? "pointer" : "default",
        background: saving ? C.bg3 : dirty ? C.buy + "22" : C.bg3,
        border: `1px solid ${saving ? C.bdr : dirty ? C.buy + "55" : C.bdr}`,
        color: saving ? C.t2 : dirty ? C.buy : C.t2,
        transition: "all .15s",
        opacity: !dirty ? 0.5 : 1,
      }}>
        {saving ? "Saving…" : "💾 Save Settings"}
      </button>
    </div>
  </div>
);

/* ══════════════════════════════════════════════════════
   MAIN SETTINGS
══════════════════════════════════════════════════════ */
const DEFAULT_LOCAL = {
  enabled_markets: { crypto: true, forex: true, stocks: true, commodities: false },
  selected_symbols: Object.fromEntries(
    Object.entries(MARKET_SYMBOLS).map(([k, v]) => [k, v])
  ),
};

export default function Settings() {
  const [cfg,      setCfg]     = useState(null);
  const [original, setOriginal] = useState(null);
  const [local,    setLocal]   = useState(DEFAULT_LOCAL);
  const [saving,   setSaving]  = useState(false);
  const [preset,   setPreset]  = useState("balanced");
  const [toast,    setToast]   = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await api("/api/settings");
      const d = await r.json();
      const settings = d.settings || d;
      setCfg(settings);
      setOriginal(JSON.parse(JSON.stringify(settings)));
    } catch (e) {
      // Provide sensible defaults if API not yet available
      const defaults = {
        min_confidence: 70,
        min_smc_score: 6,
        risk_percent: 1.0,
        risk_reward: 2.0,
        max_trades_per_day: 4,
        max_daily_loss_percent: 5,
        max_consecutive_losses: 3,
        blocked_sessions: [],
        atr_multiplier: 1.5,
        enable_trailing_stop: true,
        enable_fallback_strategy: true,
        avoid_quiet_market: true,
        avoid_sideways_market: true,
        trading_mode: "local_paper",
        starting_balance: 10000,
      };
      setCfg(defaults);
      setOriginal(JSON.parse(JSON.stringify(defaults)));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const upd = (key, value) => setCfg(c => ({ ...c, [key]: value }));

  const dirty = cfg && original
    ? JSON.stringify(cfg) !== JSON.stringify(original)
    : false;

  const save = async () => {
    setSaving(true);
    try {
      const r = await api("/api/settings", {
        method: "POST",
        body: JSON.stringify(cfg),
      });
      const d = await r.json();
      if (d.ok) {
        setOriginal(JSON.parse(JSON.stringify(cfg)));
        showToast("✓ Settings saved successfully", C.buy);
      } else {
        showToast(`⚠ ${d.error || "Save failed"}`, C.sell);
      }
    } catch {
      showToast("⚠ Network error — settings may not have saved", C.sell);
    } finally {
      setSaving(false);
    }
  };

  const reset = () => { setCfg(JSON.parse(JSON.stringify(original))); };

  const showToast = (msg, color) => {
    setToast({ msg, color });
    setTimeout(() => setToast(null), 3500);
  };

  const applyPreset = p => {
    setCfg(c => ({ ...c, ...p.values }));
    setPreset(p.key);
    showToast(`Applied ${p.label} preset`, p.color);
  };

  const toggleMarket = (mkt, on) => {
    setLocal(l => ({ ...l, enabled_markets: { ...l.enabled_markets, [mkt]: on } }));
  };

  const toggleSymbol = (mkt, sym) => {
    setLocal(l => {
      const cur  = l.selected_symbols[mkt] || MARKET_SYMBOLS[mkt];
      const next = cur.includes(sym) ? cur.filter(s => s !== sym) : [...cur, sym];
      return { ...l, selected_symbols: { ...l.selected_symbols, [mkt]: next } };
    });
  };

  if (!cfg) return (
    <div style={{ background: C.bg0, minHeight: "100vh",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: C.mono, color: C.t2 }}>
      Loading settings…
    </div>
  );

  const confColor = cfg.min_confidence >= 80 ? C.buy
    : cfg.min_confidence >= 65 ? C.gold : C.sell;

  return (
    <div style={{ background: C.bg0, minHeight: "100vh", fontFamily: C.ui }}>
      {/* Header */}
      <div style={{ background: C.bg1, borderBottom: `1px solid ${C.bdr}`,
        padding: "10px 20px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        position: "sticky", top: 0, zIndex: 200, backdropFilter: "blur(8px)",
      }}>
        <div style={{ fontFamily: C.mono, fontSize: 14, fontWeight: 800, color: C.t0 }}>
          <span style={{ color: C.purple }}>▸</span> BOT SETTINGS
        </div>
        <span style={{ fontFamily: C.mono, fontSize: 9, padding: "3px 10px", borderRadius: 4,
          background: cfg.trading_mode === "live" ? C.sell + "22" : C.buy + "18",
          color: cfg.trading_mode === "live" ? C.sell : C.buy,
          border: `1px solid ${cfg.trading_mode === "live" ? C.sell + "55" : C.buy + "33"}` }}>
          {cfg.trading_mode?.replace("_", " ").toUpperCase() || "PAPER"}
        </span>
      </div>

      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", top: 60, right: 20, zIndex: 500,
          fontFamily: C.mono, fontSize: 10, padding: "10px 16px", borderRadius: 7,
          background: toast.color + "22", border: `1px solid ${toast.color}55`,
          color: toast.color, boxShadow: `0 4px 20px ${toast.color}22`,
        }}>
          {toast.msg}
        </div>
      )}

      <div style={{ padding: 20, maxWidth: 900, paddingBottom: 80 }}>

        {/* ── AI Aggressiveness ── */}
        <Card accent={C.purple}>
          <SectionTitle icon="🤖" title="AI AGGRESSIVENESS"
            subtitle="Preset modes control how often the bot triggers signals. Conservative = fewer, higher-quality trades." />
          <AggressivenessPreset current={preset} onApply={applyPreset} />
        </Card>

        {/* ── Signal Quality ── */}
        <Card accent={confColor}>
          <SectionTitle icon="🎯" title="SIGNAL QUALITY THRESHOLDS"
            subtitle="The bot will only emit a signal when both confidence and SMC score meet the minimums." />

          <SettingRow
            label="Minimum Confidence %"
            hint={`Current: ${cfg.min_confidence}% — signals below this are suppressed`}
          >
            <Slider value={cfg.min_confidence} min={30} max={95} step={1}
              onChange={v => upd("min_confidence", v)} color={confColor} unit="%" />
          </SettingRow>

          <SettingRow
            label="Minimum SMC Score"
            hint={`Current: ${cfg.min_smc_score}/9 — how many SMC checks must align for a full ICT setup`}
          >
            <Slider value={cfg.min_smc_score} min={1} max={9} step={1}
              onChange={v => upd("min_smc_score", v)} color={C.hold} unit="/9" />
          </SettingRow>

          <SettingRow
            label="Fallback Strategy (EMA+ADX)"
            hint="When SMC score is below minimum, use EMA+ADX trend-follow instead of blocking the signal"
          >
            <Toggle value={cfg.enable_fallback_strategy}
              onChange={v => upd("enable_fallback_strategy", v)}
              label={["DISABLED","ENABLED"]} />
          </SettingRow>

          <SettingRow
            label="Block Sideways Market"
            hint="Suppresses signals when ADX is below 20 and price is ranging"
          >
            <Toggle value={cfg.avoid_sideways_market}
              onChange={v => upd("avoid_sideways_market", v)} />
          </SettingRow>

          <SettingRow
            label="Block Quiet Market"
            hint="Suppresses signals during low-volume / pre-market conditions"
          >
            <Toggle value={cfg.avoid_quiet_market}
              onChange={v => upd("avoid_quiet_market", v)} />
          </SettingRow>
        </Card>

        {/* ── Risk Management ── */}
        <Card accent={C.gold}>
          <SectionTitle icon="⚠️" title="RISK MANAGEMENT"
            subtitle="Controls how much capital is risked per trade and maximum daily exposure." />

          <SettingRow label="Risk per Trade %" hint="Percentage of account balance risked on each trade">
            <Slider value={cfg.risk_percent} min={0.1} max={5} step={0.1}
              onChange={v => upd("risk_percent", v)} color={C.gold} unit="%" />
          </SettingRow>

          <SettingRow label="Risk : Reward Ratio" hint="Minimum R:R — take profit will be placed at this multiple of the stop distance">
            <Slider value={cfg.risk_reward} min={1} max={5} step={0.5}
              onChange={v => upd("risk_reward", v)} color={C.buy} unit=":1" />
          </SettingRow>

          <SettingRow label="ATR Stop Multiplier"
            hint="Stop loss = entry ± (ATR × multiplier). Higher = wider stops, fewer whipsaws">
            <Slider value={cfg.atr_multiplier} min={0.5} max={4} step={0.25}
              onChange={v => upd("atr_multiplier", v)} color={C.hold} unit="×" />
          </SettingRow>

          <SettingRow label="Trailing Stop" hint="Moves the stop loss with price to lock in profits as the trade runs">
            <Toggle value={cfg.enable_trailing_stop}
              onChange={v => upd("enable_trailing_stop", v)}
              label={["DISABLED","ENABLED"]} />
          </SettingRow>

          <SettingRow label="Max Trades Per Day" hint="Bot will not open new positions after this limit is hit">
            <NumInput value={cfg.max_trades_per_day} min={1} max={20}
              onChange={v => upd("max_trades_per_day", v)} unit="trades/day" />
          </SettingRow>

          <SettingRow label="Max Daily Loss %" hint="Bot pauses for the day after losing this % of starting balance">
            <Slider value={cfg.max_daily_loss_percent} min={1} max={20} step={0.5}
              onChange={v => upd("max_daily_loss_percent", v)} color={C.sell} unit="%" />
          </SettingRow>

          <SettingRow label="Max Consecutive Losses" hint="Bot pauses after this many losses in a row to avoid revenge trading">
            <NumInput value={cfg.max_consecutive_losses} min={1} max={10}
              onChange={v => upd("max_consecutive_losses", v)} unit="losses" />
          </SettingRow>

          <SettingRow label="Starting / Paper Balance" hint="Virtual balance used for paper trading and backtests">
            <NumInput value={cfg.starting_balance} min={100} max={10000000} step={100}
              onChange={v => upd("starting_balance", v)} unit="USD" />
          </SettingRow>
        </Card>

        {/* ── Session Filters ── */}
        <Card accent={C.gold}>
          <SectionTitle icon="🕐" title="SESSION FILTERS"
            subtitle="Only sessions that are enabled (✓) will trigger new entries. Blocked sessions are skipped." />
          <SettingRow
            label="Active Trading Sessions"
            hint="Click a session to toggle it on or off"
          >
            <div />
          </SettingRow>
          <SessionFilter
            blocked={cfg.blocked_sessions || []}
            onChange={v => upd("blocked_sessions", v)}
          />
          <div style={{ fontFamily: C.mono, fontSize: 9, color: C.t2, marginTop: 10 }}>
            Blocked: {(cfg.blocked_sessions || []).length === 0
              ? "None — all sessions active"
              : (cfg.blocked_sessions || []).join(", ")}
          </div>
        </Card>

        {/* ── Market Selection ── */}
        <Card>
          <SectionTitle icon="🌍" title="MARKET & SYMBOL SELECTION"
            subtitle="Enable or disable entire market categories, or pick specific symbols." />
          <div style={{ fontFamily: C.ui, fontSize: 10, color: C.t2, marginBottom: 12 }}>
            Note: Symbol selection is stored locally and used to filter the dashboard. The backend scans all symbols by default.
          </div>
          <MarketSelector
            enabled={local.enabled_markets}
            selected={local.selected_symbols}
            onToggleMarket={toggleMarket}
            onToggleSymbol={toggleSymbol}
          />
        </Card>

        {/* ── Trading Mode ── */}
        <Card accent={cfg.trading_mode === "live" ? C.sell : C.buy}>
          <SectionTitle icon="⚡" title="TRADING MODE"
            subtitle="Controls whether the bot executes real orders or runs in paper mode." />

          <SettingRow label="Trading Mode"
            hint={cfg.trading_mode === "live"
              ? "⚠ LIVE MODE — real orders will be placed on your exchange"
              : "Paper mode — no real orders, safe for testing"}>
            <div style={{ display: "flex", gap: 6 }}>
              {["local_paper", "live"].map(m => (
                <button key={m} onClick={() => upd("trading_mode", m)} style={{
                  fontFamily: C.mono, fontSize: 9, fontWeight: 700,
                  padding: "6px 14px", borderRadius: 6, cursor: "pointer",
                  background: cfg.trading_mode === m
                    ? (m === "live" ? C.sell + "22" : C.buy + "22")
                    : C.bg3,
                  border: `1px solid ${cfg.trading_mode === m
                    ? (m === "live" ? C.sell + "55" : C.buy + "55")
                    : C.bdr}`,
                  color: cfg.trading_mode === m
                    ? (m === "live" ? C.sell : C.buy)
                    : C.t2,
                }}>
                  {m === "live" ? "🔴 LIVE" : "🟢 PAPER"}
                </button>
              ))}
            </div>
          </SettingRow>
        </Card>

        {/* ── Current config preview ── */}
        <Card>
          <SectionTitle icon="📋" title="ACTIVE CONFIGURATION PREVIEW"
            subtitle="Full JSON snapshot of all current settings." />
          <button onClick={() => {
            const el = document.getElementById("cfg-json");
            el.style.display = el.style.display === "none" ? "block" : "none";
          }} style={{
            fontFamily: C.mono, fontSize: 9, padding: "5px 12px",
            borderRadius: 5, cursor: "pointer",
            background: C.bg3, border: `1px solid ${C.bdr}`, color: C.t1,
            marginBottom: 10,
          }}>
            Toggle JSON
          </button>
          <pre id="cfg-json" style={{ display: "none",
            fontFamily: C.mono, fontSize: 9, color: C.t1,
            background: C.bg0, border: `1px solid ${C.bdr}`,
            borderRadius: 7, padding: 14, overflowX: "auto",
            lineHeight: 1.6,
          }}>
            {JSON.stringify(cfg, null, 2)}
          </pre>
        </Card>

      </div>

      <SaveBar dirty={dirty} saving={saving} onSave={save} onReset={reset} />
    </div>
  );
}

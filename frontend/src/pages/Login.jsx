import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { TrendingUp, Sparkles } from "lucide-react";

export default function Login({ mode = "login" }) {
  const isReg = mode === "register";
  const { login, register, loading } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ email: "", password: "", name: "" });
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      if (isReg) await register(form.email, form.password, form.name);
      else await login(form.email, form.password);
      nav("/dashboard");
    } catch (e) {
      setErr(e?.response?.data?.error || "Failed");
    }
  };

  return (
    <div className="min-h-screen relative grid-bg flex items-center justify-center p-6" data-testid="auth-page">
      <div className="aurora" />
      <div className="relative z-10 grid md:grid-cols-2 gap-10 max-w-5xl w-full items-center">
        {/* left brand */}
        <div className="hidden md:block">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-11 h-11 rounded-xl bg-[var(--accent)] flex items-center justify-center" style={{ boxShadow: "var(--glow-mint)" }}>
              <TrendingUp size={22} color="#00130b" strokeWidth={2.5} />
            </div>
            <div>
              <div className="font-bold text-lg leading-none">AI Trading Engine</div>
              <div className="text-xs mono text-[var(--text-mute)] mt-1">SMC · BACKTEST · JOURNAL</div>
            </div>
          </div>
          <h1 className="text-5xl font-extrabold leading-[1.05] mb-5" style={{ fontFamily: 'Sora' }}>
            Trade like a<br/>
            <span style={{ background: "linear-gradient(90deg, var(--accent-2), var(--accent))", WebkitBackgroundClip: "text", color: "transparent" }}>
              quant desk.
            </span>
          </h1>
          <p className="text-[var(--text-dim)] text-base leading-relaxed max-w-md mb-8">
            Smart-money signals across BTC, ETH, BNB, SOL — with explainable confidence,
            a real backtester, and a journal that learns from every trade.
          </p>
          <div className="grid grid-cols-3 gap-4 max-w-md">
            {[
              { v: "9", l: "SMC checks per signal" },
              { v: "4", l: "Live symbols tracked" },
              { v: "1m–4h", l: "Multi-timeframe" },
            ].map((s, i) => (
              <div key={i} className="panel p-4">
                <div className="mono text-2xl font-bold text-[var(--accent)]">{s.v}</div>
                <div className="text-xs text-[var(--text-mute)] mt-1">{s.l}</div>
              </div>
            ))}
          </div>
        </div>

        {/* right form */}
        <div className="panel p-8 fade-up" data-testid="auth-form-panel">
          <div className="flex items-center gap-2 mb-1">
            <Sparkles size={16} className="text-[var(--accent)]" />
            <span className="section-title">{isReg ? "Create account" : "Welcome back"}</span>
          </div>
          <h2 className="text-2xl font-bold mb-6">{isReg ? "Start trading smarter" : "Sign in to your terminal"}</h2>
          <form onSubmit={submit} className="space-y-4">
            {isReg && (
              <div>
                <label className="text-xs text-[var(--text-mute)] mb-1 block">Name</label>
                <input className="input" data-testid="auth-name-input"
                  value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Alex"/>
              </div>
            )}
            <div>
              <label className="text-xs text-[var(--text-mute)] mb-1 block">Email</label>
              <input className="input" type="email" data-testid="auth-email-input" required
                value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="you@firm.com"/>
            </div>
            <div>
              <label className="text-xs text-[var(--text-mute)] mb-1 block">Password</label>
              <input className="input" type="password" data-testid="auth-password-input" required
                value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder={isReg ? "min 6 characters" : "••••••••"}/>
            </div>
            {err && <div className="text-sm text-[var(--sell)]" data-testid="auth-error">{err}</div>}
            <button className="btn btn-primary w-full" disabled={loading} data-testid="auth-submit-btn">
              {loading ? "..." : isReg ? "Create account" : "Sign in"}
            </button>
          </form>
          <div className="mt-6 pt-6 border-t border-[var(--line)] text-sm text-[var(--text-dim)] text-center">
            {isReg ? (
              <>Already have one? <Link to="/login" className="text-[var(--accent)] font-semibold" data-testid="auth-toggle-link">Sign in</Link></>
            ) : (
              <>New here? <Link to="/register" className="text-[var(--accent)] font-semibold" data-testid="auth-toggle-link">Create an account</Link></>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// force redeploy
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { LayoutDashboard, Settings, BookOpen, FlaskConical, LogOut, TrendingUp, Activity } from "lucide-react";

export default function AppShell() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const items = [
    { to: "/dashboard", label: "Signals", icon: <LayoutDashboard size={17} /> },
    { to: "/backtester", label: "Backtester", icon: <FlaskConical size={17} /> },
    { to: "/journal", label: "Journal", icon: <BookOpen size={17} /> },
    { to: "/settings", label: "Strategy", icon: <Settings size={17} /> },
  ];

  return (
    <div className="min-h-screen flex" data-testid="app-shell">
      {/* sidebar */}
      <aside className="w-64 shrink-0 border-r border-[var(--line)] bg-[var(--bg-1)] flex flex-col">
        <div className="px-5 py-5 border-b border-[var(--line)]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[var(--accent)] flex items-center justify-center" style={{ boxShadow: "var(--glow-mint)" }}>
              <TrendingUp size={18} color="#00130b" strokeWidth={2.5} />
            </div>
            <div>
              <div className="font-bold text-sm leading-none">AI Trading</div>
              <div className="mono text-[10px] text-[var(--text-mute)] mt-1">ENGINE · v2</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          <div className="section-title px-3 pt-2 pb-3">Workspace</div>
          {items.map((it) => (
            <NavLink key={it.to} to={it.to} end className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`} data-testid={`nav-${it.label.toLowerCase()}`}>
              {it.icon}
              <span>{it.label}</span>
            </NavLink>
          ))}

          <div className="section-title px-3 pt-6 pb-3">Status</div>
          <div className="sidebar-link">
            <span className="pulse-dot" />
            <span className="text-xs">Live · Binance</span>
          </div>
          <div className="sidebar-link">
            <Activity size={16} className="text-[var(--accent-2)]" />
            <span className="text-xs">Coinbase fallback</span>
          </div>
        </nav>

        <div className="p-3 border-t border-[var(--line)]">
          <div className="panel-flat p-3 mb-2">
            <div className="text-xs text-[var(--text-mute)]">Signed in</div>
            <div className="text-sm font-semibold truncate" data-testid="sidebar-user-name">{user?.name || user?.email}</div>
            <div className="text-xs text-[var(--text-dim)] truncate">{user?.email}</div>
          </div>
          <button className="btn btn-ghost w-full" onClick={() => { logout(); nav("/login"); }} data-testid="logout-btn">
            <LogOut size={15} /> Logout
          </button>
        </div>
      </aside>

      {/* main */}
      <main className="flex-1 overflow-y-auto relative grid-bg">
        <div className="aurora" />
        <div className="relative z-10 max-w-[1500px] mx-auto p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

import { useEffect, useRef, useState, useCallback } from "react";
import api from "@/lib/api";
import { createChart, CandlestickSeries } from "lightweight-charts";
import { ArrowUpRight, ArrowDownRight, Minus, Zap, RefreshCw, CheckCircle2, XCircle, BookmarkPlus } from "lucide-react";

// FIX 6: All 18 symbols — matches backend ALL_SYMBOLS
const SYMBOLS = [
  "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
  "EURUSD",  "GBPUSD",  "USDJPY",  "AUDUSD",  "USDCAD",
  "AAPL",    "TSLA",    "NVDA",    "MSFT",    "AMZN",
  "XAUUSD",  "XAGUSD",  "USOIL",   "UKOIL",
];

const INTERVALS = ["1m", "5m", "15m", "1h", "4h"];

// FIX 6: Label helper — crypto shows /USDT, others show as-is
function symbolLabel(sym) {
  if (sym.endsWith("USDT")) {
    return (
      <>
        {sym.replace("USDT", "")}
        <span className="text-[var(--text-mute)]">/USDT</span>
      </>
    );
  }
  return sym;
}

function SignalCard({ s, active, onClick }) {
  const isBuy  = s.signal === "BUY";
  const isSell = s.signal === "SELL";
  const PillIcon = isBuy ? ArrowUpRight : isSell ? ArrowDownRight : Minus;

  // [F] Backend now supplies price_display — use it directly if present
  const priceDisplay = s.price_display || (s.price ? String(s.price) : "—");

  return (
    <button
      onClick={onClick}
      data-testid={`signal-card-${s.symbol}`}
      className={`panel p-5 text-left w-full transition-all ${active ? "border-[var(--accent)]" : ""}`}
      style={active ? { borderColor: "var(--accent)", boxShadow: "var(--glow-mint)" } : {}}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="font-bold text-base">{symbolLabel(s.symbol)}</div>
          <div className={`pill ${isBuy ? "pill-buy" : isSell ? "pill-sell" : "pill-hold"}`}>
            <PillIcon size={11} /> {s.signal}
          </div>
        </div>
        <div className={`mono text-xs ${s.change_pct >= 0 ? "num-pos" : "num-neg"}`}>
          {s.change_pct >= 0 ? "+" : ""}{s.change_pct?.toFixed(2)}%
        </div>
      </div>
      <div className="mono text-2xl font-bold mb-3">{priceDisplay}</div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-[var(--text-mute)]">Confidence</span>
        <span className="mono text-xs font-semibold">{s.confidence}%</span>
      </div>
      <div className="meter mb-3"><span style={{ width: `${s.confidence}%` }} /></div>
      <div className="flex items-center justify-between text-xs text-[var(--text-dim)]">
        <span>SMC <span className="mono font-bold text-[var(--text)]">{s.smc_score}/9</span></span>
        <span>{s.regime}</span>
      </div>
    </button>
  );
}

// Group symbols by market for the signal grid header
const MARKET_GROUPS = [
  { label: "Crypto",      symbols: ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"] },
  { label: "Forex",       symbols: ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"] },
  { label: "Stocks",      symbols: ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN"] },
  { label: "Commodities", symbols: ["XAUUSD", "XAGUSD", "USOIL", "UKOIL"] },
];

export default function Dashboard() {
  const [signals,    setSignals]    = useState([]);
  const [active,     setActive]     = useState("BTCUSDT");
  const [interval,   setInterval_]  = useState("5m");
  const [loading,    setLoading]    = useState(true);
  const [openTrades, setOpenTrades] = useState([]);
  const [stats,      setStats]      = useState(null);

  const chartRef     = useRef(null);
  const containerRef = useRef(null);
  const seriesRef    = useRef(null);

  const [signalErrors, setSignalErrors] = useState([]);

  const loadSignals = useCallback(async () => {
    try {
      const { data } = await api.get(`/signals?interval=${interval}`);
      setSignals(data.signals || []);
      setSignalErrors(data.errors  || []);
    } catch (e) {
      console.error("loadSignals failed:", e);
    } finally {
      setLoading(false);
    }
  }, [interval]);

  const loadTrades = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([api.get("/trades"), api.get("/stats")]);
      setOpenTrades((t.data || []).filter((x) => x.status === "OPEN"));
      setStats(s.data);
    } catch (e) {
      console.error("loadTrades failed:", e);
    }
  }, []);

  useEffect(() => { loadSignals(); loadTrades(); }, [loadSignals, loadTrades]);
  useEffect(() => {
    // Poll every 60 s — TwelveData free plan is 8 credits/min; 60 s gives the
    // cache time to warm up before the next refresh hits uncached symbols.
    const id = window.setInterval(loadSignals, 60000);
    return () => window.clearInterval(id);
  }, [loadSignals]);

  // Chart setup
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: "transparent" }, textColor: "#8a96a3", fontFamily: "JetBrains Mono" },
      grid: { vertLines: { color: "#1a212a" }, horzLines: { color: "#1a212a" } },
      timeScale: { borderColor: "#1f2730", timeVisible: true },
      rightPriceScale: { borderColor: "#1f2730" },
      width: containerRef.current.clientWidth,
      height: 420,
      crosshair: { mode: 1 },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#00ffa3", downColor: "#ff4d6d",
      wickUpColor: "#00ffa3", wickDownColor: "#ff4d6d", borderVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    const onResize = () => chart.applyOptions({ width: containerRef.current.clientWidth });
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, []);

  useEffect(() => {
    if (!seriesRef.current) return;
    api.get(`/chart-candles?symbol=${active}&interval=${interval}&limit=300`)
      .then(({ data }) => {
        if (data?.ok && data.data?.length && seriesRef.current) {
          seriesRef.current.setData(data.data);
          chartRef.current?.timeScale().fitContent();
        }
      })
      .catch(() => {});
  }, [active, interval, signals.length]);

  const activeSignal = signals.find((s) => s.symbol === active);

  const openPaper = async (side) => {
    try {
      await api.post("/trades", { symbol: active, side });
      loadTrades();
    } catch (e) {
      alert(e?.response?.data?.error || "Failed");
    }
  };

  const closeTrade = async (id) => {
    try { await api.post(`/trades/${id}/close`); loadTrades(); } catch {}
  };

  // Price display helper — matches backend format_price() logic
  const formatPrice = (p, sym = active) => {
    if (!p) return "—";
    if (sym?.endsWith("USDT")) {
      if (p >= 1000) return Number(p).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (p >= 1)    return Number(p).toFixed(4);
      return Number(p).toFixed(6);
    }
    if (["EURUSD","GBPUSD","AUDUSD","USDCAD"].includes(sym)) return Number(p).toFixed(5);
    if (sym === "USDJPY") return Number(p).toFixed(3);
    if (["XAUUSD","XAGUSD","USOIL","UKOIL"].includes(sym))
      return p < 100 ? Number(p).toFixed(3) : Number(p).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return Number(p).toFixed(2);
  };

  return (
    <div className="space-y-6 fade-up" data-testid="dashboard-page">
      {/* header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="section-title">Live signals</div>
          <h1 className="text-3xl font-bold mt-1">Signal terminal</h1>
          <p className="text-[var(--text-dim)] text-sm mt-1">
            Smart-money concepts across Crypto, Forex, Stocks & Commodities — refreshed every 15s
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="panel-flat px-1 py-1 flex gap-1" data-testid="interval-switch">
            {INTERVALS.map((i) => (
              <button key={i} onClick={() => setInterval_(i)}
                data-testid={`interval-${i}`}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold mono transition ${
                  interval === i
                    ? "bg-[var(--accent)] text-[#00130b]"
                    : "text-[var(--text-dim)] hover:text-[var(--text)]"
                }`}>
                {i}
              </button>
            ))}
          </div>
          <button className="btn btn-ghost" onClick={loadSignals} data-testid="refresh-btn">
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      {/* stats row */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="stats-row">
          {[
            { l: "Balance",       v: `$${stats.balance.toLocaleString()}`,      sub: `Start $${stats.starting_balance.toLocaleString()}` },
            { l: "Net PnL",       v: `${stats.net_pnl >= 0 ? "+" : ""}$${stats.net_pnl.toFixed(2)}`, klass: stats.net_pnl >= 0 ? "num-pos" : "num-neg" },
            { l: "Win rate",      v: `${stats.win_rate}%`,                       sub: `${stats.wins}W · ${stats.losses}L` },
            { l: "Closed trades", v: stats.total_trades,                         sub: "Paper" },
          ].map((k, i) => (
            <div key={i} className="panel p-5">
              <div className="text-xs text-[var(--text-mute)]">{k.l}</div>
              <div className={`mono text-2xl font-bold mt-1 ${k.klass || ""}`}>{k.v}</div>
              {k.sub && <div className="text-xs text-[var(--text-dim)] mt-1">{k.sub}</div>}
            </div>
          ))}
        </div>
      )}

      {/* rate-limit / API error notice */}
      {signalErrors.length > 0 && (
        <div className="panel-flat border border-[var(--warn)] p-3 text-xs text-[var(--warn)] flex items-start gap-2">
          <span className="shrink-0 mt-0.5">⚠</span>
          <div>
            <strong>{signalErrors.length} symbol(s) failed to load: </strong>
            {signalErrors.map(e => e.symbol).join(", ")}.{" "}
            {signalErrors.some(e => e.error?.includes("rate limit") || e.error?.includes("429"))
              ? "TwelveData rate limit hit — prices will refresh automatically in ~60 s."
              : "Check backend logs for details."}
          </div>
        </div>
      )}
      {MARKET_GROUPS.map(({ label, symbols: groupSyms }) => (
        <div key={label}>
          <div className="section-title mb-3">{label}</div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {loading
              ? groupSyms.map((_, i) => (
                  <div key={i} className="panel p-5 h-[170px] animate-pulse">
                    <div className="h-4 w-20 bg-[var(--bg-3)] rounded mb-3" />
                    <div className="h-8 w-32 bg-[var(--bg-3)] rounded mb-3" />
                    <div className="h-1 w-full bg-[var(--bg-3)] rounded" />
                  </div>
                ))
              : groupSyms.map((sym) => {
                  const s = signals.find((x) => x.symbol === sym) || {
                    symbol: sym, signal: "HOLD", price: 0, change_pct: 0,
                    confidence: 0, smc_score: 0, regime: "—",
                  };
                  return (
                    <SignalCard
                      key={sym}
                      s={s}
                      active={active === sym}
                      onClick={() => setActive(sym)}
                    />
                  );
                })}
          </div>
        </div>
      ))}

      {/* chart + explanation */}
      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 panel p-5" data-testid="chart-panel">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="section-title">Price action</div>
              <div className="text-lg font-bold mt-1 mono">{active} · {interval}</div>
            </div>
            {activeSignal && (
              <div className="flex items-center gap-3">
                <div className="text-right">
                  <div className="text-xs text-[var(--text-mute)]">Entry / SL / TP</div>
                  <div className="mono text-sm">
                    <span className="text-[var(--text)]">{formatPrice(activeSignal.entry)}</span> ·
                    <span className="text-[var(--sell)] ml-1">{formatPrice(activeSignal.sl)}</span> ·
                    <span className="text-[var(--buy)] ml-1">{formatPrice(activeSignal.tp)}</span>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button className="btn btn-primary" onClick={() => openPaper("BUY")} data-testid="paper-buy-btn">
                    <ArrowUpRight size={14} /> Paper Buy
                  </button>
                  <button className="btn btn-danger" onClick={() => openPaper("SELL")} data-testid="paper-sell-btn">
                    <ArrowDownRight size={14} /> Paper Sell
                  </button>
                </div>
              </div>
            )}
          </div>
          <div ref={containerRef} className="rounded-lg overflow-hidden" />
        </div>

        <div className="panel p-5" data-testid="signal-explanation">
          <div className="flex items-center gap-2 mb-1">
            <Zap size={14} className="text-[var(--accent)]" />
            <div className="section-title">Signal explanation</div>
          </div>
          <div className="text-lg font-bold mt-1">{activeSignal?.trade_idea || "Loading..."}</div>
          <div className="mt-3 text-xs text-[var(--text-dim)]">
            HTF bias{" "}
            <span className="mono text-[var(--text)]">{activeSignal?.higher_tf_bias}</span> on{" "}
            <span className="mono text-[var(--text)] ml-1">{activeSignal?.higher_tf}</span>
          </div>
          <div className="mt-4 pt-4 border-t border-[var(--line)] space-y-2 max-h-[280px] overflow-y-auto">
            {(activeSignal?.reasons || []).map((r, i) => {
              const ok = r.startsWith("✓");
              return (
                <div key={i} className="flex items-start gap-2 text-xs">
                  {ok
                    ? <CheckCircle2 size={14} className="text-[var(--buy)] shrink-0 mt-0.5" />
                    : <XCircle     size={14} className="text-[var(--text-mute)] shrink-0 mt-0.5" />}
                  <span className={ok ? "text-[var(--text)]" : "text-[var(--text-mute)]"}>
                    {r.replace(/^[✓✗]\s*/, "")}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* open trades */}
      <div className="panel p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="section-title">Open paper trades</div>
            <div className="text-lg font-bold mt-1">{openTrades.length} active</div>
          </div>
          <BookmarkPlus size={16} className="text-[var(--text-mute)]" />
        </div>
        {openTrades.length === 0 ? (
          <div className="text-sm text-[var(--text-mute)] py-6 text-center">
            No open trades. Click Paper Buy/Sell to simulate one.
          </div>
        ) : (
          <table className="tbl" data-testid="open-trades-table">
            <thead>
              <tr><th>Symbol</th><th>Side</th><th>Entry</th><th>SL</th><th>TP</th><th>Size</th><th>Time</th><th></th></tr>
            </thead>
            <tbody>
              {openTrades.map((t) => (
                <tr key={t.id} data-testid={`open-trade-${t.id}`}>
                  <td className="font-semibold">{t.symbol}</td>
                  <td><span className={`pill ${t.side === "BUY" ? "pill-buy" : "pill-sell"}`}>{t.side}</span></td>
                  <td className="mono">{formatPrice(t.entry)}</td>
                  <td className="mono num-neg">{formatPrice(t.sl)}</td>
                  <td className="mono num-pos">{formatPrice(t.tp)}</td>
                  <td className="mono">{t.size?.toFixed(4)}</td>
                  <td className="mono text-xs text-[var(--text-mute)]">{t.time}</td>
                  <td>
                    <button className="btn btn-ghost" onClick={() => closeTrade(t.id)}
                      data-testid={`close-trade-${t.id}`}>Close</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

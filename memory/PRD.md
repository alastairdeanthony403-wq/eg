# AI Trading Engine — SaaS Edition

## Original Problem Statement
User has a Flask-based AI crypto trading terminal (BTC/ETH/BNB/SOL) with SMC signal logic, anti-overtrading rules, true backtester, and SQLite persistence. They want a polished SaaS-style React frontend connected to that backend, with JWT auth, strategy settings, backtest reports, trade journal, and modern fintech (TradingView-style) UI.

## User Choices
- Backend: keep Flask as-is (wrapped by ASGI shim so supervisor's uvicorn keeps running)
- Auth: JWT email/password
- Paper trading: both modes (local sim + testnet flag — testnet routing is a future P1)
- Design: Modern fintech, sleek/glassy/neon (deep dark + neon mint #00ffa3 + electric cyan #00d4ff)
- Priority features: Live signal dashboard with explanations, Backtester, Strategy settings, Journal

## Architecture
- `/app/backend/flask_app.py` — Flask app, all routes prefixed `/api`. SQLite (`trades.db`) with users, trades, alerts, journal, backtest_runs.
- `/app/backend/server.py` — `a2wsgi.WSGIMiddleware(flask_app)` so `uvicorn server:app` works with the platform's ingress.
- `/app/frontend/src/` — React 19 + react-router 7 + tailwind + lightweight-charts + framer-motion.
- Auth: PyJWT HS256, bcrypt password hashing; localStorage on the FE; axios interceptor + 401 redirect.

## What's been implemented (Jan 2026)
- JWT auth (register, login, /me) — protected routes guarded by `auth_required` decorator
- Live signal dashboard for 4 symbols (BTC/ETH/BNB/SOL) with full SMC explanation (9 checks ✓/✗)
- Lightweight-charts candle chart with interval switching (1m/5m/15m/1h/4h)
- Paper-trade open/close (local simulation) with live PnL stats
- True backtester (POST /api/backtest) — saves runs, lists history, replays prior runs
- Per-user strategy settings (risk, SMC filters, watched symbols, trading mode)
- Trade journal with mood tagging + free-form notes + custom tags
- Equity curve, stats, alerts endpoints
- Polished fintech UI (Sora + JetBrains Mono, neon mint+cyan accents, glass panels, aurora bg)

## Test Status (iteration 1)
- Backend: 15/15 pytest cases PASS
- Frontend: login → dashboard → backtester → settings → logout flow PASS
- Test credentials seeded: `trader@demo.com / trader123`

## Backlog
- P1: Wire trading_mode `testnet` to actual Binance/Coinbase testnet routing (needs user keys)
- P1: WebSocket for live price streaming (currently 15s polling)
- P2: Email alerts when high-confidence signals appear
- P2: Strategy A/B compare in backtester
- P2: Refactor flask_app.py into blueprints (auth/market/backtest/journal/trades)
- P2: Parallelise signal fetch with ThreadPoolExecutor to cut first-load latency

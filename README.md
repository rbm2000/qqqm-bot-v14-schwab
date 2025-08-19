# 🤖 QQQM Options Bot

Semi-risky but **defined-risk** automation around QQQM (Nasdaq-100 ETF) using:
- Dollar-cost averaging (DCA)
- Wheel (cash‑secured puts ➜ covered calls)
- Weekly defined‑risk spreads (bull put / bear call) and occasional iron condors
- Guardrails: drawdown throttle, VIX/volatility filter, cash buffer, and strict sizing

> **Disclaimer:** Educational code. Use at your own risk. Paper trade first. Options involve risk and are not suitable for all investors.

---

## What you get
- **Scheduler** (APScheduler) for weekly DCA + options rolls
- **Risk manager** (drawdown cap, VIX gating, cash buffer checks)
- **Broker adapters**: Paper (built-in), Alpaca, Tradier (stubs you can turn on), and a slot for Schwab
- **SQLite** trade log + positions
- **Flask dashboard** (positions, P/L, logs) + JSON config editor
- **Discord webhooks** for trade alerts & daily/weekly summaries
- **Modes**: Conservative (DCA+CC), Balanced (Wheel), Enhanced (+spreads/condors)
- **Docker** support

---

## Quick Start (Paper first)
1. **Install** (Python 3.10+ recommended):
   ```bash
   pip install -r requirements.txt
   ```
2. **Copy env file** and set Discord webhook (optional):
   ```bash
   cp .env.example .env
   ```
3. **Pick a mode** and tweak numbers in `config/config.yaml`.
4. **Run the bot (paper)**:
   ```bash
   python -m qqqm.bot
   ```
5. **Open dashboard**: http://localhost:5005

### Docker (optional)
```bash
docker build -t qqqm-bot .
docker run --env-file .env -p 5005:5005 -v $(pwd)/data:/app/data qqqm-bot
```

---

## Broker Adapters
- **PaperBroker** (default): pulls market data via `yfinance` and “simulates” orders with a local book.
- **Alpaca**: fill `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY` in `.env`, set `broker: alpaca` in `config.yaml`.  (Options & multi-leg support per Alpaca docs.)
- **Tradier**: fill `TRADIER_ACCESS_TOKEN` and set `broker: tradier` in `config.yaml`.  (Options & complex orders supported.)

> **Schwab**: the code includes a placeholder adapter (`schwab.py`). You’ll need a Schwab Trader API app + OAuth flow. Enable once you have access. (Schwab’s Developer Portal documents the flow.)

---

## Options Approval Levels (typical, varies by broker)
- Covered calls & cash‑secured puts: **Level 1–2**
- Vertical spreads / iron condors: **Level 3**
No naked calls or uncovered puts are used.

---

## Strategy Logic (high level)
- **DCA**: buys `$weekly_dca` of QQQM every week (if cash ≥ min buffer).
- **Wheel**:
  - If < 100 shares → sell **cash‑secured put** (OTM by `put_pct_otm`, prefer 7–10 DTE).
  - If assigned → accumulate shares until 100+.
  - If ≥ 100 shares → sell **covered call** (OTM by `call_pct_otm`, weekly).
  - If called away → resume CSPs with new cash.
- **Spreads / Condors** (Enhanced mode only; tiny allocation):
  - Bull put or bear call spreads when trend/IV conditions pass filters.
  - Iron condor on rangebound signal; max 2 concurrent.
- **Safeguards**:
  - Stop opening new risk if `max_drawdown` breached.
  - Skip new trades if `vix_max` exceeded.
  - Keep `cash_buffer_pct` free.

---

## Files
```
qqqm-bot/
├── qqqm/
│   ├── __init__.py
│   ├── bot.py
│   ├── config.py
│   ├── risk.py
│   ├── scheduler.py
│   ├── util.py
│   ├── brokers/
│   │   ├── base.py
│   │   ├── paper.py
│   │   ├── alpaca.py
│   │   ├── tradier.py
│   │   └── schwab.py
│   ├── strategies/
│   │   ├── dca.py
│   │   ├── wheel.py
│   │   ├── spreads.py
│   │   └── condor.py
│   ├── data/
│   │   ├── db.py
│   │   └── models.py
│   └── web/
│       ├── app.py
│       ├── templates/
│       │   └── index.html
│       └── static/
│           └── styles.css
├── config/
│   └── config.yaml
├── .env.example
├── requirements.txt
├── Dockerfile
└── README.md
```
---

## Daily Reports
Enable `daily_reports: true` in `config.yaml`. A markdown summary is produced under `data/reports/` and sent to Discord (if webhook set).

---

## Backtest / Paper First
Set `mode: paper` and `broker: paper` then run for a week to validate. When ready, switch to a live broker adapter.


## What v6 adds (simple + safe + robust)
- **RiskGuard**: daily $ stop, weekly % stop, max-open-risk %, VIX ceiling, cooldown, max trades/day, direction cap.
- **HTTP backoff**: retries & timeouts for broker calls.
- **Dashboard controls**: Pause/Resume, reset Kill‑Switch, guard status banner.
- **Password option**: set `DASHBOARD_PASSWORD` to require login.
- **Quote sanity**: ignores zero/garbage quotes; uses mid when available.
- **Journal**: append-only `data/journal.jsonl` for every open/close.
- **Config validation** before save (prevents bricking the bot).
- **Royal purple UI** finish.


## What v7 adds (deploy‑ready)
- **Invest‑all‑on‑start**: fully deploys $1k immediately (keeps cash buffer).
- **Options liquidity switch**: keep DCA on QQQM while trading options on **QQQ**.
- **Volatility‑adjusted sizing** (VIX-based scaling).
- **Stop/Target exits** for spreads/condors (50/50 default; 40/60 for condors).
- **Tracked option positions** with credits/debits and auto exit checks every 10 minutes.
- **Weekly performance stats** on the dashboard.


## What v8 adds (controls + visibility)
- **Discord command bot** (optional): `!status`, `!positions`, `!pause`, `!resume`, `!killreset`
- **Dashboard APIs**: `/api/status`, `/api/ledger`, **download journal**
- **Charts**: equity & cash line chart (30d)
- **One-click controls**: Pause/Resume/Reset Kill‑Switch via UI buttons


## What v9 adds (cash sweep + control)
- **Daily Rebalance-to-Buffer** sweep (auto-invests excess idle cash while preserving buffer).
- **Daily report** to Discord (simple summary; extend as needed).
- **Option MTM** included in equity estimate (paper broker), for more realistic P/L.
- **Option controls in UI**: list open positions; one-click close (paper).
- **Discord commands**: `!report`, `!config` added.
- **Flask secret key** + `.env` improvements.
- **docker-compose** with healthcheck & persisted data volume.


## What v10 adds (cash‑only enforcement)
- **Margin policy (configurable)**: `cash_only` (default) or `forbid` (hard fail if margin account detected).
- **Cash‑only preflight** for CSPs/spreads/condors — requires full collateral/max loss in cash before entry.
- **Collateral reservation** for spreads/condors in paper broker (cash reflects reserved requirement).
- **DTE window** for entries (default 21–35 DTE).
- **Force Rebalance** button & API.


### Rate limits (defaults; configurable in `limits.*`)
- **Schwab (individual)**: ~120 requests/min **data**, ~2–4 trade req/sec (unofficial community guidance). We default to **110/min** and **2/sec** to stay safe.
- **Tradier**: ~120/min is common guidance; we default to **110/min**.
- **Alpaca**: ~200/min often cited; we keep the same safe default unless you raise it.

You can tune these in `config.yaml -> limits`.


### Panic close
- **Dashboard:** “Close All Options” button attempts to close every open option position (paper wired; live adapters should wire native multi‑leg close as supported by your broker).
- **Discord:** `!closeall`


## Multi-asset configuration
Use `symbols:` to define multiple assets with weights and strategy sets:
```yaml
weekly_dca_total: 100
symbols:
  - ticker: QQQM
    options_ticker: QQQ
    weight: 0.45
    strategies: [dca, wheel, credit_spreads, iron_condor]
    max_alloc_pct: 0.50
  - ticker: VTI
    options_ticker: VTI
    weight: 0.25
    strategies: [dca]
    max_alloc_pct: 0.35
```
The engine splits weekly DCA by weight and attempts one new entry per asset per cycle, respecting RiskGuard caps.

# Trader Terminal — Kronos-Guided MES Decision Support

A private research/decision-support terminal for forward testing and
discretionary MES trading. It combines CFTC COT positioning, dealer GEX
(5×/NY session), a live news risk score, hourly + daily Kronos forecasts, a
**Kronos-Guided Kalman Filter**, a transparent **Kronos Respect Score**, and a
unified regime engine (bias / environment / confidence / playbook /
invalidations).

**This is NOT a trading bot.** No broker connection, no order execution.
COT is weekly positioning (never intraday timing). GEX levels shown on the
MES scale are approximate proxy conversions from SPX/SPY and are labeled
as such everywhere.

Core hypothesis the terminal tests: *Kronos is the "intended path" of price.
The terminal's job is to answer: is today's market respecting Kronos,
rejecting Kronos, or distorting Kronos because of external forces (gamma,
news, positioning, events)?*

---

## 1. File tree

```
trader-terminal/
  .env.example                  <- documented env template (copy to backend/.env)
  README.md
  backend/                      <- FastAPI + SQLAlchemy + APScheduler (Python)
    requirements.txt
    pytest.ini
    .env                        <- your config/secrets (never commit)
    scripts/
      _kronos_path_inner.py     <- runs INSIDE the kronos skill venv; emits the
                                   full forecast path + ensemble bands as JSON
    app/
      main.py                   <- FastAPI app, lifespan starts the scheduler
      config.py                 <- every knob, loaded from .env (pydantic-settings)
      db.py                     <- engine/session; SQLite default, Postgres via URL
      models.py                 <- all 10 tables (UTC timestamps)
      time_utils.py             <- UTC<->NY, session status (premarket/RTH/AH/closed)
      adapters/
        flashalpha.py           <- GEX: GET /v1/exposure/gex/{symbol}, X-Api-Key,
                                   error envelopes, SPX->SPY fallback
        selfcomputed_gex.py     <- GEX fallback: BS gamma x OI from the yfinance
                                   option chain, true zero-gamma flip (used when
                                   FlashAlpha is tier-restricted/quota'd)
        cftc_cot.py             <- CFTC Socrata (legacy 6dca-aqww + TFF gpe5-46if)
        news_providers.py       <- provider abstraction: yfinance (default) / NewsAPI
        kronos_import.py        <- Mode A: JSON/CSV manual import + validation
        kronos_local.py         <- Mode B: subprocess into the kronos skill venv
      engine/                   <- pure, transparent math (no I/O)
        kalman.py               <- kronos_guided_kalman_filter()
        respect.py              <- Kronos Respect Score (5 sub-scores, total 100)
        gex_regime.py           <- regime classification + GEX score + conversion
        cot_score.py            <- net/percentile/4w/13w/crowding/exposure score
        news_score.py           <- lexicon scoring + red folder + aggregate
        regime.py               <- unified regime engine
        alerts.py               <- alert condition diffing (prev vs new state)
      services/                 <- DB orchestration per pillar
        price_service.py  gex_service.py  cot_service.py
        news_service.py   kronos_service.py  regime_service.py
      api/routes.py             <- all /api/trader-terminal/* endpoints
      jobs/scheduler.py         <- APScheduler job definitions (NY-time crons)
      seed/demo_seed.py         <- DEMO mode (clearly labeled synthetic data)
    tests/                      <- 116 tests (engines, adapters, API integration)
  frontend/                     <- Next.js 16 + TypeScript + Tailwind (dark only)
    next.config.ts              <- proxies /api/trader-terminal/* -> backend
    app/dashboard/trader-terminal/page.tsx
    lib/  (types.ts, api.ts, format.ts, useApi.ts)
    components/
      ui.tsx                    <- Card/Badge/Tooltip/Button/StatusDot primitives
      terminal/
        ControlBar.tsx  ScoreRow.tsx  MainChart.tsx (lightweight-charts)
        KronosPanel.tsx SidePanel.tsx BottomPanels.tsx
```

## 2. Installation

```powershell
# backend
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy ..\.env.example .env          # then edit .env

# frontend
cd ..\frontend
pnpm install
```

Database: nothing to install — defaults to SQLite (`backend/terminal.db`).
For PostgreSQL set `DATABASE_URL=postgresql+psycopg2://...` (install
`psycopg2-binary` on Windows manually if you switch).

## 3. Environment variables

All in `backend/.env` (see `.env.example` for the documented template):

| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (SQLite default, Postgres supported) |
| `FLASHALPHA_API_KEY` | real dealer GEX (lab.flashalpha.com) — required for GEX |
| `NEWS_API_KEY` | optional; switches news provider from yfinance to NewsAPI |
| `MARKET_DATA_TICKER` | yfinance ticker observed as MES (default `MES=F`) |
| `GEX_PRIMARY_SYMBOL` / `GEX_SECONDARY_SYMBOL` | proxy priority (SPX, SPY) |
| `GEX_SCHEDULE` | comma list of NY snapshot times (default 09:35,10:30,11:30,13:30,15:30) |
| `ENABLE_LOCAL_KRONOS` | `true` to run the local Kronos model on schedule |
| `KRONOS_MODEL_PATH` / `KRONOS_DEVICE` | override model repo dir / cpu-cuda |
| `ENABLE_SCHEDULER` / `ENABLE_GEX_JOBS` / `ENABLE_COT_JOBS` / `ENABLE_NEWS_SCORING` | job switches |
| `NEWS_REFRESH_MINUTES` | news job cadence during market hours (5–15) |
| `KALMAN_SLIDER_DEFAULT` | default Kronos Trust / Kalman Reactivity (0–100) |
| `DEMO_SEED` | `true` = load clearly-labeled synthetic data into an EMPTY db |

## 4. Run it

### Desktop shortcut (normal use)

Double-click **Trader Terminal** on the Desktop. It runs
`scripts\launch.ps1` hidden: starts the backend (:8000) and the production
frontend (:3000) if they aren't already running, waits until both answer,
and opens the browser at `/dashboard/trader-terminal`. Idempotent — if the
servers are already up it just opens the page. **Stop Trader Terminal**
kills both servers. Launch log: `%TEMP%\trader-terminal-launch.log`.

### Dev servers (when changing code)

```powershell
# terminal 1 — API (port 8000)
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# terminal 2 — UI (port 3000)
cd frontend
pnpm dev
```

Open **http://localhost:3000/dashboard/trader-terminal**.
(If the backend runs elsewhere: `BACKEND_URL=http://host:port pnpm dev`.)

## 5. Background jobs

Jobs run **in-process** with the API via APScheduler (no Redis needed) as
long as `ENABLE_SCHEDULER=true`. Schedules are America/New_York:

- `cot_update` — daily 16:10 ET, fetches only when a new report is due
- `gex_0935 … gex_1530` — one job per `GEX_SCHEDULE` slot, Mon–Fri
- `news_rating` — every `NEWS_REFRESH_MINUTES` during market hours
- `price_refresh` — every 15 min during market hours (feeds the Kalman filter)
- `kronos_hourly` / `kronos_daily` — only if `ENABLE_LOCAL_KRONOS=true`
- `terminal_regime` — every 5 min in market hours + after every data update

Every job logs to the API console; failures are logged, never swallowed.

## 6. Manually import a Kronos forecast (Mode A)

UI: bottom panel → **Kronos** tab → paste JSON or CSV → Import.

API:
```bash
curl -X POST localhost:8000/api/trader-terminal/kronos/import \
  -H "Content-Type: application/json" -d '{
  "symbol": "MES", "horizon": "hourly",
  "generated_at": "2026-06-12T13:00:00Z",
  "path":       [["2026-06-12T14:00:00Z", 6010], ["2026-06-12T15:00:00Z", 6040]],
  "band_upper": [["2026-06-12T14:00:00Z", 6030], ["2026-06-12T15:00:00Z", 6060]],
  "band_lower": [["2026-06-12T14:00:00Z", 5990], ["2026-06-12T15:00:00Z", 6020]],
  "confidence": 72, "model_version": "Kronos-small"
}'
```
CSV format: header `timestamp,value[,upper,lower]`, wrapped as
`{"format":"csv","csv":"...","horizon":"hourly"}`. Malformed input returns
HTTP 422 with the exact problem; imports never half-succeed.

Local runner (Mode B): set `ENABLE_LOCAL_KRONOS=true`. It reuses the
already-provisioned `~/.claude/skills/kronos/.venv` + model repo via
`scripts/_kronos_path_inner.py` (no torch in this backend). Trigger manually:
`POST /api/trader-terminal/kronos/run?horizon=hourly` (CPU inference takes
minutes). If Kronos is unavailable the panel says so and everything else
keeps working.

## 7. Trigger a GEX refresh

UI: bottom panel → **GEX** tab → "Fetch GEX now".
API: `curl -X POST localhost:8000/api/trader-terminal/gex/refresh`
Tries SPX first, falls back to SPY; every snapshot (including failures) is
stored with status (`ok` / `partial` / `single_expiry` / `error`) so the UI
shows exactly what happened. Mind the FlashAlpha free-tier quota (~5/day) —
the scheduled 5 slots use it fully.

## 8. Verify COT data

`curl -X POST "localhost:8000/api/trader-terminal/cot/refresh?force=true"`
then `curl localhost:8000/api/trader-terminal/cot`. Source is the official
CFTC Socrata API (no key): legacy dataset `6dca-aqww`, TFF `gpe5-46if`,
market code `13874A` (E-MINI S&P 500, CME) as the MES macro proxy. Cross-
check raw values against cftc.gov "Commitments of Traders". The panel shows
report date, as-of date (the Tuesday), and a staleness badge; reports older
than 11 days are flagged "newer release likely exists".

## 9. How to read the Kronos Respect Score

0–100, five disclosed components (formulas in code + UI tooltips):

| Component | Max | Measures |
|---|---|---|
| Direction agreement | 25 | realized moves vs forecast moves (per-step + net) |
| Path correlation | 25 | Pearson r of realized path vs Kronos path |
| Band respect | 20 | fraction of observations inside the ±2σ band |
| Kalman residual | 20 | magnitude (mean \|z\|) + persistence of residuals |
| Invalidation | 10 | −3 per persistent-breach episode |

80–100 highly respected · 60–79 respected/noisy · 40–59 mixed ·
20–39 weak · 0–19 failing or inverted. The status banner upgrades to
**FAILING** (persistent \|z\|>2.5) or **INVERTED — FADE WARNING** (net move
opposite + negative increment correlation) regardless of the number.

## 10. How to read the Kronos-Guided Kalman Filter

This is not a price smoother. The **Kronos path is the prior** ("intended
path"); live MES price is the measurement. The filter state is the
*deviation from the Kronos path*, with the prior pulling deviation toward
zero. The violet dashed line on the chart is the filtered estimate:

- estimate hugging the amber Kronos line → market respecting the forecast
- estimate migrating to the candles → market overriding the forecast
- red circles (\|z\|>2.5) → forecast-failure zones

**Kronos Trust / Kalman Reactivity** slider: 0 = trust Kronos (gain≈0.001,
very slow to abandon the forecast), 50 = balanced (gain 0.5), 100 = trust
live price (gain≈0.999, fastest failure detection). Mathematically:
`Q/R = 10^((slider-50)/16.7)`, steady-state gain `= ratio/(1+ratio)`.
Forecast bands set the measurement noise: a confident (narrow-band)
forecast makes the same deviation more damning.

## 11. How to interpret the unified regime card

- **Bias** (long/short/neutral/no-trade): Kronos direction, *gated* by the
  Respect Score (≥60 required for a directional bias; <40 = no-trade;
  strong opposing news downgrades; Red Folder + weak respect = no-trade).
- **Environment**: negative gamma + direction → continuation; positive
  gamma + direction → mean reversion (enter on pullbacks, don't chase);
  positive gamma, no direction → consolidation; failing/inverted forecast →
  reversal risk; Red Folder → event risk.
- **Confidence** 0–100: starts at 50; every adjustment (respect, 1H/1D
  agreement, GEX/news/COT alignment, red-folder and failure penalties) is
  listed verbatim — hover the number.
- **Playbook / Reasons / Invalidations / What would change my mind**: the
  full reasoning trail. If you can't explain the regime from the card, that
  is a bug.

## 12. What is stubbed or needs real keys

- **GEX**: a FlashAlpha key is configured, but the free tier rejects SPX,
  SPY *and* ES (`tier_restricted` — index/ETF GEX needs their Basic plan).
  Until the plan is upgraded, every refresh automatically falls back to the
  **self-computed GEX** (Black-Scholes gamma x open interest from the live
  ^SPX option chain, true zero-gamma flip) — stored/labeled
  `self_computed`, approximate by construction (EOD open interest, retail
  convention). Upgrading the FlashAlpha plan instantly switches back to
  real dealer GEX with zero code changes. Disable the fallback with
  `ENABLE_SELF_COMPUTED_GEX=false`.
- **News** defaults to the free yfinance provider (headline coverage is
  decent but not a pro feed). `NEWS_API_KEY` switches to NewsAPI. Scoring is
  a transparent keyword lexicon — deliberately not an LLM black box.
- **Local Kronos** requires the kronos skill venv + model
  (`~/.claude/skills/kronos/`) and is CPU-slow; otherwise use manual import.
- **Prices** come from yfinance `MES=F` (free, ~15s-delayed ticks, hourly
  candles). `MARKET_DATA_API_KEY` is reserved for a paid feed adapter later.
- **Email alerts** are not implemented (by design): alerts are in-app +
  console. The condition engine (`engine/alerts.py`) is transport-agnostic,
  so an email sender can be added without touching conditions.
- **VIX / RVOL / volume-profile (POC) inputs** to the regime engine are
  accepted by the engine signature but not yet fed by a service — the spec
  marks POC/volume-profile levels as a later addition.
- **Demo mode** (`DEMO_SEED=true`): synthetic data for UI review only; every
  row is tagged DEMO and real live prices are never injected into demo
  forecasts.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest        # 116 tests
```

Covers: Kalman (all 7 spec scenarios + slider), respect composite, GEX
parsing/fallback/regimes/distances, COT math + staleness + CFTC quirks
(including their misspelled `noncomm_postions_spread_all` column), news
lexicon + red folder + aggregation, Kronos import validation (8 malformed
cases), regime engine (5 spec scenarios), alert conditions, and full API
integration (import → respect → regime → alerts → acknowledge).

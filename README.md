# Trader Terminal

A market decision-support dashboard for discretionary MES (Micro E-mini S&P 500) trading. It takes
an AI price forecast and continuously evaluates whether the market is following that forecast or
being pulled away from it by dealer positioning, institutional flow, and news. It was built with
Claude Code from a trader's perspective: the design follows trading logic, and AI was used to
implement it.

> A personal research project. It is **decision support, not a trading bot** — there is no broker
> connection and no order execution.

---

## Screenshot

![Trader Terminal — live dashboard](docs/screenshot-dashboard.png)

> The live terminal: the candlestick chart with the Kronos forecast path, the score row, the regime
> read, and live alerts.

---

## Hypothesis

The terminal is built to test one idea:

> **An AI forecast describes the "intended path" of price. Profitable discretionary timing comes not
> from the forecast alone, but from knowing when the market is respecting it, rejecting it, or
> distorting it because of an external force.**

A forecast in isolation is fragile — dealer gamma, institutional positioning, and news routinely
push price off any predicted path. The terminal's purpose is to make that relationship measurable:
to show, at any moment, how closely price is tracking the forecast and which external forces are
most likely bending it.

---

## What it does

At a glance, the terminal answers four questions:

1. **What is the AI's expected path?** — Kronos hourly and daily forecasts with confidence bands,
   plotted directly on the chart.
2. **Is price respecting that path?** — a transparent **Respect Score** (0–100) that grades how
   closely current action is tracking the forecast.
3. **What environment are we in?** — a **regime read** combining directional bias, market
   environment, a confidence score, and the price levels that would invalidate the thesis.
4. **What changed?** — live alerts when the regime, respect, or any underlying signal shifts.

---

## How it works

The terminal pulls several independent signals, scores each one separately, and combines them into a
single regime read. Inputs are kept strictly distinct so one never silently overrides another.

| Signal | What it measures | How it's used |
|---|---|---|
| **Kronos forecast** | Forward price path (hourly + daily) with confidence bands, from the open-source [Kronos](https://github.com/shiyu-coder/Kronos) model | The "intended path." A wide band signals noise; a tight band signals a setup worth attention. |
| **Respect Score** | How closely live price tracks the forecast | A 0–100 score built from several sub-scores; the core read on whether the forecast is being honored. |
| **Dealer gamma (GEX)** | Where dealer hedging pins or accelerates price, and the zero-gamma flip | Defines the market *environment* (calm/pinned vs. fast/trending) and key levels. Pulled from a data provider, with a self-computed fallback when that feed is unavailable. |
| **Institutional positioning (COT)** | How large participants are positioned (net, percentiles, crowding) | Weekly CFTC data flagging squeeze risk and positioning extremes. |
| **News risk** | Elevated headline and event risk | A scored read that raises caution around scheduled and breaking events. |

These feed a **regime engine** that outputs the final bias, environment, confidence, and invalidation
levels, plus the alerts. Because every score is transparent, each output can be traced back to the
inputs that produced it.

---

## Use case

The intended user is a discretionary MES trader during the session. Rather than issuing buy/sell
signals, the terminal provides context for a human decision: it shows the AI's expected path, whether
the market is honoring it, and what is most likely to disrupt it — so the trader can size, time, and
invalidate ideas with a clearer view of the environment. It is equally useful as a forward-testing
tool for evaluating whether the forecast actually adds an edge over time.

---

## How it was built

The trading logic is mine; the implementation was written with Claude Code and refined through
testing against real market behavior. It is a Python application with a web dashboard and runs on
free market data by default (no paid API keys required). A full breakdown of every input and how each
score is calculated is documented in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Running it locally

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env          # runs with no keys: defaults to SQLite + free data sources
uvicorn app.main:app --reload

# frontend (the dashboard)
cd frontend
pnpm install
pnpm dev
```

---

## Scope and limitations

This is a research and decision-support tool. It does not place trades and is not financial advice.
Some displayed values (such as MES-scale gamma) are approximate conversions from SPX/SPY and are
labeled as such. The objective was to test, from a trader's standpoint, whether an AI forecast holds
up once dealer positioning, institutional flow, and news risk are taken into account.

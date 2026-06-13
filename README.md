# Trader Terminal

A market decision-support dashboard that takes an AI price forecast and evaluates it against the
forces that move markets. It was built with Claude Code from a trader's perspective rather than a
software engineer's: the design follows trading logic, and AI was used to implement it.

> A personal research project. It is **decision support, not a trading bot** — there is no broker
> connection and no order execution.

---

## Screenshot

![Trader Terminal — live dashboard](docs/screenshot-dashboard.png)

> The live terminal: the candlestick chart with the Kronos forecast path, the score row, the regime
> read, and live alerts.

---

## Concept

Most tools present a forecast and stop there. This terminal addresses a more useful question for a
discretionary trader: *is the market respecting the forecast, rejecting it, or distorting it because
of an external force?*

The AI forecast is treated as the "intended path" of price. The terminal scores how current price
action aligns with that path, while accounting for the factors that bend price away from any
forecast.

---

## Inputs

| Signal | Role |
|---|---|
| **Kronos AI forecast** | Hourly and daily forward paths with confidence bands, from the open-source [Kronos](https://github.com/shiyu-coder/Kronos) model. A wide band indicates noise; a tight band indicates a setup worth attention. |
| **Dealer gamma (GEX)** | Identifies where dealer hedging tends to pin or accelerate price, including the zero-gamma flip where the regime changes. |
| **Institutional positioning (COT)** | Weekly CFTC data showing how large participants are positioned and where squeeze risk sits. |
| **News risk** | A read on elevated headline and event risk. |

Each input answers one question and nothing else, so the signals stay distinct. They combine into a
single **regime read**: directional bias, market environment, a confidence score, and the price
levels that would invalidate the thesis.

---

## How it was built

The trading logic is mine; the implementation was written with Claude Code and refined through
testing against real market behavior. It is a Python application with a web dashboard and runs on
free market data by default (no paid API keys required).

A full breakdown of every input and how each score is calculated is documented in
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

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
Some displayed values (such as MES-scale gamma) are approximate conversions and are labeled as such.
The objective was to test, from a trader's standpoint, whether an AI forecast holds up once dealer
positioning, institutional flow, and news risk are taken into account.

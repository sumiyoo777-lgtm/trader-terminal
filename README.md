# Trader Terminal

**A full-stack market decision-support terminal I designed and built end-to-end** —
a FastAPI + Next.js system that fuses six independent market signals into a single,
transparent, *auditable* read on the market. Every number it shows can be traced back
to the assumption that produced it.

> Built solo as a research project. ~6,000+ lines across a Python backend and a
> TypeScript/React frontend. It is **decision support, not a trading bot** — there is
> no broker connection and no order execution, by design.

<!-- EDITABLE: Add one honest sentence about WHY you built this. Reviewers remember
     motivation. e.g. "I wanted to find out whether an AI forecast actually adds edge
     once you account for everything pulling price around it — so I built the instrument
     to measure it." Rewrite in your own voice. -->

---

## What it does

Most market tools hand you a number with no way to know if you should trust it. I built
this to do the opposite: take a forecast and *interrogate* it against everything that
moves real markets, then show its work.

It combines:

- **AI price forecasts** — orchestrates the open-source [Kronos](https://github.com/shiyu-coder/Kronos)
  time-series foundation model to produce hourly and daily forward paths with confidence bands.
- **Dealer gamma exposure (GEX)** — and when the paid data feed is rate-limited, it
  **computes gamma itself** from a live option chain via Black–Scholes, including the true
  zero-gamma flip point.
- **Institutional positioning** — pulls CFTC Commitment-of-Traders data and scores it
  (net position, percentiles, crowding).
- **News risk** — a lexicon-based scoring of live headlines.
- **A Kronos-Guided Kalman Filter** — my own estimator that blends the AI's "intended
  path" with live price.
- **A unified regime engine** — turns all of the above into a single state: bias,
  environment, confidence, playbook, and invalidation levels.

The core question it was built to answer: *is the market today respecting the forecast,
rejecting it, or distorting it because of gamma, news, or positioning?*

---

## What this project demonstrates

*(For anyone reviewing this as a sample of my work.)*

- **Full-stack delivery** — FastAPI + SQLAlchemy + APScheduler backend, Next.js 16 +
  React + TypeScript frontend, all the way to a live dashboard.
- **Clean architecture** — a pure, fully-testable math "engine" layer (Kalman, scoring,
  regime logic) with **zero I/O**, kept strictly separate from the adapters/services that
  talk to the outside world.
- **Engineering for the real world** — graceful fallbacks (self-computed gamma when the
  paid feed is quota'd), `.env`-driven config with secrets kept out of source, and a
  pytest suite.
- **Intellectual honesty in the design** — it refuses to pretend. Wide confidence band =
  noise. Approximate proxy values are labeled as approximate *everywhere*. No fake
  buy/sell signals.

For the deep technical breakdown — every table, adapter, and scoring formula — see
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Python · FastAPI · SQLAlchemy · APScheduler · pydantic-settings · pytest |
| Frontend | Next.js 16 · React · TypeScript |
| Data/Quant | yfinance · CFTC (Socrata) · Black–Scholes option-chain gamma · volume profile |
| AI | open-source Kronos foundation model (forecasting) |
| Storage | SQLite (default) / PostgreSQL |

---

## Running it locally

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env          # fill in optional keys; SQLite + yfinance work with none
uvicorn app.main:app --reload

# frontend
cd frontend
pnpm install
pnpm dev
```

No API keys are required to run it — it defaults to free data sources (SQLite + yfinance).
Optional keys (dealer GEX feed, NewsAPI) unlock the paid data paths.

<!-- EDITABLE: If you add screenshots, drop them in docs/ and link here. A single image of
     the live dashboard makes this README 10x more convincing. Highly recommended. -->

---

## Honest scope

This is a personal research and decision-support tool. It does not place trades, is not
financial advice, and several market values shown (e.g. MES-scale GEX) are clearly-labeled
proxy conversions. The point was never to ship a money printer — it was to build a rigorous
instrument for understanding whether an AI forecast survives contact with a real market.

# Trader Terminal

A market decision-support dashboard I built with AI. **I'm a markets person, not a software
engineer** — I understand trading, and I used Claude Code to build the software around that
understanding. The result is a tool that takes an AI price forecast and stress-tests it against
the forces that actually push markets around.

> Built as a personal research project using Claude Code. It's **decision support, not a trading
> bot** — there's no broker connection and no order execution. I described what I wanted as a
> trader, the AI wrote the code, and I iterated until it did what I needed.

---

## Screenshot

![Trader Terminal — live dashboard](docs/screenshot-dashboard.png)

> The live terminal: the candlestick chart with the Kronos forecast path, the score row, the regime
> read, and live alerts.

---

## The idea (a trader's logic)

Most tools hand you a forecast and stop there. The question I actually care about as a trader is
different: *is the market respecting this forecast, rejecting it, or distorting it because of
something external?*

So the terminal treats the AI forecast as the "intended path" of price and scores how today's
action lines up against it — alongside the things that bend price away from any forecast:

- **Kronos AI forecast** — hourly and daily forward paths with confidence bands, from the
  open-source [Kronos](https://github.com/shiyu-coder/Kronos) model. Wide band = noise; tight band =
  something worth watching.
- **Dealer gamma (GEX)** — where dealer hedging tends to pin price or accelerate it, and the
  zero-gamma flip where the regime changes.
- **Institutional positioning (COT)** — how the big players are leaning, from weekly CFTC data.
- **News risk** — a quick read on headline/event risk.

Everything rolls into one **regime read**: directional bias, the market environment, a confidence
score, and the price levels that would invalidate the idea.

---

## What each input is for

I kept the roles strict so I wouldn't fool myself — each signal answers one question and nothing else:

| Input | What it's for |
|---|---|
| Kronos forecast | The directional "intended path" + a same-day target |
| Dealer gamma | The market *environment* — calm/pinned vs. fast/trending |
| COT positioning | Who's crowded, and where the squeeze risk is |
| News risk | Whether an external shock is more likely than usual |
| Regime read | Ties it together: bias, environment, confidence, invalidation |

---

## How it was built

I'm not a programmer by training, so I leaned on Claude Code the whole way: I'd explain the trading
logic I wanted, it would write the software, and I'd test it against real market behavior and ask
for changes until it was right. It's a Python app with a web dashboard, and it runs on free market
data out of the box (no paid keys required).

If you want the full breakdown of every input and exactly how each score is calculated, it's written
up in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Running it locally

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env          # works with no keys: defaults to SQLite + free data
uvicorn app.main:app --reload

# frontend (the dashboard)
cd frontend
pnpm install
pnpm dev
```

---

## Honest scope

This is a personal research and decision-support tool. It doesn't place trades, it isn't financial
advice, and some of the market values shown (like MES-scale gamma) are clearly-labeled approximate
conversions. The point wasn't to build a money printer — it was to see, as a trader, whether an AI
forecast actually holds up once you account for everything pulling price around.

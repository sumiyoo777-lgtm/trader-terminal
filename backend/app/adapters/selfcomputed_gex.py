"""Self-computed GEX fallback — free, APPROXIMATE, clearly labeled.

Used automatically when FlashAlpha can't serve real dealer GEX (free-tier
key, quota, outage). Ported from kronos_forward_test's battle-tested
gamma_live.py:

  1. Pull the option chain (strikes, OI, IV) via yfinance for the proxy
     (^SPX first, SPY second — mirroring the configured proxy priority).
  2. Black-Scholes gamma per contract (no scipy needed: the standard normal
     pdf is exp(-d1^2/2)/sqrt(2*pi)).
  3. Standard GEX convention: calls contribute +gamma*OI*100*spot^2*1%,
     puts contribute the negative. Positive net GEX -> dealers dampen moves.
  4. Gamma flip = true zero-gamma level: total net GEX is re-evaluated at a
     grid of hypothetical spot levels (gamma recomputed at each level) and
     the flip is where that profile crosses zero — the SqueezeMetrics-style
     methodology, not a cumulative-OI shortcut. Call wall = max call-GEX
     strike; put wall = most negative put-GEX strike.

Output is shaped exactly like a FlashAlpha payload so parse_gex_payload /
the regime engine / the UI consume it unchanged. This is NOT real
dealer-positioning data: OI is end-of-day, IV is yfinance's, and the
convention is the common retail approximation. Every snapshot is stored
with status "self_computed" and an explanatory note.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

log = logging.getLogger(__name__)

RISK_FREE_RATE = 0.05
MAX_EXPIRATIONS = 6  # nearest expirations: 0DTE .. a few weeks out
DEFAULT_CHAIN_SYMBOLS = ["^SPX", "SPY"]  # yfinance tickers, proxy priority
# Only strikes within this band of spot enter the calculation. Deep-OTM tail
# hedges (e.g. 3500 puts with spot at 7400) carry OI but no hedging flow near
# price, and they drag the cumulative zero-crossing (gamma flip) far from the
# strikes that actually matter.
STRIKE_BAND_PCT = 0.15


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_gamma(spot: float, strike: float, t_years: float, iv: float,
             r: float = RISK_FREE_RATE) -> float:
    if t_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / (iv * math.sqrt(t_years))
    return _norm_pdf(d1) / (spot * iv * math.sqrt(t_years))


def _years_to_expiry(expiry_str: str, now: datetime) -> float:
    expiry = datetime.strptime(expiry_str, "%Y-%m-%d").replace(
        hour=16, tzinfo=now.tzinfo or timezone.utc
    )
    delta = (expiry - now).total_seconds() / (365.0 * 24 * 3600)
    return max(delta, 1e-6)


def compute_gex_from_chain(
    spot: float,
    chains: list[tuple[str, list[dict], list[dict]]],
    now: datetime,
) -> dict | None:
    """Pure math, testable without network.

    chains: [(expiry "YYYY-MM-DD", call_rows, put_rows)] where each row has
    strike / impliedVolatility / openInterest.

    Returns a FlashAlpha-shaped payload dict, or None when no usable
    contracts exist (missing OI/IV is common in free chains — say so, never
    guess)."""
    contracts: list[tuple[float, float, float, float, int]] = []  # strike, t, iv, oi, sign
    expirations_used: set[str] = set()

    for expiry_str, calls, puts in chains:
        t_years = _years_to_expiry(expiry_str, now)
        for side, rows in (("call", calls), ("put", puts)):
            for row in rows:
                try:
                    strike = float(row["strike"])
                    iv = float(row.get("impliedVolatility") or 0)
                    oi = float(row.get("openInterest") or 0)
                except (TypeError, ValueError, KeyError):
                    continue
                if iv <= 0 or oi <= 0 or strike <= 0:
                    continue
                if abs(strike - spot) > STRIKE_BAND_PCT * spot:
                    continue  # outside the hedging-relevant band
                contracts.append((strike, t_years, iv, oi, 1 if side == "call" else -1))
                expirations_used.add(expiry_str)

    if not contracts:
        return None
    contracts_used = len(contracts)

    # --- per-strike profile at the CURRENT spot (walls, net GEX) ------------
    # standard GEX convention: calls +, puts - ; positive net GEX => dealer
    # hedging dampens moves
    per_strike: dict[float, dict[str, float]] = {}
    for strike, t_years, iv, oi, sign in contracts:
        gamma = bs_gamma(spot, strike, t_years, iv)
        if gamma <= 0:
            continue
        exposure = gamma * oi * 100.0 * spot * spot * 0.01
        bucket = per_strike.setdefault(strike, {"call_gex": 0.0, "put_gex": 0.0})
        if sign > 0:
            bucket["call_gex"] += exposure
        else:
            bucket["put_gex"] -= exposure

    strike_rows = []
    net_total = 0.0
    for k in sorted(per_strike.keys()):
        net = per_strike[k]["call_gex"] + per_strike[k]["put_gex"]
        net_total += net
        strike_rows.append({
            "strike": k,
            "call_gex": round(per_strike[k]["call_gex"], 2),
            "put_gex": round(per_strike[k]["put_gex"], 2),
            "net_gex": round(net, 2),
        })

    # --- true zero-gamma flip: net GEX profile across hypothetical spots ----
    flip = _zero_gamma_level(contracts, spot)

    return {
        "underlying_price": round(spot, 2),
        "net_gex": round(net_total, 2),
        "net_gex_label": ("positive" if net_total >= 0 else "negative") + " (self-computed)",
        "gamma_flip": round(flip, 2) if flip is not None else None,
        "strikes": strike_rows,
        "expirations": sorted(expirations_used),
        "as_of": now.isoformat(),
        "source": "self_computed",
        "note": (
            f"Self-computed approximation: BS gamma x OI over {contracts_used} contracts / "
            f"{len(expirations_used)} expirations (yfinance chain, EOD open interest). "
            "Not real dealer-positioning data — treat flip/walls as zones, not exact lines."
        ),
    }


def _net_gex_at(contracts: list[tuple[float, float, float, float, int]], level: float) -> float:
    total = 0.0
    for strike, t_years, iv, oi, sign in contracts:
        gamma = bs_gamma(level, strike, t_years, iv)
        if gamma > 0:
            total += sign * gamma * oi * 100.0 * level * level * 0.01
    return total


def _zero_gamma_level(
    contracts: list[tuple[float, float, float, float, int]],
    spot: float,
    grid_points: int = 61,
) -> float | None:
    """True zero-gamma flip: evaluate the total net GEX profile at a grid of
    hypothetical spot levels (gamma recomputed per level) inside the strike
    band and linearly interpolate the zero crossing. Returns None when the
    profile never crosses zero inside the band (no flip near price — the
    regime then falls back to the sign of net GEX, and no fake level is
    reported)."""
    lo = spot * (1.0 - STRIKE_BAND_PCT)
    hi = spot * (1.0 + STRIKE_BAND_PCT)
    step = (hi - lo) / (grid_points - 1)
    levels = [lo + i * step for i in range(grid_points)]
    profile = [_net_gex_at(contracts, level) for level in levels]

    for i in range(len(profile) - 1):
        y0, y1 = profile[i], profile[i + 1]
        if y0 == 0:
            return round(levels[i], 2)
        if y0 * y1 < 0:
            x0, x1 = levels[i], levels[i + 1]
            return round(x0 + (0 - y0) * (x1 - x0) / (y1 - y0), 2)
    return None


def fetch_self_computed_gex(
    symbols: list[str] | None = None,
    max_expirations: int = MAX_EXPIRATIONS,
    now: datetime | None = None,
) -> tuple[str | None, dict | None, list[str]]:
    """Network wrapper: try each yfinance chain symbol in order.
    Returns (symbol_used, payload, attempt_notes)."""
    now = now or datetime.now(timezone.utc)
    notes: list[str] = []
    try:
        import yfinance as yf
    except ImportError:
        return None, None, ["yfinance not installed"]

    for symbol in symbols or DEFAULT_CHAIN_SYMBOLS:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            spot = float(info.get("lastPrice") if hasattr(info, "get") else info.last_price)
            expirations = list(ticker.options)[:max_expirations]
        except Exception as exc:
            notes.append(f"{symbol}: chain unavailable ({exc})")
            continue
        if not expirations or spot <= 0:
            notes.append(f"{symbol}: no expirations or bad spot")
            continue

        chains: list[tuple[str, list[dict], list[dict]]] = []
        for expiry in expirations:
            try:
                chain = ticker.option_chain(expiry)
                chains.append((
                    expiry,
                    chain.calls.to_dict("records"),
                    chain.puts.to_dict("records"),
                ))
            except Exception as exc:
                notes.append(f"{symbol} {expiry}: {exc}")
                continue

        payload = compute_gex_from_chain(spot, chains, now)
        if payload is None:
            notes.append(f"{symbol}: no usable OI/IV contracts in chain")
            continue
        display = symbol.lstrip("^")
        return display, payload, notes

    return None, None, notes

"""GEX regime classification and the transparent GEX Regime Score.

Regime labels:
  positive  — dealers long gamma: hedging dampens moves. Favor mean
              reversion / POC-range logic; be careful chasing breakouts.
  negative  — dealers short gamma: hedging amplifies moves. Favor
              momentum/expansion; DTOB/gamma targets more relevant.
  near_flip — spot within `near_flip_pct` of the gamma flip: transition
              zone, expect instability, lower conviction.
  unknown   — data unavailable: say so, never guess.

GEX Regime Score (-100..+100). Sign = regime, magnitude = how decisively
spot sits on that side of the flip:

    dist_pct = |spot - gamma_flip| / spot * 100
    intensity = 100 * clip(dist_pct / 1.0, 0.25, 1.0)     # saturates 1% away
    score = +intensity in positive gamma, -intensity in negative gamma
    near_flip -> score keeps its sign but is capped at +/-25
    unknown -> None

The sign is NOT a long/short bias — positive means "mean-reversion
environment", negative means "expansion environment".
"""
from __future__ import annotations

from dataclasses import dataclass, field

REGIME_GUIDANCE = {
    "positive": [
        "Favor mean reversion",
        "Respect POC/range logic",
        "Be careful chasing breakouts",
    ],
    "negative": [
        "Favor momentum/expansion",
        "DTOB/gamma targets become more relevant",
        "Breakouts can continue harder",
    ],
    "near_flip": [
        "Transition zone",
        "Expect instability",
        "Be careful with conviction",
    ],
    "unknown": ["GEX unavailable — do not assume a gamma regime"],
}


@dataclass
class GexRegime:
    regime: str  # positive | negative | near_flip | unknown
    score: float | None  # -100..+100, None when unknown
    distance_to_flip: float | None  # points, spot - flip (sign meaningful)
    distance_to_flip_pct: float | None
    distance_to_call_wall: float | None
    distance_to_put_wall: float | None
    guidance: list[str] = field(default_factory=list)
    explanation: str = ""


def classify_gex_regime(
    net_gex: float | None,
    spot: float | None,
    gamma_flip: float | None,
    call_wall: float | None = None,
    put_wall: float | None = None,
    near_flip_pct: float = 0.35,
) -> GexRegime:
    dist = dist_pct = dist_call = dist_put = None
    if spot is not None:
        if gamma_flip is not None:
            dist = round(spot - gamma_flip, 2)
            dist_pct = round(abs(dist) / spot * 100.0, 4)
        if call_wall is not None:
            dist_call = round(call_wall - spot, 2)
        if put_wall is not None:
            dist_put = round(spot - put_wall, 2)

    # Which side of the flip are we on? Prefer spot-vs-flip; fall back to
    # the sign of net GEX when only one is available.
    side: str | None = None
    if dist is not None:
        side = "positive" if dist >= 0 else "negative"
    elif net_gex is not None:
        side = "positive" if net_gex >= 0 else "negative"

    if side is None:
        return GexRegime(
            regime="unknown", score=None,
            distance_to_flip=dist, distance_to_flip_pct=dist_pct,
            distance_to_call_wall=dist_call, distance_to_put_wall=dist_put,
            guidance=REGIME_GUIDANCE["unknown"],
            explanation="No net GEX and no spot/flip pair available.",
        )

    near = dist_pct is not None and dist_pct < near_flip_pct
    regime = "near_flip" if near else side

    sign = 1.0 if side == "positive" else -1.0
    if dist_pct is None:
        intensity = 25.0  # only net-GEX sign known — low conviction
        why = f"only net GEX sign known (net_gex={net_gex}) -> intensity floor 25"
    else:
        intensity = 100.0 * max(0.25, min(1.0, dist_pct / 1.0))
        why = f"|spot-flip| = {dist_pct:.2f}% of spot -> intensity {intensity:.0f}"
    if near:
        intensity = min(intensity, 25.0)
        why += f" ; capped at 25 (within near-flip zone {near_flip_pct}%)"

    return GexRegime(
        regime=regime,
        score=round(sign * intensity, 1),
        distance_to_flip=dist,
        distance_to_flip_pct=dist_pct,
        distance_to_call_wall=dist_call,
        distance_to_put_wall=dist_put,
        guidance=REGIME_GUIDANCE[regime],
        explanation=f"side={side} ({why}); sign=+mean-reversion/-expansion, not long/short bias",
    )


# ---------------------------------------------------------------------------
# Proxy -> MES conversion helper. APPROXIMATE by construction — SPX/SPY
# options structure does not map exactly onto MES futures. Labeled as such
# everywhere it is displayed.
# ---------------------------------------------------------------------------
STATIC_MULTIPLIERS = {"SPX": 1.0, "SPY": 10.0, "ES": 1.0}


def conversion_factor(
    proxy_symbol: str,
    proxy_price: float | None,
    trading_price: float | None,
) -> tuple[float, str]:
    """Prefer a dynamic ratio (trading_price / proxy_price) which absorbs
    futures basis; fall back to the static multiplier. Returns
    (factor, method)."""
    if proxy_price and trading_price:
        return trading_price / proxy_price, "dynamic_ratio"
    return STATIC_MULTIPLIERS.get(proxy_symbol.upper(), 1.0), "static_multiplier"


def convert_level(level: float | None, factor: float) -> float | None:
    if level is None:
        return None
    return round(level * factor, 2)

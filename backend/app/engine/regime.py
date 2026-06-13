"""Unified Terminal Regime Engine — rule-based, fully explainable.

Combines Kronos direction + Respect Score, GEX regime, COT positioning,
news risk, and the Red Folder flag into:

    bias        : long | short | neutral | no_trade
    environment : continuation | consolidation | mean_reversion |
                  reversal_risk | event_risk | no_trade
    confidence  : 0-100 (additive formula, every term listed in reasons)
    playbook    : concrete best-playbook line
    reasons / invalidations / what_would_change_my_mind

No vague AI scoring: every rule that fires appends a human-readable reason,
and the confidence formula terms are returned verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RESPECT_HIGH = 60.0
RESPECT_LOW = 40.0
NEWS_STRONG = 40.0


@dataclass
class RegimeInputs:
    kronos_hourly_direction: str | None = None  # UP | DOWN | NEUTRAL | CHOP | None
    kronos_daily_direction: str | None = None
    kronos_respect_score: float | None = None
    kronos_confidence: float | None = None
    forecast_failing: bool = False
    forecast_inverted: bool = False

    gex_regime: str = "unknown"  # positive | negative | near_flip | unknown
    gex_score: float | None = None
    distance_to_flip_pct: float | None = None
    distance_to_call_wall: float | None = None
    distance_to_put_wall: float | None = None

    cot_score: float | None = None
    news_score: float | None = None
    red_folder: bool = False

    vix: float | None = None
    session_status: str = "rth"


@dataclass
class RegimeDecision:
    bias: str
    environment: str
    confidence: float
    playbook: str
    reasons: list[str] = field(default_factory=list)
    invalidations: list[str] = field(default_factory=list)
    what_would_change_my_mind: list[str] = field(default_factory=list)
    confidence_terms: list[str] = field(default_factory=list)


def _dir_sign(direction: str | None) -> int:
    if direction == "UP":
        return 1
    if direction == "DOWN":
        return -1
    return 0


def evaluate_regime(x: RegimeInputs) -> RegimeDecision:
    reasons: list[str] = []
    confidence_terms: list[str] = []
    confidence = 50.0

    def add_conf(delta: float, why: str):
        nonlocal confidence
        confidence += delta
        confidence_terms.append(f"{'+' if delta >= 0 else ''}{delta:g}: {why}")

    hd = x.kronos_hourly_direction
    dd = x.kronos_daily_direction
    respect = x.kronos_respect_score
    h_sign = _dir_sign(hd)

    # ---------------- bias ----------------
    if hd is None:
        bias = "no_trade"
        reasons.append("No Kronos forecast available — no directional thesis to trade.")
    elif x.forecast_inverted:
        bias = "no_trade"
        reasons.append(
            f"Kronos says {hd} but the market is moving persistently against it "
            "(inverted forecast) — fade warning, stand aside until a fresh forecast."
        )
    elif respect is not None and respect < RESPECT_LOW:
        bias = "no_trade"
        reasons.append(
            f"Kronos Respect Score {respect:.0f} < {RESPECT_LOW:.0f}: the market is "
            "not following the forecast — directional bets off."
        )
    elif hd in ("NEUTRAL", "CHOP"):
        bias = "neutral"
        reasons.append(f"Kronos hourly direction is {hd} — no directional edge claimed.")
    elif respect is not None and respect < RESPECT_HIGH:
        bias = "neutral"
        reasons.append(
            f"Kronos points {hd} but Respect Score {respect:.0f} is mixed "
            f"({RESPECT_LOW:.0f}-{RESPECT_HIGH:.0f}) — wait for the tape to commit."
        )
    else:
        bias = "long" if h_sign > 0 else "short"
        respect_txt = f"{respect:.0f}" if respect is not None else "unscored"
        reasons.append(
            f"Kronos hourly {hd} with Respect Score {respect_txt} — "
            "market is following the forecast."
        )

    # strong opposing news downgrades a directional bias
    if bias in ("long", "short") and x.news_score is not None:
        opposing = (bias == "long" and x.news_score < -NEWS_STRONG) or (
            bias == "short" and x.news_score > NEWS_STRONG
        )
        if opposing:
            bias = "neutral"
            reasons.append(
                f"News risk score {x.news_score:.0f} strongly opposes the Kronos direction — "
                "bias downgraded to neutral."
            )

    # Red Folder + unreliable forecast = abnormal conditions, no trade
    if x.red_folder and (respect is None or respect < RESPECT_HIGH):
        bias = "no_trade"
        reasons.append(
            "Red Folder event today with a weak/unproven forecast — abnormal conditions, no-trade."
        )

    # ---------------- environment ----------------
    if x.red_folder:
        environment = "event_risk"
        reasons.append("High-impact macro/Fed event today (Red Folder) — event-risk environment.")
    elif x.forecast_inverted or x.forecast_failing:
        environment = "reversal_risk"
        reasons.append(
            "Kronos forecast is failing/inverted — elevated risk the prevailing move reverses "
            "or extends against the forecast."
        )
    elif bias == "no_trade":
        environment = "no_trade"
    elif x.gex_regime == "negative" and bias in ("long", "short"):
        environment = "continuation"
        reasons.append(
            "Negative gamma: dealer hedging amplifies moves — continuation environment, "
            "breakouts can run."
        )
    elif x.gex_regime == "positive" and bias in ("long", "short"):
        environment = "mean_reversion"
        reasons.append(
            "Positive gamma: dealer hedging dampens moves — direction must be traded via "
            "mean-reversion entries (pullbacks to value), not chases."
        )
    elif x.gex_regime == "positive":
        environment = "consolidation"
        reasons.append("Positive gamma with no directional edge — consolidation/range environment.")
    elif x.gex_regime == "near_flip":
        environment = "reversal_risk"
        reasons.append("Price pinned near the gamma flip — unstable transition zone.")
    else:
        environment = "consolidation" if bias == "neutral" else "continuation"
        reasons.append(f"GEX regime {x.gex_regime} — defaulting environment from bias.")

    # ---------------- confidence ----------------
    if respect is not None:
        add_conf(round((respect - 50.0) * 0.5, 1), f"Kronos Respect {respect:.0f} (0.5 x (respect-50))")
    if hd and dd:
        if _dir_sign(hd) != 0 and _dir_sign(hd) == _dir_sign(dd):
            add_conf(10, f"daily Kronos ({dd}) agrees with hourly ({hd})")
        elif _dir_sign(hd) * _dir_sign(dd) == -1:
            add_conf(-15, f"daily Kronos ({dd}) opposes hourly ({hd})")
    if x.gex_regime == "negative" and bias in ("long", "short"):
        add_conf(10, "negative gamma supports continuation of a directional move")
    elif x.gex_regime == "positive" and bias in ("long", "short"):
        add_conf(-5, "positive gamma dampens directional follow-through")
    if x.gex_regime == "near_flip":
        add_conf(-15, "near gamma flip — unstable")
    if x.news_score is not None and bias in ("long", "short"):
        aligned = (bias == "long") == (x.news_score >= 0)
        delta = min(10.0, abs(x.news_score) / 10.0)
        add_conf(round(delta if aligned else -delta, 1),
                 f"news score {x.news_score:.0f} {'aligned with' if aligned else 'against'} bias")
    if x.cot_score is not None and bias in ("long", "short"):
        aligned = (bias == "long") == (x.cot_score >= 0)
        add_conf(5 if aligned else -5,
                 f"COT positioning {x.cot_score:.0f} {'aligned' if aligned else 'against'} (slow macro input)")
    if x.red_folder:
        add_conf(-25, "Red Folder event risk")
    if x.forecast_failing or x.forecast_inverted:
        add_conf(-20, "forecast failing/inverted")
    confidence = max(0.0, min(100.0, round(confidence, 1)))

    # ---------------- playbook ----------------
    playbook = _playbook(bias, environment, x, reasons)

    # ---------------- invalidations & change-my-mind ----------------
    invalidations = _invalidations(bias, environment, x)
    change_my_mind = _change_my_mind(bias, x)

    return RegimeDecision(
        bias=bias,
        environment=environment,
        confidence=confidence,
        playbook=playbook,
        reasons=reasons,
        invalidations=invalidations,
        what_would_change_my_mind=change_my_mind,
        confidence_terms=confidence_terms,
    )


def _playbook(bias: str, environment: str, x: RegimeInputs, reasons: list[str]) -> str:
    cautions = []
    if x.distance_to_flip_pct is not None and x.distance_to_flip_pct < 0.5:
        cautions.append("close to gamma flip — reduce size/conviction")
    if x.news_score is not None and abs(x.news_score) > NEWS_STRONG:
        cautions.append("news risk elevated")
    suffix = f" CAUTION: {'; '.join(cautions)}." if cautions else ""

    if bias == "no_trade" or environment in ("event_risk", "no_trade"):
        return "No-trade: signals conflict or conditions abnormal. Stand aside, reassess after the next data update." + suffix
    if environment == "continuation":
        side = "long" if bias == "long" else "short"
        return (
            f"Continuation {side}: POC/pullback entry toward gamma targets; in negative gamma "
            "DTOB/gamma-wall targets are live and breakouts can extend." + suffix
        )
    if environment == "mean_reversion":
        side = "long" if bias == "long" else "short"
        return (
            f"Mean-reversion {side}: wait for LVN/HVN or value-area entries back toward POC in the "
            "Kronos direction; do not chase breakouts in positive gamma." + suffix
        )
    if environment == "consolidation":
        return "Consolidation: LVN/HVN fade entries toward POC; range edges over breakouts." + suffix
    if environment == "reversal_risk":
        return "Reversal-risk: no fresh risk in the old direction; if positioned, tighten. Wait for a new forecast or regime confirmation." + suffix
    return "Neutral: no playbook has edge right now." + suffix


def _invalidations(bias: str, environment: str, x: RegimeInputs) -> list[str]:
    out = []
    if bias in ("long", "short"):
        out.append(f"Kronos Respect Score falling below {RESPECT_LOW:.0f} kills the {bias} thesis.")
        out.append("An hourly close outside the Kronos forecast band against the position.")
        if x.gex_regime == "negative":
            out.append("GEX flipping back positive removes the continuation tailwind.")
        if x.gex_regime == "positive":
            out.append("GEX flipping negative invalidates the mean-reversion framing.")
        out.append("Price crossing the gamma flip against the position direction.")
    if environment == "consolidation":
        out.append("A high-RVOL breakout that holds outside the value area ends the range thesis.")
    if environment == "event_risk":
        out.append("Once the event passes and respect/news normalize, re-evaluate — this no-trade is time-boxed.")
    if not out:
        out.append("A new Kronos forecast or a GEX regime change re-opens the decision.")
    return out


def _change_my_mind(bias: str, x: RegimeInputs) -> list[str]:
    out = [
        f"Kronos Respect Score drops below {RESPECT_LOW:.0f} (currently "
        f"{x.kronos_respect_score:.0f})" if x.kronos_respect_score is not None
        else f"Kronos Respect Score drops below {RESPECT_LOW:.0f}",
        "Price crosses the gamma flip level",
        "Price exits the Kronos forecast band",
        "GEX regime flips sign (positive <-> negative)",
        "News risk score flips sign or breaches +/-40",
        "Hourly and daily Kronos diverge",
    ]
    if x.red_folder:
        out.append("Red Folder event passes without abnormal volatility")
    if bias == "no_trade":
        out.append("A fresh Kronos forecast restores a readable directional thesis")
    return out

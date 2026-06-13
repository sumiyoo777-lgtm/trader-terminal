"""Kronos Respect Score — transparent 0-100 composite.

Components (per spec, totals 100):
  1. Direction Agreement   0-25  : 25 * direction_agreement (blend of
                                   per-step agreement and net-direction match)
  2. Path Correlation      0-25  : Pearson r between realized prices and the
                                   Kronos path over realized steps, mapped
                                   linearly r=-1 -> 0 pts, r=+1 -> 25 pts.
                                   Undefined (flat/short series) -> neutral 12.5.
  3. Forecast Band Respect 0-20  : 20 * fraction of observations inside the
                                   Kronos band (|z| <= 2, band = +/-2 sigma)
  4. Kalman Residual       0-20  : magnitude+persistence component computed
                                   by the Kronos-guided Kalman filter
  5. Invalidation          0-10  : 10 - 3 per invalidation episode (floor 0).
                                   An episode = a distinct persistent breach
                                   (|z| > fail_z for fail_persistence+ steps).

Labels:
  80-100 highly_respected | 60-79 respected_noisy | 40-59 mixed
  20-39 weak_respect      | 0-19 failing_or_inverted
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .kalman import KalmanOutput, _pearson

INVALIDATION_PENALTY = 3.0


@dataclass
class RespectScore:
    score: float
    label: str
    direction_score: float
    correlation_score: float
    band_respect_score: float
    kalman_residual_score: float
    invalidation_score: float
    invalidation_count: int
    forecast_status: str
    explanation: dict = field(default_factory=dict)


def label_for(score: float) -> str:
    if score >= 80:
        return "highly_respected"
    if score >= 60:
        return "respected_noisy"
    if score >= 40:
        return "mixed"
    if score >= 20:
        return "weak_respect"
    return "failing_or_inverted"


def forecast_status(score: float, kalman: KalmanOutput) -> str:
    """The Kronos panel status line. Inversion and persistent failure
    override the numeric bucket."""
    if kalman.inverted:
        return "inverted_fade_warning"
    if kalman.failure_warning:
        return "failing_forecast"
    if score >= 80:
        return "strong_respect"
    if score >= 60:
        return "moderate_respect"
    if score >= 40:
        return "mixed"
    return "weak_respect"


def compute_respect_score(kalman: KalmanOutput, extra_invalidations: int = 0) -> RespectScore:
    """Build the composite from a Kronos-guided Kalman run.

    extra_invalidations: invalidation events detected outside the filter
    (e.g. hourly close through the forecast's stated invalidation level),
    counted by the service layer.
    """
    observed = [
        (i, o) for i, o in enumerate(kalman.observed) if o is not None
    ]

    # 1. Direction Agreement (0-25)
    if kalman.direction_agreement is not None:
        direction = 25.0 * kalman.direction_agreement
        dir_note = (
            f"25 * blend(step={_fmt(kalman.step_agreement)}, "
            f"net={'match' if kalman.net_agreement else 'opposed' if kalman.net_agreement is not None else 'flat'})"
        )
    else:
        direction = 12.5
        dir_note = "not enough realized data — neutral 12.5"

    # 2. Path Correlation (0-25)
    xs = [kalman.forecast[i] for i, _ in observed]
    ys = [o for _, o in observed]
    r = _pearson(xs, ys)
    if r is None:
        correlation = 12.5
        corr_note = "correlation undefined (flat or <3 realized points) — neutral 12.5"
    else:
        correlation = 25.0 * (r + 1.0) / 2.0
        corr_note = f"pearson r={r:.3f} -> 25*(r+1)/2"

    # 3. Forecast Band Respect (0-20)
    if kalman.band_respect_fraction is not None:
        band = 20.0 * kalman.band_respect_fraction
        band_note = f"20 * inside-band fraction {kalman.band_respect_fraction:.2f} (|z|<=2)"
    else:
        band = 10.0
        band_note = "no realized data — neutral 10"

    # 4. Kalman Residual (0-20) — computed inside the filter
    kalman_component = kalman.respect_contribution if observed else 10.0

    # 5. Invalidation (0-10)
    invalidation_count = kalman.violation_episodes + max(0, int(extra_invalidations))
    invalidation = max(0.0, 10.0 - INVALIDATION_PENALTY * invalidation_count)

    total = round(direction + correlation + band + kalman_component + invalidation, 1)
    total = max(0.0, min(100.0, total))

    score = RespectScore(
        score=total,
        label=label_for(total),
        direction_score=round(direction, 2),
        correlation_score=round(correlation, 2),
        band_respect_score=round(band, 2),
        kalman_residual_score=round(kalman_component, 2),
        invalidation_score=round(invalidation, 2),
        invalidation_count=invalidation_count,
        forecast_status=forecast_status(total, kalman),
        explanation={
            "direction": dir_note,
            "correlation": corr_note,
            "band_respect": band_note,
            "kalman_residual": kalman.explanation.get(
                "respect_contribution_formula", "no realized data — neutral 10"
            ),
            "invalidation": (
                f"10 - {INVALIDATION_PENALTY} * {invalidation_count} episode(s), floor 0"
            ),
            "labels": "80+ highly respected | 60-79 respected/noisy | 40-59 mixed | 20-39 weak | <20 failing/inverted",
        },
    )
    return score


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2f}"

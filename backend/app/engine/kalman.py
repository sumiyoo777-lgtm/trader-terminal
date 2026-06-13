"""Kronos-Guided Kalman Filter.

This is NOT a generic Kalman smoother on price. The Kronos forecast path is
the model/prior ("intended path"); live MES price is the measurement. The
filter answers: "How much is the live market respecting the Kronos forecast
path right now?"

State-space formulation (1-D, transparent):

    The state is the DEVIATION d_t of the market from the Kronos path.
    Process model:      d_t = phi * d_{t-1} + w_t,   w_t ~ N(0, Q_t)
        phi < 1 pulls the deviation back toward zero — i.e. the prior
        believes the market returns to the Kronos path ("Kronos is the
        intended path").
    Measurement:        z_t = price_t - kronos_t  (observed deviation),
                        z_t = d_t + v_t,          v_t ~ N(0, R_t)

    R_t comes from the Kronos forecast band width (band ~ +/-2 sigma), so a
    confident (narrow-band) forecast treats deviations as more meaningful.
    The filtered estimate shown on the chart is  kronos_t + d_t|t .

Slider ("Kronos Trust / Kalman Reactivity", 0-100) maps to the Q/R ratio:

    ratio = 10 ** ((slider - 50) / 16.667)        # 0 -> 1e-3, 50 -> 1, 100 -> 1e3
    Q_t   = ratio * R_t * (1 - phi^2)

    The (1 - phi^2) factor makes the filter stationary with P = ratio * R,
    so the steady-state Kalman gain is exactly ratio / (1 + ratio):

    slider 0   : gain ~0.001 -> estimate hugs the Kronos path, very slow to
                 abandon the forecast.
    slider 50  : gain 0.5 -> balanced blend of Kronos and live price.
    slider 100 : gain ~0.999 -> estimate follows live price, fastest
                 possible failure detection.

Everything the UI shows (residuals, z-scores, tracking error, direction
agreement, failure warning, respect contribution) is computed here with the
formulas spelled out — no opaque scoring.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

PHI = 0.95  # deviation pull-back toward the Kronos path per step


@dataclass
class KalmanOutput:
    timestamps: list  # passthrough of the input timestamps (aligned)
    forecast: list[float]
    observed: list[float | None]
    estimate: list[float | None]  # kronos + filtered deviation
    residuals: list[float | None]  # observed - kronos (raw, per spec)
    residual_z: list[float | None]  # residual / forecast sigma
    gains: list[float | None]  # Kalman gain per step (for transparency)
    sigma: list[float]  # 1-sigma forecast uncertainty used per step

    slider: int = 50
    tracking_error: float | None = None  # RMSE of residuals (points)
    mean_abs_z: float | None = None
    max_abs_z: float | None = None
    direction_agreement: float | None = None  # 0..1 blended step+net agreement
    step_agreement: float | None = None  # fraction of steps moving with Kronos
    net_agreement: bool | None = None  # did net move match forecast net move
    band_respect_fraction: float | None = None  # fraction of obs inside +/-2 sigma
    max_violation_run: int = 0  # longest consecutive run of |z| > fail_z
    violation_episodes: int = 0  # distinct runs reaching fail_persistence
    failure_warning: bool = False  # persistent breach of the forecast
    inverted: bool = False  # market moving opposite to the forecast
    respect_contribution: float = 0.0  # 0-20, Kalman Residual Score component
    explanation: dict = field(default_factory=dict)


def _slider_ratio(slider: int) -> float:
    slider = max(0, min(100, int(slider)))
    return 10.0 ** ((slider - 50) / 16.667)


def _sigmas(
    forecast: list[float],
    band_upper: list[float] | None,
    band_lower: list[float] | None,
    default_sigma_pct: float,
) -> list[float]:
    """1-sigma uncertainty per step. Bands are treated as +/-2 sigma, so
    sigma = (upper - lower) / 4. Without bands, sigma defaults to
    default_sigma_pct * |forecast value| (configurable)."""
    out = []
    for i, f in enumerate(forecast):
        sigma = None
        if band_upper and band_lower and i < len(band_upper) and i < len(band_lower):
            u, l = band_upper[i], band_lower[i]
            if u is not None and l is not None and u > l:
                sigma = (u - l) / 4.0
        if sigma is None or sigma <= 0:
            sigma = max(abs(f) * default_sigma_pct, 1e-9)
        out.append(sigma)
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-12 or syy <= 1e-12:
        return None  # flat series: correlation undefined
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def kronos_guided_kalman_filter(
    forecast_path: list[float],
    observations: list[float | None],
    timestamps: list | None = None,
    band_upper: list[float] | None = None,
    band_lower: list[float] | None = None,
    slider: int = 50,
    default_sigma_pct: float = 0.0015,
    fail_z: float = 2.5,
    fail_persistence: int = 3,
) -> KalmanOutput:
    """Run the Kronos-guided Kalman filter over aligned forecast/observation
    arrays. `observations` may contain None for forecast steps not yet
    realized (the future part of the path); filtering stops there.
    """
    n = len(forecast_path)
    if n == 0:
        raise ValueError("forecast_path is empty")
    if len(observations) != n:
        raise ValueError(
            f"observations length {len(observations)} != forecast length {n} "
            "(caller must align by timestamp)"
        )
    timestamps = timestamps if timestamps is not None else list(range(n))

    sigma = _sigmas(forecast_path, band_upper, band_lower, default_sigma_pct)
    ratio = _slider_ratio(slider)

    estimate: list[float | None] = [None] * n
    residuals: list[float | None] = [None] * n
    residual_z: list[float | None] = [None] * n
    gains: list[float | None] = [None] * n

    d = 0.0  # filtered deviation from the Kronos path
    # Seed at the stationary deviation variance (ratio * R) so the gain is
    # ratio/(1+ratio) from the first observation — no warm-up spike.
    P = ratio * sigma[0] ** 2
    observed_idx: list[int] = []

    for t in range(n):
        z = observations[t]
        if z is None:
            continue
        R = sigma[t] ** 2
        Q = ratio * R * (1.0 - PHI * PHI)

        # predict
        d_pred = PHI * d
        P_pred = PHI * PHI * P + Q

        # update with the observed deviation from the Kronos path
        meas_dev = z - forecast_path[t]
        K = P_pred / (P_pred + R)
        d = d_pred + K * (meas_dev - d_pred)
        P = (1.0 - K) * P_pred

        estimate[t] = forecast_path[t] + d
        residuals[t] = meas_dev
        residual_z[t] = meas_dev / sigma[t]
        gains[t] = K
        observed_idx.append(t)

    out = KalmanOutput(
        timestamps=list(timestamps),
        forecast=list(forecast_path),
        observed=list(observations),
        estimate=estimate,
        residuals=residuals,
        residual_z=residual_z,
        gains=gains,
        sigma=sigma,
        slider=max(0, min(100, int(slider))),
    )

    if not observed_idx:
        out.explanation = {"note": "no realized observations yet — filter not run"}
        return out

    obs_res = [residuals[i] for i in observed_idx]
    obs_z = [abs(residual_z[i]) for i in observed_idx]

    out.tracking_error = math.sqrt(sum(r * r for r in obs_res) / len(obs_res))
    out.mean_abs_z = sum(obs_z) / len(obs_z)
    out.max_abs_z = max(obs_z)
    out.band_respect_fraction = sum(1 for z in obs_z if z <= 2.0) / len(obs_z)

    # --- direction agreement -------------------------------------------------
    # Per-step: do realized increments move with the forecast increments?
    # Steps where the forecast increment is ~flat (under 5% of sigma) are
    # skipped — there is no direction to agree with.
    step_hits, step_total = 0, 0
    for a, b in zip(observed_idx, observed_idx[1:]):
        df = forecast_path[b] - forecast_path[a]
        dp = observations[b] - observations[a]  # type: ignore[operator]
        if abs(df) < 0.05 * sigma[b]:
            continue
        step_total += 1
        if df * dp > 0:
            step_hits += 1
    out.step_agreement = (step_hits / step_total) if step_total else None

    first, last = observed_idx[0], observed_idx[-1]
    net_f = forecast_path[last] - forecast_path[first]
    net_p = (observations[last] or 0.0) - (observations[first] or 0.0)
    flat_floor = 0.05 * sigma[last]
    out.net_agreement = None if abs(net_f) < flat_floor else (net_f * net_p > 0)

    parts: list[float] = []
    if out.step_agreement is not None:
        parts.append(out.step_agreement)
    if out.net_agreement is not None:
        parts.append(1.0 if out.net_agreement else 0.0)
    out.direction_agreement = (sum(parts) / len(parts)) if parts else None

    # --- failure / inversion detection ---------------------------------------
    run = 0
    max_run = 0
    episodes = 0
    in_episode = False
    for i in observed_idx:
        if abs(residual_z[i]) > fail_z:  # type: ignore[arg-type]
            run += 1
            max_run = max(max_run, run)
            if run >= fail_persistence and not in_episode:
                episodes += 1
                in_episode = True
        else:
            run = 0
            in_episode = False
    out.max_violation_run = max_run
    out.violation_episodes = episodes
    out.failure_warning = max_run >= fail_persistence

    incr_f, incr_p = [], []
    for a, b in zip(observed_idx, observed_idx[1:]):
        incr_f.append(forecast_path[b] - forecast_path[a])
        incr_p.append(observations[b] - observations[a])  # type: ignore[arg-type]
    incr_corr = _pearson(incr_f, incr_p)
    out.inverted = bool(
        out.net_agreement is False
        and (
            (incr_corr is not None and incr_corr < -0.3)
            or (out.step_agreement is not None and out.step_agreement < 0.35)
        )
    )

    # --- respect contribution (Kalman Residual Score, 0-20) -------------------
    # magnitude (0-12): 12 * clip(1 - mean|z| / fail_z, 0, 1)
    # persistence (0-8): 8 * clip(1 - max_violation_run / (2*fail_persistence), 0, 1)
    mag = 12.0 * max(0.0, min(1.0, 1.0 - out.mean_abs_z / fail_z))
    pers = 8.0 * max(0.0, min(1.0, 1.0 - out.max_violation_run / (2.0 * fail_persistence)))
    out.respect_contribution = round(mag + pers, 2)

    out.explanation = {
        "state": "deviation from the Kronos path (prior pulls deviation toward 0)",
        "slider": out.slider,
        "q_over_r_ratio": round(ratio, 6),
        "phi": PHI,
        "fail_rule": f"|z| > {fail_z} for {fail_persistence}+ consecutive observations",
        "respect_contribution_formula": (
            f"magnitude 12*clip(1 - mean|z|/{fail_z}) = {round(mag, 2)} ; "
            f"persistence 8*clip(1 - max_run/{2 * fail_persistence}) = {round(pers, 2)}"
        ),
        "increment_correlation": None if incr_corr is None else round(incr_corr, 4),
        "observed_points": len(observed_idx),
    }
    return out

"""Kronos service: forecast storage (import + local runner), alignment of
live MES candles to forecast timestamps, the Kronos-guided Kalman run, and
Respect Score persistence.

If no forecast exists or local Kronos is unavailable the service degrades
loudly ("kronos_unavailable") and the rest of the terminal keeps working.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.kronos_local import (
    KronosLocalError,
    local_kronos_available,
    run_local_forecast,
)
from ..config import Settings
from ..engine.kalman import kronos_guided_kalman_filter
from ..engine.respect import compute_respect_score
from ..models import KronosForecast, KronosRespectScore, MarketPrice
from ..time_utils import from_db, iso_ny, ny_session_date, to_utc_naive, utc_now

log = logging.getLogger(__name__)

# how far a stored candle may be from a forecast timestamp and still count
ALIGN_TOLERANCE = {"hourly": timedelta(minutes=31), "daily": timedelta(hours=14)}


def store_forecast(db: Session, forecast: dict, source: str) -> KronosForecast:
    path = forecast["path"]
    row = KronosForecast(
        symbol=forecast["symbol"],
        horizon=forecast["horizon"],
        generated_at=to_utc_naive(forecast["generated_at"]),
        forecast_start=_parse_iso(path[0][0]),
        forecast_end=_parse_iso(path[-1][0]),
        path_json=path,
        direction=forecast["direction"],
        confidence=forecast.get("confidence"),
        band_upper_json=forecast.get("band_upper"),
        band_lower_json=forecast.get("band_lower"),
        model_version=forecast.get("model_version"),
        source=source,
        metadata_json=forecast.get("metadata") or {},
    )
    db.add(row)
    db.commit()
    log.info("stored %s %s forecast id=%s (%s points, source=%s)",
             row.symbol, row.horizon, row.id, len(path), source)
    return row


def latest_forecast(db: Session, symbol: str, horizon: str) -> KronosForecast | None:
    return db.scalars(
        select(KronosForecast)
        .where(KronosForecast.symbol == symbol, KronosForecast.horizon == horizon)
        .order_by(KronosForecast.generated_at.desc())
        .limit(1)
    ).first()


def run_local(db: Session, settings: Settings, horizon: str) -> dict:
    if not settings.enable_local_kronos:
        return {"ok": False, "error": "ENABLE_LOCAL_KRONOS is false"}
    try:
        forecast = run_local_forecast(
            settings.market_data_ticker,
            horizon,
            model_path=settings.kronos_model_path,
            device=settings.kronos_device,
        )
    except KronosLocalError as exc:
        log.warning("local Kronos %s run failed: %s", horizon, exc)
        return {"ok": False, "error": str(exc)}
    # the runner forecasts the data ticker (MES=F); store under the terminal symbol
    forecast["symbol"] = settings.default_symbol
    row = store_forecast(db, forecast, source="local_runner")
    return {"ok": True, "forecast_id": row.id, "direction": row.direction,
            "confidence": row.confidence}


def availability(settings: Settings) -> dict:
    available, reason = local_kronos_available(settings.kronos_model_path)
    return {
        "local_runner_enabled": settings.enable_local_kronos,
        "local_runner_available": available,
        "reason": reason,
        "manual_import_available": True,
    }


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _align_observations(
    db: Session, symbol: str, path: list[list], horizon: str
) -> list[float | None]:
    """For each forecast timestamp, the close of the nearest stored candle
    within tolerance; None when not yet realized / no data."""
    if not path:
        return []
    tolerance = ALIGN_TOLERANCE.get(horizon, ALIGN_TOLERANCE["hourly"])
    start = _parse_iso(path[0][0]) - tolerance
    end = _parse_iso(path[-1][0]) + tolerance
    candles = list(
        db.scalars(
            select(MarketPrice)
            .where(
                MarketPrice.symbol == symbol,
                MarketPrice.timestamp >= start,
                MarketPrice.timestamp <= end,
            )
            .order_by(MarketPrice.timestamp.asc())
        )
    )
    now_naive = utc_now().replace(tzinfo=None)
    out: list[float | None] = []
    for iso_ts, _ in path:
        target = _parse_iso(iso_ts)
        if target > now_naive:
            out.append(None)  # future — not yet realized
            continue
        best = None
        best_dt = tolerance
        for c in candles:
            delta = abs(c.timestamp - target)
            if delta <= best_dt:
                best, best_dt = c, delta
        out.append(best.close if best else None)
    return out


def compute_respect_view(
    db: Session,
    settings: Settings,
    slider: int | None = None,
    horizon: str = "hourly",
    persist: bool = True,
    live_price: float | None = None,
) -> dict:
    """The Kronos panel payload: paths, bands, Kalman estimate, residuals,
    sub-scores, deviation, forecast status."""
    slider = settings.kalman_slider_default if slider is None else int(slider)
    symbol = settings.default_symbol
    forecast = latest_forecast(db, symbol, horizon)
    if forecast is None:
        return {
            "status": "kronos_unavailable",
            "horizon": horizon,
            "message": f"No {horizon} Kronos forecast stored. Import one or enable the local runner.",
            "availability": availability(settings),
        }

    path = forecast.path_json or []
    timestamps = [p[0] for p in path]
    values = [float(p[1]) for p in path]
    upper = [float(p[1]) for p in (forecast.band_upper_json or [])] or None
    lower = [float(p[1]) for p in (forecast.band_lower_json or [])] or None

    observations = _align_observations(db, symbol, path, horizon)

    # If we have a live tick newer than the last aligned candle, use it for
    # the most recent already-due forecast step so the panel reacts intraday.
    # Guards: never mix a real live price into a DEMO forecast, and reject
    # ticks more than 10% off the forecast scale (wrong ticker / bad data —
    # a real intraday MES move can't be 10%, that's beyond circuit breakers).
    if live_price is not None and forecast.source != "demo":
        now_naive = utc_now().replace(tzinfo=None)
        due = [i for i, ts in enumerate(timestamps) if _parse_iso(ts) <= now_naive]
        if due and observations[due[-1]] is None:
            ref = values[due[-1]]
            if ref and abs(float(live_price) - ref) / abs(ref) <= 0.10:
                observations[due[-1]] = float(live_price)
            else:
                log.warning(
                    "live price %.2f is >10%% from forecast scale %.2f — not injected "
                    "(wrong ticker or bad data?)", live_price, ref,
                )

    kalman = kronos_guided_kalman_filter(
        forecast_path=values,
        observations=observations,
        timestamps=timestamps,
        band_upper=upper,
        band_lower=lower,
        slider=slider,
        default_sigma_pct=settings.kalman_default_sigma_pct,
        fail_z=settings.kalman_fail_z,
        fail_persistence=settings.kalman_fail_persistence,
    )
    respect = compute_respect_score(kalman)

    observed_idx = [i for i, o in enumerate(observations) if o is not None]
    deviation_pts = deviation_pct = None
    if observed_idx:
        i = observed_idx[-1]
        deviation_pts = round(observations[i] - values[i], 2)
        deviation_pct = round(deviation_pts / values[i] * 100.0, 3)

    if persist and observed_idx:
        db.add(
            KronosRespectScore(
                symbol=symbol,
                session_date=ny_session_date(),
                timestamp=to_utc_naive(utc_now()),
                score=respect.score,
                direction_score=respect.direction_score,
                correlation_score=respect.correlation_score,
                band_respect_score=respect.band_respect_score,
                kalman_residual_score=respect.kalman_residual_score,
                invalidation_score=respect.invalidation_score,
                invalidation_count=respect.invalidation_count,
                metadata_json={"horizon": horizon, "slider": slider,
                               "forecast_id": forecast.id},
            )
        )
        db.commit()

    return {
        "status": "ok",
        "horizon": horizon,
        "forecast": {
            "id": forecast.id,
            "symbol": forecast.symbol,
            "direction": forecast.direction,
            "confidence": forecast.confidence,
            "generated_at_ny": iso_ny(from_db(forecast.generated_at)),
            "forecast_start_ny": iso_ny(from_db(forecast.forecast_start)),
            "forecast_end_ny": iso_ny(from_db(forecast.forecast_end)),
            "model_version": forecast.model_version,
            "source": forecast.source,
            "band_width_avg": (
                round(sum(u - l for u, l in zip(upper, lower)) / len(upper), 2)
                if upper and lower else None
            ),
            "metadata": forecast.metadata_json,
        },
        "series": {
            "timestamps": timestamps,
            "kronos_path": values,
            "band_upper": upper,
            "band_lower": lower,
            "observed": observations,
            "kalman_estimate": kalman.estimate,
            "residuals": kalman.residuals,
            "residual_z": kalman.residual_z,
        },
        "kalman": {
            "slider": kalman.slider,
            "slider_label": "Kronos Trust / Kalman Reactivity",
            "tracking_error": kalman.tracking_error,
            "mean_abs_z": kalman.mean_abs_z,
            "max_abs_z": kalman.max_abs_z,
            "direction_agreement": kalman.direction_agreement,
            "band_respect_fraction": kalman.band_respect_fraction,
            "failure_warning": kalman.failure_warning,
            "inverted": kalman.inverted,
            "explanation": kalman.explanation,
        },
        "respect": {
            "score": respect.score,
            "label": respect.label,
            "forecast_status": respect.forecast_status,
            "direction_score": respect.direction_score,
            "correlation_score": respect.correlation_score,
            "band_respect_score": respect.band_respect_score,
            "kalman_residual_score": respect.kalman_residual_score,
            "invalidation_score": respect.invalidation_score,
            "invalidation_count": respect.invalidation_count,
            "explanation": respect.explanation,
        },
        "deviation": {"points": deviation_pts, "percent": deviation_pct},
    }


def forecast_history(db: Session, settings: Settings, limit: int = 20) -> list[dict]:
    rows = db.scalars(
        select(KronosForecast)
        .where(KronosForecast.symbol == settings.default_symbol)
        .order_by(KronosForecast.generated_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id, "horizon": r.horizon, "direction": r.direction,
            "confidence": r.confidence, "source": r.source,
            "generated_at_ny": iso_ny(from_db(r.generated_at)),
            "forecast_start_ny": iso_ny(from_db(r.forecast_start)),
            "forecast_end_ny": iso_ny(from_db(r.forecast_end)),
            "points": len(r.path_json or []),
            "model_version": r.model_version,
        }
        for r in rows
    ]

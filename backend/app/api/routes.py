"""All /api/trader-terminal routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.kronos_import import KronosImportError, parse_forecast_csv, parse_forecast_json
from ..config import Settings, get_settings
from ..db import get_db
from ..models import NewsRiskScore
from ..services import (
    cot_service,
    gex_service,
    kronos_service,
    news_service,
    price_service,
    regime_service,
)
from ..time_utils import iso_ny, ny_session_date, session_status, utc_now

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trader-terminal", tags=["trader-terminal"])


# ---------------------------------------------------------------- summary
@router.get("/summary")
def summary(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    price = price_service.latest_price(db, settings)
    regime = regime_service.get_regime_view(db, settings, history_limit=1)
    kronos_avail = kronos_service.availability(settings)
    hourly = kronos_service.latest_forecast(db, settings.default_symbol, "hourly")
    daily = kronos_service.latest_forecast(db, settings.default_symbol, "daily")
    gex = gex_service.get_gex_view(db, settings, trading_price=price.get("price"))
    cot = cot_service.get_cot_view(db, settings)
    news_row = db.scalars(
        select(NewsRiskScore).order_by(NewsRiskScore.timestamp.desc()).limit(1)
    ).first()

    current = regime.get("current") or {}
    return {
        "symbol": settings.default_symbol,
        "proxy_symbols": [settings.gex_primary_symbol, settings.gex_secondary_symbol],
        "session_date": ny_session_date().isoformat(),
        "session_status": session_status(),
        "now_ny": iso_ny(utc_now()),
        "last_price": price,
        "scores": {
            "bias": current.get("bias"),
            "environment": current.get("environment"),
            "confidence": current.get("confidence"),
            "kronos_respect": current.get("kronos_score"),
            "kronos_hourly_direction": hourly.direction if hourly else None,
            "kronos_daily_direction": daily.direction if daily else None,
            "gex_regime": ((gex.get("latest") or {}).get("regime") or {}).get("regime", "unknown"),
            "gex_score": ((gex.get("latest") or {}).get("regime") or {}).get("score"),
            "cot_score": (cot.get("headline") or {}).get("score"),
            "cot_label": (cot.get("headline") or {}).get("label"),
            "news_score": news_row.score if news_row else None,
            "red_folder": bool(news_row.red_folder_flag) if news_row else False,
        },
        "data_health": {
            "price": {"ok": price.get("price") is not None, "source": price.get("source"),
                      "age_seconds": price.get("age_seconds")},
            "kronos": {"ok": hourly is not None,
                       "hourly_generated_ny": iso_ny(hourly.generated_at.replace(tzinfo=None)) if hourly else None,
                       "daily_generated_ny": iso_ny(daily.generated_at.replace(tzinfo=None)) if daily else None,
                       **kronos_avail},
            "gex": {"ok": gex.get("latest") is not None, "is_stale": gex.get("is_stale"),
                    "age_minutes": gex.get("age_minutes"), "error": gex.get("latest_error")},
            "cot": {"ok": cot.get("report_date") is not None, **(cot.get("staleness") or {})},
            "news": {"ok": news_row is not None,
                     "last_scored_ny": iso_ny(news_row.timestamp.replace(tzinfo=None)) if news_row else None},
        },
    }


# ---------------------------------------------------------------- kronos
@router.get("/kronos")
def kronos(
    slider: int | None = Query(default=None, ge=0, le=100),
    horizon: str = Query(default="hourly", pattern="^(hourly|daily)$"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    price = price_service.latest_price(db, settings)
    view = kronos_service.compute_respect_view(
        db, settings, slider=slider, horizon=horizon, persist=False,
        live_price=price.get("price"),
    )
    view["daily_direction"] = None
    daily = kronos_service.latest_forecast(db, settings.default_symbol, "daily")
    if daily:
        view["daily_direction"] = daily.direction
    view["availability"] = kronos_service.availability(settings)
    view["history"] = kronos_service.forecast_history(db, settings)
    view["live_price"] = price
    return view


@router.post("/kronos/import")
def kronos_import(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Accepts {"format":"csv","csv":...,"horizon":...,...} or a forecast
    JSON object (optionally wrapped as {"format":"json","data":{...}})."""
    try:
        if body.get("format") == "csv":
            forecast = parse_forecast_csv(
                body.get("csv", ""),
                horizon=body.get("horizon", "hourly"),
                symbol=body.get("symbol", settings.default_symbol),
                confidence=body.get("confidence"),
                model_version=body.get("model_version"),
            )
        else:
            payload = body.get("data") if isinstance(body.get("data"), dict) else body
            forecast = parse_forecast_json(payload, default_symbol=settings.default_symbol)
    except KronosImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    row = kronos_service.store_forecast(db, forecast, source="import")
    regime_service.recalculate_regime(db, settings)
    return {"ok": True, "forecast_id": row.id, "horizon": row.horizon,
            "direction": row.direction, "points": len(row.path_json or [])}


@router.post("/kronos/run")
def kronos_run(
    horizon: str = Query(default="hourly", pattern="^(hourly|daily)$"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Trigger a local Kronos run (Mode B). Slow on CPU — minutes, not ms."""
    result = kronos_service.run_local(db, settings, horizon)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error"))
    regime_service.recalculate_regime(db, settings)
    return result


@router.get("/kronos/respect")
def kronos_respect(
    slider: int | None = Query(default=None, ge=0, le=100),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    price = price_service.latest_price(db, settings)
    view = kronos_service.compute_respect_view(
        db, settings, slider=slider, horizon="hourly", persist=False,
        live_price=price.get("price"),
    )
    if view.get("status") != "ok":
        return view
    return {"status": "ok", "respect": view["respect"], "kalman": view["kalman"],
            "deviation": view["deviation"]}


# ---------------------------------------------------------------- gex
@router.get("/gex")
def gex(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    price = price_service.latest_price(db, settings)
    return gex_service.get_gex_view(db, settings, trading_price=price.get("price"))


@router.post("/gex/refresh")
def gex_refresh(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    price = price_service.latest_price(db, settings)
    result = gex_service.refresh_gex(db, settings, trading_price=price.get("price"), trigger="manual")
    regime_service.recalculate_regime(db, settings)
    return result


# ---------------------------------------------------------------- cot
@router.get("/cot")
def cot(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return cot_service.get_cot_view(db, settings)


@router.post("/cot/refresh")
def cot_refresh(
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    result = cot_service.refresh_cot(db, settings, force=force)
    regime_service.recalculate_regime(db, settings)
    return result


# ---------------------------------------------------------------- news
@router.get("/news")
def news(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return news_service.get_news_view(db, settings)


@router.post("/news/refresh")
def news_refresh(
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    result = news_service.refresh_news(db, settings, force=force)
    regime_service.recalculate_regime(db, settings)
    return result


# ---------------------------------------------------------------- regime / alerts / prices
@router.get("/regime")
def regime(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return regime_service.get_regime_view(db, settings)


@router.post("/regime/recalculate")
def regime_recalculate(
    slider: int | None = Query(default=None, ge=0, le=100),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return regime_service.recalculate_regime(db, settings, slider=slider)


@router.get("/alerts")
def alerts(
    include_acknowledged: bool = Query(default=False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return {"alerts": regime_service.get_alerts(db, settings, include_acknowledged)}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: int, db: Session = Depends(get_db)):
    if not regime_service.acknowledge_alert(db, alert_id):
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    return {"ok": True, "alert_id": alert_id}


@router.get("/prices")
def prices(
    hours_back: int = Query(default=30, ge=1, le=240),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return {
        "symbol": settings.default_symbol,
        "candles": price_service.session_price_path(db, settings, hours_back),
        "live": price_service.latest_price(db, settings),
    }


@router.post("/prices/refresh")
def prices_refresh(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return price_service.refresh_prices(db, settings)

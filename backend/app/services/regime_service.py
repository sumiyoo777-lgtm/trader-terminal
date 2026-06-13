"""Regime orchestration: gather inputs from every pillar, run the unified
regime engine, persist the snapshot, diff against the previous state and
persist/log any triggered alerts.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..engine.alerts import TerminalState, check_alert_conditions
from ..engine.regime import RegimeInputs, evaluate_regime
from ..models import Alert, CotExposureScore, NewsRiskScore, TerminalRegimeSnapshot
from ..time_utils import from_db, iso_ny, to_utc_naive, utc_now
from . import gex_service, kronos_service, price_service

log = logging.getLogger(__name__)


def recalculate_regime(db: Session, settings: Settings, slider: int | None = None) -> dict:
    """The terminal_regime_job body — also called after manual refreshes."""
    symbol = settings.default_symbol

    price_info = price_service.latest_price(db, settings)
    price = price_info.get("price")

    kronos = kronos_service.compute_respect_view(
        db, settings, slider=slider, horizon="hourly", persist=True, live_price=price
    )
    daily_forecast = kronos_service.latest_forecast(db, symbol, "daily")

    gex = gex_service.get_gex_view(db, settings, trading_price=price)
    latest_gex = gex.get("latest")
    gex_regime_info = (latest_gex or {}).get("regime") or {}
    converted = (latest_gex or {}).get("converted_to_trading_symbol") or {}

    cot_row = db.scalars(
        select(CotExposureScore).order_by(CotExposureScore.report_date.desc()).limit(1)
    ).first()
    news_row = db.scalars(
        select(NewsRiskScore).order_by(NewsRiskScore.timestamp.desc()).limit(1)
    ).first()

    kronos_ok = kronos.get("status") == "ok"
    respect = kronos.get("respect", {}) if kronos_ok else {}
    kalman = kronos.get("kalman", {}) if kronos_ok else {}

    inputs = RegimeInputs(
        kronos_hourly_direction=(kronos.get("forecast", {}) or {}).get("direction") if kronos_ok else None,
        kronos_daily_direction=daily_forecast.direction if daily_forecast else None,
        kronos_respect_score=respect.get("score"),
        kronos_confidence=(kronos.get("forecast", {}) or {}).get("confidence") if kronos_ok else None,
        forecast_failing=bool(kalman.get("failure_warning")),
        forecast_inverted=bool(kalman.get("inverted")),
        gex_regime=gex_regime_info.get("regime", "unknown"),
        gex_score=gex_regime_info.get("score"),
        distance_to_flip_pct=gex_regime_info.get("distance_to_flip_pct"),
        distance_to_call_wall=gex_regime_info.get("distance_to_call_wall"),
        distance_to_put_wall=gex_regime_info.get("distance_to_put_wall"),
        cot_score=cot_row.score if cot_row else None,
        news_score=news_row.score if news_row else None,
        red_folder=bool(news_row.red_folder_flag) if news_row else False,
    )
    decision = evaluate_regime(inputs)

    new_state = TerminalState(
        price=price,
        gamma_flip=converted.get("gamma_flip"),
        call_wall=converted.get("call_wall"),
        put_wall=converted.get("put_wall"),
        gex_regime=inputs.gex_regime,
        respect_score=inputs.kronos_respect_score,
        forecast_failing=inputs.forecast_failing,
        forecast_inverted=inputs.forecast_inverted,
        news_score=inputs.news_score,
        red_folder=inputs.red_folder,
        bias=decision.bias,
        environment=decision.environment,
    )

    prev_snapshot = db.scalars(
        select(TerminalRegimeSnapshot)
        .where(TerminalRegimeSnapshot.symbol == symbol)
        .order_by(TerminalRegimeSnapshot.timestamp.desc())
        .limit(1)
    ).first()
    prev_state = None
    if prev_snapshot and isinstance(prev_snapshot.raw_json, dict):
        stored = prev_snapshot.raw_json.get("state") or {}
        prev_state = TerminalState(**{k: stored.get(k) for k in TerminalState.__dataclass_fields__})

    snapshot = TerminalRegimeSnapshot(
        timestamp=to_utc_naive(utc_now()),
        symbol=symbol,
        bias=decision.bias,
        environment=decision.environment,
        confidence=decision.confidence,
        kronos_score=inputs.kronos_respect_score,
        gex_score=inputs.gex_score,
        cot_score=inputs.cot_score,
        news_score=inputs.news_score,
        reasons_json=decision.reasons,
        invalidations_json=decision.invalidations,
        raw_json={
            "playbook": decision.playbook,
            "what_would_change_my_mind": decision.what_would_change_my_mind,
            "confidence_terms": decision.confidence_terms,
            "state": new_state.__dict__,
            "price_info": price_info,
        },
    )
    db.add(snapshot)

    events = check_alert_conditions(
        prev_state, new_state, wall_approach_pct=settings.gex_wall_approach_pct
    )
    for e in events:
        db.add(Alert(
            timestamp=to_utc_naive(utc_now()), symbol=symbol,
            alert_type=e.alert_type, severity=e.severity,
            title=e.title, message=e.message, metadata_json=e.metadata,
        ))
        log.warning("[ALERT %s] %s — %s", e.severity.upper(), e.title, e.message)
    db.commit()

    return snapshot_to_dict(snapshot) | {"new_alerts": len(events)}


def snapshot_to_dict(s: TerminalRegimeSnapshot) -> dict:
    raw = s.raw_json or {}
    return {
        "id": s.id,
        "timestamp_ny": iso_ny(from_db(s.timestamp)),
        "symbol": s.symbol,
        "bias": s.bias,
        "environment": s.environment,
        "confidence": s.confidence,
        "kronos_score": s.kronos_score,
        "gex_score": s.gex_score,
        "cot_score": s.cot_score,
        "news_score": s.news_score,
        "playbook": raw.get("playbook"),
        "reasons": s.reasons_json or [],
        "invalidations": s.invalidations_json or [],
        "what_would_change_my_mind": raw.get("what_would_change_my_mind") or [],
        "confidence_terms": raw.get("confidence_terms") or [],
    }


def get_regime_view(db: Session, settings: Settings, history_limit: int = 30) -> dict:
    rows = db.scalars(
        select(TerminalRegimeSnapshot)
        .where(TerminalRegimeSnapshot.symbol == settings.default_symbol)
        .order_by(TerminalRegimeSnapshot.timestamp.desc())
        .limit(history_limit)
    ).all()
    return {
        "current": snapshot_to_dict(rows[0]) if rows else None,
        "history": [snapshot_to_dict(r) for r in rows[1:]],
    }


def get_alerts(db: Session, settings: Settings, include_acknowledged: bool = False, limit: int = 50) -> list[dict]:
    q = select(Alert).where(Alert.symbol == settings.default_symbol)
    if not include_acknowledged:
        q = q.where(Alert.acknowledged.is_(False))
    rows = db.scalars(q.order_by(Alert.timestamp.desc()).limit(limit)).all()
    return [
        {
            "id": a.id, "timestamp_ny": iso_ny(from_db(a.timestamp)),
            "alert_type": a.alert_type, "severity": a.severity,
            "title": a.title, "message": a.message,
            "metadata": a.metadata_json, "acknowledged": a.acknowledged,
        }
        for a in rows
    ]


def acknowledge_alert(db: Session, alert_id: int) -> bool:
    alert = db.get(Alert, alert_id)
    if alert is None:
        return False
    alert.acknowledged = True
    db.commit()
    return True

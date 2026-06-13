"""GEX service: fetch (SPX -> SPY fallback), persist snapshots, classify the
regime, convert proxy levels onto the MES scale (clearly labeled
APPROXIMATE), and assemble the panel view with day-trend context.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.flashalpha import FetchResult, fetch_gex_with_fallback, parse_gex_payload
from ..adapters.selfcomputed_gex import fetch_self_computed_gex
from ..config import Settings
from ..engine.gex_regime import classify_gex_regime, conversion_factor, convert_level
from ..models import GexSnapshot
from ..time_utils import iso_ny, iso_utc, ny_session_date, to_utc_naive, utc_now

log = logging.getLogger(__name__)

CONVERSION_DISCLAIMER = (
    "Converted levels are APPROXIMATE. SPX/SPY options structure does not map "
    "exactly onto MES futures (basis, dividends, expiry mix). Use as zones, "
    "not exact ticks."
)


def refresh_gex(
    db: Session,
    settings: Settings,
    trading_price: float | None = None,
    trigger: str = "manual",
) -> dict:
    """Fetch one GEX snapshot now and persist it (success OR failure — failed
    snapshots are stored with status/error so the UI can show exactly what
    happened instead of silently reusing stale data)."""
    symbols = [settings.gex_primary_symbol, settings.gex_secondary_symbol]
    symbols = [s for s in symbols if s]
    used, result, notes = fetch_gex_with_fallback(
        symbols, settings.flashalpha_api_key, settings.flashalpha_base_url
    )
    self_computed = False

    now = utc_now()
    if (not result.ok or used is None) and settings.enable_self_computed_gex:
        # FlashAlpha unusable (free tier / quota / outage) -> self-computed
        # approximation from the live option chain, clearly labeled.
        notes.append(f"flashalpha unusable ({result.kind}) -> self-computed fallback")
        sc_used, sc_payload, sc_notes = fetch_self_computed_gex()
        notes.extend(sc_notes)
        if sc_payload is not None:
            used = sc_used
            result = FetchResult(True, "ok", "self-computed", None, sc_payload)
            self_computed = True

    if not result.ok or used is None:
        snap = GexSnapshot(
            symbol=symbols[0] if symbols else "?",
            proxy_for=settings.default_symbol,
            timestamp=to_utc_naive(now),
            status="error",
            error_message=f"{result.kind}: {result.message}",
            raw_json={"attempts": notes, "trigger": trigger},
        )
        db.add(snap)
        db.commit()
        log.warning("GEX refresh failed: %s (%s)", result.kind, result.message)
        return {"ok": False, "kind": result.kind, "message": result.message, "attempts": notes}

    parsed = parse_gex_payload(result.payload or {})
    status = "ok"
    if self_computed:
        status = "self_computed"
    elif parsed.single_expiry:
        status = "single_expiry"
    elif parsed.partial:
        status = "partial"

    snap = GexSnapshot(
        symbol=used,
        proxy_for=settings.default_symbol,
        timestamp=to_utc_naive(now),
        underlying_price=parsed.underlying_price,
        net_gex=parsed.net_gex,
        net_gex_label=parsed.net_gex_label
        or (None if parsed.net_gex is None else ("positive" if parsed.net_gex >= 0 else "negative")),
        gamma_flip=parsed.gamma_flip,
        call_wall=parsed.call_wall,
        put_wall=parsed.put_wall,
        largest_positive_gex_strike=parsed.largest_positive_gex_strike,
        largest_negative_gex_strike=parsed.largest_negative_gex_strike,
        status=status,
        error_message=None if not parsed.missing_fields else f"missing: {', '.join(parsed.missing_fields)}",
        raw_json={
            "payload": result.payload,
            "attempts": notes,
            "trigger": trigger,
            "trading_price_at_fetch": trading_price,
        },
    )
    db.add(snap)
    db.commit()
    log.info("GEX snapshot stored: %s status=%s net_gex=%s", used, status, parsed.net_gex)
    return {"ok": True, "symbol": used, "status": status, "snapshot_id": snap.id}


def _snapshot_to_dict(snap: GexSnapshot, settings: Settings, trading_price: float | None) -> dict:
    regime = classify_gex_regime(
        net_gex=snap.net_gex,
        spot=snap.underlying_price,
        gamma_flip=snap.gamma_flip,
        call_wall=snap.call_wall,
        put_wall=snap.put_wall,
        near_flip_pct=settings.gex_near_flip_pct,
    )

    factor, method = conversion_factor(snap.symbol, snap.underlying_price, trading_price)
    converted = {
        "gamma_flip": convert_level(snap.gamma_flip, factor),
        "call_wall": convert_level(snap.call_wall, factor),
        "put_wall": convert_level(snap.put_wall, factor),
        "largest_positive_gex_strike": convert_level(snap.largest_positive_gex_strike, factor),
        "largest_negative_gex_strike": convert_level(snap.largest_negative_gex_strike, factor),
        "method": method,
        "factor": round(factor, 6),
        "approximate": True,
        "disclaimer": CONVERSION_DISCLAIMER,
    }

    return {
        "id": snap.id,
        "timestamp_utc": iso_utc(snap.timestamp.replace(tzinfo=None)) if snap.timestamp else None,
        "timestamp_ny": iso_ny(snap.timestamp) if snap.timestamp else None,
        "symbol": snap.symbol,
        "proxy_for": snap.proxy_for,
        "underlying_price": snap.underlying_price,
        "net_gex": snap.net_gex,
        "net_gex_label": snap.net_gex_label,
        "gamma_flip": snap.gamma_flip,
        "call_wall": snap.call_wall,
        "put_wall": snap.put_wall,
        "largest_positive_gex_strike": snap.largest_positive_gex_strike,
        "largest_negative_gex_strike": snap.largest_negative_gex_strike,
        "status": snap.status,
        "error_message": snap.error_message,
        "regime": asdict(regime),
        "converted_to_trading_symbol": converted,
    }


def get_gex_view(db: Session, settings: Settings, trading_price: float | None = None) -> dict:
    """Latest usable snapshot + all of today's snapshots + intraday trend."""
    latest_ok = db.scalars(
        select(GexSnapshot)
        .where(GexSnapshot.status != "error")
        .order_by(GexSnapshot.timestamp.desc())
        .limit(1)
    ).first()
    latest_any = db.scalars(
        select(GexSnapshot).order_by(GexSnapshot.timestamp.desc()).limit(1)
    ).first()

    session_date = ny_session_date()
    day_start = datetime(session_date.year, session_date.month, session_date.day) - timedelta(hours=5)
    todays = list(
        db.scalars(
            select(GexSnapshot)
            .where(GexSnapshot.timestamp >= day_start, GexSnapshot.status != "error")
            .order_by(GexSnapshot.timestamp.asc())
        )
    )

    snapshots = [_snapshot_to_dict(s, settings, trading_price) for s in todays]
    for prev, cur in zip(snapshots, snapshots[1:]):
        if cur["net_gex"] is not None and prev["net_gex"] is not None:
            cur["net_gex_change"] = round(cur["net_gex"] - prev["net_gex"], 4)
        if cur["gamma_flip"] is not None and prev["gamma_flip"] is not None:
            cur["gamma_flip_change"] = round(cur["gamma_flip"] - prev["gamma_flip"], 2)

    trend = None
    nets = [s["net_gex"] for s in snapshots if s["net_gex"] is not None]
    if len(nets) >= 2:
        delta = nets[-1] - nets[0]
        # threshold: 5% of the day's max |net gex| counts as a real change
        floor = 0.05 * max(abs(n) for n in nets)
        trend = "rising" if delta > floor else ("falling" if delta < -floor else "flat")

    age_minutes = None
    is_stale = None
    if latest_ok and latest_ok.timestamp:
        age_minutes = round((utc_now().replace(tzinfo=None) - latest_ok.timestamp).total_seconds() / 60.0, 1)
        is_stale = age_minutes > settings.gex_stale_minutes

    return {
        "latest": _snapshot_to_dict(latest_ok, settings, trading_price) if latest_ok else None,
        "latest_error": (
            {"status": latest_any.status, "error_message": latest_any.error_message,
             "timestamp_ny": iso_ny(latest_any.timestamp)}
            if latest_any is not None and latest_any.status == "error" else None
        ),
        "todays_snapshots": snapshots,
        "day_trend": trend,
        "schedule_ny": settings.gex_schedule_list,
        "age_minutes": age_minutes,
        "is_stale": is_stale,
        "stale_threshold_minutes": settings.gex_stale_minutes,
    }

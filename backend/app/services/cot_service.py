"""COT service: pull CFTC legacy + TFF reports for the configured S&P 500
E-mini proxy, upsert raw rows, compute the exposure score, and assemble the
panel view (raw values + normalized scores + staleness, per spec).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.cftc_cot import CotRow, fetch_dataset, normalize_rows
from ..config import Settings
from ..engine.cot_score import (
    compute_cot_metrics,
    expected_latest_as_of,
    staleness,
)
from ..models import CotExposureScore, CotReport
from ..time_utils import iso_ny, utc_now

log = logging.getLogger(__name__)

PRIMARY_GROUP = "non_commercial"  # legacy speculators drive the headline score


def _upsert_rows(db: Session, rows: list[CotRow]) -> int:
    inserted = 0
    for r in rows:
        exists = db.scalars(
            select(CotReport.id).where(
                CotReport.report_type == r.report_type,
                CotReport.market_code == r.market_code,
                CotReport.report_date == r.report_date,
                CotReport.participant_group == r.participant_group,
            )
        ).first()
        if exists:
            continue
        db.add(
            CotReport(
                report_type=r.report_type,
                market_name=r.market_name,
                market_code=r.market_code,
                report_date=r.report_date,
                as_of_date=r.as_of_date,
                participant_group=r.participant_group,
                long_positions=r.long_positions,
                short_positions=r.short_positions,
                spreading=r.spreading,
                open_interest=r.open_interest,
                raw_json=r.raw,
            )
        )
        inserted += 1
    db.commit()
    return inserted


def refresh_cot(db: Session, settings: Settings, force: bool = False) -> dict:
    """Daily job / manual refresh. Skips the network call when the newest
    expected report is already stored (unless force)."""
    latest_stored = db.scalars(
        select(CotReport.report_date).order_by(CotReport.report_date.desc()).limit(1)
    ).first()
    expected = expected_latest_as_of()
    if not force and latest_stored is not None and latest_stored >= expected:
        return {
            "ok": True, "skipped": True,
            "reason": f"newest expected report ({expected.isoformat()}) already stored",
        }

    results = {}
    errors = []
    for report_type, dataset in (
        ("legacy", settings.cot_legacy_dataset),
        ("tff", settings.cot_tff_dataset),
    ):
        raw, err = fetch_dataset(
            dataset,
            settings.cot_market_code_list,
            settings.cot_market_name_like,
            weeks=settings.cot_lookback_weeks + 4,
        )
        if err:
            errors.append(f"{report_type}: {err}")
            log.warning("COT fetch failed (%s): %s", report_type, err)
            continue
        rows = normalize_rows(raw, report_type)
        results[report_type] = _upsert_rows(db, rows)

    score_info = _recompute_score(db, settings)
    return {
        "ok": not errors or bool(results),
        "inserted": results,
        "errors": errors,
        "score": score_info,
    }


def _group_reports(db: Session, report_type: str, group: str) -> list[dict]:
    rows = db.scalars(
        select(CotReport)
        .where(CotReport.report_type == report_type, CotReport.participant_group == group)
        .order_by(CotReport.report_date.asc())
    ).all()
    return [
        {
            "report_date": r.report_date,
            "long_positions": r.long_positions,
            "short_positions": r.short_positions,
        }
        for r in rows
    ]


def _recompute_score(db: Session, settings: Settings) -> dict | None:
    reports = _group_reports(db, "legacy", PRIMARY_GROUP)
    metrics = compute_cot_metrics(PRIMARY_GROUP, reports, settings.cot_lookback_weeks)
    if metrics.score is None or metrics.report_date is None:
        return None

    exists = db.scalars(
        select(CotExposureScore.id).where(CotExposureScore.report_date == metrics.report_date)
    ).first()
    if not exists:
        market_name = db.scalars(
            select(CotReport.market_name).where(CotReport.report_type == "legacy").limit(1)
        ).first() or settings.cot_market_name_like
        db.add(
            CotExposureScore(
                market_name=market_name,
                report_date=metrics.report_date,
                score=metrics.score,
                net_position=metrics.net_position,
                net_percentile=metrics.net_percentile,
                four_week_change=metrics.four_week_change,
                thirteen_week_change=metrics.thirteen_week_change,
                crowding_score=metrics.crowding_score,
                metadata_json={"group": PRIMARY_GROUP, **metrics.explanation},
            )
        )
        db.commit()
    return {"report_date": metrics.report_date.isoformat(), "score": metrics.score}


ALL_GROUPS = [
    ("legacy", "non_commercial"),
    ("legacy", "commercial"),
    ("tff", "dealer_intermediary"),
    ("tff", "asset_manager"),
    ("tff", "leveraged_funds"),
]


def get_cot_view(db: Session, settings: Settings) -> dict:
    """Panel payload: per-group raw + normalized metrics, headline score,
    staleness, report/as-of dates."""
    groups = []
    headline = None
    for report_type, group in ALL_GROUPS:
        reports = _group_reports(db, report_type, group)
        m = compute_cot_metrics(group, reports, settings.cot_lookback_weeks)
        latest = reports[-1] if reports else None
        entry = {
            "report_type": report_type,
            "group": group,
            "report_date": m.report_date.isoformat() if m.report_date else None,
            "long_positions": latest["long_positions"] if latest else None,
            "short_positions": latest["short_positions"] if latest else None,
            "net_position": m.net_position,
            "net_percentile": m.net_percentile,
            "four_week_change": m.four_week_change,
            "thirteen_week_change": m.thirteen_week_change,
            "crowding_score": m.crowding_score,
            "score": m.score,
            "label": m.label,
            "explanation": m.explanation,
        }
        groups.append(entry)
        if group == PRIMARY_GROUP:
            headline = entry

    latest_report = db.scalars(
        select(CotReport).order_by(CotReport.report_date.desc()).limit(1)
    ).first()
    stale = staleness(latest_report.report_date if latest_report else None)

    history = db.scalars(
        select(CotExposureScore).order_by(CotExposureScore.report_date.desc()).limit(26)
    ).all()

    return {
        "market": latest_report.market_name if latest_report else None,
        "market_code": latest_report.market_code if latest_report else None,
        "proxy_note": (
            f"{settings.default_symbol} positioning proxied by E-mini S&P 500 COT "
            "(weekly macro positioning input — NOT intraday timing)"
        ),
        "report_date": latest_report.report_date.isoformat() if latest_report else None,
        "as_of_date": latest_report.as_of_date.isoformat() if latest_report else None,
        "staleness": stale,
        "headline": headline,
        "groups": groups,
        "score_history": [
            {
                "report_date": h.report_date.isoformat(),
                "score": h.score,
                "net_position": h.net_position,
                "net_percentile": h.net_percentile,
                "four_week_change": h.four_week_change,
                "thirteen_week_change": h.thirteen_week_change,
                "crowding_score": h.crowding_score,
            }
            for h in history
        ],
        "last_checked_ny": iso_ny(utc_now()),
    }

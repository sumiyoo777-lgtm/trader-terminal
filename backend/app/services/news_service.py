"""News service: fetch via the configured provider (cache/rate-limit
protected), score each headline with the transparent lexicon model, persist
items + the aggregate Live News Risk Score.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.news_providers import build_provider
from ..config import Settings
from ..engine.news_score import aggregate_news_risk, score_headline
from ..models import NewsItem, NewsRiskScore
from ..time_utils import from_db, iso_ny, to_utc_naive, utc_now

log = logging.getLogger(__name__)


def refresh_news(db: Session, settings: Settings, force: bool = False) -> dict:
    """Fetch + score headlines. Cache guard: skips the provider call if the
    last refresh is younger than NEWS_CACHE_MINUTES (unless force) so jobs
    and manual refreshes can't hammer rate-limited providers."""
    last = db.scalars(
        select(NewsRiskScore).order_by(NewsRiskScore.timestamp.desc()).limit(1)
    ).first()
    if not force and last is not None:
        age = utc_now().replace(tzinfo=None) - last.timestamp
        if age < timedelta(minutes=settings.news_cache_minutes):
            return {
                "ok": True, "skipped": True,
                "reason": f"last refresh {age.total_seconds() / 60:.1f}m ago "
                          f"(< cache window {settings.news_cache_minutes}m)",
            }

    provider = build_provider(settings.news_api_key)
    headlines, err = provider.fetch_headlines()
    if err and not headlines:
        log.warning("news fetch failed (%s): %s", provider.name, err)
        return {"ok": False, "provider": provider.name, "error": err}

    inserted = 0
    for h in headlines:
        exists = db.scalars(select(NewsItem.id).where(NewsItem.url == h.url)).first()
        if exists:
            continue
        s = score_headline(h.title, h.summary)
        db.add(
            NewsItem(
                timestamp=to_utc_naive(h.published_utc),
                source=h.source or provider.name,
                title=h.title,
                url=h.url,
                summary=h.summary,
                sentiment_score=s.sentiment,
                volatility_score=s.volatility,
                relevance_score=s.relevance,
                urgency_score=s.urgency,
                raw_json={"matched": s.matched, "red_folder": s.red_folder,
                          "sentiment_label": s.sentiment_label},
            )
        )
        inserted += 1
    db.commit()

    agg = _recompute_risk_score(db, settings)
    return {"ok": True, "provider": provider.name, "inserted": inserted,
            "score": agg["score"], "red_folder": agg["red_folder_flag"]}


def _recent_items(db: Session, settings: Settings) -> list[NewsItem]:
    cutoff = utc_now().replace(tzinfo=None) - timedelta(hours=settings.news_max_age_hours)
    return list(
        db.scalars(
            select(NewsItem).where(NewsItem.timestamp >= cutoff).order_by(NewsItem.timestamp.desc())
        )
    )


def _recompute_risk_score(db: Session, settings: Settings) -> dict:
    items = _recent_items(db, settings)
    agg = aggregate_news_risk(
        [
            {
                "title": i.title,
                "timestamp": from_db(i.timestamp),
                "sentiment": i.sentiment_score,
                "relevance": i.relevance_score,
                "volatility": i.volatility_score,
                "red_folder": bool((i.raw_json or {}).get("red_folder")),
            }
            for i in items
        ],
        now=utc_now(),
    )
    db.add(
        NewsRiskScore(
            timestamp=to_utc_naive(utc_now()),
            score=agg["score"],
            red_folder_flag=agg["red_folder_flag"],
            summary=agg["summary"],
            metadata_json={k: agg[k] for k in
                           ("formula", "item_count", "high_volatility_count", "red_folder_events")},
        )
    )
    db.commit()
    return agg


def get_news_view(db: Session, settings: Settings, limit: int = 40) -> dict:
    latest_score = db.scalars(
        select(NewsRiskScore).order_by(NewsRiskScore.timestamp.desc()).limit(1)
    ).first()
    items = _recent_items(db, settings)[:limit]
    return {
        "risk_score": (
            {
                "score": latest_score.score,
                "red_folder_flag": latest_score.red_folder_flag,
                "summary": latest_score.summary,
                "timestamp_ny": iso_ny(from_db(latest_score.timestamp)),
                "metadata": latest_score.metadata_json,
            }
            if latest_score else None
        ),
        "items": [
            {
                "id": i.id,
                "timestamp_ny": iso_ny(from_db(i.timestamp)),
                "source": i.source,
                "title": i.title,
                "url": i.url,
                "sentiment": i.sentiment_score,
                "sentiment_label": (i.raw_json or {}).get("sentiment_label", "neutral"),
                "volatility": i.volatility_score,
                "relevance": i.relevance_score,
                "urgency": i.urgency_score,
                "red_folder": bool((i.raw_json or {}).get("red_folder")),
                "matched": (i.raw_json or {}).get("matched"),
            }
            for i in items
        ],
        "note": "Regime/risk overlay only — never a standalone trade signal.",
    }

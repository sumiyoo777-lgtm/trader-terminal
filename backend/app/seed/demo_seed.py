"""DEMO SEED MODE — clearly-labeled synthetic data so the terminal UI is
reviewable without any API keys. Activated only by DEMO_SEED=true and only
into an empty database. Every row is tagged "DEMO" (source/status/metadata)
so demo data can never silently pass as real data.
"""
from __future__ import annotations

import logging
import math
import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..engine.news_score import score_headline
from ..models import (
    CotReport,
    GexSnapshot,
    KronosForecast,
    MarketPrice,
    NewsItem,
)
from ..services.cot_service import _recompute_score
from ..services.news_service import _recompute_risk_score
from ..time_utils import iso_utc, to_utc_naive, utc_now

log = logging.getLogger(__name__)

DEMO_HEADLINES = [
    ("DEMO: Stocks rally as CPI comes in cooler than expected", 0),
    ("DEMO: Treasury yields slip ahead of auction", 2),
    ("DEMO: Fed speaker signals patience on rate cuts", 4),
    ("DEMO: Mega-cap earnings beat estimates after the close", 7),
    ("DEMO: Geopolitical tensions escalate in shipping lanes", 10),
]


def seed_if_empty(db: Session, settings: Settings) -> bool:
    if db.scalars(select(MarketPrice.id).limit(1)).first() is not None:
        log.info("demo seed skipped: database is not empty")
        return False

    log.warning("DEMO SEED MODE: loading clearly-labeled synthetic data (DEMO_SEED=true)")
    now = utc_now()
    rng = random.Random(42)
    symbol = settings.default_symbol

    # --- synthetic MES hourly candles: gentle uptrend with noise ----------
    base = 6000.0
    closes = []
    t0 = now - timedelta(hours=40)
    price = base
    for i in range(40):
        ts = t0 + timedelta(hours=i)
        drift = 1.5 * math.sin(i / 7.0) + 0.8
        price = price + drift + rng.uniform(-4, 4)
        o = price + rng.uniform(-2, 2)
        h = max(o, price) + rng.uniform(0, 3)
        l = min(o, price) - rng.uniform(0, 3)
        db.add(MarketPrice(symbol=symbol, timestamp=to_utc_naive(ts), open=round(o, 2),
                           high=round(h, 2), low=round(l, 2), close=round(price, 2),
                           volume=rng.randint(20000, 90000), source="DEMO"))
        closes.append((ts, price))

    # --- demo hourly Kronos forecast: starts 6h ago so part is realized ----
    f_start = now - timedelta(hours=6)
    last_close = closes[-7][1]
    path, upper, lower = [], [], []
    for i in range(10):
        ts = iso_utc(f_start + timedelta(hours=i))
        v = round(last_close + 3.5 * i, 2)
        path.append([ts, v])
        upper.append([ts, round(v + 14 + i, 2)])
        lower.append([ts, round(v - 14 - i, 2)])
    db.add(KronosForecast(
        symbol=symbol, horizon="hourly", generated_at=to_utc_naive(f_start),
        forecast_start=to_utc_naive(f_start),
        forecast_end=to_utc_naive(f_start + timedelta(hours=9)),
        path_json=path, direction="UP", confidence=71.0,
        band_upper_json=upper, band_lower_json=lower,
        model_version="DEMO", source="demo",
        metadata_json={"DEMO": True, "note": "synthetic forecast for UI review"},
    ))

    # daily forecast
    d_path = [[iso_utc(now + timedelta(days=i)), round(base + 25 * i, 2)] for i in range(5)]
    db.add(KronosForecast(
        symbol=symbol, horizon="daily", generated_at=to_utc_naive(now),
        forecast_start=to_utc_naive(now), forecast_end=to_utc_naive(now + timedelta(days=4)),
        path_json=d_path, direction="UP", confidence=64.0,
        band_upper_json=[[t, v + 60] for t, v in d_path],
        band_lower_json=[[t, v - 60] for t, v in d_path],
        model_version="DEMO", source="demo", metadata_json={"DEMO": True},
    ))

    # --- demo GEX snapshot --------------------------------------------------
    db.add(GexSnapshot(
        symbol=settings.gex_primary_symbol, proxy_for=symbol,
        timestamp=to_utc_naive(now - timedelta(minutes=45)),
        underlying_price=6005.0, net_gex=1.2e9, net_gex_label="positive (DEMO)",
        gamma_flip=5965.0, call_wall=6100.0, put_wall=5900.0,
        largest_positive_gex_strike=6100.0, largest_negative_gex_strike=5900.0,
        status="demo", raw_json={"DEMO": True},
    ))

    # --- demo COT history: 60 weekly reports --------------------------------
    report_day = now.date() - timedelta(days=(now.date().weekday() - 1) % 7)  # last Tuesday
    net = -80000.0
    for w in range(60, 0, -1):
        d = report_day - timedelta(weeks=w - 1)
        net += rng.uniform(-15000, 18000)
        long_v = 400000 + max(net, 0)
        short_v = long_v - net
        db.add(CotReport(
            report_type="legacy", market_name="E-MINI S&P 500 (DEMO)",
            market_code="DEMO", report_date=d, as_of_date=d,
            participant_group="non_commercial",
            long_positions=round(long_v), short_positions=round(short_v),
            spreading=50000, open_interest=2_000_000, raw_json={"DEMO": True},
        ))
        db.add(CotReport(
            report_type="legacy", market_name="E-MINI S&P 500 (DEMO)",
            market_code="DEMO", report_date=d, as_of_date=d,
            participant_group="commercial",
            long_positions=round(short_v), short_positions=round(long_v),
            spreading=0, open_interest=2_000_000, raw_json={"DEMO": True},
        ))
    db.commit()
    _recompute_score(db, settings)

    # --- demo news -----------------------------------------------------------
    for title, hours_old in DEMO_HEADLINES:
        s = score_headline(title)
        db.add(NewsItem(
            timestamp=to_utc_naive(now - timedelta(hours=hours_old)),
            source="DEMO", title=title, url=f"https://example.com/demo/{hours_old}",
            summary="Synthetic demo headline.", sentiment_score=s.sentiment,
            volatility_score=s.volatility, relevance_score=s.relevance,
            urgency_score=s.urgency,
            raw_json={"DEMO": True, "matched": s.matched, "red_folder": s.red_folder,
                      "sentiment_label": s.sentiment_label},
        ))
    db.commit()
    _recompute_risk_score(db, settings)

    log.warning("DEMO SEED complete: %s candles, 2 forecasts, 1 GEX snapshot, "
                "120 COT rows, %s headlines — all tagged DEMO",
                len(closes), len(DEMO_HEADLINES))
    return True

"""COT exposure math — pure, transparent functions.

COT Exposure Score (-100..+100):

    net_t        = long_t - short_t                (per participant group)
    percentile   = rank of latest net within the lookback window (0-100)
    score        = (percentile - 50) * 2           -> -100 crowded short,
                                                       0 neutral,
                                                      +100 crowded long
    crowding     = |percentile - 50| * 2           (0-100, direction-blind)
    4w / 13w chg = net_t - net_{t-4} / net_{t-13}

The primary signal group is non-commercial (legacy speculators); TFF groups
are computed alongside for context. COT is weekly positioning — a macro
regime input, never an intraday timing signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# CFTC releases Friday ~3:30pm ET for the Tuesday as-of. A report older than
# this many days means we are likely missing the newest release.
STALE_AFTER_DAYS = 11


@dataclass
class CotMetrics:
    group: str
    report_date: date | None
    net_position: float | None
    net_percentile: float | None
    four_week_change: float | None
    thirteen_week_change: float | None
    crowding_score: float | None
    score: float | None  # -100..+100
    label: str = "unknown"
    explanation: dict = field(default_factory=dict)


def net_series(reports: list[dict]) -> list[tuple[date, float]]:
    """[(report_date, long - short), ...] oldest first. Rows missing either
    side are skipped (never imputed)."""
    pts = []
    for r in reports:
        long_v, short_v = r.get("long_positions"), r.get("short_positions")
        if long_v is None or short_v is None or r.get("report_date") is None:
            continue
        pts.append((r["report_date"], float(long_v) - float(short_v)))
    pts.sort(key=lambda p: p[0])
    return pts


def percentile_rank(values: list[float], latest: float) -> float:
    """Fraction of window values <= latest, as 0-100. Window includes latest."""
    if not values:
        return 50.0
    below_or_equal = sum(1 for v in values if v <= latest)
    return round(below_or_equal / len(values) * 100.0, 1)


def n_week_change(series: list[tuple[date, float]], weeks: int) -> float | None:
    if len(series) <= weeks:
        return None
    return round(series[-1][1] - series[-1 - weeks][1], 1)


def exposure_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 60:
        return "crowded_long"
    if score >= 20:
        return "bullish_positioning"
    if score > -20:
        return "neutral"
    if score > -60:
        return "bearish_positioning"
    return "crowded_short"


def compute_cot_metrics(
    group: str, reports: list[dict], lookback_weeks: int = 156
) -> CotMetrics:
    """reports: dicts with report_date/long_positions/short_positions for ONE
    participant group of ONE market, any order."""
    series = net_series(reports)
    if not series:
        return CotMetrics(
            group=group, report_date=None, net_position=None, net_percentile=None,
            four_week_change=None, thirteen_week_change=None, crowding_score=None,
            score=None, label="unknown",
            explanation={"note": "no usable reports (missing long/short values)"},
        )

    window = series[-lookback_weeks:]
    latest_date, latest_net = window[-1]
    values = [v for _, v in window]
    pct = percentile_rank(values, latest_net)
    score = round((pct - 50.0) * 2.0, 1)
    crowding = round(abs(pct - 50.0) * 2.0, 1)

    return CotMetrics(
        group=group,
        report_date=latest_date,
        net_position=round(latest_net, 1),
        net_percentile=pct,
        four_week_change=n_week_change(series, 4),
        thirteen_week_change=n_week_change(series, 13),
        crowding_score=crowding,
        score=score,
        label=exposure_label(score),
        explanation={
            "net": "long - short",
            "percentile": f"rank of latest net within {len(window)}-report window = {pct}",
            "score": f"(percentile - 50) * 2 = {score}",
            "crowding": f"|percentile - 50| * 2 = {crowding}",
            "window_weeks": len(window),
        },
    )


def staleness(report_date: date | None, today: date | None = None) -> dict:
    today = today or date.today()
    if report_date is None:
        return {"is_stale": True, "age_days": None,
                "newest_report_available": False,
                "note": "no report stored"}
    age = (today - report_date).days
    stale = age > STALE_AFTER_DAYS
    return {
        "is_stale": stale,
        "age_days": age,
        "newest_report_available": not stale,
        "note": (
            f"as-of Tuesday {report_date.isoformat()}, {age}d old"
            + (" — a newer release likely exists (CFTC publishes Fridays)" if stale else "")
        ),
    }


def expected_latest_as_of(today: date | None = None) -> date:
    """Most recent Tuesday whose Friday release has already happened."""
    today = today or date.today()
    # last Friday release date
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    # that release covers the Tuesday 3 days earlier
    return last_friday - timedelta(days=3)

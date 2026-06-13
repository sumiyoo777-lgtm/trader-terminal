"""COT tests: net exposure, percentile, 4w/13w changes, stale handling,
adapter normalization (including the CFTC 'postions' typo column)."""
from datetime import date, timedelta

import pytest

from app.adapters.cftc_cot import normalize_rows
from app.engine.cot_score import (
    compute_cot_metrics,
    expected_latest_as_of,
    exposure_label,
    n_week_change,
    net_series,
    percentile_rank,
    staleness,
)


def weekly_reports(nets, end=date(2026, 6, 9)):
    """Build report dicts from net values (long = net when positive, etc.)."""
    out = []
    for i, net in enumerate(nets):
        d = end - timedelta(weeks=len(nets) - 1 - i)
        long_v = max(net, 0) + 100000
        short_v = long_v - net
        out.append({"report_date": d, "long_positions": long_v, "short_positions": short_v})
    return out


def test_net_exposure_calculation():
    reports = [{"report_date": date(2026, 6, 9), "long_positions": 350000, "short_positions": 420000}]
    series = net_series(reports)
    assert series == [(date(2026, 6, 9), -70000.0)]


def test_net_skips_incomplete_rows():
    reports = [
        {"report_date": date(2026, 6, 2), "long_positions": None, "short_positions": 1},
        {"report_date": date(2026, 6, 9), "long_positions": 10, "short_positions": 4},
    ]
    assert len(net_series(reports)) == 1


def test_percentile_calculation():
    values = [float(v) for v in range(1, 101)]  # 1..100
    assert percentile_rank(values, 100.0) == 100.0
    assert percentile_rank(values, 1.0) == 1.0
    assert percentile_rank(values, 50.0) == 50.0
    assert percentile_rank([], 5.0) == 50.0  # empty window -> neutral


def test_four_and_thirteen_week_change():
    nets = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130]
    series = [(date(2026, 1, 1) + timedelta(weeks=i), float(n)) for i, n in enumerate(nets)]
    assert n_week_change(series, 4) == 130 - 90
    assert n_week_change(series, 13) == 130 - 0
    assert n_week_change(series[:4], 4) is None  # not enough history


def test_compute_metrics_crowded_long():
    nets = list(range(0, 50)) + [500]  # latest is extreme high
    m = compute_cot_metrics("non_commercial", weekly_reports(nets))
    assert m.net_percentile == 100.0
    assert m.score == 100.0
    assert m.crowding_score == 100.0
    assert m.label == "crowded_long"
    assert "percentile" in m.explanation


def test_compute_metrics_crowded_short():
    nets = list(range(0, 50)) + [-500]
    m = compute_cot_metrics("non_commercial", weekly_reports(nets))
    assert m.score == pytest.approx(-96.0, abs=2)  # ~2nd percentile
    assert m.label == "crowded_short"


def test_compute_metrics_no_data():
    m = compute_cot_metrics("non_commercial", [])
    assert m.score is None
    assert m.label == "unknown"


def test_lookback_window_respected():
    # old extreme values outside the window must not affect the percentile
    nets = [10000.0] * 200 + [0.0, 1.0, 2.0, 3.0, 4.0]
    m = compute_cot_metrics("non_commercial", weekly_reports(nets), lookback_weeks=5)
    assert m.net_percentile == 100.0  # 4 is the max of the 5-report window


def test_stale_report_handling():
    today = date(2026, 6, 12)  # Friday
    fresh = staleness(date(2026, 6, 9), today)  # 3 days old
    assert fresh["is_stale"] is False
    assert fresh["newest_report_available"] is True

    stale = staleness(date(2026, 5, 19), today)  # 24 days old
    assert stale["is_stale"] is True
    assert stale["newest_report_available"] is False
    assert "newer release" in stale["note"]

    missing = staleness(None, today)
    assert missing["is_stale"] is True
    assert missing["age_days"] is None


def test_expected_latest_as_of():
    # Friday 2026-06-12: release that day covers Tuesday 2026-06-09
    assert expected_latest_as_of(date(2026, 6, 12)) == date(2026, 6, 9)
    # Monday 2026-06-15: newest release is still Friday 6/12 -> Tuesday 6/9
    assert expected_latest_as_of(date(2026, 6, 15)) == date(2026, 6, 9)


def test_exposure_labels():
    assert exposure_label(80) == "crowded_long"
    assert exposure_label(30) == "bullish_positioning"
    assert exposure_label(0) == "neutral"
    assert exposure_label(-30) == "bearish_positioning"
    assert exposure_label(-80) == "crowded_short"
    assert exposure_label(None) == "unknown"


LEGACY_RAW = {
    "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
    "cftc_contract_market_code": "13874A",
    "report_date_as_yyyy_mm_dd": "2026-06-09T00:00:00.000",
    "noncomm_positions_long_all": "350000",
    "noncomm_positions_short_all": "420000",
    "noncomm_postions_spread_all": "55000",  # CFTC's real typo column
    "comm_positions_long_all": "900000",
    "comm_positions_short_all": "850000",
    "open_interest_all": "2300000",
}


def test_normalize_legacy_rows():
    rows = normalize_rows([LEGACY_RAW], "legacy")
    assert len(rows) == 2
    nc = next(r for r in rows if r.participant_group == "non_commercial")
    assert nc.long_positions == 350000.0
    assert nc.short_positions == 420000.0
    assert nc.spreading == 55000.0  # typo column handled
    assert nc.open_interest == 2300000.0
    assert nc.report_date == date(2026, 6, 9)
    assert nc.as_of_date == date(2026, 6, 9)
    assert nc.market_code == "13874A"


def test_normalize_tff_rows():
    raw = {
        "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "cftc_contract_market_code": "13874A",
        "report_date_as_yyyy_mm_dd": "2026-06-09",
        "dealer_positions_long_all": "100",
        "dealer_positions_short_all": "200",
        "asset_mgr_positions_long": "1000",
        "asset_mgr_positions_short": "300",
        "lev_money_positions_long": "400",
        "lev_money_positions_short": "900",
        "open_interest_all": "5000",
    }
    rows = normalize_rows([raw], "tff")
    groups = {r.participant_group: r for r in rows}
    assert set(groups) == {"dealer_intermediary", "asset_manager", "leveraged_funds"}
    assert groups["asset_manager"].long_positions == 1000.0
    assert groups["leveraged_funds"].short_positions == 900.0


def test_normalize_skips_bad_rows():
    rows = normalize_rows([{"report_date_as_yyyy_mm_dd": None}, {"junk": 1}], "legacy")
    assert rows == []

"""News tests: headline scoring, red folder flag, aggregate score."""
from datetime import datetime, timedelta, timezone

import pytest

from app.engine.news_score import aggregate_news_risk, score_headline

NOW = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)  # 11:00 NY


def test_bullish_headline():
    s = score_headline("Stocks surge as CPI comes in cooler than expected")
    assert s.sentiment > 0.3
    assert s.sentiment_label == "bullish"
    assert s.volatility == "high"  # CPI is a high-vol term
    assert s.relevance == "high"
    assert s.red_folder is True  # CPI day
    assert "surge" in s.matched["bullish"]


def test_bearish_headline():
    s = score_headline("S&P 500 tumbles as Fed signals higher for longer")
    assert s.sentiment < -0.3
    assert s.sentiment_label == "bearish"
    assert s.relevance == "high"
    assert "tumbles" in s.matched["bearish"]


def test_neutral_irrelevant_headline():
    s = score_headline("Local bakery wins regional bread award")
    assert s.sentiment_label == "neutral"
    assert s.relevance == "low"
    assert s.volatility == "low"
    assert s.red_folder is False


def test_red_folder_terms():
    assert score_headline("FOMC rate decision due at 2pm").red_folder is True
    assert score_headline("Nonfarm payrolls preview: what to expect").red_folder is True
    assert score_headline("Powell testimony before Congress today").red_folder is True
    assert score_headline("Apple unveils new laptop").red_folder is False


def test_word_boundary_matching():
    # "scrip" should not match "strikes" etc.; "fall" must not match "fallacy"
    s = score_headline("The fallacy of crashing waves")
    assert "fall" not in s.matched["bearish"]
    assert "crash" not in s.matched["bearish"]


def make_item(sentiment, relevance="high", hours_old=0.0, red=False, vol="low", title="t"):
    return {
        "title": title,
        "timestamp": NOW - timedelta(hours=hours_old),
        "sentiment": sentiment,
        "relevance": relevance,
        "volatility": vol,
        "red_folder": red,
    }


def test_aggregate_all_bullish():
    agg = aggregate_news_risk([make_item(0.8), make_item(0.6)], NOW)
    assert agg["score"] == pytest.approx(70.0, abs=1)
    assert agg["red_folder_flag"] is False


def test_aggregate_relevance_weighting():
    # one highly-relevant bearish item should outweigh one low-relevance bullish
    agg = aggregate_news_risk(
        [make_item(-0.8, relevance="high"), make_item(0.8, relevance="low")], NOW
    )
    assert agg["score"] < 0


def test_aggregate_recency_decay():
    # a fresh bearish item outweighs an equally-relevant 12h-old bullish item
    agg = aggregate_news_risk(
        [make_item(-0.5, hours_old=0), make_item(0.5, hours_old=12)], NOW
    )
    assert agg["score"] < -20


def test_aggregate_red_folder_today_only():
    today = aggregate_news_risk([make_item(0.0, red=True, hours_old=1)], NOW)
    assert today["red_folder_flag"] is True
    assert len(today["red_folder_events"]) == 1

    yesterday = aggregate_news_risk([make_item(0.0, red=True, hours_old=30)], NOW)
    assert yesterday["red_folder_flag"] is False


def test_aggregate_empty():
    agg = aggregate_news_risk([], NOW)
    assert agg["score"] == 0.0
    assert agg["red_folder_flag"] is False


def test_aggregate_bounds():
    agg = aggregate_news_risk([make_item(1.0)] * 5, NOW)
    assert -100 <= agg["score"] <= 100
    assert agg["score"] == 100.0


def test_formula_disclosed():
    agg = aggregate_news_risk([make_item(0.5)], NOW)
    assert "0.5^(age_hours/4)" in agg["formula"]
    assert "never a standalone trade signal" in agg["note"].lower()

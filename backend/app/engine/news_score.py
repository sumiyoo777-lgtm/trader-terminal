"""News scoring — transparent keyword-lexicon model, NOT vague AI scoring.

Every headline gets:
  sentiment  : sum of matched bullish/bearish term weights, squashed to -1..+1
  volatility : low/medium/high from volatility-impact term matches
  urgency    : low/medium/high from urgency term matches
  relevance  : low/medium/high from market-topic matches (SPX/Fed/CPI/...)
plus the matched terms themselves, so the UI can show exactly why.

Aggregate Live News Risk Score (-100..+100):

    weight_i = relevance_weight (high 3 / medium 2 / low 1)
               * 0.5 ** (age_hours / 4)          # 4-hour recency half-life
    score    = 100 * sum(weight_i * sentiment_i) / sum(weight_i)

Red Folder flag: any headline today (NY date) matching a high-impact macro
event term (FOMC, CPI, NFP, Powell, ...). The news score is a regime/risk
overlay — never a standalone trade signal.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from ..time_utils import ny_session_date, to_ny, to_utc

# --- lexicons (lowercase; matched on word boundaries) ----------------------

BULLISH_TERMS = {
    "rally": 0.6, "rallies": 0.6, "surge": 0.7, "surges": 0.7, "soar": 0.7,
    "soars": 0.7, "jump": 0.5, "jumps": 0.5, "gain": 0.4, "gains": 0.4,
    "record high": 0.8, "all-time high": 0.8, "beat estimates": 0.7,
    "beats estimates": 0.7, "beats expectations": 0.7, "strong earnings": 0.7,
    "upgrade": 0.5, "upgrades": 0.5, "dovish": 0.7, "rate cut": 0.7,
    "rate cuts": 0.7, "cuts rates": 0.7, "cools": 0.5, "cooler than expected": 0.8,
    "soft landing": 0.6, "risk-on": 0.7, "optimism": 0.4, "stimulus": 0.5,
    "ceasefire": 0.6, "deal reached": 0.5, "rebound": 0.5, "rebounds": 0.5,
    "tops forecasts": 0.6, "blowout quarter": 0.7,
}

BEARISH_TERMS = {
    "selloff": -0.7, "sell-off": -0.7, "plunge": -0.8, "plunges": -0.8,
    "tumble": -0.7, "tumbles": -0.7, "sink": -0.6, "sinks": -0.6,
    "slump": -0.6, "slumps": -0.6, "drop": -0.4, "drops": -0.4,
    "fall": -0.3, "falls": -0.3, "crash": -0.9, "misses estimates": -0.7,
    "miss estimates": -0.7, "weak earnings": -0.7, "downgrade": -0.5,
    "downgrades": -0.5, "hawkish": -0.7, "rate hike": -0.7, "hikes rates": -0.7,
    "higher for longer": -0.6, "hotter than expected": -0.8, "sticky inflation": -0.7,
    "recession": -0.7, "risk-off": -0.7, "fear": -0.4, "warns": -0.4,
    "warning": -0.4, "default": -0.7, "bank failure": -0.9, "contagion": -0.8,
    "escalation": -0.6, "strikes": -0.5, "attack": -0.6, "sanctions": -0.4,
    "layoffs": -0.4, "bankruptcy": -0.7, "credit downgrade": -0.7,
    "yields spike": -0.7, "yields surge": -0.7, "weak auction": -0.6,
}

VOLATILITY_HIGH_TERMS = [
    "fomc", "fed decision", "rate decision", "cpi", "ppi", "nonfarm", "non-farm",
    "payrolls", "jobs report", "powell", "crash", "plunge", "circuit breaker",
    "emergency", "war", "invasion", "nuclear", "bank failure", "default",
    "halted", "flash crash", "vix spike",
]
VOLATILITY_MEDIUM_TERMS = [
    "earnings", "guidance", "treasury auction", "fed speaker", "fedspeak",
    "minutes", "jobless claims", "retail sales", "pce", "gdp", "ism",
    "tariff", "tariffs", "opec", "downgrade", "geopolitical", "yields",
]

URGENCY_HIGH_TERMS = [
    "breaking", "just in", "now", "emergency", "halted", "unscheduled",
    "surprise", "unexpected", "imminent",
]
URGENCY_MEDIUM_TERMS = ["today", "this morning", "this afternoon", "ahead of", "due"]

RELEVANCE_HIGH_TERMS = [
    "s&p 500", "s&p500", "spx", "spy", "es futures", "e-mini", "mes",
    "federal reserve", "fed ", "fomc", "powell", "cpi", "ppi", "inflation",
    "nonfarm", "payrolls", "jobs report", "treasury yields", "10-year",
    "vix", "stock market", "wall street", "equities", "rate decision",
    "rate cut", "rate hike", "qqq", "nasdaq",
]
RELEVANCE_MEDIUM_TERMS = [
    "nvidia", "apple", "microsoft", "amazon", "alphabet", "google", "meta",
    "tesla", "semiconductor", "semiconductors", "chips", "ai ", "earnings",
    "treasury auction", "banking", "banks", "credit", "oil", "crude",
    "geopolitic", "china", "tariff", "election", "shutdown", "debt ceiling",
]

RED_FOLDER_TERMS = [
    "fomc", "fed decision", "rate decision", "fed rate", "cpi", "ppi",
    "nonfarm payrolls", "non-farm payrolls", "jobs report", "powell speaks",
    "powell testimony", "powell testifies", "fomc minutes", "jackson hole",
    "pce inflation", "fed chair",
]


@dataclass
class HeadlineScore:
    sentiment: float  # -1..+1
    sentiment_label: str  # bullish | bearish | neutral
    volatility: str  # low | medium | high
    urgency: str
    relevance: str
    red_folder: bool
    matched: dict = field(default_factory=dict)


def _find_terms(text: str, terms) -> list[str]:
    hits = []
    for term in terms:
        if re.search(r"(?<![a-z0-9])" + re.escape(term.strip()) + r"(?![a-z0-9])", text):
            hits.append(term.strip())
    return hits


def score_headline(title: str, summary: str | None = None) -> HeadlineScore:
    text = f"{title} {summary or ''}".lower()

    bull_hits = _find_terms(text, BULLISH_TERMS)
    bear_hits = _find_terms(text, BEARISH_TERMS)
    raw = sum(BULLISH_TERMS[t] for t in bull_hits) + sum(BEARISH_TERMS[t] for t in bear_hits)
    sentiment = math.tanh(raw)  # squash to -1..+1
    label = "bullish" if sentiment > 0.15 else ("bearish" if sentiment < -0.15 else "neutral")

    vol_high = _find_terms(text, VOLATILITY_HIGH_TERMS)
    vol_med = _find_terms(text, VOLATILITY_MEDIUM_TERMS)
    volatility = "high" if vol_high else ("medium" if vol_med else "low")

    urg_high = _find_terms(text, URGENCY_HIGH_TERMS)
    urg_med = _find_terms(text, URGENCY_MEDIUM_TERMS)
    urgency = "high" if urg_high else ("medium" if urg_med or vol_high else "low")

    rel_high = _find_terms(text, RELEVANCE_HIGH_TERMS)
    rel_med = _find_terms(text, RELEVANCE_MEDIUM_TERMS)
    relevance = "high" if rel_high else ("medium" if rel_med else "low")

    red = bool(_find_terms(text, RED_FOLDER_TERMS))

    return HeadlineScore(
        sentiment=round(sentiment, 4),
        sentiment_label=label,
        volatility=volatility,
        urgency=urgency,
        relevance=relevance,
        red_folder=red,
        matched={
            "bullish": bull_hits, "bearish": bear_hits,
            "volatility": vol_high + vol_med, "urgency": urg_high + urg_med,
            "relevance": (rel_high + rel_med)[:8], "red_folder": _find_terms(text, RED_FOLDER_TERMS),
        },
    )


RELEVANCE_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}
RECENCY_HALF_LIFE_HOURS = 4.0


def aggregate_news_risk(
    items: list[dict],
    now: datetime,
) -> dict:
    """items: dicts with keys sentiment (-1..1), relevance (low/med/high),
    volatility, timestamp (tz-aware or naive-UTC datetime), red_folder (bool).

    Returns the Live News Risk Score (-100..+100), the Red Folder flag, and a
    full formula breakdown.
    """
    now = to_utc(now)
    total_w = 0.0
    weighted = 0.0
    red_today = []
    high_vol_count = 0
    for item in items:
        ts = to_utc(item["timestamp"])
        age_hours = max(0.0, (now - ts).total_seconds() / 3600.0)
        w = RELEVANCE_WEIGHT.get(item.get("relevance", "low"), 1.0) * (
            0.5 ** (age_hours / RECENCY_HALF_LIFE_HOURS)
        )
        total_w += w
        weighted += w * float(item.get("sentiment", 0.0))
        if item.get("volatility") == "high":
            high_vol_count += 1
        if item.get("red_folder") and to_ny(ts).date() == ny_session_date(now):
            red_today.append({"title": item.get("title"), "time_ny": to_ny(ts).isoformat()})

    score = 0.0 if total_w <= 0 else max(-100.0, min(100.0, 100.0 * weighted / total_w))
    red_folder = bool(red_today)

    if red_folder:
        summary = (
            f"RED FOLDER: {len(red_today)} high-impact macro/Fed item(s) today — "
            "conditions may be abnormal. "
        )
    else:
        summary = ""
    summary += (
        f"{len(items)} scored headlines, {high_vol_count} high-volatility. "
        f"Risk score {score:.0f} "
        f"({'risk-on / bullish' if score > 20 else 'risk-off / bearish' if score < -20 else 'neutral'})."
    )

    return {
        "score": round(score, 1),
        "red_folder_flag": red_folder,
        "red_folder_events": red_today,
        "high_volatility_count": high_vol_count,
        "item_count": len(items),
        "summary": summary,
        "formula": (
            "score = 100 * sum(w_i * sentiment_i) / sum(w_i); "
            "w_i = relevance_weight(high=3,med=2,low=1) * 0.5^(age_hours/4)"
        ),
        "note": "Regime/risk overlay only — never a standalone trade signal.",
    }

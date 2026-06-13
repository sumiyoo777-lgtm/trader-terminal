"""CFTC COT adapter — official public data via the CFTC Socrata API
(publicreporting.cftc.gov, no API key required, anonymous rate limits apply).

Datasets used (futures-only):
  Legacy  (6dca-aqww): non-commercial / commercial positioning
  TFF     (gpe5-46if): dealer-intermediary / asset-manager / leveraged-funds

For MES the macro proxy is E-MINI S&P 500 (CME contract market code 13874A),
configurable via COT_MARKET_CODES / COT_MARKET_NAME_LIKE.

COT is WEEKLY data (as-of Tuesday, released Friday ~3:30pm ET). It is a
positioning/regime input, never intraday timing — staleness is computed and
surfaced, not hidden.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

import requests

log = logging.getLogger(__name__)

SOCRATA_BASE = "https://publicreporting.cftc.gov/resource"

# CFTC column names. Note: the legacy dataset really does spell it
# "noncomm_postions_spread_all" (CFTC's own typo) — try both spellings.
LEGACY_GROUPS = {
    "non_commercial": {
        "long": ["noncomm_positions_long_all"],
        "short": ["noncomm_positions_short_all"],
        "spread": ["noncomm_postions_spread_all", "noncomm_positions_spread_all"],
    },
    "commercial": {
        "long": ["comm_positions_long_all"],
        "short": ["comm_positions_short_all"],
        "spread": [],
    },
}
TFF_GROUPS = {
    "dealer_intermediary": {
        "long": ["dealer_positions_long_all"],
        "short": ["dealer_positions_short_all"],
        "spread": ["dealer_positions_spread_all"],
    },
    "asset_manager": {
        "long": ["asset_mgr_positions_long", "asset_mgr_positions_long_all"],
        "short": ["asset_mgr_positions_short", "asset_mgr_positions_short_all"],
        "spread": ["asset_mgr_positions_spread", "asset_mgr_positions_spread_all"],
    },
    "leveraged_funds": {
        "long": ["lev_money_positions_long", "lev_money_positions_long_all"],
        "short": ["lev_money_positions_short", "lev_money_positions_short_all"],
        "spread": ["lev_money_positions_spread", "lev_money_positions_spread_all"],
    },
}


@dataclass
class CotRow:
    report_type: str  # legacy | tff
    market_name: str
    market_code: str
    report_date: date
    as_of_date: date  # CFTC report date IS the Tuesday as-of date
    participant_group: str
    long_positions: float | None
    short_positions: float | None
    spreading: float | None
    open_interest: float | None
    raw: dict


def _num(row: dict, keys: list[str]) -> float | None:
    for k in keys:
        v = row.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _parse_date(v) -> date | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "")).date()
    except ValueError:
        return None


def fetch_dataset(
    dataset_id: str,
    market_codes: list[str],
    market_name_like: str,
    weeks: int = 160,
    timeout: float = 30.0,
) -> tuple[list[dict], str | None]:
    """Fetch raw Socrata rows, newest first. Returns (rows, error). Filters
    by contract market code when configured, else by market name pattern."""
    url = f"{SOCRATA_BASE}/{dataset_id}.json"
    if market_codes:
        quoted = ",".join(f"'{c}'" for c in market_codes)
        where = f"cftc_contract_market_code in({quoted})"
    else:
        where = f"upper(market_and_exchange_names) like '%{market_name_like.upper()}%'"
    params = {
        "$where": where,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(weeks * max(1, len(market_codes) or 1)),
    }
    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        return [], f"CFTC request failed: {exc}"
    if resp.status_code == 429:
        return [], "CFTC Socrata rate limit (429) — retry later"
    if resp.status_code != 200:
        return [], f"CFTC HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        rows = resp.json()
    except ValueError:
        return [], "CFTC returned non-JSON body"
    if not isinstance(rows, list):
        return [], "CFTC returned unexpected payload shape"
    return rows, None


def normalize_rows(rows: list[dict], report_type: str) -> list[CotRow]:
    """Explode each raw CFTC row into one CotRow per participant group."""
    groups = LEGACY_GROUPS if report_type == "legacy" else TFF_GROUPS
    out: list[CotRow] = []
    for row in rows:
        report_date = _parse_date(row.get("report_date_as_yyyy_mm_dd"))
        if report_date is None:
            continue
        market_name = (row.get("market_and_exchange_names") or row.get("contract_market_name") or "").strip()
        market_code = (row.get("cftc_contract_market_code") or "").strip()
        oi = _num(row, ["open_interest_all"])
        for group, cols in groups.items():
            long_v = _num(row, cols["long"])
            short_v = _num(row, cols["short"])
            if long_v is None and short_v is None:
                continue
            out.append(
                CotRow(
                    report_type=report_type,
                    market_name=market_name,
                    market_code=market_code,
                    report_date=report_date,
                    as_of_date=report_date,
                    participant_group=group,
                    long_positions=long_v,
                    short_positions=short_v,
                    spreading=_num(row, cols["spread"]),
                    open_interest=oi,
                    raw=row,
                )
            )
    return out

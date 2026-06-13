"""FlashAlpha Lab GEX adapter.

GET {base_url}/v1/exposure/gex/{symbol} with X-Api-Key header.
Never raises: every outcome is a structured result so the service layer can
fall through proxies (SPX -> SPY) and surface precise error states instead
of silently failing. Error-envelope handling mirrors the battle-tested
client in kronos_forward_test (FlashAlpha can return HTTP 200 with an
in-body {"status": "ERROR", ...}).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

GEX_PATH_TEMPLATE = "/v1/exposure/gex/{symbol}"


@dataclass
class FetchResult:
    ok: bool
    kind: str  # ok | no_api_key | invalid_api_key | rate_limited | tier_restricted |
    #            quota_exceeded | server_error | http_error | request_failed | bad_payload | api_error
    message: str = ""
    http_status: int | None = None
    payload: dict | None = None


@dataclass
class ParsedGex:
    underlying_price: float | None = None
    net_gex: float | None = None
    net_gex_label: str | None = None
    gamma_flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    largest_positive_gex_strike: float | None = None
    largest_negative_gex_strike: float | None = None
    as_of: str | None = None
    single_expiry: bool = False  # only one expiration in the data -> label clearly
    partial: bool = False  # some expected fields missing
    missing_fields: list[str] = field(default_factory=list)
    strikes: list[dict] = field(default_factory=list)


def fetch_gex(symbol: str, api_key: str, base_url: str, timeout: float = 20.0) -> FetchResult:
    if not api_key:
        return FetchResult(False, "no_api_key", "FLASHALPHA_API_KEY is not set")

    url = base_url.rstrip("/") + GEX_PATH_TEMPLATE.format(symbol=symbol)
    try:
        resp = requests.get(url, headers={"X-Api-Key": api_key}, timeout=timeout)
    except requests.RequestException as exc:
        return FetchResult(False, "request_failed", str(exc))

    try:
        payload = resp.json()
    except ValueError:
        payload = None

    if resp.status_code == 401:
        return FetchResult(False, "invalid_api_key", "FlashAlpha rejected the API key (401)", 401)
    if resp.status_code == 429:
        msg = (payload or {}).get("message", "rate limited (429)")
        return FetchResult(False, "rate_limited", msg, 429, payload)
    if resp.status_code == 403:
        msg = (payload or {}).get("message", f"{symbol} forbidden (403 — likely needs a higher plan)")
        return FetchResult(False, "tier_restricted", msg, 403, payload)
    if resp.status_code >= 500:
        return FetchResult(False, "server_error", f"FlashAlpha server error {resp.status_code}", resp.status_code)
    if resp.status_code != 200:
        return FetchResult(False, "http_error", f"unexpected HTTP {resp.status_code}", resp.status_code, payload)

    if isinstance(payload, dict) and payload.get("status") == "ERROR":
        err = (payload.get("error") or "").strip().lower()
        kind = "tier_restricted" if "tier" in err else ("quota_exceeded" if "quota" in err else "api_error")
        return FetchResult(False, kind, payload.get("message", err or "FlashAlpha error envelope"), 200, payload)

    if not isinstance(payload, dict):
        return FetchResult(False, "bad_payload", "200 response body was not a JSON object", 200)

    return FetchResult(True, "ok", "", 200, payload)


def _to_float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def parse_gex_payload(payload: dict) -> ParsedGex:
    """Best-effort parse. Missing fields are recorded (partial data is
    labeled, never invented)."""
    parsed = ParsedGex(
        underlying_price=_to_float(payload.get("underlying_price") or payload.get("spot")),
        net_gex=_to_float(payload.get("net_gex")),
        net_gex_label=payload.get("net_gex_label"),
        gamma_flip=_to_float(payload.get("gamma_flip") or payload.get("zero_gamma")),
        as_of=payload.get("as_of") or payload.get("updated_at"),
    )

    strikes_raw = payload.get("strikes") or []
    rows: list[dict] = []
    for s in strikes_raw:
        if not isinstance(s, dict):
            continue
        strike = _to_float(s.get("strike"))
        if strike is None:
            continue
        rows.append({
            "strike": strike,
            "call_gex": _to_float(s.get("call_gex")) or 0.0,
            "put_gex": _to_float(s.get("put_gex")) or 0.0,
            "net_gex": _to_float(s.get("net_gex")) or 0.0,
        })
    parsed.strikes = rows

    if rows:
        parsed.call_wall = max(rows, key=lambda r: r["call_gex"])["strike"]
        parsed.put_wall = min(rows, key=lambda r: r["put_gex"])["strike"]
        by_net = sorted(rows, key=lambda r: r["net_gex"])
        parsed.largest_negative_gex_strike = by_net[0]["strike"]
        parsed.largest_positive_gex_strike = by_net[-1]["strike"]

    # explicit wall fields, if the API provides them, override derivation
    if _to_float(payload.get("call_wall")) is not None:
        parsed.call_wall = _to_float(payload.get("call_wall"))
    if _to_float(payload.get("put_wall")) is not None:
        parsed.put_wall = _to_float(payload.get("put_wall"))

    # single-expiry labeling
    expirations = payload.get("expirations") or payload.get("expiries")
    if isinstance(expirations, list) and len(expirations) == 1:
        parsed.single_expiry = True
    elif payload.get("expiry") or payload.get("expiration"):
        parsed.single_expiry = True

    for name in ("underlying_price", "net_gex", "gamma_flip", "call_wall", "put_wall"):
        if getattr(parsed, name) is None:
            parsed.missing_fields.append(name)
    parsed.partial = bool(parsed.missing_fields)
    return parsed


def fetch_gex_with_fallback(
    symbols: list[str], api_key: str, base_url: str, timeout: float = 20.0
) -> tuple[str | None, FetchResult, list[str]]:
    """Try each proxy symbol in order (SPX first, SPY second per spec).
    Returns (symbol_used, result, attempt_notes)."""
    notes: list[str] = []
    last: FetchResult = FetchResult(False, "no_attempt", "no symbols configured")
    for symbol in symbols:
        result = fetch_gex(symbol, api_key, base_url, timeout)
        if result.ok:
            return symbol, result, notes
        notes.append(f"{symbol}: {result.kind} ({result.message})")
        last = result
        if result.kind in ("no_api_key", "invalid_api_key", "quota_exceeded"):
            break  # these won't succeed for any symbol — stop burning quota
    return None, last, notes

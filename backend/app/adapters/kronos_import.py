"""Kronos Mode A — manual forecast import (JSON or CSV).

Normalized forecast shape (what the DB stores and every consumer reads):

    {
      "symbol": "MES",
      "horizon": "hourly" | "daily",
      "generated_at": datetime (UTC),
      "path": [[iso_utc, value], ...],          # ascending timestamps
      "band_upper": [[iso_utc, value], ...] | None,
      "band_lower": [[iso_utc, value], ...] | None,
      "direction": "UP" | "DOWN" | "NEUTRAL",
      "confidence": float 0-100 | None,
      "model_version": str | None,
      "metadata": dict,
    }

Malformed input raises KronosImportError with a message that says exactly
what is wrong — imports never half-succeed.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from ..time_utils import iso_utc, to_utc

DIRECTION_THRESHOLD_PCT = 0.25  # net move below this is NEUTRAL
VALID_HORIZONS = ("hourly", "daily")


class KronosImportError(ValueError):
    pass


def _parse_ts(value) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        return to_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError as exc:
        raise KronosImportError(f"unparseable timestamp {value!r}") from exc


def _parse_val(value, where: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise KronosImportError(f"non-numeric value {value!r} in {where}") from exc


def _normalize_series(raw, name: str) -> list[list]:
    """Accept [[ts, value], ...] or [{timestamp, value}, ...]; emit
    [[iso_utc, float], ...] sorted ascending."""
    if not isinstance(raw, list) or not raw:
        raise KronosImportError(f"{name} must be a non-empty list")
    points = []
    for i, p in enumerate(raw):
        if isinstance(p, dict):
            ts_raw, v_raw = p.get("timestamp") or p.get("ts") or p.get("time"), p.get("value")
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            ts_raw, v_raw = p[0], p[1]
        else:
            raise KronosImportError(f"{name}[{i}] must be [timestamp, value] or an object")
        if ts_raw is None:
            raise KronosImportError(f"{name}[{i}] is missing a timestamp")
        ts = _parse_ts(ts_raw)
        points.append([ts, _parse_val(v_raw, f"{name}[{i}]")])
    points.sort(key=lambda p: p[0])
    if len({p[0] for p in points}) != len(points):
        raise KronosImportError(f"{name} contains duplicate timestamps")
    return [[iso_utc(ts), v] for ts, v in points]


def derive_direction(path: list[list]) -> str:
    start, end = path[0][1], path[-1][1]
    if start == 0:
        return "NEUTRAL"
    pct = (end - start) / abs(start) * 100.0
    if pct > DIRECTION_THRESHOLD_PCT:
        return "UP"
    if pct < -DIRECTION_THRESHOLD_PCT:
        return "DOWN"
    return "NEUTRAL"


def parse_forecast_json(text_or_obj, default_symbol: str = "MES") -> dict:
    if isinstance(text_or_obj, (str, bytes)):
        try:
            obj = json.loads(text_or_obj)
        except json.JSONDecodeError as exc:
            raise KronosImportError(f"invalid JSON: {exc}") from exc
    else:
        obj = text_or_obj
    if not isinstance(obj, dict):
        raise KronosImportError("top-level JSON must be an object")

    horizon = str(obj.get("horizon", "")).lower()
    if horizon not in VALID_HORIZONS:
        raise KronosImportError(f"horizon must be one of {VALID_HORIZONS}, got {obj.get('horizon')!r}")

    path = _normalize_series(obj.get("path") or obj.get("forecast_path"), "path")

    band_upper = band_lower = None
    if obj.get("band_upper") is not None:
        band_upper = _normalize_series(obj["band_upper"], "band_upper")
    if obj.get("band_lower") is not None:
        band_lower = _normalize_series(obj["band_lower"], "band_lower")
    if (band_upper is None) != (band_lower is None):
        raise KronosImportError("band_upper and band_lower must be provided together")
    if band_upper is not None and (
        len(band_upper) != len(path) or len(band_lower) != len(path)
    ):
        raise KronosImportError("bands must have the same length as path")
    if band_upper is not None:
        for (_, u), (_, l) in zip(band_upper, band_lower):
            if u < l:
                raise KronosImportError("band_upper must be >= band_lower at every point")

    generated_at = (
        _parse_ts(obj["generated_at"]) if obj.get("generated_at") else datetime.now(timezone.utc)
    )

    confidence = None
    if obj.get("confidence") is not None:
        confidence = _parse_val(obj["confidence"], "confidence")
        if not 0 <= confidence <= 100:
            raise KronosImportError("confidence must be 0-100")

    direction = str(obj.get("direction", "") or derive_direction(path)).upper()
    if direction not in ("UP", "DOWN", "NEUTRAL", "CHOP"):
        raise KronosImportError(f"direction must be UP/DOWN/NEUTRAL/CHOP, got {direction!r}")

    return {
        "symbol": str(obj.get("symbol") or default_symbol).upper(),
        "horizon": horizon,
        "generated_at": generated_at,
        "path": path,
        "band_upper": band_upper,
        "band_lower": band_lower,
        "direction": direction,
        "confidence": confidence,
        "model_version": obj.get("model_version"),
        "metadata": obj.get("metadata") or {},
    }


def parse_forecast_csv(
    text: str, horizon: str, symbol: str = "MES",
    confidence: float | None = None, model_version: str | None = None,
) -> dict:
    """CSV columns: timestamp,value[,upper,lower] (header required)."""
    if horizon not in VALID_HORIZONS:
        raise KronosImportError(f"horizon must be one of {VALID_HORIZONS}, got {horizon!r}")
    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        raise KronosImportError("CSV is empty")
    fields = [f.strip().lower() for f in reader.fieldnames]
    if "timestamp" not in fields or "value" not in fields:
        raise KronosImportError("CSV must have 'timestamp' and 'value' columns")
    has_bands = "upper" in fields and "lower" in fields

    path, upper, lower = [], [], []
    for i, row in enumerate(reader):
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        ts = _parse_ts(row.get("timestamp"))
        path.append([ts, _parse_val(row.get("value"), f"row {i + 1} value")])
        if has_bands:
            upper.append([ts, _parse_val(row.get("upper"), f"row {i + 1} upper")])
            lower.append([ts, _parse_val(row.get("lower"), f"row {i + 1} lower")])
    if not path:
        raise KronosImportError("CSV contains no data rows")

    obj = {
        "symbol": symbol,
        "horizon": horizon,
        "path": [[iso_utc(ts), v] for ts, v in path],
        "band_upper": [[iso_utc(ts), v] for ts, v in upper] if has_bands else None,
        "band_lower": [[iso_utc(ts), v] for ts, v in lower] if has_bands else None,
        "confidence": confidence,
        "model_version": model_version,
        "metadata": {"import_format": "csv"},
    }
    return parse_forecast_json(obj, default_symbol=symbol)

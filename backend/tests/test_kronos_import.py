"""Kronos adapter tests: manual import (JSON/CSV), malformed handling,
hourly/daily storage, local-runner availability + payload normalization."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.adapters.kronos_import import (
    KronosImportError,
    derive_direction,
    parse_forecast_csv,
    parse_forecast_json,
)
from app.adapters.kronos_local import (
    KronosLocalError,
    local_kronos_available,
    normalize_runner_payload,
)
from app.db import Base
from app.services.kronos_service import latest_forecast, store_forecast

VALID_JSON = {
    "symbol": "MES",
    "horizon": "hourly",
    "generated_at": "2026-06-12T13:00:00Z",
    "path": [
        ["2026-06-12T14:00:00Z", 6010.0],
        ["2026-06-12T15:00:00Z", 6040.0],
        ["2026-06-12T16:00:00Z", 6070.0],
    ],
    "band_upper": [
        ["2026-06-12T14:00:00Z", 6030.0],
        ["2026-06-12T15:00:00Z", 6060.0],
        ["2026-06-12T16:00:00Z", 6090.0],
    ],
    "band_lower": [
        ["2026-06-12T14:00:00Z", 5990.0],
        ["2026-06-12T15:00:00Z", 6020.0],
        ["2026-06-12T16:00:00Z", 6050.0],
    ],
    "confidence": 72,
    "model_version": "Kronos-small",
}


def test_valid_json_import():
    f = parse_forecast_json(VALID_JSON)
    assert f["symbol"] == "MES"
    assert f["horizon"] == "hourly"
    assert f["direction"] == "UP"  # ~1% net move, derived
    assert f["confidence"] == 72.0
    assert len(f["path"]) == 3
    assert f["path"][0][0] == "2026-06-12T14:00:00Z"
    assert f["generated_at"] == datetime(2026, 6, 12, 13, 0, tzinfo=timezone.utc)


def test_object_style_path_points():
    obj = dict(VALID_JSON, path=[
        {"timestamp": "2026-06-12T14:00:00Z", "value": 6010},
        {"timestamp": "2026-06-12T15:00:00Z", "value": 6005},
    ], band_upper=None, band_lower=None)
    f = parse_forecast_json(obj)
    assert f["path"][1][1] == 6005.0


def test_path_sorted_ascending():
    obj = dict(VALID_JSON, path=list(reversed(VALID_JSON["path"])),
               band_upper=None, band_lower=None)
    f = parse_forecast_json(obj)
    assert f["path"][0][0] < f["path"][-1][0]


@pytest.mark.parametrize("mutation,fragment", [
    ({"horizon": "weekly"}, "horizon"),
    ({"path": []}, "non-empty"),
    ({"path": "nope"}, "non-empty"),
    ({"path": [["bad-ts", 1.0]]}, "timestamp"),
    ({"path": [["2026-06-12T14:00:00Z", "NaN-ish"]]}, "non-numeric"),
    ({"confidence": 150}, "confidence"),
    ({"direction": "SIDEWAYS"}, "direction"),
    ({"band_lower": None}, "together"),
])
def test_malformed_json_rejected(mutation, fragment):
    obj = {**VALID_JSON, **mutation}
    with pytest.raises(KronosImportError) as exc:
        parse_forecast_json(obj)
    assert fragment.lower() in str(exc.value).lower()


def test_invalid_json_text():
    with pytest.raises(KronosImportError):
        parse_forecast_json("{not json")


def test_duplicate_timestamps_rejected():
    obj = dict(VALID_JSON, path=[
        ["2026-06-12T14:00:00Z", 6010.0],
        ["2026-06-12T14:00:00Z", 6020.0],
    ], band_upper=None, band_lower=None)
    with pytest.raises(KronosImportError, match="duplicate"):
        parse_forecast_json(obj)


def test_band_cross_rejected():
    obj = dict(
        VALID_JSON,
        band_upper=[["2026-06-12T14:00:00Z", 5000.0], ["2026-06-12T15:00:00Z", 6060.0],
                    ["2026-06-12T16:00:00Z", 6090.0]],
    )
    with pytest.raises(KronosImportError, match="band_upper must be >="):
        parse_forecast_json(obj)


def test_csv_import_with_bands():
    csv_text = (
        "timestamp,value,upper,lower\n"
        "2026-06-12T14:00:00Z,6010,6030,5990\n"
        "2026-06-12T15:00:00Z,6040,6060,6020\n"
    )
    f = parse_forecast_csv(csv_text, horizon="daily", symbol="MES", confidence=60)
    assert f["horizon"] == "daily"
    assert f["band_upper"][0][1] == 6030.0
    assert f["confidence"] == 60.0
    assert f["metadata"]["import_format"] == "csv"


def test_csv_missing_columns():
    with pytest.raises(KronosImportError, match="timestamp"):
        parse_forecast_csv("time,price\n1,2\n", horizon="hourly")


def test_csv_empty():
    with pytest.raises(KronosImportError):
        parse_forecast_csv("", horizon="hourly")


def test_derive_direction():
    up = [["t1", 100.0], ["t2", 101.0]]
    down = [["t1", 100.0], ["t2", 99.0]]
    flat = [["t1", 100.0], ["t2", 100.1]]
    assert derive_direction(up) == "UP"
    assert derive_direction(down) == "DOWN"
    assert derive_direction(flat) == "NEUTRAL"


# --- storage (hourly + daily) ------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def test_hourly_and_daily_forecast_storage(db):
    hourly = parse_forecast_json(VALID_JSON)
    daily = parse_forecast_json({**VALID_JSON, "horizon": "daily"})
    store_forecast(db, hourly, source="import")
    store_forecast(db, daily, source="import")

    h = latest_forecast(db, "MES", "hourly")
    d = latest_forecast(db, "MES", "daily")
    assert h is not None and h.horizon == "hourly"
    assert d is not None and d.horizon == "daily"
    assert len(h.path_json) == 3
    assert h.forecast_start.isoformat().startswith("2026-06-12T14:00")
    assert h.forecast_end.isoformat().startswith("2026-06-12T16:00")
    assert h.source == "import"


# --- local runner -------------------------------------------------------------

def test_local_availability_reports_reason(tmp_path):
    ok, reason = local_kronos_available(model_path=str(tmp_path / "missing"),
                                        venv_dir=tmp_path / "novenv")
    assert ok is False
    assert "venv" in reason or "repo" in reason


def test_runner_payload_normalized_like_import():
    payload = {
        "symbol": "MES=F", "horizon": "hourly",
        "generated_at": "2026-06-12T13:05:00Z",
        "current_price": 6005.0,
        "path": [["2026-06-12T14:00:00Z", 6010.0], ["2026-06-12T15:00:00Z", 6040.0]],
        "band_upper": [["2026-06-12T14:00:00Z", 6030.0], ["2026-06-12T15:00:00Z", 6060.0]],
        "band_lower": [["2026-06-12T14:00:00Z", 5990.0], ["2026-06-12T15:00:00Z", 6020.0]],
        "direction": "UP", "confidence": 70.0,
        "model_version": "NeoQuasar/Kronos-small",
    }
    f = normalize_runner_payload(payload)
    assert f["metadata"]["mode"] == "local_runner"
    assert f["metadata"]["current_price_at_run"] == 6005.0
    assert f["direction"] == "UP"


def test_runner_payload_malformed_raises():
    with pytest.raises(KronosLocalError, match="validation"):
        normalize_runner_payload({"horizon": "hourly", "path": []})

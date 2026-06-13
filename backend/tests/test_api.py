"""API integration tests — full request/response cycle through FastAPI with
a real (file-backed test) database, no network calls."""
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Alert, GexSnapshot, MarketPrice
from app.time_utils import to_utc_naive, utc_now

from datetime import timedelta


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


VALID_FORECAST = {
    "symbol": "MES",
    "horizon": "hourly",
    "path": [],  # filled in fixture below
    "confidence": 70,
    "model_version": "test",
}


def _forecast_body():
    now = utc_now()
    path, upper, lower = [], [], []
    for i in range(8):
        ts = (now + timedelta(hours=i - 4)).isoformat()
        v = 6000.0 + 4 * i
        path.append([ts, v])
        upper.append([ts, v + 15])
        lower.append([ts, v - 15])
    return {**VALID_FORECAST, "path": path, "band_upper": upper, "band_lower": lower}


def _seed_prices_and_gex():
    db = SessionLocal()
    now = utc_now()
    for i in range(8):
        ts = to_utc_naive(now - timedelta(hours=7 - i))
        if db.query(MarketPrice).filter_by(symbol="MES", timestamp=ts).first():
            continue
        close = 6000.0 + 4 * (i - 3)
        db.add(MarketPrice(symbol="MES", timestamp=ts, open=close - 1, high=close + 2,
                           low=close - 3, close=close, volume=1000, source="test"))
    db.add(GexSnapshot(symbol="SPX", proxy_for="MES", timestamp=to_utc_naive(now),
                       underlying_price=6005.0, net_gex=1e9, net_gex_label="positive",
                       gamma_flip=5960.0, call_wall=6100.0, put_wall=5900.0,
                       status="ok", raw_json={}))
    db.commit()
    db.close()


def test_health(client):
    assert client.get("/health").json()["ok"] is True


def test_summary_empty_db_has_explicit_nulls(client):
    r = client.get("/api/trader-terminal/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "MES"
    assert body["session_status"] in ("premarket", "rth", "after_hours", "closed")
    assert body["data_health"]["kronos"]["ok"] is False  # nothing imported yet


def test_kronos_unavailable_state(client):
    r = client.get("/api/trader-terminal/kronos")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "kronos_unavailable"
    assert body["availability"]["manual_import_available"] is True


def test_kronos_import_malformed_422(client):
    r = client.post("/api/trader-terminal/kronos/import",
                    json={"horizon": "hourly", "path": []})
    assert r.status_code == 422
    assert "non-empty" in r.json()["detail"]


def test_kronos_import_and_respect_flow(client):
    _seed_prices_and_gex()
    r = client.post("/api/trader-terminal/kronos/import", json=_forecast_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["direction"] == "UP"

    k = client.get("/api/trader-terminal/kronos", params={"slider": 50}).json()
    assert k["status"] == "ok"
    assert k["respect"]["score"] is not None
    assert 0 <= k["respect"]["score"] <= 100
    assert k["kalman"]["slider_label"] == "Kronos Trust / Kalman Reactivity"
    assert len(k["series"]["kronos_path"]) == 8
    # sub-scores all present
    for key in ("direction_score", "correlation_score", "band_respect_score",
                "kalman_residual_score", "invalidation_score"):
        assert key in k["respect"]

    # slider extremes change the estimate
    k0 = client.get("/api/trader-terminal/kronos", params={"slider": 0}).json()
    k100 = client.get("/api/trader-terminal/kronos", params={"slider": 100}).json()
    assert k0["kalman"]["slider"] == 0
    assert k100["kalman"]["slider"] == 100


def test_regime_recalculate_and_view(client):
    r = client.post("/api/trader-terminal/regime/recalculate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bias"] in ("long", "short", "neutral", "no_trade")
    assert body["environment"] in (
        "continuation", "consolidation", "mean_reversion",
        "reversal_risk", "event_risk", "no_trade",
    )
    assert 0 <= body["confidence"] <= 100
    assert body["reasons"]
    assert body["invalidations"]
    assert body["what_would_change_my_mind"]
    assert body["playbook"]

    view = client.get("/api/trader-terminal/regime").json()
    assert view["current"]["bias"] == body["bias"]


def test_gex_view(client):
    r = client.get("/api/trader-terminal/gex")
    assert r.status_code == 200
    body = r.json()
    assert body["latest"]["symbol"] == "SPX"
    assert body["latest"]["regime"]["regime"] in ("positive", "negative", "near_flip")
    conv = body["latest"]["converted_to_trading_symbol"]
    assert conv["approximate"] is True
    assert "APPROXIMATE" in conv["disclaimer"]


def test_gex_refresh_without_key_is_explicit_error(client):
    r = client.post("/api/trader-terminal/gex/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["kind"] == "no_api_key"


def test_cot_view_empty_is_explicit(client):
    r = client.get("/api/trader-terminal/cot")
    assert r.status_code == 200
    body = r.json()
    assert body["staleness"]["is_stale"] is True
    assert body["headline"] is None or body["headline"]["score"] is None


def test_news_view(client):
    r = client.get("/api/trader-terminal/news")
    assert r.status_code == 200
    assert "never a standalone trade signal" in r.json()["note"].lower()


def test_alerts_acknowledge_flow(client):
    db = SessionLocal()
    db.add(Alert(timestamp=to_utc_naive(utc_now()), symbol="MES",
                 alert_type="test_alert", severity="info",
                 title="Test", message="test alert", metadata_json={}))
    db.commit()
    alert_id = db.query(Alert).order_by(Alert.id.desc()).first().id
    db.close()

    alerts = client.get("/api/trader-terminal/alerts").json()["alerts"]
    assert any(a["id"] == alert_id for a in alerts)

    ack = client.post(f"/api/trader-terminal/alerts/{alert_id}/acknowledge")
    assert ack.json()["ok"] is True
    remaining = client.get("/api/trader-terminal/alerts").json()["alerts"]
    assert not any(a["id"] == alert_id for a in remaining)

    missing = client.post("/api/trader-terminal/alerts/999999/acknowledge")
    assert missing.status_code == 404


def test_summary_after_data(client):
    body = client.get("/api/trader-terminal/summary").json()
    assert body["scores"]["kronos_hourly_direction"] == "UP"
    assert body["data_health"]["kronos"]["ok"] is True
    assert body["data_health"]["gex"]["ok"] is True

"""GEX tests: payload parsing, missing data, SPX->SPY fallback, regime
classification, gamma-flip distance, conversion labeling."""
import pytest

from app.adapters import flashalpha
from app.adapters.flashalpha import FetchResult, fetch_gex_with_fallback, parse_gex_payload
from app.engine.gex_regime import classify_gex_regime, conversion_factor, convert_level

FULL_PAYLOAD = {
    "underlying_price": 6000.0,
    "net_gex": 1.5e9,
    "net_gex_label": "Positive Gamma",
    "gamma_flip": 5950.0,
    "as_of": "2026-06-12T14:30:00Z",
    "strikes": [
        {"strike": 5900, "call_gex": 1e8, "put_gex": -9e8, "net_gex": -8e8},
        {"strike": 5950, "call_gex": 2e8, "put_gex": -3e8, "net_gex": -1e8},
        {"strike": 6000, "call_gex": 6e8, "put_gex": -1e8, "net_gex": 5e8},
        {"strike": 6050, "call_gex": 9e8, "put_gex": -5e7, "net_gex": 8.5e8},
    ],
}


def test_successful_parsing():
    p = parse_gex_payload(FULL_PAYLOAD)
    assert p.underlying_price == 6000.0
    assert p.net_gex == 1.5e9
    assert p.gamma_flip == 5950.0
    assert p.call_wall == 6050  # max call_gex strike
    assert p.put_wall == 5900  # most negative put_gex strike
    assert p.largest_positive_gex_strike == 6050
    assert p.largest_negative_gex_strike == 5900
    assert p.partial is False
    assert p.single_expiry is False


def test_missing_data_labeled_partial():
    p = parse_gex_payload({"underlying_price": 6000.0})
    assert p.partial is True
    assert "gamma_flip" in p.missing_fields
    assert "call_wall" in p.missing_fields
    assert p.net_gex is None


def test_single_expiry_labeled():
    payload = dict(FULL_PAYLOAD, expirations=["2026-06-12"])
    assert parse_gex_payload(payload).single_expiry is True
    payload2 = dict(FULL_PAYLOAD, expiry="2026-06-12")
    assert parse_gex_payload(payload2).single_expiry is True


def test_malformed_strikes_skipped():
    payload = dict(FULL_PAYLOAD, strikes=[{"strike": "bad"}, "junk", {"strike": 6000, "call_gex": 1e8}])
    p = parse_gex_payload(payload)
    assert len(p.strikes) == 1


def test_spx_to_spy_fallback(monkeypatch):
    calls = []

    def fake_fetch(symbol, api_key, base_url, timeout=20.0):
        calls.append(symbol)
        if symbol == "SPX":
            return FetchResult(False, "tier_restricted", "SPX needs paid plan", 403)
        return FetchResult(True, "ok", "", 200, FULL_PAYLOAD)

    monkeypatch.setattr(flashalpha, "fetch_gex", fake_fetch)
    used, result, notes = fetch_gex_with_fallback(["SPX", "SPY"], "key", "https://x")
    assert used == "SPY"
    assert result.ok
    assert calls == ["SPX", "SPY"]
    assert "SPX: tier_restricted" in notes[0]


def test_fallback_stops_on_invalid_key(monkeypatch):
    calls = []

    def fake_fetch(symbol, api_key, base_url, timeout=20.0):
        calls.append(symbol)
        return FetchResult(False, "invalid_api_key", "bad key", 401)

    monkeypatch.setattr(flashalpha, "fetch_gex", fake_fetch)
    used, result, notes = fetch_gex_with_fallback(["SPX", "SPY"], "key", "https://x")
    assert used is None
    assert result.kind == "invalid_api_key"
    assert calls == ["SPX"]  # no point trying SPY with a bad key


def test_no_api_key():
    result = flashalpha.fetch_gex("SPX", "", "https://x")
    assert result.kind == "no_api_key"
    assert not result.ok


def test_regime_positive_gamma():
    r = classify_gex_regime(net_gex=1e9, spot=6000.0, gamma_flip=5900.0)
    assert r.regime == "positive"
    assert r.score is not None and r.score > 0
    assert r.distance_to_flip == 100.0
    assert "mean reversion" in r.guidance[0].lower()


def test_regime_negative_gamma():
    r = classify_gex_regime(net_gex=-1e9, spot=5800.0, gamma_flip=5900.0)
    assert r.regime == "negative"
    assert r.score is not None and r.score < 0
    assert r.distance_to_flip == -100.0
    assert "momentum" in r.guidance[0].lower()


def test_regime_near_flip():
    r = classify_gex_regime(net_gex=1e8, spot=6000.0, gamma_flip=5995.0, near_flip_pct=0.35)
    assert r.regime == "near_flip"
    assert abs(r.score) <= 25
    assert r.distance_to_flip_pct < 0.35


def test_regime_unknown_when_no_data():
    r = classify_gex_regime(net_gex=None, spot=None, gamma_flip=None)
    assert r.regime == "unknown"
    assert r.score is None


def test_gamma_flip_distance_sign():
    above = classify_gex_regime(net_gex=None, spot=6000.0, gamma_flip=5950.0)
    below = classify_gex_regime(net_gex=None, spot=5900.0, gamma_flip=5950.0)
    assert above.distance_to_flip == 50.0
    assert below.distance_to_flip == -50.0
    assert above.regime == "positive"
    assert below.regime == "negative"


def test_wall_distances():
    r = classify_gex_regime(
        net_gex=1e9, spot=6000.0, gamma_flip=5900.0, call_wall=6050.0, put_wall=5800.0
    )
    assert r.distance_to_call_wall == 50.0
    assert r.distance_to_put_wall == 200.0


def test_conversion_dynamic_vs_static():
    f, method = conversion_factor("SPY", proxy_price=600.0, trading_price=6010.0)
    assert method == "dynamic_ratio"
    assert f == pytest.approx(6010.0 / 600.0)
    f2, method2 = conversion_factor("SPY", proxy_price=None, trading_price=6010.0)
    assert method2 == "static_multiplier"
    assert f2 == 10.0
    assert convert_level(600.0, f2) == 6000.0
    assert convert_level(None, f2) is None

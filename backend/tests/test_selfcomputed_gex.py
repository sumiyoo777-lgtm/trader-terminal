"""Self-computed GEX fallback tests (pure math, no network)."""
from datetime import datetime, timezone

import pytest

from app.adapters.flashalpha import parse_gex_payload
from app.adapters.selfcomputed_gex import (
    _zero_gamma_level,
    bs_gamma,
    compute_gex_from_chain,
)
from app.engine.gex_regime import classify_gex_regime

NOW = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)


def chain_row(strike, iv=0.2, oi=1000):
    return {"strike": strike, "impliedVolatility": iv, "openInterest": oi}


def test_bs_gamma_atm_positive_and_symmetric_decay():
    atm = bs_gamma(spot=600, strike=600, t_years=30 / 365, iv=0.2)
    otm = bs_gamma(spot=600, strike=660, t_years=30 / 365, iv=0.2)
    assert atm > 0
    assert otm < atm  # gamma peaks near the money
    # degenerate inputs are zero, never NaN/raise
    assert bs_gamma(600, 600, 0, 0.2) == 0.0
    assert bs_gamma(600, 600, 0.1, 0) == 0.0
    assert bs_gamma(0, 600, 0.1, 0.2) == 0.0


def contract(strike, side, oi=1000, t=30 / 365, iv=0.2):
    return (float(strike), t, iv, float(oi), 1 if side == "call" else -1)


def test_zero_gamma_level_between_put_and_call_mass():
    # heavy put gamma below spot, heavy call gamma above -> profile crosses
    # zero somewhere between the two strikes
    contracts = [contract(560, "put", oi=10000), contract(640, "call", oi=10000)]
    flip = _zero_gamma_level(contracts, spot=600.0)
    assert flip is not None
    assert 560 < flip < 640


def test_zero_gamma_level_none_when_one_sided():
    # all-call chain: net GEX positive at every level -> no flip in band,
    # and we report None instead of inventing a level
    contracts = [contract(600, "call", oi=10000), contract(610, "call", oi=8000)]
    assert _zero_gamma_level(contracts, spot=600.0) is None


def test_compute_payload_shape_feeds_flashalpha_parser():
    chains = [(
        "2026-06-19",
        [chain_row(590, oi=100), chain_row(600, oi=5000), chain_row(610, oi=8000)],  # calls
        [chain_row(570, oi=9000), chain_row(580, oi=4000), chain_row(600, oi=100)],  # puts
    )]
    payload = compute_gex_from_chain(spot=600.0, chains=chains, now=NOW)
    assert payload is not None
    assert payload["source"] == "self_computed"
    assert "self-computed" in payload["net_gex_label"]

    parsed = parse_gex_payload(payload)
    assert parsed.underlying_price == 600.0
    assert parsed.call_wall is not None and parsed.put_wall is not None
    # call wall is a call-heavy strike, put wall a put-heavy strike
    assert parsed.call_wall >= 600
    assert parsed.put_wall <= 580
    assert parsed.single_expiry is True  # one expiry -> labeled

    regime = classify_gex_regime(parsed.net_gex, parsed.underlying_price, parsed.gamma_flip)
    assert regime.regime in ("positive", "negative", "near_flip")


def test_put_dominated_chain_is_negative_gex():
    chains = [("2026-06-19", [chain_row(600, oi=100)], [chain_row(595, oi=50000)])]
    payload = compute_gex_from_chain(600.0, chains, NOW)
    assert payload["net_gex"] < 0
    assert "negative" in payload["net_gex_label"]


def test_unusable_chain_returns_none():
    # zero OI / zero IV everywhere -> no fabricated data
    chains = [(
        "2026-06-19",
        [{"strike": 600, "impliedVolatility": 0.0, "openInterest": 0}],
        [{"strike": 600, "impliedVolatility": None, "openInterest": None}],
    )]
    assert compute_gex_from_chain(600.0, chains, NOW) is None
    assert compute_gex_from_chain(600.0, [], NOW) is None


def test_malformed_rows_skipped():
    chains = [(
        "2026-06-19",
        [{"strike": "bad"}, chain_row(600, oi=1000)],
        [{}],
    )]
    payload = compute_gex_from_chain(600.0, chains, NOW)
    assert payload is not None
    assert len(payload["strikes"]) == 1

"""Unified regime engine + alert condition tests (spec scenarios)."""
from app.engine.alerts import TerminalState, check_alert_conditions
from app.engine.regime import RegimeInputs, evaluate_regime


def base_inputs(**kw) -> RegimeInputs:
    defaults = dict(
        kronos_hourly_direction="UP",
        kronos_daily_direction="UP",
        kronos_respect_score=80.0,
        kronos_confidence=75.0,
        forecast_failing=False,
        forecast_inverted=False,
        gex_regime="negative",
        distance_to_flip_pct=1.2,
        cot_score=20.0,
        news_score=30.0,
        red_folder=False,
    )
    defaults.update(kw)
    return RegimeInputs(**defaults)


def test_continuation_long():
    d = evaluate_regime(base_inputs())
    assert d.bias == "long"
    assert d.environment == "continuation"
    assert d.confidence > 65
    assert any("following the forecast" in r for r in d.reasons)
    assert any("Negative gamma" in r for r in d.reasons)
    assert "Continuation long" in d.playbook
    assert any("Respect Score falling below 40" in i for i in d.invalidations)
    assert len(d.what_would_change_my_mind) >= 6


def test_continuation_short():
    d = evaluate_regime(base_inputs(
        kronos_hourly_direction="DOWN", kronos_daily_direction="DOWN",
        news_score=-30.0, cot_score=-20.0,
    ))
    assert d.bias == "short"
    assert d.environment == "continuation"
    assert d.confidence > 65
    assert "Continuation short" in d.playbook


def test_consolidation_positive_gamma_no_direction():
    d = evaluate_regime(base_inputs(
        kronos_hourly_direction="NEUTRAL", kronos_daily_direction="NEUTRAL",
        gex_regime="positive", news_score=5.0,
    ))
    assert d.bias == "neutral"
    assert d.environment == "consolidation"
    assert "LVN/HVN" in d.playbook


def test_positive_gamma_directional_is_mean_reversion():
    d = evaluate_regime(base_inputs(gex_regime="positive"))
    assert d.bias == "long"
    assert d.environment == "mean_reversion"
    assert "do not chase breakouts" in d.playbook


def test_event_risk_no_trade():
    d = evaluate_regime(base_inputs(red_folder=True, kronos_respect_score=35.0))
    assert d.bias == "no_trade"
    assert d.environment == "event_risk"
    assert "No-trade" in d.playbook
    assert any("Red Folder" in r for r in d.reasons)


def test_red_folder_with_strong_respect_still_event_risk_env():
    d = evaluate_regime(base_inputs(red_folder=True, kronos_respect_score=85.0))
    assert d.environment == "event_risk"
    # bias may stay directional with high respect, but confidence is docked
    assert any("Red Folder" in t for t in d.confidence_terms)


def test_conflicting_signals_no_trade():
    # Kronos up + low respect + bearish news + positive gamma (spec example)
    d = evaluate_regime(base_inputs(
        kronos_respect_score=30.0, news_score=-50.0, gex_regime="positive",
    ))
    assert d.bias == "no_trade"
    assert any("not following the forecast" in r for r in d.reasons)


def test_opposing_news_downgrades_bias():
    d = evaluate_regime(base_inputs(news_score=-60.0))
    assert d.bias == "neutral"
    assert any("opposes the Kronos direction" in r for r in d.reasons)


def test_inverted_forecast_reversal_risk():
    d = evaluate_regime(base_inputs(forecast_inverted=True, kronos_respect_score=15.0))
    assert d.bias == "no_trade"
    assert d.environment == "reversal_risk"
    assert any("fade warning" in r.lower() for r in d.reasons)


def test_daily_hourly_divergence_penalized():
    agree = evaluate_regime(base_inputs())
    diverge = evaluate_regime(base_inputs(kronos_daily_direction="DOWN"))
    assert diverge.confidence < agree.confidence
    assert any("opposes hourly" in t for t in diverge.confidence_terms)


def test_near_flip_caution():
    d = evaluate_regime(base_inputs(gex_regime="near_flip", distance_to_flip_pct=0.1))
    assert any("near gamma flip" in t for t in d.confidence_terms)
    assert "CAUTION" in d.playbook


def test_no_forecast_no_trade():
    d = evaluate_regime(RegimeInputs())
    assert d.bias == "no_trade"
    assert any("No Kronos forecast" in r for r in d.reasons)


def test_confidence_bounds_and_terms_disclosed():
    d = evaluate_regime(base_inputs())
    assert 0 <= d.confidence <= 100
    assert d.confidence_terms  # every adjustment listed


# ---------------- alerts ----------------

def make_state(**kw) -> TerminalState:
    defaults = dict(
        price=6000.0, gamma_flip=5950.0, call_wall=6100.0, put_wall=5800.0,
        gex_regime="positive", respect_score=75.0, forecast_failing=False,
        forecast_inverted=False, news_score=10.0, red_folder=False,
        bias="neutral", environment="consolidation",
    )
    defaults.update(kw)
    return TerminalState(**defaults)


def alert_types(alerts):
    return [a.alert_type for a in alerts]


def test_no_change_no_alerts():
    s = make_state()
    assert check_alert_conditions(s, s) == []


def test_gex_regime_change_alert():
    out = check_alert_conditions(make_state(), make_state(gex_regime="negative"))
    assert "gex_regime_changed" in alert_types(out)


def test_gamma_flip_cross_alert():
    out = check_alert_conditions(make_state(price=5960.0), make_state(price=5940.0))
    assert "price_crossed_gamma_flip" in alert_types(out)


def test_wall_approach_fires_once():
    prev = make_state(price=6000.0)
    near = make_state(price=6090.0)  # within 0.25% of 6100 call wall
    first = check_alert_conditions(prev, near)
    assert "price_approaching_call_wall" in alert_types(first)
    # still near on the next tick -> no duplicate
    again = check_alert_conditions(near, make_state(price=6092.0))
    assert "price_approaching_call_wall" not in alert_types(again)


def test_respect_threshold_crossings():
    out60 = check_alert_conditions(make_state(respect_score=70.0), make_state(respect_score=55.0))
    assert "respect_below_60" in alert_types(out60)
    out40 = check_alert_conditions(make_state(respect_score=55.0), make_state(respect_score=35.0))
    assert "respect_below_40" in alert_types(out40)
    # crossing both at once fires both
    both = check_alert_conditions(make_state(respect_score=70.0), make_state(respect_score=30.0))
    assert {"respect_below_60", "respect_below_40"} <= set(alert_types(both))


def test_forecast_failure_and_inversion_alerts():
    out = check_alert_conditions(
        make_state(), make_state(forecast_failing=True, forecast_inverted=True)
    )
    assert {"kronos_forecast_failed", "kronos_forecast_inverted"} <= set(alert_types(out))


def test_news_spike_and_red_folder():
    out = check_alert_conditions(
        make_state(news_score=0.0), make_state(news_score=-45.0, red_folder=True)
    )
    assert {"news_risk_spike", "red_folder_detected"} <= set(alert_types(out))


def test_bias_and_regime_transition_alerts():
    out = check_alert_conditions(
        make_state(bias="neutral", environment="consolidation"),
        make_state(bias="long", environment="continuation"),
    )
    assert {"bias_actionable", "regime_changed"} <= set(alert_types(out))
    out2 = check_alert_conditions(make_state(bias="long"), make_state(bias="no_trade"))
    assert "no_trade_triggered" in alert_types(out2)


def test_first_evaluation_no_prev():
    out = check_alert_conditions(None, make_state(red_folder=True))
    assert "red_folder_detected" in alert_types(out)

"""Kronos Respect Score composite tests."""
import pytest

from app.engine.kalman import kronos_guided_kalman_filter
from app.engine.respect import compute_respect_score, label_for


def run(path, obs, width=10.0, **kw):
    upper = [p + width for p in path]
    lower = [p - width for p in path]
    return kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower, **kw)


def test_perfect_respect_scores_high():
    path = [5000.0 + 5 * i for i in range(12)]
    obs = [p + 0.5 for p in path]
    rs = compute_respect_score(run(path, obs, width=15.0))
    assert rs.score >= 90
    assert rs.label == "highly_respected"
    assert rs.forecast_status == "strong_respect"
    assert rs.direction_score == pytest.approx(25.0)
    assert rs.band_respect_score == pytest.approx(20.0)
    assert rs.invalidation_count == 0


def test_inverted_forecast_scores_low_and_flags():
    path = [5000.0 + 5 * i for i in range(12)]
    obs = [5000.0 - 6 * i for i in range(12)]
    rs = compute_respect_score(run(path, obs))
    assert rs.score < 30
    assert rs.forecast_status == "inverted_fade_warning"
    assert rs.direction_score == pytest.approx(0.0)
    assert rs.correlation_score < 5


def test_components_sum_to_total():
    path = [5000.0 + 2 * i for i in range(15)]
    obs = [5000.0 + 2 * i + ((-1) ** i) * 3 for i in range(15)]
    rs = compute_respect_score(run(path, obs))
    total = (
        rs.direction_score + rs.correlation_score + rs.band_respect_score
        + rs.kalman_residual_score + rs.invalidation_score
    )
    assert rs.score == pytest.approx(total, abs=0.11)  # rounding to 1dp


def test_extra_invalidations_penalize():
    path = [5000.0 + 5 * i for i in range(12)]
    obs = [p + 0.5 for p in path]
    base = compute_respect_score(run(path, obs, width=15.0))
    penalized = compute_respect_score(run(path, obs, width=15.0), extra_invalidations=2)
    assert penalized.invalidation_score == base.invalidation_score - 6
    assert penalized.invalidation_count == base.invalidation_count + 2
    assert penalized.score < base.score


def test_invalidation_floor_zero():
    path = [5000.0] * 6
    obs = [5000.0] * 6
    rs = compute_respect_score(run(path, obs), extra_invalidations=10)
    assert rs.invalidation_score == 0.0


def test_no_observations_neutral():
    path = [5000.0, 5001.0, 5002.0]
    out = kronos_guided_kalman_filter(path, [None, None, None])
    rs = compute_respect_score(out)
    assert 40 <= rs.score <= 59  # all components neutral -> mixed bucket
    assert rs.label == "mixed"


def test_label_boundaries():
    assert label_for(80) == "highly_respected"
    assert label_for(79.9) == "respected_noisy"
    assert label_for(60) == "respected_noisy"
    assert label_for(59.9) == "mixed"
    assert label_for(40) == "mixed"
    assert label_for(39.9) == "weak_respect"
    assert label_for(20) == "weak_respect"
    assert label_for(19.9) == "failing_or_inverted"
    assert label_for(0) == "failing_or_inverted"


def test_explanations_present():
    path = [5000.0 + i for i in range(10)]
    obs = [p for p in path]
    rs = compute_respect_score(run(path, obs))
    for key in ("direction", "correlation", "band_respect", "kalman_residual", "invalidation", "labels"):
        assert key in rs.explanation

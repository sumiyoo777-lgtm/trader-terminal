"""Kronos-guided Kalman filter tests — every scenario from the spec:
flat/flat, rising/rising, rising/falling, noisy-same-direction, price
outside bands, persistent residual drift, sudden news shock, slider behavior.
"""
import math

import pytest

from app.engine.kalman import kronos_guided_kalman_filter


def make_bands(path, width):
    return [p + width for p in path], [p - width for p in path]


def test_flat_forecast_flat_price():
    path = [5000.0] * 10
    obs = [5000.0] * 10
    upper, lower = make_bands(path, 10.0)
    out = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower)
    assert out.tracking_error == pytest.approx(0.0, abs=1e-9)
    assert out.failure_warning is False
    assert out.inverted is False
    assert out.band_respect_fraction == 1.0
    # zero residuals -> full Kalman respect contribution
    assert out.respect_contribution == pytest.approx(20.0)
    # flat forecast has no direction to agree with
    assert out.step_agreement is None
    assert out.net_agreement is None


def test_rising_kronos_rising_price():
    path = [5000.0 + 5 * i for i in range(10)]
    obs = [5000.0 + 5 * i + 0.5 for i in range(10)]
    upper, lower = make_bands(path, 12.0)
    out = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower)
    assert out.step_agreement == 1.0
    assert out.net_agreement is True
    assert out.direction_agreement == 1.0
    assert out.failure_warning is False
    assert out.inverted is False
    assert out.respect_contribution > 18


def test_rising_kronos_falling_price():
    path = [5000.0 + 5 * i for i in range(12)]
    obs = [5000.0 - 6 * i for i in range(12)]
    upper, lower = make_bands(path, 10.0)
    out = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower)
    assert out.net_agreement is False
    assert out.step_agreement == 0.0
    assert out.inverted is True
    assert out.failure_warning is True  # diverges far past the band
    assert out.respect_contribution < 8


def test_noisy_price_same_direction():
    path = [5000.0 + 4 * i for i in range(20)]
    noise = [3, -2, 4, -3, 2, -4, 3, -2, 1, -1, 4, -3, 2, -2, 3, -4, 2, -1, 3, -2]
    obs = [p + n for p, n in zip(path, noise)]
    upper, lower = make_bands(path, 20.0)
    out = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower)
    assert out.net_agreement is True
    assert out.failure_warning is False
    assert out.inverted is False
    assert out.band_respect_fraction == 1.0
    assert out.respect_contribution > 12


def test_price_outside_forecast_bands():
    path = [5000.0] * 10
    obs = [5000.0, 5001.0, 5030.0, 5032.0, 5031.0, 5033.0, 5034.0, 5032.0, 5035.0, 5036.0]
    upper, lower = make_bands(path, 10.0)  # sigma = 5 -> z of +30 is 6
    out = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower)
    assert out.max_abs_z > 2.5
    assert out.band_respect_fraction < 0.5
    assert out.failure_warning is True
    assert out.violation_episodes >= 1


def test_persistent_residual_drift():
    # price drifts away slowly: small residuals at first, then persistent breach
    path = [5000.0] * 20
    obs = [5000.0 + 1.2 * i for i in range(20)]
    upper, lower = make_bands(path, 8.0)  # sigma = 2
    out = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower)
    assert out.failure_warning is True
    assert out.max_violation_run >= 3
    # tracking error reflects the drift magnitude
    assert out.tracking_error > 5


def test_sudden_news_shock():
    # forecast respected, then a single violent gap that persists
    path = [5000.0] * 12
    obs = [5000.0] * 6 + [4950.0] * 6
    upper, lower = make_bands(path, 12.0)  # sigma = 6 -> shock z ~ -8.3
    out = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower)
    assert out.failure_warning is True
    assert out.max_abs_z > 5
    # before the shock everything was inside the band
    assert 0.4 < out.band_respect_fraction < 0.6


def test_slider_zero_hugs_kronos_slider_100_follows_price():
    path = [5000.0] * 10
    obs = [5020.0] * 10  # constant 20-pt deviation
    upper, lower = make_bands(path, 20.0)

    low = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower, slider=0)
    mid = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower, slider=50)
    high = kronos_guided_kalman_filter(path, obs, band_upper=upper, band_lower=lower, slider=100)

    # final estimates: slider 0 stays near Kronos (5000), slider 100 near price (5020)
    assert low.estimate[-1] < mid.estimate[-1] < high.estimate[-1]
    assert low.estimate[-1] < 5008
    assert high.estimate[-1] > 5018
    # gain ordering matches the trust mapping
    assert low.gains[-1] < mid.gains[-1] < high.gains[-1]


def test_partial_observations_future_path_unfiltered():
    path = [5000.0 + i for i in range(10)]
    obs = [5000.0, 5001.5, 5002.0] + [None] * 7
    out = kronos_guided_kalman_filter(path, obs)
    assert out.estimate[2] is not None
    assert out.estimate[5] is None
    assert out.explanation["observed_points"] == 3


def test_no_observations_yet():
    path = [5000.0, 5001.0]
    out = kronos_guided_kalman_filter(path, [None, None])
    assert out.tracking_error is None
    assert out.failure_warning is False
    assert "no realized observations" in out.explanation["note"]


def test_misaligned_inputs_raise():
    with pytest.raises(ValueError):
        kronos_guided_kalman_filter([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        kronos_guided_kalman_filter([], [])


def test_default_sigma_used_without_bands():
    path = [5000.0] * 5
    obs = [5000.0] * 5
    out = kronos_guided_kalman_filter(path, obs, default_sigma_pct=0.002)
    assert out.sigma[0] == pytest.approx(10.0)  # 0.2% of 5000

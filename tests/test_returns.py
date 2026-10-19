import math

import numpy as np
import pytest

from src.forecast import metrics, returns


def test_horizon_log_returns_basic_and_tail_nan():
    p = np.array([100.0, 110.0, 121.0, 133.1])
    r = returns.horizon_log_returns(p, 1, assume_aligned=True)
    assert np.allclose(r[:3], math.log(1.1))
    assert np.isnan(r[-1])


def test_horizon_log_returns_nonpositive_price_is_nan():
    p = np.array([20.0, -37.63, 10.0, 12.0])  # kiểu WTI tháng 4/2020
    r = returns.horizon_log_returns(p, 1, assume_aligned=True)
    assert np.isnan(r[0]) and np.isnan(r[1])
    assert r[2] == pytest.approx(math.log(1.2))


def test_target_does_not_change_when_future_appended():
    rng = np.random.default_rng(0)
    p = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    short = returns.horizon_log_returns(p[:200], 3, assume_aligned=True)
    long = returns.horizon_log_returns(p, 3, assume_aligned=True)
    assert np.allclose(short[:197], long[:197])


def test_quantiles_to_prices_example():
    out = returns.quantiles_to_prices(
        2000, {0.1: math.log(0.979), 0.5: math.log(1.003), 0.9: math.log(1.026)}
    )
    assert out[0.1] == pytest.approx(1958)
    assert out[0.9] == pytest.approx(2052)
    assert out[0.1] < out[0.5] < out[0.9]


@pytest.mark.parametrize("bad", [0, -1, -1.5, math.nan, math.inf, -math.inf, True, False, "100"])
def test_quantiles_to_prices_rejects_invalid_price_now(bad):
    with pytest.raises(ValueError, match="price_now"):
        returns.quantiles_to_prices(bad, {0.1: -0.02, 0.5: 0.0, 0.9: 0.02})


def test_quantiles_to_prices_valid_price_unchanged():
    q = np.array([-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03])
    for p in (71.32, 2000, np.float64(31.5), np.int64(25)):
        np.testing.assert_allclose(returns.quantiles_to_prices(p, q), float(p) * np.exp(q))


def test_prob_up_interpolates_and_clips():
    assert returns.prob_up({0.1: -0.02, 0.5: 0.0, 0.9: 0.02}) == pytest.approx(0.5)
    p = returns.prob_up({0.1: -0.021, 0.5: 0.003, 0.9: 0.026})
    assert 0.5 < p < 0.9
    assert returns.prob_up({0.1: 0.01, 0.5: 0.02, 0.9: 0.03}) == pytest.approx(0.9)
    assert returns.prob_up({0.1: -0.03, 0.5: -0.02, 0.9: -0.01}) == pytest.approx(0.1)


def test_vnd_conversion():
    assert returns.usd_oz_to_vnd_luong(1.0, 1.0) == pytest.approx(37.5 / 31.1034768)
    assert returns.usd_to_vnd(10, 25000) == 250000


def test_metrics_for_returns():
    y = np.array([0.01, -0.02, 0.005, -0.001])
    assert metrics.sign_accuracy(y, y) == 1.0
    assert metrics.mase_returns(y, y, train_returns=y) == 0.0
    assert metrics.mase_returns(y, np.zeros_like(y), train_returns=y) == pytest.approx(1.0)
    assert metrics.pinball_loss(y, y, 0.9) == 0.0
    assert metrics.brier_score(np.full(4, 0.5), y) == pytest.approx(0.25)
    assert not hasattr(metrics, "mape")

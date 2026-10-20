"""Unit tests for ADR-0008 metrics. No network, price data or AWS required."""

import numpy as np
import pytest

from src.eval import metrics as M


def _q(rows):
    return np.asarray(rows, dtype=float)


def test_pinball_loss_one_tau_hand_calculation():
    y = np.array([2.0, -1.0])
    q = np.array([1.0, 0.0])
    # tau=0.25: 0.25*(2-1)=0.25; (0.25-1)*(-1-0)=0.75
    assert M.pinball_loss(y, q, 0.25) == pytest.approx(0.5)


def test_mean_pinball_uses_all_seven_quantiles_and_all_rows():
    y = np.array([0.0, 1.0])
    q = _q([[0.0] * 7, [0.0] * 7])
    # first origin loss=0; second origin mean(tau)=0.5
    assert M.mean_pinball_loss(y, q) == pytest.approx(0.25)


def test_pinball_skill_perfect_equal_and_worse():
    y = np.array([-1.0, 1.0])
    perfect = np.repeat(y[:, None], 7, axis=1)
    baseline = np.zeros((2, 7))
    awful = np.full((2, 7), 5.0)
    assert M.pinball_skill(y, perfect, baseline) == pytest.approx(1.0)
    assert M.pinball_skill(y, baseline, baseline) == pytest.approx(0.0)
    assert M.pinball_skill(y, awful, baseline) < 0


def test_pinball_skill_zero_baseline_loss_returns_nan():
    y = np.array([1.0, 2.0])
    baseline = np.repeat(y[:, None], 7, axis=1)
    assert np.isnan(M.pinball_skill(y, np.zeros((2, 7)), baseline))


def test_quantiles_must_be_normalized_upstream_not_silently_repaired():
    y = np.array([0.0])
    crossing = _q([[0.2, 0.1, 0.3, 0.4, 0.5, 0.6, 0.7]])
    with pytest.raises(ValueError, match="normalize once upstream"):
        M.mean_pinball_loss(y, crossing)
    with pytest.raises(ValueError, match="quantiles must be"):
        M.mean_pinball_loss(y, np.zeros((1, 3)))
    with pytest.raises(ValueError, match="finite"):
        M.mean_pinball_loss(y, _q([[np.nan] * 7]))


def test_quantile_hit_rates_exact_values():
    y = np.array([0.0, 1.0])
    q = _q([[0.0] * 7, [0.0] * 7])
    hits = M.quantile_hit_rates(y, q)
    assert list(hits) == list(M.QUANTILE_LEVELS)
    assert all(rate == pytest.approx(0.5) for rate in hits.values())


def test_coverage_width_interval_score_hand_calculation():
    y = np.array([-2.0, 0.0, 3.0])
    low = np.array([-1.0] * 3)
    high = np.array([1.0] * 3)
    assert M.coverage_80(y, low, high) == pytest.approx(1 / 3)
    assert M.width_80(low, high) == pytest.approx(2.0)
    # 12 (below lower), 2 (inside), 22 (above upper) => 12 mean
    assert M.interval_score_80(y, low, high) == pytest.approx(12.0)
    with pytest.raises(ValueError, match="q10"):
        M.width_80(high, low)


def test_brier_score_and_skill_against_empirical_and_half_baselines():
    y = np.array([0.1, -0.2])
    p = np.array([0.75, 0.25])
    p_half = np.array([0.5, 0.5])
    assert M.brier_score(p, y) == pytest.approx(0.0625)
    assert M.brier_skill(p, y, p_half) == pytest.approx(0.75)
    assert M.brier_skill_vs_half(p, y) == pytest.approx(0.75)
    assert M.brier_skill(p_half, y, p_half) == pytest.approx(0.0)
    assert M.up_rate(y) == pytest.approx(0.5)


def test_brier_skill_zero_baseline_returns_nan_not_inf():
    y = np.array([0.01, -0.01])
    perfect_p = np.array([1.0, 0.0])
    assert np.isnan(M.brier_skill(np.array([0.5, 0.5]), y, perfect_p))
    with pytest.raises(ValueError, match="prob_up"):
        M.brier_score(np.array([-0.01, 0.5]), y)


def test_interval_boundaries_and_zero_width_are_inclusive():
    y = np.array([-1.0, 1.0, 0.0])
    lower = np.array([-1.0, -1.0, 0.0])
    upper = np.array([1.0, 1.0, 0.0])
    assert M.coverage_80(y, lower, upper) == 1.0
    assert M.width_80(lower, upper) == pytest.approx(4 / 3)
    assert M.interval_score_80(y, lower, upper) == pytest.approx(4 / 3)


def test_brier_zero_return_is_not_up_and_probability_endpoints_are_valid():
    y = np.array([0.0, -1.0, 1.0])
    assert M.brier_score([0.0, 0.0, 1.0], y) == 0.0
    assert M.brier_score([1.0, 1.0, 0.0], y) == 1.0
    assert M.brier_skill_vs_half([1.0, 1.0, 0.0], y) == -3.0
    assert M.up_rate(y) == pytest.approx(1 / 3)


def test_sign_accuracy_drops_true_or_predicted_zeros():
    actual = np.array([0.0, 1.0, -1.0, 2.0, -3.0])
    q50 = np.array([1.0, 0.0, -2.0, -1.0, 0.0])
    # eligible: only indices 2 and 3; one hit out of two
    assert M.sign_accuracy(actual, q50) == pytest.approx(0.5)
    assert np.isnan(M.sign_accuracy(np.array([0.0, 1.0]), np.zeros(2)))


def test_mae_ratio_and_mase_returns_zero_denominator():
    y = np.zeros(3)
    assert np.isnan(M.mae_ratio_vs_naive(y, np.ones(3), np.zeros(3)))
    assert np.isnan(M.mase_returns(np.ones(3), np.ones(3), np.zeros(3)))
    # A conventional ratio and training-based scale are unchanged
    actual = np.array([-2.0, 2.0])
    assert M.mae_ratio_vs_naive(actual, np.zeros(2), np.zeros(2)) == pytest.approx(1.0)
    assert M.mase_returns(actual, np.zeros(2), np.array([-2.0, 2.0])) == pytest.approx(1.0)


def test_diebold_mariano_accepts_losses_not_errors_and_direction():
    rng = np.random.default_rng(17)
    loss_a = rng.uniform(0.01, 0.04, 200)
    loss_b = rng.uniform(0.10, 0.20, 200)
    stat, p = M.diebold_mariano(loss_a, loss_b, h=1)
    assert stat < 0 and 0 <= p < 0.05
    reversed_stat, reversed_p = M.diebold_mariano(loss_b, loss_a, h=1)
    assert reversed_stat == pytest.approx(-stat)
    assert reversed_p == pytest.approx(p)


def test_dm_hac_and_undefined_cases():
    a = np.arange(30.0) + 1.0
    b = np.zeros(30)
    stat, p = M.diebold_mariano(a, b, h=3, hac_lag=2)
    assert np.isfinite(stat) and 0 <= p <= 1
    with pytest.raises(ValueError, match="hac_lag"):
        M.diebold_mariano(a, b, h=3, hac_lag=1)
    stat, p = M.diebold_mariano(np.ones(30), np.zeros(30), h=1)
    assert np.isnan(stat) and np.isnan(p)
    stat, p = M.diebold_mariano(np.array([1.0]), np.array([2.0]), h=1)
    assert np.isnan(stat) and np.isnan(p)


def test_dm_hac_hln_two_sided_matches_independent_reference():
    """Reference: manual uniform weights, HLN factor, two-sided Student t."""
    from scipy.stats import t as student_t

    rng = np.random.default_rng(123)
    n, h, lag = 80, 4, 3
    loss_a = rng.normal(loc=0.1, scale=0.07, size=n)
    loss_b = rng.normal(loc=0.15, scale=0.09, size=n)
    diff = loss_a - loss_b
    z = diff - diff.mean()
    cov = [float(np.sum(z[k:] * z[: n - k]) / n) for k in range(lag + 1)]
    lrv = cov[0] + 2 * sum(cov[1:])
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    expected_stat = float(diff.mean() / np.sqrt(lrv / n) * hln)
    expected_p = float(2 * student_t.sf(abs(expected_stat), n - 1))

    actual_stat, actual_p = M.diebold_mariano(loss_a, loss_b, h=h, hac_lag=lag)
    assert actual_stat == pytest.approx(expected_stat, rel=1e-12)
    assert actual_p == pytest.approx(expected_p, rel=1e-12)


@pytest.mark.parametrize(("loss_a", "loss_b"), [(0.1, 0.0), (0.0, 0.1)])
def test_dm_constant_decimal_loss_difference_is_undefined(loss_a, loss_b):
    stat, p = M.diebold_mariano(np.full(30, loss_a), np.full(30, loss_b))
    assert np.isnan(stat) and np.isnan(p)


def test_holm_adjust_preserves_nan_and_monotonicity():
    res = M.holm_adjust(np.array([0.03, 0.01, 0.04, np.nan]))
    np.testing.assert_allclose(res[:3], np.array([0.09, 0.04, 0.09]))
    assert np.isnan(res[-1])
    with pytest.raises(ValueError, match="p_values"):
        M.holm_adjust(np.array([0.01, np.inf]))


def test_block_bootstrap_ci_reproducible_and_uses_common_time_indices():
    # Paired columns, so the within-origin difference is exactly 1.0.
    data = np.column_stack([np.arange(40.0), np.arange(40.0) + 1.0])

    def stat(sampled):
        return np.mean(sampled[:, 1] - sampled[:, 0])

    kw = {"block_length": 5, "n_resamples": 200, "confidence_level": 0.95, "seed": 42}
    a = M.block_bootstrap_ci(data, stat, **kw)
    b = M.block_bootstrap_ci(data, stat, **kw)
    assert a == pytest.approx((1.0, 1.0))
    assert b == pytest.approx(a)
    with pytest.raises(ValueError, match="block_length"):
        M.block_bootstrap_ci(data, stat, block_length=0)


def test_no_samples_return_nan_or_empty_hits():
    assert np.isnan(M.mean_pinball_loss(np.empty(0), np.empty((0, 7))))
    assert all(np.isnan(x) for x in M.quantile_hit_rates([], np.empty((0, 7))).values())
    assert np.isnan(M.up_rate(np.empty(0)))


def test_block_bootstrap_ci_resamples_contiguous_time_blocks():
    n = 24
    block_length = 4
    values = np.arange(n, dtype=float)
    seen = []

    def inspect_blocks(sampled):
        # The 4 observations within each sampled block must be consecutive,
        # with wraparound from n-1 to 0 permitted (circular bootstrap).
        for start in range(0, n, block_length):
            block = sampled[start : start + block_length]
            np.testing.assert_array_equal(np.diff(block) % n, np.ones(block_length - 1))
        seen.append(sampled.copy())
        return np.mean(sampled)

    low, high = M.block_bootstrap_ci(
        values,
        inspect_blocks,
        block_length=block_length,
        n_resamples=100,
        seed=17,
    )
    assert len(seen) == 100
    assert any(not np.array_equal(sample, values) for sample in seen)
    assert np.isfinite(low) and np.isfinite(high) and low <= np.mean(values) <= high


def test_block_bootstrap_ci_non_degenerate_mean():
    rng = np.random.default_rng(12)
    values = rng.normal(loc=0.2, scale=1.0, size=80)
    low, high = M.block_bootstrap_ci(
        values,
        np.mean,
        block_length=6,
        n_resamples=400,
        confidence_level=0.95,
        seed=9,
    )
    assert low < np.mean(values) < high
    assert high > low


def test_block_bootstrap_ci_does_not_hide_non_finite_resamples():
    calls = 0

    def partly_undefined(sampled):
        nonlocal calls
        calls += 1
        return float("nan") if calls == 3 else float(np.mean(sampled))

    low, high = M.block_bootstrap_ci(
        np.arange(24.0), partly_undefined, block_length=4, n_resamples=20, seed=7
    )
    assert calls == 20
    assert np.isnan(low) and np.isnan(high)


def test_metrics_reject_unfiltered_scalar_or_nan_inputs():
    with pytest.raises(ValueError, match="aligned 1-D"):
        M.brier_score(0.5, np.array([0.01]))
    with pytest.raises(ValueError, match="finite"):
        M.brier_score(np.array([0.5, np.nan]), np.array([0.01, -0.02]))
    with pytest.raises(ValueError, match="finite"):
        M.sign_accuracy(np.array([0.01, np.nan]), np.array([0.02, -0.03]))


def test_naive_ratio_and_direction():
    y_true = np.array([101.0, 99.0, 102.0])
    last = np.array([100.0, 100.0, 100.0])
    assert M.mae_ratio_vs_naive(y_true, last, last) == 1.0
    assert M.sign_accuracy(y_true - last, y_true - last) == 1.0


def test_diebold_mariano_prefers_smaller_losses():
    rng = np.random.default_rng(2)
    losses_a = rng.uniform(0.05, 0.10, 300)
    losses_b = rng.uniform(0.15, 0.25, 300)
    stat, p = M.diebold_mariano(losses_a, losses_b, h=1)
    assert stat < 0 and p < 0.05


def test_metrics_for_returns():
    y = np.array([0.01, -0.02, 0.005, -0.001])
    assert M.sign_accuracy(y, y) == 1.0
    assert M.mase_returns(y, y, train_returns=y) == 0.0
    assert M.mase_returns(y, np.zeros_like(y), train_returns=y) == pytest.approx(1.0)
    assert M.pinball_loss(y, y, 0.9) == 0.0
    assert M.brier_score(np.full(4, 0.5), y) == pytest.approx(0.25)
    assert not hasattr(M, "mape")


@pytest.mark.parametrize(
    "y,q,expected",
    [
        ([0.0, 1.0], [[0.0] * 7, [0.0] * 7], [0.0, 0.5]),
        ([0.0], [[-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03]], [0.012 / 7]),
        ([-1.0], [[0.0] * 7], [0.5]),
    ],
)
def test_pinball_per_origin_hand_values(y, q, expected):
    result = M.pinball_loss_per_origin(y, q)
    assert result.shape == (len(y),)
    np.testing.assert_allclose(result, expected)
    assert result.mean() == pytest.approx(M.mean_pinball_loss(y, q))


@pytest.mark.parametrize(
    "y,q",
    [
        (0.0, np.zeros((1, 7))),
        ([0.0], np.zeros((1, 6))),
        ([0.0, 1.0], np.zeros((1, 7))),
        ([[0.0]], np.zeros((1, 7))),
        ([np.nan], np.zeros((1, 7))),
        ([np.inf], np.zeros((1, 7))),
        ([0.0], [[np.nan] * 7]),
        ([0.0], [[np.inf] * 7]),
        ([0.0], [[1, 0, 2, 3, 4, 5, 6]]),
    ],
)
def test_pinball_per_origin_rejects_invalid_without_filtering(y, q):
    with pytest.raises(ValueError):
        M.pinball_loss_per_origin(y, q)


def test_pinball_per_origin_empty():
    result = M.pinball_loss_per_origin([], np.empty((0, 7)))
    assert isinstance(result, np.ndarray)
    assert result.shape == (0,)
    assert result.dtype.kind == "f"


@pytest.mark.parametrize(
    "flags,expected",
    [
        ([False, False, True, False], 0.25),
        ([False, False], 0),
        ([True, True], 1),
        (np.array([[True, False], [False, True]]), 0.5),
    ],
)
def test_crossing_rate_boolean_flags(flags, expected):
    assert M.crossing_rate(flags) == expected


def test_crossing_empty():
    assert np.isnan(M.crossing_rate([]))
    assert np.isnan(M.crossing_rate(np.empty((0, 7), dtype=bool)))


@pytest.mark.parametrize(
    "flags", [[0, 1], [False, np.nan], [True, None], ["False"], np.array([True], dtype=object)]
)
def test_crossing_rejects_non_boolean_flags(flags):
    with pytest.raises(ValueError, match="boolean"):
        M.crossing_rate(flags)


@pytest.mark.parametrize(
    "y,pred", [([np.nan], [0]), ([0], [np.inf]), ([0, 1], [0]), ([[0]], [[0]]), (0, [0])]
)
def test_mae_and_ratio_reject_bad_model_pairs(y, pred):
    with pytest.raises(ValueError):
        M.mae(y, pred)
    with pytest.raises(ValueError):
        M.mae_ratio_vs_naive(y, pred, np.zeros(np.asarray(y).shape))


@pytest.mark.parametrize("naive", [[np.nan], [np.inf], [0, 0], [[0]]])
def test_mae_ratio_rejects_bad_baseline_even_zero_model_error(naive):
    with pytest.raises(ValueError):
        M.mae_ratio_vs_naive([0], [0], naive)


def test_mae_ratio_valid_and_zero_baseline_still_validates_prediction():
    assert M.mae([1, 3], [0, 1]) == 1.5
    assert M.mae_ratio_vs_naive([1, 3], [0, 1], [0, 0]) == 0.75
    with pytest.raises(ValueError):
        M.mae_ratio_vs_naive([0], [np.nan], [0])


@pytest.mark.parametrize("h,lag", [(1, 0), (3, 2), (3, 4)])
def test_dm_uniform_autocorrelated_independent_reference(h, lag):
    from scipy.stats import t

    # Smooth, positively autocorrelated differences with a nonzero mean.
    d = np.sin(np.arange(120) * 0.12) + 0.3
    n = len(d)
    mu = sum(float(v) for v in d) / n
    z = [float(v) - mu for v in d]
    gamma = [sum(z[i] * z[i - k] for i in range(k, n)) / n for k in range(lag + 1)]
    lrv = gamma[0] + 2 * sum(gamma[1:])
    factor = ((n + 1 - 2 * h + h * (h - 1) / n) / n) ** 0.5
    expected = mu / (lrv / n) ** 0.5 * factor
    actual, p = M.diebold_mariano(d + 2, np.full(n, 2.0), h=h, hac_lag=lag)
    assert actual == pytest.approx(expected, rel=1e-12)
    assert p == pytest.approx(2 * t.sf(abs(expected), n - 1), rel=1e-12)
    if lag == h - 1:
        assert M.diebold_mariano(d + 2, np.full(n, 2.0), h=h) == pytest.approx((actual, p))


def test_dm_nonpositive_uniform_variance_and_short_data():
    # Alternating d: gamma0=1, gamma1=-19/20 -> uniform LRV=-0.9.
    a = np.tile([0.0, 2.0], 10)
    for x, y, h in [(a, np.ones(20), 2), ([1, 2], [0, 0], 2)]:
        assert all(np.isnan(v) for v in M.diebold_mariano(x, y, h=h))


@pytest.mark.parametrize("h,lag", [(0, None), (-1, None), (1.5, None), (3, 1), (1, -1), (1, 1.5)])
def test_dm_invalid_horizon_or_lag(h, lag):
    with pytest.raises(ValueError):
        M.diebold_mariano(np.arange(20.0), np.zeros(20), h=h, hac_lag=lag)


def test_dm_rejects_nan_without_dropping():
    with pytest.raises(ValueError, match="finite"):
        M.diebold_mariano([1, np.nan, 2], [0, 0, 0])


@pytest.mark.parametrize("family", [14, 28])
def test_holm_full_family_keeps_nan_slots(family):
    p = np.full(family, np.nan)
    p[:2] = [0.001, 0.002]
    result = M.holm_adjust(p)
    np.testing.assert_allclose(result[:2], [family * 0.001, (family - 1) * 0.002])
    assert np.all(np.isnan(result[2:]))


def test_removed_metrics_are_not_exposed():
    for name in ("mape", "rmse"):
        assert not hasattr(M, name)


@pytest.mark.parametrize(
    "y,q",
    [
        ([np.nan], [0.0]),
        ([0.0], [np.nan]),
        ([np.inf], [0.0]),
        ([0.0], [-np.inf]),
        ([0.0, 1.0], [0.0]),
        ([[0.0], [1.0]], [0.0, 1.0]),
        ([0.0, 1.0], [[0.0], [1.0]]),
        (0.0, [0.0]),
    ],
)
def test_pinball_single_tau_rejects_invalid_pairs_and_broadcasting(y, q):
    with pytest.raises(ValueError):
        M.pinball_loss(y, q, 0.25)


def test_mase_returns_independent_training_length_hand_calculation():
    # Evaluation MAE=(1+2)/2=1.5; train mean absolute return=(1+2+3)/3=2.
    assert M.mase_returns([1.0, -2.0], [0.0, 0.0], [-1.0, 2.0, -3.0]) == 0.75


@pytest.mark.parametrize("train", [[np.nan], [np.inf], [-np.inf], [[1.0]], 1.0])
def test_mase_returns_rejects_invalid_training_series(train):
    with pytest.raises(ValueError):
        M.mase_returns([1.0, -2.0], [0.0, 0.0], train)


@pytest.mark.parametrize(
    "y,pred",
    [
        ([np.nan], [0.0]),
        ([0.0], [np.nan]),
        ([np.inf], [0.0]),
        ([0.0], [-np.inf]),
        ([0.0, 1.0], [0.0]),
        ([[0.0], [1.0]], [0.0, 1.0]),
        ([0.0, 1.0], [[0.0], [1.0]]),
        (0.0, [0.0]),
    ],
)
@pytest.mark.parametrize("train", [[1.0, 2.0, 3.0], [0.0, 0.0, 0.0]])
def test_mase_returns_validates_evaluation_even_with_zero_scale(y, pred, train):
    with pytest.raises(ValueError):
        M.mase_returns(y, pred, train)


def test_mase_returns_zero_scale_with_different_training_length():
    assert np.isnan(M.mase_returns([1.0, -2.0], [0.0, 0.0], [0.0, 0.0, 0.0]))

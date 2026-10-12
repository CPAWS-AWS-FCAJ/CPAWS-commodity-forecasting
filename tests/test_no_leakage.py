"""Guards against look-ahead leakage. These tests must stay green; CI runs them on every PR."""

import numpy as np
import pytest

from src.forecast import metrics as M
from src.forecast.decomposition import CeemdanConfig, causal_imf_windows, split_high_low

CFG = CeemdanConfig(window=128, seq_len=32, n_imfs=6, num_high=2, trials=5, seed=7)


def _series(n=400, seed=0):
    rng = np.random.default_rng(seed)
    base = np.cumsum(rng.normal(0, 1, n)) + 100
    base[300] += 25  # a spike
    return base


def test_causal_features_do_not_change_when_future_is_appended():
    s = _series()
    origins = np.array([200, 250, 299])
    short = causal_imf_windows(s[:300], origins, CFG)
    long = causal_imf_windows(s, origins, CFG)  # same data plus 100 future points incl. a spike
    np.testing.assert_allclose(short, long)


def test_whole_series_decomposition_leaks():
    """Documents WHY the causal version exists: decomposing the whole series makes past
    IMF values depend on future data. Do not 'fix' this test by changing the method."""
    from PyEMD import CEEMDAN

    s = _series()

    def whole(x):
        c = CEEMDAN(trials=5)
        c.noise_seed(7)
        return c(x, max_imf=5)[0]  # first IMF

    past_only = whole(s[:300])[250:290]
    with_future = whole(s)[250:290]
    assert not np.allclose(past_only, with_future)


def test_output_shape_and_split():
    s = _series()
    out = causal_imf_windows(s, np.array([150, 160]), CFG)
    assert out.shape == (2, CFG.seq_len, CFG.n_imfs)
    high, low = split_high_low(out, CFG.num_high)
    assert high.shape[-1] == 2 and low.shape[-1] == 4


def test_rejects_origin_without_enough_history():
    with pytest.raises(ValueError):
        causal_imf_windows(_series(), np.array([50]), CFG)


def test_spike_threshold_is_causal():
    rng = np.random.default_rng(1)
    changes = rng.normal(0, 1, 200)
    before = M.past_rolling_std(changes, 30)[:150]
    changes2 = changes.copy()
    changes2[150:] *= 50  # huge future volatility must not affect earlier thresholds
    after = M.past_rolling_std(changes2, 30)[:150]
    np.testing.assert_allclose(before, after)


def test_naive_ratio_and_direction():
    y_true = np.array([101.0, 99.0, 102.0])
    last = np.array([100.0, 100.0, 100.0])
    assert M.mae_ratio_vs_naive(y_true, last, last) == 1.0
    assert M.sign_accuracy(y_true - last, y_true - last) == 1.0


def test_spike_scores_counts():
    s = M.spike_scores([1, 1, 0, 0], [1, 0, 1, 0])
    assert s["precision"] == 0.5 and s["recall"] == 0.5 and s["false_alarm_rate"] == 0.5


def test_diebold_mariano_prefers_smaller_errors():
    rng = np.random.default_rng(2)
    stat, p = M.diebold_mariano(rng.normal(0, 1, 300), rng.normal(0, 2, 300))
    assert stat < 0 and p < 0.05

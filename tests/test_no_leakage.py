"""Guards against look-ahead leakage. These tests must stay green; CI runs them on every PR."""

import numpy as np
import pytest

from src.forecast.decomposition import (
    CeemdanConfig,
    causal_imf_windows,
    decompose_window,
    fixed_imf_matrix,
    split_high_low,
)

CFG = CeemdanConfig(window=128, keep_last=40, trials=5, seed=7)


def _series(n=400, seed=0):
    rng = np.random.default_rng(seed)
    base = np.cumsum(rng.normal(0, 1, n)) + 100
    base[300] += 25  # a spike
    return base


def _assert_same(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b, strict=True):
        assert x.origin == y.origin and x.n_imf == y.n_imf
        np.testing.assert_array_equal(x.imfs, y.imfs)
        np.testing.assert_array_equal(x.residue, y.residue)


def test_causal_features_do_not_change_when_future_is_appended():
    s = _series()
    origins = np.array([200, 250, 299])
    short = causal_imf_windows(s[:300], origins, CFG)
    long = causal_imf_windows(s, origins, CFG)  # same data plus 100 future points incl. a spike
    _assert_same(short, long)  # IMF thô, residue và n_imf đều không đổi
    np.testing.assert_array_equal(
        fixed_imf_matrix(short, max_imf=3, seq_len=32),
        fixed_imf_matrix(long, max_imf=3, seq_len=32),
    )


def test_same_seed_is_bit_identical():
    s = _series()
    a = decompose_window(s[100:228], CFG, seed_id=227, origin=227)
    b = decompose_window(s[100:228], CFG, seed_id=227, origin=227)
    np.testing.assert_array_equal(a.imfs, b.imfs)
    np.testing.assert_array_equal(a.residue, b.residue)


def test_parallel_processes_match_sequential():
    s = _series()
    origins = np.array([150, 200, 260, 330])
    _assert_same(
        causal_imf_windows(s, origins, CFG, processes=2), causal_imf_windows(s, origins, CFG)
    )


def test_seed_ids_control_noise_not_position():
    s = _series()
    shifted = np.concatenate([[100.0] * 10, s])  # thêm 10 điểm phía trước: origin dịch 10
    a = causal_imf_windows(s, np.array([250]), CFG, seed_ids=np.array([99]))
    b = causal_imf_windows(shifted, np.array([260]), CFG, seed_ids=np.array([99]))
    np.testing.assert_array_equal(a[0].imfs, b[0].imfs)


def test_whole_series_decomposition_leaks():
    """Documents WHY the causal version exists: decomposing the whole series makes past
    IMF values depend on future data. Do not 'fix' this test by changing the method."""
    from PyEMD import CEEMDAN

    s = _series()

    def whole(x):
        c = CEEMDAN(trials=5, parallel=False)
        c.noise_seed(7)
        return c(x, max_imf=5)[0]  # first IMF

    past_only = whole(s[:300])[250:290]
    with_future = whole(s)[250:290]
    assert not np.allclose(past_only, with_future)


def test_raw_format_and_fixed_matrix():
    s = _series()
    out = causal_imf_windows(s, np.array([150, 160, 340]), CFG)
    for w in out:
        assert w.imfs.shape == (w.n_imf, CFG.keep_last) and w.residue.shape == (CFG.keep_last,)
        # IMF + residue tái tạo đúng keep_last điểm cuối của cửa sổ
        np.testing.assert_allclose(w.imfs.sum(axis=0) + w.residue, s[w.origin - 39 : w.origin + 1])
    k = min(w.n_imf for w in out)
    m = fixed_imf_matrix(out, max_imf=k - 1, seq_len=32)
    assert m.shape == (3, 32, k)
    for i, w in enumerate(out):  # cột cuối = residue + phần đuôi; tổng các cột không đổi
        np.testing.assert_allclose(m[i].sum(axis=1), s[w.origin - 31 : w.origin + 1])
        np.testing.assert_array_equal(m[i, :, 0], w.imfs[0, -32:])
    wide = fixed_imf_matrix(out, max_imf=max(w.n_imf for w in out) + 2, seq_len=32)
    assert np.all(wide[:, :, -2] == 0)  # IMF thiếu là 0, residue vẫn ở cột cuối
    high, low = split_high_low(m, 2)
    assert high.shape[-1] == 2 and low.shape[-1] == k - 2
    with pytest.raises(ValueError):
        fixed_imf_matrix(out, max_imf=2, seq_len=CFG.keep_last + 1)


def test_rejects_origin_without_enough_history():
    with pytest.raises(ValueError):
        causal_imf_windows(_series(), np.array([50]), CFG)

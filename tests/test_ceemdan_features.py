"""K3 CEEMDAN features: no leakage, rule A for missing sessions, normalization identity."""

import numpy as np
import pandas as pd
import pytest

from src.data import calendars, storage
from src.features import ceemdan_cache as cc
from src.features.ceemdan_features import (
    ColumnScaler,
    baseline_quantiles,
    ceemdan_inputs,
    ceemdan_samples,
    load_cache,
)
from src.forecast.decomposition import CeemdanConfig

CFG = CeemdanConfig(window=64, trials=5, epsilon=0.005, seed=7, keep_last=40)
K, L = 3, 10
NYSE = calendars.sessions("NYSE")
GAP = pd.Timestamp("2014-02-14")  # một phiên NYSE bị thiếu trong bản giá


def _prices(end="2014-06-30", drop=()):
    dates = calendars.sessions("NYSE", "2013-01-02", "2014-06-30")
    rng = np.random.default_rng(5)
    frame = pd.DataFrame(
        {
            "asset": "gold",
            "date": dates,
            "price": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates)))),
            "source": "yfinance",
            "published_at": (dates + pd.Timedelta(days=1, hours=12)).tz_localize("UTC"),
        }
    )
    keep = (frame["date"] <= pd.Timestamp(end)) & ~frame["date"].isin(pd.DatetimeIndex(drop))
    return frame.loc[keep].reset_index(drop=True)


def _cache(directory, prices, origins):
    st = storage.LocalStorage(directory)
    cc.ensure(st, prices, "gold", CFG, pd.DatetimeIndex(origins))
    return load_cache(st, "gold", CFG, origins.min(), origins.max())


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    prices = _prices()
    origins = calendars.sessions("NYSE", "2014-02-03", "2014-05-30")
    return prices, _cache(tmp_path_factory.mktemp("full"), prices, origins)


def test_values_at_t_do_not_change_when_future_is_appended(tmp_path, full):
    prices_full, cache_full = full
    cut_day = pd.Timestamp("2014-03-31")
    prices_cut = _prices(end=cut_day)
    base = calendars.sessions("NYSE", "2014-02-03", cut_day)
    cache_cut = _cache(tmp_path, prices_cut, base)  # cache dựng chỉ từ dữ liệu ≤ cut_day
    a = ceemdan_inputs(prices_cut, "gold", cache_cut, base, max_imf=K, seq_len=L)
    b = ceemdan_inputs(prices_full, "gold", cache_full, base, max_imf=K, seq_len=L)
    assert a.valid.all()
    np.testing.assert_array_equal(a.X, b.X)  # từng bit
    np.testing.assert_array_equal(a.valid, b.valid)
    pd.testing.assert_frame_equal(a.diag, b.diag)
    qa, oka = baseline_quantiles(prices_cut, "gold", base)
    qb, okb = baseline_quantiles(prices_full, "gold", base)
    assert oka.all()
    np.testing.assert_array_equal(qa, qb)
    np.testing.assert_array_equal(oka, okb)


def test_missing_session_in_last_L_drops_origin_but_older_gap_is_kept(tmp_path):
    prices = _prices(drop=[GAP])
    base = calendars.sessions("NYSE", "2014-02-18", "2014-06-30")
    cache = _cache(tmp_path, prices, base)
    out = ceemdan_inputs(prices, "gold", cache, base, max_imf=K, seq_len=L)
    k = NYSE.get_indexer(base) - NYSE.get_loc(GAP)  # GAP cách t bao nhiêu phiên
    assert out.diag["has_cache_window"].all()

    near = k <= L  # make_windows(L) cần L + 1 giá liên tiếp t−L..t
    assert near.any() and not out.valid[near].any()
    assert (out.diag.loc[near, "input_reason"] == "invalid_input_window").all()
    assert np.isnan(out.X[near]).all()

    assert out.valid[~near].all()
    n_missing = out.diag["n_missing_sessions_decompose"].to_numpy()
    in_window = ~near & (k <= CFG.window - 1)  # 64 dòng kết thúc tại t trải 65 phiên t−64..t
    assert in_window.any() and (n_missing[in_window] == 1).all()
    assert (n_missing[k >= CFG.window] == 0).all()

    gap_day = ceemdan_inputs(prices, "gold", cache, [GAP], max_imf=K, seq_len=L)
    assert not gap_day.valid[0] and not gap_day.diag["has_cache_window"][0]


@pytest.mark.parametrize("max_imf", [2, K, 8])  # gộp phần đuôi vào residue / đệm cột 0
def test_columns_sum_to_relative_price_before_scaling(full, max_imf):
    prices, cache = full
    base = calendars.sessions("NYSE", "2014-02-03", "2014-05-30")
    out = ceemdan_inputs(prices, "gold", cache, base, max_imf=max_imf, seq_len=L)
    assert out.valid.all() and out.X.shape == (len(base), L, max_imf + 1)
    dates, values = cc.asset_series(prices, "gold")
    rows = dates.get_indexer(base)
    p_s = values[rows[:, None] + np.arange(-L + 1, 1)]
    expected = p_s / values[rows][:, None] - 1
    np.testing.assert_allclose(out.X.sum(axis=2), expected, rtol=0, atol=1e-12)
    np.testing.assert_allclose(out.diag["price_t"], values[rows], rtol=0, atol=0)


def test_samples_apply_rule_a_target_boundary(full):
    prices, cache = full
    base = calendars.sessions("NYSE", "2014-03-03", "2014-03-31")
    s = ceemdan_samples(prices, "gold", cache, base, max_imf=K, seq_len=L, period_end="2014-03-31")
    assert s.valid[:-7].all() and not s.valid[-7:].any()  # ngày đích vượt ranh giới
    assert s.diag["target_ok"].all() and s.diag["baseline_ok"].all()
    assert np.isfinite(s.y[s.valid]).all() and np.isfinite(s.baseline[s.valid]).all()
    assert (np.diff(s.baseline[s.valid], axis=-1) >= 0).all()


def test_column_scaler_fits_only_the_given_train_array():
    rng = np.random.default_rng(1)
    train = rng.normal(3, 2, (50, L, 4))
    train[..., 3] = 2.0  # cột hằng: std = 0 → 1
    scaler = ColumnScaler.fit(train)
    np.testing.assert_allclose(scaler.mean, train.mean(axis=(0, 1)))
    assert scaler.std[3] == 1.0
    z = scaler.transform(train)
    np.testing.assert_allclose(z[..., :3].mean(axis=(0, 1)), 0, atol=1e-12)
    np.testing.assert_allclose(z[..., :3].std(axis=(0, 1)), 1, atol=1e-12)
    bad = train.copy()
    bad[0, 0, 0] = np.nan
    with pytest.raises(ValueError):
        ColumnScaler.fit(bad)

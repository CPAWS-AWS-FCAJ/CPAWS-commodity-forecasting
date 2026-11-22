"""Mốc 252 phiên (ADR-0008 mục 4): đúng công thức, nhân quả, bỏ NaN, ngưỡng 200 return."""

import numpy as np
import pandas as pd
import pytest

from src.data import calendars
from src.forecast import baselines as B
from src.forecast import returns as R

Q = R.QUANTILE_LEVELS


def _prices(cal="CME", start="2018-01-02", end="2020-06-30", seed=1) -> pd.Series:
    d = calendars.sessions(cal, start, end)
    rng = np.random.default_rng(seed)
    return pd.Series(60 * np.exp(np.cumsum(rng.normal(0, 0.02, len(d)))), index=d)


def _brute(r: pd.Series, t: pd.Timestamp, h: int):
    """s ∈ [t − 251, t − h] theo vị trí lịch, bỏ NaN."""
    i = r.index.get_loc(t)
    vals = r.iloc[max(i - 251, 0) : i - h + 1].dropna().to_numpy()
    return vals


@pytest.mark.parametrize("h", [1, 3, 7])
def test_matches_brute_force_definition(h):
    p = _prices()
    r = R.horizon_log_returns(p, h, calendar="CME")
    qb = B.quantile_baseline(r, h)
    up = B.up_rate_baseline(r, h)
    for t in r.index[[300, 400, len(r) - 1]]:
        vals = _brute(r, t, h)
        assert len(vals) >= 200
        np.testing.assert_allclose(qb.loc[t].to_numpy(), np.quantile(vals, Q), rtol=0, atol=1e-12)
        assert up[t] == pytest.approx((vals > 0).mean())
    assert list(qb.columns) == list(Q)


@pytest.mark.parametrize("h", [1, 5])
def test_value_at_t_unchanged_when_prices_after_t_change(h):
    p = _prices()
    t = p.index[400]
    base_q = B.quantile_baseline(R.horizon_log_returns(p, h, calendar="CME"), h).loc[t]
    base_u = B.up_rate_baseline(R.horizon_log_returns(p, h, calendar="CME"), h)[t]
    edited = p.copy()
    edited[edited.index > t] *= 1.5  # sửa mọi giá sau t
    extra = calendars.sessions("CME", "2020-07-01", "2020-09-30")
    edited = pd.concat([edited, pd.Series(200.0, index=extra)])  # và nối thêm giá
    r2 = R.horizon_log_returns(edited, h, calendar="CME")
    pd.testing.assert_series_equal(B.quantile_baseline(r2, h).loc[t], base_q)
    assert B.up_rate_baseline(r2, h)[t] == base_u


def test_incomplete_returns_are_not_used():
    h = 5
    p = _prices()
    r = R.horizon_log_returns(p, h, calendar="CME")
    t = r.index[400]
    i = r.index.get_loc(t)
    poisoned = r.copy()
    poisoned.iloc[i - h + 1 : i + 1] = 9.9  # s + h > t: chưa hoàn tất tại t
    pd.testing.assert_series_equal(
        B.quantile_baseline(poisoned, h).loc[t], B.quantile_baseline(r, h).loc[t]
    )
    assert B.up_rate_baseline(poisoned, h)[t] == B.up_rate_baseline(r, h)[t]
    poisoned.iloc[i - h] = 9.9  # s = t − h đã hoàn tất: phải được dùng
    assert B.quantile_baseline(poisoned, h).loc[t, 0.95] != B.quantile_baseline(r, h).loc[t, 0.95]


def test_nan_from_negative_wti_price_is_dropped():
    p = _prices(start="2019-04-01", end="2020-06-30")
    p[pd.Timestamp("2020-04-20")] = -37.63
    r = R.horizon_log_returns(p, 1, calendar="CME")
    assert r[[pd.Timestamp("2020-04-17"), pd.Timestamp("2020-04-20")]].isna().all()
    t = pd.Timestamp("2020-05-15")
    vals = _brute(r, t, 1)
    assert len(vals) == 251 - 2  # 252 − h phiên, bỏ 2 return NaN
    np.testing.assert_allclose(B.quantile_baseline(r, 1).loc[t].to_numpy(), np.quantile(vals, Q))
    assert B.up_rate_baseline(r, 1)[t] == pytest.approx((vals > 0).mean())


def test_fewer_than_200_valid_returns_gives_nan():
    p = _prices()
    r = R.horizon_log_returns(p, 1, calendar="CME")
    qb, up, ok = B.quantile_baseline(r, 1), B.up_rate_baseline(r, 1), B.baseline_valid(r, 1)
    # phiên thứ 200 (vị trí 199) mới có 199 return hoàn tất; vị trí 200 có đủ 200
    assert qb.iloc[199].isna().all() and np.isnan(up.iloc[199]) and not ok.iloc[199]
    assert qb.iloc[200].notna().all() and np.isfinite(up.iloc[200]) and ok.iloc[200]
    holes = r.copy()
    t = r.index[400]
    i = r.index.get_loc(t)
    holes.iloc[i - 251 : i - 251 + 60] = np.nan  # còn 251 − 60 = 191 < 200
    assert B.quantile_baseline(holes, 1).loc[t].isna().all()
    assert np.isnan(B.up_rate_baseline(holes, 1)[t]) and not B.baseline_valid(holes, 1)[t]


def test_constant_baseline_and_bad_inputs():
    idx = pd.date_range("2019-01-01", periods=3)
    c = B.constant_prob_baseline(idx)
    assert (c == 0.5).all() and list(c.index) == list(idx)
    with pytest.raises(TypeError):
        B.quantile_baseline(np.zeros(300), 1)
    with pytest.raises(ValueError):
        B.quantile_baseline(pd.Series(np.zeros(300)), 0)

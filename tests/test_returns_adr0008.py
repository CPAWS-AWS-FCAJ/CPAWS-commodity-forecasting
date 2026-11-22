"""returns.py theo ADR-0008 mục 1–3: target theo lịch, chuẩn hóa phân vị, prob_up, PCHIP."""

import math

import numpy as np
import pandas as pd
import pytest

from src.data import calendars
from src.forecast import returns as R

Q = R.QUANTILE_LEVELS


def _series(cal: str, start: str, end: str, seed: int = 0) -> pd.Series:
    d = calendars.sessions(cal, start, end)
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(d)))), index=d)


# ---------- target theo lịch ----------


def test_missing_middle_row_keeps_h_sessions():
    s = _series("NYSE", "2019-03-01", "2019-04-30")
    cal = s.index
    t, gap = cal[10], cal[11]
    r = R.horizon_log_returns(s.drop(gap), 3, calendar="NYSE")
    # t + 3 là phiên thứ 3 trên lịch (cal[13]), không phải dòng thứ 3 (sẽ là cal[14])
    assert r[t] == pytest.approx(math.log(s[cal[13]] / s[t]))
    assert r[t] != pytest.approx(math.log(s[cal[14]] / s[t]))
    assert r.attrs["n_missing_between"] == 2  # t = cal[9], cal[10] có phiên giữa bị thiếu
    assert np.isnan(r[gap])  # chính phiên thiếu không có target


def test_missing_at_t_plus_h_is_nan():
    s = _series("CME", "2019-03-01", "2019-04-30")
    cal = s.index
    r = R.horizon_log_returns(s.drop(cal[15]), 5, calendar="CME")
    assert np.isnan(r[cal[10]])
    assert np.isfinite(r[cal[9]]) and np.isfinite(r[cal[11]])


def test_rejected_row_is_nan():
    s = _series("NYSE", "2019-03-01", "2019-04-30")
    cal = s.index
    r = R.horizon_log_returns(s, 1, calendar="NYSE", invalid_dates=[cal[20]])
    assert np.isnan(r[cal[19]]) and np.isnan(r[cal[20]])
    assert r[cal[21]] == pytest.approx(math.log(s[cal[22]] / s[cal[21]]))


def test_nonpositive_price_wti_2020_04_20_is_nan():
    s = _series("CME", "2020-04-01", "2020-04-30")
    s[pd.Timestamp("2020-04-20")] = -37.63
    r = R.horizon_log_returns(s, 1, calendar="CME")
    assert np.isnan(r[pd.Timestamp("2020-04-17")])  # đích là ngày giá âm
    assert np.isnan(r[pd.Timestamp("2020-04-20")])  # gốc là ngày giá âm
    assert np.isfinite(r[pd.Timestamp("2020-04-21")])
    r3 = R.horizon_log_returns(s, 3, calendar="CME")
    assert np.isnan(r3[pd.Timestamp("2020-04-15")])  # 15/4 + 3 phiên = 20/4


def test_last_h_sessions_have_no_target_and_future_does_not_change_past():
    s = _series("NYSE", "2019-01-02", "2019-12-31")
    short = R.horizon_log_returns(s.iloc[:200], 7, calendar="NYSE")
    long = R.horizon_log_returns(s, 7, calendar="NYSE")
    assert short.iloc[-7:].isna().all()
    pd.testing.assert_series_equal(short.iloc[:-7], long.iloc[: len(short) - 7])


def test_series_requires_calendar_and_rejects_off_calendar_dates():
    s = _series("NYSE", "2020-04-01", "2020-04-30")
    with pytest.raises(TypeError):
        R.horizon_log_returns(s, 1)  # không cho dịch theo dòng
    with pytest.raises(TypeError):
        R.horizon_log_returns(s, 1, calendar="NYSE", assume_aligned=True)  # chỉ cho mảng
    bad = pd.concat([s, pd.Series([100.0], index=[pd.Timestamp("2020-04-10")])]).sort_index()
    with pytest.raises(ValueError, match="not NYSE sessions"):
        R.horizon_log_returns(bad, 1, calendar="NYSE")  # Good Friday


def test_plain_array_requires_assume_aligned():
    p = np.array([100.0, 110.0, 121.0])
    with pytest.raises(TypeError, match="pd.Series"):
        R.horizon_log_returns(p, 1)
    with pytest.raises(TypeError):
        R.horizon_log_returns(list(p), 1)
    np.testing.assert_allclose(
        R.horizon_log_returns(p, 1, assume_aligned=True)[:2], [math.log(1.1)] * 2
    )


# ---------- chuẩn hóa phân vị ----------


def test_quantile_levels_constant():
    assert Q == (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def test_normalize_quantiles_sorts_and_flags():
    q = np.array([-0.03, -0.02, 0.001, -0.001, 0.01, 0.02, 0.03])
    out, crossed = R.normalize_quantiles(q)
    assert bool(crossed) and np.all(np.diff(out) >= 0)
    assert sorted(q.tolist()) == out.tolist()  # chỉ đổi thứ tự, không đổi giá trị (khác accumulate)
    batch = np.tile(np.linspace(-0.03, 0.03, 7), (3, 7, 1))
    batch[1, 4, [2, 3]] = batch[1, 4, [3, 2]]
    out, crossed = R.normalize_quantiles(batch)
    assert crossed.shape == (3, 7) and crossed.sum() == 1 and crossed[1, 4]
    with pytest.raises(ValueError):
        R.normalize_quantiles(np.array([0.0, np.nan, 0.1]))


# ---------- prob_up ----------

SAMPLE_Q = [-0.0325, -0.0251, -0.0122, 0.0004, 0.0131, 0.0258, 0.0334]  # contract.md, WTI h=1


def test_prob_up_rejects_crossed_until_normalized():
    crossed = [-0.03, -0.02, 0.001, -0.001, 0.01, 0.02, 0.03]
    with pytest.raises(ValueError, match="normalize_quantiles"):
        R.prob_up(crossed)
    with pytest.raises(ValueError):
        R.quantiles_to_prices(70.0, crossed)
    with pytest.raises(ValueError):
        R.prob_up_pchip(crossed)
    fixed, _ = R.normalize_quantiles(crossed)
    assert 0.05 <= R.prob_up(fixed) <= 0.95


def test_prob_up_edges_and_clip():
    assert R.prob_up([0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007]) == pytest.approx(0.95)
    assert R.prob_up([-0.007, -0.006, -0.005, -0.004, -0.003, -0.002, -0.001]) == pytest.approx(
        0.05
    )
    assert R.prob_up([-0.03, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04]) == pytest.approx(0.75)  # 0 = q25
    assert R.prob_up([-0.03, -0.02, 0.0, 0.0, 0.02, 0.03, 0.04]) == pytest.approx(0.5)  # trùng 2
    assert R.prob_up(SAMPLE_Q) == pytest.approx(1 - (0.25 + 0.25 * 0.0122 / 0.0126))
    assert round(R.prob_up(SAMPLE_Q), 2) == 0.51


def test_quantiles_to_prices_contract_sample():
    prices = R.quantiles_to_prices(71.32, SAMPLE_Q)
    # contract.md ghi 70.45 ở q25, nhưng 71.32 × exp(−0.0122) = 70.4552 → 70.46 (lỗi làm tròn
    # trong contract); 6 giá trị còn lại khớp.
    assert np.round(prices, 2).tolist() == [69.04, 69.55, 70.46, 71.35, 72.26, 73.18, 73.74]
    assert abs(prices[2] - 70.45) < 0.006


# ---------- PCHIP ----------


def test_prob_up_pchip_matches_knots_and_is_monotone():
    base = np.array([-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03])
    assert R.prob_up_pchip(base) == pytest.approx(0.5)  # 0 trùng q50
    for i, tau in enumerate(Q):
        shifted = base - base[i]  # đặt 0 đúng tại phân vị thứ i
        assert R.prob_up_pchip(shifted) == pytest.approx(min(max(1 - tau, 0.05), 0.95))
    shifts = np.linspace(-0.04, 0.04, 161)
    p = [R.prob_up_pchip(base + c) for c in shifts]  # dời phân phối lên → xác suất tăng không giảm
    assert np.all(np.diff(p) >= -1e-12)
    assert min(p) >= 0.05 and max(p) <= 0.95
    lin = [R.prob_up(base + c) for c in shifts]
    assert np.max(np.abs(np.array(p) - np.array(lin))) < 0.05

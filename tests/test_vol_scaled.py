"""K3b S1: σ_long, σ_short (EWMA), k_t và phân vị co giãn: không rò rỉ, phiên thiếu, kẹp, neo mốc."""

import numpy as np
import pandas as pd
import pytest

from configs import k3b as C
from src.data import calendars
from src.features.ceemdan_features import baseline_quantiles
from src.forecast.vol_scaled import (
    daily_log_returns,
    ewma_vol,
    long_vol,
    s1_quantiles,
    scale_quantiles,
    vol_ratio,
)

NYSE = calendars.sessions("NYSE")
GAP = pd.Timestamp("2014-02-14")  # một phiên NYSE bị thiếu trong bản giá
LAM = 0.94


def _prices(end="2014-12-31", drop=()):
    """Gold giả: biến động 1% → yên 0,3% (nửa cuối 2013) → mạnh 3% (2014), để k_t chạm cả hai
    ngưỡng kẹp."""
    dates = calendars.sessions("NYSE", "2012-01-03", "2014-12-31")
    sd = np.where(dates < "2013-07-01", 0.01, np.where(dates < "2014-01-01", 0.003, 0.03))
    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        {
            "asset": "gold",
            "date": dates,
            "price": 100 * np.exp(np.cumsum(rng.normal(0, 1, len(dates)) * sd)),
            "source": "yfinance",
            "published_at": (dates + pd.Timedelta(days=1, hours=12)).tz_localize("UTC"),
        }
    )
    keep = (frame["date"] <= pd.Timestamp(end)) & ~frame["date"].isin(pd.DatetimeIndex(drop))
    return frame.loc[keep].reset_index(drop=True)


def _series(prices):
    return pd.Series(prices["price"].to_numpy(), index=pd.DatetimeIndex(prices["date"]))


BASE = calendars.sessions("NYSE", "2013-03-01", "2014-06-30")


def test_values_at_t_do_not_change_when_future_is_appended():
    cut = pd.Timestamp("2014-03-31")
    short, full = _prices(end=cut), _prices()
    base = BASE[BASE <= cut]
    for lam in C.S1_LAMBDA.values():
        a = vol_ratio(short, "gold", base, lam)
        b = vol_ratio(full, "gold", base, lam)
        assert a.valid[-100:].all()
        np.testing.assert_array_equal(a.ratio, b.ratio)  # từng bit
        np.testing.assert_array_equal(a.k, b.k)
        pd.testing.assert_frame_equal(a.diag, b.diag)
        qa, oka, _ = s1_quantiles(short, "gold", base, lam)
        qb, okb, _ = s1_quantiles(full, "gold", base, lam)
        assert oka[-100:].all()
        np.testing.assert_array_equal(qa, qb)
        np.testing.assert_array_equal(oka, okb)
    ra, rb = daily_log_returns(_series(short), "NYSE"), daily_log_returns(_series(full), "NYSE")
    np.testing.assert_array_equal(ewma_vol(ra, LAM), ewma_vol(rb, LAM).loc[ra.index])
    np.testing.assert_array_equal(long_vol(ra)[0], long_vol(rb)[0].loc[ra.index])


@pytest.mark.parametrize("how", ["missing_row", "rejected"])
def test_pair_across_missing_session_is_dropped_and_variance_held(how):
    full = _prices()
    if how == "missing_row":
        prices, invalid = _prices(drop=[GAP]), None
    else:
        prices, invalid = full, [GAP]
    r = daily_log_returns(_series(prices), "NYSE", invalid)
    after = NYSE[NYSE.get_loc(GAP) + 1]
    before = NYSE[NYSE.get_loc(GAP) - 1]
    assert np.isnan(r.loc[GAP]) and np.isnan(r.loc[after])  # cả hai cặp chạm GAP đều bị bỏ
    # các cặp còn lại là log return giữa hai phiên liền kề
    p = _series(full)
    expected = np.log(p / p.shift(1)).reindex(r.index)
    keep = ~r.index.isin([GAP, after])
    np.testing.assert_allclose(r[keep], expected[keep], rtol=0, atol=1e-15)
    sigma = ewma_vol(r, LAM)
    assert sigma.loc[GAP] == sigma.loc[before] and sigma.loc[after] == sigma.loc[before]
    assert sigma.loc[NYSE[NYSE.get_loc(after) + 1]] != sigma.loc[before]
    _, n_long = long_vol(r)
    _, n_clean = long_vol(daily_log_returns(_series(full), "NYSE"))
    assert n_clean.loc[after] - n_long.loc[after] == 2


def test_ewma_initialisation_and_long_vol_min_obs():
    r = daily_log_returns(_series(_prices()), "NYSE")
    x = r.to_numpy()
    pos = np.flatnonzero(np.isfinite(x))
    start = pos[C.EWMA_INIT_OBS - 1]
    sigma = ewma_vol(r, LAM).to_numpy()
    assert np.isnan(sigma[:start]).all()
    assert sigma[start] ** 2 == pytest.approx(np.var(x[pos[: C.EWMA_INIT_OBS]], ddof=1), rel=1e-12)
    nxt = sigma[start] ** 2 * LAM + (1 - LAM) * x[start + 1] ** 2
    assert sigma[start + 1] ** 2 == pytest.approx(nxt, rel=1e-12)
    sigma_long, n = long_vol(r)
    assert (sigma_long[n < C.SIGMA_MIN_OBS].isna()).all()
    assert sigma_long[n >= C.SIGMA_MIN_OBS].notna().all()
    window = x[start - C.SIGMA_LONG_WINDOW + 1 : start + 1]
    assert sigma_long.iloc[start] == pytest.approx(np.nanstd(window, ddof=1), rel=1e-10)


def test_k_clipped_median_kept_and_quantiles_increase():
    prices = _prices()
    base = calendars.sessions("NYSE", "2013-03-01", "2014-12-30")
    q, ok, vr = s1_quantiles(prices, "gold", base, LAM)
    base_q, base_ok = baseline_quantiles(prices, "gold", base)
    assert ok.sum() > 300 and (ok == (base_ok & vr.valid)).all()
    k = vr.k[ok]
    assert (k >= C.K_CLIP[0]).all() and (k <= C.K_CLIP[1]).all()
    # dữ liệu giả đủ cực đoan để chạm cả hai ngưỡng (tỷ số chưa kẹp vượt ra ngoài)
    assert (vr.ratio[ok] < C.K_CLIP[0]).any() and (vr.ratio[ok] > C.K_CLIP[1]).any()
    assert k.min() == C.K_CLIP[0] and k.max() == C.K_CLIP[1]
    np.testing.assert_array_equal(q[ok][..., 3], base_q[ok][..., 3])  # trung vị = q50 mốc
    gaps = np.diff(q[ok], axis=-1)
    assert (gaps >= 0).all()
    assert (gaps[np.diff(base_q[ok], axis=-1) > 0] > 0).all()
    np.testing.assert_allclose(gaps, k[:, None, None] * np.diff(base_q[ok], axis=-1), atol=1e-15)
    assert np.isnan(q[~ok]).all()


def test_k_equal_one_is_baseline_q252():
    prices = _prices()
    base_q, base_ok = baseline_quantiles(prices, "gold", BASE)
    b = base_q[base_ok]
    np.testing.assert_array_equal(scale_quantiles(b, np.ones(len(b))), b)
    with pytest.raises(ValueError, match="positive"):
        scale_quantiles(b, np.zeros(len(b)))
    with pytest.raises(ValueError, match="nondecreasing"):
        scale_quantiles(b[..., ::-1], np.ones(len(b)))

"""K4 fhs_fit trên return GIẢ: fit arch khớp đệ quy NumPy, refit chỉ dùng return trước đầu tháng,
dùng lại tháng trước khi fit lỗi, dừng khi lần refit đầu lỗi, không đổi khi nối thêm tương lai."""

import numpy as np
import pandas as pd
import pytest

from configs import k4 as C
from src.data import calendars
from src.forecast import fhs_fit as FF
from src.forecast import fhs_numpy as F

TRUE = F.GjrParams(omega=0.02, alpha=0.03, gamma=0.08, beta=0.90, nu=7.0)


@pytest.fixture(scope="module")
def returns():
    """Return ngày theo lịch NYSE 2012–2016, sinh từ GJR-t (thang × 100), vài phiên không hợp lệ."""
    dates = calendars.sessions("NYSE", "2012-01-03", "2016-06-30")
    rng = np.random.default_rng(11)
    z = rng.standard_t(7, len(dates)) / np.sqrt(7 / 5)
    x = np.empty(len(dates))
    s2 = 1.0
    for t in range(len(dates)):
        x[t] = np.sqrt(s2) * z[t]
        s2 = F.next_variance(x[t], s2, TRUE)
    r = pd.Series(x / 100, index=dates)
    r.iloc[[0, 300, 301, 777]] = np.nan
    return r


def _month(day):
    return pd.Timestamp(day).to_period("M").to_timestamp()


def test_fit_window_matches_arch_and_recovers_parameters(returns):
    window = returns[returns.index < "2016-01-01"].dropna().iloc[-C.FHS_WINDOW :]
    fit, log = FF.fit_window(window, "2016-01-01")
    assert log["status"] == "ok" and log["convergence_flag"] == 0
    assert fit.parity_rel_error <= C.FILTER_PARITY_RTOL
    assert len(fit.z) == C.FHS_WINDOW and abs(np.std(fit.z) - 1) < 0.1
    assert fit.window_end < pd.Timestamp("2016-01-01")
    assert 0.5 < fit.params.beta < 0.99 and fit.params.persistence < 1  # 1000 quan sát: nhiễu mẫu
    assert 3 < fit.params.nu < 30


def test_monthly_fits_use_only_returns_before_month_start(returns):
    months = pd.date_range("2016-01-01", "2016-03-01", freq="MS")
    fits, logs = FF.monthly_fits(returns, months, "gold")
    changed = returns.copy()
    changed[changed.index >= "2016-02-01"] *= 3.0  # dữ liệu từ đầu tháng 2 trở đi
    fits2, _ = FF.monthly_fits(changed, months[:2], "gold")
    for m in months[:2]:
        assert fits[m].window_end < m
        assert fits2[m].params == fits[m].params and np.array_equal(fits2[m].z, fits[m].z)
    assert [row["status"] for row in logs] == ["ok"] * 3
    assert all(row["used_month"] == row["month"] for row in logs)


def test_insufficient_history_gives_no_model(returns):
    short = returns[returns.index >= "2012-02-15"]  # dưới 1000 return trước 2016-01-01
    n_before = int(short[short.index < "2016-01-01"].notna().sum())
    assert n_before < C.FHS_WINDOW
    months = pd.date_range("2016-01-01", "2016-06-01", freq="MS")
    fits, logs = FF.monthly_fits(short, months, "brent")
    status = [row["status"] for row in logs]
    first_ok = status.index("ok")
    assert first_ok > 0 and all(fits[m] is None for m in months[:first_ok])
    assert all(s == "insufficient_history" for s in status[:first_ok])


def test_failed_refit_reuses_previous_month_and_first_failure_stops(returns, monkeypatch):
    original = FF.fit_window
    months = pd.date_range("2016-01-01", "2016-03-01", freq="MS")

    def fail_february(window, month):
        if pd.Timestamp(month) == pd.Timestamp("2016-02-01"):
            return None, {"n_window": len(window), "warnings": [], "status": "not_converged"}
        return original(window, month)

    monkeypatch.setattr(FF, "fit_window", fail_february)
    fits, logs = FF.monthly_fits(returns, months, "gold")
    jan, feb, mar = months
    assert fits[feb] is fits[jan]
    assert logs[1]["status"] == "not_converged" and logs[1]["used_month"] == jan
    assert fits[mar].month == mar

    def fail_all(window, month):
        return None, {"n_window": len(window), "warnings": [], "status": "fit_error"}

    monkeypatch.setattr(FF, "fit_window", fail_all)
    with pytest.raises(FF.FitStop, match="first refit"):
        FF.monthly_fits(returns, months, "gold")


def test_forecasts_follow_recursion_and_ignore_future(returns):
    months = pd.date_range("2016-01-01", "2016-02-01", freq="MS")
    fits, _ = FF.monthly_fits(returns, months, "gold")
    base = calendars.sessions("NYSE", "2016-01-04", "2016-02-12")
    q, ok, _ = FF.fhs_forecasts(returns, "gold", base, fits)
    assert ok.all() and q.shape == (len(base), 7, 7)
    # ngày gốc t: đệ quy với tham số tháng của t, qua mọi return hợp lệ từ đầu cửa sổ tới t
    t = base[25]
    fit = fits[_month(t)]
    seq = returns[(returns.index >= fit.window_start) & (returns.index <= t)].dropna()
    _, s2 = F.variance_path(100 * seq.to_numpy(), fit.params, fit.backcast)
    expected = F.fhs_quantiles(
        float(s2[-1]), fit.z, fit.params, seed=F.seed_for("gold", t.to_datetime64()), scale=100.0
    )
    assert np.array_equal(q[25], expected)
    # nối thêm (hoặc đổi) dữ liệu sau t không đổi dự báo tại t
    future = returns.copy()
    future[future.index > t] *= 5.0
    q_cut, _, _ = FF.fhs_forecasts(returns[returns.index <= t], "gold", base[:26], fits)
    q_future, _, _ = FF.fhs_forecasts(future, "gold", base[:26], fits)
    assert np.array_equal(q_cut, q[:26]) and np.array_equal(q_future, q[:26])


def test_month_without_model_is_invalid(returns):
    base = calendars.sessions("NYSE", "2016-01-04", "2016-01-08")
    q, ok, _ = FF.fhs_forecasts(returns, "brent", base, {_month(base[0]): None})
    assert not ok.any() and np.isnan(q).all()

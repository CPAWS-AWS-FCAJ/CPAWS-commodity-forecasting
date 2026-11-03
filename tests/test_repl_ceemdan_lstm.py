"""Minh họa CEEMDAN + LSTM, bước 1 (kế hoạch mục 3.3): chỉ dữ liệu tổng hợp, không cần GPU."""

from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from src.data import calendars
from src.experiments.repl_ceemdan_lstm import config as C
from src.experiments.repl_ceemdan_lstm import data as D
from src.experiments.repl_ceemdan_lstm.decompose import (
    combine_components,
    r_causal,
    r_full,
)
from src.forecast.decomposition import CeemdanConfig, fixed_imf_matrix

# Cấu hình nhỏ cho test (cấu hình thật: C.ceemdan_config(), window 252, trials 100)
CFG = CeemdanConfig(window=64, trials=5, epsilon=0.005, seed=42, keep_last=32)


def _series(n=200, start="2014-01-02", seed=0) -> D.AssetSeries:
    rng = np.random.default_rng(seed)
    dates = calendars.sessions("NYSE", start)[:n]
    values = 100 + np.cumsum(rng.normal(0, 1, n))
    values[150] += 15  # một cú nhảy phía sau các ngày gốc đầu
    return D.AssetSeries("gold", "NYSE", dates, values)


def _prefix(s: D.AssetSeries, t: int) -> D.AssetSeries:
    return D.AssetSeries(s.asset, s.calendar, s.dates[: t + 1], s.values[: t + 1])


# ---------- bất biến theo tiền tố ----------


def test_r_causal_is_prefix_invariant_bit_for_bit():
    s = _series()
    for t in (63, 100, 149):
        full, wf = r_causal(s, CFG, np.array([t]))
        cut, wc = r_causal(_prefix(s, t), CFG, np.array([t]))
        assert full["n_imf"].tolist() == cut["n_imf"].tolist()
        assert full["price_hash"].tolist() == cut["price_hash"].tolist()
        assert full["seed_id"].tolist() == cut["seed_id"].tolist()
        np.testing.assert_array_equal(wf[0].imfs, wc[0].imfs)
        np.testing.assert_array_equal(wf[0].residue, wc[0].residue)
        for name in C.COMPONENTS:
            np.testing.assert_array_equal(full[name].iloc[0], cut[name].iloc[0])


# ---------- loader từ chối dữ liệu sau CUTOFF ----------


def _write_clean(root, dates) -> str:
    d = root / "clean" / "prices" / "dt=2099-01-01"
    d.mkdir(parents=True)
    df = pd.DataFrame(
        {"date": pd.DatetimeIndex(dates), "asset": "gold", "price": 100.0 + np.arange(len(dates))}
    )
    df.to_parquet(d / "prices.parquet", index=False)
    df.iloc[:1].to_parquet(d / "rejected.parquet", index=False)
    return "2099-01-01"


def test_read_clean_cuts_at_cutoff(tmp_path):
    dt = _write_clean(tmp_path, ["2018-12-28", "2018-12-31", "2019-01-02", "2019-06-03"])
    clean = D.read_clean(tmp_path, dt)
    assert clean.prices["date"].max() <= pd.Timestamp(C.CUTOFF)
    assert len(clean.prices) == 2
    assert set(clean.sha256) == {"prices.parquet", "rejected.parquet"}


def test_read_clean_raises_if_filter_lets_2019_through(tmp_path, monkeypatch):
    dt = _write_clean(tmp_path, ["2018-12-31", "2019-01-02"])
    real = pd.read_parquet
    monkeypatch.setattr(D.pd, "read_parquet", lambda p, filters=None: real(p))  # bỏ filter
    with pytest.raises(D.CutoffError):
        D.read_clean(tmp_path, dt)


def test_asset_series_raises_on_rows_after_cutoff():
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2018-12-28", "2018-12-31", "2019-01-02"]),
            "asset": "gold",
            "price": [1.0, 2.0, 3.0],
        }
    )
    with pytest.raises(D.CutoffError):
        D.asset_series(prices, "gold")
    assert len(D.asset_series(prices.iloc[:2], "gold").dates) == 2


def test_read_clean_missing_snapshot(tmp_path):
    with pytest.raises(FileNotFoundError):
        D.read_clean(tmp_path, "2000-01-01")


# ---------- split_train ----------


def _train_dates(drop=()) -> pd.DatetimeIndex:
    d = calendars.sessions("NYSE", C.TRAIN[0], C.TRAIN[1])
    return d.difference(pd.DatetimeIndex(drop))


@pytest.mark.parametrize("drop", [(), ("2016-02-17", "2015-06-10")])
def test_split_train_segments(drop):
    dates = _train_dates(drop)
    # ngày ngoài TRAIN bị bỏ qua
    extra = pd.DatetimeIndex(["2013-12-31", "2017-01-03"])
    segs = D.split_train(dates.union(extra), "NYSE")
    n = len(dates)
    assert [g.name for g in segs] == list(C.SPLIT_NAMES)
    assert sum(g.n_dates for g in segs) == n
    for g, frac in zip(segs, C.SPLIT, strict=True):
        assert abs(g.n_dates - frac * n) <= 1  # đúng tỷ lệ ±1 mẫu
    # liền nhau, không giao nhau: đoạn sau bắt đầu ở ngày kế tiếp ngày cuối đoạn trước
    for a, b in pairwise(segs):
        assert a.end < b.start
        assert dates[dates.get_loc(a.end) + 1] == b.start
    assert segs[0].start == dates[0] and segs[-1].end == dates[-1]
    for g in segs:
        inside = dates[(dates >= g.start) & (dates <= g.end)]
        assert g.origins.isin(inside).all()
        # mẫu ở ranh giới bị bỏ: ngày cuối đoạn có t + 1 ở đoạn sau
        assert g.end not in g.origins
        assert len(g.origins) == g.n_dates - 1
        # target (phiên kế tiếp theo lịch) không lấn sang đoạn sau
        assert (D.next_sessions(g.origins, "NYSE") <= g.end).all()
    all_origins = segs[0].origins.append([g.origins for g in segs[1:]])
    assert not all_origins.has_duplicates
    assert (all_origins <= pd.Timestamp(C.TRAIN[1])).all()


def test_next_sessions_follow_calendar_not_rows():
    # 2016-02-15 (Presidents Day) đóng cửa: phiên sau 2016-02-12 là 2016-02-16
    got = D.next_sessions(pd.DatetimeIndex(["2016-02-12", "2016-12-30"]), "NYSE")
    assert list(got) == [pd.Timestamp("2016-02-16"), pd.Timestamp("2017-01-03")]


# ---------- gộp 4 thành phần ----------


def test_components_sum_to_signal_in_window():
    s = _series()
    origins = np.array([63, 120, 199])
    df, wins = r_causal(s, CFG, origins)
    for i, t in enumerate(origins):
        total = np.sum([df[name].iloc[i] for name in C.COMPONENTS], axis=0)
        expected = s.values[t - C.SEQ_LEN + 1 : t + 1]
        np.testing.assert_allclose(total, expected, rtol=1e-8, atol=0)
        assert df[C.COMPONENTS[0]].iloc[i].shape == (C.SEQ_LEN,)
    # cùng quy tắc với fixed_imf_matrix(max_imf=3)
    for w, row in zip(wins, df.itertuples(index=False), strict=True):
        m = fixed_imf_matrix([w], C.MAX_IMF, CFG.keep_last)[0].T
        np.testing.assert_array_equal(m, combine_components(w.imfs, w.residue))
        np.testing.assert_array_equal(
            m[:, -C.SEQ_LEN :], np.vstack([row.imf1, row.imf2, row.imf3, row.rest])
        )


def test_r_full_components_sum_to_series():
    s = _series()
    df, n_imf = r_full(s, CFG)
    assert n_imf >= 1 and len(df) == len(s.values)
    np.testing.assert_allclose(df[list(C.COMPONENTS)].sum(axis=1), s.values, rtol=1e-8, atol=0)


def test_combine_components_pads_missing_imfs():
    imfs = np.ones((2, 5))
    res = np.full(5, 3.0)
    out = combine_components(imfs, res, max_imf=3)
    assert out.shape == (4, 5)
    np.testing.assert_array_equal(out[2], 0.0)
    np.testing.assert_array_equal(out.sum(axis=0), imfs.sum(axis=0) + res)


def test_config_constants():
    cfg = C.ceemdan_config()
    assert cfg.window == 252 and cfg.keep_last >= C.SEQ_LEN
    assert C.N_COMPONENTS == len(C.COMPONENTS) == C.MAX_IMF + 1
    assert np.isclose(sum(C.SPLIT), 1.0)
    assert C.EVAL[1] == C.CUTOFF and C.TRAIN[1] < C.EVAL[0]


# ---------- bước 2: mẫu, chuẩn hóa, phân vị, LSTM ----------


def _full_series(drop=()) -> D.AssetSeries:
    """Chuỗi tổng hợp 2012-01 → 2018-12-31 trên lịch NYSE, có thể bỏ vài dòng (phiên thiếu)."""
    dates = calendars.sessions("NYSE", C.WARMUP_START, C.CUTOFF)
    dates = dates.difference(pd.DatetimeIndex(drop))
    rng = np.random.default_rng(1)
    values = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates))))
    return D.AssetSeries("gold", "NYSE", dates, values)


def _fake_tables(s: D.AssetSeries) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bảng R-causal và R-full giả, cùng định dạng bước 1 (thành phần = giá × tỷ trọng cố định)."""
    w = np.array([0.1, 0.2, 0.3, 0.4])
    full = pd.DataFrame(
        {"date": s.dates} | {n: s.values * w[j] for j, n in enumerate(C.COMPONENTS)}
    )
    rows = np.flatnonzero(s.dates >= pd.Timestamp(C.CAUSAL_START))
    causal = pd.DataFrame(
        {
            "end_date": s.dates[rows],
            "n_imf": 4,
            "price_hash": "x",
        }
    )
    for j, n in enumerate(C.COMPONENTS):
        causal[n] = [s.values[t - C.SEQ_LEN + 1 : t + 1] * w[j] * 1.01 for t in rows]
    return causal, full


DROPPED = ("2015-03-10", "2017-06-14")  # phiên thiếu dòng giá: t trước đó không có target


@pytest.fixture(scope="module")
def samples():
    from src.experiments.repl_ceemdan_lstm.dataset import build_samples

    s = _full_series(DROPPED)
    causal, full = _fake_tables(s)
    return build_samples(s, causal, full)


def test_samples_targets_stay_inside_their_segment(samples):
    sm = samples
    cut = pd.Timestamp(C.CUTOFF)
    for name, (start, end) in sm.segment_bounds.items():
        m = sm.mask(name)
        assert m.any()
        assert (sm.origins[m] >= start).all() and (sm.origins[m] <= end).all()
        assert (sm.target_dates[m] <= end).all()  # target không lấn sang đoạn sau
    ev = sm.mask("eval")
    assert (sm.origins[ev] >= pd.Timestamp(C.EVAL[0])).all()
    assert (sm.origins[ev] <= pd.Timestamp(C.EVAL[1])).all()
    assert (sm.target_dates[ev] <= cut).all()
    assert sm.origins[ev].min() == pd.Timestamp("2017-01-03")
    assert sm.origins[ev].max() == pd.Timestamp("2018-12-28")
    # 2018-12-31: t + 1 sau CUTOFF; ngày trước phiên thiếu: không có target
    assert sm.reason[sm.origins == pd.Timestamp("2018-12-31")][0] == "t + 1 sau CUTOFF"
    for d in ("2015-03-09", "2017-06-13"):
        i = np.flatnonzero(sm.origins == pd.Timestamp(d))[0]
        assert sm.segment[i] == "" and sm.reason[i] == "t + 1 không có giá hợp lệ"
    used = sm.segment != ""
    assert np.isfinite(sm.r_next[used]).all()
    for v in ("r_raw", "r_full", "r_causal"):
        assert np.isfinite(sm.X[v][used]).all() and np.isfinite(sm.Y[v][used]).all()
    # target R-causal = giá trị cuối của cửa sổ kết thúc tại t + 1
    i = np.flatnonzero(sm.mask("fit"))[5]
    j = np.flatnonzero(sm.origins == sm.target_dates[i])[0]
    np.testing.assert_array_equal(sm.Y["r_causal"][i], sm.X["r_causal"][j, -1, :])


def test_scaler_sees_only_fit_segment(samples):
    from src.experiments.repl_ceemdan_lstm.dataset import fit_scalers

    sm = samples
    X = sm.X["r_causal"].copy()
    base = fit_scalers(X, sm.segment)
    other = np.isin(sm.segment, ["early_stop", "calib", "eval"])
    X[other] *= 7.0
    X[other] += 3.0
    assert fit_scalers(X, sm.segment) == base
    X[sm.mask("fit")] += 1.0
    assert fit_scalers(X, sm.segment) != base


def test_quantiles_depend_only_on_calibration_residuals():
    from src.experiments.repl_ceemdan_lstm.evaluate import calibrated_quantiles

    rng = np.random.default_rng(0)
    r_hat = rng.normal(0, 0.01, 50)
    res = rng.normal(0, 0.02, 120)
    q = calibrated_quantiles(r_hat, res)
    assert q.shape == (50, 7)
    assert (np.diff(q, axis=1) >= 0).all()
    np.testing.assert_allclose(
        q - r_hat[:, None],
        np.tile(np.quantile(res, [0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95]), (50, 1)),
    )
    # đổi r̂ (đoạn eval) không đổi phần cộng thêm; đổi phần dư calib thì đổi
    q2 = calibrated_quantiles(r_hat + 1.0, res)
    np.testing.assert_allclose(q2 - (r_hat + 1.0)[:, None], q - r_hat[:, None])
    q3 = calibrated_quantiles(r_hat, res * 2)
    assert not np.allclose(q3, q)


def test_nonpositive_price_forecast_is_counted_not_replaced():
    from src.experiments.repl_ceemdan_lstm.evaluate import to_returns

    p_hat = np.array([101.0, -3.0, 0.0, np.nan, 99.0])
    p_t = np.full(5, 100.0)
    before = p_hat.copy()
    r_hat, err = to_returns(p_hat, p_t)
    assert err.tolist() == [False, True, True, False, False]
    assert np.isnan(r_hat[[1, 2, 3]]).all()
    np.testing.assert_allclose(r_hat[[0, 4]], np.log([1.01, 0.99]))
    np.testing.assert_array_equal(p_hat, before)


def test_same_seed_training_is_bit_identical_on_cpu():
    torch = pytest.importorskip("torch")
    from src.experiments.repl_ceemdan_lstm.model import predict, train_lstm

    rng = np.random.default_rng(3)
    x = rng.normal(size=(150, C.SEQ_LEN))
    y = x[:, -1] * 0.5 + rng.normal(0, 0.1, 150)
    params = C.LSTM | {"max_epochs": 4, "patience": 2}
    dev = torch.device("cpu")
    runs = [train_lstm(x[:100], y[:100], x[100:], y[100:], 0, dev, params) for _ in range(2)]
    (m1, i1), (m2, i2) = runs
    for a, b in zip(m1.state_dict().values(), m2.state_dict().values(), strict=True):
        assert torch.equal(a, b)
    assert i1.best_epoch == i2.best_epoch
    np.testing.assert_array_equal(predict(m1, x, dev), predict(m2, x, dev))
    m3, _ = train_lstm(x[:100], y[:100], x[100:], y[100:], 1, dev, params)
    assert not torch.equal(m1.head.weight, m3.head.weight)

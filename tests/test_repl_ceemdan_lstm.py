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

"""Cache IMF CEEMDAN: layout, dùng lại, tiếp tục khi bị ngắt, cập nhật hằng ngày, nhân quả."""

import json

import numpy as np
import pandas as pd

from src.data import storage
from src.features import ceemdan_cache as cc
from src.forecast.decomposition import CeemdanConfig, causal_imf_windows

CFG = CeemdanConfig(window=64, keep_last=16, trials=3, seed=7)


def _prices(n=140, seed=0, start="2013-10-01"):
    rng = np.random.default_rng(seed)
    d = pd.bdate_range(start, periods=n)
    p = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame({"date": d, "asset": "gold", "price": p})


def _all_rows(st, cfg=CFG):
    d, w = cc.load(st, "gold", cfg, "2000-01-01", "2030-12-31")
    return d, w


def test_layout_and_row_schema(tmp_path):
    st = storage.LocalStorage(tmp_path)
    prices = _prices()
    dates = pd.DatetimeIndex(prices["date"])
    stats = cc.ensure(st, prices, "gold", CFG, dates[dates >= "2014-01-01"][:30])
    base = f"features/ceemdan/asset=gold/window=64/cfg={CFG.hash()}"
    assert st.exists(f"{base}/config.json") and st.exists(f"{base}/month=2014-01.parquet")
    meta = json.loads(st.read_bytes(f"{base}/config.json"))
    assert meta["trials"] == 3 and meta["cfg_hash"] == CFG.hash()
    df = storage.read_parquet(st, f"{base}/month=2014-01.parquet")
    assert list(df.columns) == cc.COLUMNS
    r = df.iloc[0]
    assert len(r["imfs"]) == r["n_imf"] * r["keep_last"] and len(r["residue"]) == 16
    assert r["seed_id"] == (pd.Timestamp(r["end_date"]) - pd.Timestamp("1970-01-01")).days
    assert stats.computed == 30 and stats.reused == 0


def test_cached_values_equal_direct_computation(tmp_path):
    st = storage.LocalStorage(tmp_path)
    prices = _prices()
    dates = pd.DatetimeIndex(prices["date"])
    origins = dates[[70, 90, 139]]
    cc.ensure(st, prices, "gold", CFG, origins)
    got_d, got = _all_rows(st)
    direct = causal_imf_windows(
        prices["price"].to_numpy(),
        np.array([70, 90, 139]),
        CFG,
        seed_ids=np.array([cc.seed_id(d) for d in origins]),
    )
    assert list(got_d) == list(origins)
    for a, b in zip(got, direct, strict=True):
        np.testing.assert_array_equal(a.imfs, b.imfs)
        np.testing.assert_array_equal(a.residue, b.residue)


def test_rerun_reuses_and_resumes_after_interruption(tmp_path, monkeypatch):
    st = storage.LocalStorage(tmp_path)
    prices = _prices()
    dates = pd.DatetimeIndex(prices["date"])
    origins = dates[dates >= "2014-01-01"]
    first = cc.ensure(st, prices, "gold", CFG, origins)
    # giả lập bị ngắt: mất tháng cuối, tháng giữa bị ghi dở (file hỏng)
    base = tmp_path / cc.prefix("gold", CFG)
    months = sorted(p.name for p in base.glob("month=*.parquet"))
    (base / months[-1]).unlink()
    (base / months[1]).write_bytes(b"truncated")
    again = cc.ensure(st, prices, "gold", CFG, origins)
    n_lost = sum(1 for d in origins if d.strftime("%Y-%m") in (months[-1][6:13], months[1][6:13]))
    assert again.computed == n_lost and again.reused == first.computed - n_lost
    third = cc.ensure(st, prices, "gold", CFG, origins)
    assert third.computed == 0


def test_daily_update_recomputes_only_changed_recent_windows(tmp_path):
    st = storage.LocalStorage(tmp_path)
    prices = _prices()
    dates = pd.DatetimeIndex(prices["date"])
    cc.ensure(st, prices, "gold", CFG, dates[dates >= "2014-01-01"])
    _, before = _all_rows(st)
    # ingest sửa giá phiên áp chót và thêm một phiên mới
    fixed = prices.copy()
    fixed.loc[len(fixed) - 2, "price"] += 0.5
    nxt = pd.DataFrame({"date": [dates[-1] + pd.offsets.BDay()], "asset": "gold", "price": [101.0]})
    fixed = pd.concat([fixed, nxt], ignore_index=True)
    stats = cc.update_recent(st, fixed, "gold", CFG, since=dates[-5])
    # 2 cửa sổ chứa phiên bị sửa nằm trong 5 phiên cuối (áp chót, cuối) + 1 cửa sổ mới
    assert stats.computed == 3 and stats.reused == 3
    d_after, after = _all_rows(st)
    assert d_after[-1] == nxt["date"].iloc[0]
    for a, b in zip(before[:-2], after[: len(before) - 2], strict=True):
        np.testing.assert_array_equal(a.imfs, b.imfs)


def test_cache_is_causal_when_future_is_appended(tmp_path):
    st1, st2 = storage.LocalStorage(tmp_path / "a"), storage.LocalStorage(tmp_path / "b")
    full = _prices(n=160)
    cut = full.iloc[:120]
    dates = pd.DatetimeIndex(cut["date"])
    origins = dates[dates >= "2014-01-01"]
    cc.ensure(st1, cut, "gold", CFG, origins)
    cc.ensure(st2, full, "gold", CFG, origins)
    _, a = _all_rows(st1)
    _, b = _all_rows(st2)
    assert len(a) == len(b) == len(origins)
    for x, y in zip(a, b, strict=True):
        np.testing.assert_array_equal(x.imfs, y.imfs)
        np.testing.assert_array_equal(x.residue, y.residue)


def test_seed_by_date_survives_history_shift(tmp_path):
    st1, st2 = storage.LocalStorage(tmp_path / "a"), storage.LocalStorage(tmp_path / "b")
    prices = _prices()
    shorter = prices.iloc[5:].reset_index(drop=True)  # bỏ 5 dòng đầu: vị trí các dòng dịch đi
    origin = pd.DatetimeIndex([prices["date"].iloc[120]])
    cc.ensure(st1, prices, "gold", CFG, origin)
    cc.ensure(st2, shorter, "gold", CFG, origin)
    np.testing.assert_array_equal(_all_rows(st1)[1][0].imfs, _all_rows(st2)[1][0].imfs)


def test_origins_without_enough_history_are_skipped(tmp_path):
    st = storage.LocalStorage(tmp_path)
    prices = _prices()
    stats = cc.ensure(st, prices, "gold", CFG, pd.DatetimeIndex(prices["date"][:70]))
    assert stats.skipped_no_history == 63 and stats.computed == 7


def test_config_change_uses_separate_partition():
    other = CeemdanConfig(window=64, keep_last=16, trials=4, seed=7)
    assert other.hash() != CFG.hash()
    assert cc.prefix("gold", other) != cc.prefix("gold", CFG)
    # window là một chiều riêng của đường dẫn, không nằm trong cfg_hash
    w252 = CeemdanConfig(window=252, keep_last=16, trials=3, seed=7)
    assert w252.hash() == CFG.hash() and "window=252" in cc.prefix("gold", w252)

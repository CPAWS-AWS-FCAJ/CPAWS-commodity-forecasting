"""src/features/build.py: đặc trưng theo lịch, cửa sổ input, không rò rỉ (ADR-0008 mục 1, 8)."""

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data import calendars, clean
from src.data.config import ASSETS
from src.features import build as B

ROOT = Path(__file__).resolve().parents[1]


def _prices(asset: str, start: str, end: str, seed: int = 0, cal: str | None = None):
    """Bảng clean dạng dài (schema clean.COLUMNS) với giá tổng hợp trên lịch của tài sản."""
    cal = cal or ASSETS[asset].calendar
    d = calendars.sessions(cal, start, end)
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "date": d,
            "asset": asset,
            "price": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(d)))),
            "unit": "USD",
            "source": "yfinance",
            "published_at": clean.published_at(d, "yfinance"),
            "ingested_at": pd.Timestamp("2026-10-09", tz="UTC"),
            "flag": "",
        }
    )
    return clean.normalize_types(df)


def _px(df: pd.DataFrame, day) -> float:
    return float(df.loc[df["date"] == pd.Timestamp(day), "price"].iloc[0])


def _drop(df: pd.DataFrame, day) -> pd.DataFrame:
    return df[df["date"] != pd.Timestamp(day)].reset_index(drop=True)


def _assert_batches_equal(a: B.FeatureBatch, b: B.FeatureBatch):
    np.testing.assert_array_equal(a.X, b.X)  # NaN ở cùng vị trí được coi là bằng
    np.testing.assert_array_equal(a.valid, b.valid)
    np.testing.assert_array_equal(a.reason, b.reason)
    np.testing.assert_array_equal(a.base_dates, b.base_dates)
    np.testing.assert_array_equal(a.input_session_dates, b.input_session_dates)
    np.testing.assert_array_equal(a.max_input_published_at, b.max_input_published_at)


# ---------- frame ----------


def test_frame_schema_and_reasons():
    p = _prices("gold", "2019-01-01", "2019-03-31")
    f = B.build_feature_frame(p, "gold")
    assert list(f.columns) == B.FRAME_COLUMNS
    assert str(f["feature_session_date"].dtype) == "datetime64[ns]"
    assert str(f["feature_available_at"].dtype) == "datetime64[ns, UTC]"
    assert not f.duplicated(["asset", "feature_session_date"]).any()
    assert f["feature_reason"].iloc[0] == B.FRAME_REASON_HISTORY_START
    assert f["feature_valid"].iloc[1:].all()


def test_flags_do_not_invalidate():
    p = _prices("wti", "2019-01-01", "2019-03-31")
    p["flag"] = "jump|low_liquidity|roll|stale_source|xcheck_level"
    f = B.build_feature_frame(p, "wti")
    assert f["feature_valid"].iloc[1:].all()


def test_other_assets_in_long_table_are_ignored():
    gold = _prices("gold", "2019-01-01", "2019-03-31", seed=1)
    both = pd.concat([gold, _prices("wti", "2019-01-01", "2019-03-31", seed=2)])
    pd.testing.assert_frame_equal(
        B.build_feature_frame(both, "gold"), B.build_feature_frame(gold, "gold")
    )


# ---------- (a) không đổi khi nối thêm hoặc sửa giá sau t ----------


def test_values_at_t_unchanged_when_future_appended_or_edited():
    full = _prices("brent", "2019-01-01", "2019-12-31", seed=3)
    t = pd.Timestamp("2019-08-30")
    short = full[full["date"] <= t]
    edited = full.copy()
    after = edited["date"] > t
    edited.loc[after, "price"] = edited.loc[after, "price"] * 3.0  # tương lai bị sửa
    edited.loc[edited.index[after][5], "price"] = -1.0  # và có giá <= 0 trong tương lai

    frames = [B.build_feature_frame(x, "brent") for x in (short, full, edited)]
    head = [fr[fr["feature_session_date"] <= t].reset_index(drop=True) for fr in frames]
    pd.testing.assert_frame_equal(head[0], head[1])
    pd.testing.assert_frame_equal(head[0], head[2])

    bd = calendars.sessions("CME", "2019-05-01", t)
    batches = [B.make_windows(fr, bd, window=60) for fr in frames]
    assert batches[0].valid.all()
    _assert_batches_equal(batches[0], batches[1])
    _assert_batches_equal(batches[0], batches[2])


# ---------- (b) phần tử cuối là return kết thúc ở t ----------


def test_last_element_is_return_ending_at_t():
    p = _prices("gold", "2019-01-01", "2019-06-30", seed=4)
    cal = calendars.sessions("NYSE", "2019-01-01", "2019-06-30")
    t, prev, nxt = cal[100], cal[99], cal[101]
    b = B.make_windows(B.build_feature_frame(p, "gold"), [t], window=10)
    last = b.X[0, -1, 0]
    assert last == pytest.approx(math.log(_px(p, t) / _px(p, prev)))
    assert last != pytest.approx(math.log(_px(p, nxt) / _px(p, t)))
    assert b.input_session_dates[0, -1] == np.datetime64(t)
    np.testing.assert_array_equal(b.input_session_dates[0], cal[91:101].to_numpy())
    # phần tử đầu là return kết thúc ở t-window+1, dùng giá tại t-window
    assert b.X[0, 0, 0] == pytest.approx(math.log(_px(p, cal[91]) / _px(p, cal[90])))


# ---------- (c) thiếu một phiên giữa cửa sổ ----------


def test_missing_session_invalidates_window_without_ffill():
    p = _prices("wti", "2019-01-01", "2019-06-30", seed=5)
    cal = calendars.sessions("CME", "2019-01-01", "2019-06-30")
    gap = cal[95]
    f = B.build_feature_frame(_drop(p, gap), "wti")
    row = f.set_index("feature_session_date")
    # return kết thúc ở gap và return kết thúc ở phiên sau gap đều thiếu
    assert row.loc[gap, "feature_reason"] == B.FRAME_REASON_MISSING
    assert row.loc[cal[96], "feature_reason"] == B.FRAME_REASON_MISSING
    assert np.isnan(row.loc[gap, "log_return_1_end"])
    assert row.loc[cal[97], "feature_valid"]  # không ghép qua khoảng trống

    b = B.make_windows(f, [cal[100], cal[120]], window=10)
    assert not b.valid[0] and b.reason[0] == B.REASON_INVALID_WINDOW
    assert np.isnan(b.X[0, 4, 0]) and np.isnan(b.X[0, 5, 0])  # vị trí của cal[95], cal[96]
    assert np.isfinite(np.delete(b.X[0, :, 0], [4, 5])).all()
    assert np.isnat(b.max_input_published_at[0])
    assert b.valid[1]  # cửa sổ [111..120] không chứa khoảng trống


# ---------- (d) giá <= 0 ----------


@pytest.mark.parametrize("bad", [0.0, -37.63])
def test_nonpositive_price_invalidates_window(bad):
    p = _prices("wti", "2019-01-01", "2019-06-30", seed=6)
    cal = calendars.sessions("CME", "2019-01-01", "2019-06-30")
    p.loc[p["date"] == cal[95], "price"] = bad
    f = B.build_feature_frame(p, "wti")
    row = f.set_index("feature_session_date")
    assert row.loc[cal[95], "feature_reason"] == B.FRAME_REASON_NONPOSITIVE
    assert row.loc[cal[96], "feature_reason"] == B.FRAME_REASON_NONPOSITIVE
    b = B.make_windows(f, [cal[100]], window=10)
    assert not b.valid[0] and b.reason[0] == B.REASON_INVALID_WINDOW


def test_invalid_dates_are_treated_as_missing():
    p = _prices("gold", "2019-01-01", "2019-06-30", seed=7)
    cal = calendars.sessions("NYSE", "2019-01-01", "2019-06-30")
    f = B.build_feature_frame(p, "gold", invalid_dates=[cal[95]])
    assert f.set_index("feature_session_date").loc[cal[95], "feature_reason"] == "missing_price"
    pd.testing.assert_frame_equal(f, B.build_feature_frame(_drop(p, cal[95]), "gold"))


def test_invalid_dates_generator_matches_list():
    p = _prices("wti", "2019-01-01", "2019-06-30", seed=13)
    cal = calendars.sessions("CME", "2019-01-01", "2019-06-30")
    days = [cal[40], cal[95]]
    as_list = B.build_feature_frame(p, "wti", invalid_dates=days)
    as_gen = B.build_feature_frame(p, "wti", invalid_dates=(d for d in days))
    pd.testing.assert_frame_equal(as_gen, as_list)
    assert (as_gen["feature_reason"] == B.FRAME_REASON_MISSING).sum() == 4  # 2 ngày × 2 feature


# ---------- (e) chưa đủ window + 1 giá ----------


def test_insufficient_history():
    p = _prices("silver", "2019-01-01", "2019-06-30", seed=8)
    cal = calendars.sessions("NYSE", "2019-01-01", "2019-06-30")
    w = 20
    b = B.make_windows(B.build_feature_frame(p, "silver"), [cal[w - 1], cal[w]], window=w)
    # cal[w-1] chỉ có w giá (cal[0..w-1]); cal[w] có đủ w+1 giá
    assert not b.valid[0] and b.reason[0] == B.REASON_INSUFFICIENT_HISTORY
    assert b.valid[1] and b.reason[1] == ""
    # base_date trước cả ngày giá đầu cũng là thiếu lịch sử, không phải lỗi
    early = calendars.sessions("NYSE", "2018-12-01", "2018-12-31")[-1]
    b2 = B.make_windows(B.build_feature_frame(p, "silver"), [early], window=w)
    assert b2.reason[0] == B.REASON_INSUFFICIENT_HISTORY and np.isnan(b2.X).all()


# ---------- (f) một base_date trùng với khi gọi cả dải ----------


def test_single_call_matches_range_call():
    p = _drop(_prices("brent", "2018-06-01", "2019-12-31", seed=9), "2019-03-14")
    f = B.build_feature_frame(p, "brent")
    bd = calendars.sessions("CME", "2019-01-01", "2019-12-31")
    full = B.make_windows(f, bd, window=60)
    assert (~full.valid).any() and full.valid.any()
    for i in (0, 50, 51, 130, len(bd) - 1):
        one = B.make_windows(f, [bd[i]], window=60)
        np.testing.assert_array_equal(one.X[0], full.X[i])
        assert one.valid[0] == full.valid[i] and one.reason[0] == full.reason[i]
        np.testing.assert_array_equal(one.input_session_dates[0], full.input_session_dates[i])
        np.testing.assert_array_equal(one.max_input_published_at[0], full.max_input_published_at[i])


def test_base_dates_order_is_preserved():
    p = _prices("gold", "2019-01-01", "2019-06-30")
    f = B.build_feature_frame(p, "gold")
    cal = calendars.sessions("NYSE", "2019-04-01", "2019-04-30")
    fwd = B.make_windows(f, cal, window=5)
    rev = B.make_windows(f, cal[::-1], window=5)
    np.testing.assert_array_equal(rev.X, fwd.X[::-1])
    np.testing.assert_array_equal(rev.base_dates, cal[::-1].to_numpy())


# ---------- (g) lịch CME và NYSE ----------


def test_cme_and_nyse_windows_differ_exactly_at_calendar_difference():
    # 2018-12-05: NYSE đóng cửa (quốc tang), CME vẫn có phiên
    extra = pd.Timestamp("2018-12-05")
    assert extra in calendars.sessions("CME") and extra not in calendars.sessions("NYSE")
    cme = _prices("wti", "2018-11-01", "2019-01-31", seed=10)
    by_date = cme.set_index("date")["price"]
    nyse = _prices("gold", "2018-11-01", "2019-01-31")
    nyse["price"] = by_date.reindex(nyse["date"]).to_numpy()  # cùng giá ở các ngày chung
    fc, fn = B.build_feature_frame(cme, "wti"), B.build_feature_frame(nyse, "gold")

    t = pd.Timestamp("2018-12-10")
    bc, bn = B.make_windows(fc, [t], window=5), B.make_windows(fn, [t], window=5)
    sc, sn = (
        pd.DatetimeIndex(bc.input_session_dates[0]),
        pd.DatetimeIndex(bn.input_session_dates[0]),
    )
    assert extra in sc and extra not in sn
    assert list(sc) == list(
        pd.to_datetime(["2018-12-04", "2018-12-05", "2018-12-06", "2018-12-07", t])
    )
    assert list(sn) == list(
        pd.to_datetime(["2018-12-03", "2018-12-04", "2018-12-06", "2018-12-07", t])
    )
    rc, rn = bc.X[0, :, 0], bn.X[0, :, 0]
    px = by_date
    assert rc[2] == pytest.approx(math.log(px["2018-12-06"] / px["2018-12-05"]))
    assert rn[2] == pytest.approx(math.log(px["2018-12-06"] / px["2018-12-04"]))  # qua ngày CME
    np.testing.assert_array_equal(rc[3:], rn[3:])  # sau chỗ khác lịch thì giống hệt

    # xa ngày khác lịch: cửa sổ trùng nhau
    far = pd.Timestamp("2019-01-31")
    a, b = B.make_windows(fc, [far], window=20), B.make_windows(fn, [far], window=20)
    np.testing.assert_array_equal(a.X, b.X)
    np.testing.assert_array_equal(a.input_session_dates, b.input_session_dates)


# ---------- (h) published_at ----------


def test_available_at_and_max_input_published_at():
    p = _prices("gold", "2019-01-01", "2019-06-30", seed=11)
    cal = calendars.sessions("NYSE", "2019-01-01", "2019-06-30")
    late = pd.Timestamp("2019-06-10 18:30", tz="UTC")  # giá cal[90] được công bố trễ
    p.loc[p["date"] == cal[90], "published_at"] = late
    f = B.build_feature_frame(p, "gold").set_index("feature_session_date")
    # feature kết thúc ở cal[90] và cal[91] dùng giá cal[90] → lấy max của 2 giá
    assert f.loc[cal[90], "feature_available_at"] == late
    assert f.loc[cal[91], "feature_available_at"] == late
    assert f.loc[cal[92], "feature_available_at"] == (
        cal[92].tz_localize("UTC") + pd.Timedelta(days=1, hours=12)
    )
    assert pd.isna(f.loc[cal[0], "feature_available_at"])

    b = B.make_windows(f.reset_index()[B.FRAME_COLUMNS], [cal[95], cal[100]], window=5)
    assert b.max_input_published_at.dtype == np.dtype("datetime64[ns]")  # UTC, không múi giờ
    # cửa sổ tại cal[95] dùng giá cal[90..95] → max là late
    assert b.max_input_published_at[0] == np.datetime64(late.tz_localize(None))
    expected = (cal[100] + pd.Timedelta(days=1, hours=12)).to_datetime64()
    assert b.max_input_published_at[1] == expected


def test_missing_published_at_fails_closed():
    p = _prices("gold", "2019-01-01", "2019-06-30", seed=14)
    cal = calendars.sessions("NYSE", "2019-01-01", "2019-06-30")
    p.loc[p["date"] == cal[95], "published_at"] = pd.NaT  # giá hợp lệ, không rõ lúc công bố
    f = B.build_feature_frame(p, "gold")
    row = f.set_index("feature_session_date")
    # giá cal[95] được dùng bởi feature kết thúc ở cal[95] và cal[96]
    for u in (cal[95], cal[96]):
        assert not row.loc[u, "feature_valid"]
        assert row.loc[u, "feature_reason"] == B.FRAME_REASON_MISSING_PUBLISHED
        assert np.isnan(row.loc[u, "log_return_1_end"])
        assert pd.isna(row.loc[u, "feature_available_at"])
    assert row.loc[cal[97], "feature_valid"]

    b = B.make_windows(f, [cal[96], cal[100], cal[110]], window=10)
    assert list(b.valid) == [False, False, True]
    assert b.reason[0] == b.reason[1] == B.REASON_INVALID_WINDOW
    assert np.isnat(b.max_input_published_at[:2]).all()


def test_valid_window_always_has_published_at():
    p = _prices("wti", "2018-06-01", "2019-12-31", seed=15)
    cal = calendars.sessions("CME", "2018-06-01", "2019-12-31")
    p.loc[p["date"] == cal[120], "published_at"] = pd.NaT
    p.loc[p["date"] == cal[200], "price"] = -1.0
    p = _drop(p, cal[300])
    f = B.build_feature_frame(p, "wti")
    b = B.make_windows(f, cal, window=20)
    assert b.valid.any() and (~b.valid).any()
    assert not np.isnat(b.max_input_published_at[b.valid]).any()
    assert np.isnat(b.max_input_published_at[~b.valid]).all()

    # frame bị sửa tay (feature_valid=True nhưng thiếu thời điểm công bố) vẫn không cho cửa sổ hợp lệ
    tampered = f.copy()
    tampered.loc[tampered["feature_session_date"] == cal[250], "feature_available_at"] = pd.NaT
    bt = B.make_windows(tampered, [cal[250], cal[260]], window=20)
    assert not bt.valid.any() and (bt.reason == B.REASON_INVALID_WINDOW).all()


# ---------- latest_base_date (Lambda predict) ----------


def test_latest_base_date_does_not_fall_back_to_older_session():
    p = _prices("gold", "2019-01-01", "2019-06-30", seed=12)
    cal = calendars.sessions("NYSE", "2019-01-01", "2019-06-30")
    f = B.build_feature_frame(_drop(p, cal[-2]), "gold")  # giá phiên cuối có, phiên trước thiếu
    base = B.latest_base_date(f)
    assert base == cal[-1]
    b = B.make_windows(f, [base], window=B.DEFAULT_WINDOW)
    assert not b.valid[0] and b.reason[0] == B.REASON_INVALID_WINDOW
    # dữ liệu đủ thì cửa sổ mới nhất hợp lệ
    f_ok = B.build_feature_frame(p, "gold")
    assert B.make_windows(f_ok, [B.latest_base_date(f_ok)]).valid[0]


# ---------- lỗi của caller ----------


def test_caller_errors():
    p = _prices("wti", "2019-01-01", "2019-06-30")
    f = B.build_feature_frame(p, "wti")
    with pytest.raises(ValueError, match="not a CME session"):
        B.make_windows(f, ["2019-01-05"], window=5)  # thứ Bảy
    with pytest.raises(ValueError, match="duplicate"):
        B.make_windows(f, ["2019-03-01", "2019-03-01"], window=5)
    holed = B.build_feature_frame(_drop(p, "2019-02-14"), "wti")
    with pytest.raises(ValueError, match="every calendar session"):
        B.make_windows(holed[holed["feature_valid"]], ["2019-03-01"], window=5)  # đã lọc dòng
    with pytest.raises(ValueError, match="window"):
        B.make_windows(f, ["2019-03-01"], window=0)
    with pytest.raises(ValueError, match="unknown asset"):
        B.build_feature_frame(p, "copper")
    with pytest.raises(ValueError, match="not CME sessions"):
        bad = p.copy()
        bad.loc[0, "date"] = pd.Timestamp("2019-01-05")
        B.build_feature_frame(bad, "wti")


def test_empty_base_dates():
    f = B.build_feature_frame(_prices("gold", "2019-01-01", "2019-03-31"), "gold")
    b = B.make_windows(f, [], window=5)
    assert len(b) == 0 and b.X.shape == (0, 5, len(B.FEATURE_NAMES))


# ---------- (i) import nhẹ cho Lambda predict ----------


def test_import_does_not_pull_heavy_modules():
    code = (
        "import sys, src.features.build; "
        "print(','.join(m for m in ('torch', 'scipy', 'PyEMD', 'sklearn', 'statsmodels') "
        "if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT
    )
    assert out.stdout.strip() == ""

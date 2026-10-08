"""Lịch phiên, chuẩn hóa, các flag và kiểm tra chất lượng (không gọi mạng)."""

import pandas as pd
import pytest

from src.data import calendars, clean, quality
from src.data.config import ASSETS, REFERENCES

NOW = pd.Timestamp("2026-10-07 08:00", tz="UTC")


def _bars(dates, close, open_=None):
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    close = list(close)
    return pd.DataFrame(
        {
            "open": open_ if open_ is not None else [c * 1.001 for c in close],
            "high": close,
            "low": close,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )


def _flags(df, date):
    return clean.split_flags(df.loc[df["date"] == pd.Timestamp(date), "flag"].iloc[0])


# ---------- lịch ----------


@pytest.mark.parametrize("cal", ["CME", "NYSE"])
@pytest.mark.parametrize("day", ["2023-11-23", "2025-04-18", "2025-12-25"])
def test_calendars_close_on_thanksgiving_good_friday_christmas(cal, day):
    assert not calendars.is_session(cal, [day]).iloc[0]


def test_cme_keeps_black_friday_and_mourning_day_with_trading():
    s = calendars.is_session("CME", ["2023-11-24", "2024-12-24", "2025-01-09"])
    assert s.all()


def test_roll_days_match_known_expiries():
    days = calendars.sessions("CME", "2020-04-01", "2020-04-30")
    rolls = calendars.roll_days("CL", days)
    assert pd.Timestamp("2020-04-22") in rolls  # sau đáo hạn 21/4/2020
    assert days[0] not in rolls  # đáo hạn trước phiên đầu tiên không tạo roll
    # BZ=F 2012: phiên bị thiếu 14/9 và 17/9 là ngay sau đáo hạn 13/9 (lịch ICE cũ)
    assert pd.Timestamp("2012-09-13") in calendars.bz_expiries("2012-09-01", "2012-09-30")
    assert pd.Timestamp("2016-01-29") in calendars.bz_expiries("2016-01-01", "2016-02-28")


# ---------- clean: loại và đánh dấu theo dòng ----------


def test_future_bar_on_thanksgiving_is_rejected_as_exchange_holiday():
    b = _bars(["2023-11-22", "2023-11-23", "2023-11-24"], [80, 80.5, 81])
    acc, rej = clean.bars_to_long(b, ASSETS["brent"], "yfinance", NOW)
    assert pd.Timestamp("2023-11-23") not in set(acc["date"])
    assert _flags(rej, "2023-11-23") == {"exchange_holiday"}


def test_etf_bar_on_good_friday_and_weekend_rejected():
    b = _bars(["2025-04-17", "2025-04-18", "2025-04-19", "2025-04-21"], [300, 301, 302, 303])
    acc, rej = clean.bars_to_long(b, ASSETS["gold"], "yfinance", NOW)
    assert list(acc["date"].dt.strftime("%Y-%m-%d")) == ["2025-04-17", "2025-04-21"]
    assert _flags(rej, "2025-04-18") == {"exchange_holiday"}
    assert _flags(rej, "2025-04-19") == {"weekend"}


def test_vnd_out_of_range_is_bad_value_and_fx_keeps_holidays():
    b = _bars(["2013-07-05", "2013-07-08", "2013-12-25"], [21000, 21.175, 21100])
    acc, rej = clean.bars_to_long(b, ASSETS["usd_vnd"], "yfinance", NOW)
    assert _flags(rej, "2013-07-08") == {"bad_value"}
    assert pd.Timestamp("2013-12-25") in set(acc["date"])  # FX không dùng lịch sàn


def test_wti_negative_kept_other_negative_rejected():
    b = _bars(["2020-04-17", "2020-04-20", "2020-04-21"], [18.27, -37.63, -1.0])
    acc, rej = clean.bars_to_long(b, ASSETS["wti"], "yfinance", NOW)
    assert "negative_price" in _flags(acc, "2020-04-20")
    assert acc.loc[acc["date"] == "2020-04-20", "price"].iloc[0] == -37.63
    assert _flags(rej, "2020-04-21") == {"bad_value"}


def test_low_liquidity_only_for_futures():
    b = _bars(["2015-03-02", "2015-03-03"], [60, 61], open_=[60, 60.5])
    acc, _ = clean.bars_to_long(b, ASSETS["brent"], "yfinance", NOW)
    assert _flags(acc, "2015-03-02") == {"low_liquidity"} and _flags(acc, "2015-03-03") == set()
    acc2, _ = clean.bars_to_long(b, ASSETS["gold"], "yfinance", NOW)
    assert _flags(acc2, "2015-03-02") == set()


def test_incomplete_bar_of_today_new_york_is_dropped_not_rejected():
    b = _bars(["2026-10-05", "2026-10-06", "2026-10-07"], [89, 89.4, 89.5])
    acc, rej = clean.bars_to_long(b, ASSETS["wti"], "yfinance", NOW)  # 04:00 NY ngày 7/10
    assert acc["date"].max() == pd.Timestamp("2026-10-06") and rej.empty


def test_published_at_rules():
    b = _bars(["2020-04-09"], [159.5])
    acc, _ = clean.bars_to_long(b, ASSETS["gold"], "yfinance", NOW)
    assert acc["published_at"].iloc[0] == pd.Timestamp("2020-04-10 12:00", tz="UTC")
    assert acc["source"].iloc[0] == "yfinance" and _flags(acc, "2020-04-09") == set()
    ref, _ = clean.bars_to_long(b, REFERENCES["rwtc"], "eia", NOW)
    assert ref["published_at"].iloc[0] == pd.Timestamp("2020-04-16 12:00", tz="UTC")


def test_eia_holiday_row_is_only_marked():
    b = _bars(["2024-12-24", "2024-12-25", "2024-12-26"], [74, 74.5, 75])
    acc, rej = clean.bars_to_long(b, REFERENCES["rbrte"], "eia", NOW)
    assert rej.empty and _flags(acc, "2024-12-25") == {"suspect_holiday_row"}


def test_merge_overrides_by_key_and_keeps_ingested_at_when_unchanged():
    t1, t2 = NOW, NOW + pd.Timedelta(days=1)
    old, _ = clean.bars_to_long(
        _bars(["2020-04-08", "2020-04-09"], [150, 151]), ASSETS["gold"], "yfinance", t1
    )
    new, _ = clean.bars_to_long(
        _bars(["2020-04-09", "2020-04-13"], [151, 152]), ASSETS["gold"], "yfinance", t2
    )
    m = clean.merge_snapshot(old, new, new[clean.KEY])
    assert len(m) == 3
    assert m.loc[m["date"] == "2020-04-09", "ingested_at"].iloc[0] == t1  # không đổi giá
    assert m.loc[m["date"] == "2020-04-13", "ingested_at"].iloc[0] == t2
    new2 = new.copy()
    new2.loc[new2["date"] == "2020-04-09", "price"] = 151.5  # nguồn sửa giá → ghi đè
    m2 = clean.merge_snapshot(old, new2, new2[clean.KEY])
    row = m2[m2["date"] == "2020-04-09"].iloc[0]
    assert row["price"] == 151.5 and row["ingested_at"] == t2


# ---------- quality: cờ theo chuỗi ----------


def _long(asset, dates, prices, src="yfinance"):
    spec = {**ASSETS, **REFERENCES}[asset]
    acc, _ = clean.bars_to_long(_bars(dates, prices), spec, src, NOW)
    return acc


def test_stale_is_marked_from_third_identical_session_and_is_causal():
    d = pd.bdate_range("2019-03-04", periods=6)
    p = [23200, 23200, 23200, 23200, 23210, 23210]
    s = pd.Series(p, index=d)
    m = quality.stale_mask(s)
    assert m.tolist() == [False, False, True, True, False, False]
    longer = pd.concat([s, pd.Series([23210], index=[d[-1] + pd.offsets.BDay()])])
    assert (
        quality.stale_mask(longer)[: len(s)].tolist() == m.tolist()
    )  # thêm tương lai không đổi quá khứ
    prices = _long("usd_vnd", d, p)
    flagged = quality.apply_series_flags(prices, clean.empty_frame())
    assert len(flagged) == 6  # chỉ đánh dấu, không loại


def test_spike_mask_needs_revert_and_rejects_only_flagged_assets():
    d = pd.bdate_range("2019-03-04", periods=6)
    # spike ngày 6/3; ngày 11/3 chưa có phiên t+1 nên chưa xét
    s = pd.Series([23200, 23210, 23900, 23205, 23215, 23900], index=d)
    assert quality.spike_mask(s, 0.02).tolist() == [False, False, True, False, False, False]
    step = pd.Series([23200, 23210, 23900, 23910, 23905], index=d[:5])  # tăng hẳn, không quay về
    assert not quality.spike_mask(step, 0.02).any()
    prices = pd.concat(
        [_long("usd_vnd", d, list(s)), _long("gold", d, [150, 150, 170, 150, 150, 150])],
        ignore_index=True,
    )
    kept, spikes = quality.reject_spikes(prices)
    assert list(spikes["asset"]) == ["usd_vnd"] and spikes["date"].iloc[0] == d[2]
    assert clean.split_flags(spikes["flag"].iloc[0]) == {"bad_value", "spike"}
    assert len(kept) == len(prices) - 1


def test_jump_flag_respects_known_events():
    d = ["2013-04-11", "2013-04-12", "2013-04-15", "2013-04-16", "2013-04-17"]
    prices = _long("gold", d, [150, 149, 135, 136, 120], "yfinance")
    f = quality.apply_series_flags(prices, clean.empty_frame())
    assert "jump" not in _flags(f, "2013-04-15")  # sự kiện đã biết
    assert "jump" in _flags(f, "2013-04-17")


def test_roll_and_crosschecks():
    d = calendars.sessions("CME", "2020-04-14", "2020-04-24")
    wti = [20.0] * len(d)
    brent = [28.0] * len(d)
    i = list(d).index(pd.Timestamp("2020-04-23"))
    brent[i] = 28.0 * 1.12  # phần dư 12% so với WTI
    prices = pd.concat([_long("wti", d, wti), _long("brent", d, brent)], ignore_index=True)
    rwtc = [20.0] * len(d)
    rwtc[list(d).index(pd.Timestamp("2020-04-16"))] = 21.0  # lệch 4,8% → xcheck_level
    refs = _long("rwtc", d, rwtc, "eia")
    f = quality.apply_series_flags(prices, refs)
    wti_f = f[f["asset"] == "wti"]
    assert "roll" in _flags(wti_f, "2020-04-22")
    assert "xcheck_level" in _flags(wti_f, "2020-04-16")
    assert "xcheck_resid" in _flags(f[f["asset"] == "brent"], "2020-04-23")


def test_known_source_error_excluded_from_crosscheck():
    d = calendars.sessions("CME", "2026-09-22", "2026-09-29")
    prices = _long("wti", d, [92.0] * len(d))
    r = [92.0] * len(d)
    r[list(d).index(pd.Timestamp("2026-09-25"))] = 85.23
    refs = _long("rwtc", d, r, "eia")
    assert "known_source_error" in _flags(refs, "2026-09-25")
    f = quality.apply_series_flags(prices, refs)
    assert "xcheck_level" not in _flags(f, "2026-09-25")


def test_series_flags_are_recomputed_not_accumulated():
    d = pd.bdate_range("2019-03-04", periods=4)
    prices = _long("usd_vnd", d, [23200] * 4)
    once = quality.apply_series_flags(prices, clean.empty_frame())
    twice = quality.apply_series_flags(once, clean.empty_frame())
    pd.testing.assert_frame_equal(once, twice)


def test_display_factor_is_causal():
    d = calendars.sessions("NYSE", "2020-03-02", "2020-05-29")
    gld = _long("gold", d, [150 + i * 0.1 for i in range(len(d))], "yfinance")
    gc = _long("gc_fut", d, [1600 + i for i in range(len(d))])
    full = quality.display_factors(gld, gc)
    cut = d[40]
    short = quality.display_factors(gld[gld["date"] <= cut], gc[gc["date"] <= cut])
    a = full[full["date"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, short.reset_index(drop=True))
    assert (full["reliability"] == "normal").all()


def test_report_has_gaps_flags_and_missing_sessions():
    d = list(calendars.sessions("NYSE", "2020-03-02", "2020-04-30"))
    d = d[:10] + d[17:]  # bỏ 7 phiên → khoảng trống > 4 ngày làm việc
    prices = quality.apply_series_flags(
        _long("gold", d, [150.0] * len(d), "yfinance"), clean.empty_frame()
    )
    rep = quality.build_report(
        prices,
        clean.empty_frame(),
        clean.empty_frame(),
        quality.display_factors(prices, clean.empty_frame()),
        None,
    )
    g = rep["assets"]["gold"]
    assert g["gaps_gt_4_bdays"] and g["missing_sessions"] == 7
    assert rep["assets"]["gold"]["flags"]["stale"] == len(d) - 2
    assert rep["nbp"] == {"status": "skipped"}

"""Lịch phiên giao dịch (pandas_market_calendars) và ngày đáo hạn hợp đồng để gắn flag roll.

- NYSE: ETF (GLD, SLV).
- CME: ngày có settlement của năng lượng/kim loại = ngày hợp lệ của CMEGlobex_EnergyAndMetals,
  trừ các ngày Globex chỉ mở rút ngắn mà NYSE nghỉ (Thanksgiving, 4/7, MLK...): những ngày này
  không có settlement, giao dịch tính cho phiên sau. Black Friday, 24/12 vẫn có settlement.
- ICE: lịch IEPA (ICE Futures Europe) cho RBRTE.
- FX: thứ Hai – thứ Sáu.
"""

from __future__ import annotations

import warnings
from functools import cache

import pandas as pd
import pandas_market_calendars as mcal

_CAL_START, _CAL_END = "2010-01-01", "2030-12-31"


def _naive(idx) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(idx)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.normalize()


@cache
def _sessions(name: str) -> pd.DatetimeIndex:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if name == "FX":
            return pd.bdate_range(_CAL_START, _CAL_END)
        if name == "NYSE":
            return _naive(mcal.get_calendar("NYSE").valid_days(_CAL_START, _CAL_END))
        if name == "ICE":
            return _naive(mcal.get_calendar("IEPA").valid_days(_CAL_START, _CAL_END))
        if name == "CME":
            cal = mcal.get_calendar("CMEGlobex_EnergyAndMetals")
            valid = _naive(cal.valid_days(_CAL_START, _CAL_END))
            early = _naive(cal.early_closes(cal.schedule(_CAL_START, _CAL_END)).index)
            nyse = _sessions("NYSE")
            holiday_early = early[~early.isin(nyse) & (early.dayofweek < 5)]
            return valid.difference(holiday_early)
    raise ValueError(f"unknown calendar {name}")


def sessions(name: str, start=None, end=None) -> pd.DatetimeIndex:
    s = _sessions(name)
    if start is not None:
        s = s[s >= pd.Timestamp(start)]
    if end is not None:
        s = s[s <= pd.Timestamp(end)]
    return s


def last_session_on_or_before(name: str, day) -> pd.Timestamp:
    """Phiên cuối của lịch `name` có ngày <= `day`. Nhận tham số thường (tên lịch, ngày)."""
    return pd.Timestamp(sessions(name, end=day)[-1])


def expected_latest_session(name: str, run_dt) -> pd.Timestamp:
    """Phiên mới nhất mà snapshot clean ngày `run_dt` (ngày UTC của lần ingest) phải có.

    Là phiên cuối <= run_dt − 1 ngày: thanh của chính ngày run_dt chưa chốt nên clean loại
    (incomplete_bar, theo ngày New York; lịch chạy 12:15 UTC thì ngày New York trùng run_dt).
    Dùng chung cho ingest (kiểm tra phiên cuối trễ, INGEST_STALE) và predict
    (expected_base_date, lý do latest_session_missing) để hai bên luôn cùng một mốc.
    """
    return last_session_on_or_before(name, pd.Timestamp(run_dt) - pd.Timedelta(1, "D"))


def is_session(name: str, dates) -> pd.Series:
    d = _naive(dates)
    return pd.Series(d.isin(_sessions(name)), index=d)


def _contract_months(start: str, end: str) -> pd.PeriodIndex:
    return pd.period_range(
        pd.Timestamp(start) - pd.DateOffset(months=1),
        pd.Timestamp(end) + pd.DateOffset(months=3),
        freq="M",
    )


def cl_expiries(start: str, end: str) -> pd.DatetimeIndex:
    """WTI (CL): giao dịch kết thúc 3 ngày làm việc trước ngày 25 của tháng trước tháng hợp đồng;
    nếu ngày 25 không phải ngày làm việc thì 4 ngày làm việc trước ngày 25."""
    bd = _sessions("CME")
    out = []
    for m in _contract_months(start, end):
        prev = m - 1
        d25 = pd.Timestamp(prev.year, prev.month, 25)
        k = int(bd.searchsorted(d25))  # số phiên < 25
        out.append(bd[k - 3] if d25 in bd else bd[k - 4])
    return pd.DatetimeIndex(sorted(set(out)))


def bz_expiries(start: str, end: str) -> pd.DatetimeIndex:
    """Brent (BZ, theo lịch ICE Brent):
    - Hợp đồng từ tháng 3/2016: ngày làm việc cuối của tháng thứ hai trước tháng hợp đồng.
    - Trước đó: ngày làm việc ngay trước ngày thứ 15 trước ngày đầu tháng hợp đồng
      (nếu ngày thứ 15 không phải ngày làm việc thì lấy ngày làm việc liền trước nó làm mốc).
    Xấp xỉ ngày làm việc London bằng lịch CME; đã khớp với các phiên BZ=F bị thiếu 2012–2013."""
    bd = _sessions("CME")
    out = []
    for m in _contract_months(start, end):
        if m >= pd.Period("2016-03", freq="M"):
            p2 = m - 2
            last = pd.Timestamp(p2.year, p2.month, 1) + pd.offsets.MonthEnd(0)
            out.append(bd[int(bd.searchsorted(last, side="right")) - 1])
        else:
            d15 = pd.Timestamp(m.year, m.month, 1) - pd.Timedelta(days=15)
            k = int(bd.searchsorted(d15))
            ref_pos = k if d15 in bd else k - 1
            out.append(bd[ref_pos - 1])
    return pd.DatetimeIndex(sorted(set(out)))


def roll_days(rule: str, dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Phiên đầu tiên của chuỗi sau mỗi ngày đáo hạn: return phiên này nối hai hợp đồng."""
    dates = _naive(dates).sort_values()
    if len(dates) == 0:
        return dates
    start, end = str(dates[0].date()), str(dates[-1].date())
    exp = cl_expiries(start, end) if rule == "CL" else bz_expiries(start, end)
    exp = exp[exp >= dates[0]]  # đáo hạn trước phiên đầu tiên không tạo roll trong chuỗi
    pos = dates.searchsorted(exp, side="right")
    pos = pos[pos < len(dates)]
    return pd.DatetimeIndex(sorted(set(dates[pos])))

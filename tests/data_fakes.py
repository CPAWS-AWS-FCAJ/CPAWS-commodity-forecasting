"""Nguồn giả cho test pipeline giá (không gọi mạng)."""

from __future__ import annotations

import zlib

import numpy as np
import pandas as pd


class FakeResponse:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    """Trả lần lượt các phản hồi; ghi lại url, params, headers của từng lần gọi."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.headers: dict = {}

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(self.headers)})
        r = self.responses.pop(0)
        return r(url, params) if callable(r) else r


BASE = {
    "GLD": 150.0,
    "SLV": 15.0,
    "CL=F": 30.0,
    "BZ=F": 33.0,
    "VND=X": 23_200.0,
    "GC=F": 1600.0,
    "SI=F": 16.0,
}


def synthetic_bars(symbol: str, start: str, end: str, seed: int = 0) -> pd.DataFrame:
    """Thanh ngày T2–T6 (gồm cả ngày lễ, để test loại thanh) với index có múi giờ như yfinance."""
    days = pd.bdate_range(start, end)
    rng = np.random.default_rng(zlib.crc32(symbol.encode()) + seed)
    vol = 0.001 if symbol == "VND=X" else 0.01  # tỷ giá VND dao động khoảng 0,1%/ngày
    p = BASE[symbol] * np.exp(np.cumsum(rng.normal(0, vol, len(days))))
    tz = "Europe/London" if symbol == "VND=X" else "America/New_York"
    df = pd.DataFrame(
        {"Open": p * 1.001, "High": p * 1.01, "Low": p * 0.99, "Close": p, "Volume": 1000.0},
        index=days.tz_localize(tz),
    )
    if symbol == "CL=F" and pd.Timestamp("2020-04-20") in days:
        df.loc[pd.Timestamp("2020-04-20", tz=tz), ["Open", "Close"]] = [-35.0, -37.63]
    return df


class FakeYF:
    """history_fn giả cho YFinanceSource; end mặc định cố định để kết quả tái lập được."""

    def __init__(
        self,
        end: str = "2020-05-29",
        fail: set[str] | None = None,
        spikes: dict[str, str] | None = None,
        empty: set[str] | None = None,
        ends: dict[str, str] | None = None,
    ):
        self.end = end
        # {symbol: ngày}: mã này chỉ có dữ liệu tới ngày đó (giả lập Yahoo trễ phiên)
        self.ends = ends or {}
        self.fail = fail or set()
        self.empty = empty or set()  # mã trả về bảng rỗng (yfinance khi bị chặn hoặc đổi mã)
        # {symbol: ngày hoặc list ngày}: nhân Close các ngày đó lên 5% (spike một hay nhiều phiên)
        self.spikes = spikes or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, symbol, start, end=None):
        self.calls.append((symbol, start))
        if symbol in self.fail:
            raise ConnectionError("blocked")
        df = synthetic_bars(symbol, "2020-03-02", self.ends.get(symbol, self.end))
        if symbol in self.empty:
            return df.iloc[0:0]
        if symbol in self.spikes:
            days = self.spikes[symbol]
            days = [days] if isinstance(days, str) else days
            df.loc[df.index.tz_localize(None).isin(pd.DatetimeIndex(days)), "Close"] *= 1.05
        return df[df.index.tz_localize(None) >= pd.Timestamp(start)]


class FakeEIA:
    name = "eia"

    def __init__(self, end: str = "2020-05-29"):
        self.end = end

    def fetch(self, symbol, start, end=None):
        from src.data.sources import FetchResult, finalize_bars

        src = "CL=F" if symbol == "RWTC" else "BZ=F"
        df = synthetic_bars(src, "2020-03-02", self.end)
        df.index = df.index.tz_localize(None)
        df = df[df.index >= pd.Timestamp(start)].rename(columns=str.lower)
        return FetchResult("eia", symbol, finalize_bars(df[["close"]]), b"[]", f"{symbol}.json.gz")

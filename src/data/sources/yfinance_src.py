"""yfinance: CL=F, BZ=F, VND=X (nguồn chính), GLD/SLV (dự phòng), GC=F/SI=F (hệ số hiển thị).

Index yfinance là 00:00 theo múi giờ sàn (America/New_York cho hợp đồng tương lai và ETF,
Europe/London cho VND=X); bỏ múi giờ để giữ ngày giao dịch. Không điều chỉnh giá (auto_adjust=False).
API không chính thức, điều khoản Yahoo chỉ cho dùng cá nhân (ADR-0005).
"""

from __future__ import annotations

import gzip
from collections.abc import Callable

import pandas as pd

from . import FetchResult, SourceError, finalize_bars

HistoryFn = Callable[[str, str, str | None], pd.DataFrame]


def _default_history(symbol: str, start: str, end: str | None) -> pd.DataFrame:
    import yfinance as yf

    return yf.Ticker(symbol).history(
        start=start, end=end, interval="1d", auto_adjust=False, actions=False
    )


class YFinanceSource:
    name = "yfinance"

    def __init__(self, history_fn: HistoryFn | None = None):
        self.history_fn = history_fn or _default_history

    def fetch(self, symbol: str, start: str, end: str | None = None) -> FetchResult:
        try:
            df = self.history_fn(symbol, start, end)
        except Exception as e:  # yfinance ném nhiều loại lỗi khác nhau
            raise SourceError(f"yfinance {symbol}: {type(e).__name__}: {e}") from e
        if df is None or df.empty:
            raise SourceError(f"yfinance {symbol}: empty response")
        raw = gzip.compress(df.to_csv().encode("utf-8"))
        bars = df.rename(columns=str.lower)
        idx = pd.DatetimeIndex(bars.index)
        bars.index = idx.tz_localize(None) if idx.tz is not None else idx
        safe = symbol.replace("=", "_")
        return FetchResult(self.name, symbol, finalize_bars(bars), raw, f"{safe}.csv.gz")

"""Adapter theo nguồn. Mỗi adapter trả về FetchResult với bảng thanh ngày đã chuẩn hóa
(index = ngày giao dịch, không múi giờ; cột open, high, low, close, volume) và phản hồi thô.
Đổi nguồn chỉ cần viết adapter mới; clean/quality không phụ thuộc nguồn."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]


class SourceError(RuntimeError):
    """Nguồn trả lỗi hoặc dữ liệu rỗng."""


@dataclass
class FetchResult:
    source: str
    symbol: str
    bars: pd.DataFrame
    raw: bytes
    raw_name: str  # tên file thô, ví dụ "GLD.json.gz"
    n_requests: int = 1


def empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=BAR_COLUMNS, index=pd.DatetimeIndex([], name="date"), dtype=float)


def finalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Chuẩn hóa: index ngày naive tên 'date', đủ cột, sắp xếp, bỏ dòng close NaN."""
    out = df.copy()
    for c in BAR_COLUMNS:
        if c not in out:
            out[c] = float("nan")
    out = out[BAR_COLUMNS].astype(float)
    out.index = pd.DatetimeIndex(out.index).normalize()
    out.index.name = "date"
    return out[out["close"].notna()].sort_index()

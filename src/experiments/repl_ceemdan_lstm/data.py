"""Nạp giá ≤ CUTOFF và chia train theo thời gian (kế hoạch mục 2, 3.2).

Chỉ đọc dòng có `date` ≤ 2018-12-31: cắt ngay khi đọc parquet bằng filter của pyarrow, rồi kiểm
lại ngày lớn nhất của cả prices lẫn rejected. Không có hàm nào ở đây trả về dữ liệu từ 2019.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import calendars, storage
from src.data.config import ASSETS as ASSET_SPECS
from src.features import ceemdan_cache as cc

from . import config as C

CUT = pd.Timestamp(C.CUTOFF)


class CutoffError(RuntimeError):
    """Đọc được dòng sau CUTOFF: điều kiện dừng của thí nghiệm."""


@dataclass(frozen=True)
class CleanData:
    clean_dt: str
    prices: pd.DataFrame  # dòng được giữ, date ≤ CUTOFF
    rejected: pd.DataFrame  # dòng bị loại, date ≤ CUTOFF
    sha256: dict[str, str]  # SHA-256 của file parquet đã đọc (cả file, để đối chiếu nguồn gốc)


@dataclass(frozen=True)
class AssetSeries:
    """Chuỗi giá một tài sản (dòng được giữ, WARMUP_START ≤ date ≤ CUTOFF)."""

    asset: str
    calendar: str
    dates: pd.DatetimeIndex
    values: np.ndarray


@dataclass(frozen=True)
class Segment:
    """Một đoạn của TRAIN. origins: ngày gốc t được giữ (t và phiên kế tiếp t + 1 cùng đoạn)."""

    name: str
    start: pd.Timestamp
    end: pd.Timestamp
    n_dates: int  # số ngày trong đoạn trước khi bỏ mẫu ở ranh giới
    origins: pd.DatetimeIndex


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_cut(path: Path, name: str) -> pd.DataFrame:
    df = pd.read_parquet(path, filters=[("date", "<=", CUT)])
    if len(df) and pd.Timestamp(df["date"].max()) > CUT:
        raise CutoffError(f"{name}: đọc được dữ liệu sau {C.CUTOFF}, dừng")
    return df


def read_clean(lake_dir: str | Path, clean_dt: str = C.CLEAN_DT) -> CleanData:
    """Đọc clean/prices/dt=<clean_dt>/ ở lake local, cắt tại CUTOFF ngay khi đọc.

    Thiếu bản clean thì báo FileNotFoundError (không tải từ S3)."""
    st = storage.LocalStorage(str(lake_dir))
    key = f"clean/prices/dt={clean_dt}"
    missing = [f for f in ("prices.parquet", "rejected.parquet") if not st.exists(f"{key}/{f}")]
    if missing:
        raise FileNotFoundError(f"thiếu {', '.join(missing)} trong {st.root / key}")
    d = st.root / key
    prices = _read_cut(d / "prices.parquet", "prices")
    rejected = _read_cut(d / "rejected.parquet", "rejected")
    sha = {f: file_sha256(d / f) for f in ("prices.parquet", "rejected.parquet")}
    return CleanData(clean_dt, prices[prices["asset"].isin(C.ASSETS)].copy(), rejected, sha)


def asset_series(prices: pd.DataFrame, asset: str) -> AssetSeries:
    """Dòng được giữ của tài sản từ WARMUP_START; có dòng sau CUTOFF thì báo lỗi (không lọc âm
    thầm). Mọi dòng phải là phiên lịch của tài sản."""
    dates, values = cc.asset_series(prices, asset)
    if len(dates) and dates.max() > CUT:
        raise CutoffError(f"{asset}: có dòng sau {C.CUTOFF}")
    keep = dates >= pd.Timestamp(C.WARMUP_START)
    dates, values = dates[keep], values[keep]
    cal = ASSET_SPECS[asset].calendar
    if not dates.isin(calendars.sessions(cal)).all():
        raise ValueError(f"{asset}: có dòng giá không phải phiên {cal}")
    return AssetSeries(asset, cal, dates, values)


def next_sessions(dates: pd.DatetimeIndex, calendar: str) -> pd.DatetimeIndex:
    """Phiên kế tiếp của từng ngày theo lịch giao dịch (không theo dòng giá kế tiếp)."""
    sess = calendars.sessions(calendar)
    pos = sess.searchsorted(pd.DatetimeIndex(dates), side="right")
    if (pos >= len(sess)).any():
        raise ValueError("ngày nằm sau cuối lịch")
    return sess[pos]


def split_train(
    dates: pd.DatetimeIndex,
    calendar: str,
    split: tuple[float, ...] = C.SPLIT,
    train: tuple[str, str] = C.TRAIN,
) -> list[Segment]:
    """Chia các ngày trong TRAIN thành ba đoạn liền nhau theo thời gian (fit / early_stop / calib).

    Kích thước đoạn tính theo số ngày trong `dates` (dòng giá được giữ); đoạn cuối nhận phần dư.
    Mẫu tại t thuộc đoạn chứa t và chỉ được giữ khi phiên kế tiếp t + 1 (theo lịch `calendar`)
    cũng nằm trong đoạn, nên target không lấn sang đoạn sau (hay sang EVAL với đoạn cuối). Nếu
    t + 1 là phiên thiếu dòng giá thì mẫu vẫn được giữ ở đây; bước dựng target sẽ loại nó.
    """
    if len(split) != len(C.SPLIT_NAMES) or not np.isclose(sum(split), 1.0):
        raise ValueError("split must have 3 parts summing to 1")
    dates = pd.DatetimeIndex(dates).sort_values()
    if dates.has_duplicates:
        raise ValueError("dates must be unique")
    dates = dates[(dates >= pd.Timestamp(train[0])) & (dates <= pd.Timestamp(train[1]))]
    n = len(dates)
    cuts = np.rint(np.cumsum(split[:-1]) * n).astype(int)
    bounds = np.concatenate([[0], cuts, [n]])
    if (np.diff(bounds) < 2).any():
        raise ValueError("each segment needs at least 2 dates")
    nxt = next_sessions(dates, calendar)
    out = []
    for name, a, b in zip(C.SPLIT_NAMES, bounds[:-1], bounds[1:], strict=True):
        seg, seg_next = dates[a:b], nxt[a:b]
        keep = seg_next <= seg[-1]
        out.append(Segment(name, seg[0], seg[-1], len(seg), seg[keep]))
    return out

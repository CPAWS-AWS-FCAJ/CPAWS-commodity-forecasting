"""Chuẩn hóa thanh giá của từng nguồn sang bảng dài và áp quy tắc loại/đánh dấu theo từng dòng.

Schema (mỗi dòng một (date, asset)):
  date (ngày giao dịch, không múi giờ), asset, price, unit, source,
  published_at (UTC), ingested_at (UTC), flag (các cờ nối bằng "|", rỗng nếu không có).

Dòng bị LOẠI (ghi sang bảng rejected, không vào prices):
  weekend, exchange_holiday (sàn đóng cả ngày theo calendars.py), bad_value (ngoài khoảng hợp lệ
  hoặc giá <= 0 không nằm trong danh sách cho phép), incomplete_bar (ngày hiện tại hoặc tương lai
  theo giờ New York: thanh chưa chốt).
Cờ CHỈ ĐÁNH DẤU theo từng dòng (giữ trong prices):
  low_liquidity (hợp đồng tương lai có close == open), negative_price (WTI 20/4/2020),
  suspect_holiday_row / known_source_error (chuỗi tham chiếu),
  stale_source (dòng cuối của tài sản có nguồn lỗi ở lần chạy gần nhất; gắn trong quality.py).
Cờ theo chuỗi (stale, jump, roll, xcheck_*) do quality.py tính lại trên toàn bộ lịch sử mỗi lần chạy.

published_at (quy tắc bảo thủ, config.PUBLISHED_AT_RULES): 00:00 UTC của date + N ngày, cộng H giờ.
  Hiện tại yfinance = 12:00 UTC ngày date+1; EIA = 12:00 UTC ngày date+7 (phát hành hằng tuần).
  Đặc trưng tại thời điểm t chỉ được dùng các dòng có published_at <= t.
"""

from __future__ import annotations

import pandas as pd

from . import calendars
from .config import (
    ALLOWED_NEGATIVE,
    KNOWN_SOURCE_ERRORS,
    NY_TZ,
    PUBLISHED_AT_RULES,
    AssetSpec,
)

COLUMNS = ["date", "asset", "price", "unit", "source", "published_at", "ingested_at", "flag"]
KEY = ["date", "asset"]
ROW_FLAGS = {
    "low_liquidity",
    "negative_price",
    "suspect_holiday_row",
    "known_source_error",
    "stale_source",  # dòng cuối của tài sản mà nguồn lỗi ở lần chạy gần nhất (ingest_prices)
}


def join_flags(flags) -> str:
    return "|".join(sorted({f for f in flags if f}))


def split_flags(flag: str) -> set[str]:
    return {f for f in str(flag).split("|") if f} if isinstance(flag, str) else set()


def empty_frame() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNS})
    return normalize_types(df)


def normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).astype("datetime64[ns]")
    for c in ("published_at", "ingested_at"):
        out[c] = pd.to_datetime(out[c], utc=True).astype("datetime64[ns, UTC]")
    out["price"] = out["price"].astype(float)
    for c in ("asset", "unit", "source", "flag"):
        out[c] = out[c].fillna("").astype(str)
    return out[COLUMNS]


def published_at(dates: pd.DatetimeIndex, source: str) -> pd.DatetimeIndex:
    days, hours = PUBLISHED_AT_RULES[source]
    d = pd.DatetimeIndex(dates).tz_localize("UTC")
    return d + pd.Timedelta(days=days) + pd.Timedelta(hours=hours)


def bars_to_long(
    bars: pd.DataFrame,
    spec: AssetSpec,
    source: str,
    now_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Trả về (accepted, rejected) theo schema COLUMNS."""
    if bars.empty:
        return empty_frame(), empty_frame()
    dates = pd.DatetimeIndex(bars.index)
    price = bars["close"].to_numpy(dtype=float)
    today_ny = pd.Timestamp(now_utc).tz_convert(NY_TZ).tz_localize(None).normalize()
    weekend = dates.dayofweek >= 5
    in_cal = (
        calendars.is_session(spec.calendar, dates).to_numpy() if spec.calendar != "FX" else ~weekend
    )
    flags: list[set[str]] = [set() for _ in range(len(dates))]
    reject: list[set[str]] = [set() for _ in range(len(dates))]
    for i, d in enumerate(dates):
        ds = str(d.date())
        if d >= today_ny:
            reject[i].add("incomplete_bar")
        if weekend[i]:
            reject[i].add("weekend")
        elif not in_cal[i]:
            # Chuỗi tham chiếu giao ngay (EIA): chỉ đánh dấu; tài sản chính: loại thanh
            (flags if spec.kind == "spot" else reject)[i].add(
                "suspect_holiday_row" if spec.kind == "spot" else "exchange_holiday"
            )
        if spec.valid_range and not (spec.valid_range[0] <= price[i] <= spec.valid_range[1]):
            reject[i].add("bad_value")
        if price[i] <= 0:
            if (spec.asset, ds) in ALLOWED_NEGATIVE:
                flags[i].add("negative_price")
            else:
                reject[i].add("bad_value")
        if spec.kind == "future" and bars["open"].iloc[i] == bars["close"].iloc[i]:
            flags[i].add("low_liquidity")
        if (spec.asset, ds) in KNOWN_SOURCE_ERRORS:
            flags[i].add("known_source_error")

    ingested = pd.Timestamp(now_utc).tz_convert("UTC")
    df = pd.DataFrame(
        {
            "date": dates,
            "asset": spec.asset,
            "price": price,
            "unit": spec.unit,
            "source": source,
            "published_at": published_at(dates, source),
            "ingested_at": ingested,
            "flag": [join_flags(f | r) for f, r in zip(flags, reject, strict=True)],
        }
    )
    rejected_mask = pd.Series([bool(r) for r in reject])
    # Thanh chưa chốt không lưu lại; các dòng loại khác giữ trong rejected để kiểm tra
    incomplete = pd.Series(["incomplete_bar" in r for r in reject])
    acc = normalize_types(df[~rejected_mask.to_numpy()])
    rej = normalize_types(df[(rejected_mask & ~incomplete).to_numpy()])
    return acc, rej


def merge_snapshot(
    prev: pd.DataFrame | None, new: pd.DataFrame, override_keys: pd.DataFrame
) -> pd.DataFrame:
    """Ghi đè theo khóa (date, asset): khóa có trong lần tải mới thay thế bản cũ.
    Giữ ingested_at cũ nếu price, source, unit không đổi (để chạy lại cho cùng kết quả)."""
    if prev is None or prev.empty:
        return _sort(normalize_types(new))
    prev = normalize_types(prev)
    keys = pd.MultiIndex.from_frame(override_keys[KEY]) if len(override_keys) else None
    pk = pd.MultiIndex.from_frame(prev[KEY])
    kept = prev[~pk.isin(keys)] if keys is not None else prev
    if not new.empty:
        old = prev.set_index(KEY)
        nk = pd.MultiIndex.from_frame(new[KEY])
        same = nk.isin(old.index)
        new = new.copy()
        if same.any():
            o = old.loc[nk[same]]
            unchanged = (
                (o["price"].to_numpy() == new.loc[same, "price"].to_numpy())
                & (o["source"].to_numpy() == new.loc[same, "source"].to_numpy())
                & (o["unit"].to_numpy() == new.loc[same, "unit"].to_numpy())
            )
            idx = new.index[same][unchanged]
            new.loc[idx, "ingested_at"] = o["ingested_at"].to_numpy()[unchanged]
    return _sort(normalize_types(pd.concat([kept, new], ignore_index=True)))


def _sort(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(KEY, kind="stable").reset_index(drop=True)

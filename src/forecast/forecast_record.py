"""Tạo bản ghi bảng DynamoDB `Forecasts` đúng docs/api/contract.md (ADR-0008).

Dùng chung cho Lambda predict (Tiến), script seed dữ liệu mẫu (Tuấn) và backtest (Long): giữ tên
hàm, tham số và kiểu dữ liệu ổn định. Hàm không tự sửa phân vị: phân vị phải đã qua
returns.normalize_quantiles() (không giảm trên từng h), nếu không báo ValueError.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

import numpy as np
import pandas as pd

from src.data import calendars
from src.data.config import ASSETS
from src.forecast.returns import QUANTILE_LEVELS, prob_up

HORIZONS = tuple(range(1, 8))  # h = 1..7 phiên giao dịch
OIL_ASSETS = frozenset({"brent", "wti"})
TARGET_SERIES = {a: ASSETS[a].primary.symbol for a in ("gold", "silver", "brent", "wti")}
PRICE_UNIT = {"gold": "USD/oz", "silver": "USD/oz", "brent": "USD/bbl", "wti": "USD/bbl"}
_SIX = Decimal("0.000001")


def to_decimal(x: float) -> Decimal:
    """Số cho DynamoDB: Decimal làm tròn 6 chữ số thập phân (ROUND_HALF_EVEN), không có -0."""
    v = float(x)
    if not np.isfinite(v):
        raise ValueError(f"non-finite number {x!r}")
    d = Decimal(repr(v)).quantize(_SIX, rounding=ROUND_HALF_EVEN)
    return d if d != 0 else Decimal("0.000000")


def target_dates(asset: str, base_date, horizons: Sequence[int] = HORIZONS) -> list[str]:
    """Phiên giao dịch thứ h sau base_date theo lịch của tài sản (NYSE cho GLD, SLV; CME cho
    BZ=F, CL=F). base_date phải là một phiên giao dịch."""
    cal = ASSETS[asset].calendar
    d = pd.Timestamp(base_date).normalize()
    sess = calendars.sessions(cal, d, d + pd.Timedelta(days=40))
    if len(sess) == 0 or sess[0] != d:
        raise ValueError(f"base_date {d.date()} is not a {cal} session for {asset}")
    if max(horizons) >= len(sess):
        raise ValueError("calendar too short for the requested horizons")
    return [str(sess[h].date()) for h in horizons]


def _iso_utc(t: datetime | None) -> str:
    t = datetime.now(UTC) if t is None else t
    if t.tzinfo is None:
        raise ValueError("created_at must be timezone-aware (UTC)")
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_str(d) -> str:
    if isinstance(d, str):
        return str(pd.Timestamp(d).date())
    if isinstance(d, (date, datetime, pd.Timestamp)):
        return str(pd.Timestamp(d).date())
    raise TypeError(f"unsupported date {d!r}")


def to_forecast_record(
    asset: str,
    base_date,
    last_price: float,
    quantiles,
    *,
    fx_usd_vnd: float,
    fx_date,
    stale_sources: Sequence[str],
    roll_in_horizon: bool,
    model_version: str,
    is_sample: bool,
    created_at: datetime | None = None,
) -> dict:
    """Một bản ghi `Forecasts` (dict sẵn sàng cho boto3 Table.put_item).

    quantiles: mảng (7 h, 7 phân vị) log return, hàng h theo HORIZONS, cột theo QUANTILE_LEVELS,
      đã chuẩn hóa (không giảm trên mỗi hàng); sai thì ValueError.
    last_price: giá tại base_date theo đơn vị hiển thị (USD/oz cho vàng, bạc; USD/bbl cho dầu).
    stale_sources: danh sách nguồn lỗi lấy từ quality.json (rỗng nếu không có).
    roll_in_horizon: chỉ dầu mới được True (vàng, bạc luôn False).
    created_at: datetime có múi giờ; mặc định thời điểm hiện tại (UTC).
    Số lưu dạng Decimal làm tròn 6 chữ số; prob_up tính bằng returns.prob_up() (nội suy tuyến
    tính, kẹp [0.05, 0.95]) trên phân vị chưa làm tròn."""
    if asset not in TARGET_SERIES:
        raise ValueError(f"unknown asset {asset!r}; expected one of {sorted(TARGET_SERIES)}")
    q = np.asarray(quantiles, dtype=float)
    if q.shape != (len(HORIZONS), len(QUANTILE_LEVELS)):
        raise ValueError(f"quantiles must have shape (7, 7) [h][q], got {q.shape}")
    if not np.all(np.isfinite(q)):
        raise ValueError("quantiles contain NaN or inf")
    if np.any(np.diff(q, axis=1) < 0):
        raise ValueError("quantiles are decreasing; call normalize_quantiles() first")
    if not (np.isfinite(last_price) and last_price > 0):
        raise ValueError("last_price must be a positive number")
    if not (np.isfinite(fx_usd_vnd) and fx_usd_vnd > 0):
        raise ValueError("fx_usd_vnd must be a positive number")
    if roll_in_horizon and asset not in OIL_ASSETS:
        raise ValueError("roll_in_horizon can only be true for brent or wti")
    if isinstance(stale_sources, str) or not all(isinstance(s, str) for s in stale_sources):
        raise TypeError("stale_sources must be a list of strings")

    base = _date_str(base_date)
    dates = target_dates(asset, base)
    horizons = [
        {
            "h": h,
            "target_date": dates[i],
            "q": [to_decimal(v) for v in q[i]],
            "prob_up": to_decimal(prob_up(q[i])),
        }
        for i, h in enumerate(HORIZONS)
    ]
    return {
        "asset": asset,
        "base_date": base,
        "created_at": _iso_utc(created_at),
        "model_version": str(model_version),
        "target_series": TARGET_SERIES[asset],
        "last_price": to_decimal(last_price),
        "price_unit": PRICE_UNIT[asset],
        "quantile_levels": [to_decimal(x) for x in QUANTILE_LEVELS],
        "horizons": horizons,
        "fx_usd_vnd": to_decimal(fx_usd_vnd),
        "fx_date": _date_str(fx_date),
        "stale_sources": list(stale_sources),
        "roll_in_horizon": bool(roll_in_horizon),
        "is_sample": bool(is_sample),
    }


__all__ = [
    "HORIZONS",
    "PRICE_UNIT",
    "TARGET_SERIES",
    "target_dates",
    "to_decimal",
    "to_forecast_record",
]

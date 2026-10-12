"""Chuyển đổi giữa giá và return, phân vị → khoảng giá, xác suất tăng, quy đổi VND.

Mô hình CPAWS dự đoán log return h ngày (không dự đoán mức giá) để tránh "độ chính xác ảo".
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

TROY_OUNCE_G = 31.1034768
LUONG_G = 37.5


def horizon_log_returns(prices, h: int) -> np.ndarray:
    """Target r[t] = ln(P[t+h] / P[t]). h cuối cùng là NaN (chưa có tương lai).
    Giá <= 0 (ví dụ WTI ngày 20/4/2020) cho NaN: loại các origin đó khi huấn luyện."""
    if h < 1:
        raise ValueError("h must be >= 1")
    p = np.asarray(prices, dtype=float)
    out = np.full(len(p), np.nan)
    a, b = p[:-h], p[h:]
    ok = (a > 0) & (b > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[:-h] = np.where(ok, np.log(b / a), np.nan)
    return out


def quantiles_to_prices(price_now: float, quantiles: Mapping[float, float]) -> dict[float, float]:
    """Phân vị log return → phân vị giá: P = P_now * exp(r). Hàm exp đơn điệu nên giữ nguyên thứ tự."""
    return {q: float(price_now * math.exp(r)) for q, r in sorted(quantiles.items())}


def prob_up(quantiles: Mapping[float, float]) -> float:
    """Xác suất return > 0, nội suy tuyến tính hàm phân phối giữa các phân vị.
    Nếu 0 nằm ngoài [q_min, q_max] thì trả về 1 - q_min hoặc 1 - q_max (giới hạn hiển thị)."""
    levels = np.array(sorted(quantiles))
    values = np.array([quantiles[q] for q in levels], dtype=float)
    if np.any(np.diff(values) < 0):
        values = np.maximum.accumulate(values)  # sửa phân vị bị cắt chéo
    if 0.0 <= values[0]:
        return float(1 - levels[0])
    if 0.0 >= values[-1]:
        return float(1 - levels[-1])
    cdf_at_zero = float(np.interp(0.0, values, levels))
    return 1.0 - cdf_at_zero


def usd_to_vnd(usd: float, usd_vnd: float) -> float:
    return float(usd * usd_vnd)


def usd_oz_to_vnd_luong(usd_per_oz: float, usd_vnd: float) -> float:
    """Giá thế giới quy đổi VND/lượng (chưa gồm thuế, phí, chênh lệch thị trường trong nước)."""
    return float(usd_per_oz * (LUONG_G / TROY_OUNCE_G) * usd_vnd)

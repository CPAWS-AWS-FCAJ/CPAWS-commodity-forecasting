"""Mốc so sánh nhân quả theo ADR-0008 mục 4 (dùng cho pinball_skill, coverage, brier_skill).

Đầu vào là chuỗi target r_h đã căn theo lịch giao dịch: kết quả của
returns.horizon_log_returns(prices, h, calendar=...) (pd.Series, mỗi phiên một dòng, NaN khi
không hợp lệ). Tại phiên t, mốc chỉ dùng các r_h(s) với s thuộc 252 phiên gần nhất tính tới t
(s ≤ t) và đã hoàn tất (s + h ≤ t), tức vị trí lịch s ∈ [t − 251, t − h]. Cần ít nhất 200 return
hợp lệ, nếu không trả NaN (điểm đánh giá đó bị bỏ cho mọi chỉ số dùng mốc này).

Hàm công khai dùng chung với metrics/backtest (Long) và Lambda predict (Tiến): giữ tên và kiểu.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from src.forecast.returns import QUANTILE_LEVELS

WINDOW = 252
MIN_OBS = 200


def _completed_window(r_h: pd.Series, h: int, window: int):
    """Rolling trên các r_h(s) với s ∈ [t − window + 1, t − h] (theo vị trí lịch)."""
    if h < 1:
        raise ValueError("h must be >= 1")
    if window <= h:
        raise ValueError("window must be > h")
    if not isinstance(r_h, pd.Series):
        raise TypeError("r_h must be a pd.Series on the trading calendar")
    # giá trị tại t của chuỗi dịch là r_h(t − h); cửa sổ dài window − h phủ s = t−window+1 .. t−h
    return r_h.astype(float).shift(h), window - h


def quantile_baseline(
    r_h: pd.Series,
    h: int,
    levels: Sequence[float] = QUANTILE_LEVELS,
    window: int = WINDOW,
    min_obs: int = MIN_OBS,
) -> pd.DataFrame:
    """Mốc phân phối 252 phiên: tại mỗi t, các phân vị thực nghiệm (nội suy tuyến tính, như
    np.quantile mặc định) của r_h(s) hợp lệ, đã hoàn tất. Trả DataFrame cùng index với r_h, mỗi
    cột một mức trong `levels`; NaN cả dòng khi có ít hơn min_obs return hợp lệ."""
    shifted, w = _completed_window(r_h, h, window)
    roll = shifted.rolling(w, min_periods=min_obs)
    out = pd.DataFrame({float(q): roll.quantile(q, interpolation="linear") for q in levels})
    out.index = r_h.index
    return out


def up_rate_baseline(
    r_h: pd.Series, h: int, window: int = WINDOW, min_obs: int = MIN_OBS
) -> pd.Series:
    """Tần suất tăng 252 phiên: tỷ lệ r_h(s) > 0 trên cùng tập s như quantile_baseline (NaN không
    tính là tăng hay giảm); NaN khi ít hơn min_obs return hợp lệ."""
    shifted, w = _completed_window(r_h, h, window)
    up = (shifted > 0).astype(float).where(shifted.notna())
    return up.rolling(w, min_periods=min_obs).mean().rename(f"up_rate_{h}")


def constant_prob_baseline(index: pd.Index, p: float = 0.5) -> pd.Series:
    """Mốc xác suất tăng hằng số (mặc định 0,5) cho brier_skill_vs_half."""
    return pd.Series(float(p), index=index, name="const_prob")


def baseline_valid(r_h: pd.Series, h: int, window: int = WINDOW, min_obs: int = MIN_OBS):
    """Mask bool: tại t mốc 252 phiên hợp lệ (đủ min_obs return đã hoàn tất)."""
    shifted, w = _completed_window(r_h, h, window)
    n = shifted.notna().astype(float).rolling(w, min_periods=1).sum()
    return (n >= min_obs).rename(f"baseline_valid_{h}")


__all__ = [
    "MIN_OBS",
    "WINDOW",
    "baseline_valid",
    "constant_prob_baseline",
    "quantile_baseline",
    "up_rate_baseline",
]

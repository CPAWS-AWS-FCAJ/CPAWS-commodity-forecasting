"""Mốc so sánh nhân quả theo ADR-0008 mục 4 (dùng cho pinball_skill, coverage, brier_skill).

Đầu vào là chuỗi target r_h đã căn theo lịch giao dịch: kết quả của
returns.horizon_log_returns(prices, h, calendar=...) (pd.Series, mỗi phiên một dòng, NaN khi
không hợp lệ). Tại phiên t, mốc chỉ dùng các r_h(s) với s thuộc 252 phiên gần nhất tính tới t
(s ≤ t) và đã hoàn tất (s + h ≤ t), tức vị trí lịch s ∈ [t − 251, t − h]. Cần ít nhất 200 return
hợp lệ, nếu không trả NaN (điểm đánh giá đó bị bỏ cho mọi chỉ số dùng mốc này).

Hàm công khai dùng chung với metrics/backtest (Long) và Lambda predict (Tiến): giữ tên và kiểu.
Quantile252Model bọc quantile_baseline để predict ghi mốc này như một model ("baseline-q252").
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from src.forecast.forecast_record import HORIZONS
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


class Quantile252Model:
    """Mốc 252 phiên dưới dạng model của Lambda predict (model_version "baseline-q252").

    windows [B, 252, 1]: log return 1 phiên đã căn theo lịch (cũ → mới), đúng đầu ra của
    make_windows. Cộng dồn thành log giá (gốc 0 trước return đầu), r_h(s) = logp[s + h] − logp[s]
    theo vị trí rồi lấy dòng cuối (phiên t) của quantile_baseline(r_h, h); không thêm công thức nào.
    Tại t có 252 − h ≥ 245 return đã hoàn tất, đủ MIN_OBS. Đầu ra [B, 7 h, 7 phân vị]."""

    window = WINDOW

    def predict(self, windows) -> np.ndarray:
        x = np.asarray(windows, dtype=np.float64)
        if x.ndim != 3 or x.shape[1:] != (self.window, 1) or not np.isfinite(x).all():
            raise ValueError(f"windows must be finite [B,{self.window},1]")
        out = np.empty((len(x), len(HORIZONS), len(QUANTILE_LEVELS)))
        for b, r1 in enumerate(x[:, :, 0]):
            logp = pd.Series(np.concatenate([[0.0], np.cumsum(r1)]))
            for i, h in enumerate(HORIZONS):
                r_h = logp.shift(-h) - logp
                out[b, i] = quantile_baseline(r_h, h).iloc[-1].to_numpy()
        if not np.isfinite(out).all():
            raise ValueError("baseline has fewer than MIN_OBS completed returns")
        return out


def baseline_valid(r_h: pd.Series, h: int, window: int = WINDOW, min_obs: int = MIN_OBS):
    """Mask bool: tại t mốc 252 phiên hợp lệ (đủ min_obs return đã hoàn tất)."""
    shifted, w = _completed_window(r_h, h, window)
    n = shifted.notna().astype(float).rolling(w, min_periods=1).sum()
    return (n >= min_obs).rename(f"baseline_valid_{h}")


__all__ = [
    "MIN_OBS",
    "WINDOW",
    "Quantile252Model",
    "baseline_valid",
    "constant_prob_baseline",
    "quantile_baseline",
    "up_rate_baseline",
]

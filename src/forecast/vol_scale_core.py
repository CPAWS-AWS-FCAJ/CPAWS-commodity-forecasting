"""Phần thuần NumPy/pandas của K3b S1 (src/forecast/vol_scaled.py), dùng chung cho Lambda predict.

Image predict không có PyEMD và không chép configs/, nên module này không import
src.features.ceemdan_cache hay configs.k3b; hằng số khai báo tại đây, test kiểm chúng bằng đúng
configs/k3b.py (docs/experiments/s1a-shadow-plan.md mục 3.1).

- daily_log_returns(): r_s = ln(P_s / P_{s−1}) theo lịch của tài sản, đánh chỉ số tại phiên kết thúc
  s. Cặp vắt qua phiên thiếu, bị loại hoặc giá ≤ 0 là NaN (không nối hai phiên cách xa).
- long_vol(): σ_long,t = độ lệch chuẩn mẫu của các r_s hợp lệ trong 252 phiên lịch gần nhất ≤ t,
  cần ít nhất 200 return hợp lệ.
- ewma_vol(): σ²_t = λ·σ²_{t−1} + (1 − λ)·r_t², khởi tạo tại return hợp lệ thứ 252 bằng phương sai
  mẫu của 252 return hợp lệ đầu tiên; r_t không hợp lệ thì giữ nguyên σ²_{t−1}.
- scale_quantiles(): q_τ,h = m_h + k_t·(Q_τ,h − m_h), m_h = q50 của mốc.
- k_at(): k_t = clip(σ_short/σ_long, 0,5, 2,0) của S1a (λ 0,94) tại một ngày gốc, cùng phép tính
  với vol_scaled.vol_ratio().

Mọi thống kê tại t chỉ dùng giá tới t, nên không đổi khi nối thêm dữ liệu sau t (có test).
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from src.data.config import ASSETS
from src.forecast.ceemdan_dlinear_numpy import MEDIAN, check_baseline
from src.forecast.returns import horizon_log_returns

# Bằng configs/k3b.py (tests/test_vol_scale_core.py kiểm)
S1A_LAMBDA = 0.94  # configs.k3b.S1_LAMBDA["S1a"]
K_CLIP = (0.5, 2.0)
SIGMA_LONG_WINDOW = 252
SIGMA_MIN_OBS = 200
EWMA_INIT_OBS = 252


def _asset_series(prices: pd.DataFrame, asset: str) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Như src.features.ceemdan_cache.asset_series (chép để không kéo theo PyEMD)."""
    d = prices[prices["asset"] == asset].sort_values("date")
    return pd.DatetimeIndex(d["date"]), d["price"].to_numpy(dtype=float)


def daily_log_returns(prices: pd.Series, calendar: str, invalid_dates=None) -> pd.Series:
    """r_s = ln(P_s / P_{s−1}) theo lịch, chỉ số tại s; r_1(s − 1) của returns.py dịch một phiên lịch."""
    r1 = horizon_log_returns(prices, 1, calendar=calendar, invalid_dates=invalid_dates)
    return r1.shift(1).rename("r_daily")


def long_vol(
    r: pd.Series, window: int = SIGMA_LONG_WINDOW, min_obs: int = SIGMA_MIN_OBS
) -> tuple[pd.Series, pd.Series]:
    """σ_long (ddof = 1) trên các r_s hợp lệ trong `window` phiên lịch gần nhất ≤ t, và số return
    hợp lệ dùng đến; NaN khi ít hơn min_obs."""
    count = r.notna().astype(float).rolling(window, min_periods=1).sum()
    return r.rolling(window, min_periods=min_obs).std(ddof=1).rename("sigma_long"), count


def ewma_vol(r: pd.Series, lam: float, init_obs: int = EWMA_INIT_OBS) -> pd.Series:
    """σ_short theo EWMA; NaN trước return hợp lệ thứ init_obs của chuỗi."""
    if not 0 < lam < 1:
        raise ValueError("lambda must be in (0, 1)")
    x = r.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    pos = np.flatnonzero(np.isfinite(x))
    if len(pos) >= init_obs:
        start = pos[init_obs - 1]
        var = float(np.var(x[pos[:init_obs]], ddof=1))
        out[start] = var
        for i in range(start + 1, len(x)):
            if np.isfinite(x[i]):
                var = lam * var + (1 - lam) * x[i] ** 2
            out[i] = var
    return pd.Series(np.sqrt(out), index=r.index, name="sigma_short")


def scale_quantiles(baseline, k) -> np.ndarray:
    """Mốc [B,7,7] và k [B] > 0 → q = m + k·(Q − m), viết thành Q + (k − 1)·(Q − m) để k = 1 trả
    đúng từng bit của mốc."""
    b = check_baseline(baseline)
    k = np.asarray(k, dtype=np.float64)
    if k.shape != (len(b),) or not np.isfinite(k).all() or (k <= 0).any():
        raise ValueError("k must be finite, positive, one per origin")
    m = b[..., MEDIAN : MEDIAN + 1]
    return b + (k[:, None, None] - 1.0) * (b - m)


def k_at(
    prices: pd.DataFrame, asset: str, base_date, invalid_dates: Iterable | None = None
) -> tuple[float, float, float]:
    """(k_t, σ_short, σ_long) của S1a tại base_date, chỉ từ giá tới t (bản clean, bỏ dòng bị loại).
    k_t là NaN khi σ_short/σ_long không hợp lệ (ví dụ ít hơn SIGMA_MIN_OBS return hợp lệ)."""
    invalid_list = None if invalid_dates is None else list(invalid_dates)
    base = pd.Timestamp(base_date)
    if base.tz is not None:
        raise ValueError("base_date must be a naive session date")
    base = base.normalize()
    dates, values = _asset_series(prices, asset)
    r = daily_log_returns(pd.Series(values, index=dates), ASSETS[asset].calendar, invalid_list)
    sigma_long, _ = long_vol(r)
    sigma_short = ewma_vol(r, S1A_LAMBDA)
    s = np.float64(sigma_short.get(base, np.nan))
    lv = np.float64(sigma_long.get(base, np.nan))
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = s / lv
    if not (np.isfinite(ratio) and ratio > 0):
        return float("nan"), float(s), float(lv)
    return float(np.clip(ratio, *K_CLIP)), float(s), float(lv)


__all__ = [
    "EWMA_INIT_OBS",
    "K_CLIP",
    "S1A_LAMBDA",
    "SIGMA_LONG_WINDOW",
    "SIGMA_MIN_OBS",
    "daily_log_returns",
    "ewma_vol",
    "k_at",
    "long_vol",
    "scale_quantiles",
]

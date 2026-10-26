"""K3b S1: mốc 252 phiên co giãn theo biến động (docs/experiments/k3b-volatility-plan.md mục 3, 6.3).

- daily_log_returns(): r_s = ln(P_s / P_{s−1}) theo lịch của tài sản, đánh chỉ số tại phiên kết thúc
  s. Cặp vắt qua phiên thiếu, bị loại hoặc giá ≤ 0 là NaN (không nối hai phiên cách xa).
- long_vol(): σ_long,t = độ lệch chuẩn mẫu của các r_s hợp lệ trong 252 phiên lịch gần nhất ≤ t,
  cần ít nhất 200 return hợp lệ.
- ewma_vol(): σ²_t = λ·σ²_{t−1} + (1 − λ)·r_t², khởi tạo tại return hợp lệ thứ 252 bằng phương sai
  mẫu của 252 return hợp lệ đầu tiên; r_t không hợp lệ thì giữ nguyên σ²_{t−1}.
- vol_ratio(): σ_short/σ_long (chưa kẹp, cho S2) và k_t = clip(σ_short/σ_long, 0,5, 2,0) tại các
  ngày gốc.
- scale_quantiles(): q_τ,h = m_h + k_t·(Q_τ,h − m_h), m_h = q50 của mốc. Trung vị và thứ tự phân vị
  giữ nguyên vì k_t > 0.
- s1_quantiles(): baseline_quantiles() của K3 (mốc 252 phiên tại t) co giãn theo k_t.

Mọi thống kê tại t chỉ dùng giá tới t, nên không đổi khi nối thêm dữ liệu sau t (có test).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from configs import k3b as C
from src.data.config import ASSETS
from src.features import ceemdan_cache as cc
from src.features.ceemdan_features import baseline_quantiles
from src.forecast.ceemdan_dlinear_numpy import MEDIAN, check_baseline
from src.forecast.returns import horizon_log_returns


@dataclass(frozen=True)
class VolRatio:
    """Tại từng ngày gốc: ratio = σ_short/σ_long (chưa kẹp), k = ratio kẹp trong K_CLIP; NaN ở dòng
    không hợp lệ. diag: σ_short, σ_long, số return hợp lệ trong cửa sổ 252 phiên."""

    ratio: np.ndarray
    k: np.ndarray
    valid: np.ndarray
    diag: pd.DataFrame
    base_dates: pd.DatetimeIndex


def daily_log_returns(prices: pd.Series, calendar: str, invalid_dates=None) -> pd.Series:
    """r_s = ln(P_s / P_{s−1}) theo lịch, chỉ số tại s; r_1(s − 1) của returns.py dịch một phiên lịch."""
    r1 = horizon_log_returns(prices, 1, calendar=calendar, invalid_dates=invalid_dates)
    return r1.shift(1).rename("r_daily")


def long_vol(
    r: pd.Series, window: int = C.SIGMA_LONG_WINDOW, min_obs: int = C.SIGMA_MIN_OBS
) -> tuple[pd.Series, pd.Series]:
    """σ_long (ddof = 1) trên các r_s hợp lệ trong `window` phiên lịch gần nhất ≤ t, và số return
    hợp lệ dùng đến; NaN khi ít hơn min_obs."""
    count = r.notna().astype(float).rolling(window, min_periods=1).sum()
    return r.rolling(window, min_periods=min_obs).std(ddof=1).rename("sigma_long"), count


def ewma_vol(r: pd.Series, lam: float, init_obs: int = C.EWMA_INIT_OBS) -> pd.Series:
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


def vol_ratio(
    prices: pd.DataFrame,
    asset: str,
    base_dates,
    lam: float,
    invalid_dates: Iterable | None = None,
) -> VolRatio:
    """σ_short/σ_long và k_t tại các ngày gốc, chỉ từ giá tới t (bản clean, bỏ dòng bị loại)."""
    invalid_list = None if invalid_dates is None else list(invalid_dates)
    base = pd.DatetimeIndex(pd.to_datetime(base_dates))
    if base.tz is not None:
        raise ValueError("base_dates must be naive session dates")
    base = base.normalize().astype("datetime64[ns]")
    dates, values = cc.asset_series(prices, asset)
    r = daily_log_returns(pd.Series(values, index=dates), ASSETS[asset].calendar, invalid_list)
    sigma_long, n_long = long_vol(r)
    sigma_short = ewma_vol(r, lam)
    frame = pd.DataFrame(
        {"sigma_short": sigma_short, "sigma_long": sigma_long, "n_long": n_long}
    ).reindex(base)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = (frame["sigma_short"] / frame["sigma_long"]).to_numpy(dtype=float)
    valid = np.isfinite(ratio) & (ratio > 0)
    ratio = np.where(valid, ratio, np.nan)
    k = np.where(valid, np.clip(ratio, *C.K_CLIP), np.nan)
    diag = frame.reset_index(names="base_date").assign(ratio=ratio, k=k, valid=valid)
    return VolRatio(ratio=ratio, k=k, valid=valid, diag=diag, base_dates=base)


def scale_quantiles(baseline, k) -> np.ndarray:
    """Mốc [B,7,7] và k [B] > 0 → q = m + k·(Q − m), viết thành Q + (k − 1)·(Q − m) để k = 1 trả
    đúng từng bit của mốc."""
    b = check_baseline(baseline)
    k = np.asarray(k, dtype=np.float64)
    if k.shape != (len(b),) or not np.isfinite(k).all() or (k <= 0).any():
        raise ValueError("k must be finite, positive, one per origin")
    m = b[..., MEDIAN : MEDIAN + 1]
    return b + (k[:, None, None] - 1.0) * (b - m)


def s1_quantiles(
    prices: pd.DataFrame,
    asset: str,
    base_dates,
    lam: float,
    invalid_dates: Iterable | None = None,
) -> tuple[np.ndarray, np.ndarray, VolRatio]:
    """Phân vị S1 [n,7,7] (NaN ở dòng không hợp lệ), mask hợp lệ (mốc hợp lệ cả 7 h và k_t hợp lệ)
    và VolRatio. Chưa qua normalize_quantiles()."""
    invalid_list = None if invalid_dates is None else list(invalid_dates)
    base_q, base_ok = baseline_quantiles(prices, asset, base_dates, invalid_list)
    vr = vol_ratio(prices, asset, base_dates, lam, invalid_list)
    ok = base_ok & vr.valid
    q = np.full_like(base_q, np.nan)
    if ok.any():
        q[ok] = scale_quantiles(base_q[ok], vr.k[ok])
    return q, ok, vr


__all__ = [
    "VolRatio",
    "daily_log_returns",
    "ewma_vol",
    "long_vol",
    "s1_quantiles",
    "scale_quantiles",
    "vol_ratio",
]

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

daily_log_returns, long_vol, ewma_vol, scale_quantiles nằm ở src/forecast/vol_scale_core.py (thuần
NumPy/pandas, dùng chung với Lambda predict) và được import lại ở đây.

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
from src.forecast.vol_scale_core import daily_log_returns, ewma_vol, long_vol, scale_quantiles


@dataclass(frozen=True)
class VolRatio:
    """Tại từng ngày gốc: ratio = σ_short/σ_long (chưa kẹp), k = ratio kẹp trong K_CLIP; NaN ở dòng
    không hợp lệ. diag: σ_short, σ_long, số return hợp lệ trong cửa sổ 252 phiên."""

    ratio: np.ndarray
    k: np.ndarray
    valid: np.ndarray
    diag: pd.DataFrame
    base_dates: pd.DatetimeIndex


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

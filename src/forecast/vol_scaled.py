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

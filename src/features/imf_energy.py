"""Đặc trưng S2 của K3b (docs/experiments/k3b-volatility-plan.md mục 3, 6.1, 6.3).

Dùng lại đường tính của K3 (ceemdan_features: cache ADR-0007, quy tắc A, chia cho P_t), thêm:
- log_energy(): X (n, L, K+1) đã chia cho P_t (cột residue = residue/P_t − 1) → log của trung bình
  bình phương trên L điểm, mỗi cột một giá trị: (n, K+1).
- s2_features(): ghép log năng lượng với log(σ_short/σ_long) (tỷ số chưa kẹp, vol_scaled.vol_ratio)
  → (n, K+2); với K = 3 là 5 cột.
- s2_inputs(): phần biết được tại t (ceemdan_inputs + vol_ratio), dùng cho predict sau này và test
  không rò rỉ. s2_samples(): quy tắc A trên giai đoạn có nhãn (ceemdan_samples) + cùng s2_features.
Dòng có log năng lượng không hữu hạn (cột IMF toàn 0) hoặc tỷ số không hợp lệ thì không hợp lệ.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.features.ceemdan_features import (
    CeemdanCache,
    CeemdanSamples,
    ceemdan_inputs,
    ceemdan_samples,
    column_names,
)
from src.forecast.vol_scaled import VolRatio, vol_ratio


@dataclass(frozen=True)
class S2Inputs:
    """features: (n, K+2) float64, NaN ở dòng không hợp lệ; valid: (n,) bool."""

    features: np.ndarray
    valid: np.ndarray
    base_dates: pd.DatetimeIndex
    vol: VolRatio


@dataclass(frozen=True)
class S2Samples(S2Inputs):
    """Thêm mẫu quy tắc A của K3 (y, mốc, ngày đích, diag)."""

    samples: CeemdanSamples


def log_energy(X) -> np.ndarray:
    """(n, L, C) → (n, C): log(mean_L X²). Dòng NaN giữ NaN; năng lượng 0 cho −inf."""
    x = np.asarray(X, dtype=np.float64)
    if x.ndim != 3:
        raise ValueError("X must be [n, L, C]")
    with np.errstate(divide="ignore"):
        return np.log(np.mean(x**2, axis=1))


def s2_features(X, ratio) -> tuple[np.ndarray, np.ndarray]:
    """Ghép log năng lượng từng cột X với log(ratio); trả (features, hữu hạn)."""
    ratio = np.asarray(ratio, dtype=np.float64)
    if ratio.shape != (len(X),):
        raise ValueError("ratio must have one value per origin")
    with np.errstate(divide="ignore", invalid="ignore"):
        features = np.column_stack([log_energy(X), np.log(ratio)])
    finite = np.isfinite(features).all(axis=1)
    features[~finite] = np.nan
    return features, finite


def feature_names(max_imf: int) -> list[str]:
    return [f"log_energy_{c}" for c in column_names(max_imf)] + ["log_sigma_short_over_long"]


def s2_inputs(
    prices: pd.DataFrame,
    asset: str,
    cache: CeemdanCache,
    base_dates,
    *,
    max_imf: int,
    seq_len: int,
    lam: float,
    invalid_dates: Iterable | None = None,
) -> S2Inputs:
    invalid_list = None if invalid_dates is None else list(invalid_dates)
    inputs = ceemdan_inputs(
        prices,
        asset,
        cache,
        base_dates,
        max_imf=max_imf,
        seq_len=seq_len,
        invalid_dates=invalid_list,
    )
    vol = vol_ratio(prices, asset, inputs.base_dates, lam, invalid_list)
    features, finite = s2_features(inputs.X, vol.ratio)
    valid = inputs.valid & vol.valid & finite
    features[~valid] = np.nan
    return S2Inputs(features=features, valid=valid, base_dates=inputs.base_dates, vol=vol)


def s2_samples(
    prices: pd.DataFrame,
    asset: str,
    cache: CeemdanCache,
    base_dates,
    *,
    max_imf: int,
    seq_len: int,
    period_end,
    lam: float,
    invalid_dates: Iterable | None = None,
) -> S2Samples:
    invalid_list = None if invalid_dates is None else list(invalid_dates)
    samples = ceemdan_samples(
        prices,
        asset,
        cache,
        base_dates,
        max_imf=max_imf,
        seq_len=seq_len,
        period_end=period_end,
        invalid_dates=invalid_list,
    )
    vol = vol_ratio(prices, asset, samples.base_dates, lam, invalid_list)
    features, finite = s2_features(samples.X, vol.ratio)
    valid = samples.valid & vol.valid & finite
    features[~valid] = np.nan
    return S2Samples(
        features=features,
        valid=valid,
        base_dates=samples.base_dates,
        vol=vol,
        samples=samples,
    )


__all__ = [
    "S2Inputs",
    "S2Samples",
    "feature_names",
    "log_energy",
    "s2_features",
    "s2_inputs",
    "s2_samples",
]

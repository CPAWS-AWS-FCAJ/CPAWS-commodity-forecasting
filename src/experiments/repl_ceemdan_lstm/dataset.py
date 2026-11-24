from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.forecast.baselines import baseline_valid, quantile_baseline
from src.forecast.returns import horizon_log_returns

from . import config as C
from .data import AssetSeries, next_sessions, split_train

VARIANTS = ("r_raw", "r_full", "r_causal")
SEGMENTS = (*C.SPLIT_NAMES, "eval")

# Lý do loại (mỗi ngày gốc một lý do, theo thứ tự ưu tiên này)
R_BOUNDARY = "ranh giới đoạn (t + 1 ở đoạn sau)"
R_AFTER_CUTOFF = "t + 1 sau CUTOFF"
R_NO_TARGET = "t + 1 không có giá hợp lệ"
R_NO_CAUSAL = "thiếu cửa sổ R-causal"
R_NO_BASELINE = "baseline-q252 không hợp lệ (chỉ eval)"


@dataclass
class AssetSamples:
    """Mọi ngày gốc ứng viên của một tài sản (dòng giá từ TRAIN[0] tới CUTOFF).

    segment: tên đoạn của mẫu được dùng, "" nếu bị loại (lý do ở `reason`).
    X[variant]: (n, SEQ_LEN, n_comp); Y[variant]: (n, n_comp), NaN khi không có target.
    """

    asset: str
    calendar: str
    origins: pd.DatetimeIndex
    target_dates: pd.DatetimeIndex  # phiên kế tiếp theo lịch
    segment: np.ndarray
    reason: np.ndarray
    p_t: np.ndarray
    p_next: np.ndarray
    r_next: np.ndarray  # log(P[t+1] / P[t]) theo lịch (horizon_log_returns h = 1)
    baseline_q: np.ndarray  # (n, 7) baseline-q252 h = 1 tại t (nhân quả)
    X: dict[str, np.ndarray] = field(default_factory=dict)
    Y: dict[str, np.ndarray] = field(default_factory=dict)
    segment_bounds: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=dict)

    def mask(self, segment: str) -> np.ndarray:
        return self.segment == segment


def _stack(df: pd.DataFrame, rows: np.ndarray) -> np.ndarray:
    """Cột COMPONENTS của các dòng `rows` → (len(rows), SEQ_LEN, N_COMPONENTS)."""
    return np.stack([np.stack(df[name].to_numpy()[rows]) for name in C.COMPONENTS], axis=-1).astype(
        float
    )


def build_samples(
    s: AssetSeries,
    causal: pd.DataFrame,
    full: pd.DataFrame,
    invalid_dates=None,
) -> AssetSamples:
    """Dựng mẫu của 3 biến thể từ chuỗi giá, bảng R-causal và bảng R-full (bước 1)."""
    L = C.SEQ_LEN
    cut = pd.Timestamp(C.CUTOFF)
    if len(s.dates) and s.dates.max() > cut:
        raise ValueError("series has rows after CUTOFF")
    if not pd.DatetimeIndex(full["date"]).equals(s.dates):
        raise ValueError("R-full dates must equal the price rows")

    rows = np.flatnonzero((s.dates >= pd.Timestamp(C.TRAIN[0])) & (s.dates <= cut))
    if rows.min() < L - 1:
        raise ValueError("not enough history for SEQ_LEN")
    origins = s.dates[rows]
    n = len(rows)
    target_dates = next_sessions(origins, s.calendar)

    # target theo lịch; NaN khi t + 1 thiếu dòng, bị loại, giá ≤ 0, hoặc sau dữ liệu (≥ 2019)
    price = pd.Series(s.values, index=s.dates)
    r1 = horizon_log_returns(price, 1, calendar=s.calendar, invalid_dates=invalid_dates)
    r_next = r1.reindex(origins).to_numpy()
    nxt_row = np.minimum(rows + 1, len(s.dates) - 1)
    has_next = (rows + 1 < len(s.dates)) & (s.dates[nxt_row] == target_dates) & np.isfinite(r_next)
    p_next = np.where(has_next, s.values[nxt_row], np.nan)

    bq = quantile_baseline(r1, 1)
    baseline_q = bq.reindex(origins).to_numpy()
    bl_ok = baseline_valid(r1, 1).reindex(origins, fill_value=False).to_numpy(dtype=bool)

    X, Y = {}, {}
    idx = rows[:, None] + np.arange(-L + 1, 1)[None, :]
    X["r_raw"] = s.values[idx][:, :, None]
    Y["r_raw"] = p_next[:, None]
    comp = full[list(C.COMPONENTS)].to_numpy(dtype=float)  # (len(series), 4)
    X["r_full"] = comp[idx]
    Y["r_full"] = np.where(has_next[:, None], comp[nxt_row], np.nan)

    pos = pd.Series(np.arange(len(causal)), index=pd.DatetimeIndex(causal["end_date"]))
    at_t = pos.reindex(origins).to_numpy()
    at_next = pos.reindex(target_dates).to_numpy()
    has_causal = np.isfinite(at_t) & np.isfinite(at_next)
    xc = np.full((n, L, C.N_COMPONENTS), np.nan)
    yc = np.full((n, C.N_COMPONENTS), np.nan)
    if has_causal.any():
        xc[has_causal] = _stack(causal, at_t[has_causal].astype(int))
        yc[has_causal] = _stack(causal, at_next[has_causal].astype(int))[:, -1, :]
    X["r_causal"] = xc
    Y["r_causal"] = np.where(has_next[:, None], yc, np.nan)

    segment = np.full(n, "", dtype=object)
    reason = np.full(n, "", dtype=object)
    bounds = {}
    for seg in split_train(s.dates, s.calendar):
        bounds[seg.name] = (seg.start, seg.end)
        segment[origins.isin(seg.origins)] = seg.name
        in_seg = (origins >= seg.start) & (origins <= seg.end)
        reason[in_seg & ~origins.isin(seg.origins)] = R_BOUNDARY
    in_eval = (origins >= pd.Timestamp(C.EVAL[0])) & (origins <= pd.Timestamp(C.EVAL[1]))
    bounds["eval"] = (pd.Timestamp(C.EVAL[0]), cut)
    segment[in_eval] = "eval"

    used = segment != ""
    checks = (
        (target_dates > cut, R_AFTER_CUTOFF),
        (~has_next, R_NO_TARGET),
        (~has_causal, R_NO_CAUSAL),
        (in_eval & ~bl_ok, R_NO_BASELINE),
    )
    for bad, why in checks:
        drop = used & bad & (reason == "")
        reason[drop] = why
        segment[drop] = ""
    return AssetSamples(
        asset=s.asset,
        calendar=s.calendar,
        origins=origins,
        target_dates=target_dates,
        segment=segment,
        reason=reason,
        p_t=s.values[rows],
        p_next=p_next,
        r_next=r_next,
        baseline_q=baseline_q,
        X=X,
        Y=Y,
        segment_bounds=bounds,
    )


def sample_counts(sm: AssetSamples) -> dict:
    """Số mẫu theo đoạn và số ngày gốc bị loại theo lý do."""
    out = {seg: int((sm.segment == seg).sum()) for seg in SEGMENTS}
    reasons = pd.Series(sm.reason[sm.reason != ""]).value_counts()
    out["excluded"] = {str(k): int(v) for k, v in reasons.items()}
    return out


# ---------- chuẩn hóa ----------


@dataclass(frozen=True)
class ZScaler:
    mean: float
    std: float

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def inverse(self, z: np.ndarray) -> np.ndarray:
        return z * self.std + self.mean


def fit_scalers(X: np.ndarray, segment: np.ndarray, fit: str = "fit") -> list[ZScaler]:
    """Một z-score mỗi thành phần, fit trên MỌI giá trị đầu vào (SEQ_LEN × số mẫu) của đoạn fit.
    Target của thành phần dùng cùng scaler. Không nhìn giá trị của đoạn khác."""
    xf = X[segment == fit]
    if not len(xf) or not np.isfinite(xf).all():
        raise ValueError("fit segment must be non-empty and finite")
    out = []
    for k in range(X.shape[-1]):
        v = xf[:, :, k].ravel()
        sd = float(v.std())
        if sd <= 0:
            raise ValueError(f"component {k} has zero variance on the fit segment")
        out.append(ZScaler(float(v.mean()), sd))
    return out


__all__ = [
    "SEGMENTS",
    "VARIANTS",
    "AssetSamples",
    "ZScaler",
    "build_samples",
    "fit_scalers",
    "sample_counts",
]

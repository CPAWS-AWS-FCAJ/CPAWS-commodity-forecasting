"""Đặc trưng CEEMDAN cho mô hình chính K3 (docs/experiments/k3-ceemdan-plan.md mục 1–2).

Một đường tính duy nhất cho train, validation và (sau này) predict:
- load_cache(): đọc cửa sổ IMF đã tính theo ADR-0007 (không tách lại), kiểm cfg_hash.
- ceemdan_inputs(): phần biết được tại t: ma trận IMF chuẩn hóa theo P_t và hợp lệ của input.
- baseline_quantiles(): mốc 252 phiên tại t (neo đầu ra mô hình), chỉ từ return đã hoàn tất.
- ceemdan_samples(): quy tắc A cho một giai đoạn có nhãn = ceemdan_inputs + target hợp lệ cả 7 h
  + ngày đích trong giai đoạn + mốc hợp lệ cả 7 h.
- ColumnScaler: mean/std từng cột, fit chỉ trên mảng train được truyền vào.

Quy tắc A (kế hoạch mục 1): có cửa sổ CEEMDAN kết thúc tại t; make_windows(seq_len) hợp lệ (đoạn
seq_len đưa vào mô hình không có phiên thiếu); published_at kịp như dlinear_data. Phần cũ hơn của
cửa sổ decompose được phép có phiên thiếu; số phiên thiếu ghi vào diag.

Chuẩn hóa (kế hoạch mục 2): fixed_imf_matrix(K, L) → mọi cột chia cho P_t (giá cuối cửa sổ, đã biết
tại t), cột residue đổi thành residue/P_t − 1. Tổng các cột của fixed_imf_matrix bằng giá P_s, nên
tổng các cột sau bước này bằng P_s/P_t − 1. Chuẩn hóa từng cột (ColumnScaler) là bước riêng.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data import calendars
from src.data.config import ASSETS, PUBLISHED_AT_RULES
from src.features import ceemdan_cache as cc
from src.features.build import build_feature_frame, make_windows
from src.forecast import baselines as B
from src.forecast.decomposition import CeemdanConfig, WindowIMF, fixed_imf_matrix
from src.forecast.returns import QUANTILE_LEVELS, horizon_log_returns

HORIZONS = tuple(range(1, 8))


@dataclass(frozen=True)
class CeemdanCache:
    """Cửa sổ cache của một (asset, window), sắp tăng theo end_date."""

    asset: str
    window: int
    cfg_hash: str
    end_dates: pd.DatetimeIndex
    windows: list[WindowIMF]
    price_hashes: np.ndarray


@dataclass(frozen=True)
class CeemdanInputs:
    """X: (n, L, K+1) float64 đã chia cho P_t, NaN ở dòng không hợp lệ. valid: (n,) bool.
    diag: một dòng mỗi base_date (điều kiện hợp lệ, n_imf, số phiên thiếu, P_t)."""

    X: np.ndarray
    valid: np.ndarray
    diag: pd.DataFrame
    base_dates: pd.DatetimeIndex


@dataclass(frozen=True)
class CeemdanSamples:
    """Mẫu theo quy tắc A. y: (n, 7) log return h = 1..7; baseline: (n, 7 h, 7 phân vị) mốc 252
    phiên tại t; target_dates: (n, 7). valid kết hợp input, target, ranh giới và mốc."""

    X: np.ndarray
    valid: np.ndarray
    diag: pd.DataFrame
    y: np.ndarray
    baseline: np.ndarray
    base_dates: pd.DatetimeIndex
    target_dates: np.ndarray


def _naive_dates(values) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(
        pd.to_datetime(list(values) if not isinstance(values, pd.Index) else values)
    )
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.normalize().astype("datetime64[ns]")


def load_cache(st, asset: str, cfg: CeemdanConfig, start, end) -> CeemdanCache:
    """Đọc cache tháng start..end (chỉ các tháng này), bỏ end_date > end. Mọi dòng phải cùng
    cfg_hash với cfg (ADR-0007), nếu không báo ValueError."""
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M").strftime("%Y-%m")
    frames = [f for f in (cc.read_month(st, asset, cfg, m) for m in months) if len(f)]
    if not frames:
        raise ValueError(f"{asset} w={cfg.window}: no cache rows for cfg {cfg.hash()}")
    df = pd.concat(frames, ignore_index=True)
    df["end_date"] = pd.to_datetime(df["end_date"])
    df = df[(df["end_date"] >= pd.Timestamp(start)) & (df["end_date"] <= pd.Timestamp(end))]
    df = df.sort_values("end_date").reset_index(drop=True)
    if set(df["cfg_hash"]) != {cfg.hash()} or set(df["window"]) != {cfg.window}:
        raise ValueError(f"{asset} w={cfg.window}: cache cfg_hash/window mismatch")
    if df["end_date"].duplicated().any():
        raise ValueError(f"{asset} w={cfg.window}: duplicate cache end_date")
    return CeemdanCache(
        asset=asset,
        window=cfg.window,
        cfg_hash=cfg.hash(),
        end_dates=pd.DatetimeIndex(df["end_date"]),
        windows=cc.to_windows(df),
        price_hashes=df["price_hash"].to_numpy(dtype=object),
    )


def ceemdan_inputs(
    prices: pd.DataFrame,
    asset: str,
    cache: CeemdanCache,
    base_dates,
    *,
    max_imf: int,
    seq_len: int,
    invalid_dates: Iterable | None = None,
) -> CeemdanInputs:
    """Đầu vào tại từng base_date t, chỉ dùng giá tới t và cửa sổ cache kết thúc tại t.

    Hợp lệ khi: có cửa sổ cache kết thúc tại t (price_hash khớp `window` dòng giá kết thúc tại t,
    lệch thì ValueError); make_windows(seq_len) hợp lệ; published_at lớn nhất của input ≤ thời
    điểm dự báo và thời điểm dự báo trước khi giá phiên kế tiếp được công bố (như dlinear_data)."""
    if cache.asset != asset:
        raise ValueError("cache asset mismatch")
    invalid_list = None if invalid_dates is None else list(invalid_dates)
    cal_name = ASSETS[asset].calendar
    full = calendars.sessions(cal_name)
    base = _naive_dates(base_dates)
    n, w = len(base), cache.window

    dates, values = cc.asset_series(prices, asset)
    calpos = full.get_indexer(dates)
    if (calpos < 0).any():
        raise ValueError(f"{asset}: price dates off the {cal_name} calendar")
    rows = pd.Series(np.arange(len(dates)), index=dates).reindex(base).to_numpy()
    has_row = np.isfinite(rows)
    r = np.where(has_row, rows, -1).astype(int)
    cache_pos = pd.Series(np.arange(len(cache.end_dates)), index=cache.end_dates)
    j = cache_pos.reindex(base).to_numpy()
    has_window = np.isfinite(j) & has_row & (r >= w - 1)
    j = np.where(has_window, j, -1).astype(int)
    for i in np.flatnonzero(has_window):
        if cc.price_hash(values[r[i] - w + 1 : r[i] + 1]) != cache.price_hashes[j[i]]:
            raise ValueError(f"{asset} w={w} {base[i].date()}: cache price_hash differs from clean")

    frame = build_feature_frame(prices, asset, invalid_dates=invalid_list)
    batch = make_windows(frame, base, window=seq_len)
    days, hour = PUBLISHED_AT_RULES[ASSETS[asset].primary.source]
    offset = pd.Timedelta(days=days, hours=hour)
    as_of = (base + offset).to_numpy(dtype="datetime64[ns]")
    next_session = full.to_numpy()[full.get_indexer(base) + 1]
    next_pub = next_session + offset.to_timedelta64()
    pub = batch.max_input_published_at
    publication_ok = ~np.isnat(pub) & (pub <= as_of) & (as_of < next_pub)
    valid = has_window & batch.valid & publication_ok

    X = np.full((n, seq_len, max_imf + 1), np.nan)
    idx = np.flatnonzero(valid)
    if len(idx):
        m = fixed_imf_matrix([cache.windows[j[i]] for i in idx], max_imf, seq_len)
        p_t = values[r[idx]]
        m = m / p_t[:, None, None]
        m[:, :, -1] -= 1.0
        X[idx] = m

    # Phiên lịch bị thiếu trong `window` dòng giá kết thúc tại t (cửa sổ decompose theo dòng)
    n_missing = np.full(n, -1)
    ok = has_window
    n_missing[ok] = calpos[r[ok]] - calpos[r[ok] - w + 1] + 1 - w
    n_imf = np.full(n, -1)
    n_imf[ok] = [cache.windows[k].n_imf for k in j[ok]]
    diag = pd.DataFrame(
        {
            "base_date": base,
            "has_cache_window": has_window,
            "input_window_ok": batch.valid,
            "input_reason": batch.reason,
            "publication_ok": publication_ok,
            "input_valid": valid,
            "n_imf": n_imf,
            "n_imf_below_k": ok & (n_imf < max_imf),
            "n_missing_sessions_decompose": n_missing,
            "price_t": np.where(has_row, values[np.maximum(r, 0)], np.nan),
        }
    )
    return CeemdanInputs(X=X, valid=valid, diag=diag, base_dates=base)


def baseline_quantiles(
    prices: pd.DataFrame, asset: str, base_dates, invalid_dates: Iterable | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Mốc 252 phiên tại t: (n, 7 h, 7 phân vị) và mask hợp lệ cả 7 h (baselines.py, ADR-0008
    mục 4). Chỉ dùng r_h(s) đã hoàn tất (s + h ≤ t), nên không đổi khi nối thêm giá sau t."""
    invalid_list = None if invalid_dates is None else list(invalid_dates)
    cal_name = ASSETS[asset].calendar
    base = _naive_dates(base_dates)
    dates, values = cc.asset_series(prices, asset)
    series = pd.Series(values, index=dates)
    q = np.full((len(base), len(HORIZONS), len(QUANTILE_LEVELS)), np.nan)
    ok = np.ones(len(base), dtype=bool)
    for i, h in enumerate(HORIZONS):
        r_h = horizon_log_returns(series, h, calendar=cal_name, invalid_dates=invalid_list)
        q[:, i] = B.quantile_baseline(r_h, h).reindex(base).to_numpy(dtype=float)
        ok &= B.baseline_valid(r_h, h).reindex(base, fill_value=False).to_numpy(dtype=bool)
    ok &= np.isfinite(q).all(axis=(1, 2))
    q[~ok] = np.nan
    return q, ok


def ceemdan_samples(
    prices: pd.DataFrame,
    asset: str,
    cache: CeemdanCache,
    base_dates,
    *,
    max_imf: int,
    seq_len: int,
    period_end,
    invalid_dates: Iterable | None = None,
) -> CeemdanSamples:
    """Quy tắc A trên một giai đoạn có nhãn (train hoặc validation): input hợp lệ, target hợp lệ
    cả 7 h, mọi ngày đích ≤ period_end (ADR-0008 mục 7), mốc 252 phiên hợp lệ cả 7 h."""
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
    base = inputs.base_dates
    cal_name = ASSETS[asset].calendar
    full = calendars.sessions(cal_name)
    dates, values = cc.asset_series(prices, asset)
    series = pd.Series(values, index=dates)
    y = np.column_stack(
        [
            horizon_log_returns(series, h, calendar=cal_name, invalid_dates=invalid_list)
            .reindex(base)
            .to_numpy(dtype=float)
            for h in HORIZONS
        ]
    )
    targets = full.to_numpy()[full.get_indexer(base)[:, None] + np.arange(1, len(HORIZONS) + 1)]
    boundary_ok = (targets <= np.datetime64(pd.Timestamp(period_end))).all(axis=1)
    target_ok = np.isfinite(y).all(axis=1)
    baseline, baseline_ok = baseline_quantiles(prices, asset, base, invalid_list)
    valid = inputs.valid & target_ok & boundary_ok & baseline_ok
    diag = inputs.diag.assign(
        target_ok=target_ok, boundary_ok=boundary_ok, baseline_ok=baseline_ok, valid=valid
    )
    return CeemdanSamples(
        X=inputs.X,
        valid=valid,
        diag=diag,
        y=y,
        baseline=baseline,
        base_dates=base,
        target_dates=targets,
    )


@dataclass(frozen=True)
class ColumnScaler:
    """Mean/std của từng cột (trục cuối), gộp mẫu và thời gian. std = 0 → 1."""

    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, x_train) -> ColumnScaler:
        """Chỉ nhận đúng mảng train (n, L, C) đã lọc hợp lệ; không tự cắt theo ngày."""
        x = np.asarray(x_train, dtype=np.float64)
        if x.ndim != 3 or not len(x) or not np.isfinite(x).all():
            raise ValueError("scaler needs a finite nonempty training array [N, L, C]")
        std = x.std(axis=(0, 1), ddof=0)
        return cls(x.mean(axis=(0, 1)), np.where(std == 0, 1.0, std))

    def transform(self, x) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 3 or x.shape[-1] != len(self.mean):
            raise ValueError("expected [N, L, C] with the fitted number of columns")
        return (x - self.mean) / self.std

    def to_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}


def column_names(max_imf: int) -> list[str]:
    return [f"imf{k}_over_price_t" for k in range(1, max_imf + 1)] + [
        "residue_over_price_t_minus_1"
    ]


__all__ = [
    "CeemdanCache",
    "CeemdanInputs",
    "CeemdanSamples",
    "ColumnScaler",
    "baseline_quantiles",
    "ceemdan_inputs",
    "ceemdan_samples",
    "column_names",
    "load_cache",
]

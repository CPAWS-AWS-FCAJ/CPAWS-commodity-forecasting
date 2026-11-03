"""Hai giao thức tách CEEMDAN của minh họa (kế hoạch mục 3, 3.1, 3.3).

- R-causal: mỗi cửa sổ 252 phiên kết thúc tại ngày gốc t tách độc lập bằng `causal_imf_windows`
  (ADR-0001, ADR-0007), chỉ từ giá trong cửa sổ. Không đọc cache ADR-0007.
- R-full: một lần CEEMDAN trên toàn chuỗi 2012–2018. CỐ Ý dùng dữ liệu tương lai (spline của
  CEEMDAN nhìn hai phía, nên giá trị tại t chứa thông tin sau t); chỉ để minh họa giao thức thường
  gặp trong các bài báo, không dùng cho sản phẩm.

Cả hai gộp về 4 thành phần như `fixed_imf_matrix(max_imf=3)`: IMF1..3, phần còn lại = IMF4 trở đi
+ residue. Cửa sổ có ít hơn 3 IMF thì các cột IMF thiếu bằng 0.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from src.features import ceemdan_cache as cc
from src.forecast.decomposition import (
    CeemdanConfig,
    WindowIMF,
    causal_imf_windows,
    decompose_window,
    fixed_imf_matrix,
)

from . import config as C
from .data import AssetSeries


def combine_components(
    imfs: np.ndarray, residue: np.ndarray, max_imf: int = C.MAX_IMF
) -> np.ndarray:
    """(n_imf, n) IMF + (n,) residue → (max_imf + 1, n): IMF1..max_imf, dòng cuối = phần còn lại.

    Cùng quy tắc với `fixed_imf_matrix` (dùng cho R-full, nơi chỉ có một bản tách toàn chuỗi)."""
    imfs = np.asarray(imfs, dtype=float)
    out = np.zeros((max_imf + 1, imfs.shape[1]))
    k = min(max_imf, imfs.shape[0])
    out[:k] = imfs[:k]
    out[-1] = residue + imfs[max_imf:].sum(axis=0)
    return out


def causal_origins(s: AssetSeries, cfg: CeemdanConfig) -> np.ndarray:
    """Chỉ số dòng của ngày gốc R-causal: CAUSAL_START ≤ ngày ≤ CUTOFF, đủ `window` dòng lịch sử."""
    idx = np.flatnonzero(
        (s.dates >= pd.Timestamp(C.CAUSAL_START)) & (s.dates <= pd.Timestamp(C.CUTOFF))
    )
    return idx[idx >= cfg.window - 1]


def r_causal(
    s: AssetSeries,
    cfg: CeemdanConfig,
    origins: np.ndarray,
    processes: int | None = None,
    pool=None,
) -> tuple[pd.DataFrame, list[WindowIMF]]:
    """Tách từng cửa sổ kết thúc tại `origins` (chỉ số dòng), noise seed theo ngày cuối + tài sản.

    Trả bảng: end_date, seed_id, price_hash, n_imf và SEQ_LEN giá trị cuối của từng thành phần
    (cột COMPONENTS, mỗi ô một mảng float64 độ dài SEQ_LEN, cũ → mới)."""
    origins = np.asarray(origins, dtype=int)
    seed_ids = np.array([cc.seed_id(s.asset, s.dates[t]) for t in origins], dtype=np.int64)
    wins = causal_imf_windows(
        s.values, origins, cfg, processes=processes, seed_ids=seed_ids, pool=pool
    )
    x = fixed_imf_matrix(wins, C.MAX_IMF, C.SEQ_LEN)  # (n, SEQ_LEN, N_COMPONENTS)
    df = pd.DataFrame(
        {
            "end_date": s.dates[origins],
            "seed_id": seed_ids,
            "price_hash": [cc.price_hash(s.values[t - cfg.window + 1 : t + 1]) for t in origins],
            "n_imf": [w.n_imf for w in wins],
        }
    )
    for j, name in enumerate(C.COMPONENTS):
        df[name] = list(x[:, :, j])
    return df, wins


def full_config(cfg: CeemdanConfig, n: int) -> CeemdanConfig:
    """Cùng trials, epsilon, seed với `cfg`; cửa sổ = toàn chuỗi và giữ mọi điểm."""
    return replace(cfg, window=n, keep_last=n)


def r_full(s: AssetSeries, cfg: CeemdanConfig) -> tuple[pd.DataFrame, int]:
    """CEEMDAN MỘT LẦN trên toàn chuỗi WARMUP_START → CUTOFF (giao thức cố ý rò rỉ, xem đầu file).

    seed_id = seed_id(tài sản, ngày cuối chuỗi). Trả (bảng date + COMPONENTS, n_imf)."""
    n = len(s.values)
    w = decompose_window(s.values, full_config(cfg, n), cc.seed_id(s.asset, s.dates[-1]), n - 1)
    comp = combine_components(w.imfs, w.residue)
    df = pd.DataFrame({"date": s.dates} | {name: comp[j] for j, name in enumerate(C.COMPONENTS)})
    return df, w.n_imf

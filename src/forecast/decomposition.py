"""Leakage-safe (causal) CEEMDAN features.

Rule: the IMFs that feed a forecast made at origin t may only be computed from data
up to and including t. We therefore decompose a window that ENDS at t and take the
last `seq_len` rows of that window's IMFs as the model input for origin t.

Never decompose the whole series once and slice it afterwards: CEEMDAN's spline
envelopes use neighbouring points on both sides, so values inside the series would
contain information from the future (look-ahead leakage). It also creates a train/serve
mismatch: in production only the right edge of the series exists.

The same function must be used for backtesting, weekly retraining and daily inference.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from multiprocessing import Pool

import numpy as np
from PyEMD import CEEMDAN


@dataclass(frozen=True)
class CeemdanConfig:
    window: int = 512          # points used for each decomposition (must be >= seq_len)
    seq_len: int = 60          # rows of IMFs handed to the model per origin
    n_imfs: int = 10           # fixed number of IMF columns (padded / truncated), incl. residue
    num_high: int = 3          # first num_high columns = high-frequency branch
    trials: int = 20           # CEEMDAN ensemble size
    seed: int = 42             # base seed; the origin index is added so results are reproducible


def _fix_width(imfs: np.ndarray, n_imfs: int) -> np.ndarray:
    """imfs: (n_components, n_points) -> (n_points, n_imfs), padding with zeros."""
    imfs = imfs.T
    if imfs.shape[1] < n_imfs:
        pad = np.zeros((imfs.shape[0], n_imfs - imfs.shape[1]))
        imfs = np.concatenate([imfs, pad], axis=1)
    return imfs[:, :n_imfs]


def decompose_window(window_values: np.ndarray, cfg: CeemdanConfig, origin: int) -> np.ndarray:
    """Decompose one window that ends at `origin`; return its last seq_len rows."""
    c = CEEMDAN(trials=cfg.trials)
    c.noise_seed(cfg.seed + int(origin))
    imfs = c(np.asarray(window_values, dtype=float), max_imf=cfg.n_imfs - 1)
    return _fix_width(imfs, cfg.n_imfs)[-cfg.seq_len:]


def _job(args):
    series, origin, cfg = args
    start = origin - cfg.window + 1
    return decompose_window(series[start: origin + 1], cfg, origin)


DEFAULT_CONFIG = CeemdanConfig()  # frozen nên dùng chung làm mặc định an toàn


def causal_imf_windows(
    series: np.ndarray,
    origins: np.ndarray,
    cfg: CeemdanConfig = DEFAULT_CONFIG,
    processes: int | None = None,
    cache_path: str | None = None,
) -> np.ndarray:
    """Return IMF inputs with shape (len(origins), seq_len, n_imfs).

    origins: indices t where a forecast is made; every t must satisfy t >= window - 1.
    cache_path: optional .npz path; the cache is keyed by the config and origins.
    """
    series = np.asarray(series, dtype=float).ravel()
    origins = np.asarray(origins, dtype=int)
    if cfg.seq_len > cfg.window:
        raise ValueError("seq_len must be <= window")
    if origins.min() < cfg.window - 1:
        raise ValueError(f"origins must be >= window - 1 ({cfg.window - 1})")
    if origins.max() >= len(series):
        raise ValueError("origin beyond the end of the series")

    key = f"{cfg}|{origins.tobytes().hex()[:64]}|{len(origins)}"
    if cache_path and os.path.exists(cache_path):
        cached = np.load(cache_path, allow_pickle=False)
        if str(cached["key"]) == key:
            return cached["imfs"]

    jobs = [(series, int(t), cfg) for t in origins]
    if processes and processes > 1:
        with Pool(processes) as pool:
            out = pool.map(_job, jobs)
    else:
        out = [_job(j) for j in jobs]
    result = np.stack(out)

    if cache_path:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        np.savez_compressed(cache_path, imfs=result, key=np.array(key))
    return result


def split_high_low(imf_windows: np.ndarray, num_high: int) -> tuple[np.ndarray, np.ndarray]:
    """Split (..., n_imfs) into high-frequency and low-frequency branches."""
    return imf_windows[..., :num_high], imf_windows[..., num_high:]

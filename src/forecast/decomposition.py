"""Leakage-safe (causal) CEEMDAN features.

Rule: the IMFs that feed a forecast made at origin t may only be computed from data
up to and including t. We therefore decompose a window that ENDS at t and keep the
last `keep_last` points of that window's IMFs; the model later takes the last `seq_len`
of them (seq_len <= keep_last).

Never decompose the whole series once and slice it afterwards: CEEMDAN's spline
envelopes use neighbouring points on both sides, so values inside the series would
contain information from the future (look-ahead leakage). It also creates a train/serve
mismatch: in production only the right edge of the series exists.

The same function must be used for backtesting, weekly retraining and daily inference.

Định dạng (ADR-0007): mỗi cửa sổ lưu IMF thô (số IMF thay đổi giữa các cửa sổ, không đệm 0)
và residue tách riêng. Cách ghép thành ma trận đầu vào (fixed_imf_matrix) chọn ở K3, không cần
tách lại. PyEMD chạy với parallel=False (tái lập từng bit, chạy được trong Lambda); song song chỉ
ở tầng ngoài (processes > 1).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import version
from multiprocessing import Pool

import numpy as np
from PyEMD import CEEMDAN

PYEMD_VERSION = version("EMD-signal")
# Cách tạo noise seed; đổi cách tính thì đổi chuỗi này để cfg_hash đổi theo (cache cũ không bị dùng
# nhầm). v2 (12/10/2026): seed_id = số ngày tới ngày cuối cửa sổ + crc32(tên tài sản).
SEED_SCHEME = "v2-days-plus-crc32-asset"


@dataclass(frozen=True)
class CeemdanConfig:
    window: int = 512  # điểm mỗi lần decompose; chưa chốt (252/504), chọn ở K3 trên validation 2019
    trials: int = 20  # kích thước ensemble CEEMDAN
    epsilon: float = 0.005  # biên độ nhiễu (mặc định PyEMD)
    seed: int = 42  # noise seed = (seed + seed_id) % 2**32 của từng cửa sổ
    keep_last: int = 128  # số điểm cuối cửa sổ được giữ; phải >= mọi seq_len sẽ thử (30–120)

    def hash(self) -> str:
        """Hash cấu hình tính toán (không gồm window: window là một chiều riêng của cache) và
        phiên bản PyEMD, numpy: đổi bất kỳ thứ gì trong đây thì cache cũ không dùng được."""
        d = asdict(self)
        d.pop("window")
        d.update(pyemd=PYEMD_VERSION, numpy=np.__version__, seed_scheme=SEED_SCHEME)
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]


@dataclass(frozen=True)
class WindowIMF:
    """IMF của một cửa sổ kết thúc tại origin: imfs (n_imf, keep_last), residue (keep_last,)."""

    origin: int
    imfs: np.ndarray
    residue: np.ndarray

    @property
    def n_imf(self) -> int:
        return int(self.imfs.shape[0])


DEFAULT_CONFIG = CeemdanConfig()  # frozen nên dùng chung làm mặc định an toàn


def _make_ceemdan(cfg: CeemdanConfig) -> CEEMDAN:
    # parallel=False: PyEMD 1.10 mặc định tự mở Pool mỗi lần gọi → chậm, cộng trial theo thứ tự
    # không cố định (không tái lập từng bit) và không chạy được trong Pool tầng ngoài hay Lambda.
    return CEEMDAN(trials=cfg.trials, epsilon=cfg.epsilon, parallel=False)


def noise_seed(cfg: CeemdanConfig, seed_id: int) -> int:
    """Seed của RandomState trong PyEMD: (cfg.seed + seed_id) % 2**32 (RandomState chỉ nhận
    0..2**32-1). Công thức cố định, không dùng hash() của Python (đổi theo PYTHONHASHSEED)."""
    return (int(cfg.seed) + int(seed_id)) % 2**32


def decompose_window(
    window_values: np.ndarray, cfg: CeemdanConfig, seed_id: int, origin: int = -1
) -> WindowIMF:
    """Decompose một cửa sổ (đầy đủ, max_imf=-1); giữ keep_last điểm cuối."""
    c = _make_ceemdan(cfg)
    c.noise_seed(noise_seed(cfg, seed_id))
    comp = c(np.asarray(window_values, dtype=float), max_imf=-1)  # dòng cuối là residue
    k = cfg.keep_last
    return WindowIMF(int(origin), comp[:-1, -k:].copy(), comp[-1, -k:].copy())


def _job(args) -> WindowIMF:
    series, origin, seed_id, cfg = args
    start = origin - cfg.window + 1
    return decompose_window(series[start : origin + 1], cfg, seed_id, origin)


def causal_imf_windows(
    series: np.ndarray,
    origins: np.ndarray,
    cfg: CeemdanConfig = DEFAULT_CONFIG,
    processes: int | None = None,
    seed_ids: np.ndarray | None = None,
    pool=None,
) -> list[WindowIMF]:
    """IMF của các cửa sổ kết thúc tại từng origin (chỉ số trong series).

    seed_ids: số nguyên cho noise seed của từng cửa sổ (mặc định = origin). Cache dùng số ngày
      của ngày cuối cửa sổ để seed không đổi khi lịch sử phía trước được thêm/bớt dòng.
    processes/pool: song song ở tầng ngoài (mỗi tiến trình một cửa sổ); truyền pool có sẵn để
      không phải mở Pool mới mỗi lần gọi.
    """
    series = np.asarray(series, dtype=float).ravel()
    origins = np.asarray(origins, dtype=int)
    seed_ids = origins if seed_ids is None else np.asarray(seed_ids, dtype=np.int64)
    if len(seed_ids) != len(origins):
        raise ValueError("seed_ids must match origins")
    if cfg.keep_last > cfg.window:
        raise ValueError("keep_last must be <= window")
    if len(origins) == 0:
        return []
    if origins.min() < cfg.window - 1:
        raise ValueError(f"origins must be >= window - 1 ({cfg.window - 1})")
    if origins.max() >= len(series):
        raise ValueError("origin beyond the end of the series")

    jobs = [(series, int(t), int(s), cfg) for t, s in zip(origins, seed_ids, strict=True)]
    if pool is not None:
        return pool.map(_job, jobs)
    if processes and processes > 1:
        with Pool(processes) as p:
            return p.map(_job, jobs)
    return [_job(j) for j in jobs]


def fixed_imf_matrix(windows: Sequence[WindowIMF], max_imf: int, seq_len: int) -> np.ndarray:
    """Ghép thành (n_windows, seq_len, max_imf + 1): IMF1..max_imf, cột cuối = residue + tổng các
    IMF sau max_imf (residue luôn ở cột cuối). Cửa sổ có ít IMF hơn max_imf: các cột IMF thiếu
    là 0 (residue vẫn ở cột cuối).

    Probe 11/10/2026: chạy CEEMDAN với max_imf=K cho IMF1..K giống hệt từng bit cách ghép này;
    residue chỉ lệch ở mức sai số làm tròn (~1e-14 trên giá ~100)."""
    if max_imf < 1:
        raise ValueError("max_imf must be >= 1")
    out = np.zeros((len(windows), seq_len, max_imf + 1))
    for i, w in enumerate(windows):
        if seq_len > w.residue.shape[0]:
            raise ValueError(f"seq_len {seq_len} > stored points {w.residue.shape[0]}")
        k = min(max_imf, w.n_imf)
        out[i, :, :k] = w.imfs[:k, -seq_len:].T
        out[i, :, -1] = w.residue[-seq_len:] + w.imfs[max_imf:, -seq_len:].sum(axis=0)
    return out


def split_high_low(imf_windows: np.ndarray, num_high: int) -> tuple[np.ndarray, np.ndarray]:
    """Split (..., n_columns) into high-frequency and low-frequency branches."""
    return imf_windows[..., :num_high], imf_windows[..., num_high:]

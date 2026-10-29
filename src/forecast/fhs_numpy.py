"""NumPy-only runtime cho FHS GJR-GARCH K4 (docs/experiments/k4-plan.md mục 3).

Không import arch, scipy, pandas: Lambda predict có thể dùng lại với tham số, backcast và phần dư
chuẩn hóa đã lưu (fit hằng tháng offline bằng src/forecast/fhs_fit.py).
- Trên x = return × scale: x_t = ε_t = σ_t·z_t, σ²_t = ω + (α + γ·1[ε_{t−1} < 0])·ε²_{t−1}
  + β·σ²_{t−1}. Khởi tạo như arch: σ²_0 = ω + (α + γ/2 + β)·backcast.
- variance_path(): σ²_t trên dãy return hợp lệ (return NaN đã bỏ, giống đầu vào lúc fit) và σ² của
  bước kế tiếp sau mỗi return.
- fhs_quantiles(): z* lấy mẫu có hoàn lại từ phần dư chuẩn hóa của cửa sổ fit, ε* = σ*·z*, σ* theo
  phương trình trên; return h phiên = tổng ε* của h bước đầu, chia scale. Phân vị thực nghiệm
  (nội suy tuyến tính như np.quantile) [7 h, 7 τ], CHƯA qua normalize_quantiles().
  demean=True (fhs-gjr-t-dm, kế hoạch mục 8): lấy mẫu từ z − mean(z), cùng các chỉ số rút, nên
  độ lệch chuẩn không đổi; mặc định False giữ nguyên fhs-gjr-t.
- seed_for(): seed cố định theo (asset, base_date), cùng quy ước với cache CEEMDAN (ADR-0007).
"""

import zlib
from dataclasses import dataclass

import numpy as np

LEVELS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
N_PATHS = 5000
N_STEPS = 7


@dataclass(frozen=True)
class GjrParams:
    """Tham số GJR-GARCH(1,1) trên thang return × scale; ν chỉ dùng lúc fit (FHS lấy z thực
    nghiệm), giữ lại để báo cáo."""

    omega: float
    alpha: float
    gamma: float
    beta: float
    nu: float

    def __post_init__(self):
        values = (self.omega, self.alpha, self.gamma, self.beta, self.nu)
        if not np.isfinite(values).all():
            raise ValueError("GJR parameters must be finite")
        if self.omega <= 0 or self.alpha < 0 or self.beta < 0 or self.alpha + self.gamma < 0:
            raise ValueError("GJR parameters give a non-positive variance")

    @property
    def persistence(self) -> float:
        """α + γ/2 + β (với z đối xứng)."""
        return self.alpha + 0.5 * self.gamma + self.beta


def initial_variance(params: GjrParams, backcast: float) -> float:
    if not np.isfinite(backcast) or backcast <= 0:
        raise ValueError("backcast must be finite and positive")
    return params.omega + (params.alpha + 0.5 * params.gamma + params.beta) * backcast


def next_variance(x, sigma2, params: GjrParams):
    """σ² của bước sau return x với phương sai sigma2 (vô hướng hoặc mảng cùng shape)."""
    x = np.asarray(x, dtype=np.float64)
    return params.omega + (params.alpha + params.gamma * (x < 0)) * x * x + params.beta * sigma2


def variance_path(x, params: GjrParams, backcast: float) -> tuple[np.ndarray, np.ndarray]:
    """x [n] (return hợp lệ × scale, cũ → mới) → (σ²_t [n], σ² bước kế tiếp sau từng x_t [n])."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all():
        raise ValueError("x must be a finite, nonempty 1-D array")
    sigma2 = np.empty(len(x))
    s2 = initial_variance(params, backcast)
    for t in range(len(x)):
        sigma2[t] = s2
        s2 = params.omega + (params.alpha + params.gamma * (x[t] < 0)) * x[t] * x[t]
        s2 += params.beta * sigma2[t]
    return sigma2, next_variance(x, sigma2, params)


def seed_for(asset: str, base_date) -> int:
    """Số ngày từ 1970-01-01 tới base_date cộng crc32 của tên tài sản."""
    day = np.datetime64(base_date).astype("datetime64[D]").astype(np.int64)
    return int(day) + zlib.crc32(asset.encode("utf-8"))


def simulate_cumulative(
    sigma2_next: float,
    z,
    params: GjrParams,
    rng: np.random.Generator,
    n_paths: int = N_PATHS,
    n_steps: int = N_STEPS,
    demean: bool = False,
) -> np.ndarray:
    """[n_paths, n_steps]: tổng ε* của k bước đầu (thang return × scale)."""
    z = np.asarray(z, dtype=np.float64)
    if z.ndim != 1 or not len(z) or not np.isfinite(z).all():
        raise ValueError("z must be a finite, nonempty 1-D array")
    if demean:
        z = z - z.mean()
    if not np.isfinite(sigma2_next) or sigma2_next <= 0:
        raise ValueError("sigma2_next must be finite and positive")
    draws = rng.integers(0, len(z), size=(n_steps, n_paths))
    s2 = np.full(n_paths, float(sigma2_next))
    total = np.zeros(n_paths)
    out = np.empty((n_paths, n_steps))
    for k in range(n_steps):
        eps = np.sqrt(s2) * z[draws[k]]
        total += eps
        out[:, k] = total
        s2 = next_variance(eps, s2, params)
    return out


def fhs_quantiles(
    sigma2_next: float,
    z,
    params: GjrParams,
    *,
    seed: int,
    scale: float,
    n_paths: int = N_PATHS,
    n_steps: int = N_STEPS,
    levels=LEVELS,
    demean: bool = False,
) -> np.ndarray:
    """Phân vị FHS của log return h = 1..n_steps phiên: [n_steps, len(levels)], chưa normalize."""
    rng = np.random.default_rng(seed)
    paths = simulate_cumulative(sigma2_next, z, params, rng, n_paths, n_steps, demean) / scale
    return np.quantile(paths, levels, axis=0).T


__all__ = [
    "LEVELS",
    "N_PATHS",
    "N_STEPS",
    "GjrParams",
    "fhs_quantiles",
    "initial_variance",
    "next_variance",
    "seed_for",
    "simulate_cumulative",
    "variance_path",
]

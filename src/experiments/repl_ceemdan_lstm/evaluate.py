"""Quy đổi dự báo, phân vị từ đoạn hiệu chỉnh, chỉ số và chẩn đoán (kế hoạch mục 3.1, 3.2, 4).

- r̂ = log(P̂(t+1) / P(t)); P̂ ≤ 0 là lỗi dự báo: đếm, để r̂ = NaN, không thay giá trị P̂.
- Phân vị: q_τ = r̂ + phân vị thực nghiệm τ của phần dư return (r − r̂) trên đoạn calib.
- Chỉ số ADR-0008 dùng src/eval/metrics.py. Chỉ số trên mức giá (MAE, RMSE, MAPE) chỉ để minh
  họa kiểu bài báo, ADR-0008 không dùng để đánh giá; tính riêng ở đây, không thêm vào src/eval.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.eval import metrics as M
from src.forecast.returns import QUANTILE_LEVELS

from . import config as C
from .dataset import AssetSamples


def to_returns(p_hat: np.ndarray, p_t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(r̂, lỗi) với lỗi = P̂ hữu hạn nhưng ≤ 0; r̂ = NaN ở dòng lỗi hoặc P̂ NaN. P̂ không đổi."""
    p_hat = np.asarray(p_hat, dtype=float)
    p_t = np.asarray(p_t, dtype=float)
    error = np.isfinite(p_hat) & (p_hat <= 0)
    ok = np.isfinite(p_hat) & (p_hat > 0) & (p_t > 0)
    r_hat = np.full(len(p_hat), np.nan)
    r_hat[ok] = np.log(p_hat[ok] / p_t[ok])
    return r_hat, error


def calibrated_quantiles(
    r_hat: np.ndarray, residuals: np.ndarray, levels=QUANTILE_LEVELS
) -> np.ndarray:
    """(n, len(levels)): r̂ cộng phân vị thực nghiệm (nội suy tuyến tính) của phần dư calib."""
    res = np.asarray(residuals, dtype=float)
    res = res[np.isfinite(res)]
    if not len(res):
        raise ValueError("no finite calibration residuals")
    offsets = np.quantile(res, np.asarray(levels, dtype=float))
    return np.asarray(r_hat, dtype=float)[:, None] + offsets[None, :]


def return_metrics(y: np.ndarray, r_hat: np.ndarray, q: np.ndarray, q_base: np.ndarray) -> dict:
    """Chỉ số ADR-0008 trên log return h = 1 (naive: return = 0). DM HAC lag 0 trên |sai số|."""
    i10, i90 = QUANTILE_LEVELS.index(0.10), QUANTILE_LEVELS.index(0.90)
    naive = np.zeros_like(y)
    dm, p = M.diebold_mariano(np.abs(y - r_hat), np.abs(y - naive), h=1, hac_lag=0)
    return {
        "n": len(y),
        "mae_ratio_vs_naive": M.mae_ratio_vs_naive(y, r_hat, naive),
        "sign_accuracy": M.sign_accuracy(y, r_hat),
        "up_rate": M.up_rate(y),
        "pinball_skill": M.pinball_skill(y, q, q_base),
        "coverage_80": M.coverage_80(y, q[:, i10], q[:, i90]),
        "baseline_coverage_80": M.coverage_80(y, q_base[:, i10], q_base[:, i90]),
        "dm_stat_vs_naive": dm,
        "dm_p_vs_naive": p,
    }


def price_metrics(p_true: np.ndarray, p_hat: np.ndarray, p_t: np.ndarray) -> dict:
    """Kiểu bài báo, CHỈ ĐỂ MINH HỌA (ADR-0008 không dùng): MAE, RMSE, MAPE trên mức giá một bước
    tới, kèm naive (giá mai = giá hôm nay). MAPE chỉ trên cặp có giá thực > 0."""
    out = {}
    for name, pred in (("model", p_hat), ("naive", p_t)):
        e = p_true - pred
        pos = p_true > 0
        out[f"mae_{name}"] = float(np.mean(np.abs(e)))
        out[f"rmse_{name}"] = float(np.sqrt(np.mean(e**2)))
        out[f"mape_{name}"] = float(np.mean(np.abs(e[pos] / p_true[pos])) * 100)
    out["mape_excluded_pairs"] = int((p_true <= 0).sum())
    return out


def aggregate_seeds(df: pd.DataFrame, keys: list[str], cols: list[str]) -> pd.DataFrame:
    """Trung bình và min–max qua seed: cột <c>_mean, <c>_min, <c>_max."""
    g = df.groupby(keys, sort=False)[cols]
    out = pd.concat({"mean": g.mean(), "min": g.min(), "max": g.max()}, axis=1).swaplevel(axis=1)
    out.columns = [f"{c}_{s}" for c, s in out.columns]
    order = [f"{c}_{s}" for c in cols for s in ("mean", "min", "max")]
    return out[order].reset_index()


def mechanism_diagnostics(sm: AssetSamples, mask: np.ndarray) -> list[dict]:
    """Tại cùng ngày gốc, giá trị cuối cửa sổ (tại t) của từng thành phần: R-full so với R-causal.
    Chỉ số tổng hợp: tương quan, sai lệch tuyệt đối trung bình, và sai lệch đó chia trung bình |giá|."""
    a = sm.X["r_full"][mask, -1, :]
    b = sm.X["r_causal"][mask, -1, :]
    scale = float(np.mean(np.abs(sm.p_t[mask])))
    rows = []
    for k, name in enumerate(C.COMPONENTS):
        d = np.abs(a[:, k] - b[:, k])
        rows.append(
            {
                "asset": sm.asset,
                "component": name,
                "n": int(mask.sum()),
                "corr": float(np.corrcoef(a[:, k], b[:, k])[0, 1]),
                "mean_abs_diff": float(d.mean()),
                "mean_abs_diff_rel_price": float(d.mean() / scale),
            }
        )
    return rows

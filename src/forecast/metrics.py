"""Chỉ số đánh giá cho dự đoán return của CPAWS. Mọi thí nghiệm báo cáo cạnh mốc naive
(return = 0, tức giá ngày mai = hôm nay). Không có MAPE trên giá: chỉ số đó cho "độ chính xác 99%" ảo."""

from __future__ import annotations

import math

import numpy as np


def mae(y_true, y_pred) -> float:
    return float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred))))


def rmse(y_true, y_pred) -> float:
    return float(np.sqrt(np.mean((np.asarray(y_true) - np.asarray(y_pred)) ** 2)))


def mae_ratio_vs_naive(y_true, y_pred, y_naive) -> float:
    """MAE of the model divided by MAE of the naive forecast on the same test points.
    < 1 means the model beats naive."""
    return mae(y_true, y_pred) / mae(y_true, y_naive)


def mase(y_true, y_pred, train_series, m: int = 1) -> float:
    """Classic MASE: scale = in-sample MAE of the m-step naive forecast on the training data."""
    train_series = np.asarray(train_series, dtype=float)
    scale = np.mean(np.abs(train_series[m:] - train_series[:-m]))
    return mae(y_true, y_pred) / scale


def mase_returns(y_true, y_pred, train_returns) -> float:
    """MASE cho return: chia MAE cho sai số trung bình của naive (return = 0) trên tập train.
    < 1 nghĩa là thắng naive."""
    scale = float(np.mean(np.abs(np.asarray(train_returns, dtype=float))))
    return mae(y_true, y_pred) / scale


def sign_accuracy(y_true, y_pred) -> float:
    """Tỷ lệ đoán đúng chiều của return (bỏ các điểm return thực bằng 0)."""
    real, pred = np.sign(np.asarray(y_true, dtype=float)), np.sign(np.asarray(y_pred, dtype=float))
    keep = real != 0
    return float(np.mean(real[keep] == pred[keep]))


def pinball_loss(y_true, y_q, tau: float) -> float:
    """Quantile (pinball) loss cho phân vị tau. Càng nhỏ càng tốt."""
    diff = np.asarray(y_true, dtype=float) - np.asarray(y_q, dtype=float)
    return float(np.mean(np.maximum(tau * diff, (tau - 1) * diff)))


def brier_score(prob_up, y_true) -> float:
    """Brier score cho xác suất tăng. Dự đoán 0,5 cố định cho 0,25; thấp hơn là tốt hơn."""
    outcome = (np.asarray(y_true, dtype=float) > 0).astype(float)
    return float(np.mean((np.asarray(prob_up, dtype=float) - outcome) ** 2))


def interval_coverage(y_true, lower, upper) -> tuple[float, float]:
    """(share of true values inside [lower, upper], mean interval width)."""
    y_true, lower, upper = map(np.asarray, (y_true, lower, upper))
    inside = (y_true >= lower) & (y_true <= upper)
    return float(np.mean(inside)), float(np.mean(upper - lower))


def past_rolling_std(changes, window: int = 30) -> np.ndarray:
    """Std of the previous `window` changes, EXCLUDING the current one (causal).
    First `window` values are NaN."""
    changes = np.asarray(changes, dtype=float)
    out = np.full(len(changes), np.nan)
    for i in range(window, len(changes)):
        out[i] = np.std(changes[i - window : i], ddof=1)
    return out


def spike_labels(changes, window: int = 30, k: float = 2.5, direction: str = "both") -> np.ndarray:
    """Mark spikes: |change| > k * past rolling std. direction: 'up', 'down' or 'both'.
    Fix window and k BEFORE running experiments and never tune them on the test set."""
    changes = np.asarray(changes, dtype=float)
    thr = k * past_rolling_std(changes, window)
    with np.errstate(invalid="ignore"):
        if direction == "up":
            lab = changes > thr
        elif direction == "down":
            lab = changes < -thr
        else:
            lab = np.abs(changes) > thr
    return np.where(np.isnan(thr), False, lab)


def spike_scores(true_spike, pred_spike) -> dict:
    """Precision, recall and false-alarm rate. Always report them together:
    an over-predicting model can reach high recall with many false alarms."""
    t = np.asarray(true_spike, dtype=bool)
    p = np.asarray(pred_spike, dtype=bool)
    tp, fp = int(np.sum(t & p)), int(np.sum(~t & p))
    fn, tn = int(np.sum(t & ~p)), int(np.sum(~t & ~p))
    return {
        "precision": tp / (tp + fp) if tp + fp else float("nan"),
        "recall": tp / (tp + fn) if tp + fn else float("nan"),
        "false_alarm_rate": fp / (fp + tn) if fp + tn else float("nan"),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def peak_mae(y_true, y_pred, mask) -> float:
    """MAE restricted to spike days (mask = spike_labels of the true changes)."""
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return float("nan")
    return mae(np.asarray(y_true)[mask], np.asarray(y_pred)[mask])


def diebold_mariano(err_a, err_b, h: int = 1, power: int = 1) -> tuple[float, float]:
    """Diebold-Mariano test with the Harvey et al. small-sample correction.
    err_a, err_b: forecast errors of two models on the same points.
    Returns (statistic, two-sided p-value). Negative statistic = model A is better."""
    d = np.abs(np.asarray(err_a)) ** power - np.abs(np.asarray(err_b)) ** power
    n = len(d)
    d_mean = d.mean()
    gamma = [np.sum((d[k:] - d_mean) * (d[: n - k] - d_mean)) / n for k in range(h)]
    var = (gamma[0] + 2 * sum(gamma[1:])) / n
    if var <= 0:
        return float("nan"), float("nan")
    stat = d_mean / math.sqrt(var)
    stat *= math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(stat) / math.sqrt(2))))
    return float(stat), float(p)

"""Chỉ số đánh giá dự báo log return của CPAWS theo ADR-0008.

Các hàm này chỉ tính metric trên mẫu đầu vào đã được lọc ở src/eval/.
Không tự sửa phân vị và không truy cập nhãn tương lai hoặc baseline lịch sử.
Các hàm RMSE/spike cũ được giữ vì tương thích, KHÔNG dùng trong báo cáo ADR-0008.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import t as student_t

QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def _paired_1d(a, b) -> tuple[np.ndarray, np.ndarray]:
    """Validate already-aligned, finite data; filtering happens in src/eval/."""
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
        raise ValueError("inputs must be aligned 1-D arrays with the same length")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise ValueError("metrics need finite inputs; filter invalid samples in src/eval/")
    return x, y


def _quantile_inputs(y_true, quantiles) -> tuple[np.ndarray, np.ndarray]:
    """Input shape (n, 7), sorted by fixed tau order. Never normalize again."""
    y = np.asarray(y_true, dtype=float)
    q = np.asarray(quantiles, dtype=float)
    if y.ndim != 1 or q.shape != (len(y), len(QUANTILE_LEVELS)):
        raise ValueError("y_true must be (n,), quantiles must be (n, 7)")
    if not (np.all(np.isfinite(y)) and np.all(np.isfinite(q))):
        raise ValueError("target/quantiles must be finite; filter invalid samples in src/eval/")
    if np.any(np.diff(q, axis=1) < 0):
        raise ValueError("quantiles cross: normalize once upstream, not inside metrics")
    return y, q


def _interval_inputs(y_true, lower, upper) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y, low = _paired_1d(y_true, lower)
    _, high = _paired_1d(y_true, upper)
    if np.any(low > high):
        raise ValueError("lower quantile must not exceed upper quantile")
    return y, low, high


def mae(y_true, y_pred) -> float:
    return float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred))))


def rmse(y_true, y_pred) -> float:
    return float(np.sqrt(np.mean((np.asarray(y_true) - np.asarray(y_pred)) ** 2)))


def mae_ratio_vs_naive(y_true, y_pred, y_naive) -> float:
    """MAE of the model divided by MAE of the naive forecast on the same test points.
    < 1 means the model beats naive."""
    baseline = mae(y_true, y_naive)
    return float(mae(y_true, y_pred) / baseline) if baseline > 0 else float("nan")


def mase(y_true, y_pred, train_series, m: int = 1) -> float:
    """Classic MASE: scale = in-sample MAE of the m-step naive forecast on the training data."""
    train_series = np.asarray(train_series, dtype=float)
    scale = np.mean(np.abs(train_series[m:] - train_series[:-m]))
    return float(mae(y_true, y_pred) / scale) if scale > 0 else float("nan")


def mase_returns(y_true, y_pred, train_returns) -> float:
    """MASE cho return: chia MAE cho sai số trung bình của naive (return = 0) trên tập train.
    < 1 nghĩa là thắng naive."""
    scale = float(np.mean(np.abs(np.asarray(train_returns, dtype=float))))
    return float(mae(y_true, y_pred) / scale) if scale > 0 else float("nan")


def sign_accuracy(y_true, y_pred) -> float:
    """Đúng chiều; loại cả y=0 và q50=0 theo ADR-0008."""
    y, pred = _paired_1d(y_true, y_pred)
    keep = (y != 0) & (pred != 0)
    if not np.any(keep):
        return float("nan")
    return float(np.mean(np.sign(y[keep]) == np.sign(pred[keep])))


def pinball_loss(y_true, y_q, tau: float) -> float:
    """Quantile (pinball) loss cho phân vị tau. Càng nhỏ càng tốt."""
    diff = np.asarray(y_true, dtype=float) - np.asarray(y_q, dtype=float)
    return float(np.mean(np.maximum(tau * diff, (tau - 1) * diff)))


def brier_score(prob_up, y_true) -> float:
    """Brier score cho xác suất tăng. Dự đoán 0,5 cố định cho 0,25; thấp hơn là tốt hơn."""
    prob, y = _paired_1d(prob_up, y_true)
    if np.any((prob < 0) | (prob > 1)):
        raise ValueError("prob_up must be in [0, 1]")
    if not len(y):
        return float("nan")
    outcome = (y > 0).astype(float)
    return float(np.mean((prob - outcome) ** 2))


def interval_coverage(y_true, lower, upper) -> tuple[float, float]:
    """(share of true values inside [lower, upper], mean interval width)."""
    y_true, lower, upper = map(np.asarray, (y_true, lower, upper))
    inside = (y_true >= lower) & (y_true <= upper)
    return float(np.mean(inside)), float(np.mean(upper - lower))


def mean_pinball_loss(y_true, quantiles) -> float:
    """Mean of seven pinball losses per sample, then mean over samples.

    quantiles: array (n,7) ordered by QUANTILE_LEVELS. No implicit normalization.
    """
    y, q = _quantile_inputs(y_true, quantiles)
    if not len(y):
        return float("nan")
    tau = np.asarray(QUANTILE_LEVELS, dtype=float)[None, :]
    diff = y[:, None] - q
    return float(np.mean(np.maximum(tau * diff, (tau - 1) * diff)))


def pinball_skill(y_true, quantiles, baseline_quantiles) -> float:
    """1 - mean_pinball(model) / mean_pinball(causal_252_baseline).

    Inputs must be aligned on the same forecast origins. If the denominator is
    zero, return NaN; the table adapter will set status=undefined while keeping n_obs.
    """
    model_loss = mean_pinball_loss(y_true, quantiles)
    baseline_loss = mean_pinball_loss(y_true, baseline_quantiles)
    if not np.isfinite(baseline_loss) or baseline_loss <= 0:
        return float("nan")
    return float(1.0 - model_loss / baseline_loss)


def quantile_hit_rates(y_true, quantiles) -> dict[float, float]:
    """Empirical P(y <= q_tau), one result for each of the seven tau levels."""
    y, q = _quantile_inputs(y_true, quantiles)
    if not len(y):
        return {tau: float("nan") for tau in QUANTILE_LEVELS}
    hit = np.mean(y[:, None] <= q, axis=0)
    return {tau: float(rate) for tau, rate in zip(QUANTILE_LEVELS, hit, strict=True)}


def coverage_80(y_true, q10, q90) -> float:
    """Empirical coverage of nominal 80% interval [q10, q90]."""
    y, lower, upper = _interval_inputs(y_true, q10, q90)
    if not len(y):
        return float("nan")
    return float(np.mean((lower <= y) & (y <= upper)))


def width_80(q10, q90) -> float:
    """Mean width of [q10, q90] in log-return units."""
    lower, upper = _paired_1d(q10, q90)
    if np.any(lower > upper):
        raise ValueError("q10 must not exceed q90")
    if not len(lower):
        return float("nan")
    return float(np.mean(upper - lower))


def interval_score_80(y_true, q10, q90) -> float:
    """Proper interval score for an 80% interval (alpha = 0.2)."""
    y, lower, upper = _interval_inputs(y_true, q10, q90)
    if not len(y):
        return float("nan")
    score = (upper - lower) + 10.0 * np.maximum(lower - y, 0) + 10.0 * np.maximum(y - upper, 0)
    return float(np.mean(score))


def brier_skill(prob_up, y_true, baseline_prob_up) -> float:
    """1 - BS(model) / BS(baseline); same target and forecast origins."""
    model = brier_score(prob_up, y_true)
    baseline = brier_score(baseline_prob_up, y_true)
    if not np.isfinite(baseline) or baseline <= 0:
        return float("nan")
    return float(1.0 - model / baseline)


def brier_skill_vs_half(prob_up, y_true) -> float:
    """Brier skill relative to fixed probability 0.5 (secondary reference)."""
    y = np.asarray(y_true, dtype=float)
    return brier_skill(prob_up, y, np.full_like(y, 0.5))


def up_rate(y_true) -> float:
    """Fraction of actual h-session log returns that are positive."""
    y = np.asarray(y_true, dtype=float)
    if y.ndim != 1 or not np.all(np.isfinite(y)):
        raise ValueError("y_true must be a finite 1-D array")
    if not len(y):
        return float("nan")
    return float(np.mean(y > 0))


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


def diebold_mariano(loss_a, loss_b, h: int = 1, hac_lag: int | None = None) -> tuple[float, float]:
    """DM on *paired per-origin losses*, with Bartlett HAC, HLN and t(T-1) p-value.

    Negative statistic => A has lower average loss than B. No error transform:
    callers compute (7-quantile mean) pinball loss for each origin first.
    Defaults to HAC lag h-1; any specified lag must be >= h-1 per ADR-0008.
    """
    a, b = _paired_1d(loss_a, loss_b)
    if not isinstance(h, int) or h < 1:
        raise ValueError("h must be a positive integer")
    lag = h - 1 if hac_lag is None else hac_lag
    if not isinstance(lag, int) or lag < h - 1 or lag < 0:
        raise ValueError("hac_lag must be >= h-1")
    n = len(a)
    if n <= max(h, lag + 1):
        return float("nan"), float("nan")
    d = a - b
    # A constant decimal difference can acquire a tiny artificial variance
    # when its rounded sample mean is subtracted. DM is undefined in this case.
    if np.all(d == d[0]):
        return float("nan"), float("nan")
    centered = d - np.mean(d)
    gamma0 = float(np.dot(centered, centered) / n)
    # Bartlett/Newey-West weights ensure a valid long-run variance estimate.
    long_run_var = gamma0
    for k in range(1, lag + 1):
        gamma_k = float(np.dot(centered[k:], centered[:-k]) / n)
        long_run_var += 2.0 * (1.0 - k / (lag + 1)) * gamma_k
    if long_run_var <= 0 or not np.isfinite(long_run_var):
        return float("nan"), float("nan")
    correction_sq = (n + 1 - 2 * h + h * (h - 1) / n) / n
    if correction_sq <= 0:
        return float("nan"), float("nan")
    dm_stat = float(np.mean(d) / math.sqrt(long_run_var / n) * math.sqrt(correction_sq))
    p = float(2.0 * student_t.sf(abs(dm_stat), df=n - 1))
    return dm_stat, p


def holm_adjust(p_values) -> np.ndarray:
    """Holm family-wise adjusted p-values; NaN entries remain NaN.

    Define the full family (e.g., 4 assets x 7 horizons) before calling.
    NaN means an unavailable test; it still counts toward family size.
    """
    p = np.asarray(p_values, dtype=float)
    if p.ndim != 1 or np.any(np.isinf(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("p_values must be a 1-D array with values in [0, 1] or NaN")
    valid = np.flatnonzero(np.isfinite(p))
    order = valid[np.argsort(p[valid])]
    out = np.full(p.shape, np.nan)
    # The family is fixed in advance: unavailable (NaN) tests still count.
    # Dropping them from the family would make the Holm correction too liberal.
    family_size = len(p)
    if len(order):
        scaled = np.array([(family_size - i) * p[idx] for i, idx in enumerate(order)])
        out[order] = np.minimum(1.0, np.maximum.accumulate(scaled))
    return out


def block_bootstrap_ci(
    values,
    statistic,
    *,
    block_length: int,
    n_resamples: int = 1000,
    confidence_level: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Circular moving-block bootstrap CI, resampling the first (time) axis.

    `values` can have extra aligned columns (e.g. paired model losses).
    `statistic(sample)` computes one scalar from each bootstrapped dataset.
    If any replicate produces a non-finite value, both CI bounds are NaN
    (do not silently exclude hard resamples and bias the interval).
    Block length/seed/CI level must be fixed in config before looking at test.
    """
    data = np.asarray(values, dtype=float)
    if data.ndim < 1 or not np.all(np.isfinite(data)):
        raise ValueError("values must be a finite array with a time dimension")
    n = len(data)
    if n == 0:
        return float("nan"), float("nan")
    if not isinstance(block_length, int) or not 1 <= block_length <= n:
        raise ValueError("block_length must be in [1, n_obs]")
    if not isinstance(n_resamples, int) or n_resamples < 1:
        raise ValueError("n_resamples must be >= 1")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    rng = np.random.default_rng(seed)
    scores = []
    n_blocks = math.ceil(n / block_length)
    offsets = np.arange(block_length)
    for _ in range(n_resamples):
        starts = rng.integers(0, n, size=n_blocks)
        idx = ((starts[:, None] + offsets[None, :]) % n).ravel()[:n]
        score = float(statistic(data[idx]))
        if np.isfinite(score):
            scores.append(score)
    # Never publish a CI conditional on silently discarded invalid replicates.
    # The caller must report an undefined CI and inspect the metric/baseline.
    if len(scores) != n_resamples:
        return float("nan"), float("nan")
    alpha = (1 - confidence_level) / 2
    low, high = np.quantile(scores, [alpha, 1 - alpha])
    return float(low), float(high)

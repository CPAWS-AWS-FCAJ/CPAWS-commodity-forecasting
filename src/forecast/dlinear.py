"""DLinear MVP: replicated-edge centered average and median-anchored quantiles."""

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from src.forecast.returns import QUANTILE_LEVELS


class DLinear(nn.Module):
    """Receive already scaled float32 [B,60,1]; output log-return [B,7,7]."""

    def __init__(self):
        super().__init__()
        self.trend = nn.Linear(60, 49)
        self.seasonal = nn.Linear(60, 49)

    def initialize_from_targets(self, targets):
        y = np.asarray(targets, dtype=np.float64)
        if y.ndim != 2 or y.shape[1] != 7 or not len(y) or not np.isfinite(y).all():
            raise ValueError("targets must be nonempty finite [N,7] training targets")
        q = np.quantile(y, QUANTILE_LEVELS, axis=0).T
        gaps = np.maximum(np.diff(q, axis=1), 1e-6)
        raw = np.empty_like(q)
        raw[:, 3] = q[:, 3]
        raw[:, :3] = gaps[:, :3] + np.log(-np.expm1(-gaps[:, :3]))
        raw[:, 4:] = gaps[:, 3:] + np.log(-np.expm1(-gaps[:, 3:]))
        with torch.no_grad():
            self.trend.weight.zero_()
            self.seasonal.weight.zero_()
            self.seasonal.bias.zero_()
            self.trend.bias.copy_(torch.as_tensor(raw.ravel(), dtype=torch.float32))

    @staticmethod
    def decompose(x):
        if x.ndim != 3 or x.shape[1:] != (60, 1) or not torch.isfinite(x).all():
            raise ValueError("input must be finite [B,60,1]")
        series = x.squeeze(-1)
        trend = F.avg_pool1d(F.pad(series.unsqueeze(1), (12, 12), mode="replicate"), 25, 1)
        return trend.squeeze(1), series - trend.squeeze(1)

    def forward(self, x):
        trend, seasonal = self.decompose(x)
        raw = (self.trend(trend) + self.seasonal(seasonal)).reshape(-1, 7, 7)
        g = F.softplus(raw)
        median = raw[..., 3]
        q25 = median - g[..., 2]
        q10 = q25 - g[..., 1]
        q05 = q10 - g[..., 0]
        q75 = median + g[..., 4]
        q90 = q75 + g[..., 5]
        q95 = q90 + g[..., 6]
        return torch.stack([q05, q10, q25, median, q75, q90, q95], dim=-1)


def pinball_training_loss(prediction, target):
    """Differentiable mean across batch, horizons and the seven tau levels."""
    if prediction.ndim != 3 or prediction.shape[1:] != (7, 7):
        raise ValueError("prediction must be [B,7,7]")
    if target.shape != prediction.shape[:2]:
        raise ValueError("target must be [B,7]")
    tau = prediction.new_tensor(QUANTILE_LEVELS)
    error = target.unsqueeze(-1) - prediction
    return torch.maximum(tau * error, (tau - 1) * error).mean()

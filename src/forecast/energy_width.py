"""K3b S2 (torch, chỉ để train): giữ trung vị của mốc 252 phiên, học độ rộng khoảng từ năng lượng
IMF và tỷ số biến động (docs/experiments/k3b-volatility-plan.md mục 3, 6.3).

Runtime NumPy tương đương: src/forecast/energy_width_numpy.py (cùng công thức, có test parity).
"""

import torch
from torch import nn

from src.forecast.ceemdan_dlinear import DTYPE, anchor_quantiles
from src.forecast.ceemdan_dlinear_numpy import MEDIAN, N_H
from src.forecast.energy_width_numpy import N_GAP_OUT, N_GAPS


class EnergyWidth(nn.Module):
    """Nhận đặc trưng đã chuẩn hóa [B, F] float64 và mốc [B,7,7]; xuất phân vị [B,7,7].

    Δg = x·Wᵀ + b (42 = 7 h × 6 khoảng cách), Δm = 0. Khởi tạo W = b = 0: mô hình trùng mốc 252
    phiên lúc khởi tạo."""

    def __init__(self, n_features: int):
        super().__init__()
        self.n_features = int(n_features)
        self.weight = nn.Parameter(torch.zeros(N_GAP_OUT, self.n_features, dtype=DTYPE))
        self.bias = nn.Parameter(torch.zeros(N_GAP_OUT, dtype=DTYPE))

    def forward(self, x, baseline):
        if x.ndim != 2 or x.shape[1] != self.n_features:
            raise ValueError(f"input must be [B,{self.n_features}]")
        if not torch.isfinite(x).all():
            raise ValueError("input must be finite")
        delta_g = (x @ self.weight.T + self.bias).reshape(-1, N_H, N_GAPS)
        zero = delta_g.new_zeros(delta_g.shape[:-1] + (1,))
        raw = torch.cat([delta_g[..., :MEDIAN], zero, delta_g[..., MEDIAN:]], dim=-1)
        return anchor_quantiles(raw, baseline)

    def numpy_weights(self) -> dict:
        return {
            name: value.detach().cpu().numpy().copy()
            for name, value in (("weight", self.weight), ("bias", self.bias))
        }

"""CEEMDAN-DLinear K3 (torch, chỉ để train): tuyến tính, chia sẻ trọng số giữa các cột, đầu ra neo
vào mốc 252 phiên (docs/experiments/k3-ceemdan-plan.md mục 3).

Runtime NumPy tương đương: src/forecast/ceemdan_dlinear_numpy.py (cùng công thức, có test parity).
"""

import torch
from torch import nn

from src.forecast.ceemdan_dlinear_numpy import GAP_SLOTS, MEDIAN, N_H, N_OUT, N_Q

DTYPE = torch.float64  # neo vào mốc cần atol 1e-9; float32 không đủ


def anchor_quantiles(raw, baseline):
    """raw [B,7,7] (Δm ở cột 3, Δg ở các cột còn lại) + mốc [B,7,7] → phân vị không giảm."""
    if baseline.ndim != 3 or baseline.shape[1:] != (N_H, N_Q) or not torch.isfinite(baseline).all():
        raise ValueError("baseline must be finite [B,7,7]")
    base_gaps = baseline.diff(dim=-1)
    if (base_gaps < 0).any():
        raise ValueError("baseline quantiles must be nondecreasing")
    gaps = base_gaps * torch.exp(raw[..., list(GAP_SLOTS)])
    median = baseline[..., MEDIAN] + raw[..., MEDIAN]
    q25 = median - gaps[..., 2]
    q10 = q25 - gaps[..., 1]
    q05 = q10 - gaps[..., 0]
    q75 = median + gaps[..., 3]
    q90 = q75 + gaps[..., 4]
    q95 = q90 + gaps[..., 5]
    return torch.stack([q05, q10, q25, median, q75, q90, q95], dim=-1)


class CeemdanDLinear(nn.Module):
    """Nhận đặc trưng đã chuẩn hóa [B, L, C] float64 và mốc [B,7,7]; xuất phân vị [B,7,7].

    Mỗi cột qua cùng ánh xạ tuyến tính L → 49 (shared_weight, không bias), nhân hệ số riêng của
    cột (column_weight), cộng lại, cộng bias 49. Khởi tạo shared_weight = 0, bias = 0,
    column_weight = 1: Δm = Δg = 0, tức mô hình trùng mốc 252 phiên lúc khởi tạo."""

    def __init__(self, seq_len: int, n_columns: int):
        super().__init__()
        self.seq_len, self.n_columns = int(seq_len), int(n_columns)
        self.shared_weight = nn.Parameter(torch.zeros(N_OUT, self.seq_len, dtype=DTYPE))
        self.column_weight = nn.Parameter(torch.ones(self.n_columns, dtype=DTYPE))
        self.bias = nn.Parameter(torch.zeros(N_OUT, dtype=DTYPE))

    def forward(self, x, baseline):
        if x.ndim != 3 or x.shape[1:] != (self.seq_len, self.n_columns):
            raise ValueError(f"input must be [B,{self.seq_len},{self.n_columns}]")
        if not torch.isfinite(x).all():
            raise ValueError("input must be finite")
        z = torch.einsum("blc,ol->bco", x, self.shared_weight)
        raw = torch.einsum("bco,c->bo", z, self.column_weight) + self.bias
        return anchor_quantiles(raw.reshape(-1, N_H, N_Q), baseline)

    def numpy_weights(self) -> dict:
        return {
            name: value.detach().cpu().numpy().copy()
            for name, value in (
                ("shared_weight", self.shared_weight),
                ("column_weight", self.column_weight),
                ("bias", self.bias),
            )
        }

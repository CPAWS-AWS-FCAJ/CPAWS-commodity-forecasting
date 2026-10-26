"""NumPy-only runtime cho CEEMDAN-DLinear K3 (để Lambda predict dùng sau này; không import torch).

Kiến trúc (docs/experiments/k3-ceemdan-plan.md mục 3), giống hệt src/forecast/ceemdan_dlinear.py:
- mỗi cột đặc trưng (đã chuẩn hóa) qua cùng một ánh xạ tuyến tính L → 49, nhân hệ số riêng của
  cột, cộng lại, cộng bias 49;
- 49 = 7 h × (Δm + 6 Δg). Trung vị = q50 mốc 252 phiên + Δm; mỗi khoảng cách giữa hai phân vị
  liền kề = khoảng cách của mốc × exp(Δg). Phân vị luôn không giảm; trọng số 0 → đúng mốc.
- Nhiều seed: trung bình phân vị của các seed (caller gọi normalize_quantiles() đúng một lần).
"""

import hashlib
import json
from pathlib import Path

import numpy as np

ARCHITECTURE = "ceemdan-dlinear-shared-anchored-v1"
LEVELS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
N_H, N_Q = 7, 7
N_OUT = N_H * N_Q
MEDIAN = 3
GAP_SLOTS = (0, 1, 2, 4, 5, 6)  # vị trí Δg cho 6 khoảng cách q05→q10 … q90→q95
MEMBER_KEYS = ("shared_weight", "column_weight", "bias")


def check_baseline(baseline) -> np.ndarray:
    b = np.asarray(baseline, dtype=np.float64)
    if b.ndim != 3 or b.shape[1:] != (N_H, N_Q) or not np.isfinite(b).all():
        raise ValueError("baseline must be finite [B,7,7]")
    if (np.diff(b, axis=-1) < 0).any():
        raise ValueError("baseline quantiles must be nondecreasing")
    return b


def anchor_quantiles(raw, baseline) -> np.ndarray:
    """raw [B,7,7] (Δm ở cột 3, Δg ở các cột còn lại) + mốc [B,7,7] → phân vị [B,7,7]."""
    b = check_baseline(baseline)
    gaps = np.diff(b, axis=-1) * np.exp(raw[..., GAP_SLOTS])
    q = np.empty_like(b)
    q[..., MEDIAN] = b[..., MEDIAN] + raw[..., MEDIAN]
    for i in (2, 1, 0):
        q[..., i] = q[..., i + 1] - gaps[..., i]
    for i in (4, 5, 6):
        q[..., i] = q[..., i - 1] + gaps[..., i - 1]
    return q


class CeemdanDLinearNumpy:
    """members: danh sách trọng số theo seed {shared_weight [49,L], column_weight [C], bias [49]};
    mean/std: ColumnScaler của train [C]. predict nhận đặc trưng CHƯA chuẩn hóa từng cột (đầu ra
    ceemdan_inputs) và mốc 252 phiên tại t."""

    def __init__(self, members, mean, std):
        if not members:
            raise ValueError("need at least one member")
        self.members = []
        for member in members:
            if set(member) != set(MEMBER_KEYS):
                raise ValueError("member weight keys do not match CEEMDAN-DLinear")
            m = {k: np.asarray(member[k], dtype=np.float64).copy() for k in MEMBER_KEYS}
            if not all(np.isfinite(v).all() for v in m.values()):
                raise ValueError("non-finite weights")
            if m["shared_weight"].ndim != 2 or m["shared_weight"].shape[0] != N_OUT:
                raise ValueError("shared_weight must be [49, L]")
            if m["bias"].shape != (N_OUT,) or m["column_weight"].ndim != 1:
                raise ValueError("invalid bias/column_weight shape")
            self.members.append(m)
        shapes = {(m["shared_weight"].shape[1], m["column_weight"].shape[0]) for m in self.members}
        if len(shapes) != 1:
            raise ValueError("members disagree on seq_len/columns")
        self.seq_len, self.n_columns = shapes.pop()
        self.mean = np.asarray(mean, dtype=np.float64)
        self.std = np.asarray(std, dtype=np.float64)
        if self.mean.shape != (self.n_columns,) or self.std.shape != (self.n_columns,):
            raise ValueError("scaler must have one entry per column")
        if (
            not (np.isfinite(self.mean).all() and np.isfinite(self.std).all())
            or (self.std <= 0).any()
        ):
            raise ValueError("invalid scaler")

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        try:
            config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
            scaler = json.loads((directory / "scaler.json").read_text(encoding="utf-8"))
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if (
                config.get("architecture") != ARCHITECTURE
                or config.get("quantile_levels") != LEVELS
            ):
                raise ValueError("unsupported CEEMDAN-DLinear config")
            digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
            if manifest["config_hash"] != digest:
                raise ValueError("config hash mismatch")
            for filename in ("weights.npz", "scaler.json"):
                actual = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
                if manifest["file_hashes"][filename] != actual:
                    raise ValueError(f"artifact hash mismatch: {filename}")
            with np.load(directory / "weights.npz", allow_pickle=False) as archive:
                weights = dict(archive)
            members = [
                {k: weights[f"seed{seed}_{k}"] for k in MEMBER_KEYS} for seed in config["seeds"]
            ]
            model = cls(members, scaler["mean"], scaler["std"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"missing or invalid CEEMDAN-DLinear artifact: {exc}") from exc
        if model.seq_len != config["seq_len"] or model.n_columns != config["max_imf"] + 1:
            raise ValueError("weights do not match config seq_len/max_imf")
        return model

    def member_predict(self, features, baseline) -> np.ndarray:
        """Phân vị của từng seed: [n_members, B, 7, 7]."""
        x = np.asarray(features, dtype=np.float64)
        if x.ndim != 3 or x.shape[1:] != (self.seq_len, self.n_columns):
            raise ValueError(f"features must be [B,{self.seq_len},{self.n_columns}]")
        if not np.isfinite(x).all():
            raise ValueError("features must be finite")
        x = (x - self.mean) / self.std
        out = []
        for m in self.members:
            z = np.einsum("blc,ol->bco", x, m["shared_weight"])
            raw = np.einsum("bco,c->bo", z, m["column_weight"]) + m["bias"]
            out.append(anchor_quantiles(raw.reshape(-1, N_H, N_Q), baseline))
        q = np.stack(out)
        if not np.isfinite(q).all():
            raise ValueError("non-finite CEEMDAN-DLinear output")
        return q

    def predict(self, features, baseline) -> np.ndarray:
        """Trung bình phân vị của các seed, [B, 7, 7], chưa qua normalize_quantiles()."""
        return self.member_predict(features, baseline).mean(axis=0)

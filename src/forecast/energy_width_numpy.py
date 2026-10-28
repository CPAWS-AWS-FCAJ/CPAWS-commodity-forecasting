"""NumPy-only runtime cho K3b S2 (không import torch), cùng công thức với src/forecast/energy_width.py.

Kiến trúc (docs/experiments/k3b-volatility-plan.md mục 3, 6.3):
- đặc trưng [B, F] (F = 5: log năng lượng 4 cột IMF + log σ_short/σ_long), chuẩn hóa từng cột;
- Δg = W·x + b, W [42, F], b [42] = 7 h × 6 khoảng cách; Δm = 0 (trung vị = q50 mốc 252 phiên);
- mỗi khoảng cách giữa hai phân vị liền kề = khoảng cách của mốc × exp(Δg) (anchor_quantiles của K3).
  W = b = 0 → đúng mốc. Nhiều seed: trung bình phân vị (caller gọi normalize_quantiles() một lần).
"""

import hashlib
import json
from pathlib import Path

import numpy as np

from src.forecast.ceemdan_dlinear_numpy import LEVELS, MEDIAN, N_H, N_Q, anchor_quantiles

ARCHITECTURE = "k3b-s2-energy-width-anchored-v1"
N_GAPS = N_Q - 1
N_GAP_OUT = N_H * N_GAPS
MEMBER_KEYS = ("weight", "bias")


def gaps_to_raw(delta_g) -> np.ndarray:
    """Δg [B, 7, 6] → raw [B, 7, 7] của anchor_quantiles, Δm = 0 ở cột trung vị."""
    g = np.asarray(delta_g, dtype=np.float64)
    zero = np.zeros(g.shape[:-1] + (1,))
    return np.concatenate([g[..., :MEDIAN], zero, g[..., MEDIAN:]], axis=-1)


class EnergyWidthNumpy:
    """members: trọng số theo seed {weight [42, F], bias [42]}; mean/std: ColumnScaler của train
    [F]. predict nhận đặc trưng CHƯA chuẩn hóa [B, F] và mốc 252 phiên tại t [B, 7, 7]."""

    def __init__(self, members, mean, std):
        if not members:
            raise ValueError("need at least one member")
        self.members = []
        for member in members:
            if set(member) != set(MEMBER_KEYS):
                raise ValueError("member weight keys do not match energy-width model")
            m = {k: np.asarray(member[k], dtype=np.float64).copy() for k in MEMBER_KEYS}
            if not all(np.isfinite(v).all() for v in m.values()):
                raise ValueError("non-finite weights")
            if m["weight"].ndim != 2 or m["weight"].shape[0] != N_GAP_OUT:
                raise ValueError("weight must be [42, F]")
            if m["bias"].shape != (N_GAP_OUT,):
                raise ValueError("bias must be [42]")
            self.members.append(m)
        widths = {m["weight"].shape[1] for m in self.members}
        if len(widths) != 1:
            raise ValueError("members disagree on the number of features")
        self.n_features = widths.pop()
        self.mean = np.asarray(mean, dtype=np.float64)
        self.std = np.asarray(std, dtype=np.float64)
        if self.mean.shape != (self.n_features,) or self.std.shape != (self.n_features,):
            raise ValueError("scaler must have one entry per feature")
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
                raise ValueError("unsupported energy-width config")
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
            raise ValueError(f"missing or invalid energy-width artifact: {exc}") from exc
        if model.n_features != len(config["feature_names"]):
            raise ValueError("weights do not match config feature_names")
        return model

    def member_predict(self, features, baseline) -> np.ndarray:
        """Phân vị của từng seed: [n_members, B, 7, 7]."""
        x = np.asarray(features, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != self.n_features:
            raise ValueError(f"features must be [B,{self.n_features}]")
        if not np.isfinite(x).all():
            raise ValueError("features must be finite")
        x = (x - self.mean) / self.std
        out = []
        for m in self.members:
            delta_g = (x @ m["weight"].T + m["bias"]).reshape(-1, N_H, N_GAPS)
            out.append(anchor_quantiles(gaps_to_raw(delta_g), baseline))
        q = np.stack(out)
        if not np.isfinite(q).all():
            raise ValueError("non-finite energy-width output")
        return q

    def predict(self, features, baseline) -> np.ndarray:
        """Trung bình phân vị của các seed, [B, 7, 7], chưa qua normalize_quantiles()."""
        return self.member_predict(features, baseline).mean(axis=0)

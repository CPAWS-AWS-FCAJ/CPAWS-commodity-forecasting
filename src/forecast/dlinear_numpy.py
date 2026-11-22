"""NumPy-only DLinear runtime. Does not cut windows or import training packages."""

import hashlib
import json
from pathlib import Path

import numpy as np

LEVELS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
WEIGHT_SHAPES = {
    "trend_weight": (49, 60),
    "trend_bias": (49,),
    "seasonal_weight": (49, 60),
    "seasonal_bias": (49,),
}


class DLinearNumpy:
    def __init__(self, weights, mean, std):
        if set(weights) != set(WEIGHT_SHAPES):
            raise ValueError("artifact weight keys do not match DLinear")
        self.weights = {}
        for name, shape in WEIGHT_SHAPES.items():
            value = np.asarray(weights[name])
            if value.shape != shape or value.dtype != np.float32 or not np.isfinite(value).all():
                raise ValueError(f"invalid weight {name}")
            self.weights[name] = value.copy()
        self.mean = np.asarray(mean, dtype=np.float64)
        self.std = np.asarray(std, dtype=np.float64)
        if self.mean.shape != (1,) or self.std.shape != (1,):
            raise ValueError("scaler must have one feature")
        if (
            not np.isfinite(self.mean).all()
            or not np.isfinite(self.std).all()
            or (self.std <= 0).any()
        ):
            raise ValueError("invalid scaler")

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        try:
            config = json.loads((directory / "config.json").read_text())
            scaler = json.loads((directory / "scaler.json").read_text())
            manifest = json.loads((directory / "manifest.json").read_text())
            if not all(isinstance(obj, dict) for obj in (config, scaler, manifest)):
                raise ValueError("artifact JSON files must be objects")
            expected = {
                "architecture": "dlinear-median-softplus-v1",
                "window": 60,
                "kernel": 25,
                "padding": "replicate",
                "horizons": list(range(1, 8)),
                "quantile_levels": LEVELS,
                "feature_names": ["log_return_1_end"],
                "precision": "float32",
            }
            if any(config.get(k) != v for k, v in expected.items()):
                raise ValueError("unsupported DLinear config")
            digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
            if manifest["config_hash"] != digest:
                raise ValueError("config hash mismatch")
            required = {
                "fit_id",
                "model_version",
                "asset",
                "train_end",
                "max_training_target_date",
                "trained_at",
                "config_hash",
                "commit",
            }
            if not required <= manifest.keys() or any(
                not manifest[k] for k in required - {"commit"}
            ):
                raise ValueError("missing Fits metadata")
            for filename in ("weights.npz", "scaler.json"):
                actual = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
                if manifest["file_hashes"][filename] != actual:
                    raise ValueError(f"artifact hash mismatch: {filename}")
            with np.load(directory / "weights.npz", allow_pickle=False) as archive:
                weights = dict(archive)
            return cls(weights, scaler["mean"], scaler["std"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"missing or invalid DLinear artifact: {exc}") from exc

    def predict(self, windows):
        x = np.asarray(windows, dtype=np.float64)
        if x.ndim != 3 or x.shape[1:] != (60, 1) or not np.isfinite(x).all():
            raise ValueError("windows must be finite [B,60,1]")
        if not len(x):
            return np.empty((0, 7, 7), dtype=np.float32)
        x = ((x - self.mean) / self.std).astype(np.float32).squeeze(-1)
        padded = np.pad(x, ((0, 0), (12, 12)), mode="edge")
        # This averages an already supplied window, never creates input windows.
        trend = np.stack([padded[:, k : k + 60] for k in range(25)], axis=0).mean(axis=0)
        w = self.weights
        raw = (
            trend @ w["trend_weight"].T
            + w["trend_bias"]
            + (x - trend) @ w["seasonal_weight"].T
            + w["seasonal_bias"]
        ).reshape(-1, 7, 7)
        g = np.logaddexp(np.float32(0), raw)
        q = np.empty_like(raw)
        q[..., 3] = raw[..., 3]
        for i in (2, 1, 0):
            q[..., i] = q[..., i + 1] - g[..., i]
        for i in (4, 5, 6):
            q[..., i] = q[..., i - 1] + g[..., i]
        if not np.isfinite(q).all():
            raise ValueError("non-finite DLinear output")
        return q

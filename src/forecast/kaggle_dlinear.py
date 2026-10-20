"""Small integration checks shared by the Kaggle launcher and local package tests."""

from pathlib import Path

import numpy as np
import pandas as pd

from src.forecast.dlinear_data import ASSET_NAMES, prepare_training_data


def audit_training_data(prices_path, rejected_path):
    """Read external clean inputs; never require data or a checksum manifest in Git."""
    prices = pd.read_parquet(Path(prices_path))
    rejected = pd.read_parquet(Path(rejected_path))
    required = {"date", "asset", "price", "published_at", "source"}
    for name, frame in (("prices", prices), ("rejected", rejected)):
        if not required <= set(frame.columns):
            raise ValueError(f"{name}: missing schema columns")
        if frame.duplicated(["asset", "date"]).any():
            raise ValueError(f"{name}: duplicate asset/date")
        if pd.to_datetime(frame["date"], errors="coerce").isna().any():
            raise ValueError(f"{name}: invalid dates")
    if not set(ASSET_NAMES) <= set(prices["asset"]):
        raise ValueError("clean snapshot must contain all four model assets")
    prepared = {}
    for asset in ASSET_NAMES:
        data = prepare_training_data(prices, rejected, asset)
        if not len(data.X) or not np.isfinite(data.X).all() or not np.isfinite(data.y).all():
            raise ValueError(f"{asset}: no valid finite complete cases")
        if (data.target_dates > np.datetime64("2018-12-31")).any():
            raise ValueError(f"{asset}: training target after cutoff")
        if (data.base_dates < np.datetime64("2014-01-01")).any():
            raise ValueError(f"{asset}: training origin before split")
        prepared[asset] = data
    # Snapshot may retain usd_vnd for provenance; it is never a model input/target.
    return prices, rejected, prepared


def verify_trained_artifact(directory, data):
    """Check each trained artifact on all available train windows, CPU float32, atol=1e-6."""
    import torch

    from src.forecast.dlinear import DLinear
    from src.forecast.dlinear_numpy import DLinearNumpy

    runtime = DLinearNumpy.load(directory)
    model = DLinear().eval()
    model.load_state_dict(
        {
            name.replace("_weight", ".weight").replace("_bias", ".bias"): torch.from_numpy(
                value.copy()
            )
            for name, value in runtime.weights.items()
        }
    )
    largest = 0.0
    for start in range(0, len(data.X), 128):
        x = data.X[start : start + 128]
        scaled = ((x - runtime.mean) / runtime.std).astype(np.float32)
        with torch.no_grad():
            expected = model(torch.from_numpy(scaled)).numpy()
        actual = runtime.predict(x)
        largest = max(largest, float(np.max(np.abs(actual - expected))))
        if not np.allclose(actual, expected, atol=1e-6, rtol=0):
            raise ValueError(f"Torch/NumPy parity exceeds 1e-6: {largest}")
        if (
            actual.shape[1:] != (7, 7)
            or not np.isfinite(actual).all()
            or (np.diff(actual, axis=-1) < 0).any()
        ):
            raise ValueError("invalid quantile output")
    return largest

"""Repository-safe Kaggle integration tests using only synthetic temporary data."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from src.data import calendars
from src.data.config import ASSETS
from src.forecast.kaggle_dlinear import audit_training_data, verify_trained_artifact
from src.forecast.train_dlinear import export_artifact, train_model

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def synthetic_inputs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("dlinear-clean-fixture")
    frames = []
    for seed, asset in enumerate(("gold", "silver", "brent", "wti")):
        dates = calendars.sessions(ASSETS[asset].calendar, "2013-07-01", "2019-01-31")
        rng = np.random.default_rng(seed)
        frames.append(
            pd.DataFrame(
                {
                    "asset": asset,
                    "date": dates,
                    "price": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates)))),
                    "source": "yfinance",
                    "published_at": (dates + pd.Timedelta(days=1, hours=12)).tz_localize("UTC"),
                }
            )
        )
    prices = pd.concat(frames, ignore_index=True)
    rejected = prices.iloc[:0].copy()
    prices_path, rejected_path = folder / "prices.parquet", folder / "rejected.parquet"
    prices.to_parquet(prices_path, index=False)
    rejected.to_parquet(rejected_path, index=False)
    return prices_path, rejected_path


def test_external_inputs_all_assets_train_only(synthetic_inputs):
    prices, rejected, datasets = audit_training_data(*synthetic_inputs)
    assert len(prices) and len(rejected) == 0
    assert set(datasets) == {"gold", "silver", "brent", "wti"}
    for asset, data in datasets.items():
        assert data.audit["asset"] == asset
        assert data.y.shape == (len(data.X), 7)
        assert data.target_dates.max() <= np.datetime64("2018-12-31")
        assert sum(data.audit["excluded_by_reason"].values()) == data.audit["n_excluded"]


@pytest.mark.parametrize("problem", ["duplicate", "missing_column", "missing_asset"])
def test_external_inputs_reject_bad_schema(synthetic_inputs, tmp_path, problem):
    prices_path, rejected_path = synthetic_inputs
    frame = pd.read_parquet(prices_path)
    if problem == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    elif problem == "missing_column":
        frame = frame.drop(columns="published_at")
    else:
        frame = frame.loc[frame.asset != "wti"]
    changed = tmp_path / "bad-input.parquet"
    frame.to_parquet(changed, index=False)
    with pytest.raises(ValueError):
        audit_training_data(changed, rejected_path)


def test_repository_notebook_has_no_package_or_local_data_dependency():
    nb = json.loads((ROOT / "notebooks/train_dlinear_kaggle.ipynb").read_text(encoding="utf-8"))
    sources = []
    for cell in nb["cells"]:
        source = "".join(cell["source"])
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
            compile(source, "<notebook>", "exec")
            sources.append(source)
    code = "\n".join(sources)
    assert "cpaws-dlinear-kaggle.zip" not in code
    assert "source_manifest.json" not in code
    assert "C:/" not in code and "C:\\" not in code
    assert "src.forecast.train_dlinear" in code
    assert "PRICES_PATH" in code and "REJECTED_PATH" in code


def test_external_inputs_smoke_train_export_and_parity(synthetic_inputs, tmp_path):
    torch.set_num_threads(1)
    _, _, datasets = audit_training_data(*synthetic_inputs)
    data = datasets["gold"]
    small = replace(
        data,
        X=data.X[:32],
        y=data.y[:32],
        base_dates=data.base_dates[:32],
        target_dates=data.target_dates[:32],
        audit={**data.audit, "test_smoke": True},
    )
    model, scaler, _ = train_model(small, epochs=1, batch_size=16, device="cpu")
    directory, manifest = export_artifact(
        model, scaler, small, tmp_path, asset="gold", model_version="synthetic-smoke"
    )
    assert manifest["commit"] is None and not manifest["integration_eligible"]
    assert verify_trained_artifact(directory, small) <= 1e-6


def test_train_cli_help_has_real_options():
    output = subprocess.run(
        [sys.executable, "-m", "src.forecast.train_dlinear", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    for option in ("--asset", "--prices", "--rejected", "--source-commit", "--model-version"):
        assert option in output

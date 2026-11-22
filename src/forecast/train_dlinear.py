"""One local/Kaggle training entrypoint; fixed epochs, no validation-label updates."""

import argparse
import hashlib
import json
import os
import platform
import random
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset

from src.forecast.dlinear import DLinear, pinball_training_loss
from src.forecast.dlinear_data import ASSET_NAMES, InputScaler, prepare_training_data
from src.forecast.dlinear_numpy import LEVELS, DLinearNumpy


def train_model(
    data, *, epochs=20, batch_size=64, learning_rate=0.001, optimizer="adam", seed=7, device="auto"
):
    """Experimental hyperparameter defaults, not approved model-selection choices."""
    if epochs < 1 or batch_size < 1 or not np.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("epochs/batch_size/learning_rate must be positive")
    if optimizer not in ("adam", "sgd") or device not in ("auto", "cpu", "cuda"):
        raise ValueError("unsupported optimizer/device")
    if not len(data.X):
        raise ValueError("no complete-case training samples")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    scaler = InputScaler.fit(data.X)
    x = scaler.transform(data.X)
    model = DLinear()
    model.initialize_from_targets(data.y)
    model.to(device)
    opt_cls = torch.optim.Adam if optimizer == "adam" else torch.optim.SGD
    opt = opt_cls(model.parameters(), lr=learning_rate)
    dataset = TensorDataset(torch.from_numpy(x), torch.as_tensor(data.y, dtype=torch.float32))
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
        num_workers=0,
    )
    history = []
    for epoch in range(epochs):
        total = 0.0
        model.train()
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = pinball_training_loss(model(xb), yb)
            if not torch.isfinite(loss):
                raise ValueError("non-finite training loss")
            loss.backward()
            if any(p.grad is None or not torch.isfinite(p.grad).all() for p in model.parameters()):
                raise ValueError("missing or non-finite gradient")
            opt.step()
            if any(not torch.isfinite(p).all() for p in model.parameters()):
                raise ValueError("non-finite model weights")
            total += float(loss.detach()) * len(xb)
        history.append(total / len(dataset))
        print(json.dumps({"epoch": epoch + 1, "training_pinball_loss": history[-1]}))
    return model.cpu().eval(), scaler, history


def export_artifact(
    model,
    scaler,
    data,
    output_dir,
    *,
    asset,
    model_version,
    source_commit=None,
    training_settings=None,
    data_hashes=None,
):
    if asset not in ASSET_NAMES or data.audit["asset"] != asset:
        raise ValueError("artifact asset must match training data")
    if (
        not model_version
        or Path(model_version).name != model_version
        or model_version in (".", "..")
    ):
        raise ValueError("model_version must be a single safe directory name")
    if source_commit is not None:
        source_commit = source_commit.strip() or None
    config = {
        "architecture": "dlinear-median-softplus-v1",
        "window": 60,
        "kernel": 25,
        "padding": "replicate",
        "horizons": list(range(1, 8)),
        "quantile_levels": LEVELS,
        "feature_names": ["log_return_1_end"],
        "precision": "float32",
        "train_start": "2014-01-01",
        "train_end": "2018-12-31",
        "training_settings": training_settings or {},
        "data_hashes": data_hashes or {},
    }
    weights = {
        name.replace(".", "_"): value.detach().cpu().numpy().copy()
        for name, value in model.state_dict().items()
    }
    runtime = DLinearNumpy(weights, scaler.mean, scaler.std)
    sample = data.X[: min(64, len(data.X))]
    with torch.no_grad():
        expected = model(torch.from_numpy(scaler.transform(sample))).numpy()
    actual = runtime.predict(sample)
    error = float(np.max(np.abs(actual - expected)))
    if not np.allclose(actual, expected, atol=1e-6, rtol=0):
        raise ValueError(f"NumPy/Torch parity failed: {error}")
    # Refuse even an existing version directory; never overwrite a published fit.
    directory = Path(output_dir) / asset / model_version
    directory.mkdir(parents=True, exist_ok=False)
    np.savez(directory / "weights.npz", **weights)
    (directory / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (directory / "scaler.json").write_text(
        json.dumps({"mean": scaler.mean.tolist(), "std": scaler.std.tolist()}), encoding="utf-8"
    )
    manifest = {
        "fit_id": str(uuid.uuid4()),
        "model_version": model_version,
        "asset": asset,
        "train_end": "2018-12-31",
        "max_training_target_date": str(data.target_dates.max())[:10],
        "trained_at": datetime.now(UTC).isoformat(),
        "config_hash": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "commit": source_commit,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "torch": torch.__version__,
        },
        "integration_eligible": bool(source_commit),
        "missing_metadata": [] if source_commit else ["commit"],
        "training_audit": data.audit,
        "numpy_parity_max_abs_error": error,
        "file_hashes": {
            f: hashlib.sha256((directory / f).read_bytes()).hexdigest()
            for f in ("weights.npz", "scaler.json")
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    DLinearNumpy.load(directory)
    return directory, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", choices=(*ASSET_NAMES, "all"), required=True)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--rejected", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--optimizer", choices=("adam", "sgd"), default="adam")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--model-version", default=None)
    parser.add_argument("--source-commit", default=None)
    args = parser.parse_args(argv)
    if args.threads < 1:
        parser.error("threads must be positive")
    torch.set_num_threads(args.threads)
    prices, rejected = pd.read_parquet(args.prices), pd.read_parquet(args.rejected)
    hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in (("prices", args.prices), ("rejected", args.rejected))
    }
    version = args.model_version or ("experiment-" + uuid.uuid4().hex[:12])
    settings = {
        k: getattr(args, k)
        for k in ("epochs", "batch_size", "learning_rate", "optimizer", "seed", "device", "threads")
    }
    for asset in ASSET_NAMES if args.asset == "all" else [args.asset]:
        data = prepare_training_data(prices, rejected, asset)
        print(json.dumps(data.audit))
        model, scaler, history = train_model(
            data, **{k: v for k, v in settings.items() if k != "threads"}
        )
        directory, manifest = export_artifact(
            model,
            scaler,
            data,
            args.output_dir,
            asset=asset,
            model_version=version,
            source_commit=args.source_commit,
            training_settings={**settings, "epoch_losses": history},
            data_hashes=hashes,
        )
        print(
            json.dumps(
                {
                    "artifact": str(directory),
                    "fit_id": manifest["fit_id"],
                    "integration_eligible": manifest["integration_eligible"],
                    "parity_max_abs_error": manifest["numpy_parity_max_abs_error"],
                }
            )
        )


if __name__ == "__main__":
    main()

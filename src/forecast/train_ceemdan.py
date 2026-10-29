"""K3: train + đánh giá CEEMDAN-DLinear trên validation 2019 (docs/experiments/k3-ceemdan-plan.md).

Chạy từ gốc repo, bằng venv có numpy 2.4.6 + EMD-signal 1.10.0 (nằm trong cfg_hash của cache):
  python -m src.forecast.train_ceemdan [--lake-dir ../CPAWS-commodity-forecasting/data/lake]
      [--output-dir data] [--run-id k3-val2019] [--threads 1]

- Lake chỉ đọc: bản clean configs/k3_grid.CLEAN_DT cắt tại 2019-12-31 ngay khi đọc (filter của
  pyarrow); cache CEEMDAN cfg_hash 4c3229533ae3 đọc qua src/features/ceemdan_cache.py, không dựng lại.
- Lưới 8 cấu hình × 4 tài sản × 3 seed, 20 epoch cố định trên 2014–2018 (không early stopping);
  dự báo validation 2019; trung bình phân vị 3 seed rồi normalize_quantiles() đúng một lần.
- Đánh giá bằng chính src/eval/walk_forward.py (_make_detail, _summarize: chỉ số metrics.py, CI
  block bootstrap 20 × 1000 trên lịch hợp nhất NYSE/CME, DM theo DM_GAP_POLICY), trên tập ngày gốc
  chung của 8 cấu hình từng tài sản; baseline-q252 và DLinear MVP chấm trên cùng tập.
- Chỉ ghi local: artifact <output>/models/<asset>/<model_version>/ (integration_eligible = false),
  kết quả <output>/eval/k3/<run_id>/. Không ghi S3, không đọc 2020 → nay, không chạy tập test.

Điều kiện dừng (StopRun, thoát mã 2): đọc được dữ liệu sau 2019, số mẫu khác báo cáo probe, loss
NaN/inf, parity torch–NumPy lệch, một cấu hình chạy quá 10 phút.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset

from configs import ceemdan_cache as CC
from configs import k3_grid as G
from src.data import calendars, storage
from src.data.config import ASSETS
from src.eval import walk_forward as wf
from src.features import ceemdan_cache as cc
from src.features.build import build_feature_frame, make_windows
from src.features.ceemdan_features import (
    ColumnScaler,
    baseline_quantiles,
    ceemdan_samples,
    column_names,
    load_cache,
)
from src.forecast.ceemdan_dlinear import DTYPE, CeemdanDLinear
from src.forecast.ceemdan_dlinear_numpy import ARCHITECTURE, LEVELS, CeemdanDLinearNumpy
from src.forecast.decomposition import PYEMD_VERSION, CeemdanConfig
from src.forecast.dlinear import pinball_training_loss
from src.forecast.dlinear_numpy import DLinearNumpy
from src.forecast.returns import normalize_quantiles, prob_up

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAKE = ROOT.parent / "CPAWS-commodity-forecasting" / "data" / "lake"
HORIZONS = tuple(G.HORIZONS)
QCOLS = wf.QCOLS
PARITY_ATOL = 1e-6
CODE_FILES = (
    "configs/ceemdan_cache.py",
    "configs/k3_grid.py",
    "src/eval/metrics.py",
    "src/eval/walk_forward.py",
    "src/features/build.py",
    "src/features/ceemdan_cache.py",
    "src/features/ceemdan_features.py",
    "src/forecast/baselines.py",
    "src/forecast/ceemdan_dlinear.py",
    "src/forecast/ceemdan_dlinear_numpy.py",
    "src/forecast/decomposition.py",
    "src/forecast/dlinear.py",
    "src/forecast/returns.py",
    "src/forecast/train_ceemdan.py",
)


class StopRun(RuntimeError):
    """Điều kiện dừng của K3: dừng và báo, không tự xử lý."""


def config_id(window: int, max_imf: int, seq_len: int) -> str:
    return f"w{window}-k{max_imf}-l{seq_len}"


# ---------- dữ liệu (chỉ đọc) ----------


def read_clean(lake: Path, dt: str, cutoff: str = G.CUTOFF) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bản clean cắt tại cutoff (mặc định CUTOFF của K3) ngay khi đọc; chỉ giữ 4 tài sản."""
    directory = Path(lake) / "clean" / "prices" / f"dt={dt}"
    cut = pd.Timestamp(cutoff)
    flt = [("date", "<=", cut)]
    prices = pd.read_parquet(directory / "prices.parquet", filters=flt)
    rejected = pd.read_parquet(directory / "rejected.parquet", filters=flt)
    for name, df in (("prices", prices), ("rejected", rejected)):
        if len(df) and pd.Timestamp(df["date"].max()) > cut:
            raise StopRun(f"{name}: read data after {cutoff}")
    prices = prices[prices["asset"].isin(G.ASSETS)].reset_index(drop=True)
    rejected = rejected[rejected["asset"].isin(G.ASSETS)].reset_index(drop=True)
    return prices, rejected


def frame_lineage(frame: pd.DataFrame) -> dict:
    """Hash của khung ≤ CUTOFF đã đọc (không hash cả file: file chứa dữ liệu sau 2019)."""
    canonical = frame.sort_values(["asset", "date"]).sort_index(axis=1)
    digest = hashlib.sha256(
        pd.util.hash_pandas_object(canonical, index=False).to_numpy().tobytes()
    ).hexdigest()
    return {"n_rows": len(frame), "max_date": str(frame["date"].max())[:10], "sha256": digest}


def cache_config(window: int) -> CeemdanConfig:
    cfg = CeemdanConfig(
        window=window,
        trials=CC.TRIALS,
        epsilon=CC.EPSILON,
        seed=CC.SEED,
        keep_last=CC.KEEP_LAST,
    )
    if cfg.hash() != G.EXPECTED_CFG_HASH:
        raise StopRun(
            f"cfg_hash {cfg.hash()} != {G.EXPECTED_CFG_HASH} (numpy {np.__version__}, "
            f"EMD-signal {PYEMD_VERSION}); use the pinned venv, never rebuild the cache"
        )
    return cfg


def read_caches(st) -> dict:
    caches = {}
    for asset in G.ASSETS:
        for window in sorted({w for w, _, _ in G.GRID}):
            cfg = cache_config(window)
            meta = json.loads(st.read_bytes(f"{cc.prefix(asset, cfg)}/config.json"))
            if meta.get("cfg_hash") != G.EXPECTED_CFG_HASH:
                raise StopRun(f"{asset} w={window}: config.json cfg_hash mismatch")
            caches[(asset, window)] = load_cache(st, asset, cfg, G.CACHE_START, G.CUTOFF)
    return caches


def source_commit() -> tuple[str | None, bool | None]:
    """Commit hash của worktree (chỉ đọc: git log/status) và cờ có thay đổi chưa commit."""

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        return git("log", "-1", "--format=%H"), bool(git("status", "--porcelain"))
    except (OSError, subprocess.CalledProcessError):
        return None, None


def code_sha256() -> dict:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES}


def versions() -> dict:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "torch": torch.__version__,
        "EMD-signal": PYEMD_VERSION,
    }


# ---------- train ----------


def train_member(
    x,
    baseline,
    y,
    *,
    seed: int,
    epochs: int = G.EPOCHS,
    batch_size: int = G.BATCH_SIZE,
    learning_rate: float = G.LEARNING_RATE,
    weight_decay: float = G.WEIGHT_DECAY,
):
    """Một seed: Adam, số epoch cố định, không nhìn validation. x đã qua ColumnScaler."""
    if not len(x):
        raise ValueError("no training samples")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    model = CeemdanDLinear(x.shape[1], x.shape[2])
    opt = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    tensors = [torch.as_tensor(np.asarray(a), dtype=DTYPE) for a in (x, baseline, y)]
    loader = DataLoader(
        TensorDataset(*tensors),
        batch_size=batch_size,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
        num_workers=0,
    )
    with torch.no_grad():
        initial = float(pinball_training_loss(model(tensors[0], tensors[1]), tensors[2]))
    history = []
    for epoch in range(epochs):
        model.train()
        total = 0.0
        for xb, bb, yb in loader:
            opt.zero_grad()
            loss = pinball_training_loss(model(xb, bb), yb)
            if not torch.isfinite(loss):
                raise StopRun(
                    f"seed {seed} epoch {epoch + 1}: non-finite loss {float(loss.detach())}"
                )
            loss.backward()
            if any(p.grad is None or not torch.isfinite(p.grad).all() for p in model.parameters()):
                raise StopRun(f"seed {seed} epoch {epoch + 1}: missing or non-finite gradient")
            opt.step()
            total += float(loss.detach()) * len(xb)
        history.append(total / len(x))
    return model.eval(), {"seed": seed, "initial_loss": initial, "epoch_losses": history}


def torch_predict(model, scaler: ColumnScaler, features, baseline) -> np.ndarray:
    with torch.no_grad():
        x = torch.as_tensor(scaler.transform(features), dtype=DTYPE)
        return model(x, torch.as_tensor(baseline, dtype=DTYPE)).numpy()


def export_artifact(
    members,
    histories,
    scaler: ColumnScaler,
    train,
    check,
    *,
    asset: str,
    window: int,
    max_imf: int,
    seq_len: int,
    model_root: Path,
    provenance: dict,
    audit: dict,
):
    """Ghi artifact local (weights.npz, config.json, scaler.json, manifest.json); kiểm parity
    torch–NumPy trên mẫu `check` (đặc trưng chưa scale, mốc). Không ghi đè thư mục có sẵn."""
    config = {
        "architecture": ARCHITECTURE,
        "ceemdan_window": window,
        "max_imf": max_imf,
        "seq_len": seq_len,
        "ceemdan_cfg_hash": G.EXPECTED_CFG_HASH,
        "ceemdan": {
            "trials": CC.TRIALS,
            "epsilon": CC.EPSILON,
            "seed": CC.SEED,
            "keep_last": CC.KEEP_LAST,
        },
        "feature_names": column_names(max_imf),
        "feature_normalization": "fixed_imf_matrix / P_t; residue column - 1; ColumnScaler",
        "sample_rule": "A (docs/experiments/k3-ceemdan-plan.md section 1)",
        "anchor": "baseline-q252",
        "horizons": list(HORIZONS),
        "quantile_levels": LEVELS,
        "seeds": list(G.SEEDS),
        "ensemble": "mean of seed quantiles, then normalize_quantiles once",
        "precision": "float64",
        "train_start": G.TRAIN[0],
        "train_end": G.TRAIN[1],
        "training_settings": {
            "optimizer": "adam",
            "epochs": G.EPOCHS,
            "batch_size": G.BATCH_SIZE,
            "learning_rate": G.LEARNING_RATE,
            "weight_decay": G.WEIGHT_DECAY,
            "early_stopping": None,
        },
    }
    version_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    model_version = f"k3-ceemdan-dlinear-{config_id(window, max_imf, seq_len)}-{version_hash[:8]}"
    config = {"asset": asset, "model_version": model_version, **config}
    weights = {
        f"seed{seed}_{name}": value
        for seed, model in zip(G.SEEDS, members, strict=True)
        for name, value in model.numpy_weights().items()
    }
    runtime = CeemdanDLinearNumpy([m.numpy_weights() for m in members], scaler.mean, scaler.std)
    features, base = check
    expected = np.stack([torch_predict(m, scaler, features, base) for m in members])
    actual = runtime.member_predict(features, base)
    error = float(np.max(np.abs(actual - expected)))
    if not np.allclose(actual, expected, rtol=0, atol=PARITY_ATOL):
        raise StopRun(f"{asset} {model_version}: torch/NumPy parity {error:.3g} > {PARITY_ATOL}")

    directory = Path(model_root) / asset / model_version
    directory.mkdir(parents=True, exist_ok=False)
    np.savez(directory / "weights.npz", **weights)
    (directory / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (directory / "scaler.json").write_text(json.dumps(scaler.to_dict()), encoding="utf-8")
    manifest = {
        "fit_id": str(uuid.uuid4()),
        "model_version": model_version,
        "asset": asset,
        "train_end": G.TRAIN[1],
        "max_training_target_date": str(train.target_dates[train.valid].max())[:10],
        "trained_at": datetime.now(UTC).isoformat(),
        "config_hash": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "ceemdan_cfg_hash": G.EXPECTED_CFG_HASH,
        **provenance,
        "integration_eligible": False,
        "integration_note": "K3 experiment artifact; local only, not for predict (ADR-0008).",
        "training_audit": audit,
        "seeds": histories,
        "numpy_parity_max_abs_error": error,
        "file_hashes": {
            f: hashlib.sha256((directory / f).read_bytes()).hexdigest()
            for f in ("weights.npz", "scaler.json")
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    loaded = CeemdanDLinearNumpy.load(directory)
    if not np.array_equal(loaded.member_predict(features, base), actual):
        raise StopRun(f"{asset} {model_version}: reloaded artifact differs")
    return directory, manifest


def _counts(samples) -> dict:
    d = samples.diag
    kept = d[d["valid"]]
    conditions = (
        "has_cache_window",
        "input_window_ok",
        "publication_ok",
        "target_ok",
        "boundary_ok",
        "baseline_ok",
    )
    return {
        "n_sessions": len(d),
        "n_valid": int(d["valid"].sum()),
        "excluded_by_condition": {c: int((~d[c]).sum()) for c in conditions},
        "kept_with_missing_sessions_decompose": int(
            (kept["n_missing_sessions_decompose"] > 0).sum()
        ),
        "kept_max_missing_sessions_decompose": int(kept["n_missing_sessions_decompose"].max()),
        "kept_n_imf_below_k": int(kept["n_imf_below_k"].sum()),
    }


def run_config(window, max_imf, seq_len, ctx) -> dict:
    """Một cấu hình: 4 tài sản × 3 seed. Trả số mẫu, dự báo validation và thông tin artifact."""
    t0 = time.perf_counter()
    cid = config_id(window, max_imf, seq_len)
    out = {"config_id": cid, "window": window, "max_imf": max_imf, "seq_len": seq_len}
    out.update(assets={}, forecasts={}, rows=[])
    for asset in G.ASSETS:
        cache = ctx["caches"][(asset, window)]
        invalid = ctx["invalid"][asset]
        kwargs = {"max_imf": max_imf, "seq_len": seq_len, "invalid_dates": invalid}
        train = ceemdan_samples(
            ctx["prices"],
            asset,
            cache,
            ctx["sessions"][asset]["train"],
            period_end=G.TRAIN[1],
            **kwargs,
        )
        val = ceemdan_samples(
            ctx["prices"],
            asset,
            cache,
            ctx["sessions"][asset]["val"],
            period_end=G.VALID[1],
            **kwargs,
        )
        n = (int(train.valid.sum()), int(val.valid.sum()))
        expected = G.EXPECTED_N[(asset, window, seq_len)]
        if n != expected:
            raise StopRun(f"{cid} {asset}: samples train/val {n} != probe {expected}")
        tr, va = np.flatnonzero(train.valid), np.flatnonzero(val.valid)
        scaler = ColumnScaler.fit(train.X[tr])  # đúng mảng train hợp lệ
        x_train = scaler.transform(train.X[tr])
        members, histories = [], []
        for seed in G.SEEDS:
            model, history = train_member(x_train, train.baseline[tr], train.y[tr], seed=seed)
            members.append(model)
            histories.append(history)
        audit = {"train": _counts(train), "validation": _counts(val)}
        check = (
            np.concatenate([train.X[tr[:64]], val.X[va]]),
            np.concatenate([train.baseline[tr[:64]], val.baseline[va]]),
        )
        directory, manifest = export_artifact(
            members,
            histories,
            scaler,
            train,
            check,
            asset=asset,
            window=window,
            max_imf=max_imf,
            seq_len=seq_len,
            model_root=ctx["model_root"],
            provenance=ctx["provenance"],
            audit=audit,
        )
        runtime = CeemdanDLinearNumpy.load(directory)
        per_seed = runtime.member_predict(val.X[va], val.baseline[va])
        q_mean, crossed = normalize_quantiles(per_seed.mean(axis=0))  # đúng một lần
        out["model_version"] = manifest["model_version"]
        out["forecasts"][asset] = (val.base_dates[va], q_mean, crossed)
        out["assets"][asset] = {
            "n_train": n[0],
            "n_val": n[1],
            "model_version": manifest["model_version"],
            "fit_id": manifest["fit_id"],
            "artifact": str(
                directory.relative_to(ROOT) if directory.is_relative_to(ROOT) else directory
            ),
            "commit": manifest["commit"],
            "commit_dirty": manifest["commit_dirty"],
            "ceemdan_cfg_hash": G.EXPECTED_CFG_HASH,
            "seeds": histories,
            "parity_max_abs_error": manifest["numpy_parity_max_abs_error"],
            "audit": audit,
            "scaler": scaler.to_dict(),
        }
        for member, q in [*zip(map(str, G.SEEDS), per_seed, strict=True), ("mean", q_mean)]:
            for i, k in enumerate(va):
                for j, h in enumerate(HORIZONS):
                    out["rows"].append(
                        {
                            "config_id": cid,
                            "model_version": manifest["model_version"],
                            "asset": asset,
                            "member": member,
                            "base_date": val.base_dates[k],
                            "h": h,
                            **dict(zip(QCOLS, q[i, j].tolist(), strict=True)),
                            "prob_up": prob_up(q[i, j]) if member == "mean" else None,
                            "crossed_raw": bool(crossed[i, j]) if member == "mean" else None,
                            "y_true": float(val.y[k, j]),
                            **{
                                "baseline_" + c: float(v)
                                for c, v in zip(QCOLS, val.baseline[k, j], strict=True)
                            },
                        }
                    )
    out["seconds_train"] = time.perf_counter() - t0
    if out["seconds_train"] > G.MAX_CONFIG_SECONDS:
        raise StopRun(f"{cid}: {out['seconds_train']:.0f} s > {G.MAX_CONFIG_SECONDS} s")
    return out


# ---------- dự báo so sánh trên tập chung ----------


def baseline_forecasts(prices, invalid, origins) -> dict:
    """baseline-q252 như model: phân vị mốc tại t (cùng hàm neo mô hình)."""
    out = {}
    for asset, base in origins.items():
        q, ok = baseline_quantiles(prices, asset, base, invalid[asset])
        if not ok.all():
            raise StopRun(f"{asset}: baseline invalid on common origins")
        normalized, crossed = normalize_quantiles(q)
        out[asset] = (base, normalized, crossed)
    return out


def mvp_forecasts(prices, invalid, origins, model_root: Path) -> tuple[dict, dict]:
    """DLinear MVP (artifact chỉ đọc) trên các ngày gốc chung có cửa sổ 60 hợp lệ."""
    out, missing = {}, {}
    for asset, base in origins.items():
        model = DLinearNumpy.load(model_root / asset / G.MVP_MODEL_VERSION)
        frame = build_feature_frame(prices, asset, invalid_dates=invalid[asset])
        batch = make_windows(frame, base, window=60)
        asof = np.array(
            [
                wf.publication_time(asset, str(d.date())).tz_localize(None).to_datetime64()
                for d in base
            ]
        )
        pub = batch.max_input_published_at
        ok = batch.valid & ~np.isnat(pub) & (pub <= asof)
        missing[asset] = int((~ok).sum())
        raw = model.predict(batch.X[ok])
        normalized, crossed = normalize_quantiles(raw)
        out[asset] = (base[ok], normalized, crossed)
    return out, missing


# ---------- đánh giá (src/eval/walk_forward.py) ----------


def evaluation_config(model_version: str) -> wf.EvaluationConfig:
    return wf.EvaluationConfig(
        run_id=f"k3-{model_version}",
        forecast_run_id=f"k3-{model_version}-val2019",
        model_version=model_version,
        seed=G.BOOTSTRAP_SEED,
        evaluation_as_of_time=G.EVALUATION_AS_OF,
    )


def evaluate(
    model_version: str, forecasts: dict, p, r, cfg: wf.EvaluationConfig | None = None
) -> dict:
    """Forecasts {asset: (base_dates, q đã chuẩn hóa [n,7,7], crossed [n,7])} → Detail/Accuracy/DM
    bằng _make_detail + _summarize của walk_forward (không viết lại công thức nào). cfg mặc định
    là validation 2019 của K3; K4 truyền cấu hình cross_validation."""
    t0 = time.perf_counter()
    cfg = evaluation_config(model_version) if cfg is None else cfg
    rows = []
    for asset in wf.ASSET_NAMES:
        base, q, crossed = forecasts[asset]
        for i, d in enumerate(base):
            day = str(pd.Timestamp(d).date())
            asof = wf.publication_time(asset, day).isoformat()
            for j, h in enumerate(HORIZONS):
                values = q[i, j].tolist()
                rows.append(
                    dict(
                        zip(
                            wf.FORECAST_COLUMNS,
                            [
                                cfg.forecast_run_id,
                                model_version,
                                f"{model_version}-{asset}",
                                asset,
                                day,
                                h,
                                *values,
                                prob_up(values),
                                bool(crossed[i, j]),
                                "ok",
                                None,
                                asof,
                                wf.PROVENANCE,
                                None,
                            ],
                            strict=True,
                        )
                    )
                )
    frame = pd.DataFrame(rows, columns=wf.FORECAST_COLUMNS)
    fits = {a: {"fit_id": f"{model_version}-{a}"} for a in wf.ASSET_NAMES}
    detail = wf._make_detail(frame, p, r, fits, cfg, model_version)
    accuracy, comparison, log = wf._summarize(detail, cfg, model_version)
    return {
        "detail": detail,
        "accuracy": accuracy,
        "comparison": comparison,
        "log": log,
        "seconds": time.perf_counter() - t0,
    }


def mean_skill(accuracy: pd.DataFrame) -> tuple[float, dict]:
    """Trung bình pinball_skill trên 28 nhóm (4 tài sản × 7 h, sample=all) và theo tài sản."""
    a = accuracy[(accuracy["metric"] == "pinball_skill") & (accuracy["sample"] == "all")]
    if len(a) != 28 or a["value"].isna().any():
        raise StopRun("pinball_skill must be defined for all 28 groups")
    return float(a["value"].mean()), a.groupby("asset")["value"].mean().to_dict()


def select_config(scores: dict) -> tuple[str, list[str]]:
    """Kế hoạch mục 5: cao nhất; chênh < TIE_TOLERANCE là hòa → nhỏ hơn theo window, L, K."""
    best = max(s["mean_28"] for s in scores.values())
    tied = [cid for cid, s in scores.items() if best - s["mean_28"] < G.TIE_TOLERANCE]
    key = {cid: (s["window"], s["seq_len"], s["max_imf"]) for cid, s in scores.items()}
    return min(tied, key=key.__getitem__), tied


# ---------- chạy ----------


def run(lake_dir: Path, output_dir: Path, run_id: str) -> dict:
    t_start = time.perf_counter()
    lake = Path(lake_dir)
    eval_dir = Path(output_dir) / "eval" / "k3" / run_id
    if eval_dir.exists():
        raise FileExistsError(eval_dir)
    prices, rejected = read_clean(lake, G.CLEAN_DT)
    st = storage.LocalStorage(str(lake))
    t = time.perf_counter()
    caches = read_caches(st)
    seconds_cache = time.perf_counter() - t
    commit, dirty = source_commit()
    invalid = {
        a: pd.to_datetime(rejected.loc[rejected["asset"] == a, "date"]).tolist() for a in G.ASSETS
    }
    sessions = {
        a: {
            "train": calendars.sessions(ASSETS[a].calendar, *G.TRAIN),
            "val": calendars.sessions(ASSETS[a].calendar, *G.VALID),
        }
        for a in G.ASSETS
    }
    lineage = {
        "clean_dt": G.CLEAN_DT,
        "cutoff": G.CUTOFF,
        "prices_view": frame_lineage(prices),
        "rejected_view": frame_lineage(rejected) if len(rejected) else {"n_rows": 0},
    }
    provenance = {
        "commit": commit,
        "commit_dirty": dirty,
        "versions": versions(),
        "code_sha256": code_sha256(),
        "data_lineage": lineage,
    }
    ctx = {
        "prices": prices,
        "caches": caches,
        "invalid": invalid,
        "sessions": sessions,
        "model_root": Path(output_dir) / "models",
        "provenance": provenance,
    }

    configs = []
    for window, max_imf, seq_len in G.GRID:
        result = run_config(window, max_imf, seq_len, ctx)
        print(
            json.dumps(
                {
                    "config": result["config_id"],
                    "seconds_train": round(result["seconds_train"], 1),
                    "n": {a: (v["n_train"], v["n_val"]) for a, v in result["assets"].items()},
                }
            ),
            flush=True,
        )
        configs.append(result)

    # Tập ngày gốc chung của 8 cấu hình, từng tài sản
    common = {}
    for asset in G.ASSETS:
        sets = [pd.DatetimeIndex(c["forecasts"][asset][0]) for c in configs]
        inter = sets[0]
        for s in sets[1:]:
            inter = inter.intersection(s)
        common[asset] = inter.sort_values()

    def restrict(forecasts):
        out = {}
        for asset, (base, q, crossed) in forecasts.items():
            keep = pd.DatetimeIndex(base).isin(common[asset])
            out[asset] = (pd.DatetimeIndex(base)[keep], q[keep], crossed[keep])
        return out

    cfg0 = evaluation_config("inputs")
    p, r = wf._inputs(prices, rejected, cfg0)
    evaluations, scores = {}, {}
    for c in configs:
        e = evaluate(c["model_version"], restrict(c["forecasts"]), p, r)
        if e["seconds"] > G.MAX_CONFIG_SECONDS:
            raise StopRun(f"{c['config_id']}: evaluation {e['seconds']:.0f} s")
        evaluations[c["config_id"]] = e
        m28, by_asset = mean_skill(e["accuracy"])
        scores[c["config_id"]] = {
            "model_version": c["model_version"],
            "window": c["window"],
            "max_imf": c["max_imf"],
            "seq_len": c["seq_len"],
            "mean_28": m28,
            "by_asset": by_asset,
        }
        print(json.dumps({"eval": c["config_id"], "mean_28": m28, "s": round(e["seconds"], 1)}))
    selected, tied = select_config(scores)

    base_eval = evaluate("baseline-q252", baseline_forecasts(prices, invalid, common), p, r)
    skill = base_eval["accuracy"].query("metric == 'pinball_skill'")["value"]
    if skill.abs().max() > 1e-12:
        raise StopRun("anchor baseline differs from walk_forward evaluation baseline")
    mvp, mvp_missing = mvp_forecasts(prices, invalid, common, lake / G.MVP_MODEL_SUBDIR)
    mvp_eval = evaluate(G.MVP_MODEL_VERSION, mvp, p, r)

    # Ghi kết quả (local, gitignore)
    eval_dir.mkdir(parents=True, exist_ok=False)
    pd.DataFrame([row for c in configs for row in c["rows"]]).to_parquet(
        eval_dir / "forecasts_val2019.parquet", index=False
    )
    named = {**evaluations, "baseline-q252": base_eval, "dlinear-mvp": mvp_eval}
    for kind in ("accuracy", "comparison", "detail"):
        pd.concat(
            [e[kind].assign(model=name) for name, e in named.items()], ignore_index=True
        ).to_parquet(eval_dir / f"{kind}.parquet", index=False)
    summary = {
        "run_id": run_id,
        "plan": "docs/experiments/k3-ceemdan-plan.md",
        "provenance": provenance,
        "ceemdan_cfg_hash": G.EXPECTED_CFG_HASH,
        "grid": [list(g) for g in G.GRID],
        "seeds": list(G.SEEDS),
        "common_origins": {a: len(v) for a, v in common.items()},
        "scores": scores,
        "selected": selected,
        "tied_with_best": tied,
        "mvp_missing_on_common": mvp_missing,
        "configs": [
            {k: c[k] for k in ("config_id", "model_version", "seconds_train", "assets")}
            for c in configs
        ],
        "seconds": {
            "cache_read": seconds_cache,
            "evaluation": {name: e["seconds"] for name, e in named.items()},
            "total": time.perf_counter() - t_start,
        },
        "dm_blocked_groups": {
            name: [g for g in e["log"]["dm_calendar_gaps"] if g["blocked"]]
            for name, e in named.items()
        },
        "bootstrap_plan": base_eval["log"]["bootstrap_plan"],
    }
    (eval_dir / "summary.json").write_text(
        json.dumps(wf._plain(summary), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    (eval_dir / "summary.md").write_text(render(summary, named), encoding="utf-8")
    return summary


# ---------- báo cáo Markdown (chỉ trình bày số đã tính) ----------


def md(df: pd.DataFrame, fmt: str = ".4f") -> str:
    def cell(v):
        if isinstance(v, float | np.floating):
            return "" if np.isnan(v) else format(float(v), fmt)
        return "" if v is None else str(v)

    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


METRICS = (
    "pinball_skill",
    "coverage_80",
    "width_80",
    "interval_score_80",
    "brier_skill",
    "mae_ratio_vs_naive",
    "sign_accuracy",
    "up_rate",
)


def metric_table(named: dict, models: list[str], asset: str) -> pd.DataFrame:
    rows = []
    for sample in ("all", "excl_roll") if asset in ("brent", "wti") else ("all",):
        for h in HORIZONS:
            for name in models:
                a = named[name]["accuracy"]
                a = a[(a["asset"] == asset) & (a["sample"] == sample) & (a["h"] == h)]
                a = a.set_index("metric")
                ps = a.loc["pinball_skill"]
                row = {"sample": sample, "h": h, "model": name}
                row["pinball_skill [CI 95%]"] = (
                    f"{ps['value']:+.4f} [{ps['ci_low']:+.4f}, {ps['ci_high']:+.4f}]"
                    if pd.notna(ps["value"]) and pd.notna(ps["ci_low"])
                    else (f"{ps['value']:+.4f}" if pd.notna(ps["value"]) else "")
                )
                for metric in METRICS[1:]:
                    value = a.loc[metric, "value"]
                    row[metric] = float(value) if pd.notna(value) else np.nan
                row["n"] = int(ps["n_obs"])
                rows.append(row)
    return pd.DataFrame(rows)


def render(summary: dict, named: dict) -> str:
    sel = summary["selected"]
    out = [f"# K3 CEEMDAN-DLinear: kết quả validation 2019 ({summary['run_id']})", ""]
    out.append(f"Cấu hình được chọn: **{sel}** ({summary['scores'][sel]['model_version']}).")
    out.append(f"Hòa với cao nhất (< {G.TIE_TOLERANCE}): {', '.join(summary['tied_with_best'])}.")
    out.append("")
    out.append("## Số mẫu (quy tắc A) và tập ngày gốc chung")
    rows = []
    for c in summary["configs"]:
        for asset, v in c["assets"].items():
            rows.append(
                {
                    "config": c["config_id"],
                    "asset": asset,
                    "train": v["n_train"],
                    "val": v["n_val"],
                    "train có phiên thiếu (decompose)": v["audit"]["train"][
                        "kept_with_missing_sessions_decompose"
                    ],
                    "val có phiên thiếu (decompose)": v["audit"]["validation"][
                        "kept_with_missing_sessions_decompose"
                    ],
                    "train n_imf < K": v["audit"]["train"]["kept_n_imf_below_k"],
                    "parity": f"{v['parity_max_abs_error']:.1e}",
                    "giây (cấu hình)": round(c["seconds_train"], 1),
                }
            )
    out += [md(pd.DataFrame(rows)), ""]
    out.append(
        "Tập chung (val 2019): "
        + ", ".join(f"{a} {n}" for a, n in summary["common_origins"].items())
    )
    out.append(f"DLinear MVP thiếu trên tập chung: {summary['mvp_missing_on_common']}")
    out.append("")
    out.append("## 8 cấu hình: trung bình pinball_skill (sample=all, 7 h) trên tập chung")
    rows = [
        {
            "config": cid,
            **{a: s["by_asset"][a] for a in G.ASSETS},
            "trung bình 28 nhóm": s["mean_28"],
        }
        for cid, s in summary["scores"].items()
    ]
    out += [md(pd.DataFrame(rows)), ""]
    models = [sel, "baseline-q252", "dlinear-mvp"]
    out.append(f"## Cấu hình chọn {sel} so với baseline-q252 và DLinear MVP")
    out.append("Naive (return = 0) là mẫu số của mae_ratio_vs_naive (= 1) và không có phân vị.")
    for asset in G.ASSETS:
        out += ["", f"### {asset}", "", md(metric_table(named, models, asset))]
    out.append("")
    out.append("## Cận dưới CI 95% của pinball_skill > 0 (cấu hình chọn)")
    a = named[sel]["accuracy"].query("metric == 'pinball_skill'")
    rows = []
    for (asset, sample), g in a.groupby(["asset", "sample"], sort=False):
        rows.append(
            {
                "asset": asset,
                "sample": sample,
                "số h có ci_low > 0": int((g["ci_low"] > 0).sum()),
                "h": ",".join(str(h) for h in g.loc[g["ci_low"] > 0, "h"]) or "-",
                "max ci_low": float(g["ci_low"].max()),
            }
        )
    out += [md(pd.DataFrame(rows)), ""]
    out.append("## DM (mô hình vs baseline-252, walk_forward DM_GAP_POLICY)")
    c = named[sel]["comparison"]
    c = c[
        ["asset", "sample", "h", "dm_stat", "p_value", "p_value_holm", "status", "undefined_reason"]
    ]
    out += [md(c), ""]
    out.append("## Thời gian (giây)")
    secs = summary["seconds"]
    out.append(f"Đọc cache {secs['cache_read']:.1f}; tổng {secs['total']:.1f}.")
    out += [
        md(
            pd.DataFrame([{"model": k, "giây đánh giá": v} for k, v in secs["evaluation"].items()]),
            ".1f",
        )
    ]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lake-dir", type=Path, default=DEFAULT_LAKE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--run-id", default="k3-val2019")
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args(argv)
    if args.threads < 1:
        parser.error("threads must be positive")
    torch.set_num_threads(args.threads)
    try:
        summary = run(args.lake_dir, args.output_dir, args.run_id)
    except StopRun as exc:
        print(f"DỪNG: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"selected": summary["selected"], "seconds": summary["seconds"]["total"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

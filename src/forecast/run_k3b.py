"""K3b: co giãn theo biến động trên validation 2019 (docs/experiments/k3b-volatility-plan.md).

Chạy từ gốc repo, bằng venv có numpy 2.4.6 + EMD-signal 1.10.0 (nằm trong cfg_hash của cache):
  python -m src.forecast.run_k3b [--lake-dir ../CPAWS-commodity-forecasting/data/lake]
      [--output-dir data] [--run-id k3b-val2019] [--k3-dir ../k3-rerun/eval/k3/k3-val2019-clean]
      [--threads 1]

- Lake chỉ đọc, như K3: bản clean configs/k3b.CLEAN_DT cắt tại 2019-12-31 ngay khi đọc; cache
  CEEMDAN cfg_hash 4c3229533ae3 (window 252) đọc qua src/features/ceemdan_cache.py, không dựng lại.
- 3 ứng viên chốt (kế hoạch mục 3): S1a (λ 0,94), S1b (λ 0,97) không train; S2 train trên
  2014–2018, 3 seed × 20 epoch cố định, trung bình phân vị rồi normalize_quantiles() đúng một lần.
- Đánh giá bằng chính hàm của K3 (train_ceemdan.evaluate → walk_forward._make_detail/_summarize)
  trên tập chung = giao 3 ứng viên (kế hoạch mục 6.2), và thêm trên tập chung K3; so với
  baseline-q252 và K3 w252-k3-l30 (forecasts của lần chạy k3-val2019-clean, chỉ đọc). CI của
  pinball_skill trung bình 7 h dùng chung kế hoạch bootstrap của walk_forward (mục 4, 6.3).
- Chỉ ghi local: artifact S2 <output>/models/<asset>/<model_version>/ (integration_eligible = false),
  kết quả <output>/eval/k3b/<run_id>/. Không ghi S3, không đọc 2020 → nay, không chạy tập test.

Điều kiện dừng (StopRun, thoát mã 2): đọc được dữ liệu sau 2019, số mẫu S2 khác K3, loss NaN/inf,
parity torch–NumPy lệch, tập chung khác dự kiến hoặc không chứa trọn tập K3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
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
from configs import k3b as C
from src.data import calendars, storage
from src.data.config import ASSETS
from src.eval import metrics as M
from src.eval import walk_forward as wf
from src.features import ceemdan_cache as cc
from src.features.ceemdan_features import ColumnScaler, load_cache
from src.features.imf_energy import feature_names, s2_samples
from src.forecast import train_ceemdan as T
from src.forecast.ceemdan_dlinear import DTYPE
from src.forecast.dlinear import pinball_training_loss
from src.forecast.energy_width import EnergyWidth
from src.forecast.energy_width_numpy import ARCHITECTURE, EnergyWidthNumpy
from src.forecast.returns import QUANTILE_LEVELS, normalize_quantiles
from src.forecast.vol_scaled import s1_quantiles

ROOT = T.ROOT
DEFAULT_LAKE = T.DEFAULT_LAKE
DEFAULT_K3_DIR = ROOT.parent / "k3-rerun" / "eval" / "k3" / C.K3_RUN_ID
HORIZONS = tuple(C.HORIZONS)
PARITY_ATOL = T.PARITY_ATOL
StopRun = T.StopRun  # read_clean/cache_config của K3 dừng bằng cùng lớp
K3_NAME = f"k3-{C.K3_CONFIG_ID}"
BASELINE = "baseline-q252"
CODE_FILES = (
    "configs/k3b.py",
    "configs/k3_grid.py",
    "src/eval/metrics.py",
    "src/eval/walk_forward.py",
    "src/features/ceemdan_cache.py",
    "src/features/ceemdan_features.py",
    "src/features/imf_energy.py",
    "src/forecast/baselines.py",
    "src/forecast/ceemdan_dlinear.py",
    "src/forecast/ceemdan_dlinear_numpy.py",
    "src/forecast/energy_width.py",
    "src/forecast/energy_width_numpy.py",
    "src/forecast/returns.py",
    "src/forecast/run_k3b.py",
    "src/forecast/train_ceemdan.py",
    "src/forecast/vol_scaled.py",
)


# ---------- S1 ----------


def k_summary(k) -> dict:
    """Phân bố k_t: min, trung vị, max, tỷ lệ bị kẹp ở mỗi ngưỡng."""
    k = np.asarray(k, dtype=float)
    lo, hi = C.K_CLIP
    return {
        "n": len(k),
        "min": float(k.min()),
        "median": float(np.median(k)),
        "max": float(k.max()),
        "share_at_low": float(np.mean(k == lo)),
        "share_at_high": float(np.mean(k == hi)),
    }


def run_s1(name: str, ctx) -> dict:
    """Phân vị S1 trên mọi ngày gốc 2019 hợp lệ; k_t trên ngày gốc train và 2019."""
    lam = C.S1_LAMBDA[name]
    out = {"forecasts": {}, "k": {}}
    for asset in C.ASSETS:
        kwargs = {"lam": lam, "invalid_dates": ctx["invalid"][asset]}
        _, ok_tr, vr_tr = s1_quantiles(
            ctx["prices"], asset, ctx["sessions"][asset]["train"], **kwargs
        )
        q, ok, vr = s1_quantiles(ctx["prices"], asset, ctx["sessions"][asset]["val"], **kwargs)
        normalized, crossed = normalize_quantiles(q[ok])  # đúng một lần
        base = vr.base_dates[ok]
        out["forecasts"][asset] = (base, normalized, crossed)
        out["k"][asset] = {"train": vr_tr.k[ok_tr], "val": pd.Series(vr.k[ok], index=base)}
    return out


# ---------- S2 ----------


def train_member(
    x,
    baseline,
    y,
    *,
    seed: int,
    epochs: int = C.EPOCHS,
    batch_size: int = C.BATCH_SIZE,
    learning_rate: float = C.LEARNING_RATE,
    weight_decay: float = C.WEIGHT_DECAY,
):
    """Một seed của S2: Adam, số epoch cố định, không nhìn validation. x đã chuẩn hóa [N, F]."""
    if not len(x):
        raise ValueError("no training samples")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    model = EnergyWidth(x.shape[1])
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


def scale_features(scaler: ColumnScaler, features) -> np.ndarray:
    """ColumnScaler của K3 nhận [N, L, C]; đặc trưng S2 là [N, F] nên coi L = 1."""
    return scaler.transform(np.asarray(features)[:, None, :])[:, 0]


def torch_predict(model, scaler: ColumnScaler, features, baseline) -> np.ndarray:
    with torch.no_grad():
        x = torch.as_tensor(scale_features(scaler, features), dtype=DTYPE)
        return model(x, torch.as_tensor(baseline, dtype=DTYPE)).numpy()


def export_artifact(
    members,
    histories,
    scaler: ColumnScaler,
    max_training_target_date: str,
    check,
    *,
    asset: str,
    model_root: Path,
    provenance: dict,
    audit: dict,
):
    """Ghi artifact S2 local (weights.npz, config.json, scaler.json, manifest.json); kiểm parity
    torch–NumPy trên `check` (đặc trưng chưa scale, mốc). Không ghi đè thư mục có sẵn."""
    config = {
        "architecture": ARCHITECTURE,
        "candidate": "S2",
        "ceemdan_window": C.S2_WINDOW,
        "max_imf": C.S2_MAX_IMF,
        "seq_len": C.S2_SEQ_LEN,
        "ceemdan_cfg_hash": C.EXPECTED_CFG_HASH,
        "ceemdan": {
            "trials": CC.TRIALS,
            "epsilon": CC.EPSILON,
            "seed": CC.SEED,
            "keep_last": CC.KEEP_LAST,
        },
        "ewma_lambda": C.S2_LAMBDA,
        "sigma_long_window": C.SIGMA_LONG_WINDOW,
        "sigma_min_obs": C.SIGMA_MIN_OBS,
        "ewma_init_obs": C.EWMA_INIT_OBS,
        "feature_names": feature_names(C.S2_MAX_IMF),
        "feature_normalization": "log mean square of fixed_imf_matrix / P_t columns "
        "(residue - 1); log sigma_short/sigma_long; ColumnScaler",
        "sample_rule": "A (docs/experiments/k3-ceemdan-plan.md section 1) + valid sigma ratio",
        "anchor": "baseline-q252, median fixed, gaps x exp(W x + b)",
        "horizons": list(HORIZONS),
        "quantile_levels": list(QUANTILE_LEVELS),
        "seeds": list(C.SEEDS),
        "ensemble": "mean of seed quantiles, then normalize_quantiles once",
        "precision": "float64",
        "train_start": C.TRAIN[0],
        "train_end": C.TRAIN[1],
        "training_settings": {
            "optimizer": "adam",
            "epochs": C.EPOCHS,
            "batch_size": C.BATCH_SIZE,
            "learning_rate": C.LEARNING_RATE,
            "weight_decay": C.WEIGHT_DECAY,
            "early_stopping": None,
        },
    }
    version_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    model_version = f"k3b-s2-energy-width-{version_hash[:8]}"
    config = {"asset": asset, "model_version": model_version, **config}
    weights = {
        f"seed{seed}_{name}": value
        for seed, model in zip(C.SEEDS, members, strict=True)
        for name, value in model.numpy_weights().items()
    }
    runtime = EnergyWidthNumpy([m.numpy_weights() for m in members], scaler.mean, scaler.std)
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
        "train_end": C.TRAIN[1],
        "max_training_target_date": max_training_target_date,
        "trained_at": datetime.now(UTC).isoformat(),
        "config_hash": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "ceemdan_cfg_hash": C.EXPECTED_CFG_HASH,
        **provenance,
        "integration_eligible": False,
        "integration_note": "K3b experiment artifact; local only, not for predict (ADR-0008).",
        "training_audit": audit,
        "seeds": histories,
        "numpy_parity_max_abs_error": error,
        "file_hashes": {
            f: hashlib.sha256((directory / f).read_bytes()).hexdigest()
            for f in ("weights.npz", "scaler.json")
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    loaded = EnergyWidthNumpy.load(directory)
    if not np.array_equal(loaded.member_predict(features, base), actual):
        raise StopRun(f"{asset} {model_version}: reloaded artifact differs")
    return directory, manifest


def run_s2(ctx) -> dict:
    """S2: 4 tài sản × 3 seed trên mẫu quy tắc A (w252, K 3, L 30) có tỷ số σ hợp lệ."""
    out = {"forecasts": {}, "assets": {}}
    for asset in C.ASSETS:
        kwargs = {
            "max_imf": C.S2_MAX_IMF,
            "seq_len": C.S2_SEQ_LEN,
            "lam": C.S2_LAMBDA,
            "invalid_dates": ctx["invalid"][asset],
        }
        cache = ctx["cache"][asset]
        sessions = ctx["sessions"][asset]
        train = s2_samples(
            ctx["prices"], asset, cache, sessions["train"], period_end=C.TRAIN[1], **kwargs
        )
        val = s2_samples(
            ctx["prices"], asset, cache, sessions["val"], period_end=C.VALID[1], **kwargs
        )
        n = (int(train.valid.sum()), int(val.valid.sum()))
        rule_a = (int(train.samples.valid.sum()), int(val.samples.valid.sum()))
        expected = C.S2_EXPECTED_N[asset]
        if n != expected or rule_a != expected:
            dropped = {
                period: {
                    "n_imf_below_k": int((s.samples.valid & s.samples.diag["n_imf_below_k"]).sum()),
                    "sigma_ratio_invalid": int((s.samples.valid & ~s.vol.valid).sum()),
                }
                for period, s in (("train", train), ("val", val))
            }
            raise StopRun(
                f"S2 {asset}: samples {n} (rule A {rule_a}) != K3 {expected}; dropped {dropped}"
            )
        tr, va = np.flatnonzero(train.valid), np.flatnonzero(val.valid)
        scaler = ColumnScaler.fit(train.features[tr][:, None, :])  # đúng mảng train hợp lệ
        x_train = scale_features(scaler, train.features[tr])
        y_train = train.samples.y[tr]
        members, histories = [], []
        for seed in C.SEEDS:
            model, history = train_member(x_train, train.samples.baseline[tr], y_train, seed=seed)
            members.append(model)
            histories.append(history)
        audit = {
            "train": T._counts(train.samples),
            "validation": T._counts(val.samples),
            "n_valid_with_sigma_ratio": {"train": n[0], "validation": n[1]},
        }
        check = (
            np.concatenate([train.features[tr[:64]], val.features[va]]),
            np.concatenate([train.samples.baseline[tr[:64]], val.samples.baseline[va]]),
        )
        directory, manifest = export_artifact(
            members,
            histories,
            scaler,
            str(train.samples.target_dates[train.valid].max())[:10],
            check,
            asset=asset,
            model_root=ctx["model_root"],
            provenance=ctx["provenance"],
            audit=audit,
        )
        runtime = EnergyWidthNumpy.load(directory)
        per_seed = runtime.member_predict(val.features[va], val.samples.baseline[va])
        q_mean, crossed = normalize_quantiles(per_seed.mean(axis=0))  # đúng một lần
        out["forecasts"][asset] = (val.base_dates[va], q_mean, crossed)
        width = np.diff(q_mean[..., [1, 5]], axis=-1)[..., 0]
        base_width = np.diff(val.samples.baseline[va][..., [1, 5]], axis=-1)[..., 0]
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
            "seeds": histories,
            "parity_max_abs_error": manifest["numpy_parity_max_abs_error"],
            "audit": audit,
            "scaler": scaler.to_dict(),
            "val_width80_ratio_to_baseline": k_summary(width / base_width),
        }
    return out


# ---------- K3 w252-k3-l30 (chỉ đọc) ----------


def k3_reference(k3_dir: Path) -> tuple[dict, dict]:
    """Forecasts K3 w252-k3-l30 (member mean, đã normalize) và tập chung K3 (giao 8 cấu hình)."""
    summary = json.loads((k3_dir / "summary.json").read_text(encoding="utf-8"))
    prov = summary["provenance"]
    if (
        prov.get("commit") != C.K3_COMMIT
        or prov.get("commit_dirty") is not False
        or summary.get("selected") != C.K3_CONFIG_ID
        or summary.get("common_origins") != C.K3_COMMON_N
    ):
        raise StopRun(f"{k3_dir}: not the clean K3 run {C.K3_RUN_ID} ({C.K3_COMMIT[:7]})")
    f = pd.read_parquet(k3_dir / "forecasts_val2019.parquet")
    f = f[f["member"] == "mean"]
    f["base_date"] = pd.to_datetime(f["base_date"])
    if f["base_date"].max() > pd.Timestamp(C.CUTOFF):
        raise StopRun("K3 forecasts after cutoff")
    common, forecasts = {}, {}
    for asset in C.ASSETS:
        part = f[f["asset"] == asset]
        sets = [pd.DatetimeIndex(g["base_date"].unique()) for _, g in part.groupby("config_id")]
        inter = sets[0]
        for s in sets[1:]:
            inter = inter.intersection(s)
        common[asset] = inter.sort_values()
        if len(sets) != 8 or len(common[asset]) != C.K3_COMMON_N[asset]:
            raise StopRun(f"K3 {asset}: common origins {len(common[asset])} != {C.K3_COMMON_N}")
        sel = part[part["config_id"] == C.K3_CONFIG_ID].sort_values(["base_date", "h"])
        base = pd.DatetimeIndex(sel["base_date"].unique())
        if list(sel["h"]) != list(HORIZONS) * len(base):
            raise StopRun(f"K3 {asset}: incomplete horizons")
        q = sel[list(wf.QCOLS)].to_numpy(float).reshape(len(base), len(HORIZONS), -1)
        crossed = sel["crossed_raw"].to_numpy(bool).reshape(len(base), len(HORIZONS))
        forecasts[asset] = (base, q, crossed)
    return forecasts, common


# ---------- đánh giá ----------


def restrict(forecasts: dict, origins: dict) -> dict:
    out = {}
    for asset, (base, q, crossed) in forecasts.items():
        keep = pd.DatetimeIndex(base).isin(origins[asset])
        if keep.sum() != len(origins[asset]):
            raise StopRun(f"{asset}: forecasts missing on common origins")
        out[asset] = (pd.DatetimeIndex(base)[keep], q[keep], crossed[keep])
    return out


def mean_skill_ci(detail: pd.DataFrame, asset: str, sample: str, cfg) -> dict:
    """pinball_skill trung bình 7 h và CI 95% (mục 6.3): mỗi lần lấy mẫu của kế hoạch bootstrap
    chung, pinball_skill từng h trên các ngày được rút rồi lấy trung bình 7 h. Cùng cách lọc và
    cùng kế hoạch rút với walk_forward._skill_ci."""
    dates, draws = wf.shared_bootstrap_plan(cfg)
    parts = []
    for h in HORIZONS:
        rows = detail.loc[(detail.asset == asset) & (detail.h == h)].sort_values("base_date")
        g = rows.loc[rows["common_mask_" + sample].fillna(False).to_numpy(bool)]
        parts.append(
            (
                pd.Index(pd.to_datetime(g.base_date)).get_indexer(dates),
                g.y_true.to_numpy(float),
                g[list(wf.QCOLS)].to_numpy(float),
                g[list(wf.BCOLS)].to_numpy(float),
            )
        )
    by_h = [M.pinball_skill(y, q, b) for _, y, q, b in parts]
    calls = 0

    def statistic(sampled):
        nonlocal calls
        index = sampled.astype(int)
        if not np.array_equal(index, draws[calls]):
            raise ValueError("bootstrap plan drift")
        calls += 1
        values = []
        for lookup, y, q, b in parts:
            take = lookup[index]
            take = take[take >= 0]
            values.append(M.pinball_skill(y[take], q[take], b[take]) if len(take) else np.nan)
        return float(np.mean(values))

    low, high = M.block_bootstrap_ci(
        np.arange(len(dates), dtype=float),
        statistic,
        block_length=cfg.block_length,
        n_resamples=cfg.n_bootstrap,
        confidence_level=cfg.confidence_level,
        seed=cfg.seed,
    )
    return {
        "asset": asset,
        "sample": sample,
        "value": float(np.mean(by_h)),
        "ci_low": low,
        "ci_high": high,
        "n_obs": [len(p[1]) for p in parts],
        "n_replicates": calls,
    }


def evaluate_set(models: dict, origins: dict, p, r) -> dict:
    """Mỗi model: T.evaluate trên `origins` + CI trung bình 7 h theo tài sản × sample."""
    named = {}
    for name, forecasts in models.items():
        e = T.evaluate(name, restrict(forecasts, origins), p, r)
        cfg = T.evaluation_config(name)
        acc = e["accuracy"].query("metric == 'pinball_skill'")
        rows = []
        for asset in C.ASSETS:
            for sample in ("all", "excl_roll") if asset in ("brent", "wti") else ("all",):
                row = mean_skill_ci(e["detail"], asset, sample, cfg)
                per_h = acc[(acc["asset"] == asset) & (acc["sample"] == sample)]["value"]
                if len(per_h) != 7 or not np.isclose(row["value"], per_h.mean(), atol=1e-12):
                    raise StopRun(f"{name} {asset} {sample}: 7-h mean disagrees with accuracy")
                rows.append({"model": name, **row})
        e["mean7"] = pd.DataFrame(rows)
        named[name] = e
    return named


def select_candidate(scores: dict) -> tuple[str, list[str]]:
    """Kế hoạch mục 4: cao nhất; chênh < TIE_TOLERANCE là hòa → S1a, rồi S1b, rồi S2."""
    best = max(scores[c] for c in C.CANDIDATES)
    tied = [c for c in C.CANDIDATES if best - scores[c] < C.TIE_TOLERANCE]
    return tied[0], tied


# ---------- chạy ----------


def run(lake_dir: Path, output_dir: Path, run_id: str, k3_dir: Path) -> dict:
    t_start = time.perf_counter()
    lake = Path(lake_dir)
    eval_dir = Path(output_dir) / "eval" / "k3b" / run_id
    if eval_dir.exists():
        raise FileExistsError(eval_dir)
    k3_forecasts, k3_common = k3_reference(Path(k3_dir))
    prices, rejected = T.read_clean(lake, C.CLEAN_DT)
    st = storage.LocalStorage(str(lake))
    t = time.perf_counter()
    cfg = T.cache_config(C.S2_WINDOW)
    cache = {}
    for asset in C.ASSETS:
        meta = json.loads(st.read_bytes(f"{cc.prefix(asset, cfg)}/config.json"))
        if meta.get("cfg_hash") != C.EXPECTED_CFG_HASH:
            raise StopRun(f"{asset} w={C.S2_WINDOW}: config.json cfg_hash mismatch")
        cache[asset] = load_cache(st, asset, cfg, C.CACHE_START, C.CUTOFF)
    seconds = {"cache_read": time.perf_counter() - t}
    commit, dirty = T.source_commit()
    invalid = {
        a: pd.to_datetime(rejected.loc[rejected["asset"] == a, "date"]).tolist() for a in C.ASSETS
    }
    sessions = {
        a: {
            "train": calendars.sessions(ASSETS[a].calendar, *C.TRAIN),
            "val": calendars.sessions(ASSETS[a].calendar, *C.VALID),
        }
        for a in C.ASSETS
    }
    provenance = {
        "commit": commit,
        "commit_dirty": dirty,
        "versions": T.versions(),
        "code_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES
        },
        "data_lineage": {
            "clean_dt": C.CLEAN_DT,
            "cutoff": C.CUTOFF,
            "prices_view": T.frame_lineage(prices),
            "rejected_view": T.frame_lineage(rejected) if len(rejected) else {"n_rows": 0},
        },
        "k3_reference": {"run_id": C.K3_RUN_ID, "commit": C.K3_COMMIT, "dir": str(k3_dir)},
    }
    ctx = {
        "prices": prices,
        "cache": cache,
        "invalid": invalid,
        "sessions": sessions,
        "model_root": Path(output_dir) / "models",
        "provenance": provenance,
    }

    candidates = {}
    for name in ("S1a", "S1b"):
        t = time.perf_counter()
        candidates[name] = run_s1(name, ctx)
        seconds[name] = time.perf_counter() - t
    t = time.perf_counter()
    candidates["S2"] = run_s2(ctx)
    seconds["S2"] = time.perf_counter() - t
    print(json.dumps({"candidates_done": {k: round(v, 1) for k, v in seconds.items()}}))

    # Tập chung (mục 6.2): giao 3 ứng viên = tập quy tắc A của S2, chứa trọn tập K3
    common = {}
    for asset in C.ASSETS:
        sets = [pd.DatetimeIndex(candidates[c]["forecasts"][asset][0]) for c in C.CANDIDATES]
        inter = sets[0]
        for s in sets[1:]:
            inter = inter.intersection(s)
        common[asset] = inter.sort_values()
        if not inter.equals(sets[2].sort_values()) or len(inter) != C.EXPECTED_COMMON_N[asset]:
            raise StopRun(f"{asset}: common origins {len(inter)} != S2 rule A set")
        if not k3_common[asset].isin(inter).all():
            raise StopRun(f"{asset}: K3 common origins not contained in K3b common origins")
        if not pd.DatetimeIndex(k3_forecasts[asset][0]).equals(inter):
            raise StopRun(f"{asset}: K3 {C.K3_CONFIG_ID} origins differ from K3b common origins")

    t = time.perf_counter()
    p, r = wf._inputs(prices, rejected, T.evaluation_config("inputs"))
    models = {c: candidates[c]["forecasts"] for c in C.CANDIDATES}
    models[BASELINE] = T.baseline_forecasts(prices, invalid, common)
    models[K3_NAME] = k3_forecasts
    sets = {"common": evaluate_set(models, common, p, r)}
    sets["k3_common"] = evaluate_set(models, k3_common, p, r)
    seconds["evaluation"] = time.perf_counter() - t
    for named in sets.values():
        skill = named[BASELINE]["accuracy"].query("metric == 'pinball_skill'")["value"]
        if skill.abs().max() > 1e-12:
            raise StopRun("anchor baseline differs from walk_forward evaluation baseline")

    scores = {}
    for set_name, named in sets.items():
        scores[set_name] = {}
        for name, e in named.items():
            m28, by_asset = T.mean_skill(e["accuracy"])
            scores[set_name][name] = {"mean_28": m28, "by_asset": by_asset}
    selected, tied = select_candidate({c: scores["common"][c]["mean_28"] for c in C.CANDIDATES})
    selected_k3, _ = select_candidate({c: scores["k3_common"][c]["mean_28"] for c in C.CANDIDATES})
    criterion = {}
    for set_name, named in sets.items():
        m = named[selected]["mean7"]
        criterion[set_name] = {
            f"{row.asset}/{row.sample}": bool(row.ci_low > 0) for row in m.itertuples()
        }

    k_dist = {
        name: {
            asset: {
                "train": k_summary(v["train"]),
                "val_common": k_summary(v["val"].loc[common[asset]]),
            }
            for asset, v in candidates[name]["k"].items()
        }
        for name in ("S1a", "S1b")
    }

    eval_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for name in C.CANDIDATES:
        for asset, (base, q, crossed) in candidates[name]["forecasts"].items():
            for i, d in enumerate(base):
                for j, h in enumerate(HORIZONS):
                    rows.append(
                        {
                            "candidate": name,
                            "asset": asset,
                            "base_date": d,
                            "h": h,
                            **dict(zip(wf.QCOLS, q[i, j].tolist(), strict=True)),
                            "crossed_raw": bool(crossed[i, j]),
                            "in_common": bool(d in common[asset]),
                            "in_k3_common": bool(d in k3_common[asset]),
                        }
                    )
    pd.DataFrame(rows).to_parquet(eval_dir / "forecasts_val2019.parquet", index=False)
    for kind in ("accuracy", "comparison", "detail", "mean7"):
        pd.concat(
            [
                e[kind].assign(model=name, origin_set=set_name)
                for set_name, named in sets.items()
                for name, e in named.items()
            ],
            ignore_index=True,
        ).to_parquet(eval_dir / f"{kind}.parquet", index=False)
    seconds["total"] = time.perf_counter() - t_start
    summary = {
        "run_id": run_id,
        "plan": "docs/experiments/k3b-volatility-plan.md",
        "look_number": C.LOOK_NUMBER,
        "total_configs_seen_on_2019": C.TOTAL_CONFIGS_SEEN,
        "provenance": provenance,
        "candidates": list(C.CANDIDATES),
        "s1_lambda": C.S1_LAMBDA,
        "k_clip": list(C.K_CLIP),
        "common_origins": {a: len(v) for a, v in common.items()},
        "k3_common_origins": {a: len(v) for a, v in k3_common.items()},
        "scores": scores,
        "selected": selected,
        "tied_with_best": tied,
        "selected_on_k3_common": selected_k3,
        "criterion_ci_low_gt_0": criterion,
        "mean7": {
            set_name: named[selected]["mean7"].to_dict("records")
            for set_name, named in sets.items()
        },
        "k_distribution": k_dist,
        "s2": {k: v for k, v in candidates["S2"]["assets"].items()},
        "seconds": seconds,
        "dm_blocked_groups": {
            name: [g for g in e["log"]["dm_calendar_gaps"] if g["blocked"]]
            for name, e in sets["common"].items()
        },
        "bootstrap_plan": sets["common"][BASELINE]["log"]["bootstrap_plan"],
    }
    (eval_dir / "summary.json").write_text(
        json.dumps(wf._plain(summary), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    (eval_dir / "summary.md").write_text(render(summary, sets), encoding="utf-8")
    return summary


# ---------- báo cáo Markdown (chỉ trình bày số đã tính) ----------


def mean7_table(named: dict, models: list[str]) -> pd.DataFrame:
    rows = []
    for name in models:
        for row in named[name]["mean7"].itertuples():
            rows.append(
                {
                    "model": name,
                    "asset": row.asset,
                    "sample": row.sample,
                    "pinball_skill trung bình 7 h": row.value,
                    "CI 95%": f"[{row.ci_low:+.4f}, {row.ci_high:+.4f}]",
                    "cận dưới > 0": "có" if row.ci_low > 0 else "không",
                }
            )
    return pd.DataFrame(rows)


def hit_table(named: dict, models: list[str]) -> pd.DataFrame:
    rows = []
    for name in models:
        a = named[name]["accuracy"]
        for (asset, sample, h), g in a.groupby(["asset", "sample", "h"], sort=False):
            g = g.set_index("metric")["value"]
            rows.append(
                {
                    "model": name,
                    "asset": asset,
                    "sample": sample,
                    "h": h,
                    **{f"{t:.2f}": g[f"quantile_hit_{t:.2f}"] for t in QUANTILE_LEVELS},
                }
            )
    return pd.DataFrame(rows)


def render(summary: dict, sets: dict) -> str:
    sel = summary["selected"]
    models = [*C.CANDIDATES, BASELINE, K3_NAME]
    out = [f"# K3b co giãn theo biến động: kết quả validation 2019 ({summary['run_id']})", ""]
    out.append(
        f"Lần nhìn thứ {summary['look_number']} vào validation 2019; tổng "
        f"{summary['total_configs_seen_on_2019']} cấu hình đã xem trên 2019."
    )
    out.append(
        f"Ứng viên được chọn: **{sel}**; hòa với cao nhất: {', '.join(summary['tied_with_best'])}."
    )
    out.append(f"Chọn trên tập K3 (tham khảo): {summary['selected_on_k3_common']}.")
    out.append("")
    out.append(
        "Tập chung (giao 3 ứng viên): "
        + ", ".join(f"{a} {n}" for a, n in summary["common_origins"].items())
        + "; tập K3: "
        + ", ".join(f"{a} {n}" for a, n in summary["k3_common_origins"].items())
    )
    for set_name, title in (("common", "tập chung"), ("k3_common", "tập K3")):
        out += ["", f"## Trung bình pinball_skill (sample=all, 7 h), {title}"]
        rows = [
            {
                "model": name,
                **{a: s["by_asset"][a] for a in C.ASSETS},
                "trung bình 28 nhóm": s["mean_28"],
            }
            for name, s in summary["scores"][set_name].items()
        ]
        out += [T.md(pd.DataFrame(rows)), ""]
        out.append(f"### pinball_skill trung bình 7 h, CI 95% ({title})")
        out += [T.md(mean7_table(sets[set_name], models)), ""]
    named = sets["common"]
    out.append(f"## Mọi chỉ số theo tài sản × h (tập chung): 3 ứng viên, {BASELINE}, {K3_NAME}")
    out.append("Naive (return = 0) là mẫu số của mae_ratio_vs_naive (= 1) và không có phân vị.")
    for asset in C.ASSETS:
        out += ["", f"### {asset}", "", T.md(T.metric_table(named, models, asset))]
    out += ["", "## quantile_hit_rates (tập chung)", "", T.md(hit_table(named, models)), ""]
    out.append(f"## DM ({sel} vs baseline-252, walk_forward DM_GAP_POLICY, tập chung)")
    c = named[sel]["comparison"][
        ["asset", "sample", "h", "dm_stat", "p_value", "p_value_holm", "status", "undefined_reason"]
    ]
    out += [T.md(c), ""]
    out.append("## Phân bố k_t (train: ngày gốc 2014–2018 có k_t; val: tập chung 2019)")
    rows = [
        {"candidate": name, "asset": asset, "period": period, **stats}
        for name, by_asset in summary["k_distribution"].items()
        for asset, periods in by_asset.items()
        for period, stats in periods.items()
    ]
    out += [T.md(pd.DataFrame(rows)), ""]
    out.append("## S2: huấn luyện")
    rows = [
        {
            "asset": asset,
            "seed": s["seed"],
            "loss đầu": s["initial_loss"],
            "loss cuối": s["epoch_losses"][-1],
            "parity": f"{v['parity_max_abs_error']:.1e}",
            "width80 val / mốc (trung vị)": v["val_width80_ratio_to_baseline"]["median"],
        }
        for asset, v in summary["s2"].items()
        for s in v["seeds"]
    ]
    out += [T.md(pd.DataFrame(rows), ".6f"), ""]
    out.append("## Thời gian (giây)")
    out.append(", ".join(f"{k} {v:.1f}" for k, v in summary["seconds"].items()))
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lake-dir", type=Path, default=DEFAULT_LAKE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--run-id", default="k3b-val2019")
    parser.add_argument("--k3-dir", type=Path, default=DEFAULT_K3_DIR)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args(argv)
    if args.threads < 1:
        parser.error("threads must be positive")
    torch.set_num_threads(args.threads)
    try:
        summary = run(args.lake_dir, args.output_dir, args.run_id, args.k3_dir)
    except StopRun as exc:
        print(f"DỪNG: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"selected": summary["selected"], "seconds": summary["seconds"]["total"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

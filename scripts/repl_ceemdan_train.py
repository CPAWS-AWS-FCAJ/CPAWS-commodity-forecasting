"""Minh họa CEEMDAN + LSTM, bước 2: dựng mẫu, train LSTM 3 biến thể, đo trên 2017–2018.

Chạy:
  python scripts/repl_ceemdan_train.py --device cpu --smoke   # 1 mô hình × 2 lần, kiểm tất định
  python scripts/repl_ceemdan_train.py --device cpu           # đủ 108 LSTM + chỉ số

Kế hoạch: docs/experiments/ceemdan-lstm-replication-plan.md. Đọc bản tách của bước 1
(data/eval/repl-ceemdan-lstm/, kiểm manifest trước) và bản clean ≤ 2018-12-31 ở lake local; không
gọi AWS. Ghi vào data/eval/repl-ceemdan-lstm/results/ (gitignore): predictions.parquet,
metrics.parquet, train_log.parquet, summary.json, env.txt (SHA-256 từng file trong summary.json).
Chỉ in số tổng hợp, không in giá hay giá trị IMF. Mã thoát 2: manifest hoặc digest bản tách của
bước 1 thiếu hay lệch (artifacts_sha256.json), đọc được dữ liệu sau CUTOFF, hoặc smoke không tất
định.
"""

from __future__ import annotations

import os

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import storage
from src.experiments.repl_ceemdan_lstm import config as C
from src.experiments.repl_ceemdan_lstm.data import (
    CutoffError,
    asset_series,
    file_sha256,
    read_clean,
)
from src.experiments.repl_ceemdan_lstm.dataset import (
    SEGMENTS,
    VARIANTS,
    build_samples,
    sample_counts,
)
from src.experiments.repl_ceemdan_lstm.decompose import cross_check_cache
from src.experiments.repl_ceemdan_lstm.evaluate import (
    aggregate_seeds,
    calibrated_quantiles,
    mechanism_diagnostics,
    price_metrics,
    return_metrics,
    to_returns,
)
from src.experiments.repl_ceemdan_lstm.model import (
    fit_predict_variant,
    predict,
    resolve_device,
)
from src.experiments.repl_ceemdan_lstm.provenance import (
    check_clean_sha256,
    check_digests,
    git_info,
    git_label,
    read_digests,
)
from src.forecast.returns import QUANTILE_LEVELS

# Bước 1 (quyết định Khải 3/11, bước 2 mục 1): số cửa sổ R-causal phải đủ
EXPECTED_CAUSAL = {"gold": 1258, "silver": 1258, "brent": 1254, "wti": 1256}
N_MODELS = len(C.SEEDS) * len(C.ASSETS) * (2 * C.N_COMPONENTS + 1)  # 108
MAX_FULL_HOURS = 3.0
Q_COLS = [f"q{round(q * 100):02d}" for q in QUANTILE_LEVELS]


def md(rows: list[dict] | pd.DataFrame, fmt: str = ".4g") -> str:
    df = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows
    if df.empty:
        return "_(trống)_"

    def f(v) -> str:
        if isinstance(v, float | np.floating):
            return "" if np.isnan(v) else format(float(v), fmt)
        return str(v)

    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(f(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(out)


def stop(msg: str) -> int:
    print(f"\n**DỪNG**: {msg}")
    return 2


def check_manifest(dec_dir: Path, lake: Path) -> tuple[dict, list[str]]:
    """Bản tách đầy đủ của bước 1 (fail-closed): cfg_hash, SHA-256 bản clean, đủ cửa sổ, SHA-256 của
    8 file bản tách. Chỉ băm file, không giải mã dòng dữ liệu nào."""
    try:
        m = json.loads((dec_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {}, [f"không đọc được manifest.json: {e}"]
    errs = []
    if m.get("limit"):
        errs.append(f"manifest là bản probe (limit={m['limit']})")
    if m.get("cfg_hash") != C.EXPECTED_CFG_HASH:
        errs.append(f"cfg_hash {m.get('cfg_hash')} ≠ {C.EXPECTED_CFG_HASH}")
    if m.get("clean_dt") != C.CLEAN_DT:
        errs.append(f"clean_dt {m.get('clean_dt')} ≠ {C.CLEAN_DT}")
    clean_dir = lake / "clean" / "prices" / f"dt={C.CLEAN_DT}"
    errs += check_clean_sha256(m.get("sha256"), clean_dir)
    for a, n in EXPECTED_CAUSAL.items():
        st = m.get("assets", {}).get(a, {})
        rc = st.get("r_causal", {})
        if rc.get("n_origins") != n or rc.get("n_computed") != n:
            errs.append(f"{a}: R-causal {rc.get('n_computed')}/{rc.get('n_origins')} ≠ {n}")
        if "r_full" not in st:
            errs.append(f"{a}: thiếu R-full trong manifest")
    errs += check_digests(dec_dir)
    return m, errs


def env_text(device: torch.device, threads: int) -> str:
    try:
        driver = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        driver = "không có (không tìm thấy nvidia-smi)"
    lines = [
        f"date_utc: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"python: {platform.python_version()} ({platform.system()} {platform.release()})",
        f"processor: {platform.processor()}",
        f"torch: {torch.__version__}",
        f"torch.version.cuda: {torch.version.cuda}",
        f"torch.cuda.is_available: {torch.cuda.is_available()}",
        f"cudnn: {torch.backends.cudnn.version() if torch.cuda.is_available() else None}",
        f"gpu/driver: {driver}",
        f"device: {device}",
        f"torch threads: {threads}",
        f"deterministic_algorithms: {torch.are_deterministic_algorithms_enabled()}",
        f"CUBLAS_WORKSPACE_CONFIG: {os.environ.get('CUBLAS_WORKSPACE_CONFIG')}",
        f"numpy: {np.__version__}",
        f"pandas: {pd.__version__}",
    ]
    if device.type == "cpu" and not torch.cuda.is_available():
        lines.append(
            "ghi chú: máy chỉ có torch bản CPU (cuda.is_available() = False); mọi mô hình chạy "
            "--device cpu, không cài torch CUDA, không trộn thiết bị."
        )
    return "\n".join(lines) + "\n"


def load_inputs(lake: Path, dec_dir: Path):
    clean = read_clean(lake, C.CLEAN_DT)
    samples, three_imf = {}, []
    for a in C.ASSETS:
        s = asset_series(clean.prices, a)
        causal = pd.read_parquet(dec_dir / f"r_causal_{a}.parquet")
        full = pd.read_parquet(dec_dir / f"r_full_{a}.parquet")
        for name, d in (("r_causal", causal["end_date"]), ("r_full", full["date"])):
            if pd.Timestamp(d.max()) > pd.Timestamp(C.CUTOFF):
                raise CutoffError(f"{name}_{a}: có ngày sau {C.CUTOFF}")
        invalid = pd.to_datetime(clean.rejected.loc[clean.rejected["asset"] == a, "date"])
        sm = build_samples(s, causal, full, invalid_dates=invalid.tolist())
        samples[a] = (sm, causal)
        pos = pd.Series(causal["n_imf"].to_numpy(), index=pd.DatetimeIndex(causal["end_date"]))
        used = pos.reindex(sm.origins[sm.segment != ""])
        three_imf.append(
            {
                "asset": a,
                "cửa sổ 2014–2018": len(causal),
                "n_imf = 3": int((causal["n_imf"] == 3).sum()),
                "n_imf < 3": int((causal["n_imf"] < 3).sum()),
                "n_imf = 3 trong mẫu dùng": int((used == 3).sum()),
                "n_imf min–max": f"{causal['n_imf'].min()}–{causal['n_imf'].max()}",
            }
        )
    return clean, samples, three_imf


def run_smoke(samples, device) -> tuple[dict, bool]:
    """gold × r_causal × imf1 × seed 0, hai lần: trọng số và dự báo phải trùng từng bit."""
    sm = samples["gold"][0]
    runs = []
    for _ in range(2):
        t = time.perf_counter()
        p, infos, models = fit_predict_variant(sm, "r_causal", 0, device, components=[0])
        runs.append((p, infos[0], models[0], time.perf_counter() - t))
    (p1, i1, m1, s1), (p2, i2, m2, s2) = runs
    w_equal = all(
        torch.equal(a, b) for a, b in zip(m1.state_dict().values(), m2.state_dict().values())
    )
    used = sm.segment != ""
    pred_equal = bool(np.array_equal(p1[used], p2[used]))
    x = sm.X["r_causal"][used, :, 0]
    raw_equal = bool(np.array_equal(predict(m1, x, device), predict(m2, x, device)))
    est = (s1 + s2) / 2 * N_MODELS
    out = {
        "device": str(device),
        "weights_bit_equal": w_equal,
        "predictions_bit_equal": pred_equal and raw_equal,
        "seconds": [round(s1, 2), round(s2, 2)],
        "best_epoch": [i1["best_epoch"], i2["best_epoch"]],
        "epochs_run": [i1["epochs_run"], i2["epochs_run"]],
        "estimated_full_minutes": round(est / 60, 1),
    }
    return out, w_equal and pred_equal and raw_equal


def run_full(samples, device):
    pred_rows, metric_rows, price_rows, log_rows, run_out = [], [], [], [], {}
    t_all = time.perf_counter()
    for seed in C.SEEDS:
        for a in C.ASSETS:
            sm = samples[a][0]
            for v in VARIANTS:
                p_hat, infos, _ = fit_predict_variant(sm, v, seed, device)
                r_hat, err = to_returns(p_hat, sm.p_t)
                calib = sm.mask("calib")
                resid = sm.r_next[calib] - r_hat[calib]
                q = calibrated_quantiles(r_hat, resid)
                run_out[(seed, a, v)] = (p_hat, r_hat, err, q)
                for info in infos:
                    log_rows.append({"seed": seed, "asset": a, "variant": v, **info})
                secs = sum(i["seconds"] for i in infos)
                print(
                    f"- seed {seed} {a} {v}: {len(infos)} LSTM, {secs:.1f} s, "
                    f"best_epoch {[i['best_epoch'] for i in infos]}",
                    flush=True,
                )
    train_seconds = time.perf_counter() - t_all

    masks, err_counts = {}, []
    for a in C.ASSETS:
        sm = samples[a][0]
        ev = sm.mask("eval")
        bad = np.zeros(len(ev), dtype=bool)
        for seed in C.SEEDS:
            for v in VARIANTS:
                _, r_hat, err, _ = run_out[(seed, a, v)]
                bad |= ~np.isfinite(r_hat)
                err_counts.append(
                    {
                        "seed": seed,
                        "asset": a,
                        "variant": v,
                        "p_hat_le_0_eval": int((err & ev).sum()),
                        "p_hat_le_0_all": int(err.sum()),
                    }
                )
        masks[a] = ev & ~bad

    for (seed, a, v), (p_hat, r_hat, err, q) in run_out.items():
        sm = samples[a][0]
        m = masks[a]
        y = sm.r_next[m]
        metric_rows.append(
            {"seed": seed, "asset": a, "variant": v}
            | return_metrics(y, r_hat[m], q[m], sm.baseline_q[m])
        )
        price_rows.append(
            {"seed": seed, "asset": a, "variant": v}
            | price_metrics(sm.p_next[m], p_hat[m], sm.p_t[m])
        )
        keep = sm.segment != ""
        df = pd.DataFrame(
            {
                "seed": seed,
                "asset": a,
                "variant": v,
                "origin": sm.origins[keep],
                "target_date": sm.target_dates[keep],
                "segment": sm.segment[keep].astype(str),
                "in_eval_mask": m[keep],
                "p_t": sm.p_t[keep],
                "p_true": sm.p_next[keep],
                "p_hat": p_hat[keep],
                "r_true": sm.r_next[keep],
                "r_hat": r_hat[keep],
                "forecast_error": err[keep],
            }
        )
        for j, c in enumerate(Q_COLS):
            df[c] = q[keep, j]
        pred_rows.append(df)
    return (
        pd.concat(pred_rows, ignore_index=True),
        pd.DataFrame(metric_rows),
        pd.DataFrame(price_rows),
        pd.DataFrame(log_rows),
        pd.DataFrame(err_counts),
        masks,
        train_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lake-dir", default=str(ROOT / "data" / "lake"))
    ap.add_argument("--dec-dir", default=str(ROOT / "data" / C.OUT_SUBDIR))
    ap.add_argument("--device", choices=["auto", "cpu"], default="auto")
    ap.add_argument("--threads", type=int, default=1, help="torch.set_num_threads (CPU)")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.perf_counter()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    torch.set_num_threads(args.threads)
    device = resolve_device(args.device)
    lake, dec_dir = Path(args.lake_dir), Path(args.dec_dir)
    out = dec_dir / "results"

    print("# Minh họa CEEMDAN + LSTM, bước 2\n")
    manifest, errs = check_manifest(dec_dir, lake)
    if errs:
        return stop("manifest bước 1: " + "; ".join(errs))
    digests = read_digests(dec_dir)
    git = git_info()
    decompose_commit = (manifest.get("git") or {}).get("commit")
    print(
        f"Manifest bước 1: cfg_hash {manifest['cfg_hash']}, clean dt={manifest['clean_dt']}, "
        f"SHA-256 bản clean và 8 file bản tách khớp, đủ cửa sổ {EXPECTED_CAUSAL}, "
        f"commit tách {git_label(decompose_commit)[:7]}."
    )
    print(f"Git: commit {git_label(git['commit'])}, dirty {git_label(git['dirty'])}.")
    print(
        f"Thiết bị: {device} (torch {torch.__version__}, CUDA {torch.version.cuda}), "
        f"{args.threads} luồng."
    )
    try:
        clean, samples, three_imf = load_inputs(lake, dec_dir)
    except CutoffError as e:
        return stop(str(e))
    print(
        f"Ngày lớn nhất đọc được: prices {clean.prices['date'].max().date()}, "
        f"rejected {clean.rejected['date'].max().date()}."
    )

    print("\n## Số mẫu theo đoạn\n")
    count_rows, excl_rows, bounds_rows = [], [], []
    for a in C.ASSETS:
        sm = samples[a][0]
        c = sample_counts(sm)
        count_rows.append({"asset": a} | {s: c[s] for s in SEGMENTS})
        for why, k in c["excluded"].items():
            excl_rows.append({"asset": a, "lý do": why, "số ngày gốc": k})
        bounds_rows.append(
            {"asset": a}
            | {
                s: f"{b[0].date()} → {b[1].date()}"
                for s, b in sm.segment_bounds.items()
                if s != "eval"
            }
            | {
                "eval (ngày gốc)": f"{sm.origins[sm.mask('eval')].min().date()} → "
                f"{sm.origins[sm.mask('eval')].max().date()}",
                "target eval max": str(sm.target_dates[sm.mask("eval")].max().date()),
            }
        )
    print(md(count_rows))
    print("\n**Ranh giới đoạn (ngày, dùng chung 3 biến thể × 3 seed)**\n")
    print(md(bounds_rows))
    print("\n**Ngày gốc bị loại theo lý do** (mỗi ngày một lý do, theo thứ tự ưu tiên)\n")
    print(md(excl_rows))
    print("\n**Cửa sổ R-causal chỉ có 3 IMF** (thành phần rest chỉ còn residue)\n")
    print(md(three_imf))

    print("\n## Kiểm chéo cache ADR-0007 (chỉ tháng ≤ 2018-12, không dùng cho mô hình)\n")
    st = storage.LocalStorage(str(lake))
    try:
        xc = [cross_check_cache(st, a, C.ceemdan_config(), samples[a][1]) for a in C.ASSETS]
    except RuntimeError as e:
        return stop(str(e))
    print(md(xc, ".3g"))

    if args.smoke:
        print("\n## Smoke: gold × r_causal × imf1 × seed 0, hai lần\n")
        res, ok = run_smoke(samples, device)
        print(md([res]))
        out.mkdir(parents=True, exist_ok=True)
        (out / "smoke.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        (out / "env.txt").write_text(env_text(device, args.threads), encoding="utf-8")
        if not ok:
            return stop(f"smoke không tất định trên {device}")
        print(f"\nƯớc tính {N_MODELS} mô hình: {res['estimated_full_minutes']} phút.")
        if res["estimated_full_minutes"] > MAX_FULL_HOURS * 60:
            return stop(f"ước tính vượt {MAX_FULL_HOURS} giờ")
        return 0

    print(f"\n## Train {N_MODELS} LSTM\n")
    preds, met, pm, logs, errc, masks, train_s = run_full(samples, device)
    out.mkdir(parents=True, exist_ok=True)

    keys = ["asset", "variant"]
    ret_cols = [
        "mae_ratio_vs_naive",
        "sign_accuracy",
        "pinball_skill",
        "coverage_80",
        "dm_stat_vs_naive",
        "dm_p_vs_naive",
    ]
    agg = aggregate_seeds(met, keys, ret_cols)
    seed_free = met.groupby(keys, sort=False)[["n", "up_rate", "baseline_coverage_80"]].first()
    agg = agg.merge(seed_free.reset_index(), on=keys)
    price_cols = ["mae_model", "rmse_model", "mape_model"]
    pagg = aggregate_seeds(pm, keys, price_cols)
    pagg = pagg.merge(
        pm.groupby(keys, sort=False)[
            ["mae_naive", "rmse_naive", "mape_naive", "mape_excluded_pairs"]
        ]
        .first()
        .reset_index(),
        on=keys,
    )
    diag = []
    for a in C.ASSETS:
        sm = samples[a][0]
        diag += [r | {"tập": "eval 2017–2018"} for r in mechanism_diagnostics(sm, masks[a])]
        diag += [r | {"tập": "fit"} for r in mechanism_diagnostics(sm, sm.mask("fit"))]
    diag = pd.DataFrame(diag)

    print("\n## Chỉ số ADR-0008 (log return h = 1, eval 2017–2018; mean [min, max] qua 3 seed)\n")
    print(md(agg, ".4f"))
    print("\n## Kiểu bài báo — CHỈ ĐỂ MINH HỌA, ADR-0008 không dùng (mức giá một bước tới)\n")
    print(md(pagg, ".4f"))
    print("\n## Chẩn đoán cơ chế: giá trị tại t, R-full so với R-causal\n")
    print(md(diag, ".4f"))
    print("\n## Lỗi dự báo (P̂ ≤ 0)\n")
    print(
        md(
            errc.groupby(keys, sort=False)[["p_hat_le_0_eval", "p_hat_le_0_all"]]
            .sum()
            .reset_index()
        )
    )
    print("\n## Train\n")
    tl = logs.groupby("variant", sort=False).agg(
        models=("seconds", "size"),
        seconds=("seconds", "sum"),
        best_epoch_min=("best_epoch", "min"),
        best_epoch_median=("best_epoch", "median"),
        best_epoch_max=("best_epoch", "max"),
        hit_max_epochs=("epochs_run", lambda s: int((s >= C.LSTM["max_epochs"]).sum())),
    )
    print(md(tl.reset_index(), ".4g"))

    files = {
        "predictions.parquet": preds,
        "metrics.parquet": met,
        "price_metrics.parquet": pm,
        "train_log.parquet": logs,
        "diagnostics.parquet": diag,
    }
    for name, df in files.items():
        df.to_parquet(out / name, index=False)
    (out / "env.txt").write_text(env_text(device, args.threads), encoding="utf-8")
    sha = {name: file_sha256(out / name) for name in [*files, "env.txt"]}
    summary = {
        "step": "repl-ceemdan-lstm/train",
        "started_at": started_at,
        "seconds_total": round(time.perf_counter() - t0, 1),
        "train_seconds": round(train_s, 1),
        "device": str(device),
        "threads": args.threads,
        "git": git,
        "decompose_manifest_commit": decompose_commit,
        "decomposition_sha256": digests,
        "clean_dt": C.CLEAN_DT,
        "clean_sha256": clean.sha256,
        "cfg_hash": manifest["cfg_hash"],
        "lstm": C.LSTM,
        "seeds": list(C.SEEDS),
        "split": list(C.SPLIT),
        "n_models": len(logs),
        "sample_counts": {a: sample_counts(samples[a][0]) for a in C.ASSETS},
        "eval_mask_n": {a: int(masks[a].sum()) for a in C.ASSETS},
        "three_imf_windows": three_imf,
        "cache_cross_check": xc,
        "return_metrics": agg.to_dict(orient="records"),
        "price_metrics_illustrative_only": pagg.to_dict(orient="records"),
        "diagnostics": diag.to_dict(orient="records"),
        "forecast_errors": errc.to_dict(orient="records"),
        "sha256": sha,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(
        f"\nTổng: {summary['seconds_total']} s (train {summary['train_seconds']} s). Ghi vào {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

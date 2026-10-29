"""K4: FHS GJR-GARCH và kết hợp phân vị, kiểm định chéo 2016–2018 (docs/experiments/k4-plan.md).

Chạy từ gốc repo, bằng venv có arch 8.0.0 (requirements-dev.txt):
  python -m src.forecast.run_k4 --stage cv [--lake-dir data/lake] [--output-dir data] [--run-id k4-cv]
  python -m src.forecast.run_k4 --stage val2019 --cv-dir data/eval/k4/k4-cv --candidate <tên>

- Stage cv: bản clean configs/k4.CLEAN_DT cắt tại 2018-12-31 ngay khi đọc; ngày gốc 2016–2018, ngày
  đích ≤ 2018-12-31 (một mốc cắt cho cả ba fold, mục 8). Bốn mô hình: baseline-q252, S1a (λ 0,94),
  fhs-gjr-t (src/forecast/fhs_fit.py + fhs_numpy.py), combo-eq3 = (q252 + S1a + FHS) / 3 trước
  normalize, rồi normalize_quantiles() đúng một lần. Tập ngày gốc chung: q252, S1a, FHS cùng hợp lệ.
  Đánh giá bằng walk_forward (cấu hình cross_validation) qua train_ceemdan.evaluate và
  run_k3b.evaluate_set; chọn theo mục 4; MCS 90% theo từng tài sản chỉ để báo cáo (mục 8).
- Stage val2019: chỉ phần chặn (có kết quả cv, không dừng sớm, ứng viên đúng là ứng viên mục 4
  chọn); qua được phần chặn vẫn dừng, phần chạy 2019 chưa viết.
- Không đọc cache CEEMDAN (mọi hàm đọc cache bị chặn trong lúc chạy), không ghi S3, không đọc 2019
  ở stage cv; kết quả local <output>/eval/k4/<run_id>/.

Điều kiện dừng (StopRun hoặc FitStop, thoát mã 2): đọc được dữ liệu sau mốc cắt, tập chung khác
mục 8, lần refit đầu lỗi, đệ quy NumPy lệch arch, mốc so sánh khác mốc của walk_forward.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from arch.bootstrap import MCS

from configs import k4 as C
from src.data import calendars
from src.data.config import ASSETS
from src.eval import walk_forward as wf
from src.features import ceemdan_cache as cc
from src.features import ceemdan_features as cf
from src.features.ceemdan_features import baseline_quantiles
from src.forecast import fhs_fit as FF
from src.forecast import run_k3b as R3
from src.forecast import train_ceemdan as T
from src.forecast.fhs_numpy import LEVELS, fhs_quantiles, seed_for, variance_path
from src.forecast.returns import QUANTILE_LEVELS, normalize_quantiles
from src.forecast.vol_scaled import daily_log_returns, s1_quantiles

ROOT = T.ROOT
DEFAULT_LAKE = T.DEFAULT_LAKE
PLAN = "docs/experiments/k4-plan.md"
HORIZONS = tuple(C.HORIZONS)
StopRun = T.StopRun  # read_clean, mean_skill, restrict của K3/K3b dừng bằng cùng lớp
STOPS = (StopRun, FF.FitStop)
MODELS = (C.BASELINE, C.S1A, C.FHS, C.COMBO)
CODE_FILES = (
    "configs/k4.py",
    "configs/k3_grid.py",
    "configs/k3b.py",
    "src/eval/metrics.py",
    "src/eval/walk_forward.py",
    "src/features/ceemdan_features.py",
    "src/forecast/baselines.py",
    "src/forecast/fhs_fit.py",
    "src/forecast/fhs_numpy.py",
    "src/forecast/returns.py",
    "src/forecast/run_k3b.py",
    "src/forecast/run_k4.py",
    "src/forecast/train_ceemdan.py",
    "src/forecast/vol_scaled.py",
)
# K4 không dùng IMF: các hàm này đọc cache CEEMDAN và bị chặn trong lúc chạy
CACHE_READERS = (
    (cc, "load"),
    (cc, "read_month"),
    (cc, "ensure"),
    (cc, "update_recent"),
    (cf, "load_cache"),
    (T, "load_cache"),
    (T, "read_caches"),
    (R3, "load_cache"),
)


@contextlib.contextmanager
def no_ceemdan_cache():
    """Trong khối này mọi lần đọc cache CEEMDAN báo StopRun."""

    def blocked(*_args, **_kwargs):
        raise StopRun("K4 must not read the CEEMDAN cache")

    saved = [(module, name, getattr(module, name)) for module, name in CACHE_READERS]
    try:
        for module, name, _ in saved:
            setattr(module, name, blocked)
        yield
    finally:
        for module, name, original in saved:
            setattr(module, name, original)


def cv_config(model_version: str) -> wf.EvaluationConfig:
    return wf.EvaluationConfig(
        run_id=f"k4-{model_version}",
        forecast_run_id=f"k4-{model_version}-cv",
        model_version=model_version,
        seed=C.BOOTSTRAP_SEED,
        evaluation_kind=C.CV_EVALUATION_KIND,
        evaluation_start=C.CV[0],
        evaluation_end=C.CV[1],
        target_cutoff_date=C.CV_CUTOFF,
        evaluation_as_of_time=C.EVALUATION_AS_OF,
    )


def asset_returns(prices: pd.DataFrame, asset: str, invalid) -> pd.Series:
    """Return ngày theo lịch của tài sản (vol_scaled.daily_log_returns, cùng hàm với S1a)."""
    dates, values = cc.asset_series(prices, asset)
    return daily_log_returns(pd.Series(values, index=dates), ASSETS[asset].calendar, invalid)


# ---------- ứng viên ----------


def single_forecast_seconds(r: pd.Series, asset: str, base_date, fit, expected, repeats=5):
    """Một lần dự báo FHS bằng NumPy tại base_date (đệ quy từ đầu cửa sổ fit + mô phỏng), như
    Lambda sẽ chạy; trả trung vị số giây và kiểm kết quả trùng bản chạy theo lô."""
    seconds = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        seq = r[(r.index >= fit.window_start) & (r.index <= base_date)].dropna()
        _, s2_next = variance_path(C.FHS_SCALE * seq.to_numpy(float), fit.params, fit.backcast)
        q = fhs_quantiles(
            float(s2_next[-1]),
            fit.z,
            fit.params,
            seed=seed_for(asset, pd.Timestamp(base_date).to_datetime64()),
            scale=C.FHS_SCALE,
            n_paths=C.FHS_PATHS,
            n_steps=C.FHS_STEPS,
        )
        seconds.append(time.perf_counter() - t0)
    if not np.array_equal(q, expected):
        raise StopRun(f"{asset}: single FHS forecast differs from the batch run")
    return float(np.median(seconds))


def build_cv(prices: pd.DataFrame, invalid: dict, assets=C.ASSETS) -> dict:
    """Bốn mô hình trên mọi ngày gốc 2016–2018; tập chung = q252, S1a, FHS cùng hợp lệ (mục 8).
    Phân vị mỗi mô hình qua normalize_quantiles() đúng một lần; combo lấy trung bình trước đó."""
    months = pd.date_range(*C.CV, freq="MS")
    out = {"forecasts": {m: {} for m in MODELS}, "common": {}, "fits": [], "validity": {}}
    out["seconds"] = {"fit": {}, "fhs_numpy_batch": {}, "single_forecast": {}}
    for asset in assets:
        base = calendars.sessions(ASSETS[asset].calendar, *C.CV)
        q_b, ok_b = baseline_quantiles(prices, asset, base, invalid[asset])
        q_s, ok_s, _ = s1_quantiles(prices, asset, base, C.S1A_LAMBDA, invalid[asset])
        r = asset_returns(prices, asset, invalid[asset])
        t0 = time.perf_counter()
        fits, logs = FF.monthly_fits(r, months, asset)
        out["seconds"]["fit"][asset] = time.perf_counter() - t0
        q_f, ok_f, numpy_seconds = FF.fhs_forecasts(r, asset, base, fits)
        out["seconds"]["fhs_numpy_batch"][asset] = numpy_seconds
        ok = ok_b & ok_s & ok_f
        out["validity"][asset] = {
            "origins": len(base),
            "baseline_valid": int(ok_b.sum()),
            "s1a_valid": int(ok_s.sum()),
            "fhs_valid": int(ok_f.sum()),
            "common": int(ok.sum()),
            "first_common": str(base[ok][0].date()) if ok.any() else None,
        }
        if ok.sum() != C.CV_EXPECTED_N[asset]:
            raise StopRun(f"{asset}: common origins {int(ok.sum())} != {C.CV_EXPECTED_N[asset]}")
        common = base[ok]
        raw = {
            C.BASELINE: q_b[ok],
            C.S1A: q_s[ok],
            C.FHS: q_f[ok],
            C.COMBO: (q_b[ok] + q_s[ok] + q_f[ok]) / 3.0,
        }
        for name, q in raw.items():
            normalized, crossed = normalize_quantiles(q)  # đúng một lần
            out["forecasts"][name][asset] = (common, normalized, crossed)
        out["common"][asset] = common
        out["fits"] += logs
        last = common[-1]
        out["seconds"]["single_forecast"][asset] = single_forecast_seconds(
            r, asset, last, fits[last.to_period("M").to_timestamp()], q_f[ok][-1]
        )
    return out


# ---------- chọn, MCS, độ ổn định tham số ----------


def select_candidate(scores: dict) -> dict:
    """Kế hoạch mục 4: cao nhất; chênh < TIE_TOLERANCE là hòa → fhs-gjr-t. Cả hai ≤ 0: dừng sớm."""
    best = max(scores[c] for c in C.CANDIDATES)
    tied = [c for c in C.CANDIDATES if best - scores[c] < C.TIE_TOLERANCE]
    early = all(scores[c] <= C.EARLY_STOP_AT_OR_BELOW for c in C.CANDIDATES)
    return {"selected": None if early else tied[0], "tied_with_best": tied, "early_stop": early}


def mcs_losses(detail: pd.DataFrame, asset: str) -> pd.Series:
    """Pinball trung bình 7 h × 7 τ mỗi ngày gốc (sample all), chỉ ngày gốc đủ 7 h đánh giá được."""
    d = detail[(detail.asset == asset) & detail.common_mask_all.fillna(False).astype(bool)]
    g = d.assign(loss=d.model_pinball_loss.astype(float)).groupby("base_date")["loss"]
    full = g.count() == len(HORIZONS)
    return g.mean()[full]


def run_mcs(named: dict, assets=C.ASSETS) -> dict:
    out = {}
    for asset in assets:
        series = {m: mcs_losses(named[m]["detail"], asset) for m in C.MCS_MODELS}
        index = series[C.MCS_MODELS[0]].index
        if any(not s.index.equals(index) for s in series.values()):
            raise StopRun(f"{asset}: MCS losses on different origins")
        losses = pd.DataFrame(series)
        mcs = MCS(
            losses,
            size=C.MCS_SIZE,
            reps=C.MCS_REPS,
            block_size=C.MCS_BLOCK,
            method=C.MCS_METHOD,
            bootstrap=C.MCS_BOOTSTRAP,
            seed=C.MCS_SEED,
        )
        mcs.compute()
        out[asset] = {
            "n_obs": len(losses),
            "mean_loss": {m: float(v) for m, v in losses.mean().items()},
            "included": [m for m in C.MCS_MODELS if m in set(mcs.included)],
            "excluded": [m for m in C.MCS_MODELS if m in set(mcs.excluded)],
            "pvalue": {m: float(mcs.pvalues.loc[m].iloc[0]) for m in C.MCS_MODELS},
        }
    return out


PARAMS = ("omega", "alpha", "gamma", "beta", "nu", "persistence")


def fit_summary(logs: list[dict]) -> dict:
    """Độ ổn định tham số FHS qua các lần refit, theo tài sản (mục 6)."""
    frame = pd.DataFrame(logs)
    out = {}
    for asset, g in frame.groupby("asset", sort=False):
        ok = g[g.status == "ok"]
        out[asset] = {
            "months": len(g),
            "status": g.status.value_counts().to_dict(),
            "fallback_months": [
                str(m.date())
                for m, used in zip(g.month, g.used_month, strict=True)
                if pd.notna(used) and used != m
            ],
            "with_warnings": int(
                g.warnings.map(lambda w: bool(w) if isinstance(w, list) else False).sum()
            ),
            "max_parity_rel_error": float(ok.parity_rel_error.max()),
            **{
                p: {
                    "min": float(ok[p].min()),
                    "median": float(ok[p].median()),
                    "max": float(ok[p].max()),
                }
                for p in PARAMS
            },
        }
    return out


# ---------- stage cv ----------


def provenance(prices, rejected) -> dict:
    commit, dirty = T.source_commit()
    return {
        "commit": commit,
        "commit_dirty": dirty,
        "versions": {**T.versions(), "arch": version("arch")},
        "code_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES
        },
        "data_lineage": {
            "clean_dt": C.CLEAN_DT,
            "cutoff": C.CV_CUTOFF,
            "prices_view": T.frame_lineage(prices),
            "rejected_view": T.frame_lineage(rejected) if len(rejected) else {"n_rows": 0},
        },
    }


def run_cv(lake_dir: Path, output_dir: Path, run_id: str) -> dict:
    t_start = time.perf_counter()
    if version("arch") != C.ARCH_VERSION:
        raise StopRun(f"arch {version('arch')} != pinned {C.ARCH_VERSION}")
    if list(LEVELS) != list(QUANTILE_LEVELS):
        raise StopRun("fhs_numpy.LEVELS differs from returns.QUANTILE_LEVELS")
    eval_dir = Path(output_dir) / "eval" / "k4" / run_id
    if eval_dir.exists():
        raise FileExistsError(eval_dir)
    with no_ceemdan_cache():
        prices, rejected = T.read_clean(Path(lake_dir), C.CLEAN_DT, cutoff=C.CV_CUTOFF)
        prov = provenance(prices, rejected)
        invalid = {
            a: pd.to_datetime(rejected.loc[rejected["asset"] == a, "date"]).tolist()
            for a in C.ASSETS
        }
        t = time.perf_counter()
        built = build_cv(prices, invalid)
        seconds = {"candidates": time.perf_counter() - t}
        print(json.dumps({"candidates_done": round(seconds["candidates"], 1)}))
        t = time.perf_counter()
        p, r = wf._inputs(prices, rejected, cv_config("inputs"))
        named = R3.evaluate_set(built["forecasts"], built["common"], p, r, config=cv_config)
        seconds["evaluation"] = time.perf_counter() - t
    skill = named[C.BASELINE]["accuracy"].query("metric == 'pinball_skill'")["value"]
    if skill.abs().max() > 1e-12:
        raise StopRun("anchor baseline differs from walk_forward evaluation baseline")
    groups = [(a, h) for a in C.ASSETS for h in HORIZONS]
    scores = {}
    for name, e in named.items():
        m28, by_asset = T.mean_skill(e["accuracy"])
        ci = R3.groups_skill_ci(e["detail"], groups, "all", cv_config(name))
        if not np.isclose(ci["value"], m28, atol=1e-12):
            raise StopRun(f"{name}: 28-group mean disagrees with accuracy")
        scores[name] = {
            "mean_28": m28,
            "ci_low": ci["ci_low"],
            "ci_high": ci["ci_high"],
            "by_asset": by_asset,
        }
    choice = select_candidate({c: scores[c]["mean_28"] for c in C.CANDIDATES})
    t = time.perf_counter()
    mcs = run_mcs(named)
    seconds["mcs"] = time.perf_counter() - t

    eval_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for name in MODELS:
        for asset, (base, q, crossed) in built["forecasts"][name].items():
            for i, d in enumerate(base):
                for j, h in enumerate(HORIZONS):
                    rows.append(
                        {
                            "model": name,
                            "asset": asset,
                            "base_date": d,
                            "fold": d.year,
                            "h": h,
                            **dict(zip(wf.QCOLS, q[i, j].tolist(), strict=True)),
                            "crossed_raw": bool(crossed[i, j]),
                        }
                    )
    pd.DataFrame(rows).to_parquet(eval_dir / "forecasts_cv.parquet", index=False)
    for kind in ("accuracy", "comparison", "detail", "mean7"):
        pd.concat(
            [e[kind].assign(model=name) for name, e in named.items()], ignore_index=True
        ).to_parquet(eval_dir / f"{kind}.parquet", index=False)
    fits = pd.DataFrame(built["fits"])
    fits["warnings"] = fits["warnings"].map(lambda w: "; ".join(w) if isinstance(w, list) else "")
    fits.to_parquet(eval_dir / "fhs_fits.parquet", index=False)
    seconds["total"] = time.perf_counter() - t_start
    single = built["seconds"]["single_forecast"]
    summary = {
        "run_id": run_id,
        "stage": "cv",
        "plan": PLAN,
        "look_number_if_2019_runs": C.LOOK_NUMBER,
        "total_configs_seen_on_2019_if_run": C.TOTAL_CONFIGS_SEEN,
        "provenance": prov,
        "candidates": list(C.CANDIDATES),
        "models": list(MODELS),
        "cv_period": list(C.CV),
        "cv_cutoff": C.CV_CUTOFF,
        "common_origins": {a: len(v) for a, v in built["common"].items()},
        "common_origins_by_fold": {
            a: {str(y): int((v.year == y).sum()) for y in C.CV_FOLDS}
            for a, v in built["common"].items()
        },
        "validity": built["validity"],
        "scores": scores,
        **choice,
        "mean7": {name: e["mean7"].to_dict("records") for name, e in named.items()},
        "mcs": mcs,
        "fhs_fits": fit_summary(built["fits"]),
        "seconds": {
            **seconds,
            "fhs_fit": built["seconds"]["fit"],
            "fhs_numpy_batch": built["seconds"]["fhs_numpy_batch"],
            "single_forecast": single,
            "single_forecast_4_assets": float(sum(single.values())),
        },
        "dm_blocked_groups": {
            name: [g for g in e["log"]["dm_calendar_gaps"] if g["blocked"]]
            for name, e in named.items()
        },
        "bootstrap_plan": named[C.BASELINE]["log"]["bootstrap_plan"],
    }
    (eval_dir / "summary.json").write_text(
        json.dumps(wf._plain(summary), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    (eval_dir / "summary.md").write_text(render(summary, named), encoding="utf-8")
    return summary


# ---------- stage val2019: chỉ phần chặn ----------


def val2019_gate(cv_dir: Path, candidate: str) -> dict:
    """Chỉ cho chạy 2019 khi có kết quả cv của kế hoạch này, không dừng sớm, và candidate đúng là
    ứng viên quy tắc mục 4 chọn (tính lại từ điểm đã lưu). Không đọc dữ liệu giá."""
    path = Path(cv_dir) / "summary.json"
    if not path.is_file():
        raise StopRun(f"{path}: no cv results; run --stage cv first")
    s = json.loads(path.read_text(encoding="utf-8"))
    if s.get("stage") != "cv" or s.get("plan") != PLAN:
        raise StopRun(f"{path}: not a K4 cv result")
    try:
        recomputed = select_candidate({c: s["scores"][c]["mean_28"] for c in C.CANDIDATES})
    except (KeyError, TypeError) as exc:
        raise StopRun(f"{path}: cv scores incomplete ({exc})") from exc
    if recomputed["selected"] != s.get("selected") or recomputed["early_stop"] != s.get(
        "early_stop"
    ):
        raise StopRun(f"{path}: stored selection does not follow section 4")
    if recomputed["early_stop"]:
        raise StopRun("cv early stop: both candidates have mean pinball_skill <= 0; no 2019 run")
    if candidate != recomputed["selected"]:
        raise StopRun(f"candidate {candidate!r} is not the cv selection {recomputed['selected']!r}")
    return s


def run_val2019(cv_dir: Path, candidate: str) -> dict:
    val2019_gate(cv_dir, candidate)
    raise StopRun("val2019 gate passed; the 2019 run is not implemented in this step")


# ---------- báo cáo Markdown (chỉ trình bày số đã tính) ----------


def render(summary: dict, named: dict) -> str:
    models = list(MODELS)
    out = [f"# K4 FHS GJR-GARCH và kết hợp phân vị: kiểm định chéo 2016–2018 ({summary['run_id']})"]
    look = summary["look_number_if_2019_runs"]
    seen = summary["total_configs_seen_on_2019_if_run"]
    out += [
        "",
        (
            "Ngày gốc 2016, 2017, 2018 gộp; ngày đích ≤ 2018-12-31; không đọc 2019 trở đi. Kiểm định "
            "chéo nằm trong giai đoạn train của K3. Nếu chạy 2019, đó là lần nhìn thứ "
            f"{look}, tổng {seen} cấu hình."
        ),
        "",
        "Tập ngày gốc chung (q252, S1a, FHS cùng hợp lệ): "
        + ", ".join(f"{a} {n}" for a, n in summary["common_origins"].items())
        + ". Theo fold: "
        + "; ".join(
            f"{a} " + "/".join(str(n) for n in by.values())
            for a, by in summary["common_origins_by_fold"].items()
        )
        + ".",
        "",
    ]
    if summary["early_stop"]:
        out.append("**Dừng sớm** (mục 4): cả hai ứng viên có trung bình pinball_skill ≤ 0.")
    else:
        out.append(
            f"Ứng viên được chọn (mục 4): **{summary['selected']}**; hòa với cao nhất: "
            f"{', '.join(summary['tied_with_best'])}."
        )
    out += ["", "## Trung bình pinball_skill 28 nhóm (sample all), CI 95%", ""]
    rows = [
        {
            "model": name,
            **{a: s["by_asset"][a] for a in C.ASSETS},
            "trung bình 28 nhóm": s["mean_28"],
            "CI 95%": f"[{s['ci_low']:+.4f}, {s['ci_high']:+.4f}]",
        }
        for name, s in summary["scores"].items()
    ]
    out += [T.md(pd.DataFrame(rows)), ""]
    out += ["## pinball_skill trung bình 7 h, CI 95% (dầu: all và excl_roll)", ""]
    out += [T.md(R3.mean7_table(named, models)), ""]
    out.append("## Mọi chỉ số theo tài sản × h (ADR-0008 mục 5)")
    out.append("Naive (return = 0) là mẫu số của mae_ratio_vs_naive (= 1) và không có phân vị.")
    for asset in C.ASSETS:
        out += ["", f"### {asset}", "", T.md(T.metric_table(named, models, asset))]
    out += ["", "## quantile_hit_rates", "", T.md(R3.hit_table(named, models)), ""]
    cols = ["asset", "sample", "h", "dm_stat", "p_value", "p_value_holm", "status"]
    for name in C.CANDIDATES:
        out.append(f"## DM ({name} vs baseline-252, walk_forward DM_GAP_POLICY)")
        out += [T.md(named[name]["comparison"][cols]), ""]
    out.append(
        f"## Model Confidence Set {1 - C.MCS_SIZE:.0%} (chỉ báo cáo; loss 7 h × 7 τ mỗi ngày gốc, "
        f"bootstrap {C.MCS_BOOTSTRAP} block {C.MCS_BLOCK}, {C.MCS_REPS} lần, seed {C.MCS_SEED})"
    )
    rows = [
        {
            "asset": asset,
            "n": m["n_obs"],
            **{f"loss {k}": v for k, v in m["mean_loss"].items()},
            **{f"p {k}": v for k, v in m["pvalue"].items()},
            "trong MCS": ", ".join(m["included"]),
        }
        for asset, m in summary["mcs"].items()
    ]
    out += [T.md(pd.DataFrame(rows), ".5f"), ""]
    out.append("## FHS: tham số qua các lần refit (thang return × 100)")
    rows = []
    for asset, f in summary["fhs_fits"].items():
        row = {
            "asset": asset,
            "tháng": f["months"],
            "trạng thái": ", ".join(f"{k} {v}" for k, v in f["status"].items()),
            "dùng tham số tháng trước": len(f["fallback_months"]),
        }
        for p in PARAMS:
            row[p] = f"{f[p]['min']:.3f} / {f[p]['median']:.3f} / {f[p]['max']:.3f}"
        rows.append(row)
    out += ["min / trung vị / max trên các lần fit ok.", "", T.md(pd.DataFrame(rows)), ""]
    s = summary["seconds"]
    out.append("## Thời gian (giây)")
    out.append(
        ", ".join(f"{k} {v:.1f}" for k, v in s.items() if isinstance(v, float))
        + "; một lần dự báo FHS NumPy cho 4 tài sản: "
        + f"{s['single_forecast_4_assets'] * 1000:.0f} ms"
    )
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=("cv", "val2019"), required=True)
    parser.add_argument("--lake-dir", type=Path, default=DEFAULT_LAKE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--run-id", default="k4-cv")
    parser.add_argument("--cv-dir", type=Path)
    parser.add_argument("--candidate", choices=C.CANDIDATES)
    args = parser.parse_args(argv)
    try:
        if args.stage == "val2019":
            if args.cv_dir is None or args.candidate is None:
                parser.error("--stage val2019 needs --cv-dir and --candidate")
            run_val2019(args.cv_dir, args.candidate)
            return 0
        summary = run_cv(args.lake_dir, args.output_dir, args.run_id)
    except STOPS as exc:
        print(f"DỪNG: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "selected": summary["selected"],
                "early_stop": summary["early_stop"],
                "seconds": summary["seconds"]["total"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""K4: FHS GJR-GARCH và kết hợp phân vị, kiểm định chéo 2016–2018 (docs/experiments/k4-plan.md).

Chạy từ gốc repo, bằng venv có arch 8.0.0 (requirements-dev.txt):
  python -m src.forecast.run_k4 --stage cv [--lake-dir data/lake] [--output-dir data] [--run-id k4-cv]
  python -m src.forecast.run_k4 --stage cv-dm --cv-dir data/eval/k4/k4-cv-clean [--run-id k4-cv-dm]
  python -m src.forecast.run_k4 --stage val2019 --cv-dir data/eval/k4/k4-cv-clean
      --cv-dm-dir data/eval/k4/k4-cv-dm --candidate fhs-gjr-t-dm [--k3-dir …]
      (run-id cố định k4-val2019; run-id khác hoặc đã có started.json thì từ chối)

- Stage cv: bản clean configs/k4.CLEAN_DT cắt tại 2018-12-31 ngay khi đọc; ngày gốc 2016–2018, ngày
  đích ≤ 2018-12-31 (một mốc cắt cho cả ba fold, mục 8). Bốn mô hình: baseline-q252, S1a (λ 0,94),
  fhs-gjr-t (src/forecast/fhs_fit.py + fhs_numpy.py), combo-eq3 = (q252 + S1a + FHS) / 3 trước
  normalize, rồi normalize_quantiles() đúng một lần. Tập ngày gốc chung: q252, S1a, FHS cùng hợp lệ.
  Đánh giá bằng walk_forward (cấu hình cross_validation) qua train_ceemdan.evaluate và
  run_k3b.evaluate_set; chọn theo mục 4; MCS 90% theo từng tài sản chỉ để báo cáo (mục 8).
- Stage cv-dm (mục 8, sửa đổi sau kiểm định chéo): chỉ fhs-gjr-t-dm (bootstrap từ z − mean(z)) trên
  cùng tập ngày gốc chung, cùng mốc cắt. Dựng lại fhs-gjr-t và dừng nếu không trùng từng bit với
  kết quả cv; số của các mô hình khác lấy từ thư mục cv (chỉ đọc). Thêm bảng q50 < 0 và prob_up.
- Stage val2019: phần chặn (có cv và cv-dm, cv chọn fhs-gjr-t, trung bình 28 nhóm của cv-dm > 0,
  ứng viên là fhs-gjr-t-dm, chưa có lần chạy 2019 nào), rồi một lần trên tập chung K3 (vàng 245,
  bạc 245, Brent 202, WTI 202), mốc cắt 2019-12-31, refit hằng tháng; tiêu chí mục 5 theo tài sản.
- Không đọc cache CEEMDAN (mọi hàm đọc cache bị chặn trong lúc chạy), không ghi S3, không đọc 2019
  ở stage cv và cv-dm; kết quả local <output>/eval/k4/<run_id>/.

Điều kiện dừng (StopRun hoặc FitStop, thoát mã 2): đọc được dữ liệu sau mốc cắt, tập chung khác
mục 8 hoặc khác tập K3, lần refit đầu lỗi, đệ quy NumPy lệch arch, mốc so sánh khác mốc của
walk_forward, fhs-gjr-t dựng lại khác kết quả cv, phần chặn val2019 không qua.
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
from scipy.special import xlogy
from scipy.stats import chi2

from configs import k4 as C
from src.data import calendars
from src.data.config import ASSETS
from src.eval import metrics as M
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


def configs_seen_text() -> str:
    """Tổng cấu hình đã xem trên 2019 (mục 8, 29/10 tối); None khi chưa biết số của DLinear MVP."""
    if C.TOTAL_CONFIGS_SEEN is None:
        return f"DLinear MVP (số cấu hình chưa xác định) + {C.K3_K3B_K4_CONFIGS}"
    return str(C.TOTAL_CONFIGS_SEEN)


def check_roll_calendar(config) -> None:
    """Lịch đáo hạn và ngày roll của dầu phải dựng được cho kỳ đánh giá (walk_forward trả None khi
    lỗi, khi đó excl_roll không tính được): dừng thay vì chấm thiếu."""
    cfg = config("roll-check")
    for asset in ("brent", "wti"):
        try:
            expiry, roll = wf.roll_calendar(asset, cfg)
        except (ValueError, IndexError, KeyError) as exc:
            raise StopRun(f"{asset}: roll calendar unavailable ({exc})") from exc
        inside = roll[(roll >= cfg.evaluation_start) & (roll <= cfg.evaluation_end)]
        if expiry is None or roll is None or not len(expiry) or not len(inside):
            raise StopRun(f"{asset}: roll calendar is empty for {cfg.evaluation_start[:4]}")


def check_roll_flags(named: dict) -> None:
    """Sau đánh giá: mọi dòng dầu phải có roll_in_horizon (không None)."""
    for name, e in named.items():
        d = e["detail"]
        if d.loc[d.asset.isin(["brent", "wti"]), "roll_in_horizon"].isna().any():
            raise StopRun(f"{name}: roll_in_horizon is None for oil rows")


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


def single_forecast_seconds(
    r: pd.Series, asset: str, base_date, fit, expected, repeats=5, demean=False
):
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
            demean=demean,
        )
        seconds.append(time.perf_counter() - t0)
    if not np.array_equal(q, expected):
        raise StopRun(f"{asset}: single FHS forecast differs from the batch run")
    return float(np.median(seconds))


def fhs_asset(prices: pd.DataFrame, asset: str, base, months, invalid) -> dict:
    """Return ngày, các lần refit hằng tháng và log fit của một tài sản (dùng chung cho FHS và
    bản dm: tham số, cửa sổ, z như nhau, chỉ khác bước bootstrap)."""
    r = asset_returns(prices, asset, invalid)
    t0 = time.perf_counter()
    fits, logs = FF.monthly_fits(r, months, asset)
    return {"r": r, "fits": fits, "logs": logs, "fit_seconds": time.perf_counter() - t0}


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
        f = fhs_asset(prices, asset, base, months, invalid[asset])
        r, fits, logs = f["r"], f["fits"], f["logs"]
        out["seconds"]["fit"][asset] = f["fit_seconds"]
        fhs_diag = {}
        q_f, ok_f, numpy_seconds = FF.fhs_forecasts(
            r, asset, base, fits, demean=C.FHS_DEMEAN[C.FHS], diag=fhs_diag
        )
        out["seconds"]["fhs_numpy_batch"][asset] = numpy_seconds
        ok = ok_b & ok_s & ok_f
        out["validity"][asset] = {
            "origins": len(base),
            "baseline_valid": int(ok_b.sum()),
            "s1a_valid": int(ok_s.sum()),
            "fhs_valid": int(ok_f.sum()),
            "fhs_invalid": fhs_diag,
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


def check_anchor(named: dict) -> None:
    skill = named[C.BASELINE]["accuracy"].query("metric == 'pinball_skill'")["value"]
    if skill.abs().max() > 1e-12:
        raise StopRun("anchor baseline differs from walk_forward evaluation baseline")


def run_mcs(named: dict, assets=C.ASSETS, models=C.MCS_MODELS) -> dict:
    """MCS theo tài sản trên các ngày gốc đủ 7 h ở MỌI mô hình (giao các tập); n_full_by_model và
    origins_changed cho biết tập có bị thu hẹp so với tập của từng mô hình không."""
    out = {}
    for asset in assets:
        series = {m: mcs_losses(named[m]["detail"], asset) for m in models}
        index = series[models[0]].index
        for s in series.values():
            index = index.intersection(s.index, sort=False)
        index = index.sort_values()
        changed = any(not s.index.sort_values().equals(index) for s in series.values())
        losses = pd.DataFrame({m: s.loc[index] for m, s in series.items()})
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
            "included": [m for m in models if m in set(mcs.included)],
            "excluded": [m for m in models if m in set(mcs.excluded)],
            "pvalue": {m: float(mcs.pvalues.loc[m].iloc[0]) for m in models},
            "n_full_by_model": {m: len(s) for m, s in series.items()},
            "origins_changed": bool(changed),
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
            "max_consecutive_reuse": max_consecutive_reuse(g),
            "at_persistence_bound": [
                {
                    "month": str(row.month.date()),
                    "persistence": float(row.persistence),
                    "gap": float(C.PERSISTENCE_MAX - row.persistence),
                }
                for row in ok.itertuples()
                if C.PERSISTENCE_MAX - row.persistence <= C.PERSISTENCE_TOL
            ],
            # mục 8 (30/10): α + γ ở biên 0 (cú sốc âm không làm tăng phương sai), vẫn hợp lệ
            "at_alpha_gamma_bound": [
                {"month": str(row.month.date()), "alpha_plus_gamma": float(row.alpha + row.gamma)}
                for row in ok.itertuples()
                if row.alpha + row.gamma <= C.NONNEG_TOL
            ],
        }
    return out


def max_consecutive_reuse(g: pd.DataFrame) -> int:
    """Số tháng liên tiếp lớn nhất dùng lại tham số của một tháng trước (fit lỗi/không hội tụ)."""
    best = run = 0
    for month, used in zip(g.month, g.used_month, strict=True):
        run = run + 1 if pd.notna(used) and used != month else 0
        best = max(best, run)
    return best


# ---------- báo cáo bổ sung (mục 8, 29/10 tối; chỉ báo cáo, không đổi chọn hay tiêu chí) ----------


def samples_of(asset: str) -> tuple[str, ...]:
    return ("all", "excl_roll") if asset in ("brent", "wti") else ("all",)


def scored(detail: pd.DataFrame, asset: str, h: int, sample: str) -> pd.DataFrame:
    """Các dòng được chấm của (asset, h) theo mask của sample, xếp theo ngày gốc."""
    rows = detail.loc[(detail.asset == asset) & (detail.h == h)].sort_values("base_date")
    return rows.loc[rows["common_mask_" + sample].fillna(False).to_numpy(bool)]


def _skill(g: pd.DataFrame) -> float:
    if not len(g):
        return float("nan")
    return M.pinball_skill(
        g.y_true.to_numpy(float),
        g[list(wf.QCOLS)].to_numpy(float),
        g[list(wf.BCOLS)].to_numpy(float),
    )


def valid_counts(detail: pd.DataFrame) -> pd.DataFrame:
    """Số ngày gốc được chấm theo tài sản × h (all, excl_roll cho dầu)."""
    rows = []
    for asset in C.ASSETS:
        for h in HORIZONS:
            row = {"asset": asset, "h": h}
            for sample in samples_of(asset):
                row[f"n_{sample}"] = len(scored(detail, asset, h, sample))
            rows.append(row)
    return pd.DataFrame(rows)


def fold_table(named: dict, models) -> pd.DataFrame:
    """pinball_skill trung bình 7 h theo năm của ngày gốc (fold), mô hình × tài sản × sample."""
    rows = []
    for name in models:
        d = named[name]["detail"]
        years = sorted({str(x)[:4] for x in d.base_date})
        for asset in C.ASSETS:
            for sample in samples_of(asset):
                for year in years:
                    by_h, n = [], []
                    for h in HORIZONS:
                        g = scored(d, asset, h, sample)
                        g = g[g.base_date.astype(str).str[:4] == year]
                        by_h.append(_skill(g))
                        n.append(len(g))
                    if not sum(n):
                        continue
                    rows.append(
                        {
                            "model": name,
                            "asset": asset,
                            "sample": sample,
                            "fold": int(year),
                            "pinball_skill trung bình 7 h": float(np.mean(by_h)),
                            "n min": min(n),
                            "n max": max(n),
                        }
                    )
    return pd.DataFrame(rows)


def bootstrap_dates(cfg) -> pd.DatetimeIndex:
    """Lịch hợp nhất NYSE/CME của kỳ đánh giá, như walk_forward.shared_bootstrap_plan."""
    return (
        calendars.sessions("NYSE", cfg.evaluation_start, cfg.evaluation_end)
        .union(calendars.sessions("CME", cfg.evaluation_start, cfg.evaluation_end))
        .sort_values()
    )


def skill_bootstrap(detail: pd.DataFrame, groups, sample: str, cfg, block_length: int) -> dict:
    """Như run_k3b.groups_skill_ci nhưng nhận block length và trả thêm p một phía
    (1 + #lần ≤ 0) / (B + 1). Block 20 cho đúng CI của groups_skill_ci (có test)."""
    dates = bootstrap_dates(cfg)
    parts = []
    for asset, h in groups:
        g = scored(detail, asset, h, sample)
        parts.append(
            (
                pd.Index(pd.to_datetime(g.base_date)).get_indexer(dates),
                g.y_true.to_numpy(float),
                g[list(wf.QCOLS)].to_numpy(float),
                g[list(wf.BCOLS)].to_numpy(float),
            )
        )
    values = []

    def statistic(sampled):
        index = sampled.astype(int)
        skills = []
        for lookup, y, q, b in parts:
            take = lookup[index]
            take = take[take >= 0]
            skills.append(M.pinball_skill(y[take], q[take], b[take]) if len(take) else np.nan)
        values.append(float(np.mean(skills)))
        return values[-1]

    low, high = M.block_bootstrap_ci(
        np.arange(len(dates), dtype=float),
        statistic,
        block_length=block_length,
        n_resamples=cfg.n_bootstrap,
        confidence_level=cfg.confidence_level,
        seed=cfg.seed,
    )
    reps = np.asarray(values)
    return {
        "value": float(np.mean([M.pinball_skill(y, q, b) for _, y, q, b in parts])),
        "ci_low": low,
        "ci_high": high,
        "p_one_sided": float((1 + np.sum(reps <= 0)) / (len(reps) + 1)),
        "block": block_length,
    }


def ci_sensitivity(named: dict, models, config) -> pd.DataFrame:
    """CI 95% của pinball_skill trung bình 7 h (theo tài sản × sample) và 28 nhóm theo block."""
    rows = []
    for name in models:
        d, cfg = named[name]["detail"], config(name)
        targets = [("28 nhóm", "all", [(a, h) for a in C.ASSETS for h in HORIZONS])]
        targets += [
            (asset, sample, [(asset, h) for h in HORIZONS])
            for asset in C.ASSETS
            for sample in samples_of(asset)
        ]
        for label, sample, groups in targets:
            for block in C.CI_BLOCKS:
                r = skill_bootstrap(d, groups, sample, cfg, block)
                rows.append({"model": name, "asset": label, "sample": sample, **r})
    return pd.DataFrame(rows)


def holm_table(sensitivity: pd.DataFrame, model: str) -> pd.DataFrame:
    """Kiểm định mục 5 với Holm qua 4 tài sản (sample all, block 20); excl_roll chỉ báo p riêng."""
    s = sensitivity[
        (sensitivity.model == model) & (sensitivity.block == 20) & (sensitivity.asset != "28 nhóm")
    ]
    main = s[s["sample"] == "all"].reset_index(drop=True)
    adjusted = M.holm_adjust(main.p_one_sided.to_numpy(float))
    out = main[["asset", "sample", "value", "ci_low", "p_one_sided"]].assign(
        p_holm=adjusted,
        ci_low_gt_0=main.ci_low > 0,
        holm_pass=adjusted < C.HOLM_ALPHA,
    )
    extra = s[s["sample"] == "excl_roll"][["asset", "sample", "value", "ci_low", "p_one_sided"]]
    return pd.concat([out, extra.assign(ci_low_gt_0=extra.ci_low > 0)], ignore_index=True)


def christoffersen_independence(hits) -> tuple[float, float]:
    """LR độc lập của Christoffersen (1998) trên chuỗi vượt khoảng 0/1 (Markov bậc 1): (LR, p)."""
    h = np.asarray(hits, dtype=int)
    a, b = h[:-1], h[1:]
    n00, n01 = int(np.sum((a == 0) & (b == 0))), int(np.sum((a == 0) & (b == 1)))
    n10, n11 = int(np.sum((a == 1) & (b == 0))), int(np.sum((a == 1) & (b == 1)))
    if n01 + n11 == 0 or n00 + n10 == 0:
        return float("nan"), float("nan")
    pi0 = n01 / (n00 + n01) if n00 + n01 else 0.0
    pi1 = n11 / (n10 + n11) if n10 + n11 else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    ll0 = xlogy(n00 + n10, 1 - pi) + xlogy(n01 + n11, pi)
    ll1 = xlogy(n00, 1 - pi0) + xlogy(n01, pi0) + xlogy(n10, 1 - pi1) + xlogy(n11, pi1)
    lr = float(max(-2.0 * (ll0 - ll1), 0.0))
    return lr, float(chi2.sf(lr, 1))


def christoffersen_table(named: dict, models) -> pd.DataFrame:
    """Vượt khoảng 80% [q10, q90] theo mô hình × tài sản × h (sample all), chuỗi các ngày gốc được
    chấm theo thứ tự. Với h > 1 các return chồng nhau nên các lần vượt phụ thuộc sẵn."""
    rows = []
    for name in models:
        d = named[name]["detail"]
        for asset in C.ASSETS:
            for h in HORIZONS:
                g = scored(d, asset, h, "all")
                y = g.y_true.to_numpy(float)
                hits = (y < g.q10.to_numpy(float)) | (y > g.q90.to_numpy(float))
                lr, p = christoffersen_independence(hits)
                rows.append(
                    {
                        "model": name,
                        "asset": asset,
                        "h": h,
                        "n": len(g),
                        "tỷ lệ vượt": float(np.mean(hits)) if len(hits) else float("nan"),
                        "LR_ind": lr,
                        "p": p,
                    }
                )
    return pd.DataFrame(rows)


def skill_on_mask(detail: pd.DataFrame, forecasts: dict, sample: str = "all") -> dict:
    """pinball_skill theo (asset, h) của các phân vị `forecasts` trên đúng các dòng, y và mốc mà
    detail đã chấm (không gọi lại walk_forward)."""
    out = {}
    for asset in (a for a in C.ASSETS if a in forecasts):
        if sample not in samples_of(asset):
            continue
        base, q, _ = forecasts[asset]
        pos = {str(pd.Timestamp(d).date()): i for i, d in enumerate(base)}
        for h in HORIZONS:
            g = scored(detail, asset, h, sample)
            idx = np.array([pos[str(x)[:10]] for x in g.base_date], dtype=int)
            out[(asset, h)] = M.pinball_skill(
                g.y_true.to_numpy(float), q[idx, h - 1], g[list(wf.BCOLS)].to_numpy(float)
            )
    return out


def skill_summary(skills: dict) -> dict:
    """Trung bình 28 nhóm (nếu đủ) và trung bình 7 h theo tài sản."""
    by_asset = {a: float(np.mean([skills[(a, h)] for h in HORIZONS])) for a, _ in skills}
    out = {"by_asset": by_asset}
    if len(skills) == len(C.ASSETS) * len(HORIZONS):
        out["mean_28"] = float(np.mean(list(skills.values())))
    return out


def dm_robustness(detail: pd.DataFrame, inputs: dict) -> pd.DataFrame:
    """Bản dm với 2 seed khác và 10000 đường trên cùng ngày gốc và cùng mask (chỉ kiểm độ bền)."""
    variants = [("đã chốt", 0, C.FHS_PATHS)]
    variants += [(f"seed + {o}", o, C.FHS_PATHS) for o in C.DM_ROBUST_SEED_OFFSETS]
    variants += [(f"{C.DM_ROBUST_PATHS} đường", 0, C.DM_ROBUST_PATHS)]
    rows = []
    for label, offset, paths in variants:
        forecasts = {}
        for asset, (r, fits, base) in inputs.items():
            q, ok, _ = FF.fhs_forecasts(
                r, asset, base, fits, demean=True, seed_offset=offset, n_paths=paths
            )
            if not ok.all():
                raise StopRun(f"{asset}: robustness variant {label} invalid on common origins")
            forecasts[asset] = (base, *normalize_quantiles(q))
        skills = skill_summary(skill_on_mask(detail, forecasts))
        oil = skill_summary(skill_on_mask(detail, forecasts, "excl_roll"))["by_asset"]
        rows.append(
            {
                "biến thể": label,
                "trung bình 28 nhóm": skills.get("mean_28", float("nan")),
                **skills["by_asset"],
                **{f"{a} excl_roll": v for a, v in oil.items()},
            }
        )
    return pd.DataFrame(rows)


def dm_vs_fhs(detail_dm: pd.DataFrame, detail_fhs: pd.DataFrame) -> pd.DataFrame:
    """pinball_skill của fhs-gjr-t-dm trừ fhs-gjr-t trên cùng common mask (cùng ngày gốc, h)."""
    rows = []
    for asset in C.ASSETS:
        for sample in samples_of(asset):
            for h in HORIZONS:
                a, b = scored(detail_dm, asset, h, sample), scored(detail_fhs, asset, h, sample)
                if list(a.base_date.astype(str)) != list(b.base_date.astype(str)):
                    raise StopRun(f"{asset} h{h} {sample}: dm and fhs masks differ")
                sa, sb = _skill(a), _skill(b)
                rows.append(
                    {
                        "asset": asset,
                        "sample": sample,
                        "h": h,
                        "n": len(a),
                        C.FHS_DM: sa,
                        C.FHS: sb,
                        "chênh lệch": sa - sb,
                    }
                )
    return pd.DataFrame(rows)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finalize(eval_dir: Path, summary: dict, markdown: str) -> None:
    """Ghi summary.md, rồi summary.json kèm SHA-256 của mọi file kết quả khác trong thư mục."""
    (eval_dir / "summary.md").write_text(markdown, encoding="utf-8")
    summary["file_sha256"] = {
        p.name: file_sha256(p)
        for p in sorted(eval_dir.iterdir())
        if p.is_file() and p.name != "summary.json"
    }
    (eval_dir / "summary.json").write_text(
        json.dumps(wf._plain(summary), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )


def records(frame: pd.DataFrame) -> list[dict]:
    return frame.to_dict("records")


# ---------- stage cv ----------


def code_fingerprint() -> dict:
    """SHA-256 của config và code dùng cho K4 (CODE_FILES)."""
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES}


def environment_versions() -> dict:
    return {**T.versions(), "arch": version("arch")}


def data_lineage(prices, rejected, cutoff: str) -> dict:
    return {
        "clean_dt": C.CLEAN_DT,
        "cutoff": cutoff,
        "prices_view": T.frame_lineage(prices),
        "rejected_view": T.frame_lineage(rejected) if len(rejected) else {"n_rows": 0},
    }


def provenance(prices, rejected, cutoff: str = C.CV_CUTOFF) -> dict:
    commit, dirty = T.source_commit()
    return {
        "commit": commit,
        "commit_dirty": dirty,
        "versions": environment_versions(),
        "code_sha256": code_fingerprint(),
        "data_lineage": data_lineage(prices, rejected, cutoff),
    }


def check_environment(output_dir: Path, run_id: str) -> Path:
    if version("arch") != C.ARCH_VERSION:
        raise StopRun(f"arch {version('arch')} != pinned {C.ARCH_VERSION}")
    if list(LEVELS) != list(QUANTILE_LEVELS):
        raise StopRun("fhs_numpy.LEVELS differs from returns.QUANTILE_LEVELS")
    eval_dir = Path(output_dir) / "eval" / "k4" / run_id
    if eval_dir.exists():
        raise FileExistsError(eval_dir)
    return eval_dir


def score(named: dict, config) -> dict:
    """Trung bình pinball_skill 28 nhóm (sample all) kèm CI 95% chung kế hoạch bootstrap, và theo
    tài sản, cho mỗi mô hình đã đánh giá."""
    groups = [(a, h) for a in C.ASSETS for h in HORIZONS]
    scores = {}
    for name, e in named.items():
        m28, by_asset = T.mean_skill(e["accuracy"])
        ci = R3.groups_skill_ci(e["detail"], groups, "all", config(name))
        if not np.isclose(ci["value"], m28, atol=1e-12):
            raise StopRun(f"{name}: 28-group mean disagrees with accuracy")
        scores[name] = {
            "mean_28": m28,
            "ci_low": ci["ci_low"],
            "ci_high": ci["ci_high"],
            "by_asset": by_asset,
        }
    return scores


def write_frames(eval_dir: Path, named: dict) -> None:
    for kind in ("accuracy", "comparison", "detail", "mean7"):
        pd.concat(
            [e[kind].assign(model=name) for name, e in named.items()], ignore_index=True
        ).to_parquet(eval_dir / f"{kind}.parquet", index=False)


def write_fits(eval_dir: Path, logs: list[dict]) -> pd.DataFrame:
    fits = pd.DataFrame(logs)
    fits["warnings"] = fits["warnings"].map(lambda w: "; ".join(w) if isinstance(w, list) else "")
    fits.to_parquet(eval_dir / "fhs_fits.parquet", index=False)
    return fits


def forecast_rows(forecasts: dict, models) -> pd.DataFrame:
    rows = []
    for name in models:
        for asset, (base, q, crossed) in forecasts[name].items():
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
    return pd.DataFrame(rows)


def run_cv(lake_dir: Path, output_dir: Path, run_id: str) -> dict:
    t_start = time.perf_counter()
    eval_dir = check_environment(output_dir, run_id)
    check_roll_calendar(cv_config)
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
    check_anchor(named)
    check_roll_flags(named)
    scores = score(named, cv_config)
    choice = select_candidate({c: scores[c]["mean_28"] for c in C.CANDIDATES})
    t = time.perf_counter()
    mcs = run_mcs(named)
    seconds["mcs"] = time.perf_counter() - t
    t = time.perf_counter()
    sensitivity = ci_sensitivity(named, C.CANDIDATES, cv_config)
    supplementary = {
        "folds": records(fold_table(named, MODELS)),
        "valid_counts": records(valid_counts(named[C.FHS]["detail"])),
        "ci_blocks": records(sensitivity),
        "holm": {c: records(holm_table(sensitivity, c)) for c in C.CANDIDATES},
        "christoffersen": records(christoffersen_table(named, MODELS)),
    }
    seconds["supplementary"] = time.perf_counter() - t

    eval_dir.mkdir(parents=True, exist_ok=False)
    forecast_rows(built["forecasts"], MODELS).to_parquet(
        eval_dir / "forecasts_cv.parquet", index=False
    )
    write_frames(eval_dir, named)
    write_fits(eval_dir, built["fits"])
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
        "supplementary": supplementary,
    }
    finalize(eval_dir, summary, render(summary, named))
    return summary


# ---------- stage cv-dm (mục 8, sửa đổi sau kiểm định chéo) ----------


def read_summary(directory: Path, stage: str) -> dict:
    path = Path(directory) / "summary.json"
    if not path.is_file():
        raise StopRun(f"{path}: no {stage} results; run --stage {stage} first")
    s = json.loads(path.read_text(encoding="utf-8"))
    if s.get("stage") != stage or s.get("plan") != PLAN:
        raise StopRun(f"{path}: not a K4 {stage} result")
    return s


def _ns(index) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index).astype("datetime64[ns]")


def cv_reference(cv_dir: Path) -> dict:
    """Kết quả stage cv đã lưu (chỉ đọc): summary, forecasts {model: {asset: (base, q, crossed)}},
    accuracy/mean7/detail/comparison theo mô hình và log fit."""
    cv_dir = Path(cv_dir)
    s = read_summary(cv_dir, "cv")
    forecasts = {}
    f = pd.read_parquet(cv_dir / "forecasts_cv.parquet")
    for (name, asset), g in f.groupby(["model", "asset"], sort=False):
        g = g.sort_values(["base_date", "h"])
        base = _ns(g["base_date"].unique())
        if list(g["h"]) != list(HORIZONS) * len(base):
            raise StopRun(f"{cv_dir}: {name} {asset} incomplete horizons")
        q = g[list(wf.QCOLS)].to_numpy(float).reshape(len(base), len(HORIZONS), -1)
        crossed = g["crossed_raw"].to_numpy(bool).reshape(len(base), len(HORIZONS))
        forecasts.setdefault(name, {})[asset] = (base, q, crossed)
    frames = {
        kind: pd.read_parquet(cv_dir / f"{kind}.parquet")
        for kind in ("accuracy", "comparison", "detail", "mean7")
    }
    named = {
        name: {
            kind: frame[frame["model"] == name].drop(columns="model").reset_index(drop=True)
            for kind, frame in frames.items()
        }
        for name in s["models"]
    }
    fits = pd.read_parquet(cv_dir / "fhs_fits.parquet")
    return {"summary": s, "forecasts": forecasts, "named": named, "fits": fits}


def same_fits(logs: list[dict], reference: pd.DataFrame, asset: str) -> bool:
    """Tham số các lần refit trùng từng bit với log fit của stage cv."""
    cols = ["month", "status", "omega", "alpha", "gamma", "beta", "nu"]
    new = pd.DataFrame(logs).reindex(columns=cols).reset_index(drop=True)
    old = reference[reference.asset == asset].reindex(columns=cols).reset_index(drop=True)
    new["month"], old["month"] = _ns(new["month"]), _ns(old["month"])
    return new.equals(old)


def build_cv_dm(prices: pd.DataFrame, invalid: dict, reference: dict, assets=C.ASSETS) -> dict:
    """fhs-gjr-t-dm trên tập ngày gốc chung của cv. Cùng các lần fit với fhs-gjr-t; dựng lại
    fhs-gjr-t (demean=False) và dừng nếu khác kết quả cv từng bit, hoặc tập chung khác cv."""
    months = pd.date_range(*C.CV, freq="MS")
    out = {"forecasts": {C.FHS_DM: {}}, "common": {}, "fits": [], "validity": {}, "inputs": {}}
    out["seconds"] = {"fit": {}, "fhs_numpy_batch": {}, "single_forecast": {}}
    for asset in assets:
        base = calendars.sessions(ASSETS[asset].calendar, *C.CV)
        _, ok_b = baseline_quantiles(prices, asset, base, invalid[asset])
        _, ok_s, _ = s1_quantiles(prices, asset, base, C.S1A_LAMBDA, invalid[asset])
        f = fhs_asset(prices, asset, base, months, invalid[asset])
        r, fits = f["r"], f["fits"]
        if not same_fits(f["logs"], reference["fits"], asset):
            raise StopRun(f"{asset}: refits differ from the cv run")
        q_f, ok_f, _ = FF.fhs_forecasts(r, asset, base, fits, demean=C.FHS_DEMEAN[C.FHS])
        dm_diag = {}
        q_d, ok_d, numpy_seconds = FF.fhs_forecasts(
            r, asset, base, fits, demean=C.FHS_DEMEAN[C.FHS_DM], diag=dm_diag
        )
        ok = ok_b & ok_s & ok_d
        if not np.array_equal(ok_d, ok_f) or ok.sum() != C.CV_EXPECTED_N[asset]:
            raise StopRun(f"{asset}: common origins {int(ok.sum())} != {C.CV_EXPECTED_N[asset]}")
        common = _ns(base[ok])
        ref_base, ref_q, ref_crossed = reference["forecasts"][C.FHS][asset]
        if not common.equals(_ns(ref_base)):
            raise StopRun(f"{asset}: common origins differ from the cv run")
        q_check, crossed_check = normalize_quantiles(q_f[ok])
        if not (np.array_equal(q_check, ref_q) and np.array_equal(crossed_check, ref_crossed)):
            raise StopRun(f"{asset}: {C.FHS} rebuilt here differs from the cv run")
        normalized, crossed = normalize_quantiles(q_d[ok])  # đúng một lần
        out["forecasts"][C.FHS_DM][asset] = (common, normalized, crossed)
        out["common"][asset] = common
        out["fits"] += f["logs"]
        out["inputs"][asset] = (r, fits, common)
        out["validity"][asset] = {
            "origins": len(base),
            "common": int(ok.sum()),
            "fhs_dm_invalid": dm_diag,
        }
        out["seconds"]["fit"][asset] = f["fit_seconds"]
        out["seconds"]["fhs_numpy_batch"][asset] = numpy_seconds
        last = common[-1]
        out["seconds"]["single_forecast"][asset] = single_forecast_seconds(
            r, asset, last, fits[last.to_period("M").to_timestamp()], normalized[-1], demean=True
        )
    return out


def same_scoring_inputs(new: pd.DataFrame, old: pd.DataFrame) -> bool:
    """Detail của bản dm và của fhs-gjr-t ở stage cv có cùng y, cùng mốc và cùng mask chấm."""
    cols = ["asset", "base_date", "h", "target_date"]
    a, b = (
        new.sort_values(cols).reset_index(drop=True),
        old.sort_values(cols).reset_index(drop=True),
    )
    if not a[cols].astype(str).equals(b[cols].astype(str)):
        return False
    for col in ("y_true", *wf.BCOLS):
        if not np.array_equal(a[col].to_numpy(float), b[col].to_numpy(float), equal_nan=True):
            return False
    masks = ("common_mask_all", "common_mask_excl_roll")
    return all(
        np.array_equal(a[m].fillna(False).to_numpy(bool), b[m].fillna(False).to_numpy(bool))
        for m in masks
    )


def direction_table(named: dict, models) -> pd.DataFrame:
    """Theo mô hình × tài sản × h, trên các dòng được chấm (common_mask_all): tỷ lệ q50 < 0, trung
    vị và trung bình q50 (bp), tỷ lệ prob_up < 0,5, prob_up trung bình, sign_accuracy, up_rate."""
    rows = []
    for name in models:
        d = named[name]["detail"]
        d = d[d.common_mask_all.fillna(False).astype(bool)]
        for (asset, h), g in d.groupby(["asset", "h"], sort=False):
            y, q50 = g.y_true.to_numpy(float), g.q50.to_numpy(float)
            pu = g.prob_up.to_numpy(float)
            rows.append(
                {
                    "model": name,
                    "asset": asset,
                    "h": int(h),
                    "n": len(g),
                    "up_rate": M.up_rate(y),
                    "q50<0": float(np.mean(q50 < 0)),
                    "q50 trung vị (bp)": float(np.median(q50) * 1e4),
                    "q50 trung bình (bp)": float(np.mean(q50) * 1e4),
                    "prob_up<0,5": float(np.mean(pu < 0.5)),
                    "prob_up trung bình": float(np.mean(pu)),
                    "sign_accuracy": M.sign_accuracy(y, q50),
                }
            )
    return pd.DataFrame(rows)


DECISION_ORDER = (
    "1. cv: chọn fhs-gjr-t theo mục 4 (không dừng sớm).",
    "2. Chẩn đoán trên k4-cv-clean: z bootstrap không trừ trung bình nên FHS trôi âm.",
    (
        "3. Mục 8, sửa đổi 29/10 sau kiểm định chéo: ứng viên 2019 là fhs-gjr-t-dm; quy tắc chốt "
        "trước khi xem số: trung bình 28 nhóm của cv-dm > 0 thì chạy 2019 một lần, ≤ 0 thì dừng."
    ),
    "4. cv-dm: kiểm định chéo một lần cho fhs-gjr-t-dm.",
    "5. val2019: một lần, chỉ fhs-gjr-t-dm, nếu bước 4 > 0.",
)


def run_cv_dm(lake_dir: Path, output_dir: Path, run_id: str, cv_dir: Path) -> dict:
    t_start = time.perf_counter()
    eval_dir = check_environment(output_dir, run_id)
    check_roll_calendar(cv_config)
    reference = cv_reference(cv_dir)
    ref = reference["summary"]
    with no_ceemdan_cache():
        prices, rejected = T.read_clean(Path(lake_dir), C.CLEAN_DT, cutoff=C.CV_CUTOFF)
        prov = provenance(prices, rejected)
        if prov["data_lineage"] != ref["provenance"]["data_lineage"]:
            raise StopRun("clean data differs from the cv run")
        invalid = {
            a: pd.to_datetime(rejected.loc[rejected["asset"] == a, "date"]).tolist()
            for a in C.ASSETS
        }
        t = time.perf_counter()
        built = build_cv_dm(prices, invalid, reference)
        seconds = {"candidates": time.perf_counter() - t}
        print(json.dumps({"candidates_done": round(seconds["candidates"], 1)}))
        t = time.perf_counter()
        p, r = wf._inputs(prices, rejected, cv_config("inputs"))
        named = R3.evaluate_set(built["forecasts"], built["common"], p, r, config=cv_config)
        seconds["evaluation"] = time.perf_counter() - t
    if not same_scoring_inputs(named[C.FHS_DM]["detail"], reference["named"][C.FHS]["detail"]):
        raise StopRun("targets, baseline or scoring masks differ from the cv run")
    check_roll_flags(named)
    scores = score(named, cv_config)
    m28 = scores[C.FHS_DM]["mean_28"]
    proceed = bool(m28 > C.CV_DM_PROCEED_ABOVE)
    report = {**reference["named"], **named}
    t = time.perf_counter()
    mcs = run_mcs(report, models=(*C.MCS_MODELS, C.FHS_DM))
    seconds["mcs"] = time.perf_counter() - t
    direction = direction_table(report, (C.BASELINE, C.FHS, C.FHS_DM))
    t = time.perf_counter()
    dm_detail = named[C.FHS_DM]["detail"]
    sensitivity = ci_sensitivity(named, (C.FHS_DM,), cv_config)
    supplementary = {
        "folds": records(fold_table(report, (C.FHS, C.FHS_DM))),
        "valid_counts": records(valid_counts(dm_detail)),
        "ci_blocks": records(sensitivity),
        "holm": {C.FHS_DM: records(holm_table(sensitivity, C.FHS_DM))},
        "christoffersen": records(christoffersen_table(report, (C.FHS, C.FHS_DM))),
        "dm_robustness": records(dm_robustness(dm_detail, built["inputs"])),
        "dm_minus_fhs": records(dm_vs_fhs(dm_detail, reference["named"][C.FHS]["detail"])),
    }
    seconds["supplementary"] = time.perf_counter() - t

    eval_dir.mkdir(parents=True, exist_ok=False)
    forecast_rows(built["forecasts"], (C.FHS_DM,)).to_parquet(
        eval_dir / "forecasts_cv_dm.parquet", index=False
    )
    write_frames(eval_dir, named)
    write_fits(eval_dir, built["fits"])
    direction.to_parquet(eval_dir / "direction.parquet", index=False)
    seconds["total"] = time.perf_counter() - t_start
    single = built["seconds"]["single_forecast"]
    summary = {
        "run_id": run_id,
        "stage": "cv-dm",
        "plan": PLAN,
        "model": C.FHS_DM,
        "provenance": prov,
        "cv_reference": {
            "dir": str(cv_dir),
            "run_id": ref["run_id"],
            "commit": ref["provenance"]["commit"],
            "commit_dirty": ref["provenance"]["commit_dirty"],
            "selected": ref["selected"],
        },
        "fhs_rebuilt_identical": True,
        "cv_configs_seen": C.CV_CONFIGS_SEEN,
        "look_number_if_2019_runs": C.LOOK_NUMBER,
        "total_configs_seen_on_2019_if_run": C.TOTAL_CONFIGS_SEEN,
        "decision_order": list(DECISION_ORDER),
        "common_origins": {a: len(v) for a, v in built["common"].items()},
        "validity": built["validity"],
        "scores": {C.FHS_DM: scores[C.FHS_DM]},
        "reference_scores": ref["scores"],
        "proceed_rule": f"mean_28 > {C.CV_DM_PROCEED_ABOVE}",
        "proceed_to_2019": proceed,
        "mean7": named[C.FHS_DM]["mean7"].to_dict("records"),
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
            C.FHS_DM: [g for g in named[C.FHS_DM]["log"]["dm_calendar_gaps"] if g["blocked"]]
        },
        "bootstrap_plan": named[C.FHS_DM]["log"]["bootstrap_plan"],
        "supplementary": supplementary,
    }
    finalize(eval_dir, summary, render_cv_dm(summary, report, direction))
    return summary


# ---------- stage val2019 ----------


RESULT_FILES = {
    "cv": (
        "forecasts_cv.parquet",
        "accuracy.parquet",
        "comparison.parquet",
        "detail.parquet",
        "mean7.parquet",
        "fhs_fits.parquet",
        "summary.md",
    ),
    "cv-dm": (
        "forecasts_cv_dm.parquet",
        "accuracy.parquet",
        "comparison.parquet",
        "detail.parquet",
        "mean7.parquet",
        "fhs_fits.parquet",
        "direction.parquet",
        "summary.md",
    ),
}


def verified_result(directory: Path, stage: str) -> dict:
    """Mục 8 (29/10 tối): chỉ nhận kết quả chạy từ code đã commit (commit_dirty = False), cùng
    fingerprint config/code và phiên bản thư viện với code hiện tại, và mọi file kết quả khớp
    SHA-256 đã ghi trong summary."""
    s = read_summary(directory, stage)
    prov = s.get("provenance") or {}
    if not prov.get("commit") or prov.get("commit_dirty") is not False:
        raise StopRun(f"{directory}: {stage} result was not run from committed code")
    if prov.get("code_sha256") != code_fingerprint():
        raise StopRun(f"{directory}: config/code fingerprint differs from the current code")
    if prov.get("versions") != environment_versions():
        raise StopRun(f"{directory}: library versions differ from the current environment")
    hashes = s.get("file_sha256") or {}
    missing = [name for name in RESULT_FILES[stage] if name not in hashes]
    if missing:
        raise StopRun(f"{directory}: no checksum for {', '.join(missing)}")
    for name, digest in hashes.items():
        path = Path(directory) / name
        if not path.is_file() or file_sha256(path) != digest:
            raise StopRun(f"{directory}: checksum mismatch for {name}")
    return s


def val2019_gate(cv_dir: Path, cv_dm_dir: Path, candidate: str) -> dict:
    """Mục 8, sửa đổi sau kiểm định chéo: chỉ fhs-gjr-t-dm; cần kết quả cv (quy tắc mục 4 tính lại
    từ điểm đã lưu chọn fhs-gjr-t, không dừng sớm) và cv-dm chạy trên đúng kết quả cv đó, với
    trung bình 28 nhóm > 0 (tính lại từ điểm đã lưu). Cả hai kết quả phải qua verified_result và
    cùng fingerprint dữ liệu. Không đọc dữ liệu giá (fingerprint dữ liệu kiểm ở run_val2019)."""
    if candidate != C.VAL2019_CANDIDATE:
        raise StopRun(f"only {C.VAL2019_CANDIDATE} may run on 2019 (plan section 8)")
    cv = verified_result(cv_dir, "cv")
    try:
        recomputed = select_candidate({c: cv["scores"][c]["mean_28"] for c in C.CANDIDATES})
    except (KeyError, TypeError) as exc:
        raise StopRun(f"{cv_dir}: cv scores incomplete ({exc})") from exc
    if recomputed["selected"] != cv.get("selected") or recomputed["early_stop"] != cv.get(
        "early_stop"
    ):
        raise StopRun(f"{cv_dir}: stored selection does not follow section 4")
    if recomputed["early_stop"]:
        raise StopRun("cv early stop: both candidates have mean pinball_skill <= 0; no 2019 run")
    if recomputed["selected"] != C.FHS:
        raise StopRun(
            f"cv selected {recomputed['selected']!r}; the dm amendment applies to {C.FHS}"
        )
    dm = verified_result(cv_dm_dir, "cv-dm")
    if dm["provenance"].get("data_lineage") != cv["provenance"].get("data_lineage"):
        raise StopRun(f"{cv_dm_dir}: data fingerprint differs from the cv result")
    link = dm.get("cv_reference") or {}
    if dm.get("model") != C.FHS_DM or (link.get("run_id"), link.get("commit")) != (
        cv.get("run_id"),
        (cv.get("provenance") or {}).get("commit"),
    ):
        raise StopRun(f"{cv_dm_dir}: cv-dm was not run on this cv result")
    try:
        m28 = float(dm["scores"][C.FHS_DM]["mean_28"])
    except (KeyError, TypeError, ValueError) as exc:
        raise StopRun(f"{cv_dm_dir}: cv-dm score missing ({exc})") from exc
    proceed = bool(m28 > C.CV_DM_PROCEED_ABOVE)
    if dm.get("proceed_to_2019") is not proceed:
        raise StopRun(f"{cv_dm_dir}: stored decision does not follow section 8")
    if not proceed:
        raise StopRun(f"cv-dm mean pinball_skill {m28:+.4f} <= 0: stop, no 2019 run")
    return {"cv": cv, "cv_dm": dm}


def val_config(model_version: str) -> wf.EvaluationConfig:
    return wf.EvaluationConfig(
        run_id=f"k4-{model_version}",
        forecast_run_id=f"k4-{model_version}-val2019",
        model_version=model_version,
        seed=C.BOOTSTRAP_SEED,
        evaluation_as_of_time=C.EVALUATION_AS_OF,
    )


def build_val(prices: pd.DataFrame, invalid: dict, origins: dict, assets=C.ASSETS) -> dict:
    """fhs-gjr-t-dm, baseline-q252, S1a trên tập chung K3 của 2019; refit đầu mỗi tháng 2019 chỉ
    dùng return trước ngày đầu tháng. Mọi mô hình phải hợp lệ ở mọi ngày gốc của tập K3."""
    months = pd.date_range(*C.VALID, freq="MS")
    out = {"forecasts": {m: {} for m in C.VAL_MODELS}, "fits": [], "inputs": {}, "validity": {}}
    out["seconds"] = {"fit": {}, "fhs_numpy_batch": {}, "single_forecast": {}}
    for asset in assets:
        base = _ns(origins[asset])
        if len(base) != C.K3_COMMON_N[asset]:
            raise StopRun(f"{asset}: K3 common origins {len(base)} != {C.K3_COMMON_N[asset]}")
        q_b, ok_b = baseline_quantiles(prices, asset, base, invalid[asset])
        q_s, ok_s, _ = s1_quantiles(prices, asset, base, C.S1A_LAMBDA, invalid[asset])
        f = fhs_asset(prices, asset, base, months, invalid[asset])
        dm_diag = {}
        q_d, ok_d, numpy_seconds = FF.fhs_forecasts(
            f["r"], asset, base, f["fits"], demean=C.FHS_DEMEAN[C.FHS_DM], diag=dm_diag
        )
        out["validity"][asset] = {
            "origins": len(base),
            "baseline_valid": int(ok_b.sum()),
            "s1a_valid": int(ok_s.sum()),
            "fhs_dm_valid": int(ok_d.sum()),
            "fhs_dm_invalid": dm_diag,
        }
        if not (ok_b & ok_s & ok_d).all():
            raise StopRun(f"{asset}: a model is invalid on K3 common origins")
        for name, q in ((C.FHS_DM, q_d), (C.BASELINE, q_b), (C.S1A, q_s)):
            normalized, crossed = normalize_quantiles(q)  # đúng một lần
            out["forecasts"][name][asset] = (base, normalized, crossed)
        out["fits"] += f["logs"]
        out["inputs"][asset] = (f["r"], f["fits"], base)
        out["seconds"]["fit"][asset] = f["fit_seconds"]
        out["seconds"]["fhs_numpy_batch"][asset] = numpy_seconds
        last = base[-1]
        out["seconds"]["single_forecast"][asset] = single_forecast_seconds(
            f["r"],
            asset,
            last,
            f["fits"][last.to_period("M").to_timestamp()],
            q_d[-1],
            demean=True,
        )
    return out


def runs_on_2019(output_dir: Path) -> list[str]:
    """Các thư mục kết quả K4 đã bắt đầu chạy 2019 (có started.json hoặc summary của val2019)."""
    found = []
    for path in sorted((Path(output_dir) / "eval" / "k4").glob("*/*.json")):
        if path.name not in ("started.json", "summary.json"):
            continue
        try:
            stage = json.loads(path.read_text(encoding="utf-8")).get("stage")
        except (OSError, ValueError):
            stage = None
        if stage == "val2019" and path.parent.name not in found:
            found.append(path.parent.name)
    return found


def run_val2019(
    lake_dir: Path,
    output_dir: Path,
    run_id: str,
    cv_dir: Path,
    cv_dm_dir: Path,
    candidate: str,
    k3_dir: Path,
) -> dict:
    """Một lần duy nhất (mục 8): phần chặn, fingerprint dữ liệu (đọc bản cắt 2018-12-31, so với
    cv), đánh dấu started.json trước khi đọc 2019, rồi đánh giá fhs-gjr-t-dm, baseline-q252, S1a
    trên tập chung K3. Tiêu chí mục 5 theo tài sản; dầu quyết định theo sample all, excl_roll
    chỉ báo cáo (mục 8, 29/10 tối).

    "Một lần" là chặn ở mức quy trình (review #60), không phải bảo đảm tuyệt đối: run-id cố định
    configs/k4.VAL2019_RUN_ID, từ chối run-id khác và từ chối khi đã có started.json (của run-id
    này hoặc bất kỳ thư mục val2019 nào trong eval/k4/); kết quả được upload lên S3
    eval/k4/k4-val2019/ để cả nhóm thấy đã chạy. Xóa started.json hay chạy ở máy khác vẫn lách
    được, nên việc tuân thủ dựa vào quy trình và lịch sử S3."""
    t_start = time.perf_counter()
    if run_id != C.VAL2019_RUN_ID:
        raise StopRun(f"val2019 run-id must be {C.VAL2019_RUN_ID!r}, got {run_id!r}")
    marker = Path(output_dir) / "eval" / "k4" / C.VAL2019_RUN_ID / "started.json"
    if marker.exists():
        raise StopRun(f"{marker} exists: 2019 already started once; the plan allows one run")
    gate = val2019_gate(cv_dir, cv_dm_dir, candidate)
    previous = runs_on_2019(output_dir)
    if previous:
        raise StopRun(f"2019 already run for K4 ({', '.join(previous)}); the plan allows one run")
    eval_dir = check_environment(output_dir, run_id)
    check_roll_calendar(val_config)
    with no_ceemdan_cache():
        cv_prices, cv_rejected = T.read_clean(Path(lake_dir), C.CLEAN_DT, cutoff=C.CV_CUTOFF)
    if data_lineage(cv_prices, cv_rejected, C.CV_CUTOFF) != gate["cv"]["provenance"].get(
        "data_lineage"
    ):
        raise StopRun("clean data fingerprint (≤ 2018-12-31) differs from the cv result")
    eval_dir.mkdir(parents=True, exist_ok=False)
    started = {"stage": "val2019", "candidate": candidate, "started_at": pd.Timestamp.now("UTC")}
    (eval_dir / "started.json").write_text(json.dumps(wf._plain(started)), encoding="utf-8")
    with no_ceemdan_cache():
        prices, rejected = T.read_clean(Path(lake_dir), C.CLEAN_DT, cutoff=C.VAL_CUTOFF)
        prov = provenance(prices, rejected, cutoff=C.VAL_CUTOFF)
        _, origins = R3.k3_reference(Path(k3_dir))
        invalid = {
            a: pd.to_datetime(rejected.loc[rejected["asset"] == a, "date"]).tolist()
            for a in C.ASSETS
        }
        t = time.perf_counter()
        built = build_val(prices, invalid, origins)
        seconds = {"candidates": time.perf_counter() - t}
        t = time.perf_counter()
        p, r = wf._inputs(prices, rejected, val_config("inputs"))
        named = R3.evaluate_set(built["forecasts"], origins, p, r, config=val_config)
        seconds["evaluation"] = time.perf_counter() - t
    check_anchor(named)
    check_roll_flags(named)
    scores = score(named, val_config)
    criterion = {
        name: {f"{row.asset}/{row.sample}": bool(row.ci_low > 0) for row in e["mean7"].itertuples()}
        for name, e in named.items()
    }
    passes = {
        asset: {sample: criterion[C.FHS_DM][f"{asset}/{sample}"] for sample in samples_of(asset)}
        for asset in C.ASSETS
    }
    decision = {asset: by["all"] for asset, by in passes.items()}  # dầu: theo all
    t = time.perf_counter()
    sensitivity = ci_sensitivity(named, (C.FHS_DM, C.S1A), val_config)
    supplementary = {
        "folds": records(fold_table(named, C.VAL_MODELS)),
        "valid_counts": records(valid_counts(named[C.FHS_DM]["detail"])),
        "ci_blocks": records(sensitivity),
        "holm": {C.FHS_DM: records(holm_table(sensitivity, C.FHS_DM))},
        "christoffersen": records(christoffersen_table(named, C.VAL_MODELS)),
        "dm_robustness": records(dm_robustness(named[C.FHS_DM]["detail"], built["inputs"])),
        "dm_minus_fhs": "not computed: fhs-gjr-t is not run on 2019 (one configuration only)",
    }
    seconds["supplementary"] = time.perf_counter() - t
    forecast_rows(built["forecasts"], C.VAL_MODELS).to_parquet(
        eval_dir / "forecasts_val2019.parquet", index=False
    )
    write_frames(eval_dir, named)
    write_fits(eval_dir, built["fits"])
    seconds["total"] = time.perf_counter() - t_start
    single = built["seconds"]["single_forecast"]
    cv, dm = gate["cv"], gate["cv_dm"]
    summary = {
        "run_id": run_id,
        "stage": "val2019",
        "plan": PLAN,
        "candidate": candidate,
        "models": list(C.VAL_MODELS),
        "look_number": C.LOOK_NUMBER,
        "total_configs_seen_on_2019": C.TOTAL_CONFIGS_SEEN,
        "cv_configs_seen": C.CV_CONFIGS_SEEN,
        "decision_order": list(DECISION_ORDER),
        "gate": {
            "cv": {"run_id": cv["run_id"], "commit": cv["provenance"]["commit"]},
            "cv_dm": {
                "run_id": dm["run_id"],
                "commit": dm["provenance"]["commit"],
                "mean_28": dm["scores"][C.FHS_DM]["mean_28"],
            },
        },
        "provenance": prov,
        "k3_reference": {"dir": str(k3_dir), "run_id": R3.C.K3_RUN_ID, "commit": R3.C.K3_COMMIT},
        "common_origins": {a: len(v) for a, v in origins.items()},
        "validity": built["validity"],
        "scores": scores,
        "criterion_ci_low_gt_0": criterion,
        "asset_passes": passes,
        "decision_rule": "asset passes when ci_low > 0 on sample all; excl_roll reported only",
        "asset_decision": decision,
        "any_asset_passes": any(decision.values()),
        "mean7": {name: e["mean7"].to_dict("records") for name, e in named.items()},
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
        "supplementary": supplementary,
    }
    finalize(eval_dir, summary, render_val(summary, named))
    return summary


# ---------- báo cáo Markdown (chỉ trình bày số đã tính) ----------


def render(summary: dict, named: dict) -> str:
    models = list(MODELS)
    out = [f"# K4 FHS GJR-GARCH và kết hợp phân vị: kiểm định chéo 2016–2018 ({summary['run_id']})"]
    look = summary["look_number_if_2019_runs"]
    seen = configs_seen_text()
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
    out += mcs_section(summary["mcs"])
    out += fits_section(summary["fhs_fits"])
    out += supplementary_section(summary["supplementary"])
    out += timing_section(summary["seconds"])
    return "\n".join(out) + "\n"


def supplementary_section(supp: dict) -> list[str]:
    """Báo cáo bổ sung mục 8 (29/10 tối): chỉ báo cáo, không đổi quy tắc chọn hay tiêu chí."""
    titles = {
        "folds": "Theo fold (năm của ngày gốc): pinball_skill trung bình 7 h",
        "valid_counts": "Số ngày gốc được chấm theo tài sản × h",
        "ci_blocks": "Độ nhạy CI 95% theo block length (p một phía = (1 + #≤ 0)/(B + 1))",
        "christoffersen": (
            "Kiểm định độc lập Christoffersen (1998), vượt khoảng 80%, sample all "
            "(h > 1: return chồng nhau nên phụ thuộc sẵn)"
        ),
        "dm_robustness": "Độ bền fhs-gjr-t-dm: seed khác và số đường lớn hơn (chỉ kiểm tra)",
        "dm_minus_fhs": "fhs-gjr-t-dm trừ fhs-gjr-t trên cùng common mask",
    }
    out = ["## Báo cáo bổ sung (mục 8, 29/10 tối; chỉ báo cáo)", ""]
    out += [
        (
            "Hạn chế: q252 và S1a có liên hệ trực tiếp nên combo-eq3 không kết hợp ba nguồn độc "
            "lập; FHS lấy đuôi từ phần dư lịch sử nên có thể thiếu các cú sốc ngoài mẫu."
        ),
        "",
    ]
    for key, title in titles.items():
        if key not in supp:
            continue
        value = supp[key]
        out += [f"### {title}", ""]
        out += [value if isinstance(value, str) else T.md(pd.DataFrame(value)), ""]
    for model, rows in supp.get("holm", {}).items():
        out += [
            (
                f"### Holm qua 4 tài sản cho kiểm định mục 5 ({model}; sample all, block 20, "
                f"ngưỡng {C.HOLM_ALPHA}; excl_roll chỉ báo p riêng)"
            ),
            "",
            T.md(pd.DataFrame(rows)),
            "",
        ]
    return out


def mcs_section(mcs: dict) -> list[str]:
    out = [
        (
            f"## Model Confidence Set {1 - C.MCS_SIZE:.0%} (chỉ báo cáo; loss 7 h × 7 τ mỗi ngày "
            f"gốc, bootstrap {C.MCS_BOOTSTRAP} block {C.MCS_BLOCK}, {C.MCS_REPS} lần, seed "
            f"{C.MCS_SEED})"
        )
    ]
    rows = [
        {
            "asset": asset,
            "n": m["n_obs"],
            **{f"loss {k}": v for k, v in m["mean_loss"].items()},
            **{f"p {k}": v for k, v in m["pvalue"].items()},
            "trong MCS": ", ".join(m["included"]),
            "tập ngày gốc thu hẹp": "có" if m.get("origins_changed") else "không",
        }
        for asset, m in mcs.items()
    ]
    note = "Chỉ ngày gốc đủ 7 h ở mọi mô hình (giao các tập)."
    return [*out, note, "", T.md(pd.DataFrame(rows), ".5f"), ""]


def fits_section(fhs_fits: dict) -> list[str]:
    out = ["## FHS: tham số qua các lần refit (thang return × 100)"]
    rows = []
    for asset, f in fhs_fits.items():
        row = {
            "asset": asset,
            "tháng": f["months"],
            "trạng thái": ", ".join(f"{k} {v}" for k, v in f["status"].items()),
            "dùng tham số tháng trước": len(f["fallback_months"]),
            "liên tiếp lớn nhất": f["max_consecutive_reuse"],
            "ở biên persistence": len(f["at_persistence_bound"]),
            "ở biên α + γ": len(f.get("at_alpha_gamma_bound", [])),
        }
        for p in PARAMS:
            row[p] = f"{f[p]['min']:.3f} / {f[p]['median']:.3f} / {f[p]['max']:.3f}"
        rows.append(row)
    bound = [
        {"asset": asset, **b} for asset, f in fhs_fits.items() for b in f["at_persistence_bound"]
    ]
    out += ["min / trung vị / max trên các lần fit ok.", "", T.md(pd.DataFrame(rows)), ""]
    out += [
        (
            "Các lần fit nằm ở biên ràng buộc của arch (gap = 1 − persistence ≤ "
            f"{C.PERSISTENCE_TOL}; vẫn hợp lệ):"
        ),
        "",
        T.md(pd.DataFrame(bound), ".3e") if bound else "không có",
        "",
    ]
    return out


def timing_section(s: dict) -> list[str]:
    return [
        "## Thời gian (giây)",
        ", ".join(f"{k} {v:.1f}" for k, v in s.items() if isinstance(v, float))
        + "; một lần dự báo FHS NumPy cho 4 tài sản: "
        + f"{s['single_forecast_4_assets'] * 1000:.0f} ms",
    ]


def scores_table(scores: dict) -> str:
    rows = [
        {
            "model": name,
            **{a: s["by_asset"][a] for a in C.ASSETS},
            "trung bình 28 nhóm": s["mean_28"],
            "CI 95%": f"[{s['ci_low']:+.4f}, {s['ci_high']:+.4f}]",
        }
        for name, s in scores.items()
    ]
    return T.md(pd.DataFrame(rows))


def render_cv_dm(summary: dict, named: dict, direction: pd.DataFrame) -> str:
    dm = summary["scores"][C.FHS_DM]
    out = [f"# K4 {C.FHS_DM}: kiểm định chéo 2016–2018 ({summary['run_id']})", ""]
    out += [
        (
            "Kế hoạch mục 8, sửa đổi 29/10 sau kiểm định chéo. Kết quả cv tham chiếu (chỉ đọc): "
            f"{summary['cv_reference']['run_id']} @ {summary['cv_reference']['commit'][:7]}; "
            f"{C.FHS} dựng lại ở đây trùng từng bit với kết quả đó. Kiểm định chéo đã xem "
            f"{summary['cv_configs_seen']} cấu hình; nếu chạy 2019, đó là lần nhìn thứ "
            f"{summary['look_number_if_2019_runs']}, tổng {configs_seen_text()} cấu hình. "
            "fhs-gjr-t và combo-eq3 là ứng viên đăng ký trước; fhs-gjr-t-dm là sửa đổi hậu "
            "nghiệm (lý do: trung bình z âm, q50 âm chỉ là hệ quả)."
        ),
        "",
        "Thứ tự quyết định:",
        "",
        *summary["decision_order"],
        "",
        f"Trung bình pinball_skill 28 nhóm của {C.FHS_DM}: **{dm['mean_28']:+.4f}** "
        f"[{dm['ci_low']:+.4f}, {dm['ci_high']:+.4f}]; quy tắc {summary['proceed_rule']}: "
        + (
            "**chạy 2019 một lần**." if summary["proceed_to_2019"] else "**dừng, không chạy 2019**."
        ),
        "",
        "Tập ngày gốc chung (như cv): "
        + ", ".join(f"{a} {n}" for a, n in summary["common_origins"].items())
        + ".",
        "",
        "## Trung bình pinball_skill 28 nhóm (sample all), CI 95%",
        "",
        scores_table({**summary["reference_scores"], C.FHS_DM: dm}),
        "",
    ]
    models = [C.BASELINE, C.FHS, C.COMBO, C.FHS_DM]
    out += ["## pinball_skill trung bình 7 h, CI 95% (dầu: all và excl_roll)", ""]
    out += [T.md(R3.mean7_table(named, models)), ""]
    out.append("## Mọi chỉ số theo tài sản × h (ADR-0008 mục 5)")
    out.append("Naive (return = 0) là mẫu số của mae_ratio_vs_naive (= 1) và không có phân vị.")
    compare = [C.BASELINE, C.FHS, C.FHS_DM]
    for asset in C.ASSETS:
        out += ["", f"### {asset}", "", T.md(T.metric_table(named, compare, asset))]
    out += ["", "## quantile_hit_rates", "", T.md(R3.hit_table(named, [C.FHS, C.FHS_DM])), ""]
    cols = ["asset", "sample", "h", "dm_stat", "p_value", "p_value_holm", "status"]
    out.append(f"## DM ({C.FHS_DM} vs baseline-252, walk_forward DM_GAP_POLICY)")
    out += [T.md(named[C.FHS_DM]["comparison"][cols]), ""]
    out += mcs_section(summary["mcs"])
    out += ["## Hướng: q50 < 0 và prob_up (các dòng được chấm, sample all)", ""]
    out += [T.md(direction), ""]
    out += fits_section(summary["fhs_fits"])
    out += supplementary_section(summary["supplementary"])
    out += timing_section(summary["seconds"])
    return "\n".join(out) + "\n"


def render_val(summary: dict, named: dict) -> str:
    models = list(C.VAL_MODELS)
    gate = summary["gate"]
    out = [f"# K4 {summary['candidate']}: validation 2019 ({summary['run_id']})", ""]
    out += [
        (
            f"Lần dùng validation 2019 thứ {summary['look_number']} của dự án (tính cả DLinear MVP);"
            f" tổng {configs_seen_text()} cấu hình đã xem trên 2019 (rủi ro data snooping, White "
            f"2000); kiểm định chéo "
            f"{summary['cv_configs_seen']} cấu hình. Phần chặn: cv {gate['cv']['run_id']} @ "
            f"{gate['cv']['commit'][:7]}, cv-dm {gate['cv_dm']['run_id']} @ "
            f"{gate['cv_dm']['commit'][:7]} (trung bình 28 nhóm {gate['cv_dm']['mean_28']:+.4f})."
        ),
        "",
        "Thứ tự quyết định:",
        "",
        *summary["decision_order"],
        "",
        "Tập chung K3: "
        + ", ".join(f"{a} {n}" for a, n in summary["common_origins"].items())
        + ".",
        "",
        "## Tiêu chí mục 5: cận dưới CI 95% của pinball_skill trung bình 7 h > 0",
        "Quyết định theo sample all; excl_roll của dầu chỉ báo cáo (mục 8, 29/10 tối).",
        "",
        T.md(
            pd.DataFrame(
                [
                    {
                        "asset": a,
                        "quyết định (all)": "đạt" if summary["asset_decision"][a] else "không",
                        **{
                            f"{s} (báo cáo)" if s == "excl_roll" else s: ("đạt" if ok else "không")
                            for s, ok in by.items()
                        },
                    }
                    for a, by in summary["asset_passes"].items()
                ]
            )
        ),
        "",
        T.md(R3.mean7_table(named, models)),
        "",
        "## Trung bình pinball_skill 28 nhóm (sample all), CI 95%",
        "",
        scores_table(summary["scores"]),
        "",
        "## Mọi chỉ số theo tài sản × h (ADR-0008 mục 5)",
        "Naive (return = 0) là mẫu số của mae_ratio_vs_naive (= 1) và không có phân vị.",
    ]
    for asset in C.ASSETS:
        out += ["", f"### {asset}", "", T.md(T.metric_table(named, models, asset))]
    out += ["", "## quantile_hit_rates", "", T.md(R3.hit_table(named, models)), ""]
    cols = ["asset", "sample", "h", "dm_stat", "p_value", "p_value_holm", "status"]
    out.append(f"## DM ({summary['candidate']} vs baseline-252, walk_forward DM_GAP_POLICY)")
    out += [T.md(named[summary["candidate"]]["comparison"][cols]), ""]
    out += fits_section(summary["fhs_fits"])
    out += supplementary_section(summary["supplementary"])
    out += timing_section(summary["seconds"])
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=("cv", "cv-dm", "val2019"), required=True)
    parser.add_argument("--lake-dir", type=Path, default=DEFAULT_LAKE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--run-id")
    parser.add_argument("--cv-dir", type=Path)
    parser.add_argument("--cv-dm-dir", type=Path)
    parser.add_argument("--candidate", choices=(*C.CANDIDATES, C.FHS_DM))
    parser.add_argument("--k3-dir", type=Path, default=R3.DEFAULT_K3_DIR)
    args = parser.parse_args(argv)
    run_id = (
        args.run_id or {"cv": "k4-cv", "cv-dm": "k4-cv-dm", "val2019": C.VAL2019_RUN_ID}[args.stage]
    )
    if args.stage in ("cv-dm", "val2019") and args.cv_dir is None:
        parser.error(f"--stage {args.stage} needs --cv-dir")
    if args.stage == "val2019" and (args.cv_dm_dir is None or args.candidate is None):
        parser.error("--stage val2019 needs --cv-dm-dir and --candidate")
    try:
        if args.stage == "cv":
            s = run_cv(args.lake_dir, args.output_dir, run_id)
            out = {"selected": s["selected"], "early_stop": s["early_stop"]}
        elif args.stage == "cv-dm":
            s = run_cv_dm(args.lake_dir, args.output_dir, run_id, args.cv_dir)
            out = {"mean_28": s["scores"][C.FHS_DM]["mean_28"], "proceed": s["proceed_to_2019"]}
        else:
            s = run_val2019(
                args.lake_dir,
                args.output_dir,
                run_id,
                args.cv_dir,
                args.cv_dm_dir,
                args.candidate,
                args.k3_dir,
            )
            out = {"asset_decision": s["asset_decision"], "asset_passes": s["asset_passes"]}
    except STOPS as exc:
        print(f"DỪNG: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({**out, "seconds": s["seconds"]["total"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

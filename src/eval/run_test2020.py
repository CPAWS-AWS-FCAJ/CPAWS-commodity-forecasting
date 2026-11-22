"""PR75 one-time evaluation; import and synthetic API never claim or read a lake.

Official usage (only Long after review/merge):
 python -m src.eval.run_test2020 --mode official --metadata <locked.json> \
     --clean-dir <clean/prices/dt=DT> --output-root <outside-repository>
Metadata schema is REQUIRED_METADATA in configs/test2020.py. snapshot_sha256 maps
all three SNAPSHOT_FILES to raw-file SHA256. lineage contains source='yfinance',
symbols={asset: target}, data_commit=<40 hex>, reference=<reviewed audit ref>.
config_hash is protocol_hash(commit) computed/reviewed BEFORE opening test data.
No retry/resume command. Once claim succeeds any failure consumes the attempt.
Synthetic API takes in-memory frames; its results are labelled synthetic and never
written to official storage. Internal report schema v1 is not Accuracy/public API.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from configs import k3b as K3B
from configs import test2020 as C
from src.data import calendars
from src.data.config import ASSETS
from src.eval import metrics as M
from src.eval import walk_forward as W
from src.forecast import baselines as B
from src.forecast import vol_scale_core
from src.forecast.returns import horizon_log_returns, normalize_quantiles, prob_up
from src.forecast.vol_scale_core import scale_quantiles
from src.forecast.vol_scaled import vol_ratio

ROOT = Path(__file__).resolve().parents[2]
KEYS = ["asset", "base_date", "h"]


def encoded(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def serialize_json_bytes(payload):
    """Artifact wire format: deterministic UTF-8 JSON with exactly one final LF."""
    return encoded(payload) + b"\n"


def git_bytes(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def valid_commit(commit):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid full commit SHA")
    return commit


def protocol_hash(commit):
    """Hash the same src/configs Python files and plan, from locked Git blobs.

    Enumerating the committed tree makes both the file set and bytes reproducible
    without checkout newline conversion. No working-tree fallback is permitted.
    """
    valid_commit(commit)
    plan = "docs/experiments/test2020-plan.md"
    paths = sorted(
        p
        for p in git_bytes(
            "ls-tree", "-r", "--name-only", "-z", commit, "--", "src", "configs", plan
        )
        .decode("utf-8")
        .split("\0")
        if p == plan or (p.startswith(("src/", "configs/")) and p.endswith(".py"))
    )
    if (
        plan not in paths
        or not any(p.startswith("src/") for p in paths)
        or not any(p.startswith("configs/") for p in paths)
    ):
        raise ValueError("committed protocol file set unavailable")
    return sha(
        encoded(
            {
                "protocol": C.protocol(),
                "code": {p: sha(git_bytes("show", f"{commit}:{p}")) for p in paths},
            }
        )
    )


def validate_s1a_constants():
    if C.S1A_LAMBDA != K3B.S1_LAMBDA["S1a"]:
        raise ValueError("S1a lambda configuration drift")
    if C.K_CLIP != K3B.K_CLIP or C.K_CLIP != vol_scale_core.K_CLIP:
        raise ValueError("S1a clip configuration drift")


def settings(start, end, cutoff, reps=C.N_BOOTSTRAP):
    return SimpleNamespace(
        evaluation_start=start,
        evaluation_end=end,
        target_cutoff_date=cutoff,
        n_bootstrap=reps,
        seed=C.BOOTSTRAP_SEED,
        block_length=C.BLOCK_LENGTH,
        confidence_level=C.CONFIDENCE_LEVEL,
    )


def samples(asset):
    return C.OIL_SAMPLES if asset in ("wti", "brent") else ("all",)


def value(x, n, reason=None):
    good = x is not None and np.isfinite(x)
    return {
        "value": float(x) if good else None,
        "n_obs": int(n),
        "status": "ok" if good else "undefined",
        "undefined_reason": None
        if good
        else reason or ("no_evaluable_obs" if not n else "zero_denominator"),
    }


def endpoint_reason(series, rejected, base, target):
    """Within-cutoff endpoint audit, following Walk-forward Contract section 9.1.

    Precedence: rejected base/target, absent base/target, nonpositive base/target,
    nonfinite base/target. NaN in an existing row is nonfinite, not an absent row.
    The caller checks cutoff BEFORE calling this function or reading target prices.
    """
    if base in rejected:
        return "rejected_base"
    if target in rejected:
        return "rejected_target"
    if base not in series.index:
        return "missing_base_price"
    if target not in series.index:
        return "missing_target_price"
    b, t = series.at[base], series.at[target]
    if b <= 0:
        return "nonpositive_base_price"
    if t <= 0:
        return "nonpositive_target_price"
    if not np.isfinite(b):
        return "nonfinite_base_price"
    if not np.isfinite(t):
        return "nonfinite_target_price"
    return None


def build_pairs(prices, rejected, cfg):
    """Per-horizon eligibility; reuse causal baseline and S1 volatility/scaling.

    baseline_quantiles/s1_quantiles wrap all-seven-horizon validity. PR75 masks
    each horizon separately, so use their underlying quantile_baseline and
    vol_ratio/scale_quantiles helpers without imposing that extra all-h gate.
    """
    validate_s1a_constants()
    prices, rejected = prices.copy(), rejected.copy()
    for frame in (prices, rejected):
        frame["date"] = pd.to_datetime(frame.date)
        if frame.duplicated(["asset", "date"]).any():
            raise ValueError("duplicate asset/date")
    prices = prices.loc[prices.date <= cfg.target_cutoff_date]
    rejected = rejected.loc[rejected.date <= cfg.target_cutoff_date]
    rows = []
    for asset in C.ASSETS:
        part = prices.loc[prices.asset == asset].sort_values("date")
        if part.empty:
            raise ValueError(f"missing asset input: {asset}")
        cal = calendars.sessions(ASSETS[asset].calendar)
        base = calendars.sessions(ASSETS[asset].calendar, cfg.evaluation_start, cfg.evaluation_end)
        if not len(base) or cal.get_indexer(base).min() < 0:
            raise ValueError("evaluation calendar unavailable")
        invalid = rejected.loc[rejected.asset == asset, "date"].tolist()
        series = pd.Series(part.price.to_numpy(float), index=pd.DatetimeIndex(part.date))
        # Audit on the same session index as Returns, without altering forecast input.
        audit_index = pd.DatetimeIndex(series.index)
        if audit_index.tz is not None:
            audit_index = audit_index.tz_convert("UTC").tz_localize(None)
        audit_series = pd.Series(series.to_numpy(float), index=audit_index.normalize())
        rejected_dates = set(pd.DatetimeIndex(invalid).normalize())
        audit_prices = audit_series.reindex(cal).to_numpy(float)
        invalid_sessions = ~(
            np.isfinite(audit_prices) & (audit_prices > 0) & ~cal.isin(rejected_dates)
        )
        missing_prefix = np.concatenate(([0], np.cumsum(invalid_sessions)))
        vr = vol_ratio(prices, asset, base, C.S1A_LAMBDA, invalid)
        if np.any(vr.valid & ~np.isfinite(vr.k)):
            raise ValueError("nonfinite S1a volatility factor on valid row")
        context = {"expiry": None, "roll": None}
        if asset in ("wti", "brent"):
            expiry, roll = W.roll_calendar(asset, cfg)
            if not len(expiry) or not len(roll):
                raise ValueError("oil roll calendar unavailable")
            if "flag" in part:
                flagged = part.loc[
                    part.flag.fillna("").str.split("|").map(lambda x: "roll" in x), "date"
                ]
                roll = roll.union(pd.DatetimeIndex(flagged))
            context = {"expiry": expiry, "roll": roll}
        for h in C.HORIZONS:
            returns = horizon_log_returns(
                series, h, calendar=ASSETS[asset].calendar, invalid_dates=invalid
            )
            q = B.quantile_baseline(returns, h).reindex(base).to_numpy(float, copy=True)
            bp = B.up_rate_baseline(returns, h).reindex(base).to_numpy(float)
            y = returns.reindex(base).to_numpy(float)
            ok = np.isfinite(q).all(axis=1)
            sq = np.full_like(q, np.nan)
            both = ok & vr.valid
            if both.any():
                # Scaling helper expects seven horizons; independent rows are tiled
                # only for its validated shape. No new scaling formula is introduced.
                tiled = np.repeat(q[both, None, :], 7, axis=1)
                sq[both] = scale_quantiles(tiled, vr.k[both])[:, 0, :]
            crossed = {"base": np.zeros(len(base), bool), "s1": np.zeros(len(base), bool)}
            for name, a in (("base", q), ("s1", sq)):
                finite = np.isfinite(a).all(axis=1)
                if finite.any():
                    a[finite], crossed[name][finite] = normalize_quantiles(a[finite])
            positions = cal.get_indexer(base) + h
            if np.any(positions >= len(cal)):
                raise ValueError("target calendar unavailable")
            for i, day in enumerate(base):
                target = cal[positions[i]]
                endpoints_valid = None
                # Unknown past-cutoff audit stays null; h=1 has no interior by definition.
                missing_sessions = 0 if h == 1 else None
                if target > pd.Timestamp(cfg.target_cutoff_date):
                    reason = "outside_target_cutoff"
                else:
                    reason = endpoint_reason(audit_series, rejected_dates, day, target)
                    endpoints_valid = reason is None
                    if endpoints_valid != bool(np.isfinite(y[i])):
                        raise ValueError("endpoint audit disagrees with target return")
                    # Open interval (base, target), not a sum from Series.attrs.
                    start = positions[i] - h
                    missing_sessions = int(missing_prefix[positions[i]] - missing_prefix[start + 1])
                    if reason is None:
                        if not ok[i] or not np.isfinite(bp[i]):
                            reason = "baseline_unavailable"
                        elif not both[i]:
                            reason = "s1a_unavailable"
                roll = W.roll_in_horizon(asset, day, target, context)
                if roll is None:
                    raise ValueError("unknown roll status")
                rows.append(
                    {
                        "asset": asset,
                        "base_date": day.strftime("%Y-%m-%d"),
                        "h": h,
                        "target_date": target.strftime("%Y-%m-%d"),
                        "reason": reason,
                        "endpoints_valid": endpoints_valid,
                        "missing_between": None
                        if missing_sessions is None
                        else missing_sessions > 0,
                        "n_missing_between_sessions": missing_sessions,
                        "roll": roll,
                        "y": y[i],
                        "base_q": q[i],
                        "s1_q": sq[i],
                        "baseline_prob": bp[i],
                        "base_prob": prob_up(q[i]) if ok[i] else np.nan,
                        "s1_prob": prob_up(sq[i]) if both[i] else np.nan,
                        "base_crossed": bool(crossed["base"][i]),
                        "s1_crossed": bool(crossed["s1"][i]),
                    }
                )
    return pd.DataFrame(rows).sort_values(KEYS).reset_index(drop=True)


def common_group(pairs, asset, h, sample):
    g = pairs.loc[(pairs.asset == asset) & (pairs.h == h) & pairs.reason.isna()]
    if sample == "excl_roll":
        g = g.loc[~g.roll]
    return g.sort_values("base_date")


def assert_common(left, right):
    if left.duplicated(KEYS).any() or right.duplicated(KEYS).any():
        raise ValueError("duplicate common-mask keys")
    if left[KEYS].to_records(index=False).tolist() != right[KEYS].to_records(index=False).tolist():
        raise ValueError("model common mask mismatch")


def check_invariants(g):
    # Validate each model's available keys independently before metric evaluation.
    left = g.loc[g.base_q.map(lambda q: np.isfinite(q).all())]
    right = g.loc[g.s1_q.map(lambda q: np.isfinite(q).all())]
    assert_common(left, right)
    if len(left) != len(g):
        raise ValueError("nonfinite forecasts on declared common mask")
    if g.empty:
        return
    y = g.y.to_numpy(float)
    b, s = np.stack(g.base_q), np.stack(g.s1_q)
    M.pinball_loss_per_origin(y, b)
    M.pinball_loss_per_origin(y, s)  # reject nonfinite/crossing, no re-normalization
    if b[:, 3].tobytes() != s[:, 3].tobytes():
        raise ValueError("S1a q50 is not bit-exact")
    for fn in (
        lambda q: M.mae_ratio_vs_naive(y, q, np.zeros(len(y))),
        lambda q: M.sign_accuracy(y, q),
    ):
        a, c = fn(b[:, 3]), fn(s[:, 3])
        if not (a == c or (np.isnan(a) and np.isnan(c))):
            raise ValueError("S1a direction/MAE invariant violated")
    if not np.array_equal(g.s1_prob.to_numpy(float), [prob_up(q) for q in s]):
        raise ValueError("S1a probability not recomputed")


def group_metrics(g):
    check_invariants(g)
    y = g.y.to_numpy(float)
    b = np.stack(g.base_q) if len(g) else np.empty((0, 7))
    output = {}
    for name, column, pcol in (
        (C.BASELINE, "base_q", "base_prob"),
        (C.CHALLENGER, "s1_q", "s1_prob"),
    ):
        q = np.stack(g[column]) if len(g) else np.empty((0, 7))
        p = g[pcol].to_numpy(float)
        n = len(y)
        vals = {
            "pinball_skill": M.pinball_skill(y, q, b),
            "pinball_loss": M.mean_pinball_loss(y, q),
            "coverage_80": M.coverage_80(y, q[:, 1], q[:, 5]),
            "width_80": M.width_80(q[:, 1], q[:, 5]),
            "width_80_pct": np.mean(100 * (np.exp(q[:, 5]) - np.exp(q[:, 1]))) if n else np.nan,
            "interval_score_80": M.interval_score_80(y, q[:, 1], q[:, 5]),
            "brier_skill": M.brier_skill(p, y, g.baseline_prob.to_numpy(float)),
            "brier_skill_vs_half": M.brier_skill_vs_half(p, y),
            "mae_ratio_vs_naive": M.mae_ratio_vs_naive(y, q[:, 3], np.zeros(n)) if n else np.nan,
            "sign_accuracy": M.sign_accuracy(y, q[:, 3]),
            "up_rate": M.up_rate(y),
        }
        vals.update({f"quantile_hit_{t}": x for t, x in M.quantile_hit_rates(y, q).items()})
        output[name] = {k: value(x, n) for k, x in vals.items()}
        output[name]["sign_accuracy"] = value(
            vals["sign_accuracy"], np.sum((y != 0) & (q[:, 3] != 0))
        )
    return output


def seven_skill(skills):
    a = np.asarray(skills, float)
    return float(np.mean(a)) if a.shape == (7,) and np.isfinite(a).all() else float("nan")


def centered_bootstrap(observed, replicates):
    reps = np.asarray(replicates, float)
    if not np.isfinite(observed) or not len(reps) or not np.isfinite(reps).all():
        return {
            "ci_low": None,
            "ci_high": None,
            "p": None,
            "status": "undefined",
            "undefined_reason": "incomplete_bootstrap_or_statistic",
        }
    tail = (1 - C.CONFIDENCE_LEVEL) / 2
    low, high = np.quantile(reps, [tail, 1 - tail])
    return {
        "ci_low": float(low),
        "ci_high": float(high),
        "p": float((1 + np.count_nonzero(reps - observed >= observed)) / (len(reps) + 1)),
        "status": "ok",
        "undefined_reason": None,
    }


def insufficient_block_bootstrap():
    return {
        "ci_low": None,
        "ci_high": None,
        "p": None,
        "status": "undefined",
        "undefined_reason": "insufficient_evaluable_obs_for_block",
        "n_replicates": 0,
    }


def bootstrap(pairs, cfg, block):
    bootcfg = SimpleNamespace(**vars(cfg))
    bootcfg.block_length = block
    dates = (
        calendars.sessions("NYSE", cfg.evaluation_start, cfg.evaluation_end)
        .union(calendars.sessions("CME", cfg.evaluation_start, cfg.evaluation_end))
        .sort_values()
    )
    if len(dates) < block:
        draws = np.empty((0, len(dates)), int)
    else:
        dates, draws = W.shared_bootstrap_plan(bootcfg)
    result = []
    for asset in C.ASSETS:
        for sample in samples(asset):
            observed, reps, by_h = [], [], []
            for h in C.HORIZONS:
                g = common_group(pairs, asset, h, sample)
                check_invariants(g)
                if len(g):
                    y = g.y.to_numpy(float)
                    b = np.stack(g.base_q)
                    s = np.stack(g.s1_q)
                    obs = M.pinball_skill(y, s, b)
                    bl, sl = M.pinball_loss_per_origin(y, b), M.pinball_loss_per_origin(y, s)
                else:
                    obs = np.nan
                    bl = sl = np.array([])
                # Draw full calendar first, then retain observations, preserving repeats.
                lookup = pd.DatetimeIndex(g.base_date).get_indexer(dates)
                scores = []
                for draw in draws if len(g) >= block else ():
                    take = lookup[draw]
                    take = take[take >= 0]
                    denominator = bl[take].mean() if len(take) else np.nan
                    scores.append(1 - sl[take].mean() / denominator if denominator > 0 else np.nan)
                observed.append(obs)
                reps.append(scores)
                by_h.append(
                    {
                        "h": h,
                        **value(obs, len(g)),
                        "bootstrap": (
                            insufficient_block_bootstrap()
                            if len(g) < block
                            else centered_bootstrap(obs, scores)
                        ),
                    }
                )
            observed_mean = seven_skill(observed)
            too_short = any(row["n_obs"] < block for row in by_h)
            mean_reps = np.mean(np.array(reps), axis=0) if len(draws) and not too_short else []
            result.append(
                {
                    "asset": asset,
                    "sample": sample,
                    "block": block,
                    **value(
                        observed_mean,
                        sum(len(common_group(pairs, asset, h, sample)) for h in C.HORIZONS),
                        "missing_horizon_or_zero_baseline_loss",
                    ),
                    "bootstrap": (
                        insufficient_block_bootstrap()
                        if too_short
                        else centered_bootstrap(observed_mean, mean_reps)
                    ),
                    "by_horizon": by_h,
                }
            )
    if block == C.BLOCK_LENGTH:
        primary = [r for r in result if r["sample"] == "all"]
        assert len(primary) == 4
        adjusted = M.holm_adjust(
            [np.nan if r["bootstrap"]["p"] is None else r["bootstrap"]["p"] for r in primary]
        )
        for row, p in zip(primary, adjusted, strict=True):
            row["p_holm"] = float(p) if np.isfinite(p) else None
            row["report_significant"] = bool(p < C.ALPHA) if np.isfinite(p) else None
    else:
        # Sensitivity is CI-only. Retain estimates/draws/CI, not hypothesis outputs.
        for row in result:
            for group in [row, *row["by_horizon"]]:
                group["bootstrap"].pop("p", None)
    return {
        "block": block,
        "replicates": len(draws),
        "seed": cfg.seed,
        "calendar": dates.strftime("%Y-%m-%d").tolist(),
        "draws_sha256": sha(draws.astype("<i8").tobytes()),
        "groups": result,
    }


def summarize(pairs, cfg):
    groups, dm = [], []
    for asset in C.ASSETS:
        for sample in samples(asset):
            for h in C.HORIZONS:
                allrows = pairs.loc[(pairs.asset == asset) & (pairs.h == h)].copy()
                reasons = allrows.reason.fillna("eligible").copy()
                if sample == "excl_roll":
                    reasons.loc[allrows.reason.isna() & allrows.roll] = "roll_window"
                g = common_group(pairs, asset, h, sample)
                # Audit counts respect the sample before imposing forecast eligibility.
                audit_rows = allrows.loc[~allrows.roll] if sample == "excl_roll" else allrows
                valid_endpoints = audit_rows.loc[audit_rows.endpoints_valid.eq(True)]
                groups.append(
                    {
                        "asset": asset,
                        "h": h,
                        "sample": sample,
                        "n_origins": len(g),
                        "n_expected": len(allrows),
                        "counts": {str(k): int(v) for k, v in reasons.value_counts().items()},
                        "target_audit": {
                            "n_endpoint_valid_pairs_with_missing_between": int(
                                valid_endpoints.missing_between.eq(True).sum()
                            ),
                            "n_common_pairs_with_missing_between": int(
                                g.missing_between.eq(True).sum()
                            ),
                            "n_missing_between_sessions_endpoint_valid": int(
                                valid_endpoints.n_missing_between_sessions.sum()
                            ),
                            "n_missing_between_sessions_common": int(
                                g.n_missing_between_sessions.sum()
                            ),
                            "n_pairs_not_audited_cutoff": int(
                                audit_rows.endpoints_valid.isna().sum()
                            ),
                        },
                        "metrics": group_metrics(g),
                    }
                )
                gaps = W._dm_session_gaps(g, asset, cfg)
                blocked = h > 1 and gaps > 0
                stat = p = np.nan
                if not blocked and len(g):
                    stat, p = M.diebold_mariano(
                        M.pinball_loss_per_origin(g.y, np.stack(g.s1_q)),
                        M.pinball_loss_per_origin(g.y, np.stack(g.base_q)),
                        h=h,
                        hac_lag=h - 1,
                    )
                dm.append(
                    {
                        "asset": asset,
                        "h": h,
                        "sample": sample,
                        "n_obs": len(g),
                        "gaps": gaps,
                        "statistic": float(stat) if np.isfinite(stat) else None,
                        "p": float(p) if np.isfinite(p) else None,
                        "undefined_reason": "internal_session_gaps"
                        if blocked
                        else (None if np.isfinite(p) else "insufficient_or_degenerate_loss"),
                    }
                )
    for sample in ("all", "excl_roll"):
        family = [r for r in dm if r["sample"] == sample]
        adjusted = M.holm_adjust([r["p"] if r["p"] is not None else np.nan for r in family])
        for row, p in zip(family, adjusted, strict=True):
            row["p_holm"] = float(p) if np.isfinite(p) else None
    return {"groups": groups, "dm": dm}


def evaluate_pairs(pairs, cfg, *, synthetic):
    if pairs.duplicated(KEYS).any():
        raise ValueError("duplicate pair")
    core = summarize(pairs, cfg)
    periods = [(str(y), f"{y}-01-01", f"{y}-12-31") for y in range(2020, 2027)] + list(
        C.STRESS_WINDOWS
    )
    supplemental = {}
    for label, lo, hi in periods:
        sub = pairs.loc[pairs.base_date.between(lo, hi)]
        supplemental[label] = summarize(sub, cfg)
    return {
        "schema_version": 1,
        "run_id": "synthetic-test2020" if synthetic else C.RUN_ID,
        "synthetic": synthetic,
        "limitation": W.LIMITATION,
        "dm_gap_policy": W.DM_GAP_POLICY,
        "champion_action": "none; reporting only; new ADR required",
        **core,
        "primary": bootstrap(pairs, cfg, C.BLOCK_LENGTH),
        "sensitivity": [bootstrap(pairs, cfg, b) for b in C.SENSITIVITY_BLOCKS],
        "periods": supplemental,
    }


def run_synthetic(prices, rejected, *, start, end, cutoff, n_bootstrap=20):
    """In-memory test-only API. Caller must generate synthetic data; no file loader."""
    cfg = settings(start, end, cutoff, n_bootstrap)
    pairs = build_pairs(prices, rejected, cfg)
    return evaluate_pairs(pairs, cfg, synthetic=True)


def git_provenance():
    """Official preflight only; every subprocess is mocked in offline tests."""

    def git(*args):
        return git_bytes(*args).decode("utf-8").strip()

    commit = valid_commit(git("rev-parse", "HEAD"))
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("dirty working tree")
    git("fetch", "origin", "+refs/heads/developer:refs/remotes/origin/developer")
    remote = valid_commit(git("rev-parse", "refs/remotes/origin/developer"))
    try:
        # Pin the resolved remote SHA: the ancestry proof and claim use one identity.
        git("merge-base", "--is-ancestor", commit, remote)
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 1:
            raise ValueError("runner commit not merged into origin/developer") from exc
        raise RuntimeError("remote developer ancestry verification failed") from exc
    for path in ("configs/test2020.py", "src/eval/run_test2020.py", "tests/test_run_test2020.py"):
        git("ls-files", "--error-unmatch", path)
    if git("rev-parse", "HEAD") != commit or git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("repository changed during preflight")
    return {"commit": commit, "origin_developer_sha": remote}


def validate_metadata(meta):
    if not isinstance(meta, dict) or any(k not in meta for k in C.REQUIRED_METADATA):
        raise ValueError("missing claim metadata")
    if meta["run_id"] != "test2020" or C.RUN_ID != "test2020":
        raise ValueError("fixed run_id required")
    if (
        meta["approved_for_official_run"] is not True
        or meta["operator"] != "Long"
        or not meta["plan_reference"]
    ):
        raise ValueError("Long's explicit reviewed authorization required")
    if not re.fullmatch(r"[0-9a-f]{40}", meta["commit"]):
        raise ValueError("commit required")
    if date.fromisoformat(meta["snapshot_dt"]).isoformat() != meta["snapshot_dt"]:
        raise ValueError("invalid snapshot DT")
    hashes = meta["snapshot_sha256"]
    if set(hashes) != set(C.SNAPSHOT_FILES) or not all(
        re.fullmatch(r"[0-9a-f]{64}", x) for x in hashes.values()
    ):
        raise ValueError("complete snapshot SHA256 required")
    lineage = meta["lineage"]
    if (
        lineage.get("source") != "yfinance"
        or lineage.get("symbols") != {a: ASSETS[a].primary.symbol for a in C.ASSETS}
        or not re.fullmatch(r"[0-9a-f]{40}", lineage.get("data_commit", ""))
        or not lineage.get("reference")
    ):
        raise ValueError("snapshot lineage required")
    validate_s1a_constants()
    if meta["config_hash"] != protocol_hash(meta["commit"]):
        raise ValueError("locked config/code hash mismatch")
    if C.DM_GAP_POLICY != W.DM_GAP_POLICY:
        raise ValueError("DM policy changed")


def load_snapshot(directory, meta):
    """Called ONLY after exclusive claim. Verify same bytes subsequently decoded."""
    blobs = {name: (directory / name).read_bytes() for name in C.SNAPSHOT_FILES}
    if any(sha(raw) != meta["snapshot_sha256"][name] for name, raw in blobs.items()):
        raise ValueError("snapshot SHA256 mismatch; attempt consumed")
    quality = json.loads(blobs["quality.json"])
    if not isinstance(quality.get("assets"), dict) or not set(C.ASSETS) <= set(quality["assets"]):
        raise ValueError("snapshot quality metadata missing assets")
    frames = []
    for name in ("prices.parquet", "rejected.parquet"):
        df = pd.read_parquet(
            io.BytesIO(blobs[name]), filters=[("date", "<=", pd.Timestamp(C.TARGET_CUTOFF))]
        )
        if (pd.to_datetime(df.date) > C.TARGET_CUTOFF).any():
            raise ValueError("cutoff violation")
        frames.append(df.loc[df.asset.isin(C.ASSETS)].copy())
    prices, rejected = frames
    if "source" not in prices or not prices.source.eq("yfinance").all():
        raise ValueError("price source disagrees with locked lineage")
    return prices, rejected


def write_json(path, data):
    with path.open("xb") as stream:
        stream.write(serialize_json_bytes(data))


def publish_file(s3, path):
    s3.put_object(
        Bucket=C.BUCKET, Key=C.PREFIX + path.name, Body=path.read_bytes(), IfNoneMatch="*"
    )


def finalize(directory, s3):
    hashes = {p.name: sha(p.read_bytes()) for p in sorted(directory.iterdir()) if p.is_file()}
    write_json(directory / "checksums.json", hashes)
    for p in sorted(directory.iterdir()):
        if p.name not in ("claim.json", "started.json"):
            publish_file(s3, p)


def verified_result(directory):
    hashes = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
    if set(hashes) != {p.name for p in directory.iterdir() if p.is_file()} - {"checksums.json"}:
        raise ValueError("result file set mismatch")
    if any(sha((directory / name).read_bytes()) != digest for name, digest in hashes.items()):
        raise ValueError("result checksum mismatch")
    return json.loads((directory / "summary.json").read_text(encoding="utf-8"))


COMMON_MASK_NOTE = (
    "Test2020 dùng common mask riêng cho từng asset × horizon × sample. "
    "Một origin thiếu horizon này không tự loại các horizon còn lại. "
    "K3b s1_quantiles trước đây yêu cầu đủ cả bảy horizon, nên counts giữa hai workflow "
    "không nhất thiết giống nhau. S(a) vẫn undefined nếu thiếu bất kỳ horizon nào "
    "trong bảy horizon chính."
)


def failure_message(exc):
    """Bounded diagnostic only; redact common credential forms before truncation."""
    message = str(exc)
    for name, value in os.environ.items():
        if value and re.search(r"secret|token|password|credential|access_key", name, re.IGNORECASE):
            message = message.replace(value, "[REDACTED]")
    message = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", message)
    message = re.sub(r"(?i)(https?://[^\s?]+)\?[^\s]+", r"\1?[REDACTED]", message)
    message = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", message)
    message = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED]", message)
    message = re.sub(
        r"(?i)([\"']?(?:[\w-]*(?:secret|token|password|credential|access[_-]?key|api[_-]?key)[\w-]*)"
        r"[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1[REDACTED]",
        message,
    )
    return " ".join(message.splitlines())[:500]


def run_official(meta, clean_dir, output_root, *, s3=None):
    provenance = git_provenance()
    validate_metadata(meta)
    if provenance["commit"] != meta["commit"]:
        raise ValueError("commit mismatch")
    clean_dir, output_root = Path(clean_dir).resolve(), Path(output_root).resolve()
    if clean_dir.name != "dt=" + meta["snapshot_dt"]:
        raise ValueError("snapshot directory DT mismatch")
    if output_root.is_relative_to(ROOT):
        raise ValueError("official output must be outside repository")
    directory = output_root / "eval" / "test2020"
    if directory.exists():
        raise FileExistsError("local test2020 attempt already exists")
    if s3 is None:
        import boto3
        from botocore.config import Config

        s3 = boto3.client("s3", config=Config(retries={"total_max_attempts": 1}))
    claim = {
        **meta,
        **provenance,
        "protocol": C.protocol(),
        "claimed_at": datetime.now(UTC).isoformat(),
    }
    claim_bytes = serialize_json_bytes(claim)
    directory.mkdir(parents=True, exist_ok=False)  # local exclusive reservation
    claimed = False
    try:
        # No source data, file hash, parquet metadata or prices read before this.
        s3.put_object(
            Bucket=C.BUCKET, Key=C.PREFIX + "claim.json", Body=claim_bytes, IfNoneMatch="*"
        )
        claimed = True
        with (directory / "claim.json").open("xb") as stream:
            stream.write(claim_bytes)
        write_json(
            directory / "started.json",
            {"run_id": C.RUN_ID, "started_at": datetime.now(UTC).isoformat()},
        )
        publish_file(s3, directory / "started.json")
        freeze = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"], check=True, capture_output=True, text=True
        ).stdout
        (directory / "env.txt").write_text(freeze, encoding="utf-8")
        prices, rejected = load_snapshot(clean_dir, meta)
        cfg = settings(C.EVALUATION_START, C.EVALUATION_END, C.TARGET_CUTOFF)
        pairs = build_pairs(prices, rejected, cfg)
        result = evaluate_pairs(pairs, cfg, synthetic=False)
        result["claim"] = claim
        pairs.to_parquet(directory / "pairs.parquet", index=False)
        write_json(directory / "summary.json", result)
        (directory / "summary.md").write_text(
            "# Test2020 (one attempt)\n\n"
            + W.LIMITATION
            + "\n\nReporting only; no champion change.\n\n"
            + COMMON_MASK_NOTE
            + "\n\n"
            + "\n".join(
                f"- {r['asset']}: S={r['value']}, Holm p={r.get('p_holm')}, reason={r['undefined_reason']}"
                for r in result["primary"]["groups"]
                if r["sample"] == "all"
            ),
            encoding="utf-8",
        )
        finalize(directory, s3)
        return verified_result(directory)
    except Exception as exc:
        failure = {
            "run_id": C.RUN_ID,
            "error_type": type(exc).__name__,
            "message": failure_message(exc),
            "automatic_retry": False,
            "claim_acquired": claimed,
            "failed_at": datetime.now(UTC).isoformat(),
        }
        write_json(directory / "failure.json", failure)
        if claimed:
            try:
                publish_file(s3, directory / "failure.json")
            except Exception:
                logging.getLogger(__name__).exception(
                    "Failure upload failed; local evidence retained"
                )
        raise


def main(argv=None, *, synthetic_frames=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["synthetic", "official"], required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--clean-dir", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "synthetic":
        if synthetic_frames is None:
            parser.error("synthetic mode requires in-memory frames supplied by tests")
        prices, rejected, options = synthetic_frames
        return run_synthetic(prices, rejected, **options)
    if any(x is None for x in (args.metadata, args.clean_dir, args.output_root)):
        parser.error("official mode requires locked metadata, clean-dir and output-root")
    run_official(
        json.loads(args.metadata.read_text(encoding="utf-8")), args.clean_dir, args.output_root
    )


if __name__ == "__main__":
    main()

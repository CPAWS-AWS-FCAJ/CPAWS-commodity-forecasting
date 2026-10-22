"""Fixed-model validation 2019 orchestration (WF contract/ADR-0008/Accuracy PR10).

Only local NumPy inference and evaluation. No training, cloud clients or imports
from production predict. Dates are exchange sessions; timestamps are UTC.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from numbers import Integral
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import calendars
from src.data.config import ASSETS, PUBLISHED_AT_RULES
from src.eval import metrics as M
from src.features.build import build_feature_frame, make_windows
from src.forecast import baselines as B
from src.forecast.dlinear_numpy import DLinearNumpy
from src.forecast.returns import QUANTILE_LEVELS, horizon_log_returns, normalize_quantiles, prob_up

ASSET_NAMES = ("gold", "silver", "brent", "wti")
HORIZONS = tuple(range(1, 8))
QCOLS = ("q05", "q10", "q25", "q50", "q75", "q90", "q95")
BCOLS = tuple("baseline_" + q for q in QCOLS)
SNAPSHOT_DATE = "2026-10-09"
SNAPSHOT_HASHES = {
    "prices": "21bb22cd5da99f6d5cb8ccc7adee67f58a5178521692513e7b37133249692a83",
    "rejected": "753b747d294bd309fdb90e80c5c2f4104f0a48f000337eb576e9ff92390e984f",
}
PROVENANCE = "backtest_publication_rule"
IMPLEMENTATION_VERSION = "walk-forward-mvp-2"
DM_GAP_POLICY = "block_internal_session_gaps_for_h_gt_1_pending_Khai_review"
LIMITATION = "Latest clean snapshot + publication rules; historical vintage/revisions NOT verified; not a verified point-in-time backtest."
FORECAST_COLUMNS = (
    "forecast_run_id",
    "model_version",
    "fit_id",
    "asset",
    "base_date",
    "h",
    *QCOLS,
    "prob_up",
    "crossed_raw",
    "forecast_status",
    "missing_reason",
    "as_of_time",
    "provenance_status",
    "created_at",
)
REASONS = {
    "invalid_input_window": {"input_nan", "insufficient_input_history", "input_not_available"},
    "generation_error": {"model_exception", "invalid_model_output", "upstream_failure"},
}


@dataclass(frozen=True)
class EvaluationConfig:
    run_id: str = "validation-2019"
    forecast_run_id: str = "dlinear-2019-forecasts"
    model_version: str = "dlinear-41e13dc5de3d"
    seed: int = 7
    evaluation_kind: str = "validation"
    evaluation_start: str = "2019-01-01"
    evaluation_end: str = "2019-12-31"
    target_cutoff_date: str = "2019-12-31"
    window: int = 60
    block_length: int = 20
    n_bootstrap: int = 1000
    confidence_level: float = 0.95
    retrain_every: None = None
    provenance_status: str = PROVENANCE
    evaluation_as_of_time: str | None = None

    def __post_init__(self):
        fixed = {
            "evaluation_kind": "validation",
            "evaluation_start": "2019-01-01",
            "evaluation_end": "2019-12-31",
            "target_cutoff_date": "2019-12-31",
            "window": 60,
            "block_length": 20,
            "n_bootstrap": 1000,
            "confidence_level": 0.95,
            "retrain_every": None,
            "provenance_status": PROVENANCE,
        }
        if any(getattr(self, k) != v for k, v in fixed.items()):
            raise ValueError(
                "only fixed validation 2019 / window60 / bootstrap20x1000 / 95% / no retrain is supported"
            )
        if any(
            not isinstance(getattr(self, k), str) or not getattr(self, k).strip()
            for k in ("run_id", "forecast_run_id", "model_version")
        ):
            raise ValueError("run/model identifiers must be nonempty strings")
        if isinstance(self.seed, bool) or not isinstance(self.seed, Integral) or self.seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        if self.evaluation_as_of_time is None:
            raise ValueError("evaluation_as_of_time must be explicit and fixed for a run_id")
        object.__setattr__(
            self, "evaluation_as_of_time", _utc(self.evaluation_as_of_time).isoformat()
        )
        if self.block_length < max(HORIZONS):
            raise ValueError("block_length must be >= h")


@dataclass
class ModelBundle:
    model: object
    manifest: dict
    config: dict


@dataclass
class EvaluationResult:
    detail: pd.DataFrame
    accuracy: pd.DataFrame
    model_comparison: pd.DataFrame
    manifest: dict
    log: dict


def _utc(value):
    ts = pd.Timestamp(value)
    if pd.isna(ts) or ts.tzinfo is None:
        raise ValueError("expected a nonmissing timezone-aware UTC timestamp")
    return ts.tz_convert("UTC")


def _day(value):
    ts = pd.Timestamp(value)
    if pd.isna(ts) or ts.tzinfo is not None or ts != ts.normalize():
        raise ValueError("expected an ISO session date without timezone/time")
    return str(ts.date())


def publication_time(asset, day):
    days, hours = PUBLISHED_AT_RULES[ASSETS[asset].primary.source]
    return pd.Timestamp(day).tz_localize("UTC") + pd.Timedelta(days=days, hours=hours)


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [_plain(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _plain(value.item())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _digest(value):
    return hashlib.sha256(
        json.dumps(_plain(value), sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _fits(fits, cfg):
    if set(fits) != set(ASSET_NAMES):
        raise ValueError("exactly one fixed fit per each of the four assets is required")
    seen = set()
    for asset, m in fits.items():
        required = (
            "fit_id",
            "model_version",
            "asset",
            "train_end",
            "max_training_target_date",
            "trained_at",
            "config_hash",
            "commit",
        )
        if any(not isinstance(m.get(k), str) or not m[k].strip() for k in required):
            raise ValueError(f"{asset}: missing required Fits metadata")
        if m["asset"] != asset or m["model_version"] != cfg.model_version:
            raise ValueError(f"{asset}: Fits asset/model_version mismatch")
        if m["fit_id"] in seen:
            raise ValueError("duplicate fit_id")
        seen.add(m["fit_id"])
        if m.get("integration_eligible") is not True or m.get("missing_metadata"):
            raise ValueError(f"{asset}: artifact is not integration eligible")
        if (
            _day(m["train_end"]) > "2018-12-31"
            or _day(m["max_training_target_date"]) > "2018-12-31"
        ):
            raise ValueError(f"{asset}: training target crosses 2018 cutoff")
        if _day(m["max_training_target_date"]) < "2014-01-01":
            raise ValueError(f"{asset}: training target outside train period")
        _utc(m["trained_at"])  # real 2026 timestamp, never rewritten to a backtest origin
        available = (
            _utc(m["max_training_label_available_at"])
            if m.get("max_training_label_available_at")
            else publication_time(asset, m["max_training_target_date"])
        )
        if available < publication_time(asset, m["max_training_target_date"]):
            raise ValueError(f"{asset}: inconsistent training-label publication metadata")
        first = calendars.sessions(
            ASSETS[asset].calendar, cfg.evaluation_start, cfg.evaluation_end
        )[0]
        if available > publication_time(asset, first):
            raise ValueError(f"{asset}: training labels not available at first validation origin")


def load_models(model_root, cfg, snapshot_hashes=None):
    models = {}
    for asset in ASSET_NAMES:
        directory = Path(model_root) / asset / cfg.model_version
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        if config.get("train_start") != "2014-01-01" or config.get("train_end") != "2018-12-31":
            raise ValueError(f"{asset}: unsupported train split")
        if snapshot_hashes is not None and config.get("data_hashes") != snapshot_hashes:
            raise ValueError(f"{asset}: model/snapshot hashes do not match")
        models[asset] = ModelBundle(DLinearNumpy.load(directory), manifest, config)
    _fits({a: b.manifest for a, b in models.items()}, cfg)
    return models


def load_clean_snapshot(clean_dir):
    directory = Path(clean_dir)
    hashes = {
        k: hashlib.sha256((directory / (k + ".parquet")).read_bytes()).hexdigest()
        for k in SNAPSHOT_HASHES
    }
    if hashes != SNAPSHOT_HASHES:
        raise ValueError("snapshot hash mismatch; required dt=2026-10-09, no fallback allowed")
    quality = json.loads((directory / "quality.json").read_text(encoding="utf-8"))
    return (
        pd.read_parquet(directory / "prices.parquet"),
        pd.read_parquet(directory / "rejected.parquet"),
        quality,
        hashes,
    )


def _inputs(prices, rejected, cfg):
    required = {"asset", "date", "price", "source", "published_at"}
    if not required <= set(prices.columns) or not {"asset", "date"} <= set(rejected.columns):
        raise ValueError("prices/rejected schema is incomplete")
    p = prices.copy()
    r = rejected.copy()
    p["date"] = p["date"].map(_day)
    r["date"] = r["date"].map(_day)
    if p.duplicated(["asset", "date"]).any() or r.duplicated(["asset", "date"]).any():
        raise ValueError("duplicate asset/date in snapshot")
    p = p.loc[p.asset.isin(ASSET_NAMES) & (p.date <= cfg.target_cutoff_date)].copy()
    for asset in ASSET_NAMES:
        part = p.loc[p.asset == asset]
        if part.empty:
            raise ValueError(f"{asset}: missing warm-up/validation prices")
        if not part.source.eq(ASSETS[asset].primary.source).all():
            raise ValueError(f"{asset}: source is not the configured target series")
        if not pd.DatetimeIndex(part.date).isin(calendars.sessions(ASSETS[asset].calendar)).all():
            raise ValueError(f"{asset}: off-calendar prices")
    return p, r


def _feature_batch(p, r, asset, cfg):
    invalid = pd.to_datetime(r.loc[r.asset == asset, "date"]).tolist()
    frame = build_feature_frame(p, asset, invalid_dates=invalid)
    dates = calendars.sessions(ASSETS[asset].calendar, cfg.evaluation_start, cfg.evaluation_end)
    return make_windows(frame, dates, window=cfg.window)


def generate_forecasts(prices, rejected, models, cfg=None):
    """Return every expected origin x 7, retaining failed attempts; pass raw windows unscaled."""
    cfg = cfg or EvaluationConfig()
    _fits({a: b.manifest for a, b in models.items()}, cfg)
    p, r = _inputs(prices, rejected, cfg)
    rows = []
    errors = []
    for asset in ASSET_NAMES:
        bundle = models[asset]
        batch = _feature_batch(p, r, asset, cfg)
        for i, base in enumerate(batch.base_dates):
            day = _day(base)
            asof = publication_time(asset, day)
            status = "ok"
            reason = None
            raw = None
            q = None
            crossed = None
            if not batch.valid[i]:
                status = "invalid_input_window"
                reason = {
                    "invalid_input_window": "input_nan",
                    "insufficient_input_history": "insufficient_input_history",
                }.get(str(batch.reason[i]))
                if reason is None:
                    raise ValueError(f"unsupported FeatureBatch reason: {batch.reason[i]}")
            elif (
                np.isnat(batch.max_input_published_at[i])
                or batch.max_input_published_at[i] > asof.tz_localize(None).to_datetime64()
            ):
                status = "invalid_input_window"
                reason = "input_not_available"
            else:
                try:
                    raw = np.asarray(bundle.model.predict(batch.X[i : i + 1]), dtype=float)
                except Exception as exc:  # noqa: BLE001 - preserve failed model attempts in audit
                    status = "generation_error"
                    reason = "model_exception"
                    errors.append(
                        {
                            "asset": asset,
                            "base_date": day,
                            "error": type(exc).__name__ + ": " + str(exc),
                        }
                    )
                if raw is not None:
                    if raw.shape != (1, 7, 7):
                        status = "generation_error"
                        reason = "invalid_model_output"
                    else:
                        good = np.isfinite(raw[0]).all(axis=1)
                        q = np.full((7, 7), np.nan)
                        crossed = np.full(7, None, dtype=object)
                        if good.any():
                            normalized, flags = normalize_quantiles(raw[0, good])
                            q[good] = normalized
                            crossed[good] = flags
            for j, h in enumerate(HORIZONS):
                hs, hr = status, reason
                values = [None] * 7
                prob = None
                flag = None
                if status == "ok":
                    if q is None or not np.isfinite(q[j]).all():
                        hs = "generation_error"
                        hr = "invalid_model_output"
                    else:
                        flag = bool(crossed[j])
                        values = q[j].tolist()
                        try:
                            prob = prob_up(q[j])
                        except ValueError:
                            hs = "generation_error"
                            hr = "invalid_model_output"
                            values = [None] * 7
                rows.append(
                    dict(
                        zip(
                            FORECAST_COLUMNS,
                            [
                                cfg.forecast_run_id,
                                cfg.model_version,
                                bundle.manifest["fit_id"],
                                asset,
                                day,
                                h,
                                *values,
                                prob,
                                flag,
                                hs,
                                hr,
                                asof.isoformat(),
                                PROVENANCE,
                                None,
                            ],
                            strict=True,
                        )
                    )
                )
    result = pd.DataFrame(rows, columns=FORECAST_COLUMNS)
    result.attrs["generation_errors"] = errors
    return result


def _validate_forecasts(forecasts, p, r, fits, cfg):
    if not set(FORECAST_COLUMNS) <= set(forecasts.columns):
        raise ValueError("missing Internal Forecasts columns")
    f = forecasts.loc[:, list(FORECAST_COLUMNS)].copy()
    f["base_date"] = f.base_date.map(_day)
    key = ["forecast_run_id", "model_version", "fit_id", "asset", "base_date", "h"]
    duplicated = f.duplicated(key, keep=False)
    for _, g in f.loc[duplicated].groupby(key, dropna=False):
        if len(g.drop_duplicates()) != 1:
            raise ValueError("conflicting duplicate forecast key")
    dedup = int(f.duplicated(key).sum())
    f = f.drop_duplicates(key)
    # Reject invalid h/session even outside the selected evaluation range.
    for row in f.itertuples(index=False):
        if (
            row.asset not in ASSET_NAMES
            or isinstance(row.h, bool)
            or not isinstance(row.h, Integral)
            or row.h not in HORIZONS
        ):
            raise ValueError("invalid asset/h")
        if pd.Timestamp(row.base_date) not in calendars.sessions(ASSETS[row.asset].calendar):
            raise ValueError("off-calendar base_date")
        if (
            row.forecast_run_id != cfg.forecast_run_id
            or row.model_version != cfg.model_version
            or row.fit_id != fits[row.asset]["fit_id"]
        ):
            raise ValueError("forecast run/model/fit lineage mismatch")
    outside = ~f.base_date.between(cfg.evaluation_start, cfg.evaluation_end)
    ignored = int(outside.sum())
    f = f.loc[~outside]
    batches = {a: _feature_batch(p, r, a, cfg) for a in ASSET_NAMES}
    lookup = {a: {_day(d): i for i, d in enumerate(b.base_dates)} for a, b in batches.items()}
    for row in f.itertuples(index=False):
        values = np.array([getattr(row, q) for q in QCOLS], dtype=float)
        asof = _utc(row.as_of_time)
        if row.provenance_status != PROVENANCE or asof != publication_time(
            row.asset, row.base_date
        ):
            raise ValueError("invalid provenance/as_of publication time")
        full = calendars.sessions(ASSETS[row.asset].calendar)
        pos = full.get_loc(pd.Timestamp(row.base_date))
        if asof >= publication_time(row.asset, full[pos + row.h]):
            raise ValueError("release is not before target publication")
        if (
            row.crossed_raw is not None
            and not pd.isna(row.crossed_raw)
            and not isinstance(row.crossed_raw, (bool, np.bool_))
        ):
            raise ValueError("crossed_raw must be boolean or null")
        if row.forecast_status == "ok":
            if row.missing_reason is not None and not pd.isna(row.missing_reason):
                raise ValueError("ok forecast has missing_reason")
            if not np.isfinite(values).all() or (np.diff(values) < 0).any():
                raise ValueError("invalid normalized quantiles")
            if (
                row.prob_up is None
                or not math.isfinite(row.prob_up)
                or abs(row.prob_up - prob_up(values)) > 1e-12
            ):
                raise ValueError("invalid prob_up")
            batch = batches[row.asset]
            i = lookup[row.asset][row.base_date]
            if (
                not batch.valid[i]
                or np.isnat(batch.max_input_published_at[i])
                or batch.max_input_published_at[i] > asof.tz_localize(None).to_datetime64()
            ):
                raise ValueError("ok forecast violates input/publication validity")
        elif row.forecast_status in REASONS:
            if (
                row.missing_reason not in REASONS[row.forecast_status]
                or not np.isnan(values).all()
                or not pd.isna(row.prob_up)
            ):
                raise ValueError("invalid failure row/status/reason")
        else:
            raise ValueError("unsupported forecast_status (no_forecast_row belongs only to Detail)")
    return f, {"deduplicated_identical": dedup, "ignored_outside_origins": ignored}


def _asset_context(p, r, asset, cfg):
    part = p.loc[p.asset == asset].copy().sort_values("date")
    invalid = set(r.loc[r.asset == asset, "date"])
    cal = calendars.sessions(ASSETS[asset].calendar, part.date.min(), cfg.target_cutoff_date)
    indexed = part.set_index("date")
    prices_by_day = indexed.price.to_dict()
    pub = {d: (_utc(v) if not pd.isna(v) else None) for d, v in indexed.published_at.items()}
    price_series = pd.Series(part.price.to_numpy(float), index=pd.DatetimeIndex(part.date))
    valid_price = np.array(
        [
            d not in invalid
            and d in prices_by_day
            and np.isfinite(prices_by_day[d])
            and prices_by_day[d] > 0
            for d in cal.strftime("%Y-%m-%d")
        ]
    )
    expiry = None
    roll = None
    if asset in ("brent", "wti"):
        try:
            expiry = (calendars.cl_expiries if asset == "wti" else calendars.bz_expiries)(
                cfg.evaluation_start, "2020-02-01"
            )
            roll = calendars.roll_days(
                ASSETS[asset].roll_rule,
                calendars.sessions(ASSETS[asset].calendar, "2018-12-01", "2020-02-01"),
            )
            if "flag" in indexed:
                supplied = [
                    pd.Timestamp(d)
                    for d, flag in indexed.flag.items()
                    if isinstance(flag, str) and "roll" in flag.split("|")
                ]
                roll = roll.union(pd.DatetimeIndex(supplied))
            if len(expiry) == 0:
                expiry = None
        except (ValueError, IndexError, KeyError):
            expiry = None
            roll = None
    return {
        "cal": cal,
        "prices": prices_by_day,
        "pub": pub,
        "invalid": invalid,
        "series": price_series,
        "valid_price": valid_price,
        "expiry": expiry,
        "roll": roll,
    }


def roll_in_horizon(asset, base, target, context):
    if asset not in ("brent", "wti"):
        return False
    if context["expiry"] is None or context["roll"] is None:
        return None
    dates = context["expiry"].union(context["roll"])
    return bool(((dates > pd.Timestamp(base)) & (dates <= pd.Timestamp(target))).any())


def _endpoint_reason(context, base, target):
    for endpoint, day in [("base", base), ("target", target)]:
        if day in context["invalid"]:
            return "rejected_" + endpoint
    for endpoint, day in [("base", base), ("target", target)]:
        if day not in context["prices"]:
            return "missing_" + endpoint + "_price"
    for endpoint, day in [("base", base), ("target", target)]:
        value = context["prices"][day]
        if value <= 0:
            return "nonpositive_" + endpoint + "_price"
    for endpoint, day in [("base", base), ("target", target)]:
        if not np.isfinite(context["prices"][day]):
            return "nonfinite_" + endpoint + "_price"
    return None


def _baseline_series(context, asset, h):
    cal = context["cal"]
    target = horizon_log_returns(
        context["series"],
        h,
        calendar=ASSETS[asset].calendar,
        invalid_dates=pd.to_datetime(list(context["invalid"])),
    ).reindex(cal)
    availability = []
    for i, day in enumerate(cal):
        end = cal[i + h] if i + h < len(cal) else None
        a = context["pub"].get(_day(day))
        b = context["pub"].get(_day(end)) if end is not None else None
        availability.append(max(a, b) if a is not None and b is not None else pd.NaT)
    available = (
        pd.DatetimeIndex(availability).tz_convert("UTC")
        if any(not pd.isna(v) for v in availability)
        else pd.DatetimeIndex([pd.NaT] * len(cal), tz="UTC")
    )
    # Returns with unknown publication cannot supply a causal baseline.
    ready = target.where(~available.isna())
    return (
        target,
        ready,
        available,
        B.quantile_baseline(ready, h),
        B.up_rate_baseline(ready, h),
        B.baseline_valid(ready, h),
    )


def _baseline_at(series, available, q, p, valid, position, asof, h):
    first = max(0, position - 251)
    last = position - h
    candidates = np.arange(first, last + 1, dtype=int) if last >= first else np.array([], dtype=int)
    known = np.isfinite(series.iloc[candidates].to_numpy())
    times = available.as_unit("ns").asi8[candidates]
    timely = (times != pd.NaT.value) & (times <= asof.value)
    count = int((known & timely).sum())
    # Standard publication rules need no per-origin recalculation. Recalculate only
    # exceptional late publications, still by calling the Baselines public API.
    late = candidates[known & ~timely]
    if len(late):
        prefix = series.iloc[: position + 1].copy()
        prefix.iloc[late] = np.nan
        quantiles = B.quantile_baseline(prefix, h).iloc[-1].to_numpy(float)
        probability = float(B.up_rate_baseline(prefix, h).iloc[-1])
        okay = bool(B.baseline_valid(prefix, h).iloc[-1])
    else:
        quantiles = q.iloc[position].to_numpy(float)
        probability = float(p.iloc[position])
        okay = bool(valid.iloc[position])
    if okay != (count >= 200):
        raise ValueError("baseline count/validity disagreement")
    if okay and (not np.isfinite(quantiles).all() or not math.isfinite(probability)):
        raise ValueError("invalid Baselines output")
    reason = (
        None
        if okay
        else ("insufficient_history" if len(candidates) < 200 else "insufficient_valid_returns")
    )
    return (
        quantiles if okay else np.full(7, np.nan),
        probability if okay else None,
        count,
        okay,
        reason,
    )


def _implementation_metadata(cfg):
    """Fingerprint source and numerical/calendar dependencies without inventing a commit."""
    root = Path(__file__).resolve().parents[2]
    modules = (
        "src/__init__.py",
        "src/data/__init__.py",
        "src/data/calendars.py",
        "src/data/config.py",
        "src/eval/__init__.py",
        "src/eval/metrics.py",
        "src/eval/walk_forward.py",
        "src/features/__init__.py",
        "src/features/build.py",
        "src/forecast/__init__.py",
        "src/forecast/baselines.py",
        "src/forecast/dlinear_numpy.py",
        "src/forecast/returns.py",
    )
    dependencies = {"python": platform.python_version()}
    for name in ("numpy", "pandas", "scipy", "pyarrow", "pandas_market_calendars", "tzdata"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    return {
        "version": IMPLEMENTATION_VERSION,
        "code_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in modules
        },
        "dependencies": dependencies,
        "calendar_sessions": {
            name: _digest(
                calendars.sessions(name, cfg.evaluation_start, cfg.evaluation_end)
                .strftime("%Y-%m-%d")
                .tolist()
            )
            for name in ("NYSE", "CME")
        },
        "publication_rules": PUBLISHED_AT_RULES,
        "dm_gap_policy": DM_GAP_POLICY,
        "quantile_levels": list(QUANTILE_LEVELS),
        "bootstrap_calendar": "sorted union NYSE/CME sessions",
    }


def _frame_lineage(frame, keys):
    canonical = frame.sort_values(keys).sort_index(axis=1)
    return {
        "n_rows": len(frame),
        "schema": {name: str(dtype) for name, dtype in canonical.dtypes.items()},
        "sha256": hashlib.sha256(
            pd.util.hash_pandas_object(canonical, index=False).to_numpy().tobytes()
        ).hexdigest(),
    }


def _evaluation_identity(cfg, fits, p, r, forecasts, input_lineage=None):
    return {
        "config": asdict(cfg),
        "fits": fits,
        "implementation": _implementation_metadata(cfg),
        "input_lineage": {
            "prices_evaluation_view": _frame_lineage(p, ["asset", "date"]),
            "rejected_evaluation_view": _frame_lineage(r, ["asset", "date"]),
            "validated_forecasts": _frame_lineage(forecasts, ["asset", "base_date", "h"]),
            "source_artifacts": input_lineage,
        },
    }


def _evaluation_hash(cfg, fits, p, r, forecasts, input_lineage=None):
    return _digest(_evaluation_identity(cfg, fits, p, r, forecasts, input_lineage))


def _claim_run(registry_dir, manifest):
    """Persist an immutable run binding in an explicitly scoped local registry.

    Replays may use another output directory but must share this registry. There
    is no global registry across machines or unrelated registry directories.
    """
    directory = Path(registry_dir)
    directory.mkdir(parents=True, exist_ok=True)
    record = {"run_id": manifest["run_id"], "config_hash": manifest["config_hash"]}
    target = directory / (_digest(record["run_id"]) + ".json")
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True)
    except FileExistsError:
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != record:
            raise ValueError(
                "immutable run_id conflicts with registered config/input/code; use a new run_id"
            )


def _dm_session_gaps(group, asset, cfg):
    """Count missing exchange sessions between retained pairs, not weekends/holidays."""
    sessions = calendars.sessions(ASSETS[asset].calendar, cfg.evaluation_start, cfg.evaluation_end)
    positions = sessions.get_indexer(pd.to_datetime(group.base_date))
    if np.any(positions < 0) or np.any(np.diff(positions) <= 0):
        raise ValueError("DM pairs must be unique, ordered asset sessions")
    return int(np.maximum(np.diff(positions) - 1, 0).sum())


def _make_detail(forecasts, p, r, fits, cfg, config_hash):
    by_key = {(x["asset"], x["base_date"], x["h"]): x for x in forecasts.to_dict("records")}
    rows = []
    asof_eval = _utc(cfg.evaluation_as_of_time)
    for asset in ASSET_NAMES:
        context = _asset_context(p, r, asset, cfg)
        cal = context["cal"]
        full = calendars.sessions(ASSETS[asset].calendar)
        origins = calendars.sessions(
            ASSETS[asset].calendar, cfg.evaluation_start, cfg.evaluation_end
        )
        for h in HORIZONS:
            targets, ready, available, bq, bp, bvalid = _baseline_series(context, asset, h)
            for base in origins:
                day = _day(base)
                target = _day(full[full.get_loc(base) + h])
                within = target <= cfg.target_cutoff_date
                f = by_key.get((asset, day, h))
                if f is None:
                    f = {k: None for k in FORECAST_COLUMNS}
                    f.update(
                        forecast_run_id=cfg.forecast_run_id,
                        model_version=cfg.model_version,
                        fit_id=fits[asset]["fit_id"],
                        asset=asset,
                        base_date=day,
                        h=h,
                        forecast_status="no_forecast_row",
                        missing_reason="no_forecast_row",
                        as_of_time=publication_time(asset, day).isoformat(),
                        provenance_status=PROVENANCE,
                    )
                row = dict(f)
                position = cal.get_indexer([base])[0]
                if position < 0:
                    quantiles = np.full(7, np.nan)
                    bprob = None
                    n = 0
                    bv = False
                    breason = "insufficient_history"
                else:
                    quantiles, bprob, n, bv, breason = _baseline_at(
                        ready, available, bq, bp, bvalid, position, publication_time(asset, day), h
                    )
                y = None
                tv = None
                reason = "not_loaded_cutoff"
                between = None
                if within:
                    reason = _endpoint_reason(context, day, target)
                    ti = cal.get_indexer([pd.Timestamp(target)])[0]
                    between = (
                        int((~context["valid_price"][position + 1 : ti]).sum())
                        if position >= 0 and ti >= 0
                        else None
                    )
                    if reason is None:
                        pubs = (context["pub"].get(day), context["pub"].get(target))
                        if any(v is None or v > asof_eval for v in pubs):
                            reason = "label_not_available"
                    tv = reason is None
                    if tv:
                        y = float(targets.loc[base])
                        if not math.isfinite(y):
                            raise ValueError("Returns disagrees with validated target endpoints")
                fv = f["forecast_status"] == "ok"
                common = bool(fv and tv is True and bv and within)
                roll = roll_in_horizon(asset, day, target, context)
                row.update(
                    run_id=cfg.run_id,
                    config_hash=config_hash,
                    target_date=target,
                    evaluation_kind=cfg.evaluation_kind,
                    target_cutoff_date=cfg.target_cutoff_date,
                    y_true=y,
                    target_valid=tv,
                    target_invalid_reason=reason,
                    within_cutoff=within,
                    missing_between_count=between,
                    baseline_prob_up=bprob,
                    baseline_n_obs=n,
                    baseline_valid=bv,
                    baseline_invalid_reason=breason,
                    forecast_valid=fv,
                    roll_in_horizon=roll,
                    common_mask_all=common,
                    common_mask_excl_roll=(
                        bool(common and roll is False) if asset in ("brent", "wti") else None
                    ),
                    model_pinball_loss=None,
                    baseline_pinball_loss=None,
                )
                row.update(dict(zip(BCOLS, _plain(quantiles), strict=True)))
                row["exclusion_reason"] = next(
                    (
                        name
                        for flag, name in [
                            (not within, "outside_target_cutoff"),
                            (f["forecast_status"] == "no_forecast_row", "no_forecast_row"),
                            (
                                f["forecast_status"] == "invalid_input_window",
                                "invalid_input_window",
                            ),
                            (f["forecast_status"] == "generation_error", "generation_error"),
                            (tv is not True, "invalid_target"),
                            (not bv, "insufficient_baseline"),
                        ]
                        if flag
                    ),
                    None,
                )
                rows.append(row)
    detail = pd.DataFrame(rows)
    common = detail.common_mask_all.to_numpy(bool)
    if common.any():
        detail.loc[common, "model_pinball_loss"] = M.pinball_loss_per_origin(
            detail.loc[common, "y_true"].to_numpy(float),
            detail.loc[common, list(QCOLS)].to_numpy(float),
        )
        detail.loc[common, "baseline_pinball_loss"] = M.pinball_loss_per_origin(
            detail.loc[common, "y_true"].to_numpy(float),
            detail.loc[common, list(BCOLS)].to_numpy(float),
        )
    return detail


def shared_bootstrap_plan(cfg):
    """Ask the existing helper for one date-index plan on the union calendar.

    Each CI call below uses the exact same finite union-calendar vector/seed;
    callbacks assert equality with this plan. Missing asset observations are
    removed only *after* drawing real dates. Never bootstrap compressed masks.
    """
    dates = (
        calendars.sessions("NYSE", cfg.evaluation_start, cfg.evaluation_end)
        .union(calendars.sessions("CME", cfg.evaluation_start, cfg.evaluation_end))
        .sort_values()
    )
    draws = []

    def remember(sample):
        draws.append(sample.astype(int))
        return 0.0

    M.block_bootstrap_ci(
        np.arange(len(dates), dtype=float),
        remember,
        block_length=cfg.block_length,
        n_resamples=cfg.n_bootstrap,
        confidence_level=cfg.confidence_level,
        seed=cfg.seed,
    )
    return dates, np.stack(draws)


def _skill_ci(group, dates, draws, cfg):
    if len(group) < cfg.block_length:
        return None, None, {"reason": "insufficient_evaluable_obs_for_block", "n_replicates": 0}
    lookup = pd.Index(pd.to_datetime(group.base_date)).get_indexer(dates)
    y = group.y_true.to_numpy(float)
    q = group[list(QCOLS)].to_numpy(float)
    b = group[list(BCOLS)].to_numpy(float)
    calls = 0
    bad = 0

    def statistic(sampled):
        nonlocal calls, bad
        index = sampled.astype(int)
        if not np.array_equal(index, draws[calls]):
            raise ValueError("bootstrap plan drift")
        calls += 1
        take = lookup[index]
        take = take[take >= 0]
        value = M.pinball_skill(y[take], q[take], b[take]) if len(take) else float("nan")
        if not math.isfinite(value):
            bad += 1
        return value

    low, high = M.block_bootstrap_ci(
        np.arange(len(dates), dtype=float),
        statistic,
        block_length=cfg.block_length,
        n_resamples=cfg.n_bootstrap,
        confidence_level=cfg.confidence_level,
        seed=cfg.seed,
    )
    return (
        _plain(low),
        _plain(high),
        {
            "reason": "nonfinite_replicate" if bad else None,
            "n_replicates": calls,
            "invalid_replicates": bad,
        },
    )


def _accuracy_row(cfg, config_hash, asset, h, sample, metric, value, n, reason=None):
    okay = value is not None and math.isfinite(value)
    return {
        "run_id": cfg.run_id,
        "config_hash": config_hash,
        "model_version": cfg.model_version,
        "asset": asset,
        "sample": sample,
        "evaluation_kind": cfg.evaluation_kind,
        "evaluation_start": cfg.evaluation_start,
        "evaluation_end": cfg.evaluation_end,
        "target_cutoff_date": cfg.target_cutoff_date,
        "h": h,
        "metric": metric,
        "value": float(value) if okay else None,
        "ci_low": None,
        "ci_high": None,
        "n_obs": int(n),
        "status": "ok" if okay else "undefined",
        "undefined_reason": None
        if okay
        else reason or ("no_evaluable_obs" if not n else "zero_denominator"),
    }


def _summarize(detail, cfg, config_hash):
    dates, plan = shared_bootstrap_plan(cfg)
    records = []
    comparisons = []
    counters = []
    ci_log = []
    dm_log = []
    for asset in ASSET_NAMES:
        for h in HORIZONS:
            all_rows = detail.loc[(detail.asset == asset) & (detail.h == h)].sort_values(
                "base_date"
            )
            for sample in ("all", "excl_roll") if asset in ("brent", "wti") else ("all",):
                common = all_rows["common_mask_" + sample].fillna(False).to_numpy(bool)
                g = all_rows.loc[common]
                y = g.y_true.to_numpy(float)
                q = g[list(QCOLS)].to_numpy(float)
                b = g[list(BCOLS)].to_numpy(float)
                prob = g.prob_up.to_numpy(float)
                bp = g.baseline_prob_up.to_numpy(float)
                n = len(g)
                values = {}
                if n:
                    half = B.constant_prob_baseline(g.index).to_numpy(float)
                    values = {
                        "pinball_loss": M.mean_pinball_loss(y, q),
                        "pinball_skill": M.pinball_skill(y, q, b),
                        "coverage_80": M.coverage_80(y, q[:, 1], q[:, 5]),
                        "width_80": M.width_80(q[:, 1], q[:, 5]),
                        "interval_score_80": M.interval_score_80(y, q[:, 1], q[:, 5]),
                        "brier_score": M.brier_score(prob, y),
                        "brier_skill": M.brier_skill(prob, y, bp),
                        "brier_skill_vs_half": M.brier_skill(prob, y, half),
                        "mae_ratio_vs_naive": M.mae_ratio_vs_naive(y, q[:, 3], np.zeros(n)),
                        "sign_accuracy": M.sign_accuracy(y, q[:, 3]),
                        "up_rate": M.up_rate(y),
                    }
                    values.update(
                        {
                            f"quantile_hit_{tau:.2f}": value
                            for tau, value in M.quantile_hit_rates(y, q).items()
                        }
                    )
                else:
                    values = {
                        name: None
                        for name in [
                            "pinball_loss",
                            "pinball_skill",
                            "coverage_80",
                            "width_80",
                            "interval_score_80",
                            "brier_score",
                            "brier_skill",
                            "brier_skill_vs_half",
                            "mae_ratio_vs_naive",
                            "sign_accuracy",
                            "up_rate",
                            *[f"quantile_hit_{tau:.2f}" for tau in QUANTILE_LEVELS],
                        ]
                    }
                for metric, value in values.items():
                    used = (
                        int(((y != 0) & (q[:, 3] != 0)).sum())
                        if n and metric == "sign_accuracy"
                        else n
                    )
                    row = _accuracy_row(cfg, config_hash, asset, h, sample, metric, value, used)
                    if metric == "pinball_skill" and row["status"] == "ok":
                        low, high, info = _skill_ci(g, dates, plan, cfg)
                        row.update(ci_low=low, ci_high=high)
                        ci_log.append({"asset": asset, "h": h, "sample": sample, **info})
                    records.append(row)
                raw = all_rows.loc[all_rows.crossed_raw.notna(), "crossed_raw"].to_numpy(bool)
                crossing = _accuracy_row(
                    cfg,
                    config_hash,
                    asset,
                    h,
                    sample,
                    "crossing_rate",
                    M.crossing_rate(raw) if sample == "all" else None,
                    len(raw) if sample == "all" else 0,
                )
                if sample == "excl_roll":
                    crossing.update(status="not_applicable", undefined_reason="unsupported_sample")
                records.append(crossing)
                primary = Counter(
                    all_rows.loc[~all_rows.common_mask_all, "exclusion_reason"].dropna()
                )
                c = {
                    "asset": asset,
                    "h": h,
                    "sample": sample,
                    "n_expected": len(all_rows),
                    "n_received": int(all_rows.forecast_status.ne("no_forecast_row").sum()),
                    "n_common": n,
                    "n_forecast_ok": int(all_rows.forecast_valid.sum()),
                    "n_excluded": len(all_rows) - n,
                    "excluded_by_primary_reason": dict(primary),
                    "excluded_target_boundary": primary["outside_target_cutoff"],
                    "excluded_missing_price": primary["invalid_target"],
                    "excluded_invalid_input_window": primary["invalid_input_window"],
                    "excluded_insufficient_baseline": primary["insufficient_baseline"],
                    "excluded_roll": 0,
                    "excluded_unknown_roll": 0,
                }
                if sample == "excl_roll":
                    base_common = all_rows.common_mask_all
                    c["excluded_roll"] = int(
                        (base_common & all_rows.roll_in_horizon.eq(True)).sum()
                    )
                    c["excluded_unknown_roll"] = int(
                        (base_common & all_rows.roll_in_horizon.isna()).sum()
                    )
                    primary["roll_window"] = c["excluded_roll"]
                    primary["unknown_roll"] = c["excluded_unknown_roll"]
                    c["excluded_by_primary_reason"] = dict(primary)
                counters.append(c)
                a = g.model_pinball_loss.to_numpy(float)
                bb = g.baseline_pinball_loss.to_numpy(float)
                gaps = _dm_session_gaps(g, asset, cfg)
                blocked = h > 1 and gaps > 0
                if blocked:
                    stat, p = float("nan"), float("nan")
                else:
                    stat, p = M.diebold_mariano(a, bb, h=h, hac_lag=h - 1)
                dm_log.append(
                    {
                        "asset": asset,
                        "h": h,
                        "sample": sample,
                        "internal_missing_sessions": gaps,
                        "n_pairs": n,
                        "blocked": blocked,
                        "blocker": "Khải must decide calendar-gap HAC/HLN semantics; PR11 accepts only dense vectors"
                        if blocked
                        else None,
                    }
                )
                okay = math.isfinite(stat) and math.isfinite(p)
                comparisons.append(
                    {
                        "run_id": cfg.run_id,
                        "config_hash": config_hash,
                        "asset": asset,
                        "sample": sample,
                        "evaluation_kind": cfg.evaluation_kind,
                        "evaluation_start": cfg.evaluation_start,
                        "evaluation_end": cfg.evaluation_end,
                        "target_cutoff_date": cfg.target_cutoff_date,
                        "h": h,
                        "model_a": cfg.model_version,
                        "model_b": "baseline-252",
                        "loss": "pinball",
                        "dm_stat": _plain(stat),
                        "p_value": _plain(p),
                        "p_value_holm": None,
                        "hac_lag": h - 1,
                        "n_obs": n,
                        "status": "ok" if okay else "undefined",
                        "undefined_reason": None
                        if okay
                        else (
                            "missing_paired_loss"
                            if blocked
                            else "insufficient_pairs"
                            if n <= h
                            else "nonpositive_hac_variance"
                        ),
                    }
                )
    comparison = pd.DataFrame(comparisons)
    for sample, size in [("all", 28), ("excl_roll", 14)]:
        mask = comparison["sample"].eq(sample)
        if int(mask.sum()) != size:
            raise ValueError("Holm family has wrong number of slots")
        comparison.loc[mask, "p_value_holm"] = M.holm_adjust(
            comparison.loc[mask, "p_value"].to_numpy(float)
        )
    return (
        pd.DataFrame(records),
        comparison,
        {
            "counters": counters,
            "confidence_intervals": ci_log,
            "dm_calendar_gaps": dm_log,
            "bootstrap_plan": {
                "calendar": "sorted union NYSE/CME sessions",
                "n_dates": len(dates),
                "shape": list(plan.shape),
                "sha256": hashlib.sha256(plan.tobytes()).hexdigest(),
                "date_sha256": hashlib.sha256(dates.to_numpy().tobytes()).hexdigest(),
            },
            "holm_families": {"all": 28, "excl_roll": 14},
        },
    )


def evaluate(forecasts, prices, rejected, fits, cfg=None, *, input_lineage=None):
    """Evaluate saved Internal Forecasts without invoking any model or normalizer."""
    cfg = cfg or EvaluationConfig()
    _fits(fits, cfg)
    p, r = _inputs(prices, rejected, cfg)
    clean, join_log = _validate_forecasts(forecasts, p, r, fits, cfg)
    identity = _evaluation_identity(cfg, fits, p, r, clean, input_lineage)
    config_hash = _digest(identity)
    detail = _make_detail(clean, p, r, fits, cfg, config_hash)
    accuracy, comparison, log = _summarize(detail, cfg, config_hash)
    log.update(join_log)
    log["generation_errors"] = forecasts.attrs.get("generation_errors", [])
    manifest = {
        "run_id": cfg.run_id,
        "forecast_run_id": cfg.forecast_run_id,
        "model_version": cfg.model_version,
        "config_hash": config_hash,
        "config": asdict(cfg),
        "implementation": identity["implementation"],
        "input_lineage": identity["input_lineage"],
        "run_identity_policy": "run_id binds config, validated forecasts, input lineage and implementation; changes require a new run_id",
        "dm_gap_policy": DM_GAP_POLICY,
        "dm_blocked_groups": [row for row in log["dm_calendar_gaps"] if row["blocked"]],
        "fits": fits,
        "provenance_status": PROVENANCE,
        "historical_vintage_limitation": LIMITATION,
        "calendar_versions": {
            "module_sha256": hashlib.sha256(Path(calendars.__file__).read_bytes()).hexdigest(),
            "pandas_market_calendars": version("pandas_market_calendars"),
        },
        "publication_rules": PUBLISHED_AT_RULES,
        "bootstrap": log["bootstrap_plan"],
        "ci_scope": "pinball_skill only; other metric CIs deferred phase 2",
        "roll_calendar_limitation": "Brent London business days approximated by existing CME calendar.",
        "holm_families": log["holm_families"],
        "counters": log["counters"],
    }
    return EvaluationResult(detail, accuracy, comparison, manifest, log)


def check_inputs(clean_dir, model_root, cfg):
    prices, rejected, quality, hashes = load_clean_snapshot(clean_dir)
    models = load_models(model_root, cfg, hashes)
    p, r = _inputs(prices, rejected, cfg)
    checks = []
    for asset, bundle in models.items():
        batch = _feature_batch(p, r, asset, cfg)
        available = np.array(
            [
                not np.isnat(t)
                and t <= publication_time(asset, d).tz_localize(None).to_datetime64()
                for d, t in zip(batch.base_dates, batch.max_input_published_at, strict=True)
            ]
        )
        selected = np.flatnonzero(batch.valid & available)
        if not len(selected):
            raise ValueError(f"{asset}: no valid publication-safe validation windows")
        raw = np.asarray(bundle.model.predict(batch.X[selected[:1]]), dtype=float)
        if raw.shape != (1, 7, 7) or not np.isfinite(raw).all():
            raise ValueError(f"{asset}: inference smoke failed")
        q, crossed = normalize_quantiles(raw)
        for row in q[0]:
            prob_up(row)
        checks.append(
            {
                "asset": asset,
                "expected_origins": len(batch),
                "valid_windows": len(selected),
                "smoke_crossed": int(crossed.sum()),
            }
        )
    return prices, rejected, quality, hashes, models, checks


def run_validation(clean_dir, model_root, output_dir, cfg=None, *, run_registry_dir=None):
    cfg = cfg or EvaluationConfig()
    directory = Path(output_dir)
    if directory.exists():
        raise FileExistsError(directory)
    prices, rejected, quality, hashes, models, checks = check_inputs(clean_dir, model_root, cfg)
    forecasts = generate_forecasts(prices, rejected, models, cfg)
    fits = {a: b.manifest for a, b in models.items()}
    lineage = {
        "snapshot_date": SNAPSHOT_DATE,
        "snapshot_files_sha256": {
            name: hashlib.sha256((Path(clean_dir) / name).read_bytes()).hexdigest()
            for name in ("prices.parquet", "rejected.parquet", "quality.json")
        },
        "model_files_sha256": {
            f"{asset}/{cfg.model_version}/{name}": hashlib.sha256(
                (Path(model_root) / asset / cfg.model_version / name).read_bytes()
            ).hexdigest()
            for asset in ASSET_NAMES
            for name in ("weights.npz", "scaler.json", "config.json", "manifest.json")
        },
    }
    result = evaluate(forecasts, prices, rejected, fits, cfg, input_lineage=lineage)
    result.manifest.update(
        snapshot_date=SNAPSHOT_DATE,
        snapshot_sha256=hashes,
        snapshot_quality_status=quality.get("status"),
        input_checks=checks,
    )
    registry = (
        Path(run_registry_dir)
        if run_registry_dir is not None
        else directory.parent / ".evaluation-runs"
    )
    _claim_run(registry, result.manifest)
    result.manifest["run_registry_scope"] = str(registry.resolve())
    directory.mkdir(parents=True, exist_ok=False)
    for name, frame in [
        ("forecasts", forecasts),
        ("detail", result.detail),
        ("accuracy", result.accuracy),
        ("model_comparison", result.model_comparison),
    ]:
        frame.to_parquet(directory / (name + ".parquet"), index=False)
    for name, value in [("evaluation_manifest", result.manifest), ("evaluation_log", result.log)]:
        (directory / (name + ".json")).write_text(
            json.dumps(_plain(value), indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-dir", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--model-version", default="dlinear-41e13dc5de3d")
    parser.add_argument("--run-id", default="validation-2019")
    parser.add_argument("--forecast-run-id", default="dlinear-2019-forecasts")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--evaluation-as-of-time",
        required=True,
        help="Fixed timezone-aware timestamp, retained for every replay of this run",
    )
    parser.add_argument(
        "--run-registry-dir",
        type=Path,
        help="Shared local immutable run registry; defaults to output parent/.evaluation-runs",
    )
    parser.add_argument("--check-inputs", action="store_true")
    args = parser.parse_args(argv)
    cfg = EvaluationConfig(
        run_id=args.run_id,
        forecast_run_id=args.forecast_run_id,
        model_version=args.model_version,
        seed=args.seed,
        evaluation_as_of_time=args.evaluation_as_of_time,
    )
    if args.check_inputs:
        *_, checks = check_inputs(args.clean_dir, args.model_root, cfg)
        print(json.dumps({"checks": checks, "provenance": PROVENANCE, "limitation": LIMITATION}))
    else:
        if args.output_dir is None:
            parser.error("--output-dir is required unless --check-inputs")
        result = run_validation(
            args.clean_dir,
            args.model_root,
            args.output_dir,
            cfg,
            run_registry_dir=args.run_registry_dir,
        )
        print(
            json.dumps(
                {
                    "forecasts": len(result.detail),
                    "accuracy_rows": len(result.accuracy),
                    "comparison_rows": len(result.model_comparison),
                    "output_dir": str(args.output_dir),
                    "provenance": PROVENANCE,
                }
            )
        )


if __name__ == "__main__":
    main()

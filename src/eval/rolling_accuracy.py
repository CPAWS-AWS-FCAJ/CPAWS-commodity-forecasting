"""RFC45 v4.6 pure rolling evaluation; no AWS, SciPy, training or publication writes."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data import calendars
from src.data.config import ASSETS, PUBLISHED_AT_RULES
from src.forecast.baselines import baseline_valid, quantile_baseline
from src.forecast.forecast_record import TARGET_SERIES, target_dates
from src.forecast.returns import QUANTILE_LEVELS, horizon_log_returns, prob_up

ASSET_NAMES = tuple(TARGET_SERIES)
METRICS = ("coverage_80", "width_80", "sign_accuracy", "up_rate")
DISCLAIMER = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."


class NotReady(RuntimeError):
    """Source cannot support a consistent evaluation; never publish this run."""


def day(value: str) -> str:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("expected ISO date")
    ts = pd.Timestamp(value)
    if pd.isna(ts) or ts.tzinfo or value != ts.date().isoformat():
        raise ValueError("expected ISO date")
    return value


def utc(value: Any) -> pd.Timestamp:
    if value is None:
        raise ValueError("missing UTC timestamp")
    ts = pd.Timestamp(value)
    if pd.isna(ts) or ts.tzinfo is None or ts.utcoffset().total_seconds() != 0:
        raise ValueError("expected explicit UTC timestamp")
    return ts.tz_convert("UTC")


def canonical(value: Any) -> bytes:
    """Canonical numbers equal across DynamoDB Decimal/JSON float round-trips."""

    def encode(v):
        if isinstance(v, dict):
            return {str(k): encode(x) for k, x in sorted(v.items())}
        if isinstance(v, (list, tuple)):
            return [encode(x) for x in v]
        if isinstance(v, (float, Decimal, int)) and not isinstance(v, bool):
            d = Decimal(str(v))
            if not d.is_finite():
                raise ValueError("nonfinite number")
            return {"$number": format(d.normalize(), "f") if d else "0"}
        if isinstance(v, (pd.Timestamp,)):
            return v.isoformat()
        return v

    return json.dumps(
        encode(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def source_digest(value: Any) -> str:
    """Bind invalid numeric input without allowing NaN into any metric payload."""

    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        if isinstance(v, (float, Decimal)) and not Decimal(str(v)).is_finite():
            return {"$invalid_numeric": str(v)}
        return v

    return digest(clean(value))


def implementation_identity() -> dict:
    root = Path(__file__).parents[1]
    files = [
        *sorted((root / "eval").glob("rolling_*.py")),
        root / "eval/lambda_accuracy.py",
        root / "data/calendars.py",
        root / "data/config.py",
        root / "forecast/returns.py",
        root / "forecast/baselines.py",
        root / "forecast/forecast_record.py",
    ]
    return {
        "code_sha256": {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
        "libraries": {
            n: version(n)
            for n in ("numpy", "pandas", "pandas_market_calendars", "pyarrow", "boto3")
        },
        "publication_rules": PUBLISHED_AT_RULES,
    }


@dataclass(frozen=True)
class Config:
    asset: str
    model: str
    effective: str
    job_date: str
    as_of: str
    revision: int = 0

    def __post_init__(self):
        if self.asset not in ASSET_NAMES or not isinstance(self.model, str) or not self.model:
            raise ValueError("invalid asset/model")
        day(self.effective)
        day(self.job_date)
        if utc(self.as_of).date().isoformat() != self.job_date:
            raise ValueError("as_of must belong to job UTC date")
        if type(self.revision) is not int or not 0 <= self.revision <= 9999:
            raise ValueError("revision must be 0..9999")

    @property
    def start(self):
        return (pd.Timestamp(self.job_date) - pd.Timedelta(days=55)).date().isoformat()


def expected_dates(cfg: Config) -> list[str]:
    """One base session per next-calendar-day Predict opportunity, never per invocation."""
    start = max(cfg.start, cfg.effective, "2026-10-26")
    dates = calendars.sessions(ASSETS[cfg.asset].calendar, start, cfg.job_date)
    result = []
    for d in dates:
        issued_day = d + pd.Timedelta(days=1)
        if issued_day.weekday() in range(1, 6) and issued_day.date().isoformat() <= cfg.job_date:
            result.append(d.date().isoformat())
    return result


def price_frame(prices: pd.DataFrame, rejected: pd.DataFrame, asset: str) -> pd.DataFrame:
    required = {"asset", "date", "price", "source", "published_at"}
    if not required <= set(prices) or not {"asset", "date"} <= set(rejected):
        raise NotReady("invalid clean snapshot schema")
    p = prices.loc[prices.asset.eq(asset)].copy()
    p["date"] = p.date.map(lambda x: day(pd.Timestamp(x).date().isoformat()))
    if p.date.duplicated().any() or not p.source.eq(ASSETS[asset].primary.source).all():
        raise NotReady("ambiguous target prices")
    p["published_at"] = p.published_at.map(utc)
    p["price"] = pd.to_numeric(p.price, errors="raise")
    bad = set(
        pd.to_datetime(rejected.loc[rejected.asset.eq(asset), "date"]).dt.strftime("%Y-%m-%d")
    )
    p["valid"] = np.isfinite(p.price) & p.price.gt(0) & ~p.date.isin(bad)
    return p.set_index("date").sort_index()


def validate_record(record: dict, cfg: Config, model: str | None = None) -> list[dict]:
    """Validate complete envelope, then each horizon; never normalize or overwrite source."""
    base = day(record.get("base_date"))
    created = utc(record.get("created_at"))
    if (
        record.get("asset") != cfg.asset
        or record.get("model_version") != (model or cfg.model)
        or record.get("target_series") != TARGET_SERIES[cfg.asset]
        or record.get("is_sample") is not False
    ):
        raise ValueError("invalid_forecast_identity")
    if not max(cfg.start, cfg.effective) <= base <= cfg.job_date:
        raise ValueError("outside_window_or_effective_date")
    if not utc("2026-10-27T12:00:00Z") <= created <= utc(cfg.as_of):
        raise ValueError("invalid_issuance_time")
    if not np.array_equal(np.asarray(record.get("quantile_levels"), float), QUANTILE_LEVELS):
        raise ValueError("invalid_quantile_levels")
    hs = record.get("horizons")
    if not isinstance(hs, list) or len(hs) != 7:
        raise ValueError("invalid_horizon_set")
    ids = [x.get("h") for x in hs]
    if any(isinstance(h, (bool, str)) or h not in range(1, 8) for h in ids) or set(ids) != set(
        range(1, 8)
    ):
        raise ValueError("invalid_horizon_set")
    targets = target_dates(cfg.asset, base)
    rows = []
    for item in sorted(hs, key=lambda x: x["h"]):
        h = int(item["h"])
        q = np.asarray(item.get("q"), dtype=float)
        p = float(item.get("prob_up"))
        if q.shape != (7,) or not np.isfinite(q).all() or np.any(np.diff(q) < 0):
            raise ValueError("invalid_quantiles")
        if not math.isfinite(p) or not 0.05 <= p <= 0.95:
            raise ValueError("invalid_prob_up")
        target = day(item.get("target_date"))
        if target != targets[h - 1]:
            raise ValueError("target_calendar_mismatch")
        rows.append(
            {
                "base_date": base,
                "h": h,
                "target_date": target,
                "q": q.tolist(),
                "created_at": created.isoformat(),
                "record_digest": digest(record),
                "warning": "prob_up_mismatch" if abs(float(prob_up(q)) - p) > 1e-6 else None,
            }
        )
    return rows


def summarize(rows: list[dict], overall: bool = False) -> dict:
    n = len(rows)
    dates = len({r["base_date"] for r in rows})
    hit = sum(r["q"][1] <= r["y"] <= r["q"][5] for r in rows)
    signs = [r for r in rows if r["y"] != 0 and r["q"][3] != 0]
    values = {
        "coverage_80": hit / n if n else None,
        "width_80": math.fsum(r["q"][5] - r["q"][1] for r in rows) / n if n else None,
        "width_80_pct": math.fsum(100 * (math.exp(r["q"][5]) - math.exp(r["q"][1])) for r in rows)
        / n
        if n
        else None,
        "sign_accuracy": sum((r["y"] > 0) == (r["q"][3] > 0) for r in signs) / len(signs)
        if signs
        else None,
        "up_rate": sum(r["y"] > 0 for r in rows) / n if n else None,
    }
    result = {}
    for name, value in values.items():
        count = len(signs) if name == "sign_accuracy" else n
        if value is not None and not math.isfinite(value):
            raise ValueError("nonfinite metric result")
        result[name] = {
            "value": value,
            "n_obs": count,
            "status": "ok" if value is not None else "undefined",
            "undefined_reason": None if value is not None else "no_evaluable_obs",
        }
        if name == "coverage_80":
            result[name].update(covered_count=hit, n_base_dates=dates)
        if name.startswith("width"):
            result[name]["unit"] = "percent" if name.endswith("pct") else "log_return"
    return result


def baseline_at(input_prices: pd.DataFrame, base: str, h: int) -> list[float] | None:
    """Use repository causal baseline on the issuance snapshot, not revised future data."""
    p = input_prices.loc[input_prices.index <= base]
    series = pd.Series(p.price.where(p.valid).to_numpy(), index=pd.DatetimeIndex(p.index))
    asset = p.asset.iloc[0]
    ret = horizon_log_returns(series, h, calendar=ASSETS[asset].calendar)
    key = pd.Timestamp(base)
    if key not in ret.index or not baseline_valid(ret, h).loc[key]:
        return None
    q = quantile_baseline(ret, h).loc[key].to_numpy(float)
    return q.tolist() if np.isfinite(q).all() else None


def evaluate(records: list[dict], actual, cfg: Config, evidence_for) -> dict:
    """evidence_for(record) returns verified input frame + audit lineage or rejects.

    Actual and input bundles are supplied by rolling_sources. Missing evidence is a
    row exclusion; unreadable/inconsistent actual source raises NotReady.
    """
    records = sorted(records, key=source_digest)
    prices = price_frame(actual.prices, actual.rejected, cfg.asset)
    available = prices.loc[prices.valid & prices.published_at.le(utc(cfg.as_of))]
    available = available.loc[available.index <= cfg.job_date]
    if available.empty:
        raise NotReady("actual_source_unavailable")
    cutoff = available.index.max()
    expected = expected_dates(cfg)
    published = {r.get("base_date") for r in records} & set(expected)
    counts = {
        "expected_count": len(expected),
        "published_count": len(published),
        "missing_count": len(expected) - len(published),
    }
    seen = Counter(r.get("base_date") for r in records)
    rows, lineage = [], []
    audit = [
        {"base_date": base, "reason": "missing_record_unclassified"}
        for base in expected
        if base not in published
    ]
    for record in sorted(records, key=lambda r: str(r.get("base_date"))):
        try:
            if seen[record.get("base_date")] != 1:
                raise ValueError("duplicate_forecast_key")
            candidates = validate_record(record, cfg)
            inp, proof = evidence_for(record)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            audit.append({"base_date": str(record.get("base_date")), "reason": str(exc)[:100]})
            continue
        lineage.append(proof)
        for item in candidates:
            if item["warning"]:
                audit.append(
                    {"base_date": item["base_date"], "h": item["h"], "reason": item["warning"]}
                )
        for row in candidates:
            base, target, h = row["base_date"], row["target_date"], row["h"]
            reason = None
            created = utc(row["created_at"])
            if target > cutoff:
                reason = "target_pending"
            elif (
                base not in prices.index
                or target not in prices.index
                or not (prices.loc[base, "valid"] and prices.loc[target, "valid"])
            ):
                reason = "invalid_endpoint"
            elif prices.loc[target, "published_at"] > utc(cfg.as_of):
                reason = "label_not_available"
            elif created >= min(utc(target + "T13:30:00Z"), prices.loc[target, "published_at"]):
                reason = "late_issuance"
            elif base not in inp.index or float(inp.loc[base, "price"]) != float(
                prices.loc[base, "price"]
            ):
                reason = "base_price_revision_mismatch"
            elif prices.loc[base, "published_at"] > created:
                reason = "base_not_available"
            if reason:
                audit.append({"base_date": base, "h": h, "reason": reason})
                continue
            baseline = baseline_at(inp, base, h)
            if baseline is None:
                audit.append(
                    {"base_date": base, "h": h, "reason": "excluded_insufficient_baseline"}
                )
                continue
            middle = calendars.sessions(ASSETS[cfg.asset].calendar, base, target)[1:-1]
            row.update(
                y=math.log(float(prices.loc[target, "price"]) / float(prices.loc[base, "price"])),
                baseline_q=baseline,
                target_published_at=prices.loc[target, "published_at"].isoformat(),
                missing_between_count=sum(
                    d.date().isoformat() not in prices.index
                    or not prices.loc[d.date().isoformat(), "valid"]
                    for d in middle
                ),
                input_lineage=proof,
            )
            rows.append(row)
    overall = summarize(rows, True)
    by_h = [{"h": h, **summarize([r for r in rows if r["h"] == h])} for h in range(1, 8)]
    config = {
        "asset": cfg.asset,
        "model_version": cfg.model,
        "effective": cfg.effective,
        "as_of": cfg.as_of,
        "implementation": implementation_identity(),
    }
    config_hash = digest(config)
    identity = {
        "asset": cfg.asset,
        "model_version": cfg.model,
        "effective": cfg.effective,
        "job_date": cfg.job_date,
        "revision": cfg.revision,
        "config_hash": config_hash,
        "snapshot": actual.identity,
        "target_cutoff_date": cutoff,
        "eligible_record_fingerprint": digest(
            [{"record": r["record_digest"], "h": r["h"], "input": r["input_lineage"]} for r in rows]
        ),
    }
    # Include audit/count inputs too: changed excluded rows must not reuse a run identity.
    identity["source_fingerprint"] = source_digest(
        {"records": records, "audit": audit, "counts": counts}
    )
    run_id = cfg.job_date + "-" + digest(identity)[:20]
    return {
        "run_id": run_id,
        "run_order": cfg.job_date.replace("-", "") + f"#{cfg.revision:04d}",
        "asset": cfg.asset,
        "model_version": cfg.model,
        "effective": cfg.effective,
        "evaluation_kind": "rolling_8w",
        "sample": "all",
        "evaluated_at": cfg.as_of,
        "config_hash": config_hash,
        "identity": identity,
        "implementation": config["implementation"],
        "window": {
            "basis": "base_date",
            "days": 56,
            "window_start": cfg.start,
            "window_end": cfg.job_date,
            "target_cutoff_date": cutoff,
            "first_eligible_base_date": min((r["base_date"] for r in rows), default=None),
        },
        "last_eligible_base_date": max((r["base_date"] for r in rows), default=None),
        "evaluation_evidence": {
            "schedule_basis": "trading_calendar_and_predict_schedule",
            "schedule_evidence_status": "not_audited_mvp",
            "issuance_evidence_status": "verified_eligible_rows" if rows else "no_eligible_rows",
            **counts,
        },
        "overall": overall,
        "by_horizon": by_h,
        "observations": rows,
        "audit": audit,
        "input_lineage": lineage,
        "actual_lineage": actual.identity,
    }


def response_payload(result: dict | None, asset: str, model: str) -> dict:
    """Pure projection for Tuấn's reader integration/tests; not a public Lambda."""
    ready_run = result is not None and result["asset"] == asset and result["model_version"] == model
    if not ready_run:
        result = {
            "run_id": None,
            "evaluated_at": None,
            "window": {
                "basis": "base_date",
                "days": 56,
                "window_start": None,
                "window_end": None,
                "target_cutoff_date": None,
                "first_eligible_base_date": None,
            },
            "evaluation_evidence": {
                "schedule_basis": "trading_calendar_and_predict_schedule",
                "schedule_evidence_status": "not_audited_mvp",
                "issuance_evidence_status": "no_completed_run",
                "expected_count": None,
                "published_count": None,
                "missing_count": None,
            },
            "overall": summarize([]),
            "by_horizon": [{"h": h, **summarize([])} for h in range(1, 8)],
        }
    enough = result["overall"]["coverage_80"]["n_base_dates"] >= 20
    state = "not_ready" if not ready_run else "ready" if enough else "collecting"

    def project(group, overall):
        output = {}
        for metric in (*METRICS, "width_80_pct"):
            m = {k: v for k, v in group[metric].items() if k != "undefined_reason"}
            status = (
                (
                    "not_ready"
                    if not ready_run
                    else "insufficient_data"
                    if not enough
                    else "ready"
                    if m["status"] == "ok"
                    else "undefined"
                )
                if overall
                else "counts_only"
            )
            m.update(
                display_status=status,
                display_value=round(m["value"], 6) if status == "ready" else None,
            )
            if metric == "coverage_80":
                del m["value"]
                if overall:
                    m["min_display_base_dates"] = 20
            elif m["value"] is not None:
                m["value"] = round(m["value"], 6)
            output[metric] = m
        return output

    return {
        "asset": asset,
        "model_version": model,
        "evaluation_kind": "rolling_8w",
        "sample": "all",
        **{k: result[k] for k in ("run_id", "evaluated_at", "window", "evaluation_evidence")},
        "overall": project(result["overall"], True),
        "by_horizon": [{"h": h["h"], **project(h, False)} for h in result["by_horizon"]],
        "data_status": state,
        "disclaimer": DISCLAIMER,
    }

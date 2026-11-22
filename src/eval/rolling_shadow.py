"""Independent S1a paired comparison; no Accuracy table writes or champion mutation."""

from __future__ import annotations

import io
import json
import math

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.eval.rolling_accuracy import digest, summarize, utc, validate_record
from src.eval.rolling_sources import approved
from src.forecast.forecast_record import TARGET_SERIES, to_decimal
from src.forecast.returns import QUANTILE_LEVELS


def pinball(y, q):
    err = float(y) - np.asarray(q, float)
    levels = np.asarray(QUANTILE_LEVELS, float)
    return float(np.maximum(levels * err, (levels - 1) * err).mean())


def compare(result: dict, cfg, sources, evidence) -> dict:
    if cfg.model != "baseline-q252":
        return {"status": "shadow_not_applicable_model_change", "paired_n_obs": 0}
    policy = evidence.config.get("shadow_release", {})
    if not approved(policy) or policy.get("immutable_write") is not True:
        return {"status": "shadow_not_ready", "paired_n_obs": 0}
    if utc(policy["approved_at"]) > utc(cfg.as_of):
        return {"status": "shadow_not_ready", "paired_n_obs": 0}
    candidates, excluded, source_refs = {}, [], []
    observations = result["observations"]
    # dt is a run day, not the champion issuance date or forecast base_date.
    # Bound probes by real champion publication and evaluation as-of; no ListBucket scan.
    issuance_days = {utc(r["created_at"]).normalize() for r in observations}
    dates = []
    if issuance_days:
        dates = [
            d.date().isoformat()
            for d in pd.date_range(min(issuance_days), utc(cfg.as_of).normalize())
            if d.weekday() in range(1, 6) or d in issuance_days
        ]
    for date in dates:
        try:
            obj = sources.shadow(cfg.asset, date)
            if obj is None:
                continue
            record, ref = obj
            source_refs.append(ref)
            created, modified = utc(record["created_at"]), utc(ref["last_modified"])
            if not utc(policy["deployed_at"]) <= created <= modified <= utc(cfg.as_of):
                raise ValueError("shadow_publication_unverified")
            if not math.isfinite(float(record["shadow"]["k"])) or float(record["shadow"]["k"]) <= 0:
                raise ValueError("invalid_k")
            if record["shadow"].get("champion_model_version") != cfg.model:
                raise ValueError("shadow_champion_mismatch")
            _, proof = evidence.for_record(record, shadow=True)
            validated = validate_record(record, cfg, model="s1a-l094")
            for row in validated:
                key = (
                    record["asset"],
                    row["base_date"],
                    row["h"],
                    row["target_date"],
                    record["target_series"],
                )
                candidates.setdefault(key, []).append(
                    (row, ref, proof, record["input_snapshot_dt"])
                )
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            excluded.append({"dt": date, "reason": str(exc)[:100]})
    pairs = []
    for champion in observations:
        key = (
            cfg.asset,
            champion["base_date"],
            champion["h"],
            champion["target_date"],
            TARGET_SERIES[cfg.asset],
        )
        valid = []
        for shadow, ref, proof, snapshot_dt in candidates.get(key, []):
            reason = None
            if (
                snapshot_dt != champion["input_lineage"]["snapshot"]["dt"]
                or proof["snapshot"] != champion["input_lineage"]["snapshot"]
            ):
                reason = "input_snapshot_mismatch"
            elif utc(ref["last_modified"]) >= min(
                utc(champion["target_published_at"]), utc(champion["target_date"] + "T13:30:00Z")
            ):
                reason = "shadow_late_write"
            elif to_decimal(shadow["q"][3]) != to_decimal(champion["q"][3]):
                reason = "s1a_median_mismatch"
            elif [to_decimal(q) for q in champion["q"]] != [
                to_decimal(q) for q in champion["baseline_q"]
            ]:
                reason = "baseline_representation_mismatch"
            if reason:
                excluded.append(
                    {
                        "base_date": champion["base_date"],
                        "h": champion["h"],
                        "key": ref["key"],
                        "reason": reason,
                    }
                )
            else:
                valid.append((shadow, ref))
        if not valid:
            excluded.append(
                {"base_date": champion["base_date"], "h": champion["h"], "reason": "shadow_missing"}
            )
            continue
        # Deterministic tie-break only among fully eligible, matching-snapshot objects.
        # Earliest actual S3 issuance wins; key resolves equal timestamps. One pair only.
        shadow, ref = min(valid, key=lambda item: (utc(item[1]["last_modified"]), item[1]["key"]))
        pairs.append(
            (
                champion,
                {
                    **champion,
                    "q": shadow["q"],
                    "record_digest": shadow["record_digest"],
                    "shadow_object": ref,
                },
            )
        )
    refs = {
        "champion_run": result["run_id"],
        "actual": result["actual_lineage"],
        "shadow_objects": source_refs,
        "release_evidence": policy,
        "pairs": [
            {
                "base_date": a["base_date"],
                "h": a["h"],
                "champion": a["record_digest"],
                "shadow": b["record_digest"],
                "shadow_object": b["shadow_object"],
            }
            for a, b in pairs
        ],
    }
    comparison_id = digest(refs)
    metrics = []
    for scope in [*range(1, 8), "overall"]:
        selected = [p for p in pairs if scope == "overall" or p[0]["h"] == scope]
        n = len(selected)
        # Validated q6 champion representation is also the baseline denominator.
        denominator = math.fsum(pinball(a["y"], a["q"]) for a, _ in selected) / n if n else None
        for side, model in [(0, cfg.model), (1, "s1a-l094")]:
            rows = [p[side] for p in selected]
            summary = summarize(rows)
            loss = math.fsum(pinball(r["y"], r["q"]) for r in rows) / n if n else None
            reason = (
                "no_evaluable_obs" if not n else "zero_denominator" if denominator == 0 else None
            )
            values = {
                "pinball_skill": None if reason else 1 - loss / denominator,
                "coverage_80": summary["coverage_80"]["value"],
                "width_80": summary["width_80"]["value"],
            }
            for metric, value in values.items():
                metrics.append(
                    {
                        "h": str(scope),
                        "model_version": model,
                        "metric": metric,
                        "value": value,
                        "status": "ok" if value is not None else "undefined",
                        "undefined_reason": reason
                        if metric == "pinball_skill"
                        else (None if n else "no_evaluable_obs"),
                        "paired_n_obs": n,
                        "n_base_dates_paired": len({r["base_date"] for r in rows}),
                    }
                )
    return {
        "status": "ok" if pairs else "shadow_not_ready",
        "paired_n_obs": len(pairs),
        "comparison_id": comparison_id,
        "run_id": result["run_id"],
        "asset": cfg.asset,
        "provenance": refs,
        "exclusions": excluded,
        "metrics": metrics,
        "validation_scope": "q50 equality at q6; full scaling requires upstream raw quantiles and k",
    }


def parquet_bytes(report: dict) -> bytes:
    schema = pa.schema(
        [
            ("h", pa.string()),
            ("model_version", pa.string()),
            ("metric", pa.string()),
            ("value", pa.float64()),
            ("status", pa.string()),
            ("undefined_reason", pa.string()),
            ("paired_n_obs", pa.int64()),
            ("n_base_dates_paired", pa.int64()),
        ]
    )
    metadata = {k: v for k, v in report.items() if k != "metrics"}
    table = pa.Table.from_pylist(report["metrics"], schema=schema).replace_schema_metadata(
        {
            b"cpaws": json.dumps(
                metadata, sort_keys=True, ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy", version="2.6")
    return buf.getvalue()


def publish_report(report, sources):
    if "metrics" not in report:
        return None
    key = f"eval/shadow_eval/run_id={report['run_id']}/asset={report['asset']}/comparison_id={report['comparison_id']}.parquet"
    sources.verify_unchanged(report["provenance"]["shadow_objects"])
    return sources.write_shadow(key, parquet_bytes(report))

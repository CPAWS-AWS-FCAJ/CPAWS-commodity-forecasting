"""Lambda entrypoint for Scheduler integration; no infrastructure or public API routes."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import boto3

from src.eval.rolling_accuracy import ASSET_NAMES, Config, NotReady, day, utc
from src.eval.rolling_job import run_asset
from src.eval.rolling_sources import Sources
from src.eval.rolling_store import AccuracyStore

log = logging.getLogger("cpaws.accuracy")
log.setLevel(logging.INFO)


class AccuracyFailed(RuntimeError):
    def __init__(self, summary):
        super().__init__("accuracy assets failed; inspect structured summary")
        self.summary = summary


def parse_config(event, env, now):
    if event is None:
        event = {}
    if not isinstance(event, dict) or set(event) - {"assets", "dry_run", "job_utc_date"}:
        raise ValueError("unsupported event fields")
    dry_run = event.get("dry_run", False)
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be bool")
    if "job_utc_date" in event and not dry_run:
        raise ValueError("historical job date allowed only for dry_run diagnostics")
    names = event.get("assets", list(ASSET_NAMES))
    if (
        not isinstance(names, list)
        or not names
        or len(set(names)) != len(names)
        or any(a not in ASSET_NAMES for a in names)
    ):
        raise ValueError("invalid assets")
    models = json.loads(env["MODEL_VERSIONS"])
    effective = json.loads(env["CHAMPION_EFFECTIVE_BASE_DATES"])
    if (
        not isinstance(models, dict)
        or not isinstance(effective, dict)
        or set(models) != set(ASSET_NAMES)
        or set(effective) != set(ASSET_NAMES)
    ):
        raise ValueError("both mappings must contain exactly four assets")
    for a in ASSET_NAMES:
        if not isinstance(models[a], str) or not models[a].strip():
            raise ValueError("invalid champion")
        day(effective[a])
    for name in ("LAKE_BUCKET", "FORECASTS_TABLE", "ACCURACY_TABLE"):
        if not env.get(name, "").strip():
            raise ValueError("missing " + name)
    date = day(event.get("job_utc_date", utc(now).date().isoformat()))
    as_of = date + "T13:45:00Z"
    if utc(as_of) > utc(now):
        raise ValueError("scheduled evaluation time has not arrived")
    if env.get("ROLLING_EVIDENCE_JSON") and env.get("ROLLING_EVIDENCE_PATH"):
        raise ValueError("choose one evidence source")
    # Reviewed image/layer artifact avoids Lambda's 4 KB environment limit.
    # Content is fingerprinted; caller events cannot select an evidence path.
    evidence_text = (
        Path(env["ROLLING_EVIDENCE_PATH"]).read_text(encoding="utf-8")
        if env.get("ROLLING_EVIDENCE_PATH")
        else env.get("ROLLING_EVIDENCE_JSON", "{}")
    )
    evidence = json.loads(evidence_text)
    if not isinstance(evidence, dict):
        raise TypeError("evidence must be JSON object")
    revision = int(env.get("ROLLING_REVISION", "0"))
    configs = [Config(a, models[a], effective[a], date, as_of, revision) for a in names]
    return configs, evidence, dry_run


def execute(event, env, s3, dynamodb, now):
    configs, evidence, dry_run = parse_config(event, env, now)
    table = dynamodb.Table(env["ACCURACY_TABLE"])
    forecasts = dynamodb.Table(env["FORECASTS_TABLE"])
    summary = {"dry_run": dry_run, "assets": []}
    for cfg in configs:
        sources = Sources(s3, env["LAKE_BUCKET"], forecasts, env.get("LAKE_PREFIX", ""))
        try:
            row = run_asset(cfg, sources, AccuracyStore(table), evidence, dry_run=dry_run)
        except NotReady as exc:
            log.warning("ACCURACY_NOT_READY asset=%s error_type=%s", cfg.asset, type(exc).__name__)
            row = {"asset": cfg.asset, "status": "not_ready", "error_type": type(exc).__name__}
        except Exception as exc:  # noqa: BLE001 -- isolate assets/shadow; report failure explicitly
            log.error("ACCURACY_FAILED asset=%s error_type=%s", cfg.asset, type(exc).__name__)
            row = {"asset": cfg.asset, "status": "FAILED", "error_type": type(exc).__name__}
        summary["assets"].append(row)
    log.info("ACCURACY_DONE %s", summary)
    if not dry_run and any(a["status"] == "FAILED" for a in summary["assets"]):
        raise AccuracyFailed(summary)
    return summary


def handler(event, context=None):
    # Explicit UTC logical schedule makes repeated invocations on the same day deterministic.
    now = datetime.now(UTC)
    parse_config(event, os.environ, now)  # Validate before creating any SDK clients.
    return execute(event, os.environ, boto3.client("s3"), boto3.resource("dynamodb"), now)

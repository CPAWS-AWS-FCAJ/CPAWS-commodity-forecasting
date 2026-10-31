"""Rolling orchestration. Champion commits independently of optional shadow results."""

from __future__ import annotations

import logging

from src.data import calendars
from src.data.config import ASSETS
from src.eval.rolling_accuracy import Config, NotReady, evaluate, utc
from src.eval.rolling_shadow import compare, publish_report
from src.eval.rolling_sources import Evidence, price_frame

log = logging.getLogger("cpaws.accuracy")


def run_asset(
    cfg: Config,
    sources,
    store,
    evidence_config: dict,
    *,
    dry_run=False,
    champion_guard=lambda: True,
    shadow=True,
) -> dict:
    evidence = Evidence(sources, evidence_config, cfg.as_of)
    records = sources.records(cfg.asset, cfg.start, cfg.job_date)
    if not dry_run:
        evidence.require_configured(cfg, records)
    # Today's completed snapshot is mandatory; do not silently fall back to stale input.
    actual = sources.snapshot(cfg.job_date, cfg.as_of)
    if cfg.asset not in actual.quality["assets"] or cfg.asset in (
        actual.quality.get("stale_sources") or {}
    ):
        raise NotReady("asset_snapshot_not_ready")
    prices = price_frame(actual.prices, actual.rejected, cfg.asset)
    expected = (
        calendars.expected_latest_session(ASSETS[cfg.asset].calendar, cfg.job_date)
        .date()
        .isoformat()
    )
    if expected not in prices.index or prices.loc[expected, "published_at"] > utc(cfg.as_of):
        raise NotReady("latest_actual_not_ready")
    result = evaluate(records, actual, cfg, evidence.for_record)
    # All configured approval inputs bind identity even when there are zero eligible pairs.
    from src.eval.rolling_accuracy import digest

    result["identity"]["evidence_config_hash"] = digest(evidence_config)
    result["run_id"] = cfg.job_date + "-" + digest(result["identity"])[:20]
    if not dry_run:
        published = store.publish(result, sources.verify_unchanged, champion_guard)
    else:
        sources.verify_unchanged()
        published = "dry_run"
    summary = {
        "asset": cfg.asset,
        "status": "COMPLETED" if not dry_run else "dry_run",
        "publication": published,
        "run_id": result["run_id"],
        "n_obs": result["overall"]["coverage_80"]["n_obs"],
        "n_base_dates": result["overall"]["coverage_80"]["n_base_dates"],
        "shadow_status": "disabled",
    }
    if shadow:
        try:
            report = compare(result, cfg, sources, evidence)
            if not dry_run:
                publish_report(report, sources)
            summary.update(shadow_status=report["status"], paired_n_obs=report["paired_n_obs"])
        except Exception as exc:  # noqa: BLE001 -- isolate assets/shadow; report failure explicitly
            # Class only: SDK errors and evidence refs can include sensitive identifiers.
            log.warning(
                "ACCURACY_SHADOW_FAILED asset=%s error_type=%s", cfg.asset, type(exc).__name__
            )
            summary["shadow_status"] = "shadow_failed"
    return summary

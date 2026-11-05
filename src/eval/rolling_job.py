"""Rolling orchestration. Champion commits independently of optional shadow results."""

from __future__ import annotations

import logging
from collections import Counter

from src.data import calendars
from src.data.config import ASSETS
from src.eval.rolling_accuracy import Config, NotReady, evaluate, utc
from src.eval.rolling_shadow import compare, publish_report
from src.eval.rolling_sources import Evidence, price_frame

log = logging.getLogger("cpaws.accuracy")


# Only fixed codes may leave the audit boundary; exception text may contain input values.
_SAFE_REASONS = frozenset(
    [
        "missing_record_unclassified",
        "prob_up_mismatch",
        "duplicate_forecast_key",
        "invalid_forecast_identity",
        "outside_window_or_effective_date",
        "invalid_issuance_time",
        "invalid_quantile_levels",
        "invalid_horizon_set",
        "invalid_quantiles",
        "invalid_prob_up",
        "target_calendar_mismatch",
        "target_pending",
        "invalid_endpoint",
        "label_not_available",
        "late_issuance",
        "base_price_revision_mismatch",
        "base_not_available",
        "excluded_insufficient_baseline",
        "release_provenance_unverified",
        "legacy_unverified",
        "legacy_approval_after_evaluation",
        "legacy_outside_schedule",
        "legacy_cutover_unverified",
        "snapshot_binding_mismatch",
        "shadow_release_unverified",
        "invalid_input_snapshot_dt",
        "input_snapshot_unverified",
        "legacy_snapshot_binding_mismatch",
        "input_base_unavailable",
        "input_not_available_at_issuance",
        "missing_source_object",
        "source_changed_during_read",
        "snapshot_written_after_asof",
        "invalid_quality_schema",
        "snapshot_quality_not_final",
        "source_changed_before_publication",
        "provenance_configuration_not_ready",
        "actual_source_unavailable",
        "asset_snapshot_not_ready",
        "latest_actual_not_ready",
    ]
)


def _safe_reason(value):
    return value if value in _SAFE_REASONS else "other_validation_error"


def dry_diagnostics(result, records, evidence, cfg, source_reason=None):
    """Private operational output only: never appended to META, METRIC or public API."""
    evidence_status = "ready"
    try:
        evidence.require_configured(cfg, records or [])
    except (NotReady, ValueError, TypeError, KeyError):
        evidence_status = "not_ready"
    categories = {
        k: Counter() for k in ("record_exclusions", "pair_exclusions", "warnings", "schedule")
    }
    for row in result["audit"] if result else []:
        reason = _safe_reason(row["reason"])
        category = (
            "schedule"
            if reason == "missing_record_unclassified"
            else "warnings"
            if reason == "prob_up_mismatch"
            else "pair_exclusions"
            if "h" in row
            else "record_exclusions"
        )
        categories[category][reason] += 1
    total = sum(categories.values(), Counter())
    pairs = 7 * len(result["input_lineage"]) if result else None
    mismatch = categories["pair_exclusions"]["base_price_revision_mismatch"] if result else None
    return {
        "asset": cfg.asset,
        "records_read": len(records) if records is not None else None,
        "records_passing_provenance": len(result["input_lineage"]) if result else None,
        "records_with_scored_pairs": len({r["record_digest"] for r in result["observations"]})
        if result
        else None,
        "n_obs": result["overall"]["coverage_80"]["n_obs"] if result else None,
        "source_status": "not_ready" if source_reason else "ready",
        "source_reason": _safe_reason(source_reason) if source_reason else None,
        "evidence_status": evidence_status,
        "reason_counts": dict(sorted(total.items())),
        **{k: dict(sorted(v.items())) for k, v in categories.items()},
        "base_price_revision_mismatch": {
            "count": mismatch,
            "denominator": pairs,
            "denominator_definition": "7 * records_passing_provenance; includes pending targets, excludes record-level rejections",
            "rate": mismatch / pairs if pairs else None,
        },
    }


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
    records = None
    try:
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
    except NotReady as exc:
        if not dry_run:
            raise
        return {
            "asset": cfg.asset,
            "status": "not_ready",
            "publication": "dry_run",
            "diagnostics": dry_diagnostics(None, records, evidence, cfg, str(exc)),
        }
    # All configured approval inputs bind identity even when there are zero eligible pairs.
    from src.eval.rolling_accuracy import digest

    result["identity"]["evidence_config_hash"] = digest(evidence_config)
    result["run_id"] = cfg.job_date + "-" + digest(result["identity"])[:20]
    if not dry_run:
        published = store.publish(result, sources.verify_unchanged, champion_guard)
    else:
        try:
            sources.verify_unchanged()
        except NotReady as exc:
            return {
                "asset": cfg.asset,
                "status": "not_ready",
                "publication": "dry_run",
                "diagnostics": dry_diagnostics(None, records, evidence, cfg, str(exc)),
            }
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
    if dry_run:
        summary["diagnostics"] = dry_diagnostics(result, records, evidence, cfg)
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

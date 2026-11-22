import copy
import json

import pytest

from src.eval.rolling_accuracy import NotReady, digest
from src.eval.rolling_job import run_asset
from src.eval.rolling_store import AccuracyStore
from tests.rolling_support import Table, case


@pytest.mark.parametrize("asset", ["gold", "silver", "brent", "wti"])
def test_end_to_end_retry(asset):
    cfg, sources, evidence, _ = case(asset)
    table = Table()
    first = run_asset(cfg, sources, AccuracyStore(table), evidence)
    second = run_asset(cfg, sources, AccuracyStore(table), evidence)
    assert first == second
    assert first["n_obs"] == 10 and first["status"] == "COMPLETED"
    assert len(table.items) == 30


def test_dry_run_and_no_evidence():
    cfg, sources, _, _ = case()
    table = Table()
    result = run_asset(cfg, sources, AccuracyStore(table), {}, dry_run=True)
    assert result["n_obs"] == 0 and not table.items
    with pytest.raises(NotReady, match="provenance_configuration_not_ready"):
        run_asset(cfg, sources, AccuracyStore(table), {})
    assert not table.items and not table.calls


def test_valid_evidence_zero_eligible_completes():
    cfg, sources, evidence, records = case()
    for record in records:
        record["is_sample"] = True
    table = Table()
    result = run_asset(cfg, sources, AccuracyStore(table), evidence)
    assert result["n_obs"] == 0 and len(table.items) == 30
    assert result["status"] == "COMPLETED"


def test_legacy_gold_provenance_cannot_publish_wti():
    cfg, sources, _, records = case("gold")
    record = records[0]
    snapshot = sources.snapshot(record["input_snapshot_dt"], record["created_at"])
    policy = {
        "legacy": [
            {
                "approved": True,
                "approved_by": "synthetic-reviewer",
                "approved_at": cfg.as_of,
                "reference": "synthetic-gold-audit",
                "record_digest": digest(record),
                "snapshot_digest": digest(snapshot.identity),
                "input_snapshot_dt": record["input_snapshot_dt"],
                "pre_cutover_verified": True,
                "no_overwrite": True,
                "scheduled_run": True,
                "input_asof_checked": True,
            }
        ]
    }
    gold_table = Table()
    result = run_asset(cfg, sources, AccuracyStore(gold_table), policy, shadow=False)
    assert result["n_obs"] == 4 and len(gold_table.items) == 30
    wti_cfg, wti_sources, _, _ = case("wti")
    wti_table = Table()
    with pytest.raises(NotReady, match="provenance_configuration_not_ready"):
        run_asset(wti_cfg, wti_sources, AccuracyStore(wti_table), policy, shadow=False)
    assert not wti_table.items and not wti_table.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved", False),
        ("conditional_write", False),
        ("input_asof_checked", False),
        ("cutover_at", "invalid"),
        ("cutover_at", "2027-01-01T00:00:00Z"),
        ("approved_at", "2027-01-01T00:00:00Z"),
    ],
)
def test_invalid_release_no_writes(field, value):
    cfg, sources, evidence, _ = case()
    evidence["release"][field] = value
    table = Table()
    with pytest.raises(NotReady):
        run_asset(cfg, sources, AccuracyStore(table), evidence)
    assert not table.calls and not table.items


def test_missing_snapshot_no_promote():
    cfg, sources, evidence, _ = case()
    del sources.s3.objects[f"clean/prices/dt={cfg.job_date}/quality.json"]
    table = Table()
    with pytest.raises(NotReady):
        run_asset(cfg, sources, AccuracyStore(table), evidence)
    assert not table.items


def test_shadow_failure_is_independent(monkeypatch):
    cfg, sources, evidence, _ = case()

    def broken(*args):
        raise RuntimeError("synthetic shadow failure")

    monkeypatch.setattr("src.eval.rolling_job.compare", broken)
    table = Table()
    result = run_asset(cfg, sources, AccuracyStore(table), evidence)
    assert result["status"] == "COMPLETED" and result["shadow_status"] == "shadow_failed"
    assert len(table.items) == 30


def test_full_window_ready_and_metadata_fits():
    cfg, sources, evidence, _ = case(job_date="2026-12-05", first="2026-10-26")
    table = Table()
    result = run_asset(cfg, sources, AccuracyStore(table), evidence, shadow=False)
    assert result["n_base_dates"] >= 20
    assert result["n_obs"] > 140 and len(table.items) == 30


@pytest.mark.parametrize("asset", ["gold", "silver", "brent", "wti"])
def test_dry_diagnostics_no_mutation_and_same_publish(asset):
    cfg, sources, evidence, records = case(asset)
    saved_records, saved_evidence = copy.deepcopy(records), copy.deepcopy(evidence)
    table = Table()
    result = run_asset(cfg, sources, AccuracyStore(table), evidence, dry_run=True)
    d = result["diagnostics"]
    assert d["records_read"] == 5 and d["records_passing_provenance"] == 5
    assert d["records_with_scored_pairs"] == 4 and d["n_obs"] == 10
    assert d["source_status"] == d["evidence_status"] == "ready"
    assert d["base_price_revision_mismatch"]["denominator"] == 35
    assert d["base_price_revision_mismatch"]["rate"] == 0
    assert not table.items and not table.calls and sources.s3.puts == 0
    assert records == saved_records and evidence == saved_evidence
    published = run_asset(cfg, sources, AccuracyStore(table), evidence)
    assert published["run_id"] == result["run_id"] and published["n_obs"] == result["n_obs"]
    assert "diagnostics" not in published
    assert all("diagnostics" not in item for item in table.items.values())


def test_dry_revision_mismatch_exact_counter_not_tolerance():
    cfg, sources, evidence, _ = case()
    actual = sources.snapshot(cfg.job_date, cfg.as_of)
    mask = actual.prices.date.eq(__import__("pandas").Timestamp("2026-11-02"))
    actual.prices.loc[mask, "price"] += 0.00000001
    table = Table()
    result = run_asset(cfg, sources, AccuracyStore(table), evidence, dry_run=True)
    d = result["diagnostics"]
    assert d["pair_exclusions"]["base_price_revision_mismatch"] == 4
    assert d["base_price_revision_mismatch"]["rate"] == pytest.approx(4 / 35)
    assert d["n_obs"] == 6 and not table.items and sources.s3.puts == 0
    assert '"price"' not in json.dumps(d) and '"q"' not in json.dumps(d)


def test_dry_unready_and_missing_evidence_are_explicit():
    cfg, sources, _, _ = case()
    table = Table()
    result = run_asset(cfg, sources, AccuracyStore(table), {}, dry_run=True)
    assert result["diagnostics"]["evidence_status"] == "not_ready"
    assert result["diagnostics"]["record_exclusions"]["legacy_unverified"] == 5
    assert result["diagnostics"]["base_price_revision_mismatch"]["rate"] is None
    sources.snapshots.clear()
    del sources.s3.objects[f"clean/prices/dt={cfg.job_date}/quality.json"]
    result = run_asset(cfg, sources, AccuracyStore(table), {}, dry_run=True)
    assert result["status"] == "not_ready"
    assert result["diagnostics"]["source_reason"] == "missing_source_object"
    assert result["diagnostics"]["records_read"] == 5
    assert result["diagnostics"]["n_obs"] is None
    assert not table.items and not table.calls and sources.s3.puts == 0


def test_diagnostic_never_prints_raw_exception_reason():
    from src.eval.rolling_job import dry_diagnostics
    from src.eval.rolling_sources import Evidence
    from tests.test_rolling_accuracy import result_case

    result, cfg, sources, policy, records = result_case()
    result["audit"].append({"reason": "price=123456 SECRET credential", "base_date": "2026-11-02"})
    result["audit"].append({"reason": "prob_up_mismatch", "h": 1, "base_date": "2026-11-02"})
    d = dry_diagnostics(result, records, Evidence(sources, policy, cfg.as_of), cfg)
    assert d["record_exclusions"]["other_validation_error"] == 1
    assert d["warnings"]["prob_up_mismatch"] == 1
    assert "SECRET" not in json.dumps(d)

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

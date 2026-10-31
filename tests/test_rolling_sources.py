import copy
import io

import pandas as pd
import pytest
from botocore.exceptions import ClientError

from src.eval.rolling_accuracy import digest
from src.eval.rolling_sources import Evidence, NotReady, SourceConflict
from tests.rolling_support import case


def test_paginated_forecasts_no_scan():
    cfg, sources, _, records = case()
    assert sources.records(cfg.asset, cfg.start, cfg.job_date) == records
    assert len(sources.forecasts.calls) == 3


def test_conditional_release_and_input_snapshot():
    cfg, sources, policy, records = case()
    ev = Evidence(sources, policy, cfg.as_of)
    frame, proof = ev.for_record(records[0])
    assert proof["policy"] == "POST_CUTOVER" and len(frame) >= 252
    invalid = copy.deepcopy(records[0])
    invalid.pop("input_snapshot_dt")
    with pytest.raises(ValueError):
        ev.for_record(invalid)
    with pytest.raises(ValueError, match="legacy_unverified"):
        Evidence(sources, {}, cfg.as_of).for_record(records[0])


def test_legacy_exact_allowlist_snapshot_binding():
    cfg, sources, _, records = case()
    record = copy.deepcopy(records[0])
    dt = record.pop("input_snapshot_dt")
    snap = sources.snapshot(dt, record["created_at"])
    entry = {
        "approved": True,
        "approved_by": "synthetic",
        "approved_at": cfg.as_of,
        "reference": "synthetic-audit",
        "record_digest": digest(record),
        "input_snapshot_dt": dt,
        "snapshot_digest": digest(snap.identity),
        "no_overwrite": True,
        "scheduled_run": True,
        "input_asof_checked": True,
        "pre_cutover_verified": True,
    }
    ev = Evidence(sources, {"legacy": [entry]}, cfg.as_of)
    ev.require_configured(cfg, [record])
    from dataclasses import replace

    for other, actual in [
        (replace(cfg, asset="wti"), [record]),
        (replace(cfg, effective="2026-11-05"), [record]),
        (replace(cfg, job_date="2027-01-07", as_of="2027-01-07T13:45:00Z"), [record]),
        (cfg, []),
    ]:
        with pytest.raises(NotReady, match="provenance_configuration_not_ready"):
            ev.require_configured(other, actual)
    assert ev.for_record(record)[1]["policy"] == "LEGACY_ACCEPT_WITH_EVIDENCE"
    altered = copy.deepcopy(record)
    altered["horizons"][0]["prob_up"] = 0.05
    with pytest.raises(ValueError, match="legacy_unverified"):
        ev.for_record(altered)
    entry["approved"] = False
    with pytest.raises(NotReady, match="provenance_configuration_not_ready"):
        ev.require_configured(cfg, [record])
    with pytest.raises(ValueError):
        ev.for_record(record)


def test_source_not_ready_or_mixed_snapshot():
    cfg, sources, _, _ = case()
    key = f"clean/prices/dt={cfg.job_date}/quality.json"
    del sources.s3.objects[key]
    with pytest.raises(NotReady):
        sources.snapshot(cfg.job_date, cfg.as_of)


def test_snapshot_rewrite_and_asof_are_fail_closed():
    cfg, sources, policy, records = case()
    ev = Evidence(sources, policy, cfg.as_of)
    ev.for_record(records[0])
    key = f"clean/prices/dt={records[0]['input_snapshot_dt']}/prices.parquet"
    sources.s3.objects[key]["ETag"] = "changed"
    with pytest.raises(SourceConflict):
        sources.verify_unchanged()


def test_input_published_after_issuance():
    cfg, sources, policy, records = case()
    dt = records[0]["input_snapshot_dt"]
    key = f"clean/prices/dt={dt}/prices.parquet"
    df = pd.read_parquet(io.BytesIO(sources.s3.objects[key]["raw"]))
    df.loc[df.index[-1], "published_at"] = pd.Timestamp(dt + "T13:00:00Z")
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    sources.s3.seed(key, buf.getvalue(), dt + "T12:02:00Z")
    with pytest.raises(ValueError, match="input_not_available"):
        Evidence(sources, policy, cfg.as_of).for_record(records[0])


def test_403_is_not_missing_without_list_evidence():
    _, sources, _, _ = case()
    sources.s3.denied.add("missing")
    assert sources.read_object("missing", optional=True) is None
    sources.s3.seed("exists", b"x", "2026-11-07T12:00:00Z")
    sources.s3.denied.add("exists")
    with pytest.raises(ClientError):
        sources.read_object("exists", optional=True)
    sources.s3.list_denied = True
    with pytest.raises(ClientError):
        sources.read_object("missing", optional=True)


def test_parquet_object_collision():
    _, sources, _, _ = case()
    key = "eval/shadow_eval/run_id=synthetic/asset=gold/test.parquet"
    sources.write_shadow(key, b"synthetic")
    sources.write_shadow(key, b"synthetic")
    assert sources.s3.puts == 1
    with pytest.raises(SourceConflict, match="immutable_shadow_conflict"):
        sources.write_shadow(key, b"different")

import copy
import io
import json
from dataclasses import replace

import pyarrow.parquet as pq
import pytest

from src.eval.rolling_shadow import compare, parquet_bytes, publish_report
from src.eval.rolling_sources import Evidence
from tests.test_rolling_accuracy import result_case


def shadow_case(late=False):
    result, cfg, sources, policy, records = result_case()
    policy["shadow_release"] = dict(
        policy["release"], immutable_write=True, deployed_at="2026-10-30T12:00:00Z"
    )
    for original in records[:2]:
        record = copy.deepcopy(original)
        record["model_version"] = "s1a-l094"
        record["shadow"] = {"k": 1.0, "champion_model_version": "baseline-q252"}
        dt = record["created_at"][:10]
        modified = cfg.as_of if late else dt + "T12:16:00Z"
        sources.s3.seed(
            f"eval/shadow/s1a-l094/dt={dt}/gold.json", json.dumps(record).encode(), modified
        )
    return result, cfg, sources, Evidence(sources, policy, cfg.as_of)


def test_paired_subset_parquet_retry():
    result, cfg, sources, evidence = shadow_case()
    report = compare(result, cfg, sources, evidence)
    assert result["overall"]["coverage_80"]["n_obs"] == 10
    assert report["paired_n_obs"] == 7
    rows = pq.read_table(io.BytesIO(parquet_bytes(report))).to_pylist()
    assert len(rows) == 48
    assert all(
        r["value"] == 0
        for r in rows
        if r["model_version"] == "baseline-q252"
        and r["metric"] == "pinball_skill"
        and r["paired_n_obs"]
    )
    assert publish_report(report, sources) == publish_report(report, sources)
    assert sources.s3.puts == 1


def test_late_shadow_not_paired():
    result, cfg, sources, evidence = shadow_case(late=True)
    report = compare(result, cfg, sources, evidence)
    assert report["paired_n_obs"] == 0
    assert all(r["value"] is None for r in report["metrics"])


def test_model_change_and_unapproved():
    result, cfg, sources, evidence = shadow_case()
    assert (
        compare(result, replace(cfg, model="K4"), sources, evidence)["status"]
        == "shadow_not_applicable_model_change"
    )
    evidence.config["shadow_release"]["approved"] = False
    assert compare(result, cfg, sources, evidence)["status"] == "shadow_not_ready"


@pytest.mark.parametrize("retain_original", [True, False])
def test_later_run_same_base_same_snapshot_no_double_count(retain_original):
    result, cfg, sources, evidence = shadow_case()
    # The champion was already published Nov 3. Another run writes the same
    # base/snapshot on Nov 4; h1 is now late, but h2..4 can still be eligible.
    key = "eval/shadow/s1a-l094/dt=2026-11-03/gold.json"
    raw = sources.s3.objects[key]["raw"]
    sources.s3.seed("eval/shadow/s1a-l094/dt=2026-11-04/gold.json", raw, "2026-11-04T12:16:00Z")
    if not retain_original:
        del sources.s3.objects[key]
    report = compare(result, cfg, sources, evidence)
    assert report["paired_n_obs"] == (4 if retain_original else 3)
    paired = report["provenance"]["pairs"]
    assert len({(p["base_date"], p["h"]) for p in paired}) == len(paired)
    assert all(
        p["shadow_object"]["key"].endswith(
            "2026-11-03/gold.json" if retain_original else "2026-11-04/gold.json"
        )
        for p in paired
    )


def test_wrong_snapshot_candidate_does_not_hide_matching_later_object():
    result, cfg, sources, evidence = shadow_case()
    original = "eval/shadow/s1a-l094/dt=2026-11-03/gold.json"
    raw = sources.s3.objects[original]["raw"]
    wrong = json.loads(raw)
    wrong["input_snapshot_dt"] = "2026-11-04"
    wrong["created_at"] = "2026-11-04T12:15:00Z"
    del sources.s3.objects[original]
    sources.s3.seed(
        "eval/shadow/s1a-l094/dt=2026-11-04/gold.json",
        json.dumps(wrong).encode(),
        "2026-11-04T12:16:00Z",
    )
    sources.s3.seed("eval/shadow/s1a-l094/dt=2026-11-05/gold.json", raw, "2026-11-05T12:16:00Z")
    report = compare(result, cfg, sources, evidence)
    assert report["paired_n_obs"] == 2
    assert all(
        p["shadow_object"]["key"].endswith("2026-11-05/gold.json")
        for p in report["provenance"]["pairs"]
    )
    del sources.s3.objects["eval/shadow/s1a-l094/dt=2026-11-05/gold.json"]
    # New read session, as after a fresh invocation.
    sources.objects.clear()
    report = compare(result, cfg, sources, evidence)
    assert report["paired_n_obs"] == 0
    assert any(e["reason"] == "shadow_missing" for e in report["exclusions"])

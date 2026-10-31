import copy
from dataclasses import replace

import pytest

from src.eval.rolling_accuracy import (
    Config,
    day,
    digest,
    evaluate,
    expected_dates,
    response_payload,
    summarize,
    validate_record,
)
from src.eval.rolling_sources import Evidence
from tests.rolling_support import case


@pytest.mark.parametrize("state", ["collecting", "ready"])
def test_projection_against_actual_pr62_fixture(state):
    import json
    import os
    import zipfile
    from pathlib import Path

    archive = os.environ.get("CPAWS_ACCURACY_FIXTURES_ZIP")
    name = "tests/fixtures/accuracy/" + state + ".json"
    if archive:
        with zipfile.ZipFile(archive) as z:
            expected = json.loads(z.read(name))
    elif Path(name).is_file():
        expected = json.loads(Path(name).read_text(encoding="utf-8"))
    else:
        pytest.skip("PR62 fixtures absent: provide CPAWS_ACCURACY_FIXTURES_ZIP")
    # Adapt the fixture's internal values/counts to a completed result. This tests
    # the entire public projection, not reconstruction of synthetic q/y inputs.
    result = copy.deepcopy(expected)
    for group in [result["overall"], *result["by_horizon"]]:
        for metric, value in group.items():
            if metric == "h":
                continue
            value.pop("display_value")
            value.pop("display_status")
            value.pop("min_display_base_dates", None)
            if metric == "coverage_80":
                value["value"] = value["covered_count"] / value["n_obs"] if value["n_obs"] else None
            value["undefined_reason"] = None if value["status"] == "ok" else "no_evaluable_obs"
    assert response_payload(result, expected["asset"], expected["model_version"]) == expected


def result_case(**kw):
    cfg, sources, evidence, records = case(**kw)
    result = evaluate(
        records,
        sources.snapshot(cfg.job_date, cfg.as_of),
        cfg,
        Evidence(sources, evidence, cfg.as_of).for_record,
    )
    return result, cfg, sources, evidence, records


@pytest.mark.parametrize("asset", ["gold", "silver", "brent", "wti"])
def test_calendar_window_and_actuals(asset):
    result, cfg, _, _, _ = result_case(asset=asset)
    assert cfg.start == "2026-09-13"
    assert result["overall"]["coverage_80"]["n_obs"] == 10
    assert result["overall"]["coverage_80"]["n_base_dates"] == 4
    assert [x["coverage_80"]["n_obs"] for x in result["by_horizon"]] == [4, 3, 2, 1, 0, 0, 0]
    e = result["evaluation_evidence"]
    assert e["expected_count"] == e["published_count"] + e["missing_count"]


@pytest.mark.parametrize("date", ["2026-02-30", "26-11-02", "2026-1-02", None])
def test_strict_dates(date):
    with pytest.raises((ValueError, TypeError)):
        day(date)


@pytest.mark.parametrize("n", [0, 19, 20])
def test_display_gate_all_metrics(n):
    rows = [
        {
            "base_date": f"2026-11-{i + 1:02d}",
            "q": [-0.04, -0.03, -0.01, 0.001, 0.01, 0.04, 0.05],
            "y": 0.02,
        }
        for i in range(n)
    ]
    m = summarize(rows)
    result = {
        "asset": "gold",
        "model_version": "baseline-q252",
        "run_id": "synthetic",
        "evaluated_at": "2026-12-01T13:45:00Z",
        "window": {},
        "evaluation_evidence": {},
        "overall": m,
        "by_horizon": [{"h": h, **m} for h in range(1, 8)],
    }
    response = response_payload(result, "gold", "baseline-q252")
    for metric in response["overall"].values():
        assert (metric["display_value"] is not None) == (n >= 20)
    for h in response["by_horizon"]:
        for k, metric in h.items():
            if k != "h":
                assert metric["display_value"] is None and metric["display_status"] == "counts_only"


def test_width_percent_pairwise_and_zero_sign():
    rows = [
        {"base_date": "2026-11-02", "q": [-0.1, -0.05, 0, 0, 0.1, 0.2, 0.3], "y": 0},
        {"base_date": "2026-11-03", "q": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07], "y": 0.05},
    ]
    import math

    m = summarize(rows)
    expected = 50 * (math.exp(0.2) - math.exp(-0.05) + math.exp(0.06) - math.exp(0.02))
    assert m["width_80_pct"]["value"] == pytest.approx(expected)
    assert m["width_80_pct"]["value"] != pytest.approx(100 * m["width_80"]["value"])
    assert m["sign_accuracy"]["n_obs"] == 1 and m["up_rate"]["n_obs"] == 2


@pytest.mark.parametrize("state,n", [("collecting", 19), ("ready", 20)])
def test_completed_response_contract(state, n):
    # Explicit v3.1 field contract; no dependency on a user's external fixture path.
    result = result_case()[0]
    result["overall"]["coverage_80"]["n_base_dates"] = n
    payload = response_payload(result, "gold", "baseline-q252")
    assert set(payload) == {
        "asset",
        "model_version",
        "evaluation_kind",
        "sample",
        "run_id",
        "evaluated_at",
        "window",
        "evaluation_evidence",
        "overall",
        "by_horizon",
        "data_status",
        "disclaimer",
    }
    assert payload["data_status"] == state
    assert set(payload["window"]) == {
        "basis",
        "days",
        "window_start",
        "window_end",
        "target_cutoff_date",
        "first_eligible_base_date",
    }
    assert set(payload["evaluation_evidence"]) == {
        "schedule_basis",
        "schedule_evidence_status",
        "issuance_evidence_status",
        "expected_count",
        "published_count",
        "missing_count",
    }
    assert [h["h"] for h in payload["by_horizon"]] == list(range(1, 8))
    metrics = {"coverage_80", "width_80", "width_80_pct", "sign_accuracy", "up_rate"}
    assert set(payload["overall"]) == metrics
    common = {"n_obs", "status", "display_value", "display_status"}
    for group in [payload["overall"], *payload["by_horizon"]]:
        overall = group is payload["overall"]
        assert set(group) == metrics | (set() if overall else {"h"})
        for name in metrics:
            m = group[name]
            fields = common | (
                {"covered_count", "n_base_dates"} if name == "coverage_80" else {"value"}
            )
            if name.startswith("width"):
                fields.add("unit")
                assert m["unit"] == ("percent" if name.endswith("pct") else "log_return")
            if overall and name == "coverage_80":
                fields.add("min_display_base_dates")
                assert m["min_display_base_dates"] == 20
            assert set(m) == fields
            expected = (
                ("ready" if state == "ready" else "insufficient_data") if overall else "counts_only"
            )
            assert m["display_status"] == expected
            assert (m["display_value"] is not None) == (overall and state == "ready")
    assert payload["overall"]["width_80_pct"]["n_obs"] == payload["overall"]["width_80"]["n_obs"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(is_sample=True),
        lambda r: r.update(target_series="GC=F"),
        lambda r: r.update(model_version="old"),
        lambda r: r.update(created_at="2026-10-26T12:15:00Z"),
        lambda r: r["horizons"].pop(),
        lambda r: r["horizons"][0].update(q=[1] * 6),
        lambda r: r["horizons"][0].update(q=[float("nan")] * 7),
        lambda r: r["horizons"][0].update(prob_up=1),
        lambda r: r["horizons"][0].update(target_date="2026-11-08"),
    ],
)
def test_invalid_record(mutate):
    cfg, _, _, records = case()
    row = copy.deepcopy(records[0])
    mutate(row)
    with pytest.raises((ValueError, TypeError)):
        validate_record(row, cfg)


def test_prob_mismatch_audit_only():
    cfg, _, _, records = case()
    record = copy.deepcopy(records[0])
    record["horizons"][0]["prob_up"] = 0.05
    assert validate_record(record, cfg)[0]["warning"] == "prob_up_mismatch"


def test_identity_deterministic_and_effective():
    r, cfg, sources, evidence, records = result_case()
    fn = Evidence(sources, evidence, cfg.as_of).for_record
    assert (
        r["run_id"]
        == evaluate(list(reversed(records)), sources.snapshot(cfg.job_date, cfg.as_of), cfg, fn)[
            "run_id"
        ]
    )
    late = replace(cfg, effective="2026-11-05")
    other = evaluate(records, sources.snapshot(cfg.job_date, cfg.as_of), late, fn)
    assert other["overall"]["coverage_80"]["n_base_dates"] == 1
    assert other["run_id"] != r["run_id"]
    assert response_payload(r, "gold", "new-champion")["data_status"] == "not_ready"


def test_holidays_and_canonical_numbers():
    from decimal import Decimal

    cfg = Config("gold", "baseline-q252", "2026-10-26", "2026-11-28", "2026-11-28T13:45:00Z")
    assert "2026-11-26" not in expected_dates(cfg)
    assert digest({"a": Decimal("1.000")}) == digest({"a": 1.0})


def test_missing_middle_keeps_valid_endpoints():
    _, cfg, sources, evidence, records = result_case()
    snapshot = copy.deepcopy(sources.snapshot(cfg.job_date, cfg.as_of))
    snapshot.prices = snapshot.prices.loc[
        snapshot.prices.date != __import__("pandas").Timestamp("2026-11-03")
    ]
    changed = evaluate(records, snapshot, cfg, Evidence(sources, evidence, cfg.as_of).for_record)
    rows = [r for r in changed["observations"] if r["base_date"] == "2026-11-02" and r["h"] == 2]
    assert len(rows) == 1 and rows[0]["missing_between_count"] == 1
    assert not any(r["target_date"] == "2026-11-03" for r in changed["observations"])


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_invalid_numeric_source_is_excluded(number):
    _, cfg, sources, evidence, records = result_case()
    records[0]["horizons"][0]["q"][0] = number
    result = evaluate(
        records,
        sources.snapshot(cfg.job_date, cfg.as_of),
        cfg,
        Evidence(sources, evidence, cfg.as_of).for_record,
    )
    assert result["overall"]["coverage_80"]["n_obs"] == 6

import copy
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

from src.eval.rolling_accuracy import (
    canonical as writer_canonical,
)
from src.eval.rolling_accuracy import (
    digest as writer_digest,
)
from src.eval.rolling_accuracy import (
    implementation_identity,
    response_payload,
)
from src.eval.rolling_store import AccuracyStore, run_pk
from tests.rolling_support import Table
from tests.test_rolling_accuracy import result_case

API_DIR = Path(__file__).resolve().parents[1] / "infra" / "lambda" / "accuracy_api"

# Cấu hình môi trường trước khi import Lambda handler.
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

sys.path.insert(0, str(API_DIR))

reader = importlib.import_module("handler")


ASSET = "gold"
MODEL = "baseline-q252"
EFFECTIVE = "2026-10-26"
JOB_DATE = "2026-11-07"
REVISION = 1
RUN_ORDER = "20261107#0001"
WINDOW = {
    "basis": "base_date",
    "days": 56,
    "window_start": "2026-09-13",
    "window_end": "2026-11-07",
    "target_cutoff_date": "2026-11-06",
    "first_eligible_base_date": "2026-10-27",
}


def metric_value(metric: str, horizon: int | None = None) -> dict:
    n = 24

    if metric == "coverage_80":
        return {
            "value": 0.8,
            "n_obs": n,
            "covered_count": 19,
            "n_base_dates": n,
            "status": "ok",
        }

    if metric == "width_80":
        return {
            "value": 0.012 + (horizon or 0) * 0.001,
            "n_obs": n,
            "unit": "log_return",
            "status": "ok",
        }

    if metric == "sign_accuracy":
        return {"value": 0.6, "n_obs": n, "status": "ok"}

    if metric == "up_rate":
        return {"value": 0.52, "n_obs": n, "status": "ok"}

    if metric == "width_80_pct":
        return {
            "value": 1.2 + (horizon or 0) * 0.1,
            "n_obs": n,
            "unit": "percent",
            "status": "ok",
        }

    raise AssertionError(metric)


def make_snapshot() -> dict:
    return {
        "dt": "2026-11-06",
        "objects": [
            {
                "bucket": "cpaws-dev-lake",
                "key": f"clean/prices/dt=2026-11-06/{filename}",
                "etag": f"etag-{index}",
                "version_id": None,
                "last_modified": "2026-11-06T10:00:00+00:00",
                "sha256": str(index) * 64,
            }
            for index, filename in enumerate(
                ("quality.json", "prices.parquet", "rejected.parquet"),
                start=1,
            )
        ],
    }


def make_input_lineage(snapshot: dict) -> list[dict]:
    approval = {
        "approved": True,
        "reference": "test-approval-001",
        "approved_by": "test-reviewer",
        "approved_at": "2026-11-06T12:00:00+00:00",
        "no_overwrite": True,
        "scheduled_run": True,
        "input_asof_checked": True,
        "snapshot_digest": writer_digest(snapshot),
        "pre_cutover_verified": True,
    }

    return [
        {
            "policy": "LEGACY_ACCEPT_WITH_EVIDENCE",
            "approval": approval,
            "snapshot": copy.deepcopy(snapshot),
            "record_digest": "a" * 64,
            "max_input_published_at": "2026-11-06T11:00:00+00:00",
        }
    ]


def make_identity(
    *,
    model: str = MODEL,
    effective: str = EFFECTIVE,
) -> dict:
    config_hash = "a" * 64
    snapshot = make_snapshot()

    # Synthetic evidence config for the Reader test fixture.
    # Use the same digest function as the Writer.
    evidence_config = {
        "fixture": "accuracy-reader-test",
    }

    return {
        "asset": ASSET,
        "model_version": model,
        "effective": effective,
        "job_date": JOB_DATE,
        "revision": REVISION,
        "config_hash": config_hash,
        "evidence_config_hash": writer_digest(evidence_config),
        "snapshot": copy.deepcopy(snapshot),
        "target_cutoff_date": WINDOW["target_cutoff_date"],
        "eligible_record_fingerprint": "b" * 64,
        "source_fingerprint": "c" * 64,
    }


# Giữ RUN_ID để các test có thể đối chiếu run mặc định.
RUN_ID = f"{JOB_DATE}-{writer_digest(make_identity())[:20]}"


def make_run(
    *,
    model: str = MODEL,
    effective: str = EFFECTIVE,
    run_order: str = RUN_ORDER,
) -> tuple[dict, list[dict], dict]:
    """Build a complete synthetic RUN partition using the writer's item shape."""

    config_hash = "a" * 64
    snapshot = make_snapshot()
    identity = make_identity(model=model, effective=effective)

    run_id = f"{JOB_DATE}-{writer_digest(identity)[:20]}"
    pk = reader._run_pk(ASSET, model, run_id)

    overall = {metric: metric_value(metric) for metric in reader.METRICS}
    overall["width_80_pct"] = metric_value("width_80_pct")

    by_horizon = []
    derived_horizons = []
    metric_rows = []

    for horizon in reader.HORIZONS:
        group = {"h": horizon}
        derived_horizons.append({"h": horizon, **metric_value("width_80_pct", horizon)})

        for metric in reader.METRICS:
            group[metric] = metric_value(metric, horizon)

            parts = (
                "all",
                "rolling_8w",
                WINDOW["window_start"],
                WINDOW["window_end"],
                WINDOW["target_cutoff_date"],
                f"H{horizon}",
                metric,
            )
            sk = "METRIC#" + "#".join(reader._component(value) for value in parts)

            row = {
                "PK": pk,
                "SK": sk,
                "run_id": run_id,
                "config_hash": config_hash,
                "model_version": model,
                "asset": ASSET,
                "sample": "all",
                "evaluation_kind": "rolling_8w",
                "evaluation_start": WINDOW["window_start"],
                "evaluation_end": WINDOW["window_end"],
                "target_cutoff_date": WINDOW["target_cutoff_date"],
                "h": horizon,
                "metric": metric,
                "ci_low": None,
                "ci_high": None,
                **copy.deepcopy(group[metric]),
            }
            row["payload_hash"] = reader._digest(row)
            metric_rows.append(row)

        by_horizon.append(group)

    evidence = {
        "schedule_basis": "trading_calendar_and_predict_schedule",
        "schedule_evidence_status": "not_audited_mvp",
        "issuance_evidence_status": "verified_eligible_rows",
        "expected_count": 24,
        "published_count": 24,
        "missing_count": 0,
    }

    input_lineage = make_input_lineage(snapshot)
    observation_proof = input_lineage[0]

    observation_count = overall["coverage_80"]["n_obs"]

    observations = [
        {
            "record_digest": observation_proof["record_digest"],
            "input_lineage": copy.deepcopy(observation_proof),
        }
        for _ in range(observation_count)
    ]

    meta = {
        "PK": pk,
        "SK": "META",
        "run_id": run_id,
        "run_order": run_order,
        "asset": ASSET,
        "model_version": model,
        "effective": effective,
        "evaluation_kind": "rolling_8w",
        "sample": "all",
        "evaluated_at": "2026-11-07T14:00:00Z",
        "config_hash": config_hash,
        "identity": identity,
        "implementation": implementation_identity(),
        "actual_lineage": copy.deepcopy(snapshot),
        "input_lineage": input_lineage,
        "observations": observations,
        "window": copy.deepcopy(WINDOW),
        "last_eligible_base_date": "2026-11-07",
        "evaluation_evidence": evidence,
        "overall": overall,
        "by_horizon": by_horizon,
        "derived_metrics": {
            "width_80_pct": {
                "overall": copy.deepcopy(overall["width_80_pct"]),
                "by_horizon": derived_horizons,
            }
        },
        "metric_hashes": {row["SK"]: row["payload_hash"] for row in metric_rows},
    }

    meta["payload_hash"] = reader._digest(meta)
    meta["status"] = "COMPLETED"

    return (
        meta,
        metric_rows,
        {
            "PK": f"ASSET#{ASSET}",
            "SK": "STATE",
            "latest_run_pk": pk,
            "latest_run_id": run_id,
            "latest_run_order": run_order,
        },
    )


class FakeTable:
    """Strongly consistent, paginated DynamoDB table fake."""

    def __init__(self, state=None, items=None, page_size=9, state_sequence=None):
        self.state = copy.deepcopy(state)
        self.items = copy.deepcopy(items or [])
        self.page_size = page_size
        self.state_sequence = copy.deepcopy(state_sequence)
        self.state_reads = 0
        self.query_calls = 0

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead is True
        assert Key == {"PK": f"ASSET#{ASSET}", "SK": "STATE"}

        self.state_reads += 1

        if self.state_sequence is not None:
            index = min(self.state_reads - 1, len(self.state_sequence) - 1)
            state = self.state_sequence[index]
        else:
            state = self.state

        return {"Item": copy.deepcopy(state)} if state is not None else {}

    def query(
        self,
        *,
        KeyConditionExpression,
        ConsistentRead,
        ExclusiveStartKey=None,
    ):
        assert ConsistentRead is True
        self.query_calls += 1

        offset = (ExclusiveStartKey or {}).get("offset", 0)
        page = self.items[offset : offset + self.page_size]

        result = {"Items": copy.deepcopy(page)}
        if offset + self.page_size < len(self.items):
            result["LastEvaluatedKey"] = {"offset": offset + self.page_size}

        return result


class FakeDynamo:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        assert name == "test-accuracy"
        return self.table


@pytest.fixture
def configure_reader(monkeypatch):
    def configure(table):
        monkeypatch.setattr(reader, "TABLE_NAME", "test-accuracy")
        monkeypatch.setattr(reader, "MODEL_VERSIONS", {ASSET: MODEL})
        monkeypatch.setattr(
            reader,
            "CHAMPION_EFFECTIVE_BASE_DATES",
            {ASSET: EFFECTIVE},
        )
        monkeypatch.setattr(reader, "dynamodb", FakeDynamo(table))

    return configure


def invoke():
    return reader.handler(
        {"pathParameters": {"asset": ASSET}},
        None,
    )


def body(response):
    return json.loads(response["body"])


def ready_table():
    meta, metrics, state = make_run()
    return FakeTable(state=state, items=[meta, *metrics])


def test_missing_state_returns_contract_not_ready(configure_reader):
    table = FakeTable()
    configure_reader(table)

    response = invoke()
    payload = body(response)

    assert response["statusCode"] == 200
    assert payload["data_status"] == "not_ready"
    assert payload["model_version"] == MODEL
    assert payload["run_id"] is None
    assert payload["overall"]["coverage_80"]["display_status"] == "not_ready"
    assert payload["overall"]["coverage_80"]["n_base_dates"] == 0
    assert len(payload["by_horizon"]) == 7
    assert table.query_calls == 0


def test_current_champion_returns_verified_metrics(configure_reader):
    table = ready_table()
    configure_reader(table)

    response = invoke()
    payload = body(response)

    assert response["statusCode"] == 200
    assert payload["data_status"] == "ready"
    assert payload["model_version"] == MODEL
    assert payload["run_id"] == RUN_ID
    assert payload["overall"]["coverage_80"]["display_status"] == "ready"
    assert len(payload["by_horizon"]) == 7
    assert table.query_calls > 1


@pytest.mark.parametrize(
    ("old_model", "old_effective"),
    [
        ("previous-model", EFFECTIVE),
        (MODEL, "2026-10-20"),
    ],
)
def test_valid_old_champion_returns_not_ready_without_old_metrics(
    configure_reader,
    old_model,
    old_effective,
):
    meta, metrics, state = make_run(
        model=old_model,
        effective=old_effective,
    )
    table = FakeTable(state=state, items=[meta, *metrics])
    configure_reader(table)

    response = invoke()
    payload = body(response)

    assert response["statusCode"] == 200
    assert payload["data_status"] == "not_ready"
    assert payload["model_version"] == MODEL
    assert payload["run_id"] is None
    assert payload["overall"]["width_80"]["value"] is None
    assert table.query_calls > 0


def test_old_champion_with_invalid_meta_hash_returns_503(configure_reader):
    meta, metrics, state = make_run(model="previous-model")
    meta["payload_hash"] = "0" * 64

    table = FakeTable(state=state, items=[meta, *metrics])
    configure_reader(table)

    response = invoke()

    assert response["statusCode"] == 503
    assert body(response) == {"error": "accuracy_unavailable"}


def test_corrupt_metric_hash_returns_503(configure_reader):
    meta, metrics, state = make_run()
    metrics[0]["value"] = 999

    table = FakeTable(state=state, items=[meta, *metrics])
    configure_reader(table)

    response = invoke()

    assert response["statusCode"] == 503


def test_missing_metric_returns_503(configure_reader):
    meta, metrics, state = make_run()
    table = FakeTable(state=state, items=[meta, *metrics[:-1]])
    configure_reader(table)

    response = invoke()

    assert response["statusCode"] == 503


def test_unexpected_run_item_returns_503(configure_reader):
    meta, metrics, state = make_run()
    extra = {"PK": meta["PK"], "SK": "UNEXPECTED"}
    table = FakeTable(state=state, items=[meta, *metrics, extra])
    configure_reader(table)

    response = invoke()

    assert response["statusCode"] == 503


def test_state_change_retries_complete_read_cycle(configure_reader):
    meta, metrics, state = make_run()
    changed = copy.deepcopy(state)
    changed["latest_run_order"] = "20261108#0001"

    table = FakeTable(
        state=state,
        items=[meta, *metrics],
        state_sequence=[state, changed, changed, changed],
    )
    configure_reader(table)

    response = invoke()

    assert response["statusCode"] == 503
    assert table.state_reads == 3
    assert table.query_calls == 8
    assert table.query_calls > 1


def test_state_change_to_unknown_run_fails_closed(configure_reader):
    meta, metrics, state = make_run()
    changed = copy.deepcopy(state)
    changed["latest_run_order"] = "20261108#0001"

    table = FakeTable(
        state=state,
        items=[meta, *metrics],
        state_sequence=[state, changed, changed, changed],
    )
    configure_reader(table)

    response = invoke()

    assert response["statusCode"] == 503


def test_invalid_asset_returns_400(configure_reader):
    configure_reader(FakeTable())

    response = reader.handler(
        {"pathParameters": {"asset": "copper"}},
        None,
    )

    assert response["statusCode"] == 400
    assert body(response) == {"error": "invalid_asset"}


def test_reader_hash_matches_rolling_writer():
    from decimal import Decimal

    payload = {
        "asset": "gold",
        "value": 1.0,
        "count": 20,
        "nested": {
            "decimal": Decimal("1.00"),
            "boolean": True,
        },
        "values": [1, 2.50, 3],
    }

    assert reader._canonical(payload) == writer_canonical(payload)
    assert reader._digest(payload) == writer_digest(payload)


def reseal_meta(meta: dict) -> None:
    """Recompute META hash after an intentional fixture mutation."""
    payload = {key: value for key, value in meta.items() if key not in ("payload_hash", "status")}
    meta["payload_hash"] = reader._digest(payload)


def invoke_corrupt_provenance(configure_reader, mutate_meta) -> dict:
    meta, metrics, state = make_run()
    mutate_meta(meta)
    reseal_meta(meta)

    table = FakeTable(state=state, items=[meta, *metrics])
    configure_reader(table)

    return invoke()


def invoke_corrupt_derived(configure_reader, mutate_meta) -> dict:
    return invoke_corrupt_provenance(configure_reader, mutate_meta)


@pytest.mark.parametrize("invalid_snapshot", ["bucket", "path"])
def test_invalid_input_snapshot_returns_503(
    configure_reader,
    invalid_snapshot,
):
    def mutate(meta):
        item = meta["input_lineage"][0]["snapshot"]["objects"][0]

        if invalid_snapshot == "bucket":
            item["bucket"] = "another-bucket"
        else:
            item["key"] = item["key"].replace(
                "dt=2026-11-06",
                "dt=2026-11-05",
            )

    response = invoke_corrupt_provenance(configure_reader, mutate)

    assert response["statusCode"] == 503


def test_legacy_snapshot_digest_mismatch_returns_503(configure_reader):
    def mutate(meta):
        snapshot = meta["input_lineage"][0]["snapshot"]
        snapshot["objects"][0]["sha256"] = "2" * 64

    response = invoke_corrupt_provenance(configure_reader, mutate)

    assert response["statusCode"] == 503


def test_input_proof_without_valid_record_digest_returns_503(
    configure_reader,
):
    def mutate(meta):
        meta["input_lineage"][0]["record_digest"] = "invalid"

    response = invoke_corrupt_provenance(configure_reader, mutate)

    assert response["statusCode"] == 503


def test_input_proof_with_invalid_published_at_returns_503(
    configure_reader,
):
    def mutate(meta):
        meta["input_lineage"][0]["max_input_published_at"] = "not-a-timestamp"

    response = invoke_corrupt_provenance(configure_reader, mutate)

    assert response["statusCode"] == 503


def test_duplicate_input_record_digest_returns_503(configure_reader):
    def mutate(meta):
        duplicate = copy.deepcopy(meta["input_lineage"][0])
        meta["input_lineage"].append(duplicate)

    response = invoke_corrupt_provenance(configure_reader, mutate)

    assert response["statusCode"] == 503


def test_missing_derived_horizon_returns_503(configure_reader):
    response = invoke_corrupt_derived(
        configure_reader,
        lambda meta: meta["derived_metrics"]["width_80_pct"]["by_horizon"].pop(),
    )

    assert response["statusCode"] == 503


def test_reordered_derived_horizons_returns_503(configure_reader):
    def mutate(meta):
        horizons = meta["derived_metrics"]["width_80_pct"]["by_horizon"]
        horizons[0], horizons[1] = horizons[1], horizons[0]

    response = invoke_corrupt_derived(configure_reader, mutate)

    assert response["statusCode"] == 503


@pytest.mark.parametrize("invalid_count", [-1, "24", True])
def test_invalid_derived_n_obs_returns_503(configure_reader, invalid_count):
    def mutate(meta):
        meta["derived_metrics"]["width_80_pct"]["by_horizon"][0]["n_obs"] = invalid_count

    response = invoke_corrupt_derived(configure_reader, mutate)

    assert response["statusCode"] == 503


def test_invalid_derived_unit_returns_503(configure_reader):
    def mutate(meta):
        meta["derived_metrics"]["width_80_pct"]["by_horizon"][0]["unit"] = "log_return"

    response = invoke_corrupt_derived(configure_reader, mutate)

    assert response["statusCode"] == 503


@pytest.mark.parametrize(
    ("status", "value"),
    [
        ("undefined", 1.25),
        ("ok", None),
    ],
)
def test_derived_status_value_mismatch_returns_503(
    configure_reader,
    status,
    value,
):
    def mutate(meta):
        metric = meta["derived_metrics"]["width_80_pct"]["by_horizon"][0]
        metric["status"] = status
        metric["value"] = value

    response = invoke_corrupt_derived(configure_reader, mutate)

    assert response["statusCode"] == 503


def test_derived_mutation_without_resealing_meta_returns_503(configure_reader):
    meta, metrics, state = make_run()
    meta["derived_metrics"]["width_80_pct"]["by_horizon"][0]["value"] = 999

    table = FakeTable(state=state, items=[meta, *metrics])
    configure_reader(table)

    response = invoke()

    assert response["statusCode"] == 503

def test_writer_publish_round_trips_through_reader(configure_reader):
    """Persist with the real Writer, then read its META/METRIC rows through Reader."""

    result, cfg, _sources, evidence, _records = result_case(
        asset=ASSET,
        job_date=JOB_DATE,
    )

    # Match rolling_job.run_asset() identity finalization exactly.
    result["identity"]["evidence_config_hash"] = writer_digest(evidence)
    result["run_id"] = (
        cfg.job_date + "-" + writer_digest(result["identity"])[:20]
    )

    table = Table()

    published = AccuracyStore(table).publish(result)

    assert published == "promoted"

    persisted_meta = table.items[(run_pk(result), "META")]
    assert "observations" not in persisted_meta

    configure_reader(table)

    response = invoke()
    payload = body(response)

    assert response["statusCode"] == 200
    assert payload == response_payload(result, ASSET, MODEL)

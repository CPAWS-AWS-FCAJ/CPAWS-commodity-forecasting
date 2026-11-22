import copy
import hashlib
import json
from decimal import Decimal

import pytest
from boto3.dynamodb.types import TypeSerializer

from src.eval.rolling_accuracy import digest
from src.eval.rolling_evidence import candidates, load_records, main, read_json
from src.eval.rolling_sources import Evidence
from src.eval.rolling_store import dynamo
from tests.rolling_support import case


@pytest.fixture
def inputs():
    _, sources, _, records = case(job_date="2026-10-31", first="2026-10-26")
    record = copy.deepcopy(records[0])
    dt = record.pop("input_snapshot_dt")
    record.update(
        last_price=Decimal("123.456789"),
        price_unit="USD/oz",
        fx_usd_vnd=Decimal(25000),
        fx_date="2026-10-26",
        stale_sources=[],
        roll_in_horizon=False,
    )
    claim = {k: record[k] for k in ("asset", "base_date", "model_version", "created_at")}
    claim.update(
        input_snapshot_dt=dt,
        reference="audit-test-74",
        dry_run=False,
        written=True,
        no_overwrite=True,
        scheduled_run=True,
        input_asof_checked=True,
        pre_cutover_verified=True,
    )
    return record, claim, sources


def generate(record, claim, sources, **kwargs):
    return candidates(
        [record],
        [claim] if claim else [],
        sources,
        asset="gold",
        start="2026-10-16",
        end="2026-10-31",
        full_items=True,
        **kwargs,
    )["candidates"][0]


def test_production_digests_and_never_auto_approve(inputs):
    record, claim, sources = inputs
    claim.update(approved=True, approved_by="not-an-approval", approved_at=record["created_at"])
    row = generate(record, claim, sources)
    assert row["status"] == "pending_review"
    ev = row["evidence"]
    assert ev["record_digest"] == digest(record)
    assert ev["snapshot_digest"] == digest(
        sources.snapshot(claim["input_snapshot_dt"], record["created_at"]).identity
    )
    assert ev["approved"] is False and ev["approved_by"] is None and ev["approved_at"] is None
    assert not sources.s3.puts


def test_full_item_not_redacted_and_numbers_canonical(inputs):
    record, claim, sources = inputs
    first = generate(record, claim, sources)["evidence"]["record_digest"]
    record["last_price"] = float(record["last_price"])
    assert generate(record, claim, sources)["evidence"]["record_digest"] == first
    record["private_metadata"] = {"credentials": "DO-NOT-PRINT-ME"}
    row = generate(record, claim, sources)
    assert row["evidence"]["record_digest"] == digest(record) != first
    output = json.dumps(row)
    assert all(
        secret not in output
        for secret in ("DO-NOT-PRINT-ME", "last_price", "credentials", '"q"', "123.456789")
    )


def test_candidate_requires_separate_approval_and_matches_runtime(inputs):
    record, claim, sources = inputs
    entry = generate(record, claim, sources)["evidence"]
    with pytest.raises(ValueError, match="legacy_unverified"):
        Evidence(sources, {"legacy": [entry]}, "2026-10-31T13:45:00Z").for_record(record)
    # Synthetic reviewer action, separate from the CLI's always-unapproved output.
    approved_entry = dict(
        entry, approved=True, approved_by="synthetic-reviewer", approved_at="2026-10-30T12:00:00Z"
    )
    _, proof = Evidence(sources, {"legacy": [approved_entry]}, "2026-10-31T13:45:00Z").for_record(
        record
    )
    assert proof["policy"] == "LEGACY_ACCEPT_WITH_EVIDENCE"
    assert proof["record_digest"] == entry["record_digest"]
    assert digest(proof["snapshot"]) == entry["snapshot_digest"]
    assert entry["approved"] is False


def test_projected_export_has_no_record_digest(inputs):
    record, claim, sources = inputs
    projected = {
        k: record[k] for k in ("asset", "base_date", "created_at", "is_sample", "model_version")
    }
    row = generate(projected, claim, sources)
    assert row["reasons"] == ["full_item_export_required"]
    assert row["evidence"]["record_digest"] is None
    report = candidates(
        [record],
        [claim],
        sources,
        asset="gold",
        start="2026-10-26",
        end="2026-10-28",
        full_items=False,
    )
    assert report["candidates"][0]["evidence"]["record_digest"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("no_overwrite", None),
        ("scheduled_run", "true"),
        ("input_asof_checked", False),
        ("pre_cutover_verified", False),
        ("dry_run", True),
        ("written", False),
        ("input_snapshot_dt", None),
        ("reference", "https://secret?token=PRIVATE"),
    ],
)
def test_missing_or_false_evidence_not_accepted(inputs, field, value):
    record, claim, sources = inputs
    claim[field] = value
    row = generate(record, claim, sources)
    assert row["status"] == "unverified" and row["reasons"]
    assert row["evidence"]["approved"] is False
    assert "PRIVATE" not in json.dumps(row)


def test_missing_ambiguous_and_mismatched_evidence(inputs):
    record, claim, sources = inputs
    assert generate(record, None, sources)["status"] == "unverified"
    report = candidates(
        [record],
        [claim, claim],
        sources,
        asset="gold",
        start="2026-10-26",
        end="2026-10-28",
        full_items=True,
    )
    assert report["candidates"][0]["reasons"] == ["missing_or_ambiguous_issuance_evidence"]
    claim["model_version"] = "other"
    assert generate(record, claim, sources)["status"] == "unverified"


@pytest.mark.parametrize(
    "mutation",
    [
        {"is_sample": True},
        {"base_date": "2026-10-16"},
        {"base_date": "2026-10-23"},
        {"base_date": "2026-10-29"},
        {"asset": "wti"},
    ],
)
def test_sample_and_scope_never_allowlisted(inputs, mutation):
    record, claim, sources = inputs
    record.update(mutation)
    row = generate(record, claim, sources)
    assert row["status"] == "excluded" and row["evidence"]["record_digest"] is None


def test_snapshot_identity_change_and_overwrite(inputs):
    record, claim, sources = inputs
    first = generate(record, claim, sources)["evidence"]["snapshot_digest"]
    sources.snapshots.clear()
    key = f"clean/prices/dt={claim['input_snapshot_dt']}/prices.parquet"
    sources.s3.objects[key]["VersionId"] = "different-version"
    sources.objects.clear()
    second = generate(record, claim, sources)["evidence"]["snapshot_digest"]
    assert second != first
    claim["snapshot_digest"] = first
    assert generate(record, claim, sources)["reasons"] == ["historical_snapshot_identity_mismatch"]
    sources.snapshots.clear()
    sources.objects.clear()
    for obj in sources.s3.objects.values():
        obj["LastModified"] = "2026-11-02T12:00:00Z"
    row = generate(record, claim, sources)
    assert row["status"] == "unverified"
    assert row["evidence"]["snapshot_digest"] is None
    assert "snapshot_written_after_asof" in row["reasons"]


def test_decimal_decode_complete_item(inputs):
    record, _, _ = inputs
    serialized = {k: TypeSerializer().serialize(v) for k, v in dynamo(record).items()}
    decoded, full = load_records(
        {
            "format": "dynamodb-attribute-values",
            "Items": [serialized],
            "full_items": True,
            "projection_used": False,
        }
    )
    assert full and digest(decoded[0]) == digest(record)


def test_cli_offline_round_trip_no_sdk_no_overwrite(inputs, tmp_path, monkeypatch, capsys):
    record, claim, sources = inputs

    def forbidden(*args, **kwargs):
        raise AssertionError("AWS SDK session forbidden")

    monkeypatch.setattr("boto3.client", forbidden)
    monkeypatch.setattr("boto3.resource", forbidden)
    serialized = {k: TypeSerializer().serialize(v) for k, v in dynamo(record).items()}
    (tmp_path / "full.json").write_text(
        json.dumps(
            {
                "format": "dynamodb-attribute-values",
                "full_items": True,
                "projection_used": False,
                "Items": [serialized],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "claims.json").write_text(json.dumps({"issuances": [claim]}), encoding="utf-8")
    objects = []
    for index, (key, obj) in enumerate(sources.s3.objects.items()):
        name = f"object-{index}.bin"
        (tmp_path / name).write_bytes(obj["raw"])
        objects.append(
            {
                "key": key,
                "path": name,
                "etag": obj["ETag"],
                "version_id": obj["VersionId"],
                "last_modified": obj["LastModified"].isoformat(),
                "sha256": hashlib.sha256(obj["raw"]).hexdigest(),
            }
        )
    (tmp_path / "bundle.json").write_text(
        json.dumps({"bucket": sources.bucket, "objects": objects}), encoding="utf-8"
    )
    output = tmp_path / "candidate.json"
    args = [
        "--asset",
        "gold",
        "--from",
        "2026-10-26",
        "--to",
        "2026-10-28",
        "--forecasts",
        str(tmp_path / "full.json"),
        "--issuance-evidence",
        str(tmp_path / "claims.json"),
        "--snapshot-bundle",
        str(tmp_path / "bundle.json"),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    report = read_json(output)
    assert report["production_ready"] is False
    assert report["candidates"][0] == generate(record, claim, sources)
    saved = output.read_bytes()
    assert main(args) == 2 and output.read_bytes() == saved
    assert "123.456789" not in capsys.readouterr().out


def test_json_nonfinite_duplicate_key_rejected(tmp_path):
    path = tmp_path / "invalid.json"
    for content in ('{"a":NaN}', '{"a":1,"a":2}'):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError):
            read_json(path)

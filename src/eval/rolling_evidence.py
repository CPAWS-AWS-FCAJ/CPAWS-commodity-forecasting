"""Offline, read-only candidate evidence tooling; never grants release approval."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from boto3.dynamodb.types import TypeDeserializer

from src.eval.rolling_accuracy import (
    ASSET_NAMES,
    Config,
    NotReady,
    day,
    digest,
    price_frame,
    utc,
    validate_record,
)
from src.eval.rolling_sources import Sources

LEGACY_DATES = frozenset({"2026-10-26", "2026-10-27", "2026-10-28"})
FULL_FIELDS = frozenset(
    {
        "asset",
        "base_date",
        "created_at",
        "model_version",
        "target_series",
        "last_price",
        "price_unit",
        "quantile_levels",
        "horizons",
        "fx_usd_vnd",
        "fx_date",
        "stale_sources",
        "roll_in_horizon",
        "is_sample",
    }
)
FLAGS = ("no_overwrite", "scheduled_run", "input_asof_checked", "pre_cutover_verified")


def read_json(path):
    def reject_constant(_):
        raise ValueError("nonfinite_json")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(
        Path(path).read_text(encoding="utf-8-sig"),
        parse_float=Decimal,
        parse_constant=reject_constant,
        object_pairs_hook=unique_keys,
    )


def load_records(document):
    """Full-item attestation is a trust boundary, not proof an export was complete."""
    if not isinstance(document, dict) or not isinstance(document.get("Items"), list):
        raise TypeError("invalid_forecast_export")
    confirmed = document.get("full_items") is True and document.get("projection_used") is False
    fmt = document.get("format")
    if fmt not in ("resource-json", "dynamodb-attribute-values"):
        raise ValueError("explicit_item_format_required")
    records = document["Items"]
    if fmt == "dynamodb-attribute-values":
        deserializer = TypeDeserializer()
        records = [{k: deserializer.deserialize(v) for k, v in item.items()} for item in records]
    return records, confirmed


class OfflineS3:
    """Replays archived bytes plus ORIGINAL S3 metadata, never filesystem mtime."""

    def __init__(self, manifest_path):
        self.root = Path(manifest_path).resolve().parent
        manifest = read_json(manifest_path)
        self.bucket = manifest["bucket"]
        self.prefix = manifest.get("prefix", "")
        self.objects = {}
        for item in manifest["objects"]:
            if item["key"] in self.objects:
                raise ValueError("duplicate_snapshot_object")
            self.objects[item["key"]] = item

    def get_object(self, *, Bucket, Key):
        if Bucket != self.bucket or Key not in self.objects:
            raise NotReady("historical_snapshot_missing")
        item = self.objects[Key]
        path = (self.root / item["path"]).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("snapshot_path_outside_bundle")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise NotReady("historical_snapshot_checksum_mismatch")
        return {
            "Body": io.BytesIO(raw),
            "ETag": item["etag"],
            "VersionId": item["version_id"],
            "LastModified": utc(item["last_modified"]),
        }


def _reference(value):
    # Opaque audit ID only: never echo raw logs, URLs, query tokens or free text.
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value) else None
    )


def candidates(records, claims, sources, *, asset, start, end, full_items):
    """Hash complete decoded items before selecting fields; emit only safe candidates.

    claims are operator-reviewed issuance attestations, not raw PREDICT_DONE logs.
    This function checks bindings; it does not verify CloudWatch or grant approval.
    """
    if asset not in ASSET_NAMES or day(start) > day(end):
        raise ValueError("invalid_scope")
    if not isinstance(claims, list) or any(not isinstance(c, dict) for c in claims):
        raise ValueError("invalid_issuance_claims")
    result = []
    keys = Counter((r.get("asset"), r.get("base_date")) for r in records if isinstance(r, dict))
    for index, record in enumerate(records):
        evidence = dict.fromkeys(
            (
                "record_digest",
                "input_snapshot_dt",
                "snapshot_digest",
                "approved_by",
                "approved_at",
                "reference",
            )
        )
        evidence.update(approved=False, **dict.fromkeys(FLAGS, None))
        row = {
            "input_index": index,
            "asset": asset,
            "base_date": None,
            "status": "unverified",
            "reasons": [],
            "evidence": evidence,
        }
        result.append(row)
        if not isinstance(record, dict) or not full_items or not FULL_FIELDS <= record.keys():
            row["reasons"].append("full_item_export_required")
            continue
        try:
            # No redaction/projection/mutation before the production digest call.
            whole_digest = digest(record)
            base = day(record.get("base_date"))
            created = utc(record.get("created_at"))
        except (ValueError, TypeError, KeyError):
            row["reasons"].append("invalid_full_item")
            continue
        row["base_date"] = base
        if record.get("asset") != asset or not start <= base <= end or base not in LEGACY_DATES:
            row.update(status="excluded", reasons=["outside_legacy_scope"])
            continue
        if record.get("is_sample") is not False:
            row.update(status="excluded", reasons=["sample_or_invalid_production_flag"])
            continue
        if keys[(asset, base)] != 1:
            row["reasons"].append("duplicate_forecast_key")
            continue
        try:
            cfg = Config(
                asset,
                "baseline-q252",
                min(LEGACY_DATES),
                created.date().isoformat(),
                created.isoformat(),
            )
            validate_record(record, cfg)
            if (
                created.weekday() not in range(1, 6)
                or not 735 <= created.hour * 60 + created.minute < 810
            ):
                raise ValueError("outside_schedule")
        except (ValueError, TypeError, KeyError, OverflowError):
            row["reasons"].append("invalid_legacy_forecast")
            continue
        evidence["record_digest"] = whole_digest
        matches = [
            c
            for c in claims
            if all(
                c.get(k) == record[k] for k in ("asset", "base_date", "model_version", "created_at")
            )
        ]
        if len(matches) != 1:
            row["reasons"].append("missing_or_ambiguous_issuance_evidence")
            continue
        claim = matches[0]
        evidence["reference"] = _reference(claim.get("reference"))
        if (
            not evidence["reference"]
            or claim.get("dry_run") is not False
            or claim.get("written") is not True
        ):
            row["reasons"].append("issuance_not_verified")
            continue
        for flag in FLAGS:
            evidence[flag] = claim.get(flag) if type(claim.get(flag)) is bool else None
            if evidence[flag] is not True:
                row["reasons"].append(flag + "_unverified")
        try:
            dt = day(claim.get("input_snapshot_dt"))
            if (
                base >= dt
                or dt > created.date().isoformat()
                or record.get("input_snapshot_dt") not in (None, dt)
            ):
                raise ValueError("snapshot_binding")
            evidence["input_snapshot_dt"] = dt
        except (ValueError, TypeError):
            row["reasons"].append("snapshot_binding_unverified")
            continue
        try:
            snapshot = sources.snapshot(dt, created.isoformat())
            snapshot_hash = digest(snapshot.identity)
            # Optional independently archived identity fingerprint must match if supplied.
            if claim.get("snapshot_digest") not in (None, snapshot_hash):
                row["reasons"].append("historical_snapshot_identity_mismatch")
                continue
            frame = price_frame(snapshot.prices, snapshot.rejected, asset)
            frame = frame.loc[frame.index <= base]
            if (
                base not in frame.index
                or not frame.loc[base, "valid"]
                or (frame.published_at > created).any()
            ):
                row["reasons"].append("snapshot_input_asof_unverified")
                continue
            evidence["snapshot_digest"] = snapshot_hash
        except NotReady as exc:
            known = {
                "snapshot_written_after_asof",
                "historical_snapshot_missing",
                "historical_snapshot_checksum_mismatch",
                "snapshot_quality_not_final",
            }
            reason = str(exc) if str(exc) in known else "historical_snapshot_unverified"
            row["reasons"].append(reason)
        except (ValueError, TypeError, KeyError, OSError):
            row["reasons"].append("historical_snapshot_unverified")
        if not row["reasons"]:
            row["status"] = "pending_review"
    return {
        "kind": "legacy_evidence_candidates",
        "production_ready": False,
        "asset": asset,
        "from": start,
        "to": end,
        "candidates": result,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", choices=ASSET_NAMES, required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--forecasts", type=Path, required=True)
    parser.add_argument("--issuance-evidence", type=Path, required=True)
    parser.add_argument("--snapshot-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        records, full = load_records(read_json(args.forecasts))
        claims = read_json(args.issuance_evidence)["issuances"]
        s3 = OfflineS3(args.snapshot_bundle)
        sources = Sources(s3, s3.bucket, None, s3.prefix)
        report = candidates(
            records,
            claims,
            sources,
            asset=args.asset,
            start=args.start,
            end=args.end,
            full_items=full,
        )
        # Do not overwrite raw exports, evidence, or an existing review artifact.
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (ValueError, TypeError, KeyError, OSError, NotReady):
        # Input exceptions can embed prices, credentials or local paths.
        print('{"status":"error","reason":"offline_input_or_output_invalid"}')
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

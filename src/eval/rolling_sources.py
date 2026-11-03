"""Injected boto3 adapters. Reads only named S3 objects and DynamoDB Query, never Scan."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass

import pandas as pd
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.eval.rolling_accuracy import NotReady, day, digest, price_frame, utc, validate_record


class SourceConflict(NotReady):
    """An object changed during the run or cannot be tied to issuance."""


def error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


@dataclass
class Snapshot:
    dt: str
    prices: pd.DataFrame
    rejected: pd.DataFrame
    quality: dict
    identity: dict
    latest_modified: str


class Sources:
    def __init__(self, s3, bucket: str, forecasts, prefix: str = ""):
        if not bucket or prefix.startswith("/") or ".." in prefix.split("/"):
            raise ValueError("invalid bucket/prefix")
        self.s3, self.bucket, self.forecasts = s3, bucket, forecasts
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.objects = {}
        self.snapshots = {}

    def read_object(self, key: str, optional: bool = False):
        key = self.prefix + key
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = error_code(exc)
            if code in ("NoSuchKey", "404", "NotFound"):
                if optional:
                    return None
                raise NotReady("missing_source_object") from exc
            if code in ("403", "AccessDenied"):
                # A scoped list is a separate request: absence is not inferred from 403.
                page = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=key, MaxKeys=1)
                if not any(x["Key"] == key for x in page.get("Contents", [])):
                    if optional:
                        return None
                    raise NotReady("missing_source_object") from exc
            raise
        raw = response["Body"].read()
        identity = {
            "bucket": self.bucket,
            "key": key,
            "etag": response["ETag"],
            "version_id": response.get("VersionId"),
            "last_modified": utc(response["LastModified"]).isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if key in self.objects and self.objects[key] != identity:
            raise SourceConflict("source_changed_during_read")
        self.objects[key] = identity
        return raw, identity

    def snapshot(self, dt: str, as_of: str) -> Snapshot:
        day(dt)
        if dt in self.snapshots:
            snap = self.snapshots[dt]
            if utc(snap.latest_modified) > utc(as_of):
                raise SourceConflict("snapshot_written_after_asof")
            return snap
        base = f"clean/prices/dt={dt}/"
        qraw, qi = self.read_object(base + "quality.json")
        praw, pi = self.read_object(base + "prices.parquet")
        rraw, ri = self.read_object(base + "rejected.parquet")
        quality = json.loads(qraw)
        if not isinstance(quality, dict) or not isinstance(quality.get("assets"), dict):
            raise NotReady("invalid_quality_schema")
        # Ingest writes quality last; a mixed/partial rewrite must not be scored.
        if utc(qi["last_modified"]) < max(utc(pi["last_modified"]), utc(ri["last_modified"])):
            raise NotReady("snapshot_quality_not_final")
        latest = max(i["last_modified"] for i in (qi, pi, ri))
        if utc(latest) > utc(as_of):
            raise SourceConflict("snapshot_written_after_asof")
        snap = Snapshot(
            dt,
            pd.read_parquet(io.BytesIO(praw)),
            pd.read_parquet(io.BytesIO(rraw)),
            quality,
            {"dt": dt, "objects": [qi, pi, ri]},
            latest,
        )
        self.snapshots[dt] = snap
        return snap

    def verify_unchanged(self, identities=None):
        """Strong S3 HEAD recheck immediately before publication; no latest fallback."""
        for identity in identities or self.objects.values():
            head = self.s3.head_object(Bucket=self.bucket, Key=identity["key"])
            if (
                head["ETag"] != identity["etag"]
                or head.get("VersionId") != identity["version_id"]
                or utc(head["LastModified"]).isoformat() != identity["last_modified"]
            ):
                raise SourceConflict("source_changed_before_publication")

    def records(self, asset: str, start: str, end: str) -> list[dict]:
        args = {
            "KeyConditionExpression": Key("asset").eq(asset) & Key("base_date").between(start, end),
            "ConsistentRead": True,
        }
        rows = []
        while True:
            page = self.forecasts.query(**args)
            rows.extend(page.get("Items", []))
            if not page.get("LastEvaluatedKey"):
                return rows
            args["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def shadow(self, asset: str, dt: str):
        day(dt)
        obj = self.read_object(f"eval/shadow/s1a-l094/dt={dt}/{asset}.json", optional=True)
        if obj is None:
            return None
        raw, identity = obj
        record = json.loads(raw)
        if not isinstance(record, dict) or utc(record.get("created_at")).date().isoformat() > dt:
            raise ValueError("shadow_partition_mismatch")
        return record, identity

    def write_shadow(self, key: str, raw: bytes) -> str:
        if not key.startswith("eval/shadow_eval/run_id="):
            raise ValueError("invalid report prefix")
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=self.prefix + key,
                Body=raw,
                IfNoneMatch="*",
                ContentType="application/vnd.apache.parquet",
                Metadata={"sha256": hashlib.sha256(raw).hexdigest()},
            )
        except ClientError as exc:
            if error_code(exc) not in (
                "PreconditionFailed",
                "412",
                "ConditionalRequestConflict",
                "409",
            ):
                raise
            existing = self.read_object(key)
            if existing[0] != raw:
                raise SourceConflict("immutable_shadow_conflict") from exc
        return key


def approved(entry: dict) -> bool:
    """Trust boundary: release/legacy evidence supplied by authorized deployment owner.

    This checks structure/binding, not a cryptographic signature or remote audit.
    Protect config/file changes with IAM/release review; never accept evidence from event.
    """
    if not isinstance(entry, dict) or entry.get("approved") is not True:
        return False
    if not all(
        isinstance(entry.get(k), str) and entry[k].strip()
        for k in ("reference", "approved_by", "approved_at")
    ):
        return False
    utc(entry["approved_at"])
    return True


class Evidence:
    def __init__(self, sources: Sources, config: dict, as_of: str):
        self.sources, self.config, self.as_of = sources, config, as_of
        if not isinstance(config, dict):
            raise TypeError("evidence must be object")
        self.release = config.get("release", {})
        self.legacy = config.get("legacy", [])
        if not isinstance(self.legacy, list):
            raise TypeError("legacy must be list")

    def require_configured(self, cfg, records):
        """Gate publication, separately from per-record eligibility and target maturity."""

        def approval_valid(entry):
            try:
                return approved(entry) and utc(entry["approved_at"]) <= utc(self.as_of)
            except (ValueError, TypeError, KeyError):
                return False

        cutover_known = False
        if approval_valid(self.release):
            try:
                cutover_known = utc(self.release["cutover_at"]) <= utc(self.as_of)
            except (ValueError, TypeError, KeyError):
                pass
            if cutover_known and all(
                self.release.get(k) is True for k in ("conditional_write", "input_asof_checked")
            ):
                return
        # An unrelated allowlist entry cannot establish provenance for this run.
        # Reuse the unchanged record-level rules, including exact digest and snapshot binding.
        for record in records:
            try:
                validate_record(record, cfg)
                _, proof = self.for_record(record)
            except (ValueError, TypeError, KeyError, OverflowError):
                continue
            if proof["policy"] == "LEGACY_ACCEPT_WITH_EVIDENCE":
                return
        raise NotReady("provenance_configuration_not_ready")

    def for_record(self, record: dict, *, shadow: bool = False):
        created = utc(record.get("created_at"))
        base = day(record.get("base_date"))
        release_ok = approved(self.release) and utc(self.release["approved_at"]) <= utc(self.as_of)
        cutover = utc(self.release["cutover_at"]) if release_ok else None
        binding = None
        if cutover is not None and created >= cutover:
            if (
                self.release.get("conditional_write") is not True
                or self.release.get("input_asof_checked") is not True
            ):
                raise ValueError("release_provenance_unverified")
            dt = day(record.get("input_snapshot_dt"))
            binding = self.release
        elif not shadow:
            matches = [x for x in self.legacy if x.get("record_digest") == digest(record)]
            if len(matches) != 1 or not approved(matches[0]):
                raise ValueError("legacy_unverified")
            binding = matches[0]
            if utc(binding["approved_at"]) > utc(self.as_of):
                raise ValueError("legacy_approval_after_evaluation")
            if not all(
                binding.get(k) is True
                for k in ("no_overwrite", "scheduled_run", "input_asof_checked")
            ):
                raise ValueError("legacy_unverified")
            minute = created.hour * 60 + created.minute
            if created.weekday() not in range(1, 6) or not 735 <= minute < 810:
                raise ValueError("legacy_outside_schedule")
            if cutover is None and binding.get("pre_cutover_verified") is not True:
                raise ValueError("legacy_cutover_unverified")
            dt = day(binding.get("input_snapshot_dt"))
            if record.get("input_snapshot_dt") not in (None, dt):
                raise ValueError("snapshot_binding_mismatch")
        else:
            raise ValueError("shadow_release_unverified")
        if dt > created.date().isoformat() or base >= dt:
            raise ValueError("invalid_input_snapshot_dt")
        try:
            snap = self.sources.snapshot(dt, created.isoformat())
        except NotReady as exc:
            raise ValueError("input_snapshot_unverified") from exc
        if binding is not self.release and binding.get("snapshot_digest") != digest(snap.identity):
            raise ValueError("legacy_snapshot_binding_mismatch")
        p = price_frame(snap.prices, snap.rejected, record["asset"])
        p = p.loc[p.index <= base]
        if p.empty or base not in p.index or not p.loc[base, "valid"]:
            raise ValueError("input_base_unavailable")
        if (p.published_at > created).any():
            raise ValueError("input_not_available_at_issuance")
        return p, {
            "policy": "POST_CUTOVER" if binding is self.release else "LEGACY_ACCEPT_WITH_EVIDENCE",
            "approval": binding,
            "snapshot": snap.identity,
            "record_digest": digest(record),
            "max_input_published_at": p.published_at.max().isoformat(),
        }

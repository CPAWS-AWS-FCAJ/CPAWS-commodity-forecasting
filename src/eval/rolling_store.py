"""Immutable Accuracy writer with resumable, conditional lifecycle and monotonic pointer."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from urllib.parse import quote

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.eval.rolling_accuracy import METRICS, canonical, digest, summarize
from src.eval.rolling_sources import error_code


class Conflict(RuntimeError):
    pass


def dynamo(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [dynamo(v) for v in value]
    return value


def component(value) -> str:
    return quote(str(value), safe="-._~")


def run_pk(result: dict) -> str:
    return "RUN#" + "#".join(component(result[k]) for k in ("asset", "model_version", "run_id"))


def metric_items(result: dict) -> list[dict]:
    w = result["window"]
    rows = []
    for group in result["by_horizon"]:
        for metric in METRICS:
            key = "METRIC#" + "#".join(
                component(x)
                for x in (
                    "all",
                    "rolling_8w",
                    w["window_start"],
                    w["window_end"],
                    w["target_cutoff_date"],
                    "H" + str(group["h"]),
                    metric,
                )
            )
            payload = {
                "PK": run_pk(result),
                "SK": key,
                "run_id": result["run_id"],
                "config_hash": result["config_hash"],
                "model_version": result["model_version"],
                "asset": result["asset"],
                "sample": "all",
                "evaluation_kind": "rolling_8w",
                "evaluation_start": w["window_start"],
                "evaluation_end": w["window_end"],
                "target_cutoff_date": w["target_cutoff_date"],
                "h": group["h"],
                "metric": metric,
                "ci_low": None,
                "ci_high": None,
                **group[metric],
            }
            payload["payload_hash"] = digest(payload)
            rows.append(payload)
    return rows


def validate_result(result: dict):
    if result["sample"] != "all" or result["evaluation_kind"] != "rolling_8w":
        raise ValueError("invalid rolling scope")
    hs = result["by_horizon"]
    if [h["h"] for h in hs] != list(range(1, 8)):
        raise ValueError("expected seven horizons")
    rows = result["observations"]
    for group in hs:
        expected = summarize([r for r in rows if r["h"] == group["h"]])
        if digest(expected) != digest({k: v for k, v in group.items() if k != "h"}):
            raise ValueError("metric_or_derived_mismatch")
    if digest(summarize(rows)) != digest(result["overall"]):
        raise ValueError("overall_mismatch")
    ev = result["evaluation_evidence"]
    if ev["expected_count"] != ev["published_count"] + ev["missing_count"]:
        raise ValueError("publication_counts_mismatch")
    if len(metric_items(result)) != 28:
        raise ValueError("expected 28 metrics")


class AccuracyStore:
    """Accept a boto3 DynamoDB Table resource or a behavioral fake with same operations."""

    def __init__(self, table):
        self.table = table

    def get(self, pk, sk):
        return self.table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")

    def _put_once(self, item, meta=False):
        try:
            self.table.put_item(Item=dynamo(item), ConditionExpression="attribute_not_exists(PK)")
            return item
        except ClientError as exc:
            if error_code(exc) != "ConditionalCheckFailedException":
                raise
        existing = self.get(item["PK"], item["SK"])
        a = {k: v for k, v in item.items() if not (meta and k == "status")}
        b = {k: v for k, v in (existing or {}).items() if not (meta and k == "status")}
        if canonical(a) != canonical(b):
            raise Conflict("RUN_ID_CONFLICT" if meta else "IMMUTABLE_METRIC_CONFLICT")
        if meta and existing["status"] == "FAILED":
            raise Conflict("FAILED_RUN_REQUIRES_NEW_REVISION")
        return existing

    def _transition(self, meta, previous, target):
        try:
            self.table.update_item(
                Key={"PK": meta["PK"], "SK": "META"},
                UpdateExpression="SET #s = :target",
                ConditionExpression="#s = :previous AND payload_hash = :hash",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":previous": previous,
                    ":target": target,
                    ":hash": meta["payload_hash"],
                },
            )
        except ClientError as exc:
            if error_code(exc) != "ConditionalCheckFailedException":
                raise
            current = self.get(meta["PK"], "META")
            if (
                not current
                or current["payload_hash"] != meta["payload_hash"]
                or current["status"] not in (target, "COMPLETED")
            ):
                raise Conflict("LIFECYCLE_CONFLICT") from exc

    def _verify(self, meta, rows):
        page_args = {"KeyConditionExpression": Key("PK").eq(meta["PK"]), "ConsistentRead": True}
        found = {}
        while True:
            page = self.table.query(**page_args)
            for item in page.get("Items", []):
                if item["SK"] in found:
                    raise Conflict("DUPLICATE_METRIC_KEY")
                found[item["SK"]] = item
            if not page.get("LastEvaluatedKey"):
                break
            page_args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        if set(found) != {"META", *(r["SK"] for r in rows)}:
            raise Conflict("INCOMPLETE_METRIC_SET")
        expected_meta = {k: v for k, v in meta.items() if k != "status"}
        if canonical(expected_meta) != canonical(
            {k: v for k, v in found["META"].items() if k != "status"}
        ):
            raise Conflict("META_HASH_MISMATCH")
        for row in rows:
            if canonical(row) != canonical(found[row["SK"]]):
                raise Conflict("METRIC_HASH_MISMATCH")

    def promote(self, meta):
        current = self.get(meta["PK"], "META")
        if (
            not current
            or current["status"] != "COMPLETED"
            or current["payload_hash"] != meta["payload_hash"]
        ):
            raise Conflict("NOT_COMPLETED")
        try:
            self.table.update_item(
                Key={"PK": "ASSET#" + component(meta["asset"]), "SK": "STATE"},
                UpdateExpression="SET latest_run_pk = :pk, latest_run_id = :id, latest_run_order = :order",
                ConditionExpression="attribute_not_exists(latest_run_order) OR latest_run_order < :order OR (latest_run_order = :order AND latest_run_pk = :pk)",
                ExpressionAttributeValues={
                    ":pk": meta["PK"],
                    ":id": meta["run_id"],
                    ":order": meta["run_order"],
                },
            )
            return "promoted"
        except ClientError as exc:
            if error_code(exc) != "ConditionalCheckFailedException":
                raise
            state = self.get("ASSET#" + component(meta["asset"]), "STATE")
            if state and state["latest_run_order"] > meta["run_order"]:
                return "superseded"
            raise Conflict("RUN_ORDER_CONFLICT") from exc

    def publish(self, result: dict, verify_sources=lambda: None, champion_guard=lambda: True):
        validate_result(result)
        rows = metric_items(result)
        payload = deepcopy(
            {k: v for k, v in result.items() if k not in ("observations", "by_horizon")}
        )
        payload["by_horizon"] = [
            {"h": g["h"], **{m: g[m] for m in METRICS}} for g in result["by_horizon"]
        ]
        payload["derived_metrics"] = {
            "width_80_pct": {
                "overall": result["overall"]["width_80_pct"],
                "by_horizon": [{"h": g["h"], **g["width_80_pct"]} for g in result["by_horizon"]],
            }
        }
        payload.update(
            PK=run_pk(result), SK="META", metric_hashes={r["SK"]: r["payload_hash"] for r in rows}
        )
        payload["payload_hash"] = digest(payload)
        meta = dict(payload, status="RUNNING")
        # Fail explicitly before partial writes if metadata would exceed DynamoDB limits.
        if len(canonical(meta)) > 350_000:
            raise ValueError("META_TOO_LARGE: reduce audit configuration; no truncation allowed")
        verify_sources()
        if not champion_guard():
            raise Conflict("CHAMPION_CONFIG_CHANGED")
        stored = self._put_once(meta, meta=True)
        try:
            for row in rows:
                self._put_once(row)
            if stored["status"] != "COMPLETED":
                self._transition(meta, "RUNNING", "VALIDATING")
            self._verify(meta, rows)
            verify_sources()
            if not champion_guard():
                raise Conflict("CHAMPION_CONFIG_CHANGED")
            if stored["status"] != "COMPLETED":
                self._transition(meta, "VALIDATING", "COMPLETED")
            return self.promote(meta)
        except Conflict:
            # Terminal semantic failures; transport/crash failures remain resumable.
            current = self.get(meta["PK"], "META")
            if current and current["status"] in ("RUNNING", "VALIDATING"):
                self._transition(meta, current["status"], "FAILED")
            raise

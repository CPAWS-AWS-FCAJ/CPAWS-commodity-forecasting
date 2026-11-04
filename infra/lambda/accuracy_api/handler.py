"""Read-only Accuracy API Lambda for RFC #45 v4.6."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from decimal import Decimal
from urllib.parse import quote

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from response import build_response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ASSETS = {"gold", "silver", "brent", "wti"}
METRICS = ("coverage_80", "width_80", "sign_accuracy", "up_rate")
HORIZONS = tuple(range(1, 8))
DISPLAY_METRICS = (*METRICS, "width_80_pct")

TABLE_NAME = os.environ.get("ACCURACY_TABLE_NAME", "")
MODEL_VERSIONS = json.loads(os.environ.get("MODEL_VERSIONS", "{}"))
CHAMPION_EFFECTIVE_BASE_DATES = json.loads(os.environ.get("CHAMPION_EFFECTIVE_BASE_DATES", "{}"))

dynamodb = boto3.resource("dynamodb")


class AccuracyUnavailable(Exception):
    """Stored accuracy data is incomplete or fails integrity checks."""


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
        },
        "body": json.dumps(body, ensure_ascii=False, default=_json_default),
    }


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _canonical(value) -> bytes:
    """Match src.eval.rolling_accuracy.canonical for DynamoDB values."""

    def encode(item):
        if isinstance(item, dict):
            return {
                str(key): encode(val)
                for key, val in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, (list, tuple)):
            return [encode(val) for val in item]
        if isinstance(item, bool):
            return item
        if isinstance(item, (float, Decimal, int)):
            number = Decimal(str(item))
            if not number.is_finite():
                raise ValueError("nonfinite number")
            normalized = format(number.normalize(), "f") if number else "0"
            return {"$number": normalized}
        return item

    return json.dumps(
        encode(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _component(value: str) -> str:
    return quote(str(value), safe="-._~")


def _run_pk(asset: str, model: str, run_id: str) -> str:
    return "RUN#" + "#".join(_component(value) for value in (asset, model, run_id))


def _expected_metric_keys(meta: dict) -> set[str]:
    window = meta.get("window")
    if not isinstance(window, dict):
        raise AccuracyUnavailable("window_missing")

    values = (
        window.get("window_start"),
        window.get("window_end"),
        window.get("target_cutoff_date"),
    )
    if not all(isinstance(value, str) and value for value in values):
        raise AccuracyUnavailable("window_dates_invalid")

    parts = ("all", "rolling_8w", *values)
    prefix = "METRIC#" + "#".join(_component(value) for value in parts)

    return {f"{prefix}#H{h}#{metric}" for h in HORIZONS for metric in METRICS}


def _query_all(table, pk: str) -> list[dict]:
    """Read the complete RUN partition using strongly consistent pagination."""

    items = []
    kwargs = {
        "KeyConditionExpression": Key("PK").eq(pk),
        "ConsistentRead": True,
    }

    while True:
        page = table.query(**kwargs)
        items.extend(page.get("Items", []))

        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            break

        kwargs["ExclusiveStartKey"] = last_key

    return items


def _verify_metric(item: dict) -> None:
    supplied_hash = item.get("payload_hash")
    if not isinstance(supplied_hash, str):
        raise AccuracyUnavailable("metric_hash_missing")

    payload = {key: value for key, value in item.items() if key != "payload_hash"}
    if _digest(payload) != supplied_hash:
        raise AccuracyUnavailable("metric_hash_mismatch")


def _verify_meta(meta: dict) -> None:
    supplied_hash = meta.get("payload_hash")
    if not isinstance(supplied_hash, str):
        raise AccuracyUnavailable("meta_hash_missing")

    payload = {key: value for key, value in meta.items() if key not in {"payload_hash", "status"}}
    if _digest(payload) != supplied_hash:
        raise AccuracyUnavailable("meta_hash_mismatch")


def _verify_meta_identity(
    meta: dict,
    *,
    run_pk: str,
    run_id: str,
    run_order: str,
    asset: str,
) -> None:
    """Verify META identity and the writer's run-level provenance."""

    if meta.get("PK") != run_pk or meta.get("SK") != "META":
        raise AccuracyUnavailable("meta_key_mismatch")

    if (
        meta.get("run_id") != run_id
        or meta.get("run_order") != run_order
        or meta.get("asset") != asset
    ):
        raise AccuracyUnavailable("run_identity_mismatch")

    model = meta.get("model_version")
    effective = meta.get("effective")

    if not isinstance(model, str) or not model:
        raise AccuracyUnavailable("model_version_invalid")

    if not isinstance(effective, str) or not effective:
        raise AccuracyUnavailable("effective_date_invalid")

    if meta.get("evaluation_kind") != "rolling_8w":
        raise AccuracyUnavailable("evaluation_kind_invalid")

    if meta.get("sample") != "all":
        raise AccuracyUnavailable("sample_invalid")

    if not isinstance(meta.get("config_hash"), str) or not meta["config_hash"]:
        raise AccuracyUnavailable("config_hash_missing")

    if not isinstance(meta.get("evaluated_at"), str) or not meta["evaluated_at"]:
        raise AccuracyUnavailable("evaluated_at_missing")

    window = meta.get("window")
    if not isinstance(window, dict):
        raise AccuracyUnavailable("window_missing")

    if (
        window.get("basis") != "base_date"
        or window.get("days") != 56
        or window.get("window_start") is None
        or window.get("window_end") is None
        or window.get("target_cutoff_date") is None
    ):
        raise AccuracyUnavailable("window_invalid")

    first_eligible = window.get("first_eligible_base_date")
    last_eligible = meta.get("last_eligible_base_date")

    if first_eligible is not None:
        if not isinstance(first_eligible, str) or first_eligible < effective:
            raise AccuracyUnavailable("first_eligible_base_date_invalid")

        if not isinstance(last_eligible, str) or last_eligible < first_eligible:
            raise AccuracyUnavailable("eligible_date_range_invalid")

        if last_eligible > window["window_end"]:
            raise AccuracyUnavailable("eligible_date_after_window_end")
    elif last_eligible is not None:
        raise AccuracyUnavailable("eligible_date_range_invalid")

    if window["target_cutoff_date"] < window["window_start"]:
        raise AccuracyUnavailable("cutoff_before_window_start")


def _verify_metric_provenance(
    item: dict,
    *,
    run_pk: str,
    meta: dict,
) -> None:
    window = meta["window"]

    expected = {
        "PK": run_pk,
        "run_id": meta["run_id"],
        "config_hash": meta["config_hash"],
        "model_version": meta["model_version"],
        "asset": meta["asset"],
        "sample": "all",
        "evaluation_kind": "rolling_8w",
        "evaluation_start": window["window_start"],
        "evaluation_end": window["window_end"],
        "target_cutoff_date": window["target_cutoff_date"],
    }

    for field, expected_value in expected.items():
        if item.get(field) != expected_value:
            raise AccuracyUnavailable("metric_provenance_mismatch")


def _metric_groups(
    meta: dict,
    metric_items: list[dict],
    *,
    run_pk: str,
) -> tuple[dict, list[dict], dict]:
    """Verify 28 rows, manifest, META projections and derived metrics."""

    expected_keys = _expected_metric_keys(meta)
    actual_keys = [item.get("SK") for item in metric_items]

    if len(metric_items) != 28 or len(set(actual_keys)) != 28:
        raise AccuracyUnavailable("metric_count_invalid")

    if set(actual_keys) != expected_keys:
        raise AccuracyUnavailable("metric_manifest_mismatch")

    manifest = meta.get("metric_hashes")
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise AccuracyUnavailable("metric_manifest_invalid")

    by_horizon = {h: {"h": h} for h in HORIZONS}

    for item in metric_items:
        _verify_metric(item)
        _verify_metric_provenance(item, run_pk=run_pk, meta=meta)

        sk = item["SK"]
        if manifest.get(sk) != item["payload_hash"]:
            raise AccuracyUnavailable("metric_manifest_hash_mismatch")

        horizon = item.get("h")
        metric = item.get("metric")

        if isinstance(horizon, bool) or horizon not in HORIZONS or metric not in METRICS:
            raise AccuracyUnavailable("metric_identity_invalid")

        expected_suffix = f"#H{horizon}#{metric}"
        if not sk.endswith(expected_suffix):
            raise AccuracyUnavailable("metric_key_identity_mismatch")

        if metric in by_horizon[horizon]:
            raise AccuracyUnavailable("duplicate_metric")

        metric_value = {
            key: item[key]
            for key in (
                "value",
                "n_obs",
                "status",
                "undefined_reason",
                "covered_count",
                "n_base_dates",
                "unit",
            )
            if key in item
        }
        by_horizon[horizon][metric] = metric_value

    for horizon in HORIZONS:
        if set(by_horizon[horizon]) != {"h", *METRICS}:
            raise AccuracyUnavailable("horizon_metrics_incomplete")

    overall = meta.get("overall")
    stored_by_horizon = meta.get("by_horizon")

    if not isinstance(overall, dict) or not isinstance(stored_by_horizon, list):
        raise AccuracyUnavailable("meta_metrics_missing")

    if set(overall) != set(DISPLAY_METRICS):
        raise AccuracyUnavailable("overall_metric_set_invalid")

    if len(stored_by_horizon) != 7:
        raise AccuracyUnavailable("meta_horizon_count_invalid")

    expected_by_horizon = [by_horizon[h] for h in HORIZONS]

    if _canonical(stored_by_horizon) != _canonical(expected_by_horizon):
        raise AccuracyUnavailable("meta_horizon_projection_mismatch")

    for horizon in HORIZONS:
        stored_horizon = stored_by_horizon[horizon - 1]
        if stored_horizon.get("h") != horizon:
            raise AccuracyUnavailable("meta_horizon_order_invalid")

    derived = meta.get("derived_metrics")
    if not isinstance(derived, dict) or set(derived) != {"width_80_pct"}:
        raise AccuracyUnavailable("derived_metrics_invalid")

    width = derived["width_80_pct"]
    if not isinstance(width, dict) or set(width) != {"overall", "by_horizon"}:
        raise AccuracyUnavailable("derived_width_invalid")

    if "width_80_pct" not in overall:
        raise AccuracyUnavailable("overall_derived_width_missing")

    if _canonical(width["overall"]) != _canonical(overall["width_80_pct"]):
        raise AccuracyUnavailable("overall_derived_width_mismatch")

    derived_horizons = width["by_horizon"]
    if not isinstance(derived_horizons, list) or len(derived_horizons) != 7:
        raise AccuracyUnavailable("derived_horizon_count_invalid")

    for index, horizon in enumerate(HORIZONS):
        entry = derived_horizons[index]

        if not isinstance(entry, dict) or entry.get("h") != horizon:
            raise AccuracyUnavailable("derived_horizon_order_invalid")

        metric = {key: value for key, value in entry.items() if key != "h"}

        n_obs = metric.get("n_obs")

        if isinstance(n_obs, bool):
            raise AccuracyUnavailable("derived_horizon_n_obs_invalid")

        if isinstance(n_obs, Decimal):
            if not n_obs.is_finite() or n_obs != n_obs.to_integral_value():
                raise AccuracyUnavailable("derived_horizon_n_obs_invalid")
            n_obs = int(n_obs)
        elif not isinstance(n_obs, int):
            raise AccuracyUnavailable("derived_horizon_n_obs_invalid")

        if n_obs < 0:
            raise AccuracyUnavailable("derived_horizon_n_obs_invalid")

        metric["n_obs"] = n_obs

        if metric.get("status") not in ("ok", "undefined"):
            raise AccuracyUnavailable("derived_horizon_status_invalid")

        if metric.get("unit") != "percent":
            raise AccuracyUnavailable("derived_horizon_unit_invalid")

        if metric["status"] == "undefined" and metric.get("value") is not None:
            raise AccuracyUnavailable("derived_horizon_value_invalid")

        if metric["status"] == "ok" and metric.get("value") is None:
            raise AccuracyUnavailable("derived_horizon_value_invalid")

    return overall, expected_by_horizon, derived


def _read_state(table, asset: str):
    return table.get_item(
        Key={"PK": f"ASSET#{asset}", "SK": "STATE"},
        ConsistentRead=True,
    ).get("Item")


def _read_cycle(table, asset: str):
    """Read and verify one complete STATE -> RUN -> STATE cycle."""

    state = _read_state(table, asset)

    if state is None:
        # Confirm that STATE did not appear while this read cycle was running.
        if _read_state(table, asset) is not None:
            raise AccuracyUnavailable("state_pointer_changed")
        return None

    run_pk = state.get("latest_run_pk")
    run_id = state.get("latest_run_id")
    run_order = state.get("latest_run_order")

    if not all(isinstance(value, str) and value for value in (run_pk, run_id, run_order)):
        raise AccuracyUnavailable("state_pointer_invalid")

    items = _query_all(table, run_pk)

    meta_items = [item for item in items if item.get("SK") == "META"]
    metric_items = [
        item
        for item in items
        if isinstance(item.get("SK"), str) and item["SK"].startswith("METRIC#")
    ]

    if len(meta_items) != 1:
        raise AccuracyUnavailable("meta_count_invalid")

    if len(items) != 29:
        raise AccuracyUnavailable("run_item_count_invalid")

    meta = meta_items[0]

    # Verify integrity before checking whether this run belongs to the
    # currently configured champion.
    _verify_meta(meta)

    if meta.get("status") != "COMPLETED":
        raise AccuracyUnavailable("run_not_completed")

    _verify_meta_identity(
        meta,
        run_pk=run_pk,
        run_id=run_id,
        run_order=run_order,
        asset=asset,
    )

    if _run_pk(asset, meta["model_version"], run_id) != run_pk:
        raise AccuracyUnavailable("run_pk_identity_mismatch")

    overall, by_horizon, derived = _metric_groups(
        meta,
        metric_items,
        run_pk=run_pk,
    )

    evidence = meta.get("evaluation_evidence")
    if not isinstance(evidence, dict):
        raise AccuracyUnavailable("evaluation_evidence_missing")

    if (
        evidence.get("schedule_basis") != "trading_calendar_and_predict_schedule"
        or evidence.get("schedule_evidence_status") != "not_audited_mvp"
    ):
        raise AccuracyUnavailable("evaluation_evidence_invalid")

    # Detect a concurrent promotion after the RUN partition has been read.
    after = _read_state(table, asset)
    if after != state:
        raise AccuracyUnavailable("state_pointer_changed")

    return {
        "state": state,
        "meta": meta,
        "overall": overall,
        "by_horizon": by_horizon,
        "derived": derived,
    }


def _not_ready(asset: str, current_model: str) -> dict:
    """Use the v3.1 not_ready fixture and the currently configured champion."""

    return build_response(
        asset=asset,
        model_version=current_model,
        meta=None,
        overall={},
        by_horizon=[],
        derived_metrics={},
    )


def handler(event, context):
    """API Gateway REST handler: GET /accuracy/{asset}."""

    asset = ((event.get("pathParameters") or {}).get("asset") or "").lower()

    if asset not in ASSETS:
        return _response(400, {"error": "invalid_asset"})

    current_model = MODEL_VERSIONS.get(asset)
    current_effective = CHAMPION_EFFECTIVE_BASE_DATES.get(asset)

    if (
        not isinstance(current_model, str)
        or not current_model
        or not isinstance(current_effective, str)
        or not current_effective
    ):
        logger.error("Champion configuration missing for asset=%s", asset)
        return _response(503, {"error": "accuracy_unavailable"})

    if not TABLE_NAME:
        logger.error("ACCURACY_TABLE_NAME is not configured")
        return _response(503, {"error": "accuracy_unavailable"})

    table = dynamodb.Table(TABLE_NAME)

    for attempt in range(2):
        try:
            result = _read_cycle(table, asset)

            if result is None:
                return _response(200, _not_ready(asset, current_model))

            meta = result["meta"]

            # Integrity has already been verified. A valid run from an old
            # champion or a different effective scope is simply not_ready.
            if meta["model_version"] != current_model or meta["effective"] != current_effective:
                return _response(200, _not_ready(asset, current_model))

            response_meta = {
                "run_id": meta["run_id"],
                "evaluated_at": meta["evaluated_at"],
                "window": meta["window"],
                "evaluation_evidence": meta["evaluation_evidence"],
            }

            payload = build_response(
                asset=asset,
                model_version=current_model,
                meta=response_meta,
                overall=result["overall"],
                by_horizon=result["by_horizon"],
                derived_metrics=result["derived"],
            )
            return _response(200, payload)

        except (
            AccuracyUnavailable,
            BotoCoreError,
            ClientError,
            KeyError,
            TypeError,
            ValueError,
            ArithmeticError,
        ) as exc:
            logger.warning(
                "Accuracy read attempt %s failed for asset=%s reason=%s",
                attempt + 1,
                asset,
                type(exc).__name__,
            )

            if attempt == 1:
                break

    return _response(503, {"error": "accuracy_unavailable"})

"""Read-only API handlers for the CPAWS Forecasts DynamoDB table."""

from __future__ import annotations

import json
import math
import os
import re
from datetime import date
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

ASSETS = ("gold", "silver", "brent", "wti")
QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
PRICE_INDEX = {"p10": 1, "p50": 3, "p90": 5}
DISCLAIMER = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
PROXY_NOTE = (
    "Dự báo vàng và bạc sử dụng ETF proxy GLD/SLV; "
    "giá hiển thị được quy đổi theo quy ước của dự án, "
    "không phải giá giao ngay trực tiếp của kim loại."
)


def _response(status_code: int, body: dict) -> dict:
    """API Gateway REST API proxy response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
        },
        "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    }


def _json_value(value):
    """Convert DynamoDB Decimal and nested values into JSON-safe values."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _table():
    table_name = os.environ.get("FORECASTS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("FORECASTS_TABLE_NAME environment variable is missing")

    region = os.environ.get("AWS_REGION", "ap-southeast-1")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _latest_record(table, asset: str) -> dict | None:
    result = table.query(
        KeyConditionExpression=Key("asset").eq(asset),
        ScanIndexForward=False,
        Limit=1,
    )
    items = result.get("Items", [])
    return items[0] if items else None


def _exact_record(table, asset: str, base_date: str) -> dict | None:
    result = table.query(
        KeyConditionExpression=(Key("asset").eq(asset) & Key("base_date").eq(base_date)),
        Limit=1,
    )
    items = result.get("Items", [])
    return items[0] if items else None


def _price(last_price, log_return) -> float:
    value = float(last_price) * math.exp(float(log_return))
    if not math.isfinite(value):
        raise ValueError("Calculated price is not finite")
    return value


def _summary_item(record: dict) -> dict:
    last_price = float(record["last_price"])
    horizons = record["horizons"]
    by_h = {int(item["h"]): item for item in horizons}

    def horizon_summary(h: int) -> dict:
        item = by_h[h]
        q = item["q"]
        return {
            "target_date": item["target_date"],
            "p10": _price(last_price, q[PRICE_INDEX["p10"]]),
            "p50": _price(last_price, q[PRICE_INDEX["p50"]]),
            "p90": _price(last_price, q[PRICE_INDEX["p90"]]),
            "prob_up": float(item["prob_up"]),
        }

    asset = record["asset"]
    result = {
        "asset": asset,
        "target_series": record["target_series"],
        "base_date": record["base_date"],
        "created_at": record["created_at"],
        "model_version": record["model_version"],
        "last_price": last_price,
        "price_unit": record["price_unit"],
        "h1": horizon_summary(1),
        "h7": horizon_summary(7),
        "stale": bool(record.get("stale_sources", [])),
        "roll_in_horizon": bool(record.get("roll_in_horizon", False)),
        "is_sample": bool(record.get("is_sample", False)),
    }
    if asset in ("gold", "silver"):
        result["proxy_note"] = PROXY_NOTE
    return result


def _detail_item(record: dict) -> dict:
    last_price = float(record["last_price"])
    horizons = []

    for item in sorted(record["horizons"], key=lambda x: int(x["h"])):
        q = [float(value) for value in item["q"]]
        horizons.append(
            {
                "h": int(item["h"]),
                "target_date": item["target_date"],
                "returns": q,
                "prices": [_price(last_price, value) for value in q],
                "prob_up": float(item["prob_up"]),
            }
        )

    asset = record["asset"]
    result = {
        "asset": asset,
        "target_series": record["target_series"],
        "base_date": record["base_date"],
        "last_price": last_price,
        "price_unit": record["price_unit"],
        "quantile_levels": _json_value(record["quantile_levels"]),
        "horizons": horizons,
        "fx": {
            "usd_vnd": _json_value(record["fx_usd_vnd"]),
            "date": record["fx_date"],
        },
        "stale_sources": record.get("stale_sources", []),
        "roll_in_horizon": bool(record.get("roll_in_horizon", False)),
        "is_sample": bool(record.get("is_sample", False)),
        "disclaimer": DISCLAIMER,
    }
    if asset in ("gold", "silver"):
        result["proxy_note"] = PROXY_NOTE
    return result


def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def handler(event, context):
    # API Gateway REST API provides the route template in "resource".
    # Prefer it so the "/dev" stage prefix in "path" does not break routing.
    path = event.get("resource") or event.get("path", "")
    method = event.get("httpMethod", "GET").upper()

    if method != "GET":
        return _response(
            405,
            {
                "error": "method_not_allowed",
                "message": "Only GET is supported.",
            },
        )

    if path.rstrip("/") == "/health":
        return _response(200, {"status": "ok"})

    if path.rstrip("/") not in ("/forecasts",) and not path.startswith("/forecasts/"):
        return _response(
            404,
            {
                "error": "not_found",
                "message": "Endpoint not found.",
            },
        )

    path_params = event.get("pathParameters") or {}
    asset = path_params.get("asset")
    query_params = event.get("queryStringParameters") or {}
    requested_date = query_params.get("date")

    if path.rstrip("/") == "/forecasts":
        if asset is not None:
            return _response(
                400,
                {
                    "error": "invalid_asset",
                    "message": "Do not specify an asset on /forecasts.",
                },
            )
    else:
        if not asset or asset not in ASSETS:
            return _response(
                400,
                {
                    "error": "invalid_asset",
                    "message": f"asset must be one of: {', '.join(ASSETS)}.",
                },
            )

    if requested_date is not None and not _valid_date(requested_date):
        return _response(
            400,
            {
                "error": "invalid_date",
                "message": "date must use the YYYY-MM-DD format and be a valid date.",
            },
        )

    try:
        table = _table()

        if path.rstrip("/") == "/forecasts":
            items = []
            for name in ASSETS:
                record = _latest_record(table, name)
                if record is not None:
                    items.append(_summary_item(record))

            return _response(
                200,
                {
                    "items": items,
                    "disclaimer": DISCLAIMER,
                },
            )

        if requested_date is None:
            record = _latest_record(table, asset)
        else:
            record = _exact_record(table, asset, requested_date)

        if record is None:
            return _response(
                404,
                {
                    "error": "not_found",
                    "message": "No forecast found for the requested asset and date.",
                },
            )

        return _response(200, _detail_item(record))

    except Exception:  # noqa: BLE001
        # Do not expose AWS details or internal exception messages to API clients.
        print("Forecast API request failed.")
        return _response(
            500,
            {
                "error": "internal_error",
                "message": "Unable to retrieve forecasts.",
            },
        )

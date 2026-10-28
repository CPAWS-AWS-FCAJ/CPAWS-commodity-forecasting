"""Read-only API handlers for the CPAWS Forecasts DynamoDB table."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date

import boto3

# Đọc và định dạng bản ghi dùng chung với tool get_forecast của chatbot (forecast_format.py cùng
# thư mục, nằm trong cùng asset Lambda). Giữ tên cũ để code và test hiện có không đổi.
from forecast_format import ASSETS, DISCLAIMER
from forecast_format import detail_item as _detail_item
from forecast_format import exact_record as _exact_record
from forecast_format import latest_record as _latest_record
from forecast_format import summary_item as _summary_item

logger = logging.getLogger(__name__)


def _response(status_code: int, body: dict) -> dict:
    """API Gateway REST API proxy response."""
    allowed_origin = os.environ.get("ALLOWED_ORIGIN", "*")

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": allowed_origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
        },
        "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    }


def _table():
    table_name = os.environ.get("FORECASTS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("FORECASTS_TABLE_NAME environment variable is missing")

    region = os.environ.get("AWS_REGION", "ap-southeast-1")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


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

    except Exception:
        # Log traceback for operators without exposing internal details to clients.
        logger.exception("Forecast API request failed.")
        return _response(
            500,
            {
                "error": "internal_error",
                "message": "Unable to retrieve forecasts.",
            },
        )

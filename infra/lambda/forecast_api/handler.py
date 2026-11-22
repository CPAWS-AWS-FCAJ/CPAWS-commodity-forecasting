"""Read-only API handlers for the CPAWS Forecasts DynamoDB table."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from datetime import date
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Đọc và định dạng bản ghi dùng chung với tool get_forecast của chatbot (forecast_format.py cùng
# thư mục, nằm trong cùng asset Lambda). Giữ tên cũ để code và test hiện có không đổi.
from forecast_format import ASSETS, DISCLAIMER
from forecast_format import detail_item as _detail_item
from forecast_format import exact_record as _exact_record
from forecast_format import json_value as _json_value
from forecast_format import latest_record as _latest_record
from forecast_format import summary_item as _summary_item

logger = logging.getLogger(__name__)

# Tham số ?history= của GET /forecasts/{asset}: số phiên giá cuối gần nhất trả kèm (trang Tổng
# quan giá, biểu đồ trang sản phẩm). 520 phiên ~ 2 năm giao dịch. Bảng Forecasts chỉ có dữ liệu từ
# khi predict chạy thật; điểm cũ hơn lấy từ file JSON xuất một lần từ lake
# (scripts/export_price_history.py, docs/api/contract.md mục "Tham số history").
HISTORY_MAX = 520
# Mỗi lần Query đọc tối đa ngần này bản ghi; ProjectionExpression chỉ lấy 3 trường nên nhẹ.
HISTORY_PAGE_SIZE = 100

# File lịch sử giá: s3://<PRICE_HISTORY_BUCKET>/<PRICE_HISTORY_PREFIX><asset>.json. Không có
# PRICE_HISTORY_BUCKET thì chỉ đọc bảng Forecasts (hành vi cũ).
PRICE_HISTORY_PREFIX_DEFAULT = "serving/price-history/"
# Đơn vị giá trong file phải khớp đơn vị last_price của Forecasts (forecast_record.PRICE_UNIT);
# khác (ví dụ giá GLD theo USD/share) thì bỏ cả file.
PRICE_HISTORY_UNITS = {"gold": "USD/oz", "silver": "USD/oz", "brent": "USD/bbl", "wti": "USD/bbl"}
# File chỉ đổi khi chạy lại script xuất, nên giữ trong bộ nhớ container ~30 phút theo asset.
# Lần đọc lỗi không được cache: request sau đọc lại.
PRICE_HISTORY_CACHE_SECONDS = 30 * 60
_price_history_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_s3_client_cache = None
# Đồng hồ cho cache; test thay bằng hàm giả
_clock = time.monotonic


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


def _parse_history(value: str) -> int | None:
    """Số phiên hợp lệ (1..HISTORY_MAX) hoặc None nếu sai định dạng hay ngoài khoảng."""
    if not re.fullmatch(r"\d{1,3}", value):
        return None
    sessions = int(value)
    return sessions if 1 <= sessions <= HISTORY_MAX else None


def _valid_price(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    number = float(value)
    return math.isfinite(number) and number > 0


def _forecasts_price_history(table, asset: str, sessions: int) -> list[dict]:
    """Giá cuối phiên của `sessions` bản ghi gần nhất trong bảng Forecasts, xếp cũ → mới.

    Bỏ bản ghi mẫu (`is_sample = true`) và bản ghi thiếu `last_price` hợp lệ; đọc thêm trang nếu
    trang đầu bị lọc bớt. Chỉ đọc `base_date`, `last_price`, `is_sample` (ProjectionExpression).
    """
    points: list[dict] = []
    query = {
        "KeyConditionExpression": "#asset = :asset",
        "ExpressionAttributeNames": {
            "#asset": "asset",
            "#base_date": "base_date",
            "#last_price": "last_price",
            "#is_sample": "is_sample",
        },
        "ExpressionAttributeValues": {":asset": asset},
        "ProjectionExpression": "#base_date, #last_price, #is_sample",
        "ScanIndexForward": False,
        "Limit": HISTORY_PAGE_SIZE,
    }
    while len(points) < sessions:
        result = table.query(**query)
        for item in result.get("Items", []):
            if item.get("is_sample") is True or not _valid_price(item.get("last_price")):
                continue
            points.append(
                {"base_date": item["base_date"], "last_price": _json_value(item["last_price"])}
            )
            if len(points) == sessions:
                break
        last_key = result.get("LastEvaluatedKey")
        if not last_key:
            break
        query["ExclusiveStartKey"] = last_key
    points.reverse()
    return points


def _s3_client():
    """Client S3 dùng lại giữa các request. Timeout ngắn, tối đa 2 lượt (khoảng 6 giây xấu nhất)
    để lỗi S3 không làm request vượt Lambda timeout 10 giây."""
    global _s3_client_cache
    if _s3_client_cache is None:
        from botocore.config import Config

        region = os.environ.get("AWS_REGION", "ap-southeast-1")
        _s3_client_cache = boto3.client(
            "s3",
            region_name=region,
            config=Config(
                connect_timeout=1,
                read_timeout=2,
                retries={"total_max_attempts": 2, "mode": "standard"},
            ),
        )
    return _s3_client_cache


def _parse_price_history_file(document, asset: str) -> dict:
    """{base_date: last_price} từ file JSON; bỏ điểm sai ngày hoặc giá không dương/không hữu hạn.
    Sai cấu trúc → TypeError; sai asset hay sai đơn vị → ValueError."""
    if not isinstance(document, dict) or not isinstance(document.get("points"), list):
        raise TypeError("price history file must be an object with a points list")
    if document.get("asset") != asset:
        raise ValueError(f"price history file is for asset {document.get('asset')!r}")
    if document.get("unit") != PRICE_HISTORY_UNITS[asset]:
        raise ValueError(f"price history file has unit {document.get('unit')!r}")
    prices = {}
    for point in document["points"]:
        if not isinstance(point, dict):
            continue
        base_date, price = point.get("base_date"), point.get("last_price")
        if isinstance(base_date, str) and _valid_date(base_date) and _valid_price(price):
            prices[base_date] = price
    return prices


def _archived_price_history(asset: str) -> dict:
    """{base_date: last_price} từ s3://PRICE_HISTORY_BUCKET/<prefix><asset>.json, cache theo asset.

    Không có PRICE_HISTORY_BUCKET → {}. Mọi lỗi (không có file, AccessDenied, JSON hỏng) → log
    WARNING kèm asset và lỗi, trả {} để API vẫn trả phần lấy từ Forecasts."""
    bucket = os.environ.get("PRICE_HISTORY_BUCKET", "").strip()
    if not bucket:
        return {}
    prefix = os.environ.get("PRICE_HISTORY_PREFIX", PRICE_HISTORY_PREFIX_DEFAULT)
    key = f"{prefix}{asset}.json"
    now = _clock()
    cached = _price_history_cache.get((bucket, key))
    if cached is not None and now - cached[0] < PRICE_HISTORY_CACHE_SECONDS:
        return cached[1]
    try:
        body = _s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
        prices = _parse_price_history_file(json.loads(body), asset)
    except (BotoCoreError, ClientError, KeyError, TypeError, ValueError) as error:
        # ClientError: NoSuchKey, AccessDenied (không có s3:ListBucket thì thiếu file cũng là
        # AccessDenied); BotoCoreError: timeout, mạng; ValueError: JSON hỏng, sai asset/đơn vị.
        code = (getattr(error, "response", None) or {}).get("Error", {}).get("Code")
        logger.warning(
            "PRICE_HISTORY_FILE_UNAVAILABLE asset=%s bucket=%s key=%s error=%s code=%s detail=%s",
            asset,
            bucket,
            key,
            type(error).__name__,
            code,
            str(error)[:200],
        )
        return {}
    _price_history_cache[(bucket, key)] = (now, prices)
    return prices


def _price_history(table, asset: str, sessions: int) -> list[dict]:
    """Giá cuối phiên của `sessions` phiên gần nhất, xếp cũ → mới.

    Lấy từ bảng Forecasts trước; chỉ khi chưa đủ `sessions` điểm mới đọc file lịch sử trên S3.
    Ngày có trong cả hai thì dùng giá của Forecasts. S3 lỗi hoặc chưa cấu hình → chỉ phần Forecasts.
    """
    points = _forecasts_price_history(table, asset, sessions)
    if len(points) >= sessions:
        return points
    archived = _archived_price_history(asset)
    if not archived:
        return points
    merged = dict(archived)
    merged.update((p["base_date"], p["last_price"]) for p in points)
    return [{"base_date": day, "last_price": merged[day]} for day in sorted(merged)[-sessions:]]


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

    raw_history = query_params.get("history")
    history_sessions = None
    if raw_history is not None:
        if path.rstrip("/") == "/forecasts" or requested_date is not None:
            return _response(
                400,
                {
                    "error": "invalid_query",
                    "message": "history is only supported on /forecasts/{asset} without date.",
                },
            )
        history_sessions = _parse_history(raw_history)
        if history_sessions is None:
            return _response(
                400,
                {
                    "error": "invalid_history",
                    "message": f"history must be an integer from 1 to {HISTORY_MAX}.",
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

        body = _detail_item(record)
        if history_sessions is not None:
            body["price_history"] = _price_history(table, asset, history_sessions)
        return _response(200, body)

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

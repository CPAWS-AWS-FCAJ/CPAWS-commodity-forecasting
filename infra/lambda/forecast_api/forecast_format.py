"""Đọc và định dạng bản ghi bảng DynamoDB `Forecasts` theo docs/api/contract.md.

Dùng chung cho Lambda API (`handler.py`, cùng thư mục) và tool `get_forecast` của chatbot
(`src/chatbot/tools.py`), để chatbot đọc đúng dạng `GET /forecasts/{asset}` mà không gọi vòng qua
API Gateway (Khải chốt 26/10). Chỉ dùng thư viện chuẩn: không nạp boto3 lúc import, bảng truyền từ
ngoài vào (boto3 `Table` hoặc bảng giả trong test). Lambda `/chat` cần đóng gói kèm file này.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

ASSETS = ("gold", "silver", "brent", "wti")
QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
PRICE_INDEX = {"p10": 1, "p50": 3, "p90": 5}
DISCLAIMER = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
PROXY_NOTE = (
    "Dự báo vàng và bạc sử dụng ETF proxy GLD/SLV; "
    "giá hiển thị được quy đổi theo quy ước của dự án, "
    "không phải giá giao ngay trực tiếp của kim loại."
)


def json_value(value):
    """Convert DynamoDB Decimal and nested values into JSON-safe values."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


def latest_record(table: Any, asset: str) -> dict | None:
    """Bản ghi mới nhất của tài sản: Query theo `asset`, `ScanIndexForward=False`, `Limit=1`."""
    result = table.query(
        KeyConditionExpression="#asset = :asset",
        ExpressionAttributeNames={"#asset": "asset"},
        ExpressionAttributeValues={":asset": asset},
        ScanIndexForward=False,
        Limit=1,
    )
    items = result.get("Items", [])
    return items[0] if items else None


def exact_record(table: Any, asset: str, base_date: str) -> dict | None:
    """Bản ghi của tài sản tại đúng `base_date` (tham số `?date=` của API)."""
    result = table.query(
        KeyConditionExpression="#asset = :asset AND #base_date = :base_date",
        ExpressionAttributeNames={"#asset": "asset", "#base_date": "base_date"},
        ExpressionAttributeValues={":asset": asset, ":base_date": base_date},
        Limit=1,
    )
    items = result.get("Items", [])
    return items[0] if items else None


def price(last_price, log_return) -> float:
    value = float(last_price) * math.exp(float(log_return))
    if not math.isfinite(value):
        raise ValueError("Calculated price is not finite")
    return value


def summary_item(record: dict) -> dict:
    """Một phần tử của `GET /forecasts` (trang chủ)."""
    last_price = float(record["last_price"])
    by_h = {int(item["h"]): item for item in record["horizons"]}

    def horizon_summary(h: int) -> dict:
        item = by_h[h]
        q = item["q"]
        return {
            "target_date": item["target_date"],
            "p10": price(last_price, q[PRICE_INDEX["p10"]]),
            "p50": price(last_price, q[PRICE_INDEX["p50"]]),
            "p90": price(last_price, q[PRICE_INDEX["p90"]]),
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


def detail_item(record: dict) -> dict:
    """Bản ghi bảng `Forecasts` → JSON `GET /forecasts/{asset}` theo contract."""
    last_price = float(record["last_price"])
    horizons = []

    for item in sorted(record["horizons"], key=lambda x: int(x["h"])):
        q = [float(value) for value in item["q"]]
        horizons.append(
            {
                "h": int(item["h"]),
                "target_date": item["target_date"],
                "returns": q,
                "prices": [price(last_price, value) for value in q],
                "prob_up": float(item["prob_up"]),
            }
        )

    asset = record["asset"]
    result = {
        "asset": asset,
        "target_series": record["target_series"],
        "base_date": record["base_date"],
        "created_at": record["created_at"],
        "model_version": record["model_version"],
        "last_price": last_price,
        "price_unit": record["price_unit"],
        "quantile_levels": json_value(record["quantile_levels"]),
        "horizons": horizons,
        "fx": {
            "usd_vnd": json_value(record["fx_usd_vnd"]),
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

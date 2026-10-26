import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Nạp handler từ thư mục có tên "lambda".
# Không import bằng cú pháp "from infra.lambda..." vì lambda là từ khóa Python.
HANDLER_PATH = (
    Path(__file__).resolve().parents[1] / "infra" / "lambda" / "forecast_api" / "handler.py"
)

# handler import forecast_format cùng thư mục (trong Lambda, thư mục asset nằm trên sys.path)
sys.path.insert(0, str(HANDLER_PATH.parent))
spec = importlib.util.spec_from_file_location("forecast_api_handler", HANDLER_PATH)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def make_record(asset="gold", base_date="2026-10-14"):
    quantiles = [
        Decimal("-0.030000"),
        Decimal("-0.020000"),
        Decimal("-0.010000"),
        Decimal("0.001000"),
        Decimal("0.010000"),
        Decimal("0.020000"),
        Decimal("0.030000"),
    ]

    return {
        "asset": asset,
        "base_date": base_date,
        "created_at": "2026-10-15T12:00:00Z",
        "model_version": "test",
        "target_series": "GLD" if asset == "gold" else "CL=F",
        "last_price": Decimal("100.000000"),
        "price_unit": "USD/oz" if asset == "gold" else "USD/bbl",
        "quantile_levels": [
            Decimal("0.050000"),
            Decimal("0.100000"),
            Decimal("0.250000"),
            Decimal("0.500000"),
            Decimal("0.750000"),
            Decimal("0.900000"),
            Decimal("0.950000"),
        ],
        "horizons": [
            {
                "h": h,
                "target_date": f"2026-10-{14 + h:02d}",
                "q": quantiles,
                "prob_up": Decimal("0.510000"),
            }
            for h in range(1, 8)
        ],
        "fx_usd_vnd": Decimal("26310.000000"),
        "fx_date": "2026-10-14",
        "stale_sources": [],
        "roll_in_horizon": False,
        "is_sample": True,
    }


def decode(response):
    return response["statusCode"], json.loads(response["body"])


def event(path, asset=None, query=None, method="GET"):
    return {
        "path": path,
        "httpMethod": method,
        "pathParameters": {"asset": asset} if asset else {},
        "queryStringParameters": query,
    }


def setup_fake_table(monkeypatch, record=None):
    # Không gọi AWS thật. Thay các hàm đọc DynamoDB bằng dữ liệu giả.
    monkeypatch.setattr(api, "_table", lambda: object())
    monkeypatch.setattr(
        api,
        "_latest_record",
        lambda table, asset: record if record and record["asset"] == asset else None,
    )
    monkeypatch.setattr(
        api,
        "_exact_record",
        lambda table, asset, base_date: (
            record
            if record and record["asset"] == asset and record["base_date"] == base_date
            else None
        ),
    )


def test_health_returns_ok():
    status, body = decode(api.handler(event("/health"), None))
    assert status == 200
    assert body == {"status": "ok"}


def test_unknown_endpoint_returns_404():
    status, body = decode(api.handler(event("/unknown"), None))
    assert status == 404
    assert body["error"] == "not_found"


def test_post_returns_405():
    status, body = decode(api.handler(event("/health", method="POST"), None))
    assert status == 405
    assert body["error"] == "method_not_allowed"


def test_invalid_asset_returns_400():
    status, body = decode(api.handler(event("/forecasts/copper", asset="copper"), None))
    assert status == 400
    assert body["error"] == "invalid_asset"


@pytest.mark.parametrize(
    "requested_date",
    ["2026-02-30", "14-10-2026", "2026/10/14"],
)
def test_invalid_date_returns_400(monkeypatch, requested_date):
    setup_fake_table(monkeypatch, make_record())

    status, body = decode(
        api.handler(
            event(
                "/forecasts/gold",
                asset="gold",
                query={"date": requested_date},
            ),
            None,
        )
    )

    assert status == 400
    assert body["error"] == "invalid_date"


def test_detail_returns_seven_horizons(monkeypatch):
    setup_fake_table(monkeypatch, make_record())

    status, body = decode(api.handler(event("/forecasts/gold", asset="gold"), None))

    assert status == 200
    assert body["asset"] == "gold"
    assert len(body["horizons"]) == 7
    assert body["horizons"][0]["h"] == 1
    assert body["horizons"][0]["prices"][3] == pytest.approx(100 * __import__("math").exp(0.001))
    assert body["fx"]["usd_vnd"] == 26310
    assert body["is_sample"] is True
    assert body["created_at"] == "2026-10-15T12:00:00Z"
    assert body["model_version"] == "test"
    assert "disclaimer" in body


def test_exact_date_not_found_returns_404(monkeypatch):
    setup_fake_table(monkeypatch, make_record())

    status, body = decode(
        api.handler(
            event(
                "/forecasts/gold",
                asset="gold",
                query={"date": "2026-10-15"},
            ),
            None,
        )
    )

    assert status == 404
    assert body["error"] == "not_found"


def test_summary_returns_latest_records(monkeypatch):
    setup_fake_table(monkeypatch, make_record())

    status, body = decode(api.handler(event("/forecasts"), None))

    assert status == 200
    assert len(body["items"]) == 1
    assert body["items"][0]["asset"] == "gold"
    assert body["items"][0]["h1"]["p50"] == pytest.approx(100 * __import__("math").exp(0.001))
    assert body["items"][0]["is_sample"] is True
    assert "disclaimer" in body


def test_response_includes_cors_headers(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGIN", "http://localhost:5173")

    response = api._response(200, {"status": "ok"})

    assert response["headers"]["Access-Control-Allow-Origin"] == ("http://localhost:5173")
    assert response["headers"]["Access-Control-Allow-Headers"] == ("Content-Type,Authorization")
    assert response["headers"]["Access-Control-Allow-Methods"] == "GET,OPTIONS"


def test_latest_record_query_matches_contract():
    """Query theo asset, mới nhất trước, Limit 1 (contract.md; dùng chung với chatbot)."""
    seen = []

    class Table:
        def query(self, **kwargs):
            seen.append(kwargs)
            return {"Items": [make_record("wti")]}

    record = api._latest_record(Table(), "wti")
    assert record["asset"] == "wti"
    assert seen == [
        {
            "KeyConditionExpression": "#asset = :asset",
            "ExpressionAttributeNames": {"#asset": "asset"},
            "ExpressionAttributeValues": {":asset": "wti"},
            "ScanIndexForward": False,
            "Limit": 1,
        }
    ]

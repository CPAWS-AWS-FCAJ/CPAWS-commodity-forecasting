import importlib.util
import io
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

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


@pytest.fixture(autouse=True)
def no_price_history_bucket(monkeypatch):
    """Mặc định không có file lịch sử trên S3 (hành vi cũ); cache và client sạch mỗi test."""
    monkeypatch.delenv("PRICE_HISTORY_BUCKET", raising=False)
    monkeypatch.delenv("PRICE_HISTORY_PREFIX", raising=False)
    monkeypatch.setattr(api, "_price_history_cache", {})
    monkeypatch.setattr(api, "_s3_client_cache", None)


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


@pytest.mark.parametrize(
    ("items", "expected_asset"),
    [([], None), (["found"], "gold")],
)
def test_exact_record_query_matches_contract(items, expected_asset):
    """`?date=`: Query đúng khóa asset + base_date, Limit 1; không có bản ghi thì None
    (Tiến review PR #38: trước đây chỉ có test cho latest_record)."""
    seen = []

    class Table:
        def query(self, **kwargs):
            seen.append(kwargs)
            return {"Items": [make_record("gold")] if items else []}

    record = api._exact_record(Table(), "gold", "2026-10-23")
    assert (record or {}).get("asset") == expected_asset
    assert seen == [
        {
            "KeyConditionExpression": "#asset = :asset AND #base_date = :base_date",
            "ExpressionAttributeNames": {"#asset": "asset", "#base_date": "base_date"},
            "ExpressionAttributeValues": {":asset": "gold", ":base_date": "2026-10-23"},
            "Limit": 1,
        }
    ]


# --- ?history= (trang Tổng quan giá) ---


class PagedHistoryTable:
    """Bảng giả cho _price_history: trả các trang đã định sẵn, ghi lại tham số Query."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        result = {"Items": self.pages[index]}
        if index + 1 < len(self.pages):
            result["LastEvaluatedKey"] = {"asset": "gold", "base_date": f"page-{index}"}
        return result


def history_item(base_date, last_price="100.5", is_sample=False):
    item = {"base_date": base_date, "is_sample": is_sample}
    if last_price is not None:
        item["last_price"] = Decimal(last_price)
    return item


def test_price_history_orders_old_to_new_and_projects_three_fields():
    table = PagedHistoryTable(
        [[history_item("2026-11-19", "101"), history_item("2026-11-18", "100.25")]]
    )
    points = api._price_history(table, "gold", 5)
    assert points == [
        {"base_date": "2026-11-18", "last_price": 100.25},
        {"base_date": "2026-11-19", "last_price": 101},
    ]
    call = table.calls[0]
    assert call["ScanIndexForward"] is False
    assert call["ProjectionExpression"] == "#base_date, #last_price, #is_sample"
    assert call["ExpressionAttributeValues"] == {":asset": "gold"}


def test_price_history_skips_sample_and_invalid_prices_and_reads_next_page():
    table = PagedHistoryTable(
        [
            [
                history_item("2026-11-19", is_sample=True),
                history_item("2026-11-18", last_price=None),
                history_item("2026-11-17", "0"),
            ],
            [history_item("2026-11-14", "98"), history_item("2026-11-13", "97")],
        ]
    )
    points = api._price_history(table, "gold", 2)
    assert [p["base_date"] for p in points] == ["2026-11-13", "2026-11-14"]
    assert len(table.calls) == 2
    assert table.calls[1]["ExclusiveStartKey"] == {"asset": "gold", "base_date": "page-0"}


def test_price_history_stops_at_requested_sessions():
    table = PagedHistoryTable([[history_item(f"2026-11-{day:02d}") for day in range(19, 9, -1)]])
    points = api._price_history(table, "gold", 3)
    assert [p["base_date"] for p in points] == ["2026-11-17", "2026-11-18", "2026-11-19"]


def test_detail_with_history_adds_price_history(monkeypatch):
    setup_fake_table(monkeypatch, make_record())
    seen = []

    def fake_history(table, asset, sessions):
        seen.append((asset, sessions))
        return [{"base_date": "2026-10-14", "last_price": 100}]

    monkeypatch.setattr(api, "_price_history", fake_history)
    status, body = decode(api.handler(event("/forecasts/gold", "gold", {"history": "60"}), None))
    assert status == 200
    assert body["price_history"] == [{"base_date": "2026-10-14", "last_price": 100}]
    assert seen == [("gold", 60)]
    assert len(body["horizons"]) == 7


def test_detail_without_history_has_no_price_history(monkeypatch):
    setup_fake_table(monkeypatch, make_record())
    status, body = decode(api.handler(event("/forecasts/gold", "gold"), None))
    assert status == 200
    assert "price_history" not in body


@pytest.mark.parametrize("value", ["0", "521", "abc", "-5", "1.5", "", "1000"])
def test_invalid_history_returns_400(monkeypatch, value):
    setup_fake_table(monkeypatch, make_record())
    status, body = decode(api.handler(event("/forecasts/gold", "gold", {"history": value}), None))
    assert status == 400
    assert body["error"] == "invalid_history"


def test_history_with_date_returns_400(monkeypatch):
    setup_fake_table(monkeypatch, make_record())
    query = {"history": "30", "date": "2026-10-14"}
    status, body = decode(api.handler(event("/forecasts/gold", "gold", query), None))
    assert status == 400
    assert body["error"] == "invalid_query"


def test_history_on_summary_returns_400(monkeypatch):
    setup_fake_table(monkeypatch, make_record())
    status, body = decode(api.handler(event("/forecasts", query={"history": "30"}), None))
    assert status == 400
    assert body["error"] == "invalid_query"


def test_history_520_is_valid(monkeypatch):
    setup_fake_table(monkeypatch, make_record())
    seen = []
    monkeypatch.setattr(api, "_price_history", lambda t, a, n: seen.append(n) or [])
    status, body = decode(api.handler(event("/forecasts/gold", "gold", {"history": "520"}), None))
    assert status == 200
    assert body["price_history"] == []
    assert seen == [520]


def test_invalid_history_message_names_new_range(monkeypatch):
    setup_fake_table(monkeypatch, make_record())
    _, body = decode(api.handler(event("/forecasts/gold", "gold", {"history": "521"}), None))
    assert body["message"] == "history must be an integer from 1 to 520."


# --- ?history= ghép với file lịch sử trên S3 (serving/price-history/<asset>.json) ---

BUCKET = "cpaws-test-lake"


def archive_document(asset="gold", points=(), unit=None):
    return {
        "asset": asset,
        "unit": unit or api.PRICE_HISTORY_UNITS[asset],
        "source": "Yahoo Finance (yfinance)",
        "generated_at": "2026-11-21T00:00:00Z",
        "last_base_date": points[-1][0] if points else None,
        "points": [{"base_date": d, "last_price": p} for d, p in points],
    }


class FakeS3:
    """Client S3 giả: trả JSON theo key, hoặc raise lỗi đã định; ghi lại các lần get_object."""

    def __init__(self, objects=None, error=None):
        self.objects = objects or {}
        self.error = error
        self.calls = []

    def get_object(self, Bucket, Key):  # tên tham số theo boto3
        self.calls.append((Bucket, Key))
        if self.error is not None:
            raise self.error
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")
        body = self.objects[Key]
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        return {"Body": io.BytesIO(data)}


def use_s3(monkeypatch, fake, prefix=None):
    monkeypatch.setenv("PRICE_HISTORY_BUCKET", BUCKET)
    if prefix is not None:
        monkeypatch.setenv("PRICE_HISTORY_PREFIX", prefix)
    monkeypatch.setattr(api, "_s3_client", lambda: fake)


def table_with(*items):
    return PagedHistoryTable([list(items)])


def test_history_merges_archive_and_prefers_forecasts(monkeypatch):
    fake = FakeS3(
        {
            "serving/price-history/gold.json": archive_document(
                points=[
                    ("2026-10-21", 3900.5),
                    ("2026-10-22", 3910.25),
                    ("2026-10-23", 3920.0),
                    ("2026-10-26", 3930.0),
                ]
            )
        }
    )
    use_s3(monkeypatch, fake)
    table = table_with(
        history_item("2026-10-27", "3951.123456"), history_item("2026-10-26", "3931")
    )
    points = api._price_history(table, "gold", 4)
    assert points == [
        {"base_date": "2026-10-22", "last_price": 3910.25},
        {"base_date": "2026-10-23", "last_price": 3920.0},
        {"base_date": "2026-10-26", "last_price": 3931},  # Forecasts thắng khi trùng ngày
        {"base_date": "2026-10-27", "last_price": 3951.123456},
    ]
    assert fake.calls == [(BUCKET, "serving/price-history/gold.json")]


def test_history_returns_all_merged_points_when_fewer_than_requested(monkeypatch):
    fake = FakeS3({"serving/price-history/wti.json": archive_document("wti", [("2026-10-20", 58)])})
    use_s3(monkeypatch, fake)
    points = api._price_history(table_with(history_item("2026-10-27", "60.5")), "wti", 520)
    assert points == [
        {"base_date": "2026-10-20", "last_price": 58},
        {"base_date": "2026-10-27", "last_price": 60.5},
    ]


def test_history_does_not_read_s3_when_forecasts_has_enough(monkeypatch):
    fake = FakeS3(error=AssertionError("S3 must not be read"))
    use_s3(monkeypatch, fake)
    table = table_with(history_item("2026-11-19", "101"), history_item("2026-11-18", "100"))
    points = api._price_history(table, "gold", 2)
    assert [p["base_date"] for p in points] == ["2026-11-18", "2026-11-19"]
    assert fake.calls == []


def test_history_archive_is_cached_per_asset_for_30_minutes(monkeypatch):
    fake = FakeS3(
        {
            "serving/price-history/gold.json": archive_document("gold", [("2026-10-20", 1)]),
            "serving/price-history/brent.json": archive_document("brent", [("2026-10-20", 2)]),
        }
    )
    use_s3(monkeypatch, fake)
    now = [1000.0]
    monkeypatch.setattr(api, "_clock", lambda: now[0])
    for _ in range(3):
        assert api._price_history(table_with(), "gold", 5)[0]["last_price"] == 1
    api._price_history(table_with(), "brent", 5)
    assert len(fake.calls) == 2  # một lần mỗi asset
    now[0] += api.PRICE_HISTORY_CACHE_SECONDS - 1
    api._price_history(table_with(), "gold", 5)
    assert len(fake.calls) == 2
    now[0] += 2  # hết hạn cache → đọc lại
    api._price_history(table_with(), "gold", 5)
    assert fake.calls[-1] == (BUCKET, "serving/price-history/gold.json")
    assert len(fake.calls) == 3
    assert api.PRICE_HISTORY_CACHE_SECONDS == 30 * 60


def test_history_uses_configured_prefix(monkeypatch):
    fake = FakeS3({"custom/silver.json": archive_document("silver", [("2026-10-20", 48.1)])})
    use_s3(monkeypatch, fake, prefix="custom/")
    points = api._price_history(table_with(), "silver", 3)
    assert points == [{"base_date": "2026-10-20", "last_price": 48.1}]


@pytest.mark.parametrize(
    "fake",
    [
        FakeS3(),  # không có file (NoSuchKey)
        FakeS3(
            error=ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetObject")
        ),
        FakeS3({"serving/price-history/gold.json": b"{not json"}),
        FakeS3({"serving/price-history/gold.json": b"[1, 2]"}),
        FakeS3(
            {"serving/price-history/gold.json": archive_document("silver", [("2026-10-20", 1)])}
        ),
        FakeS3(
            {
                "serving/price-history/gold.json": archive_document(
                    "gold", [("2026-10-20", 1)], unit="USD/share"
                )
            }
        ),
    ],
    ids=["missing", "access_denied", "bad_json", "not_object", "wrong_asset", "wrong_unit"],
)
def test_history_s3_failure_returns_forecasts_part_with_200(monkeypatch, caplog, fake):
    setup_fake_table(monkeypatch, make_record())
    use_s3(monkeypatch, fake)
    rows = [history_item("2026-10-27", "3951"), history_item("2026-10-26", "3931")]
    monkeypatch.setattr(api, "_table", lambda: table_with(*rows))
    caplog.set_level(logging.WARNING)
    status, body = decode(api.handler(event("/forecasts/gold", "gold", {"history": "60"}), None))
    assert status == 200
    assert body["price_history"] == [
        {"base_date": "2026-10-26", "last_price": 3931},
        {"base_date": "2026-10-27", "last_price": 3951},
    ]
    assert "PRICE_HISTORY_FILE_UNAVAILABLE asset=gold" in caplog.text
    # Lỗi không được cache: request sau đọc lại
    api._price_history(table_with(*rows), "gold", 60)
    assert len(fake.calls) == 2


def test_history_archive_drops_invalid_points(monkeypatch):
    doc = archive_document("gold")
    doc["points"] = [
        {"base_date": "2026-10-19", "last_price": 0},
        {"base_date": "2026-10-20", "last_price": -5},
        {"base_date": "2026-10-21", "last_price": "3900"},
        {"base_date": "2026-10-22", "last_price": True},
        {"base_date": "2026-02-30", "last_price": 3900},
        {"base_date": "2026-10-23"},
        "bad",
        {"base_date": "2026-10-26", "last_price": 3930.5},
    ]
    body = json.dumps(doc)[:-1] + ', "x": NaN}'  # NaN / Infinity hợp lệ với json.loads
    body = body.replace('"last_price": 0}', '"last_price": Infinity}')
    fake = FakeS3({"serving/price-history/gold.json": body.encode()})
    use_s3(monkeypatch, fake)
    points = api._price_history(table_with(), "gold", 10)
    assert points == [{"base_date": "2026-10-26", "last_price": 3930.5}]


def test_history_without_bucket_env_keeps_old_behavior(monkeypatch):
    monkeypatch.setattr(api, "_s3_client", lambda: pytest.fail("S3 must not be used"))
    points = api._price_history(table_with(history_item("2026-11-19", "101")), "gold", 520)
    assert points == [{"base_date": "2026-11-19", "last_price": 101}]


def test_detail_without_history_never_reads_s3(monkeypatch):
    setup_fake_table(monkeypatch, make_record())
    fake = FakeS3(error=AssertionError("S3 must not be read"))
    use_s3(monkeypatch, fake)
    status, body = decode(api.handler(event("/forecasts/gold", "gold"), None))
    assert status == 200 and "price_history" not in body
    assert fake.calls == []


def test_archive_units_match_forecast_record():
    from src.forecast.forecast_record import PRICE_UNIT

    assert api.PRICE_HISTORY_UNITS == PRICE_UNIT


def test_history_reads_archive_with_real_boto3_client(monkeypatch):
    """Đọc qua boto3 thật (moto), đúng bucket/key mặc định; 520 điểm ghép từ file + Forecasts."""
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_REGION": "ap-southeast-1",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PRICE_HISTORY_BUCKET", BUCKET)
    days = [f"2024-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]  # 336 ngày
    days += [f"2025-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]  # +336
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-southeast-1")
        s3.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"}
        )
        doc = archive_document("brent", [(d, 70 + i / 100) for i, d in enumerate(days)])
        s3.put_object(
            Bucket=BUCKET,
            Key="serving/price-history/brent.json",
            Body=json.dumps(doc).encode(),
            ContentType="application/json",
        )
        points = api._price_history(table_with(history_item("2026-11-20", "63.4")), "brent", 520)
    assert len(points) == 520
    assert points[-1] == {"base_date": "2026-11-20", "last_price": 63.4}
    assert points[0]["base_date"] == days[-519]
    assert [p["base_date"] for p in points] == sorted(p["base_date"] for p in points)

"""Test tool get_forecast của chatbot (src/chatbot/tools.py), không gọi AWS.

Dùng fixture benchmark v1 (`tests/chatbot/fixtures/forecasts/`, dạng GET /forecasts/{asset}) và
bản ghi bảng `Forecasts` tạo bằng `to_forecast_record()` đặt trong bảng DynamoDB giả. Không dùng
fixture của bộ v2 để bộ đó vẫn là phép thử độc lập.
"""

from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from src.chatbot import tools as T
from src.forecast import forecast_record, returns

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "chatbot" / "fixtures" / "forecasts"
DROPPED_LEVELS = ("q05", "q25", "q75", "q95")
PRICE_KEYS = {"last_price", "price_unit", "q10_price", "q50_price", "q90_price", "prices"}


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def repo(**files: str) -> T.JsonFileForecastRepository:
    """Repository đọc fixture: repo(gold="gold__baseline.json") hoặc mặc định <asset>.json."""
    mapping = {a: FIXTURES / f"{a}.json" for a in T.ASSETS}
    mapping.update({a: FIXTURES / f for a, f in files.items()})
    return T.JsonFileForecastRepository(mapping)


class DictRepo:
    """Repository giả trả bản ghi có sẵn và đếm số lần đọc."""

    def __init__(self, records: dict | None = None):
        self.records = records or {}
        self.calls: list[str] = []

    def latest(self, asset):
        self.calls.append(asset)
        return self.records.get(asset)


class FakeTable:
    """Bảng DynamoDB giả: lưu tham số query, trả bản ghi mới nhất theo base_date."""

    def __init__(self, items: list[dict]):
        self.items = items
        self.queries: list[dict] = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        asset = kwargs["ExpressionAttributeValues"][":asset"]
        rows = sorted(
            (i for i in self.items if i["asset"] == asset),
            key=lambda i: i["base_date"],
            reverse=not kwargs.get("ScanIndexForward", True),
        )
        return {"Items": rows[: kwargs.get("Limit", len(rows))]}


def table_record(fixture: dict, *, base_date: str | None = None) -> dict:
    """Bản ghi bảng Forecasts (Decimal, `q`, `fx_usd_vnd`) dựng từ fixture bằng code của predict."""
    q = np.array([h["returns"] for h in fixture["horizons"]], dtype=float)
    return forecast_record.to_forecast_record(
        fixture["asset"],
        base_date or fixture["base_date"],
        fixture["last_price"],
        q,
        fx_usd_vnd=fixture["fx"]["usd_vnd"],
        fx_date=fixture["fx"]["date"],
        stale_sources=fixture["stale_sources"],
        roll_in_horizon=fixture["roll_in_horizon"],
        model_version=fixture["model_version"],
        is_sample=fixture["is_sample"],
        created_at=datetime(2026, 10, 15, 12, 40, 5, tzinfo=UTC),
    )


def all_keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in all_keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in all_keys(v)}
    return set()


def all_numbers(obj) -> list[float]:
    if isinstance(obj, bool):
        return []
    if isinstance(obj, int | float):
        return [float(obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in all_numbers(v)]
    if isinstance(obj, list):
        return [n for v in obj for n in all_numbers(v)]
    return []


# ---------- tool spec ----------


def test_tool_spec_matches_bedrock_shape():
    spec = T.GET_FORECAST_TOOL_SPEC["toolSpec"]
    assert spec["name"] == "get_forecast"
    schema = spec["inputSchema"]["json"]
    assert schema["required"] == ["asset"]
    assert schema["properties"]["asset"]["enum"] == ["gold", "silver", "brent", "wti"]
    horizon = schema["properties"]["horizon"]
    assert (horizon["type"], horizon["minimum"], horizon["maximum"]) == ("integer", 1, 7)
    # mô tả không còn chỉ dẫn đếm vị trí phần tử trong mảng phân vị (lỗi của v1)
    assert "phần tử" not in spec["description"]
    json.dumps(T.GET_FORECAST_TOOL_SPEC)


def test_constants_match_forecast_package():
    assert T.QUANTILE_LEVELS == returns.QUANTILE_LEVELS
    assert T.HORIZONS == forecast_record.HORIZONS
    assert T.TARGET_SERIES == forecast_record.TARGET_SERIES
    assert T.METALS == {a for a, u in forecast_record.PRICE_UNIT.items() if u == "USD/oz"}
    assert {T.QUANTILE_LEVELS[i] for i in T.INTERVAL_INDEX.values()} == {0.10, 0.50, 0.90}
    assert T.DISCLAIMER == load("gold.json")["disclaimer"]


def test_module_imports_without_numpy_or_boto3():
    """Lambda api đóng gói zip: tool không được kéo numpy, pandas hay boto3 lúc import."""
    code = (
        "import sys, src.chatbot.tools; "
        "print(sorted(m for m in ('numpy', 'pandas', 'boto3') if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


# ---------- đủ 4 tài sản ----------


@pytest.mark.parametrize("asset", T.ASSETS)
def test_all_assets_return_named_80pct_interval(asset):
    fixture = load(f"{asset}.json")
    res = T.get_forecast({"asset": asset}, repo())

    assert "error" not in res
    assert res["asset"] == asset
    assert res["target_series"] == T.TARGET_SERIES[asset]
    assert res["base_date"] == fixture["base_date"]
    assert res["model_version"] == "sample"
    assert res["disclaimer"] == "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
    assert [h["h"] for h in res["horizons"]] == list(range(1, 8))
    for got, src in zip(res["horizons"], fixture["horizons"], strict=True):
        r = src["returns"]
        assert got["target_date"] == src["target_date"]
        assert got["q10_pct"] == round(r[1] * 100, 2)
        assert got["q50_pct"] == round(r[3] * 100, 2)
        assert got["q90_pct"] == round(r[5] * 100, 2)
        assert got["prob_up_pct"] == round(src["prob_up"] * 100)
        assert isinstance(got["prob_up_pct"], int)
        assert got["q10_pct"] <= got["q50_pct"] <= got["q90_pct"]
    # chỉ q10/q50/q90: không có q05, q25, q75, q95 hay mảng 7 phân vị
    keys = all_keys(res)
    assert not {k for k in keys if k.startswith(DROPPED_LEVELS)}
    assert not {"returns", "q", "quantile_levels"} & keys
    json.dumps(res, ensure_ascii=False)


def test_gold_h1_values_from_fixture():
    # gold.json h=1: returns[1,3,5] = -0.0116, 0.0006, 0.0128; prob_up 0.52
    h1 = T.get_forecast({"asset": "gold", "horizon": 1}, repo())["horizons"][0]
    assert h1 == {
        "h": 1,
        "target_date": "2026-10-15",
        "q10_pct": -1.16,
        "q50_pct": 0.06,
        "q90_pct": 1.28,
        "prob_up_pct": 52,
    }


@pytest.mark.parametrize("asset", ["gold", "silver"])
def test_metals_have_no_price_fields(asset):
    fixture = load(f"{asset}.json")
    res = T.get_forecast({"asset": asset}, repo())

    assert not PRICE_KEYS & all_keys(res)
    proxy = T.TARGET_SERIES[asset]
    assert proxy in res["proxy_note"] and "chuỗi đại diện" in res["proxy_note"]
    # không có con số nào trong kết quả trùng giá USD/oz của fixture
    prices = {fixture["last_price"]} | {p for h in fixture["horizons"] for p in h["prices"]}
    assert not prices & set(all_numbers(res))


@pytest.mark.parametrize("asset", ["brent", "wti"])
def test_oil_has_usd_bbl_prices_for_q10_q50_q90(asset):
    fixture = load(f"{asset}.json")
    res = T.get_forecast({"asset": asset}, repo())

    assert res["last_price"] == fixture["last_price"]
    assert res["price_unit"] == "USD/bbl"
    assert "proxy_note" not in res
    for got, src in zip(res["horizons"], fixture["horizons"], strict=True):
        for name, i in T.INTERVAL_INDEX.items():
            expected = round(fixture["last_price"] * math.exp(src["returns"][i]), 2)
            assert got[f"{name}_price"] == pytest.approx(expected, abs=1e-9)
            # cùng công thức với API, chỉ lệch do làm tròn return trong fixture
            assert got[f"{name}_price"] == pytest.approx(src["prices"][i], abs=0.011)
        assert set(got) == {
            "h",
            "target_date",
            "q10_pct",
            "q50_pct",
            "q90_pct",
            "prob_up_pct",
            "q10_price",
            "q50_price",
            "q90_price",
        }


# ---------- horizon ----------


@pytest.mark.parametrize("h", [1, 4, 7])
def test_valid_horizon_returns_single_entry(h):
    res = T.get_forecast({"asset": "wti", "horizon": h}, repo())
    assert [x["h"] for x in res["horizons"]] == [h]
    full = T.get_forecast({"asset": "wti"}, repo())
    assert res["horizons"][0] == full["horizons"][h - 1]


@pytest.mark.parametrize("h", [0, 8, -1, "3", 2.5, True, [1]])
def test_invalid_horizon_is_rejected_before_reading(h):
    spy = DictRepo({"wti": load("wti.json")})
    res = T.get_forecast({"asset": "wti", "horizon": h}, spy)
    assert res["error"] == "invalid_horizon"
    assert set(res) == {"error", "message"}
    assert spy.calls == []


def test_build_rejects_invalid_horizon():
    with pytest.raises(ValueError, match="horizon"):
        T.build_forecast_result(load("wti.json"), horizon=9)


# ---------- tài sản không hợp lệ, chưa có bản ghi ----------


@pytest.mark.parametrize("asset", ["copper", "GOLD", "", None, 1])
def test_unknown_asset_is_rejected_before_reading(asset):
    spy = DictRepo()
    res = T.get_forecast({"asset": asset}, spy)
    assert res["error"] == "invalid_asset"
    assert spy.calls == []


def test_missing_asset_argument():
    assert T.get_forecast({}, DictRepo())["error"] == "invalid_asset"


def test_not_found_fixture_returns_contract_error():
    res = T.get_forecast({"asset": "silver"}, repo(silver="silver__not_found.json"))
    assert res == {"error": "not_found", "message": "Chưa có bản ghi dự báo cho tài sản silver."}
    assert not all_numbers(res)


def test_not_found_when_table_has_no_record():
    table = FakeTable([table_record(load("gold.json"))])
    res = T.get_forecast({"asset": "brent"}, T.DynamoForecastRepository(table))
    assert res["error"] == "not_found"


# ---------- tình trạng dữ liệu ----------


def test_stale_flag_follows_stale_sources():
    stale = T.get_forecast({"asset": "brent"}, repo(brent="brent__stale.json"))
    assert stale["stale"] is True
    assert stale["stale_sources"] == ["brent"]

    fresh = T.get_forecast({"asset": "brent"}, repo())
    assert fresh["stale"] is False
    assert fresh["stale_sources"] == []


def test_is_sample_and_baseline_model_version():
    sample = T.get_forecast({"asset": "gold"}, repo())
    assert sample["is_sample"] is True

    baseline = T.get_forecast({"asset": "gold"}, repo(gold="gold__baseline.json"))
    assert baseline["is_sample"] is False
    assert baseline["model_version"] == "baseline-q252"


def test_roll_in_horizon_and_fx_are_passed_through():
    res = T.get_forecast({"asset": "wti"}, repo(wti="wti__roll.json"))
    assert res["roll_in_horizon"] is True
    assert res["fx"] == {"usd_vnd": 26310, "date": "2026-10-14"}


# ---------- phân vị giảm ----------


def _swap_quantiles(record: dict, h: int, key: str) -> dict:
    bad = copy.deepcopy(record)
    q = bad["horizons"][h - 1][key]
    q[2], q[4] = q[4], q[2]  # q25 > q75
    return bad


def test_decreasing_quantiles_raise_and_are_not_sorted():
    bad = _swap_quantiles(load("gold.json"), 3, "returns")
    with pytest.raises(T.InvalidForecastRecord, match="decreasing"):
        T.build_forecast_result(bad)
    # chỉ hỏi h = 1 vẫn báo lỗi: cả bản ghi bị kiểm tra
    with pytest.raises(T.InvalidForecastRecord, match="h=3"):
        T.build_forecast_result(bad, horizon=1)
    assert issubclass(T.InvalidForecastRecord, ValueError)


def test_decreasing_quantiles_give_internal_error_without_numbers(caplog):
    bad = _swap_quantiles(table_record(load("brent.json")), 5, "q")
    res = T.get_forecast({"asset": "brent"}, DictRepo({"brent": bad}))
    assert res["error"] == "internal_error"
    assert not all_numbers(res)
    assert "decreasing" in caplog.text


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda r: r.update(asset="silver"), "requested"),
        (lambda r: r.update(quantile_levels=[0.1, 0.5, 0.9]), "quantile_levels"),
        (lambda r: r["horizons"].pop(), "h = 1–7"),
        (lambda r: r["horizons"][0].update(prob_up=0.99), "prob_up"),
        (lambda r: r["horizons"][0]["returns"].__setitem__(0, float("nan")), "non-finite"),
        (lambda r: r.update(last_price=0), "last_price"),
        (lambda r: r.update(price_unit="USD/oz"), "price_unit"),
        (lambda r: r.pop("is_sample"), "is_sample"),
        (lambda r: r.update(stale_sources="brent"), "stale_sources"),
    ],
)
def test_record_contract_violations_raise(mutate, match):
    bad = copy.deepcopy(load("brent.json"))
    mutate(bad)
    with pytest.raises(T.InvalidForecastRecord, match=match):
        T.build_forecast_result(bad, asset="brent")


# ---------- đọc bảng DynamoDB (giả) ----------


def test_dynamo_repository_reads_latest_record_and_matches_fixture_path():
    fixture = load("wti.json")
    older = table_record(fixture, base_date="2026-10-13")
    older["model_version"] = "old"
    table = FakeTable([older, table_record(fixture)])

    res = T.get_forecast({"asset": "wti"}, T.DynamoForecastRepository(table))

    assert table.queries == [
        {
            "KeyConditionExpression": "#asset = :asset",
            "ExpressionAttributeNames": {"#asset": "asset"},
            "ExpressionAttributeValues": {":asset": "wti"},
            "ScanIndexForward": False,
            "Limit": 1,
        }
    ]
    assert res["base_date"] == "2026-10-14"
    assert res["model_version"] == "sample"
    from_json = T.get_forecast({"asset": "wti"}, repo())
    for a, b in zip(res["horizons"], from_json["horizons"], strict=True):
        for k in ("h", "target_date", "q10_pct", "q50_pct", "q90_pct", "q10_price", "q90_price"):
            assert a[k] == b[k]
    # kết quả không còn Decimal, gửi thẳng được cho Bedrock
    assert not any(isinstance(n, Decimal) for n in all_numbers(res))
    json.dumps(res)


def test_negative_zero_is_not_returned():
    rec = copy.deepcopy(load("gold.json"))
    rec["horizons"][0]["returns"][3] = -0.000001  # q50 làm tròn về 0
    h1 = T.build_forecast_result(rec, horizon=1)["horizons"][0]
    assert h1["q50_pct"] == 0.0
    assert json.dumps(h1["q50_pct"]) == "0.0"


def test_json_repository_from_dir(tmp_path):
    (tmp_path / "gold.json").write_text(json.dumps(load("gold.json")), encoding="utf-8")
    r = T.JsonFileForecastRepository.from_dir(tmp_path)
    assert r.latest("gold")["asset"] == "gold"
    assert r.latest("silver") is None


# ---------- dùng chung hàm định dạng với Lambda API (Khải 26/10) ----------


def test_dynamo_path_uses_lambda_api_formatter(monkeypatch):
    """Đọc DynamoDB đi qua đúng latest_record + detail_item của infra/lambda/forecast_api."""
    record = table_record(load("brent.json"))
    calls = []
    real = T.FF.detail_item
    monkeypatch.setattr(T.FF, "detail_item", lambda r: calls.append(r) or real(r))
    res = T.get_forecast({"asset": "brent"}, T.DynamoForecastRepository(FakeTable([record])))
    assert calls == [record]
    assert res == T.build_forecast_result(real(record))


def test_shared_constants_come_from_lambda_api_module():
    assert T.DISCLAIMER == T.FF.DISCLAIMER
    assert T.ASSETS == tuple(T.FF.ASSETS)
    assert T.QUANTILE_LEVELS == tuple(T.FF.QUANTILE_LEVELS)

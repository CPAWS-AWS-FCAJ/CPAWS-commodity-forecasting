"""Lambda predict (src/forecast/predict.py, lambda_predict.py): snapshot clean → bản ghi Forecasts.

S3 và DynamoDB dùng moto (không gọi AWS thật); giá tổng hợp 2019 (không đụng dữ liệu 2020 → nay).
Phần lớn test dùng mô hình giả; test tích hợp cuối file huấn luyện DLinear thật 1 epoch trên giá
tổng hợp 2013–2018 rồi nạp bằng DLinearNumpy.load.
"""

import json
import logging
import subprocess
import sys
import textwrap
import time
import zlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
import pytest
from moto import mock_aws

from src.data import calendars, clean, ingest_prices, storage
from src.data.config import ASSETS
from src.forecast import lambda_predict, predict
from src.forecast.baselines import Quantile252Model, quantile_baseline
from src.forecast.forecast_record import target_dates, to_decimal
from src.forecast.returns import QUANTILE_LEVELS, horizon_log_returns

ROOT = Path(__file__).resolve().parents[1]
REGION = "ap-southeast-1"
BUCKET = "cpaws-test-lake"
TABLE = "cpaws-test-forecasts"
MV = "dlinear-test-2019"
START, END, DT = "2019-01-02", "2019-06-28", "2019-06-29"  # dt = thứ Bảy sau phiên cuối
BASE = "2019-06-28"
NOW = datetime(2019, 6, 29, 12, 30, tzinfo=UTC)
BASE_PRICE = {"gold": 120.0, "silver": 14.0, "brent": 65.0, "wti": 58.0, "usd_vnd": 23_200.0}
FACTOR = {"gold": 10.5, "silver": 1.08}
ITEM_KEYS = {
    "asset",
    "base_date",
    "created_at",
    "model_version",
    "target_series",
    "last_price",
    "price_unit",
    "quantile_levels",
    "horizons",
    "fx_usd_vnd",
    "fx_date",
    "stale_sources",
    "roll_in_horizon",
    "is_sample",
    "input_snapshot_dt",
}


# ---------- dữ liệu và mô hình giả ----------


def _prices(start: str = START, end: str = END) -> pd.DataFrame:
    """Bảng clean dạng dài cho 4 tài sản + usd_vnd, mỗi tài sản trên lịch của nó."""
    frames = []
    for asset, p0 in BASE_PRICE.items():
        d = calendars.sessions(ASSETS[asset].calendar, start, end)
        rng = np.random.default_rng(zlib.crc32(asset.encode()))
        vol = 0.001 if asset == "usd_vnd" else 0.01
        frames.append(
            pd.DataFrame(
                {
                    "date": d,
                    "asset": asset,
                    "price": p0 * np.exp(np.cumsum(rng.normal(0, vol, len(d)))),
                    "unit": ASSETS[asset].unit,
                    "source": "yfinance",
                    "published_at": clean.published_at(d, "yfinance"),
                    "ingested_at": pd.Timestamp("2019-07-01", tz="UTC"),
                    "flag": "",
                }
            )
        )
    return clean.normalize_types(pd.concat(frames, ignore_index=True))


def _factors(prices: pd.DataFrame) -> pd.DataFrame:
    """Hệ số hiển thị theo ngày của GLD/SLV; mỗi ngày một giá trị khác để biết đã dùng ngày nào."""
    rows = []
    for asset, f0 in FACTOR.items():
        d = prices.loc[prices["asset"] == asset, "date"].sort_values().to_numpy()
        rows.append(
            pd.DataFrame(
                {
                    "date": d,
                    "asset": asset,
                    "factor": f0 + 1e-4 * np.arange(len(d)),
                    "reference": "gc_fut" if asset == "gold" else "si_fut",
                    "reliability": "normal" if asset == "gold" else "low",
                    "unit": "USD/oz per share",
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def _write_lake(st, prices, *, rejected=None, factors="auto", report=None, dt=DT):
    base = f"clean/prices/dt={dt}"
    storage.write_parquet(st, f"{base}/prices.parquet", prices)
    rej = clean.empty_frame() if rejected is None else clean.normalize_types(rejected)
    storage.write_parquet(st, f"{base}/rejected.parquet", rej)
    if isinstance(factors, str):
        factors = _factors(prices)
    if factors is not None:
        storage.write_parquet(st, f"clean/display_factors/dt={dt}/display_factors.parquet", factors)
    storage.write_json(st, f"{base}/quality.json", report or {"status": "ok", "stale_sources": {}})


def _px(prices, asset, day) -> float:
    m = (prices["asset"] == asset) & (prices["date"] == pd.Timestamp(day))
    return float(prices.loc[m, "price"].iloc[0])


class FakeModel:
    """[B, 60, 1] → [B, 7, 7]: q = mean·h + sd·√h·z_τ, phụ thuộc cửa sổ (test rò rỉ có ý nghĩa).
    cross_rows: các hàng h bị đảo thứ tự phân vị (mô phỏng phân vị cắt nhau)."""

    Z = np.array([-1.645, -1.2816, -0.6745, 0.0, 0.6745, 1.2816, 1.645])

    def __init__(self, cross_rows=()):
        self.cross_rows = tuple(cross_rows)
        self.calls: list[np.ndarray] = []

    def predict(self, windows):
        x = np.asarray(windows, dtype=float)
        assert x.ndim == 3 and x.shape[1:] == (60, 1) and np.isfinite(x).all()
        self.calls.append(x.copy())
        mu, sd = x.mean(axis=(1, 2)), x.std(axis=(1, 2)) + 1e-4
        h = np.arange(1, 8, dtype=float)
        q = mu[:, None, None] * h[None, :, None] + (
            sd[:, None, None] * np.sqrt(h)[None, :, None] * self.Z[None, None, :]
        )
        for r in self.cross_rows:
            q[:, r, :] = q[:, r, ::-1]
        return q.astype(np.float32)


def _loader(model=None):
    model = model or FakeModel()
    return lambda asset: predict.LoadedModel(model, 60, {"asset": asset, "model_version": MV})


def _run(st, sink=None, model=None, now=NOW, **kw) -> predict.PredictRun:
    return predict.run_predict(st, sink, load_model=_loader(model), model_version=MV, now=now, **kw)


def _by_asset(run: predict.PredictRun) -> dict[str, predict.AssetResult]:
    return {r.asset: r for r in run.results}


def _local(tmp_path, name="lake"):
    return storage.LocalStorage(tmp_path / name)


def _assert_contract(
    item: dict, asset: str, base: str = BASE, mv: str = MV, snapshot_dt: str = DT
) -> None:
    assert set(item) == ITEM_KEYS
    assert item["asset"] == asset and item["base_date"] == base
    assert item["input_snapshot_dt"] == snapshot_dt
    assert item["model_version"] == mv and item["is_sample"] is False
    assert item["target_series"] == ASSETS[asset].primary.symbol
    assert item["price_unit"] == ("USD/oz" if asset in ("gold", "silver") else "USD/bbl")
    assert [float(x) for x in item["quantile_levels"]] == list(QUANTILE_LEVELS)
    assert item["stale_sources"] == []
    assert isinstance(item["roll_in_horizon"], bool)
    assert item["roll_in_horizon"] == predict.roll_in_horizon(asset, base)
    assert isinstance(item["last_price"], Decimal) and item["last_price"] > 0
    assert isinstance(item["fx_usd_vnd"], Decimal) and item["fx_usd_vnd"] > 0
    dates = target_dates(asset, base)
    assert [h["h"] for h in item["horizons"]] == list(range(1, 8))
    for h in item["horizons"]:
        assert h["target_date"] == dates[int(h["h"]) - 1]
        assert len(h["q"]) == 7 and all(isinstance(v, Decimal) for v in h["q"])
        assert all(a <= b for a, b in zip(h["q"], h["q"][1:], strict=False))
        assert isinstance(h["prob_up"], Decimal) and Decimal("0.05") <= h["prob_up"] <= 0.95


def _forecast(record: dict) -> dict:
    """Bản ghi bỏ input_snapshot_dt (nguồn gốc, khác nhau giữa các snapshot) để so nội dung dự báo."""
    return {k: v for k, v in record.items() if k != "input_snapshot_dt"}


def _no_floats(obj) -> bool:
    if isinstance(obj, float):
        return False
    if isinstance(obj, dict):
        return all(_no_floats(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_no_floats(v) for v in obj)
    return True


# ---------- AWS giả ----------


@pytest.fixture
def aws(monkeypatch):
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
        "LAKE_BUCKET": BUCKET,
        "FORECASTS_TABLE": TABLE,
        "MODEL_VERSION": MV,
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("LAKE_PREFIX", "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        table = boto3.resource("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "asset", "KeyType": "HASH"},
                {"AttributeName": "base_date", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "asset", "AttributeType": "S"},
                {"AttributeName": "base_date", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield s3, table


def _items(table, asset) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    return table.query(KeyConditionExpression=Key("asset").eq(asset))["Items"]


def _fake_loader(monkeypatch, model=None):
    monkeypatch.setattr(predict, "make_model_loader", lambda mv, **k: _loader(model))


# ---------- đầu-cuối ----------


def test_handler_end_to_end_writes_contract_items(aws, monkeypatch):
    s3, table = aws
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices())
    _fake_loader(monkeypatch)
    out = lambda_predict.handler({}, None)
    assert out["ok"] and out["written"] == 4 and not out["dry_run"]
    json.dumps(out)  # tóm tắt trả về Lambda phải JSON được
    for asset in predict.PREDICT_ASSETS:
        items = _items(table, asset)
        assert len(items) == 1
        _assert_contract(items[0], asset)
        assert items[0]["created_at"].endswith("Z")
    assert _items(table, "gold")[0]["roll_in_horizon"] is False


def test_record_numbers_are_decimal_before_put(tmp_path):
    st = _local(tmp_path)
    _write_lake(st, _prices())
    run = _run(st, sink=None)
    assert run.ok and run.dry_run
    for r in run.results:
        _assert_contract(r.record, r.asset)
        assert _no_floats(r.record)


def test_dry_run_writes_nothing(aws, monkeypatch):
    s3, table = aws
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices())
    _fake_loader(monkeypatch)
    out = lambda_predict.handler({"dry_run": True, "assets": ["gold", "wti"]}, None)
    assert out["dry_run"] and out["ok"] and out["written"] == 0
    assert set(out["assets"]) == {"gold", "wti"}
    assert all(0.05 <= p <= 0.95 for p in out["assets"]["gold"]["prob_up"])
    assert table.scan()["Count"] == 0


def test_local_json_sink_writes_floats(tmp_path):
    st = _local(tmp_path)
    _write_lake(st, _prices())
    run = _run(st, predict.LocalJsonSink(tmp_path / "out"), assets=["wti"])
    assert run.ok
    rec = json.loads((tmp_path / "out" / "wti.json").read_text(encoding="utf-8"))
    assert rec["base_date"] == BASE and isinstance(rec["last_price"], float)
    assert rec["is_sample"] is False and len(rec["horizons"]) == 7


# ---------- không ghi đè dự báo đã phát hành ----------


def test_first_write_counts_written_not_already_published(aws, monkeypatch):
    s3, table = aws
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices())
    _fake_loader(monkeypatch)
    out = lambda_predict.handler({}, None)
    assert out["ok"] and out["written"] == 4 and out["already_published"] == 0
    assert not any("already_published" in a for a in out["assets"].values())
    assert table.scan()["Count"] == 4


def test_second_run_same_key_keeps_published_record(aws, monkeypatch, caplog):
    s3, table = aws
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices())
    _fake_loader(monkeypatch)
    lambda_predict.handler({}, None)
    first = {a: _items(table, a) for a in predict.PREDICT_ASSETS}
    caplog.set_level(logging.INFO, logger="cpaws.predict")

    out = lambda_predict.handler({}, None)  # không raise PredictFailed

    assert out["ok"] and out["written"] == 0 and out["already_published"] == 4
    for asset in predict.PREDICT_ASSETS:
        a = out["assets"][asset]
        assert a["status"] == "ok" and a["already_published"] is True and "written_to" not in a
        assert _items(table, asset) == first[asset]  # bản đã phát hành giữ nguyên
        assert f"PREDICT_ALREADY_PUBLISHED asset={asset} base_date={BASE}" in caplog.text
    assert all(
        r.levelno == logging.WARNING
        for r in caplog.records
        if r.getMessage().startswith("PREDICT_ALREADY_PUBLISHED")
    )


def test_sample_record_is_replaced(aws, monkeypatch):
    s3, table = aws
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices())
    sample = {"asset": "gold", "base_date": BASE, "model_version": "sample", "is_sample": True}
    table.put_item(Item=sample)
    _fake_loader(monkeypatch)
    out = lambda_predict.handler({"assets": ["gold"]}, None)
    assert out["ok"] and out["written"] == 1 and out["already_published"] == 0
    items = _items(table, "gold")
    assert len(items) == 1
    _assert_contract(items[0], "gold")


def test_champion_record_has_input_snapshot_dt(aws, monkeypatch, tmp_path):
    s3, table = aws
    snap_dt = "2019-06-30"  # khác DT để chắc giá trị lấy từ snapshot, không phải hằng số
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices(), dt=snap_dt)
    _fake_loader(monkeypatch)
    out = lambda_predict.handler({}, None)
    assert out["ok"] and out["written"] == 4 and out["already_published"] == 0
    for asset in predict.PREDICT_ASSETS:
        items = _items(table, asset)
        assert len(items) == 1
        _assert_contract(items[0], asset, snapshot_dt=snap_dt)

    # Lần chạy thứ hai trên snapshot mới hơn: conditional write giữ bản đã phát hành
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices(), dt="2019-07-01")
    out = lambda_predict.handler({}, None)
    assert out["written"] == 0 and out["already_published"] == 4
    assert all(_items(table, a)[0]["input_snapshot_dt"] == snap_dt for a in predict.PREDICT_ASSETS)

    st = _local(tmp_path)
    _write_lake(st, _prices(), dt=snap_dt)
    assert _run(st, predict.LocalJsonSink(tmp_path / "out"), assets=["wti"]).ok
    rec = json.loads((tmp_path / "out" / "wti.json").read_text(encoding="utf-8"))
    assert rec["input_snapshot_dt"] == snap_dt


class _FailingTable:
    def __init__(self, code: str):
        self.code = code
        self.calls: list[dict] = []

    def put_item(self, **kw):
        from botocore.exceptions import ClientError

        self.calls.append(kw)
        raise ClientError({"Error": {"Code": self.code, "Message": "x"}}, "PutItem")


class _FakeResource:
    def __init__(self, table):
        self.table = table

    def Table(self, name):  # tên theo boto3
        return self.table


def test_put_uses_condition_on_asset_and_is_sample():
    table = _FailingTable("ConditionalCheckFailedException")
    sink = predict.DynamoSink(TABLE, resource=_FakeResource(table))
    assert sink.put({"asset": "gold", "base_date": BASE}) is None
    kw = table.calls[0]
    assert kw["ConditionExpression"] == "attribute_not_exists(#a) OR #s = :t"
    assert kw["ExpressionAttributeNames"] == {"#a": "asset", "#s": "is_sample"}
    assert kw["ExpressionAttributeValues"] == {":t": True}


def test_other_client_error_still_fails(tmp_path, caplog):
    from botocore.exceptions import ClientError

    table = _FailingTable("ProvisionedThroughputExceededException")
    sink = predict.DynamoSink(TABLE, resource=_FakeResource(table))
    with pytest.raises(ClientError):
        sink.put({"asset": "gold", "base_date": BASE})

    st = _local(tmp_path)
    _write_lake(st, _prices())
    caplog.set_level(logging.INFO, logger="cpaws.predict")
    run = _run(st, sink, assets=["gold", "wti"])
    assert not run.ok
    for r in run.results:
        assert r.status == predict.STATUS_ERROR and r.reason == predict.REASON_EXCEPTION
        assert not r.already_published and "ProvisionedThroughputExceeded" in r.detail
    assert run.summary()["already_published"] == 0
    assert "PREDICT_ALREADY_PUBLISHED" not in caplog.text


def test_handler_raises_on_other_client_error(aws, monkeypatch):
    s3, _ = aws
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices())
    _fake_loader(monkeypatch)
    table = _FailingTable("ValidationException")
    real = predict.DynamoSink
    monkeypatch.setattr(
        predict, "DynamoSink", lambda name: real(name, resource=_FakeResource(table))
    )
    with pytest.raises(lambda_predict.PredictFailed):
        lambda_predict.handler({"assets": ["gold"]}, None)


# ---------- cửa sổ không hợp lệ, thiếu phiên cuối ----------


@pytest.mark.parametrize(
    "asset,case",
    [("silver", "rejected"), ("wti", "missing")],
)
def test_invalid_last_window_skips_asset_and_handler_raises(aws, monkeypatch, caplog, asset, case):
    s3, table = aws
    prices = _prices()
    rejected = None
    if case == "rejected":
        # Dòng vẫn còn trong prices: chắc rằng predict truyền ngày bị loại vào build_feature_frame
        m = (prices["asset"] == asset) & (prices["date"] == pd.Timestamp("2019-06-12"))
        rejected = prices.loc[m].assign(flag="bad_value")
    else:
        m = (prices["asset"] == asset) & (prices["date"] == pd.Timestamp("2019-06-05"))
        prices = prices.loc[~m].reset_index(drop=True)
    _write_lake(storage.S3Storage(BUCKET, client=s3), prices, rejected=rejected)
    old = {"asset": asset, "base_date": "2019-06-27", "model_version": "old"}
    table.put_item(Item=old)
    _fake_loader(monkeypatch)
    caplog.set_level(logging.INFO, logger="cpaws.predict")

    with pytest.raises(lambda_predict.PredictFailed, match=asset):
        lambda_predict.handler({}, None)

    assert _items(table, asset) == [old]  # không ghi bản ghi mới, bản ghi cũ giữ nguyên
    for other in set(predict.PREDICT_ASSETS) - {asset}:
        _assert_contract(_items(table, other)[0], other)
    assert f"PREDICT_SKIPPED asset={asset} base_date={BASE} reason=invalid_input_window" in (
        caplog.text
    )


def test_latest_session_missing_skips_without_falling_back(tmp_path, caplog):
    prices = _prices()
    m = (prices["asset"] == "gold") & (prices["date"] == pd.Timestamp(BASE))
    st = _local(tmp_path)
    _write_lake(st, prices.loc[~m].reset_index(drop=True))
    caplog.set_level(logging.INFO, logger="cpaws.predict")
    run = _run(st, predict.LocalJsonSink(tmp_path / "out"))
    res = _by_asset(run)
    assert res["gold"].status == "skipped" and res["gold"].reason == "latest_session_missing"
    assert res["gold"].base_date == "2019-06-27" and res["gold"].record is None
    assert not (tmp_path / "out" / "gold.json").exists()
    assert all(res[a].status == "ok" for a in ("silver", "brent", "wti"))
    assert not run.ok
    assert "reason=latest_session_missing expected=2019-06-28" in caplog.text


def test_holiday_is_not_a_missing_session(tmp_path):
    # 4/7/2019: NYSE nghỉ, CME không có settlement; snapshot dt = 5/7 → phiên mong đợi là 3/7
    st = _local(tmp_path)
    _write_lake(st, _prices(end="2019-07-03"), dt="2019-07-05")
    snap = predict.load_snapshot(st)
    for asset in predict.PREDICT_ASSETS:
        assert predict.expected_base_date(asset, snap) == pd.Timestamp("2019-07-03")
    run = _run(st, now=datetime(2019, 7, 5, 12, 30, tzinfo=UTC))
    assert run.ok
    assert {r.base_date for r in run.results} == {"2019-07-03"}


def test_no_snapshot_raises(tmp_path):
    with pytest.raises(predict.SnapshotMissing):
        _run(_local(tmp_path))


@pytest.mark.parametrize(
    "now,stale",
    [(NOW, False), (datetime(2019, 7, 1, 12, 30, tzinfo=UTC), True)],
)
def test_snapshot_older_than_today_warns_but_runs(tmp_path, caplog, now, stale):
    st = _local(tmp_path)
    _write_lake(st, _prices())  # dt = 2019-06-29
    caplog.set_level(logging.INFO, logger="cpaws.predict")
    run = predict.run_predict(st, None, load_model=_loader(), model_version=MV, now=now)
    assert run.ok
    msg = f"PREDICT_SNAPSHOT_STALE snapshot_dt={DT} today=2019-07-01"
    assert (msg in caplog.text) == stale
    assert ("PREDICT_SNAPSHOT_STALE" in caplog.text) == stale


# ---------- phân vị cắt nhau ----------


def test_crossing_quantiles_sorted_once_and_logged(tmp_path, monkeypatch, caplog):
    st = _local(tmp_path)
    _write_lake(st, _prices())
    calls = []
    real = predict.normalize_quantiles

    def counting(q):
        calls.append(np.array(q))
        return real(q)

    monkeypatch.setattr(predict, "normalize_quantiles", counting)
    model = FakeModel(cross_rows=(0, 3))
    caplog.set_level(logging.INFO, logger="cpaws.predict")
    res = _by_asset(_run(st, model=model, assets=["gold"]))["gold"]

    assert len(calls) == 1  # đúng một lần, trên đầu ra thô của mô hình
    raw = FakeModel(cross_rows=(0, 3)).predict(model.calls[0])[0].astype(float)
    np.testing.assert_array_equal(calls[0][0], raw)
    assert int(np.any(np.diff(raw, axis=-1) < 0, axis=-1).sum()) == 2
    assert res.status == "ok" and res.n_crossed == 2
    got = np.array([[float(v) for v in h["q"]] for h in res.record["horizons"]])
    np.testing.assert_allclose(got, np.sort(raw, axis=-1), atol=1e-6)
    assert f"PREDICT_QUANTILE_CROSSING asset=gold base_date={BASE} n_crossed=2 n_rows=7" in (
        caplog.text
    )


# ---------- chống rò rỉ ----------


def test_base_date_result_independent_of_later_sessions(tmp_path, caplog):
    d = pd.Timestamp("2019-05-15")
    clean_prices = _prices()
    full = clean_prices.copy()
    later = full["date"] > d
    full.loc[later, "price"] *= np.where(full.loc[later, "asset"] == "usd_vnd", 1.05, 1.3)
    gold_rej = full.loc[(full["asset"] == "gold") & (full["date"] == pd.Timestamp("2019-05-20"))]
    st_full, st_cut = _local(tmp_path, "full"), _local(tmp_path, "cut")
    stale = {"gold": {"last_date": "2019-06-27"}, "usd_vnd": {"last_date": "2019-06-27"}}
    _write_lake(
        st_full,
        full,
        rejected=gold_rej.assign(flag="bad_value"),
        report={"status": "partial", "stale_sources": stale},
    )
    cut = clean_prices.loc[clean_prices["date"] <= d].reset_index(drop=True)
    _write_lake(st_cut, cut, factors=_factors(cut), dt="2019-05-16")

    caplog.set_level(logging.INFO, logger="cpaws.predict")
    m_full, m_cut, m_live = FakeModel(), FakeModel(), FakeModel()
    r_full = _by_asset(_run(st_full, model=m_full, base_date="2019-05-15"))
    r_cut = _by_asset(_run(st_cut, model=m_cut, base_date="2019-05-15"))
    r_live = _by_asset(_run(st_cut, model=m_live))  # chạy thường vào đúng ngày đó
    assert "PREDICT_BACKFILL base_date=2019-05-15" in caplog.text
    for asset in predict.PREDICT_ASSETS:
        assert r_full[asset].status == "ok", r_full[asset]
        assert r_full[asset].record["base_date"] == "2019-05-15"
        assert r_full[asset].record["stale_sources"] == []
        assert _forecast(r_full[asset].record) == _forecast(r_cut[asset].record)
        assert _forecast(r_cut[asset].record) == _forecast(r_live[asset].record)
        assert r_full[asset].record["input_snapshot_dt"] == DT
        assert r_cut[asset].record["input_snapshot_dt"] == "2019-05-16"
        assert r_live[asset].record["input_snapshot_dt"] == "2019-05-16"
    for a, b in zip(m_full.calls, m_cut.calls, strict=True):
        np.testing.assert_array_equal(a, b)


# ---------- last_price, tỷ giá, stale_sources ----------


def test_last_price_uses_display_factor_for_metals_only(tmp_path):
    prices = _prices()
    st = _local(tmp_path)
    _write_lake(st, prices)
    res = _by_asset(_run(st))
    f = _factors(prices)
    for asset in ("gold", "silver"):
        fac = float(
            f.loc[(f["asset"] == asset) & (f["date"] == pd.Timestamp(BASE)), "factor"].iloc[0]
        )
        want = _px(prices, asset, BASE) * fac
        assert res[asset].record["last_price"] == to_decimal(want)
    for asset in ("brent", "wti"):
        assert res[asset].record["last_price"] == to_decimal(_px(prices, asset, BASE))
    fx = prices.loc[prices["asset"] == "usd_vnd"].sort_values("date").iloc[-1]
    assert res["wti"].record["fx_usd_vnd"] == to_decimal(fx["price"])
    assert res["wti"].record["fx_date"] == str(fx["date"].date())


@pytest.mark.parametrize("lag,status", [(0, "ok"), (2, "ok"), (5, "ok"), (6, "skipped")])
def test_display_factor_lag(tmp_path, caplog, lag, status):
    prices = _prices()
    nyse = calendars.sessions("NYSE", START, BASE)
    fdate = nyse[len(nyse) - 1 - lag]
    f = _factors(prices)
    f = f.loc[(f["asset"] != "gold") | (f["date"] <= fdate)].reset_index(drop=True)
    st = _local(tmp_path)
    _write_lake(st, prices, factors=f)
    caplog.set_level(logging.INFO, logger="cpaws.predict")
    res = _by_asset(_run(st))
    assert res["silver"].status == "ok"
    assert res["gold"].status == status
    if status == "skipped":
        assert res["gold"].reason == "display_factor_stale"
        return
    fac = float(f.loc[(f["asset"] == "gold") & (f["date"] == fdate), "factor"].iloc[0])
    assert res["gold"].record["last_price"] == to_decimal(_px(prices, "gold", BASE) * fac)
    warned = "PREDICT_DISPLAY_FACTOR_LAG asset=gold" in caplog.text
    assert warned == (lag > 0)


def test_missing_display_factors_skip_metals_only(tmp_path):
    st = _local(tmp_path)
    _write_lake(st, _prices(), factors=None)
    res = _by_asset(_run(st))
    assert {a: r.reason for a, r in res.items() if r.status != "ok"} == {
        "gold": "display_factor_missing",
        "silver": "display_factor_missing",
    }


def test_stale_sources_from_quality_json(tmp_path):
    assert predict.stale_sources_for({"stale_sources": {}}, "gold") == []
    report = {"stale_sources": {"usd_vnd": {}, "brent": {}, "gold": {}}}
    assert predict.stale_sources_for(report, "gold") == ["gold", "usd_vnd"]
    assert predict.stale_sources_for(report, "wti") == ["usd_vnd"]
    st = _local(tmp_path)
    _write_lake(st, _prices(), report={"status": "partial", "stale_sources": {"usd_vnd": {}}})
    res = _by_asset(_run(st))
    assert all(r.record["stale_sources"] == ["usd_vnd"] for r in res.values())


# ---------- roll_in_horizon ----------


@pytest.mark.parametrize("asset,expiries", [("wti", "cl_expiries"), ("brent", "bz_expiries")])
def test_roll_in_horizon_window_edges(asset, expiries):
    exp = getattr(calendars, expiries)("2019-01-01", "2019-12-31")
    e = exp[exp >= pd.Timestamp("2019-03-01")][0]
    cme = calendars.sessions("CME")
    i = cme.get_loc(e)
    assert predict.roll_in_horizon(asset, e) is True  # đáo hạn đúng base: phiên roll = base + 1
    assert target_dates(asset, cme[i - 7])[-1] == str(e.date())
    assert predict.roll_in_horizon(asset, cme[i - 7]) is False  # đáo hạn đúng t7
    assert predict.roll_in_horizon(asset, cme[i - 6]) is True  # phiên roll đúng t7
    assert predict.roll_in_horizon(asset, cme[i + 1]) is False  # base là phiên roll


def test_roll_in_horizon_never_true_for_metals():
    for d in calendars.sessions("NYSE", "2019-01-01", "2019-12-20"):
        assert predict.roll_in_horizon("gold", d) is False
        assert predict.roll_in_horizon("silver", d) is False


# ---------- artifact mô hình ----------


def _write_artifact(d: Path, asset="gold", version=MV, **manifest):
    d.mkdir(parents=True, exist_ok=True)
    np.savez(d / "weights.npz", w=np.zeros(1, dtype=np.float32))
    (d / "config.json").write_text(json.dumps({"window": 60}), encoding="utf-8")
    (d / "scaler.json").write_text(json.dumps({"mean": [0.0], "std": [1.0]}), encoding="utf-8")
    m = {"asset": asset, "model_version": version, "integration_eligible": True}
    m.update(manifest)
    (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return d


def _factory(d):
    return FakeModel()


def test_load_model_dir_accepts_eligible_artifact(tmp_path):
    d = _write_artifact(tmp_path / "gold" / MV)
    loaded = predict.load_model_dir(d, "gold", MV, factory=_factory)
    assert loaded.window == 60 and loaded.manifest["asset"] == "gold"
    assert isinstance(loaded.model, FakeModel)


@pytest.mark.parametrize(
    "manifest",
    [{"integration_eligible": False}, {"integration_eligible": None}, {"asset": "silver"}],
)
def test_load_model_dir_rejects_bad_manifest(tmp_path, manifest):
    d = _write_artifact(tmp_path / "a", **manifest)
    with pytest.raises(predict.ModelArtifactError):
        predict.load_model_dir(d, "gold", MV, factory=_factory)


def test_load_model_dir_rejects_wrong_version_or_missing_file(tmp_path):
    d = _write_artifact(tmp_path / "a", version="other")
    with pytest.raises(predict.ModelArtifactError, match="model_version"):
        predict.load_model_dir(d, "gold", MV, factory=_factory)
    d = _write_artifact(tmp_path / "b")
    (d / "scaler.json").unlink()
    with pytest.raises(predict.ModelArtifactError, match="scaler.json"):
        predict.load_model_dir(d, "gold", MV, factory=_factory)


def test_allow_experimental_loads_with_warning(tmp_path, caplog):
    d = _write_artifact(tmp_path / "a", integration_eligible=False, missing_metadata=["commit"])
    caplog.set_level(logging.WARNING, logger="cpaws.predict")
    loaded = predict.load_model_dir(d, "gold", MV, allow_experimental=True, factory=_factory)
    assert loaded.window == 60
    assert "PREDICT_EXPERIMENTAL_MODEL asset=gold" in caplog.text


def test_default_factory_errors_are_artifact_errors(tmp_path):
    # Không có DLinearNumpy (PR #18 chưa merge) hoặc artifact giả không đúng DLinear: đều là
    # ModelArtifactError, không phải lỗi khác
    d = _write_artifact(tmp_path / "a")
    with pytest.raises(predict.ModelArtifactError):
        predict.load_model_dir(d, "gold", MV)


def test_invalid_model_version_rejected():
    with pytest.raises(ValueError):
        predict.make_model_loader("../x", model_dir=".")


def test_handler_rejects_ineligible_artifact_and_writes_others(aws, monkeypatch, tmp_path):
    s3, table = aws
    st = storage.S3Storage(BUCKET, client=s3)
    _write_lake(st, _prices())
    for asset in predict.PREDICT_ASSETS:
        src = _write_artifact(
            tmp_path / "src" / asset, asset, integration_eligible=asset != "brent"
        )
        for f in predict.MODEL_FILES:
            st.write_bytes(f"models/{asset}/{MV}/{f}", (src / f).read_bytes())
    real = predict.make_model_loader
    monkeypatch.setattr(
        predict,
        "make_model_loader",
        lambda mv, **k: real(mv, cache_dir=tmp_path / "cache", factory=_factory, **k),
    )
    with pytest.raises(lambda_predict.PredictFailed, match="brent"):
        lambda_predict.handler({}, None)
    assert _items(table, "brent") == []
    for asset in ("gold", "silver", "wti"):
        _assert_contract(_items(table, asset)[0], asset)
    assert (tmp_path / "cache" / "gold" / MV / "manifest.json").exists()


def test_model_missing_in_lake_is_artifact_error(tmp_path):
    st = _local(tmp_path)
    _write_lake(st, _prices())
    loader = predict.make_model_loader(MV, st=st, cache_dir=tmp_path / "cache", factory=_factory)
    run = predict.run_predict(st, None, load_model=loader, model_version=MV, assets=["wti"])
    res = run.results[0]
    assert res.status == "error" and res.reason == "model_artifact"
    assert f"models/wti/{MV}/weights.npz" in res.detail


# ---------- handler: cấu hình ----------


def test_handler_config_errors(aws, monkeypatch):
    with pytest.raises(lambda_predict.PredictConfigError):
        lambda_predict.handler({"assets": ["xau"]}, None)
    with pytest.raises(lambda_predict.PredictConfigError):
        lambda_predict.handler({"assets": "gold"}, None)
    # [] hoặc null không được ngầm hiểu là "cả 4 tài sản"
    with pytest.raises(lambda_predict.PredictConfigError):
        lambda_predict.handler({"assets": []}, None)
    with pytest.raises(lambda_predict.PredictConfigError, match="None"):
        lambda_predict.handler(json.loads('{"assets": null}'), None)
    monkeypatch.delenv("FORECASTS_TABLE")
    with pytest.raises(lambda_predict.PredictConfigError, match="FORECASTS_TABLE"):
        lambda_predict.handler({}, None)
    monkeypatch.delenv("MODEL_VERSION")
    with pytest.raises(lambda_predict.PredictConfigError, match="MODEL_VERSION"):
        lambda_predict.handler({"dry_run": True}, None)


# ---------- CLI ----------


def test_cli_local_with_base_date(tmp_path, monkeypatch):
    st = _local(tmp_path)
    _write_lake(st, _prices())
    seen = {}

    def fake_make_model_loader(mv, **kw):
        seen.update(kw, mv=mv)
        return _loader()

    monkeypatch.setattr(predict, "make_model_loader", fake_make_model_loader)
    out = tmp_path / "out"
    argv = ["--source", "local", "--lake-dir", str(tmp_path / "lake"), "--dest", "local"]
    argv += ["--out-dir", str(out), "--model-version", MV, "--assets", "gold", "brent"]
    rc = predict.main([*argv, "--base-date", "2019-05-15", "--allow-experimental"])
    assert rc == 0
    assert sorted(p.name for p in out.iterdir()) == ["brent.json", "gold.json"]
    assert json.loads((out / "gold.json").read_text(encoding="utf-8"))["base_date"] == "2019-05-15"
    assert seen["mv"] == MV and seen["allow_experimental"] is True
    assert seen["st"] is not None and seen["model_dir"] is None


def test_cli_exit_code_1_when_asset_skipped(tmp_path, monkeypatch):
    prices = _prices()
    m = (prices["asset"] == "wti") & (prices["date"] == pd.Timestamp(BASE))
    st = _local(tmp_path)
    _write_lake(st, prices.loc[~m].reset_index(drop=True))
    monkeypatch.setattr(predict, "make_model_loader", lambda mv, **k: _loader())
    argv = ["--lake-dir", str(tmp_path / "lake"), "--out-dir", str(tmp_path / "out")]
    assert predict.main([*argv, "--model-version", MV]) == 1
    assert not (tmp_path / "out" / "wti.json").exists()
    assert (tmp_path / "out" / "gold.json").exists()


# ---------- mốc 252 phiên (baseline-q252) ----------

BL = predict.BASELINE_MODEL_VERSION
BL_START = "2018-01-02"  # đủ 252 phiên trước BASE


def _bl_run(st, **kw) -> predict.PredictRun:
    loader = predict.make_model_loader(BL, st=st)
    return predict.run_predict(st, None, load_model=loader, model_version=BL, now=NOW, **kw)


def _q(record: dict) -> np.ndarray:
    return np.array([[float(v) for v in h["q"]] for h in record["horizons"]])


def _q252_direct(prices: pd.DataFrame, asset: str, base: str = BASE) -> np.ndarray:
    """quantile_baseline gọi trực tiếp trên r_h của toàn bộ chuỗi giá (theo lịch tài sản)."""
    s = prices.loc[prices["asset"] == asset].set_index("date")["price"]
    cal = ASSETS[asset].calendar
    return np.array(
        [
            quantile_baseline(horizon_log_returns(s, h, calendar=cal), h).loc[base].to_numpy()
            for h in range(1, 8)
        ]
    )


def test_quantile252_model_shape_and_order():
    rng = np.random.default_rng(0)
    q = Quantile252Model().predict(rng.normal(0, 0.01, (3, 252, 1)))
    assert q.shape == (3, 7, 7)
    assert (np.diff(q, axis=-1) >= 0).all()
    with pytest.raises(ValueError):
        Quantile252Model().predict(np.zeros((1, 60, 1)))
    with pytest.raises(ValueError):
        Quantile252Model().predict(np.full((1, 252, 1), np.nan))


def test_baseline_loader_reads_no_artifact(tmp_path):
    loaded = predict.make_model_loader(BL, model_dir=tmp_path / "missing")("gold")
    assert isinstance(loaded.model, Quantile252Model) and loaded.window == 252
    assert loaded.manifest == {"model_version": BL, "asset": "gold"}


def test_baseline_record_matches_quantile_baseline(tmp_path):
    prices = _prices(BL_START)
    st = _local(tmp_path)
    _write_lake(st, prices)
    run = _bl_run(st)
    assert run.ok, run.summary()
    res = _by_asset(run)
    for asset in predict.PREDICT_ASSETS:
        rec = res[asset].record
        _assert_contract(rec, asset, mv=BL)
        np.testing.assert_allclose(_q(rec), _q252_direct(prices, asset), atol=1e-6)


def test_baseline_unchanged_by_future_data(tmp_path):
    cut = _prices(BL_START)
    full = _prices(BL_START, "2019-09-30")
    later = full["date"] > pd.Timestamp(BASE)
    full.loc[later, "price"] *= np.where(full.loc[later, "asset"] == "usd_vnd", 1.05, 1.3)
    st_cut, st_full = _local(tmp_path, "cut"), _local(tmp_path, "full")
    _write_lake(st_cut, cut)
    _write_lake(st_full, full, dt="2019-10-01")
    r_cut = _by_asset(_bl_run(st_cut))  # chạy thường vào đúng ngày BASE
    r_full = _by_asset(_bl_run(st_full, base_date=BASE))
    for asset in predict.PREDICT_ASSETS:
        assert r_cut[asset].status == r_full[asset].status == "ok"
        assert _forecast(r_cut[asset].record) == _forecast(r_full[asset].record)
        assert r_cut[asset].record["input_snapshot_dt"] == DT
        assert r_full[asset].record["input_snapshot_dt"] == "2019-10-01"
        # quantile_baseline trên chuỗi có tương lai vẫn cho cùng giá trị tại BASE
        np.testing.assert_allclose(_q(r_full[asset].record), _q252_direct(full, asset), atol=1e-6)


@pytest.mark.parametrize(
    "day, reason",
    [(BASE, "latest_session_missing"), ("2018-10-15", "invalid_input_window")],
)
def test_baseline_missing_session_skips(tmp_path, caplog, day, reason):
    prices = _prices(BL_START)
    m = (prices["asset"] == "gold") & (prices["date"] == pd.Timestamp(day))
    st = _local(tmp_path)
    _write_lake(st, prices.loc[~m].reset_index(drop=True))
    caplog.set_level(logging.INFO, logger="cpaws.predict")
    res = _by_asset(_bl_run(st))
    assert res["gold"].status == "skipped" and res["gold"].reason == reason
    assert res["gold"].record is None
    assert all(res[a].status == "ok" for a in ("silver", "brent", "wti"))
    assert "PREDICT_SKIPPED asset=gold" in caplog.text and f"reason={reason}" in caplog.text


def test_cli_baseline_runs_selected_assets_only(tmp_path):
    _write_lake(_local(tmp_path), _prices(BL_START))
    out = tmp_path / "out"
    argv = ["--source", "local", "--lake-dir", str(tmp_path / "lake"), "--dest", "local"]
    argv += ["--out-dir", str(out), "--model-version", BL, "--assets", "gold", "silver"]
    assert predict.main([*argv, "--base-date", BASE]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["gold.json", "silver.json"]
    for name in ("gold", "silver"):
        rec = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
        assert rec["model_version"] == BL and rec["base_date"] == BASE


# Event Lambda destination OnSuccess của Lambda ingest (định dạng invocation record của AWS)
DESTINATION_EVENT = {
    "version": "1.0",
    "timestamp": "2019-06-29T12:16:03.512Z",
    "requestContext": {
        "requestId": "c6af9ac6-7b61-11e6-9a41-93e8deadbeef",
        "functionArn": "arn:aws:lambda:ap-southeast-1:000000000000:function:cpaws-dev-ingest:$LATEST",
        "condition": "Success",
        "approximateInvokeCount": 1,
    },
    "requestPayload": {},
    "responseContext": {"statusCode": 200, "executedVersion": "$LATEST"},
    "responsePayload": {"run_dt": DT, "status": "ok", "stale_sources": {}, "written": 12},
}


def _forbid_artifact_download(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("baseline-q252 must not read models/ from the lake")

    monkeypatch.setattr(predict, "_download_model", fail)


def test_handler_baseline_dry_run_all_assets_without_artifact(aws, monkeypatch):
    s3, table = aws
    monkeypatch.setenv("MODEL_VERSION", BL)
    _forbid_artifact_download(monkeypatch)
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices(BL_START))
    out = lambda_predict.handler({"dry_run": True}, None)
    assert out["ok"] and out["dry_run"] and out["written"] == 0
    assert out["model_version"] == BL
    assert set(out["assets"]) == set(predict.PREDICT_ASSETS)
    assert all(a["status"] == "ok" for a in out["assets"].values())
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET, Prefix="models/")
    assert table.scan()["Count"] == 0


def test_handler_destination_event_runs_all_assets(aws, monkeypatch):
    s3, table = aws
    monkeypatch.setenv("MODEL_VERSION", BL)
    _forbid_artifact_download(monkeypatch)
    _write_lake(storage.S3Storage(BUCKET, client=s3), _prices(BL_START))
    out = lambda_predict.handler(DESTINATION_EVENT, None)
    assert out["ok"] and not out["dry_run"] and out["written"] == 4
    assert set(out["assets"]) == set(predict.PREDICT_ASSETS)
    for asset in predict.PREDICT_ASSETS:
        items = _items(table, asset)
        assert len(items) == 1
        _assert_contract(items[0], asset, mv=BL)


# Event destination OnFailure: ingest raise sau khi đã retry (ví dụ một nguồn lỗi)
DESTINATION_FAILURE_EVENT = {
    **DESTINATION_EVENT,
    "requestContext": {
        **DESTINATION_EVENT["requestContext"],
        "condition": "RetriesExhausted",
        "approximateInvokeCount": 2,
    },
    "responseContext": {
        "statusCode": 200,
        "executedVersion": "$LATEST",
        "functionError": "Unhandled",
    },
    "responsePayload": {"errorMessage": "sources failed: gold", "errorType": "IngestFailed"},
}


def test_handler_failure_destination_event_writes_good_assets(aws, monkeypatch):
    """OnFailure vẫn gọi predict: tài sản có phiên mới nhất được ghi, tài sản thiếu phiên bị bỏ qua
    (bản ghi cũ giữ nguyên), rồi raise PredictFailed để metric Errors bật alarm."""
    s3, table = aws
    monkeypatch.setenv("MODEL_VERSION", BL)
    _forbid_artifact_download(monkeypatch)
    prices = _prices(BL_START)
    missing = (prices["asset"] == "gold") & (prices["date"] == pd.Timestamp(BASE))
    _write_lake(storage.S3Storage(BUCKET, client=s3), prices.loc[~missing].reset_index(drop=True))
    with pytest.raises(lambda_predict.PredictFailed, match="gold"):
        lambda_predict.handler(DESTINATION_FAILURE_EVENT, None)
    assert _items(table, "gold") == []
    for asset in ("silver", "brent", "wti"):
        items = _items(table, asset)
        assert len(items) == 1
        _assert_contract(items[0], asset, mv=BL)


# ---------- module ----------


def test_lake_keys_match_ingest():
    assert predict.PRICES == ingest_prices.PRICES
    assert predict.FACTORS == ingest_prices.FACTORS


def test_predict_path_does_not_import_heavy_libraries(tmp_path):
    """Import lambda_predict và chạy predict trên lake local trong tiến trình mới, chặn torch,
    PyEMD, yfinance, requests, ...; sau đó các module này không có trong sys.modules."""
    _write_lake(_local(tmp_path), _prices())
    code = textwrap.dedent(
        f"""
        import sys
        BLOCK = {{"torch", "PyEMD", "yfinance", "requests", "scipy", "sklearn", "statsmodels",
                  "dotenv"}}

        class Blocker:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCK:
                    raise ImportError("blocked " + name)
                return None

        sys.meta_path.insert(0, Blocker())
        sys.path.insert(0, {str(ROOT)!r})
        import numpy as np
        import src.forecast.lambda_predict
        from src.forecast import predict
        from src.data import storage

        class Model:
            def predict(self, x):
                return np.tile(np.linspace(-0.02, 0.02, 7), (len(x), 7, 1))

        st = storage.LocalStorage({str(tmp_path / "lake")!r})
        run = predict.run_predict(
            st,
            predict.LocalJsonSink({str(tmp_path / "out")!r}),
            load_model=lambda a: predict.LoadedModel(Model(), 60, {{}}),
            model_version="test",
        )
        assert run.ok, run.summary()
        assert not BLOCK & {{m.split(".")[0] for m in sys.modules}}
        print("OK")
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert out.returncode == 0 and out.stdout.strip().endswith("OK"), out.stderr[-2000:]


# ---------- thời điểm công bố của input ----------


def _late_publication(prices, asset, day, published_at):
    """Đổi published_at của một phiên (mô phỏng thanh giá công bố trễ hơn quy tắc)."""
    out = prices.copy()
    m = (out["asset"] == asset) & (out["date"] == pd.Timestamp(day))
    out.loc[m, "published_at"] = pd.Timestamp(published_at, tz="UTC")
    return out


@pytest.mark.parametrize(
    "now,ok",
    [
        (datetime(2019, 6, 29, 11, 59, tzinfo=UTC), False),  # thanh 28/6 công bố 29/6 12:00
        (datetime(2019, 6, 29, 12, 0, tzinfo=UTC), True),
    ],
)
def test_run_before_publication_time_skips(tmp_path, caplog, now, ok):
    st = _local(tmp_path)
    _write_lake(st, _prices())
    caplog.set_level(logging.INFO, logger="cpaws.predict")
    res = _by_asset(_run(st, now=now))
    for asset in predict.PREDICT_ASSETS:
        if ok:
            assert res[asset].status == "ok"
        else:
            assert res[asset].status == "skipped"
            assert res[asset].reason == "input_publication_unavailable"
            assert res[asset].record is None
    assert ("reason=input_publication_unavailable" in caplog.text) == (not ok)


def test_last_session_published_late_skips_only_that_asset(tmp_path):
    prices = _late_publication(_prices(), "gold", BASE, "2019-06-30 12:00")
    st = _local(tmp_path)
    _write_lake(st, prices)
    out = tmp_path / "out"
    res = _by_asset(_run(st, predict.LocalJsonSink(out)))  # now = 29/6 12:30
    assert res["gold"].status == "skipped"
    assert res["gold"].reason == "input_publication_unavailable"
    assert "as_of=2019-06-29T12:30:00+00:00" in res["gold"].detail
    assert not (out / "gold.json").exists()
    assert all(res[a].status == "ok" for a in ("silver", "brent", "wti"))


def test_backfill_as_of_follows_published_at_rule(tmp_path):
    d = "2019-05-15"
    snap = predict.cut_snapshot(predict.Snapshot(DT, _prices(), clean.empty_frame(), {}, None), d)
    # yfinance: D+1 12:00 UTC, không phụ thuộc thời điểm chạy thật
    assert predict.publication_as_of("gold", snap, NOW) == pd.Timestamp("2019-05-16 12:00Z")
    live = predict.Snapshot(DT, _prices(), clean.empty_frame(), {}, None)
    assert predict.publication_as_of("wti", live, NOW) == pd.Timestamp(NOW)

    # Thanh vàng của D công bố muộn hơn quy tắc 1 giờ: backfill bỏ qua dù now (29/6) muộn hơn nhiều
    late = _late_publication(_prices(), "gold", d, "2019-05-16 13:00")
    st = _local(tmp_path)
    _write_lake(st, late)
    res = _by_asset(_run(st, base_date=d))
    assert res["gold"].status == "skipped"
    assert res["gold"].reason == "input_publication_unavailable"
    assert all(res[a].status == "ok" for a in ("silver", "brent", "wti"))
    st2 = _local(tmp_path, "on_time")
    _write_lake(st2, _late_publication(_prices(), "gold", d, "2019-05-16 12:00"))
    assert _by_asset(_run(st2, base_date=d))["gold"].status == "ok"


# ---------- tích hợp với DLinear thật (PR #18) ----------

COMMIT = "0123456789abcdef0123456789abcdef01234567"  # commit giả → integration_eligible = true
TRAIN_START = "2013-06-03"  # khởi động cửa sổ 60 phiên cho origin đầu 2014


@pytest.fixture(scope="module")
def dlinear_artifacts(tmp_path_factory):
    """Huấn luyện DLinear 1 epoch cho 4 tài sản trên giá tổng hợp 2013–2018 và xuất artifact thật
    (eligible); thêm một bản vàng không có source_commit (experimental)."""
    pytest.importorskip("torch")
    from src.forecast.dlinear_data import prepare_training_data
    from src.forecast.train_dlinear import export_artifact, train_model

    root = tmp_path_factory.mktemp("dlinear")
    prices = _prices(start=TRAIN_START)
    rejected = clean.empty_frame()
    t0 = time.perf_counter()
    for asset in predict.PREDICT_ASSETS:
        data = prepare_training_data(prices, rejected, asset)
        model, scaler, _ = train_model(data, epochs=1, batch_size=256, device="cpu")
        export_artifact(
            model,
            scaler,
            data,
            root / "eligible",
            asset=asset,
            model_version=MV,
            source_commit=COMMIT,
        )
        if asset == "gold":
            export_artifact(
                model, scaler, data, root / "experimental", asset=asset, model_version=MV
            )
    print(f"dlinear_artifacts: trained and exported in {time.perf_counter() - t0:.1f}s")
    return root, prices


def test_real_dlinear_artifact_end_to_end(tmp_path, dlinear_artifacts):
    from src.features.build import build_feature_frame, make_windows
    from src.forecast.dlinear_numpy import DLinearNumpy

    root, prices = dlinear_artifacts
    st = _local(tmp_path)
    _write_lake(st, prices)
    loader = predict.make_model_loader(MV, model_dir=root / "eligible")  # không truyền factory
    run = predict.run_predict(st, None, load_model=loader, model_version=MV, now=NOW)
    assert run.ok, run.summary()
    res = _by_asset(run)
    for asset in predict.PREDICT_ASSETS:
        _assert_contract(res[asset].record, asset)
        assert _no_floats(res[asset].record)

    # Bản ghi vàng đúng bằng đầu ra DLinearNumpy trên cửa sổ của build.py, đã sắp xếp
    loaded = loader("gold")
    assert isinstance(loaded.model, DLinearNumpy)
    assert loaded.manifest["integration_eligible"] is True and loaded.manifest["commit"] == COMMIT
    frame = build_feature_frame(prices, "gold", invalid_dates=[])
    batch = make_windows(frame, [pd.Timestamp(BASE)], window=60)
    want = np.sort(DLinearNumpy.load(root / "eligible" / "gold" / MV).predict(batch.X)[0], axis=-1)
    got = np.array([[float(v) for v in h["q"]] for h in res["gold"].record["horizons"]])
    np.testing.assert_allclose(got, want, atol=1e-6)


def test_real_artifact_without_commit_needs_allow_experimental(tmp_path, dlinear_artifacts, caplog):
    root, prices = dlinear_artifacts
    st = _local(tmp_path)
    _write_lake(st, prices)
    strict = predict.make_model_loader(MV, model_dir=root / "experimental")
    with pytest.raises(predict.ModelArtifactError, match="integration_eligible=False"):
        strict("gold")
    run = predict.run_predict(
        st, None, load_model=strict, model_version=MV, assets=["gold"], now=NOW
    )
    assert run.results[0].status == "error" and run.results[0].reason == "model_artifact"

    caplog.set_level(logging.WARNING, logger="cpaws.predict")
    loose = predict.make_model_loader(MV, model_dir=root / "experimental", allow_experimental=True)
    run = predict.run_predict(
        st, None, load_model=loose, model_version=MV, assets=["gold"], now=NOW
    )
    assert run.ok
    _assert_contract(run.results[0].record, "gold")
    assert "PREDICT_EXPERIMENTAL_MODEL asset=gold" in caplog.text

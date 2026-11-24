import importlib.util
import json
import logging
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
import pytest
from moto import mock_aws

from scripts import export_price_history as eph
from src.data import calendars, clean, storage
from src.data.config import ASSETS
from src.forecast import predict
from src.forecast.forecast_record import PRICE_UNIT

ROOT = Path(__file__).resolve().parents[1]
REGION = "ap-southeast-1"
BUCKET = "cpaws-test-lake"
START, END, DT = "2019-01-02", "2019-06-28", "2019-06-29"
BASE_PRICE = {"gold": 120.0, "silver": 14.0, "brent": 65.0, "wti": 58.0, "usd_vnd": 23_200.0}
FACTOR = {"gold": 10.5, "silver": 1.08}
NOW = datetime(2019, 6, 29, 13, 0, tzinfo=UTC)
DOC_KEYS = {
    "asset",
    "unit",
    "source",
    "generated_at",
    "last_base_date",
    "points",
    "input_snapshot_dt",
}


def _prices(start: str = START, end: str = END) -> pd.DataFrame:
    """Bảng clean dạng dài cho 4 tài sản + usd_vnd, mỗi tài sản trên lịch của nó."""
    frames = []
    for asset, p0 in BASE_PRICE.items():
        d = calendars.sessions(ASSETS[asset].calendar, start, end)
        rng = np.random.default_rng(zlib.crc32(asset.encode()))
        frames.append(
            pd.DataFrame(
                {
                    "date": d,
                    "asset": asset,
                    "price": p0 * np.exp(np.cumsum(rng.normal(0, 0.01, len(d)))),
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
                    "factor": f0 + 1e-3 * np.arange(len(d)),
                    "reference": "gc_fut" if asset == "gold" else "si_fut",
                    "reliability": "normal" if asset == "gold" else "low",
                    "unit": "USD/oz per share",
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def _write_lake(st, prices, *, rejected=None, factors="auto", dt=DT):
    base = f"clean/prices/dt={dt}"
    storage.write_parquet(st, f"{base}/prices.parquet", prices)
    rej = clean.empty_frame() if rejected is None else clean.normalize_types(rejected)
    storage.write_parquet(st, f"{base}/rejected.parquet", rej)
    if isinstance(factors, str):
        factors = _factors(prices)
    if factors is not None:
        storage.write_parquet(st, f"clean/display_factors/dt={dt}/display_factors.parquet", factors)
    storage.write_json(st, f"{base}/quality.json", {"status": "ok", "stale_sources": {}})


def _px(prices, asset, day) -> float:
    m = (prices["asset"] == asset) & (prices["date"] == pd.Timestamp(day))
    return float(prices.loc[m, "price"].iloc[0])


def _fac(factors, asset, day) -> float:
    m = (factors["asset"] == asset) & (factors["date"] == pd.Timestamp(day))
    return float(factors.loc[m, "factor"].iloc[0])


def _lake(tmp_path, prices=None, **kw):
    st = storage.LocalStorage(tmp_path / "lake")
    _write_lake(st, _prices() if prices is None else prices, **kw)
    return st


def _export(st, tmp_path, **kw):
    kw.setdefault("out_dir", tmp_path / "out")
    return eph.export(st, now=NOW, **kw)


def _read(tmp_path, asset) -> dict:
    return json.loads((tmp_path / "out" / f"{asset}.json").read_text(encoding="utf-8"))


# ---------- đơn vị và giá trị ----------


def test_metals_use_display_factor_and_oil_uses_raw_price(tmp_path):
    prices = _prices()
    factors = _factors(prices)
    st = _lake(tmp_path, prices, factors=factors)
    _export(st, tmp_path, sessions=20)
    for asset in ("gold", "silver"):
        doc = _read(tmp_path, asset)
        assert doc["unit"] == "USD/oz"
        for p in doc["points"]:
            want = _px(prices, asset, p["base_date"]) * _fac(factors, asset, p["base_date"])
            assert p["last_price"] == round(want, 2)
    for asset in ("brent", "wti"):
        doc = _read(tmp_path, asset)
        assert doc["unit"] == "USD/bbl"
        for p in doc["points"]:
            assert p["last_price"] == round(_px(prices, asset, p["base_date"]), 2)


def test_points_match_predict_last_price_display(tmp_path):
    """Cùng hàm predict dùng cho Forecasts.last_price: điểm cuối = giá predict ghi cho base_date."""
    st = _lake(tmp_path)
    snap = predict.load_snapshot(st)
    _export(st, tmp_path, sessions=5)
    for asset in eph.EXPORT_ASSETS:
        last = _read(tmp_path, asset)["points"][-1]
        want = predict.last_price_display(snap, asset, pd.Timestamp(last["base_date"]))
        assert last["last_price"] == round(want, 2)


def test_document_fields_and_rounding(tmp_path):
    st = _lake(tmp_path)
    _export(st, tmp_path, sessions=10)
    for asset in eph.EXPORT_ASSETS:
        doc = _read(tmp_path, asset)
        assert set(doc) == DOC_KEYS
        assert doc["asset"] == asset
        assert doc["unit"] == PRICE_UNIT[asset]
        assert doc["source"] == "Yahoo Finance (yfinance)"
        assert doc["generated_at"] == "2019-06-29T13:00:00Z"
        assert doc["input_snapshot_dt"] == DT
        assert doc["last_base_date"] == doc["points"][-1]["base_date"]
        for p in doc["points"]:
            assert set(p) == {"base_date", "last_price"}
            assert p["last_price"] == round(p["last_price"], 2) > 0


# ---------- chọn phiên ----------


def test_points_old_to_new_limited_to_most_recent_sessions(tmp_path):
    prices = _prices()
    st = _lake(tmp_path, prices)
    _export(st, tmp_path, sessions=30)
    for asset in eph.EXPORT_ASSETS:
        dates = [p["base_date"] for p in _read(tmp_path, asset)["points"]]
        cal = calendars.sessions(ASSETS[asset].calendar, START, END)
        assert dates == [str(d.date()) for d in cal[-30:]]
        assert dates == sorted(dates) and len(set(dates)) == 30


def test_fewer_sessions_than_requested_writes_what_exists(tmp_path):
    st = _lake(tmp_path)
    res = _export(st, tmp_path, sessions=520)
    for asset in eph.EXPORT_ASSETS:
        n = len(calendars.sessions(ASSETS[asset].calendar, START, END))
        assert len(res[asset].points) == n < 520
        assert len(_read(tmp_path, asset)["points"]) == n


def test_as_of_cuts_snapshot(tmp_path):
    st = _lake(tmp_path)
    _export(st, tmp_path, sessions=10, as_of="2019-03-16")  # thứ Bảy
    for asset in eph.EXPORT_ASSETS:
        doc = _read(tmp_path, asset)
        assert doc["last_base_date"] == "2019-03-15"
        assert len(doc["points"]) == 10


def test_missing_factor_and_stale_factor_days_are_dropped(tmp_path):
    """Vàng: factor chỉ có từ phiên thứ 11 tới phiên cuối − 10. Trước đó: thiếu factor; sau đó:
    dùng factor cũ tới lag 5 phiên NYSE, lag > 5 bị bỏ. Không forward-fill giá."""
    prices = _prices()
    nyse = calendars.sessions("NYSE", START, END)
    f = _factors(prices)
    first, last = nyse[10], nyse[-11]
    gold = f["asset"] == "gold"
    f = f.loc[~gold | ((f["date"] >= first) & (f["date"] <= last))].reset_index(drop=True)
    st = _lake(tmp_path, prices, factors=f)
    res = _export(st, tmp_path, sessions=520)

    dates = [p["base_date"] for p in res["gold"].points]
    want = nyse[10 : len(nyse) - 11 + 5 + 1]
    assert dates == [str(d.date()) for d in want]
    assert res["gold"].skipped["display_factor_missing"] == 10
    assert res["gold"].skipped["display_factor_stale"] == 10 - 5
    # Ngày trễ dùng factor cũ (ngày `last`), không phải factor của chính ngày đó
    lagged = res["gold"].points[-1]
    assert lagged["last_price"] == round(
        _px(prices, "gold", lagged["base_date"]) * _fac(f, "gold", last), 2
    )
    # Bạc không bị ảnh hưởng
    assert len(res["silver"].points) == len(nyse)


def test_rejected_and_nonpositive_days_are_dropped_without_fill(tmp_path):
    prices = _prices()
    cme = calendars.sessions("CME", START, END)
    bad_day, neg_day = cme[-3], cme[-5]
    rejected = prices.loc[(prices["asset"] == "wti") & (prices["date"] == bad_day)].copy()
    rejected["flag"] = "bad_value"
    prices = prices.loc[~((prices["asset"] == "wti") & (prices["date"] == bad_day))].copy()
    prices.loc[(prices["asset"] == "wti") & (prices["date"] == neg_day), "price"] = -1.0
    st = _lake(tmp_path, prices, rejected=rejected)
    res = _export(st, tmp_path, sessions=6)

    dates = [p["base_date"] for p in res["wti"].points]
    assert str(bad_day.date()) not in dates and str(neg_day.date()) not in dates
    assert dates == [str(d.date()) for d in cme[-8:] if d not in (bad_day, neg_day)]
    assert res["wti"].skipped["nonpositive_price"] == 1


def test_rejected_date_still_in_prices_is_dropped(tmp_path):
    """Ngày nằm trong rejected.parquet bị bỏ kể cả khi prices.parquet vẫn còn dòng ngày đó."""
    prices = _prices()
    nyse = calendars.sessions("NYSE", START, END)
    rejected = prices.loc[(prices["asset"] == "silver") & (prices["date"] == nyse[-2])].copy()
    st = _lake(tmp_path, prices, rejected=rejected)
    res = _export(st, tmp_path, sessions=3)
    assert [p["base_date"] for p in res["silver"].points] == [
        str(d.date()) for d in (nyse[-4], nyse[-3], nyse[-1])
    ]
    assert res["silver"].skipped["rejected"] == 1


def test_no_display_factors_skips_metals_and_cli_exits_1(tmp_path, capsys):
    st = _lake(tmp_path, factors=None)
    out = tmp_path / "out"
    code = eph.main(
        ["--source", "local", "--lake-dir", str(st.root), "--dest", "local", "--out-dir", str(out)]
    )
    assert code == 1
    assert sorted(p.name for p in out.iterdir()) == ["brent.json", "wti.json"]
    summary = json.loads(capsys.readouterr().out)
    assert summary["gold"]["points"] == 0 and summary["gold"]["written_to"] is None


# ---------- nơi ghi ----------


def test_cli_local_writes_four_files(tmp_path, capsys):
    st = _lake(tmp_path)
    out = tmp_path / "out"
    argv = ["--lake-dir", str(st.root), "--out-dir", str(out), "--sessions", "15"]
    assert eph.main(argv) == 0
    assert sorted(p.name for p in out.iterdir()) == sorted(f"{a}.json" for a in eph.EXPORT_ASSETS)
    for asset in eph.EXPORT_ASSETS:
        assert len(_read(tmp_path, asset)["points"]) == 15
    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == set(eph.EXPORT_ASSETS)


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_cli_rejects_invalid_sessions(value):
    with pytest.raises(SystemExit):
        eph.main(["--sessions", value])


@pytest.fixture
def aws(monkeypatch):
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
        "LAKE_BUCKET": BUCKET,
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("LAKE_PREFIX", "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        yield s3


def test_cli_s3_to_s3_writes_json_objects(aws, capsys):
    st = predict.make_storage("s3")
    _write_lake(st, _prices())
    assert eph.main(["--source", "s3", "--dest", "s3", "--sessions", "12"]) == 0
    for asset in eph.EXPORT_ASSETS:
        obj = aws.get_object(Bucket=BUCKET, Key=f"serving/price-history/{asset}.json")
        assert obj["ContentType"] == "application/json"
        doc = json.loads(obj["Body"].read())
        assert doc["asset"] == asset and len(doc["points"]) == 12
    summary = json.loads(capsys.readouterr().out)
    assert summary["wti"]["written_to"] == f"s3://{BUCKET}/serving/price-history/wti.json"


@pytest.mark.parametrize("source", ["s3", "local"])
def test_cli_s3_dest_with_lake_prefix_fails_fast_and_writes_nothing(
    aws, tmp_path, monkeypatch, caplog, source
):
    """LAKE_PREFIX khác rỗng: Lambda đọc ở gốc bucket nên script dừng (mã 2), không ghi object nào."""
    if source == "s3":
        _write_lake(predict.make_storage("s3"), _prices())
        args = ["--source", "s3"]
    else:
        _lake(tmp_path)
        args = ["--source", "local", "--lake-dir", str(tmp_path / "lake")]
    monkeypatch.setenv("LAKE_PREFIX", "team-a/")
    caplog.set_level(logging.ERROR)
    assert eph.main([*args, "--dest", "s3", "--sessions", "4"]) == 2
    assert "EXPORT_PREFIX_MISMATCH" in caplog.text
    listed = aws.list_objects_v2(Bucket=BUCKET)
    keys = [o["Key"] for o in listed.get("Contents", [])]
    assert not [k for k in keys if "price-history" in k]


def test_cli_local_dest_ignores_lake_prefix(tmp_path, monkeypatch):
    """--dest local không phụ thuộc LAKE_PREFIX: vẫn ghi đủ 4 file."""
    _lake(tmp_path)
    monkeypatch.setenv("LAKE_PREFIX", "team-a/")
    out = tmp_path / "out"
    args = ["--source", "local", "--lake-dir", str(tmp_path / "lake"), "--dest", "local"]
    assert eph.main([*args, "--out-dir", str(out), "--sessions", "4"]) == 0
    assert sorted(f.name for f in out.iterdir()) == sorted(f"{a}.json" for a in eph.EXPORT_ASSETS)


def test_s3_export_overwrites_and_reads_local_lake(aws, tmp_path):
    """--source local --dest s3: đọc lake local, ghi đè object đã có trên S3."""
    aws.put_object(Bucket=BUCKET, Key="serving/price-history/gold.json", Body=b"old")
    st = _lake(tmp_path)
    dest = predict.make_storage("s3")
    res = eph.export(st, sessions=4, dest="s3", dest_st=dest, now=NOW)
    assert res["gold"].written_to == f"s3://{BUCKET}/serving/price-history/gold.json"
    body = aws.get_object(Bucket=BUCKET, Key="serving/price-history/gold.json")["Body"].read()
    assert json.loads(body)["points"] == res["gold"].points


def test_s3_dest_requires_storage(tmp_path):
    with pytest.raises(ValueError):
        eph.export(_lake(tmp_path), dest="s3")


def test_defaults_match_forecast_api_lambda():
    """Số phiên mặc định = HISTORY_MAX, key = PRICE_HISTORY_PREFIX mặc định của Lambda."""
    handler_path = ROOT / "infra" / "lambda" / "forecast_api" / "handler.py"
    sys.path.insert(0, str(handler_path.parent))
    try:
        spec = importlib.util.spec_from_file_location("forecast_api_for_export", handler_path)
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
    finally:
        sys.path.remove(str(handler_path.parent))
    assert eph.DEFAULT_SESSIONS == api.HISTORY_MAX == 520
    assert f"{eph.SERVING_PREFIX}/" == api.PRICE_HISTORY_PREFIX_DEFAULT
    assert eph.DEFAULT_OUT_DIR == "data/serving/price-history"

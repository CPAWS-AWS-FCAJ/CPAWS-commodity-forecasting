"""Ghi lên S3 (moto, không gọi AWS thật), Lambda handler, dry_run, lấy EIA key."""

import functools
import json

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from src.data import ingest_prices, lambda_ingest, secret_store, storage
from src.data.sources import yfinance_src
from src.data.sources.yfinance_src import YFinanceSource
from tests.data_fakes import FakeEIA, FakeYF

NOW = pd.Timestamp("2020-05-29 20:00", tz="UTC")
BUCKET = "cpaws-test-lake"


@pytest.fixture
def s3(monkeypatch):
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "ap-southeast-1",
        "LAKE_BUCKET": BUCKET,
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("LAKE_PREFIX", "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    # CLI gọi load_dotenv(); không để .env của máy (profile, key thật) lọt vào test
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    with mock_aws():
        client = boto3.client("s3", region_name="ap-southeast-1")
        client.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"}
        )
        yield client


def _keys(client):
    return {o["Key"] for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])}


def _fake(monkeypatch, fail=None):
    src = {"yfinance": YFinanceSource(FakeYF(fail=fail)), "eia": FakeEIA()}
    monkeypatch.setattr(ingest_prices, "build_sources", lambda: (src, None))
    monkeypatch.setattr(ingest_prices, "run", functools.partial(ingest_prices.run, now=NOW))


@pytest.mark.parametrize("prefix", ["", "team-a"])
def test_handler_writes_lake_layout_to_s3(s3, monkeypatch, prefix):
    if prefix:
        monkeypatch.setenv("LAKE_PREFIX", prefix)
    _fake(monkeypatch)
    out = lambda_ingest.handler({"start": "2020-03-02"}, None)
    assert out["status"] == "ok" and out["stale_sources"] == {}
    p = f"{prefix}/" if prefix else ""
    keys = _keys(s3)
    for k in (
        "raw/yfinance/dt=2020-05-29/GLD.csv.gz",
        "clean/prices/dt=2020-05-29/prices.parquet",
        "clean/prices/dt=2020-05-29/rejected.parquet",
        "clean/prices/dt=2020-05-29/quality.json",
        "clean/display_fx/dt=2020-05-29/display_fx.parquet",
    ):
        assert p + k in keys, k
    assert all(k.startswith(p) for k in keys)
    st = storage.S3Storage(BUCKET, client=s3, root=p)
    q = json.loads(st.read_bytes("clean/prices/dt=2020-05-29/quality.json"))
    assert q["status"] == "ok"
    assert len(storage.read_parquet(st, "clean/prices/dt=2020-05-29/prices.parquet")) > 0


def test_handler_raises_on_source_failure_after_writing_others(s3, monkeypatch, caplog):
    _fake(monkeypatch, fail={"CL=F"})
    with (
        caplog.at_level("ERROR", logger="cpaws.ingest"),
        pytest.raises(lambda_ingest.IngestSourceFailed, match="wti"),
    ):
        lambda_ingest.handler({"start": "2020-03-02"}, None)
    assert any("INGEST_SOURCE_FAILED" in r.getMessage() for r in caplog.records)
    assert "clean/prices/dt=2020-05-29/prices.parquet" in _keys(s3)  # tài sản khác vẫn ghi


def test_handler_incremental_reads_previous_snapshot_from_s3(s3, monkeypatch):
    _fake(monkeypatch)
    lambda_ingest.handler({"start": "2020-03-02"}, None)
    later = pd.Timestamp("2020-06-05 20:00", tz="UTC")
    src = {"yfinance": YFinanceSource(FakeYF(end="2020-06-05")), "eia": FakeEIA("2020-06-05")}
    monkeypatch.setattr(ingest_prices, "build_sources", lambda: (src, None))
    real = ingest_prices.run.func
    monkeypatch.setattr(ingest_prices, "run", functools.partial(real, now=later))
    lambda_ingest.handler({}, None)
    st = storage.S3Storage(BUCKET, client=s3)
    p = storage.read_parquet(st, "clean/prices/dt=2020-06-05/prices.parquet")
    assert p.loc[p["asset"] == "gold", "date"].min() == pd.Timestamp("2020-03-02")


def test_dry_run_reports_each_symbol_and_writes_nothing(s3, monkeypatch):
    fake = FakeYF(end="2020-05-29", fail={"VND=X"})
    monkeypatch.setattr(yfinance_src, "_default_history", fake)
    monkeypatch.setattr(ingest_prices, "dry_run", functools.partial(ingest_prices.dry_run, now=NOW))
    out = lambda_ingest.handler({"dry_run": True}, None)
    sym = out["symbols"]
    assert set(sym) == {"GLD", "SLV", "CL=F", "BZ=F", "VND=X"}
    assert sym["GLD"]["rows"] == 10 and sym["GLD"]["error"] is None
    assert sym["VND=X"]["rows"] == 0 and "blocked" in sym["VND=X"]["error"]
    assert _keys(s3) == set()


def test_lambda_setup_moves_yfinance_cache_to_tmp(monkeypatch, tmp_path):
    import yfinance

    called = {}
    monkeypatch.setattr(yfinance, "set_tz_cache_location", lambda d: called.setdefault("dir", d))
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    lambda_ingest._lambda_setup()
    assert called == {}  # ở local không đụng cache
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "cpaws-dev-ingest")
    monkeypatch.setenv("YF_CACHE_DIR", str(tmp_path))
    lambda_ingest._lambda_setup()
    assert called["dir"] == str(tmp_path)


def test_cli_dest_s3(s3, monkeypatch):
    _fake(monkeypatch)
    code = ingest_prices.main(["--dest", "s3", "--start", "2020-03-02", "--no-nbp"])
    assert code == 0 and "clean/prices/dt=2020-05-29/quality.json" in _keys(s3)


def test_eia_key_from_env_and_secret_id_todo(monkeypatch, caplog):
    monkeypatch.setenv("EIA_API_KEY", "abc123")
    assert secret_store.get_eia_api_key() == "abc123"
    monkeypatch.delenv("EIA_API_KEY")
    monkeypatch.setenv("EIA_SECRET_ID", "cpaws/dev/eia")
    with pytest.raises(secret_store.SecretUnavailable):
        secret_store.get_eia_api_key()
    # build_sources bỏ EIA (nguồn tham chiếu) thay vì dừng, và không in key ra log
    monkeypatch.setenv("EIA_API_KEY", "")
    with caplog.at_level("WARNING", logger="cpaws.ingest"):
        sources, _ = ingest_prices.build_sources()
    assert "eia" not in sources
    assert not any("abc123" in r.getMessage() for r in caplog.records)

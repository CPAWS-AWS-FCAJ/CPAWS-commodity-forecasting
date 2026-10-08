"""Pipeline ingest đầu-cuối với nguồn giả: spike VND, ghi local hai lần cho cùng kết quả, tăng dần."""

import json

import pandas as pd
import pytest

from src.data import ingest_prices, storage
from src.data.clean import split_flags
from src.data.sources.yfinance_src import YFinanceSource
from tests.data_fakes import FakeEIA, FakeYF

NOW = pd.Timestamp("2020-05-29 20:00", tz="UTC")  # 16:00 NY: thanh 29/5 chưa chốt


def _sources(yf_fail=None, spikes=None):
    return {
        "yfinance": YFinanceSource(FakeYF(fail=yf_fail, spikes=spikes)),
        "eia": FakeEIA(),
    }


def _read(st, run_dt, name):
    return storage.read_parquet(st, f"clean/prices/dt={run_dt}/{name}")


def test_full_run_writes_layout_and_flags(tmp_path):
    st = storage.LocalStorage(tmp_path)
    res = ingest_prices.run(st, _sources(), start="2020-03-02", now=NOW)
    p = res.prices
    assert set(p["asset"]) == {"gold", "silver", "wti", "brent", "usd_vnd"}
    assert p["date"].max() < pd.Timestamp("2020-05-29")  # bỏ thanh của ngày hiện tại (giờ NY)
    # Good Friday 10/4/2020: loại thanh vàng/dầu, VND (FX) vẫn giữ
    gf = pd.Timestamp("2020-04-10")
    assert gf not in set(p.loc[p["asset"] == "gold", "date"])
    rej = res.rejected
    assert "exchange_holiday" in split_flags(
        rej.loc[(rej["asset"] == "wti") & (rej["date"] == gf), "flag"].iloc[0]
    )
    wti_neg = p[(p["asset"] == "wti") & (p["date"] == "2020-04-20")].iloc[0]
    assert wti_neg["price"] == -37.63 and "negative_price" in split_flags(wti_neg["flag"])
    assert set(p["source"]) == {"yfinance"}
    for key in (
        "clean/prices/dt=2020-05-29/prices.parquet",
        "clean/prices/dt=2020-05-29/quality.json",
        "clean/reference_prices/dt=2020-05-29/reference.parquet",
        "clean/display_factors/dt=2020-05-29/display_factors.parquet",
        "raw/yfinance/dt=2020-05-29/GLD.csv.gz",
        "raw/yfinance/dt=2020-05-29/CL_F.csv.gz",
    ):
        assert st.exists(key), key
    q = json.loads(st.read_bytes("clean/prices/dt=2020-05-29/quality.json"))
    assert q["assets"]["wti"]["rejected"]["exchange_holiday"] >= 1
    assert "roll" in q["assets"]["wti"]["flags"]


def test_vnd_one_day_spike_is_rejected(tmp_path):
    st = storage.LocalStorage(tmp_path)
    res = ingest_prices.run(
        st, _sources(spikes={"VND=X": "2020-04-15"}), start="2020-03-02", now=NOW
    )
    vnd = res.prices[res.prices["asset"] == "usd_vnd"]
    assert pd.Timestamp("2020-04-15") not in set(vnd["date"])
    rej = res.rejected
    row = rej[(rej["asset"] == "usd_vnd") & (rej["date"] == "2020-04-15")].iloc[0]
    assert split_flags(row["flag"]) == {"bad_value", "spike"}
    assert res.report["assets"]["usd_vnd"]["rejected"]["spike"] == 1


def test_one_source_failing_does_not_stop_pipeline(tmp_path):
    st = storage.LocalStorage(tmp_path)
    res = ingest_prices.run(st, _sources(yf_fail={"BZ=F"}), start="2020-03-02", now=NOW)
    assert "brent" not in set(res.prices["asset"]) and "wti" in set(res.prices["asset"])


def test_running_twice_gives_same_result(tmp_path):
    st = storage.LocalStorage(tmp_path)
    ingest_prices.run(st, _sources(), start="2020-03-02", now=NOW)
    first = {n: _read(st, "2020-05-29", n) for n in ("prices.parquet", "rejected.parquet")}
    q1 = st.read_bytes("clean/prices/dt=2020-05-29/quality.json")
    ingest_prices.run(st, _sources(), start="2020-03-02", now=NOW + pd.Timedelta(minutes=5))
    for n, df in first.items():
        pd.testing.assert_frame_equal(df, _read(st, "2020-05-29", n))
    q2 = json.loads(st.read_bytes("clean/prices/dt=2020-05-29/quality.json"))
    q1 = json.loads(q1)
    q1.pop("run"), q2.pop("run")
    assert q1 == q2


def test_incremental_run_refetches_last_sessions_only(tmp_path):
    st = storage.LocalStorage(tmp_path)
    ingest_prices.run(st, _sources(), start="2020-03-02", now=NOW)
    yf = FakeYF(end="2020-06-05")
    src = {"yfinance": YFinanceSource(yf), "eia": FakeEIA(end="2020-06-05")}
    res = ingest_prices.run(st, src, now=pd.Timestamp("2020-06-05 20:00", tz="UTC"))
    starts = {s for _, s in yf.calls}
    assert len(starts) == 1 and pd.Timestamp(starts.pop()) >= pd.Timestamp("2020-05-20")
    g = res.prices[res.prices["asset"] == "wti"]
    assert g["date"].min() == pd.Timestamp("2020-03-02")  # lịch sử cũ được giữ
    assert g["date"].max() == pd.Timestamp("2020-06-04")
    assert not g.duplicated(["date", "asset"]).any()


@pytest.mark.parametrize("dest", ["local"])
def test_cli_parses_args(dest, monkeypatch, tmp_path):
    called = {}

    def fake_run(st, sources, start=None, nbp_source=None, now=None):
        called.update(start=start, st=st, nbp=nbp_source)
        return ingest_prices.RunResult(
            "2020-05-29",
            *(pd.DataFrame(),) * 4,
            {"assets": {}, "run": {"fetch_log": []}},
            ["q.json"],
        )

    monkeypatch.setattr(ingest_prices, "run", fake_run)
    monkeypatch.setattr(ingest_prices, "build_sources", lambda: ({}, object()))
    ingest_prices.main(
        ["--start", "2012-01-01", "--dest", dest, "--lake-dir", str(tmp_path), "--no-nbp"]
    )
    assert called["start"] == "2012-01-01" and called["nbp"] is None
    assert isinstance(called["st"], storage.LocalStorage)

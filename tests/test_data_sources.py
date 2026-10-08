"""Adapter nguồn giá: yfinance, EIA, NBP (fixture giả, không gọi mạng)."""

import pandas as pd
import pytest

from src.data.sources import SourceError
from src.data.sources import eia as eia_mod
from src.data.sources.eia import EIASource
from src.data.sources.nbp import OZ_G, NBPSource
from src.data.sources.yfinance_src import YFinanceSource
from tests.data_fakes import FakeResponse, FakeSession, synthetic_bars

# ---------- yfinance ----------


def test_yfinance_strips_timezone_keeping_trading_date():
    df = synthetic_bars("CL=F", "2020-04-15", "2020-04-22")
    res = YFinanceSource(lambda s, a, b: df).fetch("CL=F", "2020-04-15")
    assert res.bars.index.tz is None
    assert res.bars.index[0] == pd.Timestamp("2020-04-15")
    assert res.bars.loc["2020-04-20", "close"] == -37.63
    assert res.raw_name == "CL_F.csv.gz"


def test_yfinance_errors_become_source_error():
    def boom(s, a, b):
        raise ConnectionError("blocked")

    with pytest.raises(SourceError):
        YFinanceSource(boom).fetch("GLD", "2020-01-01")
    with pytest.raises(SourceError):
        YFinanceSource(lambda s, a, b: pd.DataFrame()).fetch("GLD", "2020-01-01")


# ---------- EIA ----------


def _eia_page(rows, total):
    return FakeResponse(200, {"response": {"total": total, "data": rows}})


def test_eia_paginates_and_skips_nulls(monkeypatch):
    monkeypatch.setattr(eia_mod, "PAGE", 3)
    days = pd.bdate_range("2020-04-13", periods=7)
    rows = [{"period": str(d.date()), "value": str(20 + i)} for i, d in enumerate(days)]
    rows[1]["value"] = None
    s = FakeSession([_eia_page(rows[:3], 7), _eia_page(rows[3:6], 7), _eia_page(rows[6:], 7)])
    res = EIASource("KEY", session=s).fetch("RWTC", "2020-04-13")
    assert [c["params"]["offset"] for c in s.calls] == [0, 3, 6]
    assert res.n_requests == 3
    assert len(res.bars) == 6 and res.bars["close"].iloc[0] == 20.0


def test_eia_http_error_hides_key():
    s = FakeSession([FakeResponse(403, {"error": "bad key"})])
    with pytest.raises(SourceError) as e:
        EIASource("KEY123", session=s).fetch("RWTC", "2020-01-01")
    assert "KEY123" not in str(e.value)


# ---------- NBP ----------


def test_nbp_chunks_and_converts_to_usd_oz():
    def gold(url, params):
        if "cenyzlota/2020-01-02" in url:
            return FakeResponse(200, [{"data": "2020-01-02", "cena": 200.0}])
        return FakeResponse(404, "no data")

    def usd(url, params):
        if "rates/a/usd/2020-01-02" in url:
            return FakeResponse(200, {"rates": [{"effectiveDate": "2020-01-02", "mid": 4.0}]})
        return FakeResponse(404, "no data")

    # 2020-01-02 → 2020-06-30: 2 khúc 93 ngày cho mỗi chuỗi
    s = FakeSession([gold, gold, usd, usd])
    res = NBPSource(session=s).fetch_gold_usd_oz("2020-01-02", "2020-06-30")
    assert res.n_requests == 4
    assert res.bars["close"].iloc[0] == pytest.approx(200.0 * OZ_G / 4.0)

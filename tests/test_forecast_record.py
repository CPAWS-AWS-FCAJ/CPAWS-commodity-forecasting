"""Bản ghi Forecasts theo docs/api/contract.md, với số liệu mẫu WTI trong contract."""

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

from src.forecast import forecast_record as F
from src.forecast import returns as R

SAMPLE_Q = [-0.0325, -0.0251, -0.0122, 0.0004, 0.0131, 0.0258, 0.0334]  # contract.md, WTI h=1


def _quantiles():
    """7 h × 7 phân vị không giảm; hàng h=1 là mẫu trong contract, các h sau rộng dần."""
    base = np.array(SAMPLE_Q)
    return np.vstack([base * np.sqrt(h) for h in range(1, 8)])


def _record(**kw):
    args = {
        "asset": "wti",
        "base_date": "2026-10-14",
        "last_price": 71.32,
        "quantiles": _quantiles(),
        "fx_usd_vnd": 26310,
        "fx_date": "2026-10-14",
        "stale_sources": [],
        "roll_in_horizon": False,
        "model_version": "sample",
        "is_sample": True,
        "created_at": datetime(2026, 10, 15, 12, 40, 5, tzinfo=UTC),
    }
    args.update(kw)
    a = args.pop("asset"), args.pop("base_date"), args.pop("last_price"), args.pop("quantiles")
    return F.to_forecast_record(*a, **args)


def test_wti_contract_sample():
    rec = _record()
    assert rec["asset"] == "wti" and rec["target_series"] == "CL=F"
    assert rec["price_unit"] == "USD/bbl" and rec["base_date"] == "2026-10-14"
    assert rec["created_at"] == "2026-10-15T12:40:05Z"
    assert rec["quantile_levels"] == [
        Decimal(str(x)).quantize(Decimal("0.000001")) for x in R.QUANTILE_LEVELS
    ]
    assert len(rec["horizons"]) == 7 and [x["h"] for x in rec["horizons"]] == list(range(1, 8))
    h1 = rec["horizons"][0]
    assert h1["target_date"] == "2026-10-15"
    assert rec["horizons"][6]["target_date"] == "2026-10-23"  # 7 phiên CME sau 14/10
    assert h1["q"] == [Decimal(str(x)).quantize(Decimal("0.000001")) for x in SAMPLE_Q]
    assert round(float(h1["prob_up"]), 2) == 0.51
    prices = R.quantiles_to_prices(float(rec["last_price"]), [float(x) for x in h1["q"]])
    assert np.round(prices, 2).tolist() == [69.04, 69.55, 70.46, 71.35, 72.26, 73.18, 73.74]
    assert rec["fx_usd_vnd"] == Decimal("26310.000000") and rec["fx_date"] == "2026-10-14"
    assert (
        rec["stale_sources"] == [] and rec["roll_in_horizon"] is False and rec["is_sample"] is True
    )


def test_numbers_are_decimal_rounded_to_6_places():
    rec = _record(last_price=71.123456789)
    assert rec["last_price"] == Decimal("71.123457")
    for x in rec["horizons"]:
        for v in [*x["q"], x["prob_up"]]:
            assert isinstance(v, Decimal) and v.as_tuple().exponent == -6
        assert Decimal("0.05") <= x["prob_up"] <= Decimal("0.95")
    assert F.to_decimal(-1e-9) == Decimal("0.000000") and str(F.to_decimal(-1e-9)) == "0.000000"


def test_rejects_unnormalized_quantiles_and_bad_inputs():
    crossed = _quantiles()
    crossed[2, [2, 3]] = crossed[2, [3, 2]]
    with pytest.raises(ValueError, match="normalize_quantiles"):
        _record(quantiles=crossed)
    fixed, flags = R.normalize_quantiles(crossed)
    assert flags.tolist() == [False, False, True, False, False, False, False]
    assert _record(quantiles=fixed)["horizons"][2]["q"] == [
        F.to_decimal(v) for v in np.sort(crossed[2])
    ]
    with pytest.raises(ValueError):
        _record(quantiles=_quantiles()[:6])  # thiếu một h
    with pytest.raises(ValueError):
        _record(asset="copper")
    with pytest.raises(ValueError, match="not a CME session"):
        _record(base_date="2026-10-17")  # thứ Bảy
    with pytest.raises(ValueError):
        _record(asset="gold", roll_in_horizon=True)  # roll chỉ áp cho dầu
    with pytest.raises(ValueError):
        _record(created_at=datetime(2026, 10, 15, 12, 40))  # noqa: DTZ001 - cố ý thiếu múi giờ
    with pytest.raises(TypeError):
        _record(stale_sources="brent")


def test_target_series_units_and_calendars_per_asset():
    rec = _record(asset="gold", base_date="2026-10-16", last_price=2655.4)  # thứ Sáu, NYSE
    assert rec["target_series"] == "GLD" and rec["price_unit"] == "USD/oz"
    assert rec["horizons"][0]["target_date"] == "2026-10-19"
    assert _record(asset="silver", base_date="2026-10-16")["target_series"] == "SLV"
    brent = _record(asset="brent", roll_in_horizon=True, stale_sources=["brent"])
    assert brent["target_series"] == "BZ=F" and brent["roll_in_horizon"] is True
    assert brent["stale_sources"] == ["brent"]
    # Thanksgiving 26/11/2026: NYSE và CME đều nghỉ
    assert F.target_dates("gold", "2026-11-25", [1]) == ["2026-11-27"]

"""vol_scale_core (S1a dùng chung K3b và Lambda predict): giống từng bit K3b, hằng số bằng
configs/k3b.py, không rò rỉ, không kéo PyEMD/configs (docs/experiments/s1a-shadow-plan.md mục 10)."""

import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from configs import k3b as C
from src.data import calendars
from src.features.ceemdan_features import baseline_quantiles
from src.forecast import vol_scale_core as V
from src.forecast import vol_scaled
from tests.test_vol_scaled import GAP, _prices

ROOT = Path(__file__).resolve().parents[1]
LAM = C.S1_LAMBDA["S1a"]
# Từ trước khi EWMA khởi tạo (k NaN) tới vùng kẹp cả hai ngưỡng của dữ liệu giả
BASES = calendars.sessions("NYSE", "2012-11-01", "2014-12-30")[::7]


@pytest.mark.parametrize("how", ["clean", "missing_row", "rejected"])
def test_k_at_matches_k3b_vol_ratio_and_s1_quantiles_bitwise(how):
    """Mục 10.1: k_at và scale_quantiles của module mới = vol_ratio, s1_quantiles của K3b."""
    prices = _prices(drop=[GAP]) if how == "missing_row" else _prices()
    invalid = [GAP] if how == "rejected" else None
    vr = vol_scaled.vol_ratio(prices, "gold", BASES, LAM, invalid)
    got = np.array([V.k_at(prices, "gold", b, invalid) for b in BASES])
    assert np.isnan(got[:, 0]).any() and np.isfinite(got[:, 0]).sum() > 50
    np.testing.assert_array_equal(got[:, 0], vr.k)  # từng bit, NaN cùng chỗ
    np.testing.assert_array_equal(got[:, 1], vr.diag["sigma_short"].to_numpy())
    np.testing.assert_array_equal(got[:, 2], vr.diag["sigma_long"].to_numpy())
    assert (vr.k[vr.valid] == C.K_CLIP[0]).any() and (vr.k[vr.valid] == C.K_CLIP[1]).any()

    q, ok, _ = vol_scaled.s1_quantiles(prices, "gold", BASES, LAM, invalid)
    base_q, _ = baseline_quantiles(prices, "gold", BASES, invalid)
    assert ok.sum() > 50
    np.testing.assert_array_equal(V.scale_quantiles(base_q[ok], got[ok, 0]), q[ok])


def test_constants_equal_k3b_config():
    """Mục 10.2."""
    assert V.S1A_LAMBDA == C.S1_LAMBDA["S1a"]
    assert V.K_CLIP == C.K_CLIP
    assert V.SIGMA_LONG_WINDOW == C.SIGMA_LONG_WINDOW
    assert V.SIGMA_MIN_OBS == C.SIGMA_MIN_OBS
    assert V.EWMA_INIT_OBS == C.EWMA_INIT_OBS


def test_k_at_unchanged_when_future_is_appended():
    """Mục 10.4: k_t tại t chỉ dùng giá tới t."""
    cut = pd.Timestamp("2014-03-31")
    short, full = _prices(end=cut), _prices()
    for b in BASES[BASES <= cut]:
        a, f = V.k_at(short, "gold", b), V.k_at(full, "gold", b)
        np.testing.assert_array_equal(np.array(a), np.array(f))
    assert np.isfinite(V.k_at(short, "gold", cut)[0])


def test_k_at_nan_with_fewer_than_min_obs_returns():
    """Mục 10.7 (phần hàm): ít hơn SIGMA_MIN_OBS return hợp lệ → k NaN, không raise."""
    prices = _prices(end="2012-09-28")  # khoảng 186 phiên từ 3/1/2012
    k, sigma_short, sigma_long = V.k_at(prices, "gold", "2012-09-28")
    assert np.isnan(k) and np.isnan(sigma_short) and np.isnan(sigma_long)
    # ngày gốc không phải phiên của lịch → NaN
    assert np.isnan(V.k_at(_prices(), "gold", "2014-03-29")[0])  # thứ Bảy
    with pytest.raises(ValueError, match="naive"):
        V.k_at(prices, "gold", pd.Timestamp("2012-09-28", tz="UTC"))


def test_vol_scaled_reuses_core_and_core_needs_no_pyemd_or_configs():
    """Mục 10.10 và 3.1: K3b dùng đúng các hàm của core; core import được khi chặn PyEMD,
    configs, torch (như image predict)."""
    for name in ("daily_log_returns", "long_vol", "ewma_vol", "scale_quantiles"):
        assert getattr(vol_scaled, name) is getattr(V, name)
    code = textwrap.dedent(
        f"""
        import sys
        BLOCK = {{"PyEMD", "configs", "torch", "scipy", "sklearn", "statsmodels"}}

        class Blocker:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCK:
                    raise ImportError("blocked " + name)
                return None

        sys.meta_path.insert(0, Blocker())
        sys.path.insert(0, {str(ROOT)!r})
        import src.forecast.vol_scale_core
        import src.forecast.lambda_predict
        assert not BLOCK & {{m.split(".")[0] for m in sys.modules}}
        print("OK")
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert out.returncode == 0 and out.stdout.strip().endswith("OK"), out.stderr[-2000:]

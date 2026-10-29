"""K4 fhs_numpy: phương trình GJR, khớp arch, mô phỏng tất định theo seed, không import arch/scipy/
pandas. Chỉ dùng số giả."""

import hashlib
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from arch.univariate import GARCH

from configs import k4 as C
from src.features import ceemdan_cache as cc
from src.forecast import fhs_numpy as F
from src.forecast.returns import QUANTILE_LEVELS, normalize_quantiles

PARAMS = F.GjrParams(omega=0.02, alpha=0.03, gamma=0.08, beta=0.90, nu=7.0)


def _gjr_sample(n=600, seed=1, params=PARAMS):
    rng = np.random.default_rng(seed)
    z = rng.standard_t(7, n) / np.sqrt(7 / 5)
    x = np.empty(n)
    s2 = 1.0
    for t in range(n):
        x[t] = np.sqrt(s2) * z[t]
        s2 = F.next_variance(x[t], s2, params)
    return x


def test_module_imports_numpy_only():
    code = (
        "import sys; import src.forecast.fhs_numpy; "
        "print(','.join(m for m in ('arch', 'scipy', 'pandas') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""


def test_constants_match_returns_and_config():
    assert F.LEVELS == list(QUANTILE_LEVELS)
    assert (F.N_PATHS, F.N_STEPS) == (C.FHS_PATHS, C.FHS_STEPS)


def test_variance_path_follows_gjr_equation():
    x = np.array([0.5, -1.0, 2.0])
    backcast = 1.2
    w, a, g, b = PARAMS.omega, PARAMS.alpha, PARAMS.gamma, PARAMS.beta
    s0 = w + (a + g / 2 + b) * backcast
    s1 = w + a * 0.25 + b * s0  # ε_0 > 0: không có γ
    s2 = w + (a + g) * 1.0 + b * s1  # ε_1 < 0: có γ
    s3 = w + a * 4.0 + b * s2
    sigma2, nxt = F.variance_path(x, PARAMS, backcast)
    assert np.allclose(sigma2, [s0, s1, s2], rtol=1e-15, atol=0)
    assert np.allclose(nxt, [s1, s2, s3], rtol=1e-15, atol=0)
    assert PARAMS.persistence == pytest.approx(a + g / 2 + b)


def test_variance_path_matches_arch_recursion():
    x = _gjr_sample()
    vol = GARCH(p=1, o=1, q=1)
    backcast = vol.backcast(x)
    arch_params = np.array([PARAMS.omega, PARAMS.alpha, PARAMS.gamma, PARAMS.beta])
    expected = np.empty(len(x))
    vol.compute_variance(arch_params, x, expected, backcast, vol.variance_bounds(x))
    sigma2, _ = F.variance_path(x, PARAMS, backcast)
    assert np.max(np.abs(sigma2 / expected - 1)) < 1e-12


def test_simulation_with_one_residual_is_the_gjr_recursion():
    s2, c = 1.5, -0.7  # z* luôn bằng c
    paths = F.simulate_cumulative(s2, [c], PARAMS, np.random.default_rng(0), n_paths=3, n_steps=4)
    total, expected = 0.0, []
    for _ in range(4):
        eps = np.sqrt(s2) * c
        total += eps
        expected.append(total)
        s2 = PARAMS.omega + (PARAMS.alpha + PARAMS.gamma) * eps**2 + PARAMS.beta * s2
    assert np.allclose(paths, np.tile(expected, (3, 1)), rtol=1e-14, atol=0)


def test_quantiles_deterministic_by_seed_and_monotone_after_normalize():
    z = _gjr_sample(1000, seed=3) / 1.3
    seed = F.seed_for("gold", np.datetime64("2016-03-01"))
    kwargs = {"seed": seed, "scale": 100.0}
    q1 = F.fhs_quantiles(1.1, z, PARAMS, **kwargs)
    q2 = F.fhs_quantiles(1.1, z, PARAMS, **kwargs)
    q3 = F.fhs_quantiles(1.1, z, PARAMS, seed=seed + 1, scale=100.0)
    assert q1.shape == (7, 7) and np.array_equal(q1, q2) and not np.array_equal(q1, q3)
    normalized, crossed = normalize_quantiles(q1)
    assert not crossed.any() and (np.diff(normalized, axis=-1) >= 0).all()
    assert np.array_equal(normalized, q1)
    width = q1[:, 5] - q1[:, 1]
    assert (np.diff(width) > 0).all()  # dải 80% rộng dần theo h


# sha256 của fhs_quantiles (làm tròn 12 chữ số) tính ở commit d048bdc, trước khi có tùy chọn demean
GOLDEN_BEFORE_DEMEAN = "0df59d31a0f8ebefdf257711cbcf68f0b2f7eb08b6f793a7cdfc93598befa4a0"


def test_demean_false_reproduces_previous_output():
    z = np.random.default_rng(5).standard_t(6, 1000) / 1.2 + 0.03
    seed = F.seed_for("brent", "2017-06-01")
    q = F.fhs_quantiles(1.3, z, PARAMS, seed=seed, scale=100.0)
    assert np.array_equal(q, F.fhs_quantiles(1.3, z, PARAMS, seed=seed, scale=100.0, demean=False))
    assert hashlib.sha256(np.round(q, 12).tobytes()).hexdigest() == GOLDEN_BEFORE_DEMEAN


def test_demean_centres_bootstrap_draws_and_keeps_spread():
    z = np.random.default_rng(9).standard_t(6, 1000) / 1.2 + 0.2
    flat = F.GjrParams(omega=1.0, alpha=0.0, gamma=0.0, beta=0.0, nu=7.0)  # σ* = 1: ε* = z*
    for demean, centre in ((False, z.mean()), (True, 0.0)):
        rng = np.random.default_rng(1)
        paths = F.simulate_cumulative(1.0, z, flat, rng, n_paths=5000, n_steps=7, demean=demean)
        draws = np.diff(paths, axis=1, prepend=0.0)  # z* từng bước
        assert abs(draws.mean() - centre) < 0.02
        assert draws.std() == pytest.approx(z.std(), rel=0.03)
    # cùng chỉ số rút: bản dm đúng bằng bản gốc chạy trên z − mean(z)
    a = F.fhs_quantiles(1.1, z, PARAMS, seed=123, scale=100.0, demean=True)
    b = F.fhs_quantiles(1.1, z - z.mean(), PARAMS, seed=123, scale=100.0)
    assert np.array_equal(a, b)
    assert np.isclose(np.std(z - z.mean()), np.std(z), rtol=1e-12)
    # mean(z) > 0 ở đây: trừ trung bình kéo trung vị xuống ở mọi h
    assert (a[:, 3] < F.fhs_quantiles(1.1, z, PARAMS, seed=123, scale=100.0)[:, 3]).all()


def test_seed_matches_ceemdan_convention():
    for asset in ("gold", "brent"):
        for day in ("2016-01-04", "2018-12-31"):
            assert F.seed_for(asset, np.datetime64(day)) == cc.seed_id(asset, pd.Timestamp(day))
            assert F.seed_for(asset, day) == F.seed_for(asset, pd.Timestamp(day).to_datetime64())


@pytest.mark.parametrize(
    "values",
    [
        {"omega": 0.0},
        {"alpha": -0.01},
        {"beta": -0.1},
        {"alpha": 0.01, "gamma": -0.02},
        {"nu": float("nan")},
        {"nu": 2.0},  # mục 8 (29/10 tối): ν > 2
        {"nu": 1.5},
        {"alpha": 0.05, "gamma": 0.0, "beta": 0.95 + 2e-9},  # vượt 1 + 1e-9
        {"alpha": 0.1, "gamma": 0.1, "beta": 0.9},
    ],
)
def test_params_reject_invalid_variance(values):
    base = {"omega": 0.02, "alpha": 0.03, "gamma": 0.08, "beta": 0.9, "nu": 7.0}
    with pytest.raises(ValueError):
        F.GjrParams(**{**base, **values})


def test_params_accept_arch_boundary_solutions():
    """Nghiệm ở biên ràng buộc của arch (persistence trong [1, 1 + 1e-9]) vẫn nhận; như 11 lần fit
    của kiểm định chéo (gap tới −4,4e−11)."""
    for beta in (0.95, 0.95 + 4.4e-11, 0.95 + 9e-10):
        p = F.GjrParams(omega=0.02, alpha=0.0, gamma=0.1, beta=beta, nu=2.0 + 1e-12)
        assert p.persistence <= F.PERSISTENCE_MAX + F.PERSISTENCE_TOL
    assert (F.NU_MIN_EXCLUSIVE, F.PERSISTENCE_MAX, F.PERSISTENCE_TOL) == (
        C.NU_MIN_EXCLUSIVE,
        C.PERSISTENCE_MAX,
        C.PERSISTENCE_TOL,
    )


def test_inputs_are_validated():
    with pytest.raises(ValueError):
        F.variance_path([0.1, np.nan], PARAMS, 1.0)
    with pytest.raises(ValueError):
        F.variance_path([0.1], PARAMS, 0.0)
    with pytest.raises(ValueError):
        F.fhs_quantiles(0.0, [0.1], PARAMS, seed=1, scale=100.0)
    with pytest.raises(ValueError):
        F.fhs_quantiles(1.0, [], PARAMS, seed=1, scale=100.0)

"""K3b S2: đặc trưng năng lượng IMF không rò rỉ; mô hình neo mốc 252 phiên, parity torch–NumPy."""

import json

import numpy as np
import pandas as pd
import pytest
import torch

from src.data import calendars, storage
from src.features import ceemdan_cache as cc
from src.features.ceemdan_features import ColumnScaler, ceemdan_inputs, load_cache
from src.features.imf_energy import feature_names, log_energy, s2_features, s2_inputs
from src.forecast import run_k3b as R
from src.forecast.ceemdan_dlinear import DTYPE
from src.forecast.decomposition import CeemdanConfig
from src.forecast.dlinear import pinball_training_loss
from src.forecast.energy_width import EnergyWidth
from src.forecast.energy_width_numpy import EnergyWidthNumpy
from src.forecast.vol_scaled import vol_ratio

F = 5
CFG = CeemdanConfig(window=64, trials=5, epsilon=0.005, seed=7, keep_last=40)
K, L = 3, 10


@pytest.fixture(autouse=True)
def cpu_threads():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def _data(n=32, seed=0):
    rng = np.random.default_rng(seed)
    features = rng.normal(-8, 1.5, (n, F))
    baseline = np.sort(rng.normal(0, 0.02, (n, 7, 7)), axis=-1)
    return features, baseline


def _scaler(features):
    s = ColumnScaler.fit(features[:, None, :])
    return s, s.transform(features[:, None, :])[:, 0]


def _random_model(seed):
    torch.manual_seed(seed)
    model = EnergyWidth(F)
    with torch.no_grad():
        model.weight.normal_(0, 0.3)
        model.bias.normal_(0, 0.3)
    return model


def _torch(model, x, baseline):
    with torch.no_grad():
        return model(
            torch.as_tensor(x, dtype=DTYPE), torch.as_tensor(baseline, dtype=DTYPE)
        ).numpy()


# ---------- mô hình ----------


def test_initial_output_equals_baseline_q252():
    features, baseline = _data()
    scaler, x = _scaler(features)
    model = EnergyWidth(F)
    np.testing.assert_allclose(_torch(model, x, baseline), baseline, rtol=0, atol=1e-9)
    runtime = EnergyWidthNumpy([model.numpy_weights()] * 3, scaler.mean, scaler.std)
    np.testing.assert_allclose(runtime.predict(features, baseline), baseline, rtol=0, atol=1e-9)


def test_torch_numpy_parity_on_random_weights():
    features, baseline = _data(n=64, seed=4)
    scaler = ColumnScaler(np.linspace(-9, -7, F), np.linspace(0.5, 2.0, F))
    x = scaler.transform(features[:, None, :])[:, 0]
    models = [_random_model(s) for s in (7, 8, 9)]
    runtime = EnergyWidthNumpy([m.numpy_weights() for m in models], scaler.mean, scaler.std)
    expected = np.stack([_torch(m, x, baseline) for m in models])
    np.testing.assert_allclose(runtime.member_predict(features, baseline), expected, atol=1e-6)
    np.testing.assert_allclose(runtime.predict(features, baseline), expected.mean(0), atol=1e-6)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_median_is_baseline_and_quantiles_increase(seed):
    features, baseline = _data(seed=seed)
    scaler, x = _scaler(features)
    model = _random_model(seed)
    runtime = EnergyWidthNumpy([model.numpy_weights()], scaler.mean, scaler.std)
    strict = np.diff(baseline, axis=-1) > 0
    for q in (_torch(model, x, baseline), runtime.predict(features, baseline)):
        np.testing.assert_array_equal(q[..., 3], baseline[..., 3])  # Δm = 0
        gaps = np.diff(q, axis=-1)
        assert (gaps[strict] > 0).all() and (gaps >= 0).all()


def test_zero_init_has_gradient_and_rejects_bad_input():
    features, baseline = _data()
    model = EnergyWidth(F)
    x = torch.as_tensor(features, dtype=DTYPE)
    b = torch.as_tensor(baseline, dtype=DTYPE)
    loss = pinball_training_loss(model(x, b), torch.full((len(x), 7), 0.05, dtype=DTYPE))
    loss.backward()
    assert model.weight.grad.abs().sum() > 0 and model.bias.grad.abs().sum() > 0
    with pytest.raises(ValueError, match="nondecreasing"):
        model(x, b.flip(-1))
    with pytest.raises(ValueError, match="input must be"):
        model(x[:, :4], b)


def test_train_member_is_seeded_and_stops_on_nonfinite_loss():
    features, baseline = _data(n=100, seed=5)
    y = np.random.default_rng(5).normal(0, 0.02, (100, 7))
    _, x = _scaler(features)
    a, ha = R.train_member(x, baseline, y, seed=7, epochs=2)
    b, hb = R.train_member(x, baseline, y, seed=7, epochs=2)
    assert ha == hb and np.isfinite(ha["epoch_losses"]).all()
    np.testing.assert_array_equal(a.weight.detach(), b.weight.detach())
    with pytest.raises(R.StopRun, match="non-finite"):
        R.train_member(x, baseline, y, seed=7, epochs=1, learning_rate=1e300)


def test_artifact_round_trip_is_local_and_not_integration_eligible(tmp_path):
    features, baseline = _data(n=40, seed=6)
    scaler, _ = _scaler(features)
    models = [_random_model(s) for s in R.C.SEEDS]
    directory, manifest = R.export_artifact(
        models,
        [{"seed": s} for s in R.C.SEEDS],
        scaler,
        "2018-12-31",
        (features, baseline),
        asset="gold",
        model_root=tmp_path,
        provenance={"commit": None, "commit_dirty": None},
        audit={},
    )
    assert manifest["integration_eligible"] is False
    loaded = EnergyWidthNumpy.load(directory)
    expected = np.stack(
        [_torch(m, scaler.transform(features[:, None, :])[:, 0], baseline) for m in models]
    )
    np.testing.assert_allclose(loaded.member_predict(features, baseline), expected, atol=1e-12)
    with pytest.raises(FileExistsError):  # không ghi đè thư mục đã có
        R.export_artifact(
            models,
            [{"seed": s} for s in R.C.SEEDS],
            scaler,
            "2018-12-31",
            (features, baseline),
            asset="gold",
            model_root=tmp_path,
            provenance={"commit": None, "commit_dirty": None},
            audit={},
        )
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    config["seeds"] = [7]
    (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="config hash"):
        EnergyWidthNumpy.load(directory)


# ---------- đặc trưng ----------


def test_log_energy_and_feature_columns():
    X = np.zeros((3, 4, 2))
    X[0] = [[1.0, 0.1], [-1.0, 0.1], [2.0, -0.1], [0.0, 0.1]]
    X[1, :, 1] = 0.2  # cột 0 toàn 0 → −inf → dòng không hợp lệ
    X[2] = np.nan
    out = log_energy(X)
    assert out.shape == (3, 2)
    assert out[0, 0] == pytest.approx(np.log(6 / 4)) and out[0, 1] == pytest.approx(np.log(0.01))
    features, finite = s2_features(X, np.array([1.0, 1.0, 1.0]))
    assert features.shape == (3, 3) and finite.tolist() == [True, False, False]
    assert features[0, 2] == 0.0 and np.isnan(features[1:]).all()
    assert len(feature_names(3)) == F


def _prices(end="2014-06-30"):
    dates = calendars.sessions("NYSE", "2013-01-02", "2014-06-30")
    rng = np.random.default_rng(5)
    frame = pd.DataFrame(
        {
            "asset": "gold",
            "date": dates,
            "price": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates)))),
            "source": "yfinance",
            "published_at": (dates + pd.Timedelta(days=1, hours=12)).tz_localize("UTC"),
        }
    )
    return frame.loc[frame["date"] <= pd.Timestamp(end)].reset_index(drop=True)


def _cache(directory, prices, origins):
    st = storage.LocalStorage(directory)
    cc.ensure(st, prices, "gold", CFG, pd.DatetimeIndex(origins))
    return load_cache(st, "gold", CFG, origins.min(), origins.max())


def test_s2_features_at_t_do_not_change_when_future_is_appended(tmp_path):
    cut = pd.Timestamp("2014-03-31")
    origins = calendars.sessions("NYSE", "2014-03-03", "2014-04-30")
    base = origins[origins <= cut]
    full, short = _prices(), _prices(end=cut)
    cache_full = _cache(tmp_path / "full", full, origins)
    cache_short = _cache(tmp_path / "short", short, base)  # cache dựng chỉ từ dữ liệu ≤ cut
    kwargs = {"max_imf": K, "seq_len": L, "lam": 0.94}
    a = s2_inputs(short, "gold", cache_short, base, **kwargs)
    b = s2_inputs(full, "gold", cache_full, base, **kwargs)
    assert a.valid.all() and a.features.shape == (len(base), K + 2)
    np.testing.assert_array_equal(a.features, b.features)  # từng bit
    np.testing.assert_array_equal(a.valid, b.valid)
    # đúng công thức: log năng lượng của ceemdan_inputs, cột cuối log(σ_short/σ_long)
    inputs = ceemdan_inputs(full, "gold", cache_full, base, max_imf=K, seq_len=L)
    vr = vol_ratio(full, "gold", base, 0.94)
    np.testing.assert_array_equal(a.features[:, :-1], np.log(np.mean(inputs.X**2, axis=1)))
    np.testing.assert_array_equal(a.features[:, -1], np.log(vr.ratio))

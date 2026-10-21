"""DLinear architecture, leakage, artifacts and training smoke tests."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from src.data import calendars
from src.features.build import build_feature_frame, make_windows
from src.forecast import dlinear_data as D
from src.forecast.dlinear import DLinear, pinball_training_loss
from src.forecast.dlinear_data import InputScaler, prepare_training_data
from src.forecast.dlinear_numpy import DLinearNumpy
from src.forecast.returns import horizon_log_returns
from src.forecast.train_dlinear import export_artifact, train_model


@pytest.fixture(autouse=True)
def cpu_threads():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


@pytest.fixture(scope="module")
def prices():
    dates = calendars.sessions("NYSE", "2013-07-01", "2019-01-31")
    rng = np.random.default_rng(19)
    return pd.DataFrame(
        {
            "asset": "gold",
            "date": dates,
            "price": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates)))),
            "source": "yfinance",
            "published_at": (dates + pd.Timedelta(days=1, hours=12)).tz_localize("UTC"),
        }
    )


@pytest.fixture(scope="module")
def prepared(prices):
    return prepare_training_data(prices, None, "gold")


def test_model_shape_monotonic_gradient_and_pinball():
    torch.manual_seed(3)
    model = DLinear()
    x = torch.randn(8, 60, 1, requires_grad=True)
    q = model(x)
    assert q.shape == (8, 7, 7)
    assert torch.isfinite(q).all() and (q.diff(dim=-1) >= 0).all()
    loss = pinball_training_loss(q, torch.zeros(8, 7))
    loss.backward()
    assert torch.isfinite(x.grad).all()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())
    assert pinball_training_loss(torch.zeros(2, 7, 7), torch.ones(2, 7)) == 0.5


def test_centered_average_replicates_edges():
    x = torch.arange(60, dtype=torch.float32).reshape(1, 60, 1)
    trend, seasonal = DLinear.decompose(x)
    values = x.numpy().ravel()
    expected = np.convolve(np.pad(values, (12, 12), mode="edge"), np.ones(25) / 25, mode="valid")
    np.testing.assert_allclose(trend.numpy()[0], expected, atol=4e-6, rtol=0)
    np.testing.assert_allclose((trend + seasonal).numpy(), values[None, :])
    assert trend[0, 0] == pytest.approx(sum(range(13)) / 25)


def test_empirical_training_quantile_initialization(prepared):
    model = DLinear()
    model.initialize_from_targets(prepared.y)
    q = model(torch.zeros(1, 60, 1)).detach().numpy()[0]
    expected = np.quantile(prepared.y, [0.05, 0.10, 0.25, 0.5, 0.75, 0.9, 0.95], axis=0).T
    np.testing.assert_allclose(q, expected, atol=1e-6, rtol=0)


@pytest.mark.parametrize("shape", [(2, 59, 1), (2, 60, 2), (60, 1)])
def test_model_bad_shape(shape):
    with pytest.raises(ValueError):
        DLinear()(torch.zeros(shape))


def test_model_nan_rejected():
    with pytest.raises(ValueError):
        DLinear()(torch.full((1, 60, 1), float("nan")))


def test_training_data_complete_cases_cutoff_and_shared_window_cutter(prices, monkeypatch):
    called = []
    original = D.make_windows

    def spy(frame, dates, window):
        called.append((len(frame), len(dates), window))
        return original(frame, dates, window)

    monkeypatch.setattr(D, "make_windows", spy)
    data = prepare_training_data(prices, None, "gold")
    assert len(called) == 1 and called[0][2] == 60
    assert data.X.shape[1:] == (60, 1) and data.y.shape == (len(data.X), 7)
    assert np.isfinite(data.X).all() and np.isfinite(data.y).all()
    assert data.base_dates.min() >= np.datetime64("2014-01-01")
    assert data.target_dates.max() <= np.datetime64("2018-12-31")
    assert data.audit["n_valid"] + data.audit["n_excluded"] == data.audit["n_expected"]
    assert sum(data.audit["excluded_by_reason"].values()) == data.audit["n_excluded"]
    assert data.audit["excluded_by_reason"]["outside_training_target_cutoff"] == 7


def test_no_future_prices_targets_or_scaler_leakage(prices, prepared):
    changed = prices.copy()
    changed.loc[changed.date >= "2019-01-01", "price"] *= 1000
    other = prepare_training_data(changed, None, "gold")
    for name in ("X", "y", "base_dates", "target_dates"):
        np.testing.assert_array_equal(getattr(prepared, name), getattr(other, name))
    a, b = InputScaler.fit(prepared.X), InputScaler.fit(other.X)
    np.testing.assert_array_equal(a.mean, b.mean)
    np.testing.assert_array_equal(a.std, b.std)
    assert a.mean == pytest.approx(prepared.X.mean(axis=(0, 1)))
    assert a.std == pytest.approx(prepared.X.std(axis=(0, 1), ddof=0))


def test_window_at_origin_does_not_use_future(prices):
    date = pd.Timestamp("2016-06-10")
    a = make_windows(build_feature_frame(prices, "gold"), [date], 60)
    changed = prices.copy()
    changed.loc[changed.date > date, "price"] *= 100
    b = make_windows(build_feature_frame(changed, "gold"), [date], 60)
    np.testing.assert_array_equal(a.X, b.X)
    assert a.input_session_dates.max() <= date.to_datetime64()


def test_missing_session_and_rejected_asset_are_not_filled(prices, prepared):
    day = pd.Timestamp("2016-06-09")
    missing = prices.loc[prices.date != day]
    data = prepare_training_data(missing, None, "gold")
    assert pd.Timestamp("2016-06-10").to_datetime64() not in data.base_dates
    assert data.audit["n_valid"] < prepared.audit["n_valid"]
    rejected = pd.DataFrame({"date": [day], "asset": ["silver"]})
    unchanged = prepare_training_data(prices, rejected, "gold")
    np.testing.assert_array_equal(unchanged.X, prepared.X)
    rejected["asset"] = "gold"
    own = prepare_training_data(prices, rejected, "gold")
    assert pd.Timestamp("2016-06-10").to_datetime64() not in own.base_dates


def test_targets_follow_sessions_and_allow_missing_between_endpoints(prices):
    days = calendars.sessions("NYSE", "2016-06-09", "2016-06-15")
    p = pd.Series([100.0, 110.0, 121.0, 133.1, 146.41], index=days)
    p = p.drop(days[1])
    r = horizon_log_returns(p, 2, calendar="NYSE")
    assert r.loc[days[0]] == pytest.approx(np.log(1.21))
    assert days[2] - days[0] > pd.Timedelta(days=2)
    assert np.isnan(horizon_log_returns(p, 1, calendar="NYSE").loc[days[0]])


@pytest.mark.parametrize("kind", ["missing", "late"])
def test_missing_or_late_publication_never_accepted(prices, prepared, kind):
    prices = prices.copy()
    date = pd.Timestamp("2016-06-09")
    prices.loc[prices.date == date, "published_at"] = (
        pd.NaT if kind == "missing" else pd.Timestamp("2020-01-01", tz="UTC")
    )
    data = prepare_training_data(prices, None, "gold")
    assert date.to_datetime64() not in data.base_dates
    if kind == "missing":
        assert data.audit["excluded_by_reason"].get("invalid_input_window", 0) > 0
    else:
        assert data.audit["input_publication_failures"] > 0
    assert data.audit["n_valid"] < prepared.audit["n_valid"]


def test_constant_scaler_uses_unit_std():
    scaler = InputScaler.fit(np.full((2, 60, 1), 2.0))
    assert scaler.std[0] == 1
    assert not scaler.transform(np.full((2, 60, 1), 2.0)).any()


@pytest.fixture
def artifact(tmp_path, prepared):
    model, scaler, losses = train_model(prepared, epochs=2, batch_size=256, seed=19, device="cpu")
    directory, manifest = export_artifact(
        model,
        scaler,
        prepared,
        tmp_path,
        asset="gold",
        model_version="smoke-v1",
        training_settings={"epochs": 2, "seed": 19},
    )
    return directory, model, scaler, losses, manifest


def test_end_to_end_train_export_reload_parity_and_no_overwrite(artifact, prepared):
    directory, model, scaler, losses, manifest = artifact
    assert len(losses) == 2 and np.isfinite(losses).all()
    runtime = DLinearNumpy.load(directory)
    expected = model(torch.from_numpy(scaler.transform(prepared.X[:16]))).detach().numpy()
    actual = runtime.predict(prepared.X[:16])
    np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=0)
    assert (np.diff(actual, axis=-1) >= 0).all()
    assert manifest["commit"] is None and manifest["missing_metadata"] == ["commit"]
    assert not manifest["integration_eligible"]
    assert pd.Timestamp(manifest["trained_at"]).year >= 2026
    with pytest.raises(FileExistsError):
        export_artifact(
            model, scaler, prepared, directory.parent.parent, asset="gold", model_version="smoke-v1"
        )


def test_training_seed_reproducible(prepared):
    a, _sa, ha = train_model(prepared, epochs=1, batch_size=256, seed=19, device="cpu")
    b, _sb, hb = train_model(prepared, epochs=1, batch_size=256, seed=19, device="cpu")
    assert ha == hb
    for key in a.state_dict():
        np.testing.assert_array_equal(a.state_dict()[key], b.state_dict()[key])


def test_numpy_runtime_import_and_predict_without_training_packages(artifact):
    directory = artifact[0]
    script = """
import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','scipy','PyEMD','pandas','pyarrow'}:
            raise ImportError('blocked training dependency '+fullname)
sys.meta_path.insert(0,Block())
from src.forecast.dlinear_numpy import DLinearNumpy
import numpy as np
result=DLinearNumpy.load(sys.argv[1]).predict(np.zeros((2,60,1)))
assert result.shape==(2,7,7)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(directory)],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )


@pytest.mark.parametrize("filename", ["config.json", "scaler.json", "weights.npz", "manifest.json"])
def test_missing_artifact_is_clear_error(artifact, filename):
    directory = artifact[0]
    (directory / filename).unlink()
    with pytest.raises(ValueError):
        DLinearNumpy.load(directory)


def test_invalid_config_and_corrupt_artifact_rejected(artifact):
    directory = artifact[0]
    p = directory / "config.json"
    config = json.loads(p.read_text())
    config["kernel"] = 3
    p.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="config"):
        DLinearNumpy.load(directory)


def test_numpy_random_weights_match_torch(prepared):
    torch.manual_seed(31)
    model = DLinear().eval()
    scaler = InputScaler.fit(prepared.X)
    weights = {k.replace(".", "_"): v.detach().numpy() for k, v in model.state_dict().items()}
    x = prepared.X[:32]
    expected = model(torch.from_numpy(scaler.transform(x))).detach().numpy()
    actual = DLinearNumpy(weights, scaler.mean, scaler.std).predict(x)
    np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=0)


@pytest.mark.parametrize("filename", ["weights.npz", "scaler.json"])
def test_artifact_corruption_detected_by_hash(artifact, filename):
    directory = artifact[0]
    with (directory / filename).open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        DLinearNumpy.load(directory)


def test_non_object_config_rejected(artifact):
    directory = artifact[0]
    (directory / "config.json").write_text("[]")
    with pytest.raises(ValueError, match="objects"):
        DLinearNumpy.load(directory)


def test_numpy_invalid_weights_and_scaler_are_rejected():
    weights = {
        "trend_weight": np.zeros((49, 60), np.float32),
        "trend_bias": np.zeros(49, np.float32),
        "seasonal_weight": np.zeros((49, 60), np.float32),
        "seasonal_bias": np.zeros(49, np.float32),
    }
    with pytest.raises(ValueError, match="scaler"):
        DLinearNumpy(weights, [0], [0])
    weights["trend_bias"][0] = np.nan
    with pytest.raises(ValueError, match="weight"):
        DLinearNumpy(weights, [0], [1])

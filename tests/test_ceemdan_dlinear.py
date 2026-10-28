"""CEEMDAN-DLinear K3: neo vào mốc 252 phiên, phân vị tăng dần, parity torch–NumPy, artifact."""

import json

import numpy as np
import pytest
import torch

from src.features.ceemdan_features import ColumnScaler
from src.forecast import train_ceemdan as T
from src.forecast.ceemdan_dlinear import DTYPE, CeemdanDLinear
from src.forecast.ceemdan_dlinear_numpy import CeemdanDLinearNumpy
from src.forecast.dlinear import pinball_training_loss

L, C = 30, 5


@pytest.fixture(autouse=True)
def cpu_threads():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def _data(n=32, seed=0):
    rng = np.random.default_rng(seed)
    features = rng.normal(0, 0.02, (n, L, C))
    baseline = np.sort(rng.normal(0, 0.02, (n, 7, 7)), axis=-1)
    return features, baseline


def _random_model(seed):
    torch.manual_seed(seed)
    model = CeemdanDLinear(L, C)
    with torch.no_grad():
        model.shared_weight.normal_(0, 0.3)
        model.column_weight.normal_(0, 1.0)
        model.bias.normal_(0, 0.5)
    return model


def _torch(model, x, baseline):
    with torch.no_grad():
        return model(
            torch.as_tensor(x, dtype=DTYPE), torch.as_tensor(baseline, dtype=DTYPE)
        ).numpy()


def test_initial_output_equals_baseline_q252():
    features, baseline = _data()
    scaler = ColumnScaler.fit(features)
    model = CeemdanDLinear(L, C)
    np.testing.assert_allclose(
        _torch(model, scaler.transform(features), baseline), baseline, rtol=0, atol=1e-9
    )
    runtime = CeemdanDLinearNumpy([model.numpy_weights()] * 3, scaler.mean, scaler.std)
    np.testing.assert_allclose(runtime.predict(features, baseline), baseline, rtol=0, atol=1e-9)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_quantiles_always_increase(seed):
    features, baseline = _data(seed=seed)
    baseline[0, 2, 3:5] = baseline[0, 2, 3]  # khoảng cách 0 ở mốc vẫn giữ không giảm
    scaler = ColumnScaler.fit(features)
    model = _random_model(seed)
    runtime = CeemdanDLinearNumpy([model.numpy_weights()], scaler.mean, scaler.std)
    strict = np.diff(baseline, axis=-1) > 0
    for scale in (1, 50):  # 50: input lớn bất thường, exp(Δg) có thể tràn dưới về 0
        q_torch = _torch(model, scaler.transform(features * scale), baseline)
        for q in (q_torch, runtime.predict(features * scale, baseline)):
            assert np.isfinite(q).all()
            gaps = np.diff(q, axis=-1)
            assert (gaps >= 0).all()
            if scale == 1:
                assert (gaps[strict] > 0).all()  # tăng thật khi mốc tăng thật


def test_torch_numpy_parity_on_random_weights():
    features, baseline = _data(n=64, seed=4)
    scaler = ColumnScaler(np.linspace(-0.01, 0.01, C), np.linspace(0.5, 2.0, C))
    models = [_random_model(s) for s in (7, 8, 9)]
    runtime = CeemdanDLinearNumpy([m.numpy_weights() for m in models], scaler.mean, scaler.std)
    expected = np.stack([_torch(m, scaler.transform(features), baseline) for m in models])
    np.testing.assert_allclose(runtime.member_predict(features, baseline), expected, atol=1e-6)
    np.testing.assert_allclose(runtime.predict(features, baseline), expected.mean(0), atol=1e-6)


def test_zero_init_still_has_gradient_and_rejects_bad_baseline():
    features, baseline = _data()
    model = CeemdanDLinear(L, C)
    x = torch.as_tensor(features, dtype=DTYPE)
    b = torch.as_tensor(baseline, dtype=DTYPE)
    loss = pinball_training_loss(model(x, b), torch.full((len(x), 7), 0.03, dtype=DTYPE))
    loss.backward()
    assert model.bias.grad.abs().sum() > 0 and model.shared_weight.grad.abs().sum() > 0
    with pytest.raises(ValueError, match="nondecreasing"):
        model(x, b.flip(-1))


def test_train_member_is_seeded_and_finite():
    features, baseline = _data(n=100, seed=5)
    y = np.random.default_rng(5).normal(0, 0.02, (100, 7))
    a, ha = T.train_member(features, baseline, y, seed=7, epochs=2)
    b, hb = T.train_member(features, baseline, y, seed=7, epochs=2)
    assert ha == hb and np.isfinite(ha["epoch_losses"]).all()
    np.testing.assert_array_equal(a.shared_weight.detach(), b.shared_weight.detach())
    with pytest.raises(T.StopRun, match="non-finite"):
        T.train_member(features, baseline, y, seed=7, epochs=1, learning_rate=1e300)


def test_artifact_round_trip_is_local_and_not_integration_eligible(tmp_path):
    features, baseline = _data(n=40, seed=6)
    scaler = ColumnScaler.fit(features)
    models = [_random_model(s) for s in T.G.SEEDS]

    class Train:  # chỉ các trường export_artifact đọc
        valid = np.ones(40, dtype=bool)
        target_dates = np.full((40, 7), np.datetime64("2018-12-31"))

    directory, manifest = T.export_artifact(
        models,
        [{"seed": s} for s in T.G.SEEDS],
        scaler,
        Train,
        (features, baseline),
        asset="gold",
        window=252,
        max_imf=C - 1,
        seq_len=L,
        model_root=tmp_path,
        provenance={"commit": "abc", "commit_dirty": True},
        audit={},
    )
    assert manifest["integration_eligible"] is False
    assert manifest["ceemdan_cfg_hash"] == T.G.EXPECTED_CFG_HASH
    loaded = CeemdanDLinearNumpy.load(directory)
    expected = np.stack([_torch(m, scaler.transform(features), baseline) for m in models])
    np.testing.assert_allclose(loaded.member_predict(features, baseline), expected, atol=1e-12)
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    config["seq_len"] = 60
    (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="config hash"):
        CeemdanDLinearNumpy.load(directory)
    with pytest.raises(FileExistsError):  # không ghi đè artifact đã có
        T.export_artifact(
            models,
            [{"seed": s} for s in T.G.SEEDS],
            scaler,
            Train,
            (features, baseline),
            asset="gold",
            window=252,
            max_imf=C - 1,
            seq_len=L,
            model_root=tmp_path,
            provenance={"commit": "abc", "commit_dirty": True},
            audit={},
        )


def test_selection_rule_breaks_ties_by_smaller_config():
    def s(w, k, l_, m):
        return {"window": w, "max_imf": k, "seq_len": l_, "mean_28": m}

    scores = {
        "w504-k4-l30": s(504, 4, 30, 0.0105),
        "w252-k4-l60": s(252, 4, 60, 0.0100),  # hòa (chênh 0,05 điểm %), nhỏ hơn theo window
        "w252-k3-l30": s(252, 3, 30, 0.0080),  # chênh 0,25 điểm %: không hòa
    }
    assert T.select_config(scores) == ("w252-k4-l60", ["w504-k4-l30", "w252-k4-l60"])
    scores["w252-k4-l60"]["mean_28"] = 0.0090
    assert T.select_config(scores)[0] == "w504-k4-l30"

"""K3b run_k3b trên giá GIẢ (không đọc lake): đường S2 đầy đủ, CI trung bình 7 h, quy tắc chọn,
đọc mốc K3 chỉ đọc, báo cáo Markdown. Không chạy trên dữ liệu 2019 thật."""

import json

import numpy as np
import pandas as pd
import pytest

from configs import k3b as C
from src.data import calendars, storage
from src.data.config import ASSETS
from src.eval import walk_forward as wf
from src.features import ceemdan_cache as cc
from src.features.ceemdan_features import baseline_quantiles, load_cache
from src.forecast import run_k3b as R
from src.forecast import train_ceemdan as T
from src.forecast.decomposition import CeemdanConfig
from src.forecast.energy_width_numpy import EnergyWidthNumpy


def _fake_prices():
    frames = []
    for i, asset in enumerate(C.ASSETS):
        dates = calendars.sessions(ASSETS[asset].calendar, "2017-01-03", "2019-12-31")
        rng = np.random.default_rng(i)
        sd = 0.01 * (1 + 0.6 * np.sin(np.arange(len(dates)) / 40))  # biến động theo cụm
        frames.append(
            pd.DataFrame(
                {
                    "asset": asset,
                    "date": dates,
                    "price": 50 * np.exp(np.cumsum(rng.normal(0, 1, len(dates)) * sd)),
                    "source": ASSETS[asset].primary.source,
                    "published_at": [wf.publication_time(asset, str(d.date())) for d in dates],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def evaluated():
    prices = _fake_prices()
    rejected = pd.DataFrame(
        {"asset": pd.Series(dtype=str), "date": pd.Series(dtype="datetime64[ns]")}
    )
    invalid = {a: [] for a in C.ASSETS}
    sessions = {
        a: {
            "train": calendars.sessions(ASSETS[a].calendar, *C.TRAIN),
            "val": calendars.sessions(ASSETS[a].calendar, *C.VALID),
        }
        for a in C.ASSETS
    }
    s1 = R.run_s1("S1a", {"prices": prices, "invalid": invalid, "sessions": sessions})
    common = {}
    for asset, (base, _, _) in s1["forecasts"].items():
        full = calendars.sessions(ASSETS[asset].calendar)
        last = full[full.get_indexer(base) + 7]
        common[asset] = pd.DatetimeIndex(base[last <= pd.Timestamp(C.VALID[1])])
    models = {"S1a": s1["forecasts"], R.BASELINE: T.baseline_forecasts(prices, invalid, common)}
    p, r = wf._inputs(prices, rejected, T.evaluation_config("inputs"))
    return s1, common, R.evaluate_set(models, common, p, r)


def test_mean7_ci_uses_shared_plan_and_matches_accuracy(evaluated):
    s1, common, named = evaluated
    base = named[R.BASELINE]["mean7"]
    assert len(base) == 6  # 4 tài sản all + 2 dầu excl_roll
    assert (base[["value", "ci_low", "ci_high"]].abs().to_numpy() < 1e-12).all()
    m = named["S1a"]["mean7"]
    assert (m["n_replicates"] == 1000).all()
    assert (m["ci_low"] <= m["value"]).all() and (m["value"] <= m["ci_high"]).all()
    assert (m["ci_low"] < m["ci_high"]).all()
    gold = m[m["asset"] == "gold"].iloc[0]
    assert gold["n_obs"] == [len(common["gold"])] * 7
    m28, _ = T.mean_skill(named["S1a"]["accuracy"])
    assert np.isfinite(m28)
    assert len(R.mean7_table(named, ["S1a", R.BASELINE])) == 12
    assert len(R.hit_table(named, ["S1a"])) == 42
    stats = R.k_summary(s1["k"]["gold"]["val"])
    assert C.K_CLIP[0] <= stats["min"] <= stats["median"] <= stats["max"] <= C.K_CLIP[1]


def test_restrict_stops_when_common_origin_is_missing(evaluated):
    s1, common, _ = evaluated
    shifted = {a: v.append(pd.DatetimeIndex(["2020-01-02"])) for a, v in common.items()}
    with pytest.raises(R.StopRun, match="missing on common origins"):
        R.restrict(s1["forecasts"], shifted)


def test_select_candidate_tie_prefers_simpler():
    assert R.select_candidate({"S1a": 0.0100, "S1b": 0.0105, "S2": 0.0050}) == (
        "S1a",
        ["S1a", "S1b"],
    )
    assert R.select_candidate({"S1a": 0.0, "S1b": 0.0020, "S2": 0.0025})[0] == "S1b"
    assert R.select_candidate({"S1a": -0.02, "S1b": -0.03, "S2": -0.001})[0] == "S2"


def _fake_k3_dir(tmp_path, commit=C.K3_COMMIT):
    configs = ["w252-k3-l30", "w252-k3-l60", "w252-k4-l30", "w252-k4-l60"]
    configs += ["w504-k4-l30", "w504-k4-l60", "w504-k5-l30", "w504-k5-l60"]
    rows = []
    for asset in C.ASSETS:
        val = calendars.sessions(ASSETS[asset].calendar, *C.VALID)
        for cid in configs:
            n = C.K3_COMMON_N[asset] + (5 if cid.endswith("l30") else 0)
            for member in ("7", "mean"):
                for d in val[:n]:
                    for h in C.HORIZONS:
                        q = np.linspace(-0.02, 0.02, 7) * h
                        rows.append(
                            {
                                "config_id": cid,
                                "asset": asset,
                                "member": member,
                                "base_date": d,
                                "h": h,
                                **dict(zip(wf.QCOLS, q, strict=True)),
                                "crossed_raw": False if member == "mean" else None,
                            }
                        )
    pd.DataFrame(rows).to_parquet(tmp_path / "forecasts_val2019.parquet", index=False)
    summary = {
        "provenance": {"commit": commit, "commit_dirty": False},
        "selected": C.K3_CONFIG_ID,
        "common_origins": C.K3_COMMON_N,
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return tmp_path


def test_k3_reference_reads_selected_config_and_common_set(tmp_path):
    forecasts, common = R.k3_reference(_fake_k3_dir(tmp_path))
    for asset in C.ASSETS:
        base, q, crossed = forecasts[asset]
        assert len(common[asset]) == C.K3_COMMON_N[asset]
        assert len(base) == C.K3_COMMON_N[asset] + 5 and common[asset].isin(base).all()
        assert q.shape == (len(base), 7, 7) and crossed.shape == (len(base), 7)
        np.testing.assert_allclose(q[0, 2], np.linspace(-0.02, 0.02, 7) * 3)


def test_k3_reference_rejects_other_run(tmp_path):
    with pytest.raises(R.StopRun, match="not the clean K3 run"):
        R.k3_reference(_fake_k3_dir(tmp_path, commit="59384e48d04abd86bab1737ec7221f5a0be9ee89"))


def test_render_writes_every_section(evaluated):
    _, common, named = evaluated
    alias = {name: named["S1a"] for name in (*C.CANDIDATES, R.K3_NAME)}
    sets = {"common": {**alias, R.BASELINE: named[R.BASELINE]}}
    sets["k3_common"] = sets["common"]
    m28, by_asset = T.mean_skill(named["S1a"]["accuracy"])
    scores = {name: {"mean_28": m28, "by_asset": by_asset} for name in sets["common"]}
    stats = R.k_summary([0.5, 1.0, 2.0])
    seed = {"seed": 7, "initial_loss": 0.01, "epoch_losses": [0.009]}
    summary = {
        "run_id": "fake",
        "look_number": C.LOOK_NUMBER,
        "total_configs_seen_on_2019": C.TOTAL_CONFIGS_SEEN,
        "selected": "S1a",
        "tied_with_best": ["S1a", "S1b", "S2"],
        "selected_on_k3_common": "S1a",
        "common_origins": {a: len(v) for a, v in common.items()},
        "k3_common_origins": {a: len(v) for a, v in common.items()},
        "scores": {"common": scores, "k3_common": scores},
        "k_distribution": {"S1a": {"gold": {"train": stats, "val_common": stats}}},
        "s2": {
            "gold": {
                "seeds": [seed],
                "parity_max_abs_error": 0.0,
                "val_width80_ratio_to_baseline": stats,
            }
        },
        "seconds": {"total": 1.0},
    }
    text = R.render(summary, sets)
    assert "Lần nhìn thứ 2" in text and "tổng 11 cấu hình" in text
    for heading in ("tập K3", "quantile_hit_rates", "## DM", "Phân bố k_t", "S2: huấn luyện"):
        assert heading in text


def test_run_s2_trains_exports_and_keeps_median(tmp_path, monkeypatch):
    """Đường S2 đầy đủ trên một tài sản giả với cache CEEMDAN nhỏ: đếm mẫu, scaler, 3 seed,
    artifact (parity, không integration), dự báo validation có trung vị = mốc."""
    cfg = CeemdanConfig(window=64, trials=5, epsilon=0.005, seed=7, keep_last=40)
    dates = calendars.sessions("NYSE", "2013-01-02", "2014-07-31")
    rng = np.random.default_rng(3)
    prices = pd.DataFrame(
        {
            "asset": "gold",
            "date": dates,
            "price": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates)))),
            "source": "yfinance",
            "published_at": (dates + pd.Timedelta(days=1, hours=12)).tz_localize("UTC"),
        }
    )
    train = calendars.sessions("NYSE", "2014-02-03", "2014-04-30")
    val = calendars.sessions("NYSE", "2014-05-01", "2014-05-30")
    st = storage.LocalStorage(str(tmp_path / "lake"))
    cc.ensure(st, prices, "gold", cfg, train.append(val))
    cache = load_cache(st, "gold", cfg, train.min(), val.max())
    monkeypatch.setattr(C, "ASSETS", ["gold"])
    monkeypatch.setattr(C, "S2_EXPECTED_N", {"gold": (len(train), len(val))})
    monkeypatch.setattr(C, "EPOCHS", 2)
    # cửa sổ 64 trên giá giả đôi khi chỉ có 2 IMF (cột IMF3 = 0 → log năng lượng −inf, ngày gốc
    # bị loại); K = 2 để đếm mẫu bằng quy tắc A. Dữ liệu thật dùng K = 3 (C.S2_MAX_IMF).
    monkeypatch.setattr(C, "S2_MAX_IMF", 2)
    ctx = {
        "prices": prices,
        "cache": {"gold": cache},
        "invalid": {"gold": []},
        "sessions": {"gold": {"train": train, "val": val}},
        "model_root": tmp_path / "models",
        "provenance": {"commit": None, "commit_dirty": None},
    }
    out = R.run_s2(ctx)
    base, q, crossed = out["forecasts"]["gold"]
    assert len(base) == len(val) and q.shape == (len(val), 7, 7) and not crossed.any()
    info = out["assets"]["gold"]
    assert len(info["seeds"]) == 3 and info["parity_max_abs_error"] <= R.PARITY_ATOL
    directory = tmp_path / "models" / "gold" / info["model_version"]
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["integration_eligible"] is False
    assert len(EnergyWidthNumpy.load(directory).mean) == 2 + 2  # K+1 log năng lượng + log σ
    baseline, _ = baseline_quantiles(prices, "gold", base)
    np.testing.assert_allclose(q[..., 3], baseline[..., 3], rtol=0, atol=1e-15)
    monkeypatch.setattr(C, "S2_MAX_IMF", 3)  # có ngày gốc n_imf < 3 → dừng, nói rõ lý do
    with pytest.raises(R.StopRun, match="n_imf_below_k': [1-9]"):
        R.run_s2({**ctx, "model_root": tmp_path / "other"})

"""K4 run_k4 trên giá GIẢ (không đọc lake thật): bốn mô hình, combo, tập chung kiểu mục 8, đánh giá
cấu hình cross_validation, MCS, quy tắc chọn, mốc cắt 2018-12-31, chặn cache CEEMDAN, phần chặn
val2019. Không chạy trên dữ liệu thật."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from configs import k4 as C
from src.data import calendars
from src.data.config import ASSETS
from src.eval import walk_forward as wf
from src.forecast import run_k4 as R
from src.forecast import train_ceemdan as T

ROOT = Path(__file__).resolve().parents[1]
BRENT_GAPS = slice(300, 400, 5)  # 20 phiên Brent thiếu năm 2013: chưa đủ 1000 return đầu 2016


def _fake_prices(end="2019-03-29"):
    frames = []
    for i, asset in enumerate(C.ASSETS):
        dates = calendars.sessions(ASSETS[asset].calendar, "2012-01-03", end)
        rng = np.random.default_rng(i)
        sd = 0.01 * (1 + 0.6 * np.sin(np.arange(len(dates)) / 40))  # biến động theo cụm
        frame = pd.DataFrame(
            {
                "asset": asset,
                "date": dates,
                "price": 50 * np.exp(np.cumsum(rng.normal(0, 1, len(dates)) * sd)),
                "source": ASSETS[asset].primary.source,
                "published_at": [wf.publication_time(asset, str(d.date())) for d in dates],
            }
        )
        if asset == "brent":
            frame = frame.drop(index=frame.index[BRENT_GAPS])
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _expected_common(prices):
    """Mọi ngày gốc CV hợp lệ, trừ các tháng FHS chưa có 1000 return trước đầu tháng."""
    out = {}
    for asset in C.ASSETS:
        r = R.asset_returns(prices, asset, [])
        base = calendars.sessions(ASSETS[asset].calendar, *C.CV)
        first = next(
            m
            for m in pd.date_range(*C.CV, freq="MS")
            if r[r.index < m].notna().sum() >= C.FHS_WINDOW
        )
        out[asset] = int((base >= first).sum())
    return out


@pytest.fixture(scope="module")
def built():
    prices = _fake_prices()
    cut = prices[prices["date"] <= C.CV_CUTOFF].reset_index(drop=True)
    invalid = {a: [] for a in C.ASSETS}
    expected = _expected_common(cut)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "CV_EXPECTED_N", expected)
        calls = []
        original = R.normalize_quantiles

        def counting(q):
            calls.append(q.shape)
            return original(q)

        mp.setattr(R, "normalize_quantiles", counting)
        with R.no_ceemdan_cache():  # đường chạy không đọc cache CEEMDAN nào
            out = R.build_cv(cut, invalid)
    return cut, out, expected, calls


def test_common_set_follows_section_8(built):
    _, out, expected, _ = built
    assert {a: len(v) for a, v in out["common"].items()} == expected
    v = out["validity"]
    assert v["gold"]["fhs_valid"] == v["gold"]["origins"] == 754
    assert v["wti"]["common"] == 755
    assert v["brent"]["fhs_valid"] < v["brent"]["origins"]  # thiếu 1000 return đầu 2016
    assert pd.Timestamp(v["brent"]["first_common"]) >= pd.Timestamp("2016-02-01")
    months = pd.DataFrame(out["fits"])
    brent = months[months.asset == "brent"]
    assert (brent.status.iloc[:1] == "insufficient_history").all()
    assert set(brent.status.iloc[-30:]) <= {"ok", "not_converged", "fit_error"}


def test_combo_is_mean_of_three_then_normalized_once(built):
    _, out, _, calls = built
    assert len(calls) == len(R.MODELS) * len(C.ASSETS)  # đúng một lần mỗi mô hình × tài sản
    f = out["forecasts"]
    for asset in C.ASSETS:
        b, s, h = (f[m][asset][1] for m in (C.BASELINE, C.S1A, C.FHS))
        combo = f[C.COMBO][asset][1]
        # q252, S1a, FHS vốn không cắt nhau nên normalize không đổi gì; trung bình cũng không cắt
        assert np.array_equal(combo, np.sort((b + s + h) / 3.0, axis=-1))
        assert np.allclose(combo, (b + s + h) / 3.0, rtol=0, atol=1e-15)
        for m in R.MODELS:
            q = f[m][asset][1]
            assert (np.diff(q, axis=-1) >= 0).all() and np.isfinite(q).all()
            assert f[m][asset][0].equals(out["common"][asset])


def test_single_forecast_timing_recorded(built):
    _, out, _, _ = built
    single = out["seconds"]["single_forecast"]
    assert set(single) == set(C.ASSETS) and all(0 < s < 5 for s in single.values())


@pytest.fixture(scope="module")
def evaluated(built):
    cut, out, _, _ = built
    origins = {a: v[::8] for a, v in out["common"].items()}
    rejected = pd.DataFrame({"asset": pd.Series(dtype=str), "date": pd.Series(dtype=str)})
    p, r = wf._inputs(cut, rejected, R.cv_config("inputs"))
    # một mô hình: _make_detail duyệt mọi ngày gốc CV nên mỗi lần đánh giá mất gần một phút
    named = R.R3.evaluate_set({C.FHS: out["forecasts"][C.FHS]}, origins, p, r, config=R.cv_config)
    return out, origins, named


def test_cv_evaluation_uses_cross_validation_period(evaluated):
    out, _, named = evaluated
    d = named[C.FHS]["detail"]
    used = d[d.common_mask_all.fillna(False).astype(bool)]
    # mốc neo q252 của K4 trùng mốc 252 phiên mà walk_forward dùng để chấm
    base, q, _ = out["forecasts"][C.BASELINE]["gold"]
    gold = used[used.asset == "gold"]
    pos = pd.DatetimeIndex(base).get_indexer(pd.to_datetime(gold.base_date))
    expected = q[pos, gold.h.to_numpy() - 1]
    assert np.allclose(gold[list(wf.BCOLS)].to_numpy(float), expected, rtol=0, atol=1e-12)
    acc = named[C.FHS]["accuracy"]
    assert set(acc.evaluation_kind) == {"cross_validation"}
    assert set(acc.evaluation_start) == {"2016-01-01"} and set(acc.target_cutoff_date) == {
        "2018-12-31"
    }
    assert pd.to_datetime(used.target_date).max() <= pd.Timestamp("2018-12-31")
    assert set(used.base_date.str[:4]) == {"2016", "2017", "2018"}
    oil = d[d.asset.isin(["brent", "wti"]) & d.roll_in_horizon.fillna(False).astype(bool)]
    assert set(oil.base_date.str[:4]) == {"2016", "2017", "2018"}  # ngày roll 2016–2018
    m = named[C.FHS]["mean7"]
    assert len(m) == 6 and (m.n_replicates == 1000).all()
    m28, _ = T.mean_skill(acc)
    groups = [(a, h) for a in C.ASSETS for h in C.HORIZONS]
    ci = R.R3.groups_skill_ci(d, groups, "all", R.cv_config(C.FHS))
    assert ci["value"] == pytest.approx(m28, abs=1e-12)
    assert ci["ci_low"] <= ci["value"] <= ci["ci_high"]


def test_mcs_per_asset_on_full_horizon_origins(evaluated):
    _, origins, named = evaluated
    d = named[C.FHS]["detail"]
    three = {  # mốc lấy đúng loss mốc của detail; "combo" giả = FHS × 1,01
        C.BASELINE: {"detail": d.assign(model_pinball_loss=d.baseline_pinball_loss)},
        C.FHS: named[C.FHS],
        C.COMBO: {"detail": d.assign(model_pinball_loss=d.model_pinball_loss.astype(float) * 1.01)},
    }
    mcs = R.run_mcs(three)
    for asset in C.ASSETS:
        res = mcs[asset]
        losses = R.mcs_losses(d, asset)
        assert res["n_obs"] == len(losses) and 0 < len(losses) <= len(origins[asset])
        assert res["included"] and set(res["included"]) | set(res["excluded"]) == set(C.MCS_MODELS)
        assert all(0 <= p <= 1 for p in res["pvalue"].values())
        assert C.COMBO not in res["included"] or C.FHS in res["included"]
    one = d[(d.asset == "gold") & d.common_mask_all.fillna(False).astype(bool)]
    first = one.base_date.min()
    expected = one[one.base_date == first].model_pinball_loss.astype(float).mean()
    assert R.mcs_losses(d, "gold").loc[first] == pytest.approx(expected)


def test_select_candidate_rule():
    pick = R.select_candidate
    assert pick({C.FHS: 0.010, C.COMBO: 0.0105}) == {
        "selected": C.FHS,
        "tied_with_best": [C.FHS, C.COMBO],
        "early_stop": False,
    }
    assert pick({C.FHS: 0.010, C.COMBO: 0.0112})["selected"] == C.COMBO
    assert pick({C.FHS: 0.012, C.COMBO: 0.002})["selected"] == C.FHS
    stop = pick({C.FHS: 0.0, C.COMBO: -0.01})
    assert stop["early_stop"] and stop["selected"] is None
    assert not pick({C.FHS: -0.01, C.COMBO: 0.001})["early_stop"]


def test_cache_reads_raise_inside_guard():
    saved = [getattr(m, n) for m, n in R.CACHE_READERS]
    with R.no_ceemdan_cache():
        for module, name in R.CACHE_READERS:
            with pytest.raises(R.StopRun, match="CEEMDAN cache"):
                getattr(module, name)("lake", "gold")
    assert [getattr(m, n) for m, n in R.CACHE_READERS] == saved


def _fake_lake(tmp_path, dt, end="2019-06-28"):
    directory = tmp_path / "clean" / "prices" / f"dt={dt}"
    directory.mkdir(parents=True)
    prices = _fake_prices(end=end)
    prices.to_parquet(directory / "prices.parquet", index=False)
    rejected = pd.DataFrame(
        {
            "asset": ["gold", "wti", "silver"],
            "date": pd.to_datetime(["2017-05-02", "2019-02-01", "2019-06-03"]),
            "reason": "test",
        }
    )
    rejected.to_parquet(directory / "rejected.parquet", index=False)
    return tmp_path


def test_cv_reads_nothing_after_2018(tmp_path, monkeypatch):
    lake = _fake_lake(tmp_path, C.CLEAN_DT)
    prices, rejected = T.read_clean(lake, C.CLEAN_DT, cutoff=C.CV_CUTOFF)
    assert prices["date"].max() <= pd.Timestamp("2018-12-31")
    assert list(rejected["date"]) == [pd.Timestamp("2017-05-02")]
    seen = {}

    def capture(lake_dir, dt, cutoff):
        seen.update(dt=dt, cutoff=cutoff)
        raise R.StopRun("captured")

    monkeypatch.setattr(T, "read_clean", capture)
    with pytest.raises(R.StopRun, match="captured"):
        R.run_cv(lake, tmp_path / "out", "k4-test")
    assert seen == {"dt": C.CLEAN_DT, "cutoff": "2018-12-31"}
    monkeypatch.undo()
    unfiltered = pd.read_parquet
    monkeypatch.setattr(pd, "read_parquet", lambda path, filters=None: unfiltered(path))
    with pytest.raises(R.StopRun, match="after 2018-12-31"):
        T.read_clean(lake, C.CLEAN_DT, cutoff=C.CV_CUTOFF)


# ---------- cv-dm ----------


@pytest.fixture(scope="module")
def cv_dir(built, evaluated, tmp_path_factory):
    """Thư mục kết quả cv giả: forecasts/fits từ build_cv, detail… của fhs-gjr-t đã đánh giá."""
    _, out, _, _ = built
    _, _, named = evaluated
    d = tmp_path_factory.mktemp("cv")
    R.forecast_rows(out["forecasts"], R.MODELS).to_parquet(d / "forecasts_cv.parquet")
    R.write_frames(d, named)
    R.write_fits(d, out["fits"])
    summary = {"run_id": "k4-cv-fake", "stage": "cv", "plan": R.PLAN, "models": [C.FHS]}
    (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return d


def test_cv_dm_rebuilds_fhs_exactly_and_demeans(built, cv_dir):
    cut, out, expected, _ = built
    ref = R.cv_reference(cv_dir)
    base, q, crossed = out["forecasts"][C.FHS]["gold"]
    rb, rq, rc = ref["forecasts"][C.FHS]["gold"]
    assert R._ns(base).equals(rb) and np.array_equal(q, rq) and np.array_equal(crossed, rc)
    invalid = {a: [] for a in C.ASSETS}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "CV_EXPECTED_N", expected)
        dm = R.build_cv_dm(cut, invalid, ref, assets=("gold", "brent"))
        bad = {**ref, "forecasts": {C.FHS: {"gold": (rb, rq + 1e-12, rc)}}}
        with pytest.raises(R.StopRun, match="differs from the cv run"):
            R.build_cv_dm(cut, invalid, bad, assets=("gold",))
        fits = ref["fits"].copy()
        fits.loc[fits.asset == "gold", "beta"] += 1e-12
        with pytest.raises(R.StopRun, match="refits differ"):
            R.build_cv_dm(cut, invalid, {**ref, "fits": fits}, assets=("gold",))
    for asset in ("gold", "brent"):
        b_dm, q_dm, _ = dm["forecasts"][C.FHS_DM][asset]
        b_f, q_f, _ = out["forecasts"][C.FHS][asset]
        assert R._ns(b_dm).equals(R._ns(b_f)) and len(b_dm) == expected[asset]
        assert not np.array_equal(q_dm, q_f) and (np.diff(q_dm, axis=-1) >= 0).all()


def test_scoring_inputs_and_direction_table(evaluated):
    _, _, named = evaluated
    d = named[C.FHS]["detail"]
    assert R.same_scoring_inputs(d, d.copy())
    other = d.copy()
    other.loc[other.index[0], "y_true"] = 1.0
    assert not R.same_scoring_inputs(other, d)
    t = R.direction_table(named, [C.FHS])
    assert len(t) == 28 and t.n.gt(0).all()
    # prob_up < 0,5 đúng khi q50 < 0 (nội suy tuyến tính giữa các phân vị)
    assert np.allclose(t["prob_up<0,5"], t["q50<0"])
    assert t["q50<0"].between(0, 1).all() and t["sign_accuracy"].between(0, 1).all()


# ---------- phần chặn val2019 (mục 8, sửa đổi sau kiểm định chéo) ----------


def _gate_dirs(root, fhs=0.0155, combo=0.0133, dm=0.002, cv_override=None, **dm_override):
    cv_dir, dm_dir = root / "cv", root / "cv-dm"
    cv_dir.mkdir(exist_ok=True)
    dm_dir.mkdir(exist_ok=True)
    cv = {
        "run_id": "k4-cv-clean",
        "stage": "cv",
        "plan": R.PLAN,
        "provenance": {"commit": "a" * 40},
        "scores": {C.FHS: {"mean_28": fhs}, C.COMBO: {"mean_28": combo}},
        **R.select_candidate({C.FHS: fhs, C.COMBO: combo}),
        **(cv_override or {}),
    }
    cv_dm = {
        "run_id": "k4-cv-dm",
        "stage": "cv-dm",
        "plan": R.PLAN,
        "model": C.FHS_DM,
        "provenance": {"commit": "b" * 40},
        "cv_reference": {"run_id": "k4-cv-clean", "commit": "a" * 40},
        "scores": {C.FHS_DM: {"mean_28": dm}},
        "proceed_to_2019": dm > 0,
        **dm_override,
    }
    (cv_dir / "summary.json").write_text(json.dumps(cv), encoding="utf-8")
    (dm_dir / "summary.json").write_text(json.dumps(cv_dm), encoding="utf-8")
    return cv_dir, dm_dir


def test_val2019_gate_only_for_dm_after_cv_and_positive_cv_dm(tmp_path, monkeypatch):
    def no_data(*_args, **_kwargs):
        raise AssertionError("val2019 gate must not read prices")

    monkeypatch.setattr(T, "read_clean", no_data)
    gate = R.val2019_gate
    cv, dm = _gate_dirs(tmp_path)
    assert gate(cv, dm, C.FHS_DM)["cv_dm"]["scores"][C.FHS_DM]["mean_28"] == 0.002
    for candidate in (C.FHS, C.COMBO):
        with pytest.raises(R.StopRun, match="only fhs-gjr-t-dm"):
            gate(cv, dm, candidate)
    with pytest.raises(R.StopRun, match="no cv results"):
        gate(tmp_path / "none", dm, C.FHS_DM)
    with pytest.raises(R.StopRun, match="no cv-dm results"):
        gate(cv, tmp_path / "none", C.FHS_DM)
    for value in (0.0, -0.003):  # ≤ 0: dừng, không chạy 2019
        _gate_dirs(tmp_path, dm=value)
        with pytest.raises(R.StopRun, match="no 2019 run"):
            gate(cv, dm, C.FHS_DM)
    _gate_dirs(tmp_path, dm=0.002, proceed_to_2019=False)
    with pytest.raises(R.StopRun, match="does not follow section 8"):
        gate(cv, dm, C.FHS_DM)
    _gate_dirs(tmp_path, cv_reference={"run_id": "k4-cv", "commit": "c" * 40})
    with pytest.raises(R.StopRun, match="not run on this cv result"):
        gate(cv, dm, C.FHS_DM)
    _gate_dirs(tmp_path, fhs=0.004, combo=0.012)  # cv chọn combo: sửa đổi dm không áp dụng
    with pytest.raises(R.StopRun, match="dm amendment applies"):
        gate(cv, dm, C.FHS_DM)
    _gate_dirs(tmp_path, fhs=-0.001, combo=-0.002)
    with pytest.raises(R.StopRun, match="early stop"):
        gate(cv, dm, C.FHS_DM)
    _gate_dirs(tmp_path, cv_override={"selected": C.COMBO})
    with pytest.raises(R.StopRun, match="does not follow section 4"):
        gate(cv, dm, C.FHS_DM)
    args = ["--stage", "val2019", "--cv-dir", str(cv), "--cv-dm-dir", str(dm)]
    assert R.main([*args, "--candidate", C.FHS]) == 2
    with pytest.raises(SystemExit):
        R.main(["--stage", "val2019", "--cv-dir", str(cv), "--candidate", C.FHS_DM])


# ---------- phần thân val2019 trên dữ liệu GIẢ ----------


def test_val2019_body_on_fake_data_runs_once(tmp_path):
    from tests.test_run_k3b import _fake_k3_dir

    lake = _fake_lake(tmp_path / "lake", C.CLEAN_DT, end="2020-03-31")  # có cả 2020
    (tmp_path / "k3").mkdir()
    k3_dir = _fake_k3_dir(tmp_path / "k3")
    cv, dm = _gate_dirs(tmp_path)
    out = tmp_path / "out"
    s = R.run_val2019(lake, out, "k4-val-fake", cv, dm, C.FHS_DM, k3_dir)
    assert s["stage"] == "val2019" and s["candidate"] == C.FHS_DM
    assert s["models"] == [C.FHS_DM, C.BASELINE, C.S1A]
    assert (s["look_number"], s["total_configs_seen_on_2019"], s["cv_configs_seen"]) == (3, 12, 3)
    assert s["common_origins"] == C.K3_COMMON_N
    assert s["provenance"]["data_lineage"]["prices_view"]["max_date"] == "2019-12-31"
    assert s["provenance"]["data_lineage"]["cutoff"] == "2019-12-31"
    assert s["asset_passes"].keys() == set(C.ASSETS)
    assert set(s["asset_passes"]["brent"]) == {"all", "excl_roll"}
    assert set(s["asset_passes"]["gold"]) == {"all"}
    assert all(f["months"] == 12 for f in s["fhs_fits"].values())
    d = out / "eval" / "k4" / "k4-val-fake"
    f = pd.read_parquet(d / "forecasts_val2019.parquet")
    assert set(f.model) == set(C.VAL_MODELS) and f.base_date.max() <= pd.Timestamp("2019-12-31")
    detail = pd.read_parquet(d / "detail.parquet")
    used = detail[detail.common_mask_all.fillna(False).astype(bool)]
    assert pd.to_datetime(used.target_date).max() <= pd.Timestamp("2019-12-31")
    assert set(used.base_date.str[:4]) == {"2019"}
    assert (d / "started.json").is_file() and (d / "summary.md").is_file()
    assert R.runs_on_2019(out) == ["k4-val-fake"]
    with pytest.raises(R.StopRun, match="already run"):  # kế hoạch: một lần
        R.run_val2019(lake, out, "k4-val-again", cv, dm, C.FHS_DM, k3_dir)


def test_config_and_requirements_pins():
    assert (C.LOOK_NUMBER, C.TOTAL_CONFIGS_SEEN) == (3, 12)
    assert C.CANDIDATES == ("fhs-gjr-t", "combo-eq3") and C.TIE_TOLERANCE == 0.001
    assert C.CV_EXPECTED_N == {"gold": 754, "silver": 754, "brent": 716, "wti": 755}
    assert (C.MCS_SIZE, C.MCS_REPS, C.MCS_BLOCK, C.MCS_SEED) == (0.10, 1000, 20, 7)
    assert (C.FHS_WINDOW, C.FHS_SCALE, C.FHS_PATHS, C.FHS_STEPS) == (1000, 100.0, 5000, 7)
    assert C.CV == ("2016-01-01", "2018-12-31") and C.CV_CUTOFF == "2018-12-31"
    assert C.FHS_DM == "fhs-gjr-t-dm" and C.VAL2019_CANDIDATE == C.FHS_DM
    assert C.FHS_DEMEAN == {C.FHS: False, C.FHS_DM: True} and C.CV_DM_PROCEED_ABOVE == 0.0
    assert C.CV_CONFIGS_SEEN == 3 and C.VAL_MODELS == (C.FHS_DM, C.BASELINE, C.S1A)
    assert C.VAL_CUTOFF == "2019-12-31" and C.K3_COMMON_N == {
        "gold": 245,
        "silver": 245,
        "brent": 202,
        "wti": 202,
    }
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    assert any(line.split("#")[0].strip() == f"arch=={C.ARCH_VERSION}" for line in dev)
    predict = (ROOT / "requirements-predict.txt").read_text(encoding="utf-8").splitlines()
    assert not any(line.strip().lower().startswith("arch") for line in predict)

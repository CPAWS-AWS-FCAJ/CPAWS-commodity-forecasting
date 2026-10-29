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


# ---------- kết quả cv khớp commit trước trong sai số (dữ liệu tổng hợp) ----------

# Forecasts của build_cv và build_cv_dm đi qua bước fit arch (bộ tối ưu của scipy), không tái lập
# từng bit giữa các hệ điều hành (CI Linux khác Windows ở bit cuối); tái lập từng bit chỉ áp dụng
# trên cùng nền tảng. Nên so giá trị chuẩn rút gọn trong sai số: một mẫu cố định các phần tử (mỗi
# tài sản: ngày gốc đầu h1 q05, giữa h4 q50, cuối h7 q95), tổng trị tuyệt đối, tổng bình phương và
# tổng có dấu theo từng mô hình. Giá trị chuẩn tính bằng code ở 850cbc5 trên Windows, trùng hash
# của cfecd62 trên cùng máy. Phần NumPy-only có tham số cố định vẫn so hash từng bit
# (tests/test_fhs_numpy.py).
TOL = {"rtol": 1e-6, "atol": 1e-10}
N_COMMON = [754, 754, 716, 755]
REFERENCE = {
    "baseline-q252": {
        "sum": 150.24506882510224,
        "abs_sum": 3008.362077957237,
        "sumsq": 93.30176619419626,
        "sample": [
            -0.015372347695275464,
            6.135559443404756e-05,
            0.04575326709685627,
            -0.02058172830264119,
            0.0017403682296427444,
            0.04184160792530466,
            -0.01809050052788306,
            -0.004719536691896953,
            0.05331191940155231,
            -0.022315921714155872,
            0.0006695588811941777,
            0.0681383794091988,
        ],
    },
    "S1a": {
        "sum": 140.4514496201212,
        "abs_sum": 2821.945031994406,
        "sumsq": 92.8814457455803,
        "sample": [
            -0.01307863742717126,
            6.135559443404756e-05,
            0.031519494023974325,
            -0.018287130198793123,
            0.0017403682296427444,
            0.021711860309024056,
            -0.022424568742190613,
            -0.004719536691896953,
            0.04715271513863061,
            -0.020625969647751492,
            0.0006695588811941777,
            0.047199746950395874,
        ],
    },
    "fhs-gjr-t": {
        "sum": -141.29248284228171,
        "abs_sum": 2938.4557687565202,
        "sumsq": 96.58806671348827,
        "sample": [
            -0.01327488509747911,
            -0.0008941171112575932,
            0.037928647714852506,
            -0.02015645506327512,
            0.0003887194065851568,
            0.02392452270906941,
            -0.0224440593853761,
            -0.002264424150266173,
            0.039221241677650245,
            -0.018835268031922994,
            0.002304603877660701,
            0.036131745829191056,
        ],
    },
    "combo-eq3": {
        "sum": 49.801345200980556,
        "abs_sum": 2920.162731588858,
        "sumsq": 90.05144300140093,
        "sample": [
            -0.013908623406641944,
            -0.000257135307463166,
            0.03840046961189437,
            -0.019675104521569814,
            0.001289818621956882,
            0.029159330314466048,
            -0.02098637621848326,
            -0.0039011658446866924,
            0.04656195873927773,
            -0.02059238646461012,
            0.0012145738800163521,
            0.05048995739626191,
        ],
    },
    "fhs-gjr-t-dm": {
        "sum": -6.664751133586341,
        "abs_sum": 2912.096421061552,
        "sumsq": 95.73415278795025,
        "sample": [
            -0.012867444663159982,
            0.0002617113436634349,
            0.038674653667314575,
            -0.01945475719283682,
            0.00040132760356886735,
            0.02427261136056729,
            -0.02196060300920806,
            -0.0002602568739348409,
            0.04381264445166926,
            -0.019255894372345223,
            0.0009941182169919817,
            0.033826197241150144,
        ],
    },
}
GOLDEN_MCS_P = {"baseline-q252": 1.0, "fhs-gjr-t": 0.0, "combo-eq3": 0.0}
GOLDEN_MCS_MEAN = {
    "gold": [0.0021369839897171844, 0.0021583538296143564, 0.0021797236695115284],
    "brent": [0.0019844485845729176, 0.002004293070418647, 0.0020241375562643758],
}


def _assert_matches_reference(forecasts, model):
    ref = REFERENCE[model]
    qs = [forecasts[model][a][1] for a in C.ASSETS]
    assert [len(q) for q in qs] == N_COMMON
    assert not any(np.asarray(forecasts[model][a][2]).any() for a in C.ASSETS)
    sample = [x for q in qs for x in (q[0, 0, 0], q[len(q) // 2, 3, 3], q[-1, 6, 6])]
    allq = np.concatenate([q.ravel() for q in qs])
    np.testing.assert_allclose(sample, ref["sample"], **TOL)
    np.testing.assert_allclose(
        [np.abs(allq).sum(), (allq**2).sum()], [ref["abs_sum"], ref["sumsq"]], **TOL
    )
    # tổng có dấu triệt tiêu nhau (bản dm: −6,7 trên tổng trị tuyệt đối 2912) nên so theo thang
    # của tổng trị tuyệt đối, không theo chính nó
    np.testing.assert_allclose(allq.sum(), ref["sum"], rtol=0, atol=TOL["rtol"] * ref["abs_sum"])


def _synthetic_mcs_named(drop=0):
    rng = np.random.default_rng(3)
    rows = []
    for a in C.ASSETS:
        for d in pd.bdate_range("2016-01-04", periods=120):
            for h in C.HORIZONS:
                rows.append(
                    {
                        "asset": a,
                        "base_date": str(d.date()),
                        "h": h,
                        "common_mask_all": True,
                        "loss": rng.gamma(2.0, 0.001),
                    }
                )
    base = pd.DataFrame(rows)
    named = {
        m: {"detail": base.assign(model_pinball_loss=base.loss * (1 + 0.01 * i))}
        for i, m in enumerate(C.MCS_MODELS)
    }
    if drop:  # một mô hình thiếu h = 7 ở `drop` ngày gốc đầu
        d = named[C.FHS]["detail"]
        first = sorted(d.base_date.unique())[:drop]
        named[C.FHS]["detail"] = d[~(d.base_date.isin(first) & (d.h == 7))]
    return named


def test_cv_and_cv_dm_forecasts_match_previous_commit_within_tolerance(built):
    """Forecasts cv (4 mô hình) và cv-dm khớp giá trị chuẩn của commit trước trong sai số
    rtol 1e-6, atol 1e-10: bước fit arch không tái lập từng bit giữa các hệ điều hành, nên tái
    lập từng bit chỉ áp dụng trên cùng nền tảng (lần chạy thật so file parquet trên cùng máy)."""
    cut, out, expected, _ = built
    for model in R.MODELS:
        _assert_matches_reference(out["forecasts"], model)
    ref = {"forecasts": out["forecasts"], "fits": pd.DataFrame(out["fits"])}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "CV_EXPECTED_N", expected)
        dm = R.build_cv_dm(cut, {a: [] for a in C.ASSETS}, ref)
    _assert_matches_reference(dm["forecasts"], C.FHS_DM)
    for asset in C.ASSETS:
        assert out["validity"][asset]["fhs_invalid"]["invalid_variance"] == 0
        assert dm["validity"][asset]["fhs_dm_invalid"]["nonfinite_quantiles"] == 0


def test_mcs_unchanged_and_uses_origins_full_in_every_model():
    res = R.run_mcs(_synthetic_mcs_named())
    for asset, means in GOLDEN_MCS_MEAN.items():
        got = [res[asset]["mean_loss"][m] for m in C.MCS_MODELS]
        np.testing.assert_allclose(got, means, **TOL)
    assert all(res[a]["pvalue"] == GOLDEN_MCS_P for a in C.ASSETS)
    assert all(res[a]["n_obs"] == 120 and not res[a]["origins_changed"] for a in C.ASSETS)
    narrowed = R.run_mcs(_synthetic_mcs_named(drop=5))
    for asset in C.ASSETS:
        assert narrowed[asset]["n_obs"] == 115 and narrowed[asset]["origins_changed"]
        assert narrowed[asset]["n_full_by_model"] == {
            C.BASELINE: 120,
            C.FHS: 115,
            C.COMBO: 120,
        }


def test_fit_summary_reports_reuse_streak_and_persistence_bound():
    months = pd.date_range("2016-01-01", periods=6, freq="MS")
    used = [months[0], months[0], months[0], months[3], months[3], months[5]]
    pers = [0.99, 1.0 + 4e-11, 0.98, 1.0 - 5e-10, 0.97, 0.96]
    logs = [
        {
            "asset": "brent",
            "month": m,
            "status": "ok" if u == m else "not_converged",
            "used_month": u,
            "warnings": [],
            "parity_rel_error": 1e-16,
            "omega": 0.01,
            "alpha": 0.0,
            "gamma": 0.05,
            "beta": p - 0.025,
            "nu": 5.0,
            "persistence": p,
        }
        for m, u, p in zip(months, used, pers, strict=True)
    ]
    f = R.fit_summary(logs)["brent"]
    assert f["max_consecutive_reuse"] == 2 and len(f["fallback_months"]) == 3
    bound = f["at_persistence_bound"]
    assert [b["month"] for b in bound] == ["2016-04-01"]  # chỉ tính các lần fit ok
    assert bound[0]["gap"] == pytest.approx(5e-10)


def test_roll_calendar_checks(evaluated, monkeypatch):
    _, _, named = evaluated
    for config in (R.cv_config, R.val_config):
        R.check_roll_calendar(config)
    R.check_roll_flags(named)
    bad = named[C.FHS]["detail"].copy()
    bad["roll_in_horizon"] = bad["roll_in_horizon"].astype(object)
    bad.loc[bad.asset == "wti", "roll_in_horizon"] = None
    with pytest.raises(R.StopRun, match="roll_in_horizon is None"):
        R.check_roll_flags({C.FHS: {"detail": bad}})
    monkeypatch.setattr(
        R.wf, "roll_calendar", lambda asset, cfg: (pd.DatetimeIndex([]), pd.DatetimeIndex([]))
    )
    with pytest.raises(R.StopRun, match="roll calendar is empty"):
        R.check_roll_calendar(R.cv_config)

    def broken(asset, cfg):
        raise ValueError("no expiries")

    monkeypatch.setattr(R.wf, "roll_calendar", broken)
    with pytest.raises(R.StopRun, match="roll calendar unavailable"):
        R.check_roll_calendar(R.val_config)


# ---------- dự báo tại t không đổi khi đổi giá sau t (5 mô hình) ----------


def test_forecasts_at_t_ignore_prices_after_t(built):
    cut, _, expected, _ = built
    t = pd.Timestamp("2017-06-15")
    changed = cut.copy()
    later = changed["date"] > t
    rng = np.random.default_rng(42)
    changed.loc[later, "price"] *= np.exp(rng.normal(0, 0.05, int(later.sum())))
    assets = ("gold", "wti")
    invalid = {a: [] for a in C.ASSETS}
    runs = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "CV_EXPECTED_N", expected)
        for prices in (cut, changed):
            b = R.build_cv(prices, invalid, assets=assets)
            ref = {"forecasts": b["forecasts"], "fits": pd.DataFrame(b["fits"])}
            dm = R.build_cv_dm(prices, invalid, ref, assets=assets)
            runs.append({**b["forecasts"], C.FHS_DM: dm["forecasts"][C.FHS_DM]})
    for name in (*R.MODELS, C.FHS_DM):
        for asset in assets:
            (b0, q0, c0), (b1, q1, c1) = runs[0][name][asset], runs[1][name][asset]
            assert R._ns(b0).equals(R._ns(b1))
            upto = np.asarray(R._ns(b0) <= t)
            assert upto.sum() > 300
            assert np.array_equal(q0[upto], q1[upto]) and np.array_equal(c0[upto], c1[upto])
            assert not np.array_equal(q0[~upto], q1[~upto])  # sau t thì đổi


# ---------- báo cáo bổ sung (mục 8, 29/10 tối) ----------


def test_supplementary_reports(built, evaluated):
    _, out, _, _ = built
    _, origins, named = evaluated
    d = named[C.FHS]["detail"]
    cfg = R.cv_config(C.FHS)
    groups7 = [("gold", h) for h in C.HORIZONS]
    groups28 = [(a, h) for a in C.ASSETS for h in C.HORIZONS]
    for groups, sample in ((groups7, "all"), (groups28, "all"), ([("wti", 3)], "excl_roll")):
        mine = R.skill_bootstrap(d, groups, sample, cfg, 20)
        ref = R.R3.groups_skill_ci(d, groups, sample, cfg)
        assert (mine["value"], mine["ci_low"], mine["ci_high"]) == (
            ref["value"],
            ref["ci_low"],
            ref["ci_high"],
        )
        assert 0 < mine["p_one_sided"] <= 1
    sens = R.ci_sensitivity(named, [C.FHS], R.cv_config)
    assert len(sens) == 7 * 3 and set(sens.block) == {10, 20, 40}
    holm = R.holm_table(sens, C.FHS)
    main = holm[holm["sample"] == "all"]
    assert list(main.asset) == list(C.ASSETS) and (main.p_holm >= main.p_one_sided).all()
    assert set(holm.loc[holm["sample"] == "excl_roll", "asset"]) == {"brent", "wti"}
    folds = R.fold_table(named, [C.FHS])
    assert set(folds.fold) == set(C.CV_FOLDS) and len(folds) == 6 * 3
    counts = R.valid_counts(d)
    assert len(counts) == 28 and counts.loc[counts.asset == "wti", "n_excl_roll"].notna().all()
    assert (counts.n_all > 0).all()
    chris = R.christoffersen_table(named, [C.FHS])
    assert len(chris) == 28 and chris["tỷ lệ vượt"].between(0, 1).all()
    acc = named[C.FHS]["accuracy"].query("metric == 'pinball_skill' and sample == 'all'")
    skills = R.skill_on_mask(d, R.R3.restrict(out["forecasts"][C.FHS], origins))
    for row in acc.itertuples():
        assert skills[(row.asset, row.h)] == pytest.approx(row.value, abs=1e-12)
    diff = R.dm_vs_fhs(d, d.copy())
    assert (diff["chênh lệch"] == 0).all() and len(diff) == 28 + 14


def test_christoffersen_independence():
    rng = np.random.default_rng(0)
    iid = rng.random(2000) < 0.2
    clustered = np.repeat(rng.random(200) < 0.2, 10)
    _, p_iid = R.christoffersen_independence(iid)
    lr, p_cl = R.christoffersen_independence(clustered)
    assert p_iid > 0.01 and p_cl < 1e-6 and lr > 0
    assert all(np.isnan(R.christoffersen_independence(np.zeros(50, bool))))


def test_dm_robustness_variants(built, cv_dir):
    cut, _, expected, _ = built
    ref = R.cv_reference(cv_dir)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "CV_EXPECTED_N", expected)
        dm = R.build_cv_dm(cut, {a: [] for a in C.ASSETS}, ref, assets=("gold",))
    detail = ref["named"][C.FHS]["detail"]
    sub = {"gold": dm["inputs"]["gold"]}
    sub["gold"] = (*sub["gold"][:2], R._ns(sub["gold"][2])[::8])  # đúng tập ngày gốc đã chấm
    table = R.dm_robustness(detail, sub)
    assert list(table["biến thể"]) == ["đã chốt", "seed + 1000000", "seed + 2000000", "10000 đường"]
    assert table.gold.notna().all() and table["trung bình 28 nhóm"].isna().all()
    assert table.gold.std() < 0.02  # chỉ sai số Monte Carlo


# ---------- phần chặn val2019 (mục 8: sau kiểm định chéo, và 29/10 tối) ----------


FAKE_LINEAGE = {
    "clean_dt": C.CLEAN_DT,
    "cutoff": C.CV_CUTOFF,
    "prices_view": {"n_rows": 1, "max_date": "2018-12-31", "sha256": "f" * 64},
    "rejected_view": {"n_rows": 0},
}


def _result_dir(directory, stage, summary, lineage, prov=None, drop_hash=None):
    """Thư mục kết quả giả mà verified_result chấp nhận: commit sạch, fingerprint config/code và
    phiên bản thư viện của code hiện tại, file kết quả kèm SHA-256."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in R.RESULT_FILES[stage]:
        (directory / name).write_bytes(f"{stage}:{name}".encode())
    provenance = {
        "commit": "a" * 40 if stage == "cv" else "b" * 40,
        "commit_dirty": False,
        "code_sha256": R.code_fingerprint(),
        "versions": R.environment_versions(),
        "data_lineage": lineage,
        **(prov or {}),
    }
    hashes = {n: R.file_sha256(directory / n) for n in R.RESULT_FILES[stage] if n != drop_hash}
    s = {**summary, "provenance": provenance, "file_sha256": hashes}
    (directory / "summary.json").write_text(json.dumps(s), encoding="utf-8")
    return directory


def _gate_dirs(
    root,
    fhs=0.0155,
    combo=0.0133,
    dm=0.002,
    cv_override=None,
    cv_prov=None,
    dm_prov=None,
    lineage=FAKE_LINEAGE,
    **dm_override,
):
    cv = {
        "run_id": "k4-cv-clean",
        "stage": "cv",
        "plan": R.PLAN,
        "scores": {C.FHS: {"mean_28": fhs}, C.COMBO: {"mean_28": combo}},
        **R.select_candidate({C.FHS: fhs, C.COMBO: combo}),
        **(cv_override or {}),
    }
    cv_dm = {
        "run_id": "k4-cv-dm",
        "stage": "cv-dm",
        "plan": R.PLAN,
        "model": C.FHS_DM,
        "cv_reference": {"run_id": "k4-cv-clean", "commit": "a" * 40},
        "scores": {C.FHS_DM: {"mean_28": dm}},
        "proceed_to_2019": dm > 0,
        **dm_override,
    }
    return (
        _result_dir(root / "cv", "cv", cv, lineage, cv_prov),
        _result_dir(root / "cv-dm", "cv-dm", cv_dm, lineage, dm_prov),
    )


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


def test_val2019_gate_rejects_dirty_or_mismatched_results(tmp_path):
    gate = R.val2019_gate
    cv, dm = _gate_dirs(tmp_path)
    assert gate(cv, dm, C.FHS_DM)
    for which in ("cv_prov", "dm_prov"):  # chạy từ code chưa commit
        cv, dm = _gate_dirs(tmp_path, **{which: {"commit_dirty": True}})
        with pytest.raises(R.StopRun, match="not run from committed code"):
            gate(cv, dm, C.FHS_DM)
    cv, dm = _gate_dirs(tmp_path, cv_prov={"commit_dirty": None})
    with pytest.raises(R.StopRun, match="not run from committed code"):
        gate(cv, dm, C.FHS_DM)
    code = {**R.code_fingerprint(), "configs/k4.py": "0" * 64}
    cv, dm = _gate_dirs(tmp_path, dm_prov={"code_sha256": code})
    with pytest.raises(R.StopRun, match="config/code fingerprint differs"):
        gate(cv, dm, C.FHS_DM)
    versions = {**R.environment_versions(), "arch": "0.0"}
    cv, dm = _gate_dirs(tmp_path, cv_prov={"versions": versions})
    with pytest.raises(R.StopRun, match="library versions differ"):
        gate(cv, dm, C.FHS_DM)
    other = {**FAKE_LINEAGE, "prices_view": {"n_rows": 2}}
    cv, dm = _gate_dirs(tmp_path, dm_prov={"data_lineage": other})
    with pytest.raises(R.StopRun, match="data fingerprint differs"):
        gate(cv, dm, C.FHS_DM)
    cv, dm = _gate_dirs(tmp_path)
    (dm / "detail.parquet").write_bytes(b"changed after the run")
    with pytest.raises(R.StopRun, match="checksum mismatch for detail.parquet"):
        gate(cv, dm, C.FHS_DM)
    _gate_dirs(tmp_path)
    (cv / "mean7.parquet").unlink()
    with pytest.raises(R.StopRun, match="checksum mismatch for mean7.parquet"):
        gate(cv, dm, C.FHS_DM)
    cv, dm = _gate_dirs(tmp_path)
    _result_dir(
        cv,
        "cv",
        json.loads((cv / "summary.json").read_text(encoding="utf-8")),
        FAKE_LINEAGE,
        drop_hash="forecasts_cv.parquet",
    )
    with pytest.raises(R.StopRun, match="no checksum for forecasts_cv.parquet"):
        gate(cv, dm, C.FHS_DM)


def test_finalize_records_sha256_of_every_result_file(tmp_path):
    (tmp_path / "a.parquet").write_bytes(b"a")
    (tmp_path / "b.json").write_bytes(b"{}")
    summary = {"stage": "x"}
    R.finalize(tmp_path, summary, "# md\n")
    stored = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert set(stored["file_sha256"]) == {"a.parquet", "b.json", "summary.md"}
    assert stored["file_sha256"]["summary.md"] == R.file_sha256(tmp_path / "summary.md")


# ---------- phần thân val2019 trên dữ liệu GIẢ ----------


def test_val2019_body_on_fake_data_runs_once(tmp_path):
    from tests.test_run_k3b import _fake_k3_dir

    lake = _fake_lake(tmp_path / "lake", C.CLEAN_DT, end="2020-03-31")  # có cả 2020
    (tmp_path / "k3").mkdir()
    k3_dir = _fake_k3_dir(tmp_path / "k3")
    out = tmp_path / "out"
    run_id = C.VAL2019_RUN_ID
    # fingerprint dữ liệu sai: dừng trước khi đánh dấu chạy hay đọc 2019
    cv, dm = _gate_dirs(tmp_path / "bad")
    with pytest.raises(R.StopRun, match="clean data fingerprint"):
        R.run_val2019(lake, out, run_id, cv, dm, C.FHS_DM, k3_dir)
    assert R.runs_on_2019(out) == [] and not (out / "eval" / "k4" / run_id).exists()
    lineage = R.data_lineage(*T.read_clean(lake, C.CLEAN_DT, cutoff=C.CV_CUTOFF), C.CV_CUTOFF)
    cv, dm = _gate_dirs(tmp_path, lineage=lineage)
    s = R.run_val2019(lake, out, run_id, cv, dm, C.FHS_DM, k3_dir)
    assert s["stage"] == "val2019" and s["candidate"] == C.FHS_DM and s["run_id"] == "k4-val2019"
    assert s["models"] == [C.FHS_DM, C.BASELINE, C.S1A]
    assert (s["look_number"], s["total_configs_seen_on_2019"], s["cv_configs_seen"]) == (4, 13, 3)
    assert s["common_origins"] == C.K3_COMMON_N
    assert s["provenance"]["data_lineage"]["prices_view"]["max_date"] == "2019-12-31"
    assert s["provenance"]["data_lineage"]["cutoff"] == "2019-12-31"
    assert s["asset_passes"].keys() == set(C.ASSETS)
    assert set(s["asset_passes"]["brent"]) == {"all", "excl_roll"}
    assert set(s["asset_passes"]["gold"]) == {"all"}
    assert s["asset_decision"] == {a: by["all"] for a, by in s["asset_passes"].items()}
    assert s["any_asset_passes"] == any(s["asset_decision"].values())
    assert all(f["months"] == 12 for f in s["fhs_fits"].values())
    supp = s["supplementary"]
    assert {r["fold"] for r in supp["folds"]} == {2019}
    assert {r["biến thể"] for r in supp["dm_robustness"]} == {
        "đã chốt",
        "seed + 1000000",
        "seed + 2000000",
        "10000 đường",
    }
    assert {r["block"] for r in supp["ci_blocks"]} == set(C.CI_BLOCKS)
    assert len(supp["holm"][C.FHS_DM]) == 6 and len(supp["christoffersen"]) == 3 * 28
    assert isinstance(supp["dm_minus_fhs"], str)  # fhs-gjr-t không chạy trên 2019
    d = out / "eval" / "k4" / run_id
    hashes = s["file_sha256"]
    assert {"started.json", "summary.md", "forecasts_val2019.parquet"} <= set(hashes)
    assert all(R.file_sha256(d / n) == h for n, h in hashes.items())
    f = pd.read_parquet(d / "forecasts_val2019.parquet")
    assert set(f.model) == set(C.VAL_MODELS) and f.base_date.max() <= pd.Timestamp("2019-12-31")
    detail = pd.read_parquet(d / "detail.parquet")
    used = detail[detail.common_mask_all.fillna(False).astype(bool)]
    assert pd.to_datetime(used.target_date).max() <= pd.Timestamp("2019-12-31")
    assert set(used.base_date.str[:4]) == {"2019"}
    assert (d / "started.json").is_file() and (d / "summary.md").is_file()
    assert R.runs_on_2019(out) == [run_id]
    with pytest.raises(R.StopRun, match="already started once"):  # kế hoạch: một lần
        R.run_val2019(lake, out, run_id, cv, dm, C.FHS_DM, k3_dir)


def test_val2019_only_fixed_run_id_and_never_after_started(tmp_path, monkeypatch):
    """Chặn ở mức quy trình: run-id khác k4-val2019 hoặc đã có started.json thì từ chối, trước cả
    phần chặn và trước khi đọc dữ liệu."""

    def no_data(*_args, **_kwargs):
        raise AssertionError("must not read prices")

    monkeypatch.setattr(T, "read_clean", no_data)
    cv, dm = _gate_dirs(tmp_path)
    out = tmp_path / "out"
    for other in ("k4-val2019-retry", "k4-val-fake", "k4-cv"):
        with pytest.raises(R.StopRun, match="run-id must be 'k4-val2019'"):
            R.run_val2019(tmp_path, out, other, cv, dm, C.FHS_DM, tmp_path)
    args = ["--stage", "val2019", "--cv-dir", str(cv), "--cv-dm-dir", str(dm)]
    args += ["--candidate", C.FHS_DM, "--output-dir", str(out)]
    assert R.main([*args, "--run-id", "k4-val2019-b"]) == 2
    marker = out / "eval" / "k4" / C.VAL2019_RUN_ID / "started.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"stage": "val2019"}), encoding="utf-8")
    with pytest.raises(R.StopRun, match="already started once"):
        R.run_val2019(tmp_path, out, C.VAL2019_RUN_ID, cv, dm, C.FHS_DM, tmp_path)
    assert R.main(args) == 2  # run-id mặc định = k4-val2019, đã có started.json


def test_config_and_requirements_pins():
    assert C.LOOK_NUMBER == 4  # mục 8 (29/10 tối): tính cả DLinear MVP
    assert C.DLINEAR_MVP_CONFIGS == 1 and C.TOTAL_CONFIGS_SEEN == 13  # PR #26, review #60
    assert C.K3_K3B_K4_CONFIGS == 12 and R.configs_seen_text() == "13"
    assert C.VAL2019_RUN_ID == "k4-val2019"
    assert C.CANDIDATES == ("fhs-gjr-t", "combo-eq3") and C.TIE_TOLERANCE == 0.001
    assert C.CV_EXPECTED_N == {"gold": 754, "silver": 754, "brent": 716, "wti": 755}
    assert (C.MCS_SIZE, C.MCS_REPS, C.MCS_BLOCK, C.MCS_SEED) == (0.10, 1000, 20, 7)
    assert (C.FHS_WINDOW, C.FHS_SCALE, C.FHS_PATHS, C.FHS_STEPS) == (1000, 100.0, 5000, 7)
    assert (C.NU_MIN_EXCLUSIVE, C.PERSISTENCE_MAX, C.PERSISTENCE_TOL) == (2.0, 1.0, 1e-9)
    assert C.CV == ("2016-01-01", "2018-12-31") and C.CV_CUTOFF == "2018-12-31"
    assert C.FHS_DM == "fhs-gjr-t-dm" and C.VAL2019_CANDIDATE == C.FHS_DM
    assert C.FHS_DEMEAN == {C.FHS: False, C.FHS_DM: True} and C.CV_DM_PROCEED_ABOVE == 0.0
    assert C.CV_CONFIGS_SEEN == 3 and C.VAL_MODELS == (C.FHS_DM, C.BASELINE, C.S1A)
    assert (C.HOLM_ALPHA, C.CI_BLOCKS, C.DM_ROBUST_PATHS) == (0.025, (10, 20, 40), 10_000)
    assert C.DM_ROBUST_SEED_OFFSETS == (1_000_000, 2_000_000)
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

"""Validation2019 orchestration: synthetic edge cases and opt-in real artifact integration."""

import json
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data import calendars
from src.eval import metrics as M
from src.eval import walk_forward as W


class FixedModel:
    """Test double only; never an artifact or result delivered as a real model."""

    def __init__(self, crossing=False):
        self.calls = []
        self.raw = np.tile([-0.03, -0.02, -0.01, 0.001, 0.01, 0.02, 0.03], (7, 1))
        if crossing:
            self.raw[:, [1, 2]] = self.raw[:, [2, 1]]

    def predict(self, x):
        self.calls.append(x.copy())
        return np.repeat(self.raw[None, :, :], len(x), axis=0)


@pytest.fixture(scope="module")
def cfg():
    return W.EvaluationConfig(
        model_version="synthetic-test-only", evaluation_as_of_time="2026-10-22T00:00:00Z"
    )


@pytest.fixture(scope="module")
def fits(cfg):
    # Explicit synthetic IDs/commit labels, not claims about production Fits.
    return {
        a: {
            "fit_id": "test-only-" + a,
            "model_version": cfg.model_version,
            "asset": a,
            "train_end": "2018-12-31",
            "max_training_target_date": "2018-12-31",
            "trained_at": "2026-10-21T00:00:00Z",
            "config_hash": "test-config-" + a,
            "commit": "synthetic-test-only",
            "integration_eligible": True,
            "missing_metadata": [],
        }
        for a in W.ASSET_NAMES
    }


@pytest.fixture(scope="module")
def prices():
    frames = []
    for seed, asset in enumerate(W.ASSET_NAMES):
        dates = calendars.sessions(W.ASSETS[asset].calendar, "2017-01-01", "2020-02-01")
        rng = np.random.default_rng(seed)
        frames.append(
            pd.DataFrame(
                {
                    "asset": asset,
                    "date": dates,
                    "price": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates)))),
                    "source": "yfinance",
                    "published_at": (dates + pd.Timedelta(days=1, hours=12)).tz_localize("UTC"),
                    "flag": "",
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def rejected(prices):
    return prices.iloc[:0].copy()


@pytest.fixture
def models(fits):
    return {a: W.ModelBundle(FixedModel(), m, {}) for a, m in fits.items()}


@pytest.fixture(scope="module")
def forecasts(prices, rejected, fits, cfg):
    models = {a: W.ModelBundle(FixedModel(), m, {}) for a, m in fits.items()}
    return W.generate_forecasts(prices, rejected, models, cfg)


@pytest.fixture(scope="module")
def result(forecasts, prices, rejected, fits, cfg):
    return W.evaluate(forecasts, prices, rejected, fits, cfg)


@pytest.mark.parametrize(
    "changes",
    [
        {"evaluation_kind": "test"},
        {"evaluation_start": "2019-02-01"},
        {"target_cutoff_date": "2020-01-01"},
        {"retrain_every": 1},
        {"window": 61},
        {"block_length": 6},
        {"n_bootstrap": 10},
        {"provenance_status": "verified_backtest"},
        {"confidence_level": 0.9},
    ],
)
def test_reject_unsupported_configuration(changes):
    with pytest.raises(ValueError):
        W.EvaluationConfig(**changes)


def test_expected_full_grid_and_schema(forecasts, cfg):
    assert len(forecasts) == sum(
        len(calendars.sessions(W.ASSETS[a].calendar, "2019-01-01", "2019-12-31")) * 7
        for a in W.ASSET_NAMES
    )
    assert set(forecasts) == set(W.FORECAST_COLUMNS)
    assert forecasts.groupby(["asset", "base_date"]).h.nunique().eq(7).all()
    assert forecasts.forecast_status.eq("ok").all()
    assert forecasts.provenance_status.eq(W.PROVENANCE).all()
    assert not forecasts.duplicated(["asset", "base_date", "h"]).any()


def test_uses_builder_raw_windows_and_one_normalization(prices, rejected, models, cfg, monkeypatch):
    calls = []
    normal = []
    orig_window = W.make_windows
    orig_normal = W.normalize_quantiles

    def windows(*args, **kwargs):
        batch = orig_window(*args, **kwargs)
        calls.append(batch)
        return batch

    def normalize(raw):
        normal.append(raw.copy())
        return orig_normal(raw)

    monkeypatch.setattr(W, "make_windows", windows)
    monkeypatch.setattr(W, "normalize_quantiles", normalize)
    models["gold"].model = FixedModel(crossing=True)
    f = W.generate_forecasts(prices, rejected, models, cfg)
    assert len(calls) == 4
    assert len(normal) == sum(len(b.base_dates) for b in calls)
    for asset, batch in zip(W.ASSET_NAMES, calls, strict=True):
        # Inference receives unscaled, float64 FeatureBatch windows; no fit/scaler API is called.
        np.testing.assert_array_equal(models[asset].model.calls[0], batch.X[:1])
    assert f.loc[f.asset == "gold", "crossed_raw"].all()
    assert (np.diff(f[list(W.QCOLS)].to_numpy(), axis=1) >= 0).all()
    assert np.any(np.diff(normal[0], axis=1) < 0)


@pytest.mark.parametrize("kind", ["missing", "late", "equal"])
def test_input_publication_and_invalid_window_attempts(prices, rejected, models, cfg, kind):
    p = prices.copy()
    p["published_at"] = p["published_at"].astype("datetime64[ns, UTC]")
    day = pd.Timestamp("2019-01-03")
    select = (p.asset == "gold") & (p.date == day)
    p.loc[select, "published_at"] = (
        pd.NaT
        if kind == "missing"
        else W.publication_time("gold", day) + pd.Timedelta(nanoseconds=1 if kind == "late" else 0)
    )
    f = W.generate_forecasts(p, rejected, models, cfg)
    rows = f.loc[(f.asset == "gold") & (f.base_date == "2019-01-03")]
    assert len(rows) == 7
    if kind == "equal":
        assert rows.forecast_status.eq("ok").all()
    else:
        assert rows.forecast_status.eq("invalid_input_window").all()
        assert rows.missing_reason.eq(
            "input_nan" if kind == "missing" else "input_not_available"
        ).all()
        assert rows[[*W.QCOLS, "prob_up"]].isna().all().all()


@pytest.mark.parametrize("bad", ["exception", "shape", "nonfinite"])
def test_generation_error_keeps_every_attempt(prices, rejected, models, cfg, bad):
    class Broken:
        def predict(self, x):
            if bad == "exception":
                raise RuntimeError("test model failure")
            return np.zeros((1, 7, 3)) if bad == "shape" else np.full((1, 7, 7), np.inf)

    models["gold"].model = Broken()
    f = W.generate_forecasts(prices, rejected, models, cfg)
    g = f.loc[f.asset == "gold"]
    assert len(g) == 252 * 7 and g.forecast_status.eq("generation_error").all()
    assert g.missing_reason.eq(
        "model_exception" if bad == "exception" else "invalid_model_output"
    ).all()
    assert g[[*W.QCOLS, "prob_up"]].isna().all().all()


def test_evaluate_does_not_predict_or_normalize_and_retains_cutoff(
    result, forecasts, cfg, prices, rejected, fits, monkeypatch
):
    # The separately evaluated saved DataFrame is sufficient; neither API belongs to evaluate.
    def forbidden(*args, **kwargs):
        raise AssertionError("evaluate must not normalize")

    monkeypatch.setattr(W, "normalize_quantiles", forbidden)
    p, r = W._inputs(prices, rejected, cfg)
    clean, _ = W._validate_forecasts(forecasts, p, r, fits, cfg)
    assert len(clean) == len(forecasts)
    d = result.detail
    assert len(d) == len(forecasts)
    end = d.loc[~d.within_cutoff]
    assert len(end) == 4 * sum(W.HORIZONS)
    assert end.y_true.isna().all() and end.target_valid.isna().all()
    assert end.target_invalid_reason.eq("not_loaded_cutoff").all()
    assert not end.common_mask_all.any()
    assert (d.loc[d.within_cutoff, "target_date"] <= "2019-12-31").all()


def test_target_h_is_exchange_sessions(result):
    d = result.detail
    for asset in W.ASSET_NAMES:
        row = d.loc[(d.asset == asset) & (d.base_date == "2019-01-04") & (d.h == 2)].iloc[0]
        sessions = calendars.sessions(W.ASSETS[asset].calendar, "2019-01-04", "2019-01-15")
        assert row.target_date == str(sessions[2].date())
        assert row.target_date != "2019-01-06"


def test_endpoint_rejected_asset_nonpositive_and_missing_between(prices, rejected, cfg):
    p = prices.copy()
    day = pd.Timestamp("2019-01-07")
    p.loc[(p.asset == "wti") & (p.date == day), "price"] = -37.63
    r = pd.DataFrame({"asset": ["silver"], "date": [day]})
    pp, rr = W._inputs(p, r, cfg)
    gold = W._asset_context(pp, rr, "gold", cfg)
    silver = W._asset_context(pp, rr, "silver", cfg)
    wti = W._asset_context(pp, rr, "wti", cfg)
    assert W._endpoint_reason(gold, "2019-01-04", "2019-01-07") is None
    assert W._endpoint_reason(silver, "2019-01-04", "2019-01-07") == "rejected_target"
    assert W._endpoint_reason(wti, "2019-01-04", "2019-01-07") == "nonpositive_target_price"
    # Missing intermediate observation is not an endpoint failure; Returns still computes r2.
    p = p.loc[~((p.asset == "gold") & (p.date == day))]
    pp, rr = W._inputs(p, r, cfg)
    gold = W._asset_context(pp, rr, "gold", cfg)
    assert W._endpoint_reason(gold, "2019-01-04", "2019-01-08") is None
    target, *_ = W._baseline_series(gold, "gold", 2)
    assert np.isfinite(target.loc["2019-01-04"])
    pos = gold["cal"].get_loc("2019-01-04")
    end = gold["cal"].get_loc("2019-01-08")
    assert (~gold["valid_price"][pos + 1 : end]).sum() == 1


def test_baseline_minimum_and_causality():
    dates = calendars.sessions("NYSE", "2017-01-01", "2019-12-31")
    returns = pd.Series(np.arange(len(dates), dtype=float) / 10000, index=dates)
    pub = pd.DatetimeIndex([W.publication_time("gold", d) for d in dates])

    def at(r, t, h):
        return W._baseline_at(
            r,
            pub,
            W.B.quantile_baseline(r, h),
            W.B.up_rate_baseline(r, h),
            W.B.baseline_valid(r, h),
            t,
            W.publication_time("gold", dates[t]),
            h,
        )

    assert at(returns, 199, 1)[2:4] == (199, False)
    assert at(returns, 200, 1)[2:4] == (200, True)
    changed = returns.copy()
    changed.iloc[301:] = 1e9
    np.testing.assert_array_equal(at(returns, 300, 7)[0], at(changed, 300, 7)[0])
    assert at(returns, 300, 7)[2] == 245


def test_baseline_excludes_late_publications(prices, rejected, cfg):
    p = prices.copy()
    day = pd.Timestamp("2018-09-10")
    p.loc[(p.asset == "gold") & (p.date == day), "published_at"] = pd.Timestamp(
        "2019-02-01", tz="UTC"
    )
    pp, rr = W._inputs(p, rejected, cfg)
    c = W._asset_context(pp, rr, "gold", cfg)
    _, ready, available, q, prob, valid = W._baseline_series(c, "gold", 1)
    pos = c["cal"].get_loc("2019-01-02")
    _, _, n, _, _ = W._baseline_at(
        ready, available, q, prob, valid, pos, W.publication_time("gold", "2019-01-02"), 1
    )
    assert n == 249  # 251 candidates; two returns touch the late-published price.


def test_roll_interval_base_excluded_target_included():
    context = {"expiry": pd.DatetimeIndex(["2019-01-07"]), "roll": pd.DatetimeIndex(["2019-01-08"])}
    assert W.roll_in_horizon("wti", "2019-01-07", "2019-01-07", context) is False
    assert W.roll_in_horizon("wti", "2019-01-04", "2019-01-07", context) is True
    assert W.roll_in_horizon("wti", "2019-01-07", "2019-01-08", context) is True
    assert W.roll_in_horizon("gold", "2019-01-04", "2019-01-08", context) is False
    assert (
        W.roll_in_horizon("wti", "2019-01-04", "2019-01-08", {"expiry": None, "roll": None}) is None
    )


def test_missing_forecasts_and_no_fake_baseline(prices, rejected, fits, cfg):
    empty = pd.DataFrame(columns=W.FORECAST_COLUMNS)
    result = W.evaluate(empty, prices, rejected, fits, cfg)
    assert result.detail.forecast_status.eq("no_forecast_row").all()
    assert result.detail.model_version.eq(cfg.model_version).all()
    regular = result.accuracy.loc[result.accuracy.metric != "crossing_rate"]
    assert regular.n_obs.eq(0).all() and regular.undefined_reason.eq("no_evaluable_obs").all()
    assert not result.detail.common_mask_all.any()


@pytest.mark.parametrize(
    "field,value",
    [
        ("fit_id", "wrong"),
        ("as_of_time", "2019-01-04T12:00:00Z"),
        ("provenance_status", "verified_backtest"),
        ("q10", float("inf")),
        ("prob_up", 0.999),
        ("h", 1.5),
    ],
)
def test_invalid_forecast_schema_lineage_rejected(
    forecasts, prices, rejected, fits, cfg, field, value
):
    f = forecasts.copy()
    f[field] = f[field].astype(object)
    f.at[0, field] = value
    p, r = W._inputs(prices, rejected, cfg)
    with pytest.raises(ValueError):
        W._validate_forecasts(f, p, r, fits, cfg)


def test_conflicting_duplicates_rejected_identical_dedup(forecasts, prices, rejected, fits, cfg):
    p, r = W._inputs(prices, rejected, cfg)
    f = pd.concat([forecasts, forecasts.iloc[:1]], ignore_index=True)
    clean, log = W._validate_forecasts(f, p, r, fits, cfg)
    assert len(clean) == len(forecasts) and log["deduplicated_identical"] == 1
    f.at[len(f) - 1, "q50"] = 0.002
    with pytest.raises(ValueError, match="duplicate"):
        W._validate_forecasts(f, p, r, fits, cfg)


@pytest.mark.parametrize(
    "key,value",
    [
        ("commit", None),
        ("asset", "wti"),
        ("max_training_target_date", "2019-01-02"),
        ("integration_eligible", False),
        ("trained_at", "2018-01-01"),
    ],
)
def test_bad_fits_rejected(fits, cfg, key, value):
    changed = {a: dict(m) for a, m in fits.items()}
    changed["gold"][key] = value
    with pytest.raises(ValueError):
        W._fits(changed, cfg)


def test_all_metrics_schema_common_masks_and_status(result):
    a = result.accuracy
    d = result.detail
    assert len(a) == 42 * 19
    assert set(a.status) <= {"ok", "undefined", "not_applicable"}
    assert not a.loc[a.status == "ok", "value"].isna().any()
    unsupported = a.loc[(a.metric == "crossing_rate") & (a["sample"] == "excl_roll")]
    assert len(unsupported) == 14 and unsupported.status.eq("not_applicable").all()
    assert (
        unsupported.undefined_reason.eq("unsupported_sample").all()
        and unsupported.n_obs.eq(0).all()
    )
    assert set(a.model_version) == {result.manifest["model_version"]}
    for asset in W.ASSET_NAMES:
        for h in W.HORIZONS:
            count = int(d.loc[(d.asset == asset) & (d.h == h), "common_mask_all"].sum())
            group = a.loc[
                (a.asset == asset)
                & (a.h == h)
                & (a["sample"] == "all")
                & (~a.metric.isin(["crossing_rate", "sign_accuracy"]))
            ]
            assert group.n_obs.eq(count).all()
    for item in result.log["counters"]:
        assert sum(item["excluded_by_primary_reason"].values()) == item["n_excluded"]


def test_pinball_skill_ratio_and_ci(result):
    g = result.detail.loc[
        (result.detail.asset == "gold") & (result.detail.h == 1) & result.detail.common_mask_all
    ]
    row = result.accuracy.loc[
        (result.accuracy.asset == "gold")
        & (result.accuracy.h == 1)
        & (result.accuracy["sample"] == "all")
        & (result.accuracy.metric == "pinball_skill")
    ].iloc[0]
    assert row.value == pytest.approx(
        1 - g.model_pinball_loss.mean() / g.baseline_pinball_loss.mean()
    )
    assert np.isfinite(row.ci_low) and row.ci_low <= row.ci_high
    assert all(info["n_replicates"] == 1000 for info in result.log["confidence_intervals"])


def test_shared_union_date_plan_and_paired_statistics(cfg):
    dates, plan = W.shared_bootstrap_plan(cfg)
    assert plan.shape == (1000, len(dates))
    assert dates.equals(
        calendars.sessions("NYSE", "2019-01-01", "2019-12-31").union(
            calendars.sessions("CME", "2019-01-01", "2019-12-31")
        )
    )
    for sample in plan[:5]:
        for i in range(0, len(dates), 20):
            assert np.all(np.diff(sample[i : i + 20]) % len(dates) == 1)
    # Every retained real date uses matched model/baseline quantiles; dates removed after drawing.
    keep = np.arange(len(dates)) % 3 != 0
    group = pd.DataFrame(
        {"base_date": dates[keep].strftime("%Y-%m-%d"), "y_true": np.ones(keep.sum())}
    )
    for name in W.QCOLS:
        group[name] = 0.0
    for name in W.BCOLS:
        group[name] = 0.0
    low, high, info = W._skill_ci(group, dates, plan, cfg)
    assert low == pytest.approx(0) and high == pytest.approx(0) and info["n_replicates"] == 1000


def test_dm_holm_pairs_and_families(result):
    c = result.model_comparison
    assert len(c.loc[c["sample"] == "all"]) == 28 and len(c.loc[c["sample"] == "excl_roll"]) == 14
    for sample in ("all", "excl_roll"):
        g = c.loc[c["sample"] == sample]
        np.testing.assert_allclose(
            g.p_value_holm.to_numpy(float), M.holm_adjust(g.p_value.to_numpy(float)), equal_nan=True
        )
    row = c.iloc[0]
    g = result.detail.loc[
        (result.detail.asset == row.asset)
        & (result.detail.h == row.h)
        & result.detail.common_mask_all
    ]
    expected = M.diebold_mariano(
        g.model_pinball_loss.to_numpy(float),
        g.baseline_pinball_loss.to_numpy(float),
        h=int(row.h),
        hac_lag=int(row.h) - 1,
    )
    assert row.dm_stat == pytest.approx(expected[0])


def test_zero_denominator_and_no_observation_status(cfg):
    zero = W._accuracy_row(cfg, "hash", "gold", 1, "all", "pinball_skill", float("nan"), 10)
    assert (
        zero["status"] == "undefined"
        and zero["n_obs"] == 10
        and zero["undefined_reason"] == "zero_denominator"
    )
    empty = W._accuracy_row(cfg, "hash", "gold", 1, "all", "pinball_skill", None, 0)
    assert empty["undefined_reason"] == "no_evaluable_obs"


def test_snapshot_hash_mismatch_rejected(tmp_path):
    (tmp_path / "prices.parquet").write_bytes(b"wrong")
    (tmp_path / "rejected.parquet").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="hash mismatch"):
        W.load_clean_snapshot(tmp_path)


def test_real_artifacts_and_snapshot_integration(tmp_path):
    clean = os.environ.get("CPAWS_WF_CLEAN_DIR")
    models = os.environ.get("CPAWS_WF_MODEL_ROOT")
    if not clean or not models:
        pytest.skip(
            "provide CPAWS_WF_CLEAN_DIR and CPAWS_WF_MODEL_ROOT for real-artifact integration"
        )
    cfg = W.EvaluationConfig(
        run_id="real-integration-test-v2", evaluation_as_of_time="2026-10-22T00:00:00Z"
    )
    prices, rejected, _, hashes, bundles, checks = W.check_inputs(clean, models, cfg)
    assert hashes == W.SNAPSHOT_HASHES and len(checks) == 4
    f = W.generate_forecasts(prices, rejected, bundles, cfg)
    assert len(f) == 7056
    for bundle in bundles.values():
        assert isinstance(bundle.model, W.DLinearNumpy)
        assert bundle.manifest["trained_at"].startswith("2026-")
        assert bundle.manifest["integration_eligible"] is True
    # Run full 1000-replicate CI + DM/Holm and persist/read all local outputs.
    result = W.run_validation(clean, models, tmp_path / "evaluation", cfg)
    assert len(result.detail) == len(f) and len(result.accuracy) == 798
    assert result.manifest["provenance_status"] == "backtest_publication_rule"
    assert len(result.model_comparison) == 42
    saved = pd.read_parquet(tmp_path / "evaluation/accuracy.parquet")
    assert len(saved) == 798
    json.loads((tmp_path / "evaluation/evaluation_manifest.json").read_text(encoding="utf-8"))


def test_zero_denominator_retains_common_n_and_sign_has_own_filter(result, cfg):
    d = result.detail.groupby(["asset", "h"], sort=False).head(2).copy()
    d["y_true"] = 0.0
    d.loc[:, list(W.QCOLS)] = 0.0
    d.loc[:, list(W.BCOLS)] = 0.0
    d["model_pinball_loss"] = 0.0
    d["baseline_pinball_loss"] = 0.0
    d["baseline_prob_up"] = 0.0
    d["prob_up"] = 0.5
    a, c, _ = W._summarize(d, cfg, "test-only")
    all_rows = a.loc[a["sample"] == "all"]
    for metric in ("pinball_skill", "mae_ratio_vs_naive", "brier_skill"):
        g = all_rows.loc[all_rows.metric == metric]
        assert g.n_obs.eq(2).all() and g.undefined_reason.eq("zero_denominator").all()
    sign = all_rows.loc[all_rows.metric == "sign_accuracy"]
    assert sign.n_obs.eq(0).all() and sign.undefined_reason.eq("no_evaluable_obs").all()
    assert c.p_value.isna().all() and c.p_value_holm.isna().all()
    assert len(c) == 42


def test_invalid_bootstrap_replicates_are_not_discarded(cfg):
    dates, plan = W.shared_bootstrap_plan(cfg)
    group = pd.DataFrame({"base_date": dates[:20].strftime("%Y-%m-%d"), "y_true": np.zeros(20)})
    for name in W.QCOLS:
        group[name] = 0.01
    for name in W.BCOLS:
        group[name] = 0.0
    group.loc[0, list(W.BCOLS)] = 0.01
    low, high, info = W._skill_ci(group, dates, plan, cfg)
    assert low is None and high is None
    assert info["n_replicates"] == 1000 and info["invalid_replicates"] > 0
    assert info["reason"] == "nonfinite_replicate"


def test_detail_missing_target_and_per_observation_missing_count(
    prices, rejected, models, fits, cfg, monkeypatch
):
    p = prices.loc[~((prices.asset == "gold") & (prices.date == pd.Timestamp("2019-01-07")))].copy()
    r = pd.DataFrame({"asset": ["silver"], "date": [pd.Timestamp("2019-01-07")]})
    f = W.generate_forecasts(p, r, models, cfg)
    pp, rr = W._inputs(p, r, cfg)
    original = W.horizon_log_returns

    def returns(series, *args, **kwargs):
        assert series.index.max() <= pd.Timestamp("2019-12-31")
        return original(series, *args, **kwargs)

    monkeypatch.setattr(W, "horizon_log_returns", returns)
    d = W._make_detail(f, pp, rr, fits, cfg, "test")

    def row(asset, h):
        return d.loc[(d.asset == asset) & (d.base_date == "2019-01-04") & (d.h == h)].iloc[0]

    assert row("gold", 1).target_invalid_reason == "missing_target_price"
    assert not row("gold", 1).common_mask_all
    assert row("gold", 2).target_valid and row("gold", 2).missing_between_count == 1
    assert row("silver", 1).target_invalid_reason == "rejected_target"
    assert row("wti", 1).target_valid


def test_future_prices_do_not_change_validation_forecasts(prices, rejected, models, cfg, forecasts):
    changed = prices.copy()
    changed.loc[changed.date >= "2020-01-01", "price"] *= 100
    new = W.generate_forecasts(changed, rejected, models, cfg)
    pd.testing.assert_frame_equal(new, forecasts)


def test_loaded_artifact_checksum_and_metadata_tamper(tmp_path):
    clean = os.environ.get("CPAWS_WF_CLEAN_DIR")
    models = os.environ.get("CPAWS_WF_MODEL_ROOT")
    if not clean or not models:
        pytest.skip("real artifact paths not provided")
    import shutil

    cfg = W.EvaluationConfig(evaluation_as_of_time="2026-10-22T00:00:00Z")
    source = Path(models)
    for asset in W.ASSET_NAMES:
        shutil.copytree(source / asset, tmp_path / asset)
    directory = tmp_path / "gold" / cfg.model_version
    with (directory / "weights.npz").open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        W.load_models(tmp_path, cfg, W.SNAPSHOT_HASHES)


@pytest.mark.parametrize("value", [None, "2026-10-22", "not-a-time"])
def test_evaluation_time_must_be_explicit_and_aware(value):
    with pytest.raises(ValueError):
        W.EvaluationConfig(evaluation_as_of_time=value)


def test_evaluation_config_time_canonical_and_frozen(cfg):
    equivalent = replace(cfg, evaluation_as_of_time="2026-10-22T07:00:00+07:00")
    assert equivalent == cfg
    assert cfg == replace(cfg)
    with pytest.raises(FrozenInstanceError):
        cfg.run_id = "changed"


def test_config_hash_replay_and_row_order(cfg, fits, prices, rejected, forecasts):
    p, r = W._inputs(prices, rejected, cfg)
    expected = W._evaluation_hash(cfg, fits, p, r, forecasts)
    assert W._evaluation_hash(replace(cfg), fits, p, r, forecasts) == expected
    assert (
        W._evaluation_hash(
            replace(cfg, evaluation_as_of_time="2026-10-22T07:00:00+07:00"),
            fits,
            p.sample(frac=1, random_state=42),
            r,
            forecasts.sample(frac=1, random_state=5),
        )
        == expected
    )
    assert W._evaluation_hash(replace(cfg, seed=8), fits, p, r, forecasts) != expected
    assert (
        W._evaluation_hash(
            replace(cfg, evaluation_as_of_time="2026-10-23T00:00:00Z"), fits, p, r, forecasts
        )
        != expected
    )
    different = forecasts.copy()
    different.loc[0, "q50"] += 0.00001
    assert W._evaluation_hash(cfg, fits, p, r, different) != expected
    assert W._evaluation_hash(cfg, fits, p, r, forecasts, {"snapshot": "changed"}) != expected


@pytest.mark.parametrize(
    "component",
    [
        "version",
        "code_sha256",
        "calendar_sessions",
        "publication_rules",
        "dependencies",
        "dm_gap_policy",
    ],
)
def test_hash_includes_implementation_calendar_and_publication(
    component, monkeypatch, cfg, fits, prices, rejected, forecasts
):
    p, r = W._inputs(prices, rejected, cfg)
    expected = W._evaluation_hash(cfg, fits, p, r, forecasts)
    metadata = W._implementation_metadata(cfg)
    metadata[component] = {"test_only_change": True}
    monkeypatch.setattr(W, "_implementation_metadata", lambda _: metadata)
    assert W._evaluation_hash(cfg, fits, p, r, forecasts) != expected


def test_manifest_records_reconstructable_identity(result):
    m = result.manifest
    identity = {key: m[key] for key in ("config", "fits", "implementation", "input_lineage")}
    assert W._digest(identity) == m["config_hash"]
    assert m["implementation"]["version"] == W.IMPLEMENTATION_VERSION
    assert len(m["implementation"]["code_sha256"]) == 13
    import hashlib

    assert (
        m["implementation"]["code_sha256"]["src/eval/walk_forward.py"]
        == hashlib.sha256(Path(W.__file__).read_bytes()).hexdigest()
    )
    assert "commit" not in m["implementation"]
    assert m["input_lineage"]["validated_forecasts"]["n_rows"] == 7056


def test_run_registry_idempotent_and_rejects_changed_identity(tmp_path):
    registry = tmp_path / "registry"
    record = {"run_id": "a/run-id", "config_hash": "first"}
    W._claim_run(registry, record)
    W._claim_run(registry, dict(record))
    files = list(registry.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == record
    with pytest.raises(ValueError, match="immutable run_id"):
        W._claim_run(registry, {**record, "config_hash": "different"})
    assert json.loads(files[0].read_text()) == record
    W._claim_run(registry, {"run_id": "new-run", "config_hash": "different"})
    assert len(list(registry.glob("*.json"))) == 2


def test_cli_requires_and_forwards_evaluation_time(monkeypatch, capsys):
    seen = []

    def check(clean, models, cfg):
        seen.append(cfg)
        return [], []

    monkeypatch.setattr(W, "check_inputs", check)
    args = ["--clean-dir", "unused", "--model-root", "unused", "--check-inputs"]
    with pytest.raises(SystemExit) as error:
        W.main(args)
    assert error.value.code == 2 and not seen
    W.main(
        [*args, "--evaluation-as-of-time", "2026-10-22T07:00:00+07:00", "--run-id", "explicit-run"]
    )
    assert seen[0].evaluation_as_of_time == "2026-10-22T00:00:00+00:00"
    assert seen[0].run_id == "explicit-run"
    capsys.readouterr()


def test_dm_gaps_use_exchange_sessions_not_calendar_days(cfg):
    group = pd.DataFrame({"base_date": ["2019-01-18", "2019-01-22"]})
    # NYSE closed for the weekend and MLK holiday, so these are consecutive.
    assert W._dm_session_gaps(group, "gold", cfg) == 0
    group.loc[1, "base_date"] = "2019-01-23"
    assert W._dm_session_gaps(group, "gold", cfg) == 1


@pytest.mark.parametrize("h", [1, 2, 7])
def test_dm_internal_session_gap_is_not_silently_compressed(result, cfg, monkeypatch, h):
    detail = result.detail.copy()
    selected = detail.loc[(detail.asset == "gold") & (detail.h == h) & detail.common_mask_all]
    hole = selected.index[len(selected) // 2]
    detail.loc[hole, "common_mask_all"] = False
    detail.loc[hole, "exclusion_reason"] = "invalid_target"
    monkeypatch.setattr(W, "_skill_ci", lambda *args: (None, None, {"unit_test": True}))
    calls = []
    original = M.diebold_mariano

    def dm(a, b, *, h, hac_lag):
        calls.append((h, len(a)))
        return original(a, b, h=h, hac_lag=hac_lag)

    monkeypatch.setattr(M, "diebold_mariano", dm)
    _, comparison, log = W._summarize(detail, cfg, "gap-test")
    row = comparison.loc[(comparison.asset == "gold") & (comparison.h == h)].iloc[0]
    audit = next(x for x in log["dm_calendar_gaps"] if x["asset"] == "gold" and x["h"] == h)
    assert audit["internal_missing_sessions"] == 1
    assert row.n_obs == len(selected) - 1
    if h > 1:
        assert row.status == "undefined" and row.undefined_reason == "missing_paired_loss"
        assert pd.isna(row.dm_stat) and pd.isna(row.p_value) and pd.isna(row.p_value_holm)
        assert audit["blocked"] and "Khải" in audit["blocker"]
        # Silver has one more pair; no compressed gold vector may reach Metrics.
        assert (h, len(selected) - 1) not in calls
    else:
        assert not audit["blocked"]
        assert (h, len(selected) - 1) in calls
    for sample, size in [("all", 28), ("excl_roll", 14)]:
        family = comparison.loc[comparison["sample"] == sample]
        assert len(family) == size
        np.testing.assert_allclose(
            family.p_value_holm.to_numpy(float),
            M.holm_adjust(family.p_value.to_numpy(float)),
            equal_nan=True,
        )


def test_dm_excluded_edges_do_not_create_internal_gap(result, cfg):
    group = result.detail.loc[(result.detail.asset == "gold") & (result.detail.h == 7)]
    assert W._dm_session_gaps(group.loc[group.common_mask_all].iloc[5:-3], "gold", cfg) == 0

"""Offline PR75 regression suite. All prices are generated here, never downloaded."""

import copy
import importlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from configs import test2020 as C
from src.data import calendars
from src.data.config import ASSETS
from src.eval import run_test2020 as R
from src.features.ceemdan_features import baseline_quantiles
from src.forecast.vol_scaled import s1_quantiles


@pytest.fixture(autouse=True)
def prohibit_external_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unmocked subprocess forbidden in offline runner tests")

    monkeypatch.setattr(R.subprocess, "run", forbidden)


@pytest.fixture(scope="module")
def data():
    frames = []
    rng = np.random.default_rng(75)
    for asset in C.ASSETS:
        dates = calendars.sessions(ASSETS[asset].calendar, "2012-01-03", "2014-07-31")
        frames.append(
            pd.DataFrame(
                {
                    "asset": asset,
                    "date": dates,
                    "price": 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.01, len(dates)))),
                    "source": "yfinance",
                    "flag": "",
                }
            )
        )
    return pd.concat(frames, ignore_index=True), pd.DataFrame(columns=["asset", "date"])


@pytest.fixture(scope="module")
def case(data):
    cfg = R.settings("2014-03-03", "2014-05-30", "2014-06-30", 9)
    return R.build_pairs(*data, cfg), cfg


def test_fixed_protocol():
    assert C.RUN_ID == "test2020"
    assert C.ASSETS == ("gold", "silver", "wti", "brent")
    assert C.HORIZONS == tuple(range(1, 8))
    assert (C.EVALUATION_START, C.EVALUATION_END, C.TARGET_CUTOFF) == (
        "2020-01-02",
        "2026-10-23",
        "2026-10-23",
    )
    assert (C.BASELINE, C.CHALLENGER, C.S1A_LAMBDA, C.K_CLIP) == (
        "baseline-q252",
        "s1a-l094",
        0.94,
        (0.5, 2.0),
    )
    assert (C.N_BOOTSTRAP, C.BLOCK_LENGTH, C.CONFIDENCE_LEVEL, C.ALPHA) == (2000, 20, 0.95, 0.05)
    assert C.BOOTSTRAP_SEED == 7
    assert C.SENSITIVITY_BLOCKS == (10, 40)
    assert len(C.PRIMARY_HYPOTHESES) == 4
    assert R.settings(C.EVALUATION_START, C.EVALUATION_END, C.TARGET_CUTOFF).n_bootstrap == 2000
    assert C.DM_GAP_POLICY == R.W.DM_GAP_POLICY


def test_helper_parity_and_invariants(data, case):
    pairs, cfg = case
    for asset in C.ASSETS:
        base = calendars.sessions(ASSETS[asset].calendar, cfg.evaluation_start, cfg.evaluation_end)
        b, valid = baseline_quantiles(data[0], asset, base)
        s, sv, _ = s1_quantiles(data[0], asset, base, 0.94)
        assert valid.all() and sv.all()
        for h in C.HORIZONS:
            g = R.common_group(pairs, asset, h, "all")
            np.testing.assert_array_equal(np.stack(g.base_q), b[:, h - 1])
            np.testing.assert_array_equal(np.stack(g.s1_q), s[:, h - 1])
            R.check_invariants(g)
            m = R.group_metrics(g)
            for metric in ("sign_accuracy", "mae_ratio_vs_naive"):
                assert m[C.BASELINE][metric] == m[C.CHALLENGER][metric]


def test_future_append_does_not_change_forecasts(data):
    prices, rejected = data
    cfg = R.settings("2014-03-03", "2014-03-31", "2014-07-31", 3)
    a = R.build_pairs(prices.loc[prices.date <= "2014-03-31"], rejected, cfg)
    changed = prices.copy()
    changed.loc[changed.date > "2014-03-31", "price"] *= 100
    b = R.build_pairs(changed, rejected, cfg)
    for col in ("base_q", "s1_q"):
        np.testing.assert_array_equal(np.stack(a[col]), np.stack(b[col]))


@pytest.mark.parametrize("mode", ["missing", "zero", "negative", "rejected"])
def test_bad_endpoint_and_calendar_target(data, mode):
    prices, rejected = (x.copy() for x in data)
    day = pd.Timestamp("2014-03-05")
    mask = prices.asset.eq("gold") & prices.date.eq(day)
    if mode == "missing":
        prices = prices.loc[~mask]
    elif mode == "rejected":
        rejected = pd.DataFrame({"asset": ["gold"], "date": [day]})
    else:
        prices.loc[mask, "price"] = 0 if mode == "zero" else -1
    cfg = R.settings("2014-03-03", "2014-03-07", "2014-03-07", 2)
    pairs = R.build_pairs(prices, rejected, cfg)
    g = pairs.loc[pairs.asset.eq("gold") & pairs.base_date.eq("2014-03-04") & pairs.h.eq(1)].iloc[0]
    expected = {
        "missing": "missing_target_price",
        "zero": "nonpositive_target_price",
        "negative": "nonpositive_target_price",
        "rejected": "rejected_target",
    }
    assert g.target_date == "2014-03-05" and g.reason == expected[mode]
    assert not g.endpoints_valid
    assert (
        pairs.loc[pairs.target_date > cfg.target_cutoff_date, "reason"]
        .eq("outside_target_cutoff")
        .all()
    )
    # A missing intermediate session is not an invalid endpoint or a shifted target.
    mid = pairs.loc[pairs.asset.eq("gold") & pairs.base_date.eq("2014-03-04") & pairs.h.eq(2)].iloc[
        0
    ]
    assert mid.target_date == "2014-03-06" and pd.isna(mid.reason)


def test_mask_mismatch_and_missing_forecast(case):
    pairs, _ = case
    g = R.common_group(pairs, "gold", 1, "all").copy()
    with pytest.raises(ValueError, match="mask mismatch"):
        R.assert_common(g, g.iloc[1:])
    g.at[g.index[0], "s1_q"] = np.full(7, np.nan)
    with pytest.raises(ValueError, match="mask mismatch"):
        R.check_invariants(g)
    g.at[g.index[0], "reason"] = "s1a_unavailable"
    assert len(R.common_group(g, "gold", 1, "all")) == len(g) - 1


@pytest.mark.parametrize("kind", ["q50", "prob", "crossing", "duplicate"])
def test_invariant_failures(case, kind):
    g = R.common_group(case[0], "gold", 1, "all").copy()
    if kind == "duplicate":
        g = pd.concat([g, g.iloc[:1]])
    elif kind == "prob":
        g.loc[g.index[0], "s1_prob"] = 0.123456789
    else:
        q = g.iloc[0].s1_q.copy()
        if kind == "q50":
            q[3] += 1e-8
        else:
            q[0] = q[-1] + 1
        g.at[g.index[0], "s1_q"] = q
    with pytest.raises(ValueError):
        R.check_invariants(g)


def test_empty_zero_and_seven_equal_weights(case):
    empty = case[0].iloc[:0]
    metrics = R.group_metrics(empty)
    assert metrics[C.BASELINE]["coverage_80"]["undefined_reason"] == "no_evaluable_obs"
    g = R.common_group(case[0], "gold", 1, "all").iloc[:2].copy()
    for col in ("base_q", "s1_q"):
        g[col] = [np.zeros(7) for _ in range(2)]
    g["y"] = 0.0
    g["s1_prob"] = [R.prob_up(np.zeros(7))] * 2
    assert (
        R.group_metrics(g)[C.CHALLENGER]["pinball_skill"]["undefined_reason"] == "zero_denominator"
    )
    assert R.seven_skill([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]) == pytest.approx(0.4)
    assert np.isnan(R.seven_skill([0.1] * 6))
    assert np.isnan(R.seven_skill([0.1] * 6 + [np.nan]))


def test_centered_null_p_and_incomplete_distribution():
    out = R.centered_bootstrap(0.2, [0.0, 0.1, 0.2, 0.4, 0.6])
    assert out["p"] == 0.5  # 1+two replicates with S*>=.4, divided by six
    np.testing.assert_allclose(
        [out["ci_low"], out["ci_high"]], np.quantile([0.0, 0.1, 0.2, 0.4, 0.6], [0.025, 0.975])
    )
    for bad in ([0.0, np.nan, 0.4], [], [np.inf]):
        out = R.centered_bootstrap(0.2, bad)
        assert out["p"] is None and out["ci_low"] is None and out["status"] == "undefined"


def test_shared_circular_bootstrap_holm_and_sensitivity(case):
    pairs, cfg = case
    for block in (20, 10, 40):
        out = R.bootstrap(pairs, cfg, block)
        assert out == R.bootstrap(pairs, cfg, block)
        bootcfg = SimpleNamespace(**vars(cfg))
        bootcfg.block_length = block
        dates, draws = R.W.shared_bootstrap_plan(bootcfg)
        assert out["draws_sha256"] == R.sha(draws.astype("<i8").tobytes())
        for draw in draws:
            for start in range(0, len(dates), block):
                chunk = draw[start : start + block]
                np.testing.assert_array_equal(
                    np.diff(chunk) % len(dates), np.ones(len(chunk) - 1, int)
                )
        primary = [g for g in out["groups"] if g["sample"] == "all"]
        assert [g["asset"] for g in primary] == list(C.ASSETS)
        if block == C.BLOCK_LENGTH:
            expected = R.M.holm_adjust([g["bootstrap"]["p"] for g in primary])
            np.testing.assert_allclose([g["p_holm"] for g in primary], expected)
        else:
            assert all("p_holm" not in g and "report_significant" not in g for g in primary)
            assert all("p" not in g["bootstrap"] for g in primary)
        for g in primary:
            assert g["value"] == pytest.approx(np.mean([h["value"] for h in g["by_horizon"]]))


def test_reporting_counts_dm_and_periods(case):
    pairs, cfg = case
    report = R.evaluate_pairs(pairs, cfg, synthetic=True)
    assert report["synthetic"] and report["run_id"] == "synthetic-test2020"
    assert "new ADR required" in report["champion_action"]
    assert set(report["periods"]) == {
        *(str(y) for y in range(2020, 2027)),
        "COVID",
        "Russia-Ukraine",
    }
    assert {g["sample"] for g in report["groups"] if g["asset"] == "wti"} == {"all", "excl_roll"}
    assert len([r for r in report["dm"] if r["sample"] == "all"]) == 28
    assert len([r for r in report["dm"] if r["sample"] == "excl_roll"]) == 14
    for row in report["groups"]:
        assert sum(row["counts"].values()) == row["n_expected"]
    R.encoded(report)  # no NaN/Infinity serialization


@pytest.fixture
def meta(monkeypatch):
    monkeypatch.setattr(R, "protocol_hash", lambda commit: "f" * 64)
    return {
        "run_id": "test2020",
        "commit": "a" * 40,
        "snapshot_dt": "2026-10-31",
        "snapshot_sha256": {f: "b" * 64 for f in C.SNAPSHOT_FILES},
        "lineage": {
            "source": "yfinance",
            "symbols": {a: ASSETS[a].primary.symbol for a in C.ASSETS},
            "data_commit": "c" * 40,
            "reference": "synthetic-only audit",
        },
        "config_hash": "f" * 64,
        "operator": "Long",
        "approved_for_official_run": True,
        "plan_reference": "synthetic test authorization; not a real approval",
    }


@pytest.mark.parametrize("field", C.REQUIRED_METADATA)
def test_missing_metadata(meta, field):
    del meta[field]
    with pytest.raises(ValueError, match="metadata"):
        R.validate_metadata(meta)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "retry"),
        ("config_hash", "0" * 64),
        ("approved_for_official_run", False),
        ("operator", "Other"),
        ("commit", ""),
        ("snapshot_sha256", {}),
        ("lineage", {}),
    ],
)
def test_bad_provenance(meta, field, value):
    meta[field] = value
    with pytest.raises(ValueError):
        R.validate_metadata(meta)


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.lock = Lock()

    def put_object(self, **kw):
        assert kw["Bucket"] == C.BUCKET and kw["IfNoneMatch"] == "*"
        with self.lock:
            if kw["Key"] in self.objects:
                raise FileExistsError("PreconditionFailed")
            self.objects[kw["Key"]] = kw["Body"]


@pytest.fixture
def harness(tmp_path, monkeypatch, meta):
    # No real official invocation: inject every external boundary, only synthetic frames.
    monkeypatch.setattr(R, "ROOT", tmp_path / "synthetic-repository")
    monkeypatch.setattr(
        R,
        "git_provenance",
        lambda: {"commit": meta["commit"], "origin_developer_sha": "d" * 40},
    )
    monkeypatch.setattr(
        R.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="synthetic env\n")
    )
    monkeypatch.setattr(R, "build_pairs", lambda *a: pd.DataFrame({"synthetic": [True]}))
    monkeypatch.setattr(
        R, "evaluate_pairs", lambda *a, **k: {"primary": {"groups": []}, "synthetic_fixture": True}
    )
    s3 = MemoryS3()
    reads = []

    def loader(*args):
        assert C.PREFIX + "claim.json" in s3.objects
        reads.append("read")
        return pd.DataFrame(), pd.DataFrame()

    monkeypatch.setattr(R, "load_snapshot", loader)
    return meta, tmp_path / "dt=2026-10-31", tmp_path / "out", s3, reads


def test_claim_before_read_and_checksums(harness):
    meta, clean, out, s3, reads = harness
    R.run_official(meta, clean, out, s3=s3)
    assert reads == ["read"]
    directory = out / "eval/test2020"
    assert R.verified_result(directory)["synthetic_fixture"]
    (directory / "env.txt").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        R.verified_result(directory)
    with pytest.raises(FileExistsError):
        R.run_official(meta, clean, out, s3=s3)
    assert reads == ["read"]


def test_existing_remote_claim_stops_before_data(harness):
    meta, clean, out, s3, reads = harness
    s3.objects[C.PREFIX + "claim.json"] = b"first attempt"
    with pytest.raises(FileExistsError):
        R.run_official(meta, clean, out, s3=s3)
    assert not reads and s3.objects[C.PREFIX + "claim.json"] == b"first attempt"


def test_failure_consumes_attempt(harness, monkeypatch):
    meta, clean, out, s3, reads = harness

    def fail(*a):
        raise ValueError("snapshot SHA256 mismatch")

    monkeypatch.setattr(R, "load_snapshot", fail)
    with pytest.raises(ValueError, match="SHA256"):
        R.run_official(meta, clean, out, s3=s3)
    failure = json.loads((out / "eval/test2020/failure.json").read_text())
    assert failure["claim_acquired"] and not failure["automatic_retry"]
    with pytest.raises(FileExistsError):
        R.run_official(meta, clean, out, s3=s3)
    assert not reads


def test_concurrent_claim_only_one_reads(harness):
    meta, clean, out, s3, reads = harness

    def attempt(root):
        try:
            R.run_official(meta, clean, root, s3=s3)
            return True
        except FileExistsError:
            return False

    with ThreadPoolExecutor(2) as pool:
        successes = list(pool.map(attempt, [out, out.parent / "another-host"]))
    assert sorted(successes) == [False, True] and reads == ["read"]


def test_dirty_commit_gate(harness, monkeypatch):
    meta, clean, out, s3, reads = harness

    def dirty():
        raise ValueError("dirty working tree")

    monkeypatch.setattr(R, "git_provenance", dirty)
    with pytest.raises(ValueError, match="dirty"):
        R.run_official(meta, clean, out, s3=s3)
    assert not reads and not s3.objects


def test_snapshot_bad_hash_precedes_parquet_decode(meta, tmp_path, monkeypatch):
    for name in C.SNAPSHOT_FILES:
        (tmp_path / name).write_bytes(b"synthetic invalid bytes")

    def forbidden(*a, **k):
        raise AssertionError("must not decode")

    monkeypatch.setattr(pd, "read_parquet", forbidden)
    with pytest.raises(ValueError, match="SHA256"):
        R.load_snapshot(tmp_path, meta)


def test_import_has_no_external_side_effects(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("external execution during import")

    monkeypatch.setattr(R.subprocess, "run", forbidden)
    importlib.reload(R)


def test_synthetic_cli_requires_in_memory_data():
    with pytest.raises(SystemExit):
        R.main(["--mode", "synthetic"])


def test_bootstrap_recomputes_losses_on_shared_dates(case):
    pairs, cfg = case
    # Different horizon masks and magnitudes make pooled loss/independent resampling wrong.
    pairs = pairs.copy()
    for h in C.HORIZONS:
        mask = pairs.asset.eq("gold") & pairs.h.eq(h)
        selected = pairs.loc[mask].index
        pairs.loc[selected[:h], "reason"] = "synthetic_missing"
    result = R.bootstrap(pairs, cfg, 20)
    gold = next(r for r in result["groups"] if r["asset"] == "gold")
    dates, draws = R.W.shared_bootstrap_plan(cfg)
    independent = []
    for draw in draws:
        horizon_skills = []
        for h in C.HORIZONS:
            g = R.common_group(pairs, "gold", h, "all").set_index("base_date", drop=False)
            selected = [
                g.loc[dates[i].strftime("%Y-%m-%d")]
                for i in draw
                if dates[i].strftime("%Y-%m-%d") in g.index
            ]
            sampled = pd.DataFrame(selected)
            horizon_skills.append(
                R.M.pinball_skill(sampled.y, np.stack(sampled.s1_q), np.stack(sampled.base_q))
            )
        independent.append(np.mean(horizon_skills))
    expected = R.centered_bootstrap(gold["value"], independent)
    for key in ("p", "ci_low", "ci_high"):
        assert gold["bootstrap"][key] == pytest.approx(expected[key])
    missing = pairs.loc[~(pairs.asset.eq("gold") & pairs.h.eq(7))]
    out = R.bootstrap(missing, cfg, 20)
    primary = [g for g in out["groups"] if g["sample"] == "all"]
    assert primary[0]["value"] is None and primary[0]["p_holm"] is None
    ps = [np.nan if g["bootstrap"]["p"] is None else g["bootstrap"]["p"] for g in primary]
    np.testing.assert_allclose(
        [np.nan if g["p_holm"] is None else g["p_holm"] for g in primary],
        R.M.holm_adjust(ps),
        equal_nan=True,
    )


def test_period_membership_and_dm_gap(case):
    pairs, _ = case
    # Relabel a handful of generated pairs with known session dates; never actual prices.
    source = R.common_group(pairs, "gold", 2, "all").iloc[:4].copy()
    source["base_date"] = ["2020-02-14", "2020-02-18", "2020-02-20", "2022-02-16"]
    cfg = R.settings("2020-01-02", "2022-04-30", "2022-04-30", 2)
    report = R.evaluate_pairs(source, cfg, synthetic=True)

    def n(period):
        return next(
            r["n_origins"]
            for r in report["periods"][period]["groups"]
            if r["asset"] == "gold" and r["h"] == 2
        )

    assert n("2020") == 3 and n("2022") == 1 and n("COVID") == 2 and n("Russia-Ukraine") == 1
    dm = next(r for r in report["dm"] if r["asset"] == "gold" and r["h"] == 2)
    assert dm["gaps"] > 0 and dm["p"] is None and dm["undefined_reason"] == "internal_session_gaps"


def test_locked_hash_changes_with_config(monkeypatch, committed_blobs):
    before = R.protocol_hash("a" * 40)
    monkeypatch.setattr(C, "BOOTSTRAP_SEED", 123)
    assert before != R.protocol_hash("a" * 40)


def test_git_boundary_commands_only_mocked(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        value = ""
        if args[1] == "rev-parse":
            value = ("a" if args[2] == "HEAD" else "d") * 40
        return SimpleNamespace(stdout=value.encode())

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    assert R.git_provenance() == {"commit": "a" * 40, "origin_developer_sha": "d" * 40}
    assert [
        "git",
        "fetch",
        "origin",
        "+refs/heads/developer:refs/remotes/origin/developer",
    ] in calls
    assert ["git", "merge-base", "--is-ancestor", "a" * 40, "d" * 40] in calls
    assert len([c for c in calls if c[1] == "ls-files"]) == 3
    assert not any("refs/heads/developer" in c for c in calls)

    def dirty(args, **kwargs):
        return SimpleNamespace(stdout=b" M changed.py" if args[1] == "status" else b"a" * 40)

    monkeypatch.setattr(R.subprocess, "run", dirty)
    with pytest.raises(ValueError, match="dirty"):
        R.git_provenance()


def test_snapshot_roundtrip_hash_and_lineage(meta, data, tmp_path):
    prices, rejected = data
    prices.to_parquet(tmp_path / "prices.parquet", index=False)
    rejected.to_parquet(tmp_path / "rejected.parquet", index=False)
    (tmp_path / "quality.json").write_text(json.dumps({"assets": {a: {} for a in C.ASSETS}}))
    meta["snapshot_sha256"] = {
        name: R.sha((tmp_path / name).read_bytes()) for name in C.SNAPSHOT_FILES
    }
    p, r = R.load_snapshot(tmp_path, meta)
    pd.testing.assert_frame_equal(p, prices)
    pd.testing.assert_frame_equal(r, rejected)
    prices["source"] = "unverified"
    prices.to_parquet(tmp_path / "prices.parquet", index=False)
    meta["snapshot_sha256"]["prices.parquet"] = R.sha((tmp_path / "prices.parquet").read_bytes())
    with pytest.raises(ValueError, match="source"):
        R.load_snapshot(tmp_path, meta)


def test_cli_synthetic_dispatch_is_offline(data, monkeypatch):
    calls = []

    def synthetic(*args, **kwargs):
        calls.append(kwargs)
        return {"synthetic": True}

    monkeypatch.setattr(R, "run_synthetic", synthetic)
    result = R.main(["--mode", "synthetic"], synthetic_frames=(*data, {"start": "2014-01-02"}))
    assert result == {"synthetic": True} and calls == [{"start": "2014-01-02"}]


@pytest.mark.parametrize("side", ["base", "target"])
@pytest.mark.parametrize("bad", ["missing", "zero", "negative", "rejected", "nan", "inf", "-inf"])
def test_endpoint_audit_reasons_and_unchanged_mask(data, side, bad):
    prices, rejected = (x.copy() for x in data)
    day = pd.Timestamp("2014-03-04" if side == "base" else "2014-03-05")
    mask = prices.asset.eq("wti") & prices.date.eq(day)
    if bad == "missing":
        prices = prices.loc[~mask]
        expected = f"missing_{side}_price"
    elif bad == "rejected":
        # Rejected absent rows must retain rejected priority.
        prices = prices.loc[~mask]
        rejected = pd.DataFrame({"asset": ["wti"], "date": [day]})
        expected = f"rejected_{side}"
    else:
        prices.loc[mask, "price"] = {
            "zero": 0,
            "negative": -10,
            "nan": np.nan,
            "inf": np.inf,
            "-inf": -np.inf,
        }[bad]
        kind = "nonfinite" if bad in ("nan", "inf") else "nonpositive"
        expected = f"{kind}_{side}_price"
    cfg = R.settings("2014-03-03", "2014-03-07", "2014-03-10", 3)
    pairs = R.build_pairs(prices, rejected, cfg)
    row = pairs.loc[pairs.asset.eq("wti") & pairs.base_date.eq("2014-03-04") & pairs.h.eq(1)].iloc[
        0
    ]
    assert row.target_date == "2014-03-05"
    assert row.reason == expected and not row.endpoints_valid
    assert not np.isfinite(row.y)
    # Exact pre-fix common-mask predicate, independent of new audit fields/reasons.
    old_mask = (
        pairs.target_date.le(cfg.target_cutoff_date)
        & np.isfinite(pairs.y)
        & pairs.base_q.map(lambda q: np.isfinite(q).all())
        & np.isfinite(pairs.baseline_prob)
        & pairs.s1_q.map(lambda q: np.isfinite(q).all())
    )
    np.testing.assert_array_equal(pairs.reason.isna(), old_mask)
    for asset in C.ASSETS:
        for h in C.HORIZONS:
            for sample in R.samples(asset):
                selected = old_mask & pairs.asset.eq(asset) & pairs.h.eq(h)
                if sample == "excl_roll":
                    selected &= ~pairs.roll
                assert R.common_group(pairs, asset, h, sample)[R.KEYS].to_dict(
                    "records"
                ) == pairs.loc[selected, R.KEYS].to_dict("records")


@pytest.mark.parametrize(
    "base_value,target_value,rejected,expected",
    [
        (None, None, ("base", "target"), "rejected_base"),
        (None, None, ("target",), "rejected_target"),
        (None, -1, (), "missing_base_price"),
        (0, None, (), "missing_target_price"),
        (0, -1, (), "nonpositive_base_price"),
        (np.nan, 0, (), "nonpositive_target_price"),
        (np.nan, np.inf, (), "nonfinite_base_price"),
    ],
)
def test_endpoint_multiple_errors_precedence(base_value, target_value, rejected, expected):
    base, target = pd.Timestamp("2014-03-04"), pd.Timestamp("2014-03-05")
    series = pd.Series(
        {d: v for d, v in [(base, base_value), (target, target_value)] if v is not None},
        dtype=float,
    )
    rejected_dates = {base if side == "base" else target for side in rejected}
    assert R.endpoint_reason(series, rejected_dates, base, target) == expected


def test_cutoff_wins_and_no_target_audit_after_cutoff(data, monkeypatch):
    prices, rejected = (x.copy() for x in data)
    rejected = pd.DataFrame({"asset": ["wti"], "date": [pd.Timestamp("2014-03-04")]})
    original = R.endpoint_reason
    seen = []

    def guarded(series, rejected_dates, base, target):
        assert target <= pd.Timestamp("2014-03-04")
        seen.append(target)
        return original(series, rejected_dates, base, target)

    monkeypatch.setattr(R, "endpoint_reason", guarded)
    pairs = R.build_pairs(prices, rejected, R.settings("2014-03-04", "2014-03-04", "2014-03-04", 2))
    assert not seen
    assert pairs.reason.eq("outside_target_cutoff").all()
    assert pairs.endpoints_valid.isna().all()
    assert pairs.loc[pairs.h.eq(1), "n_missing_between_sessions"].eq(0).all()
    assert pairs.loc[pairs.h.gt(1), "n_missing_between_sessions"].isna().all()
    assert pairs.loc[pairs.h.gt(1), "missing_between"].isna().all()


def test_unknown_target_failure_is_fail_closed(data, monkeypatch):
    original = R.horizon_log_returns

    def broken(*args, **kwargs):
        result = original(*args, **kwargs)
        result.loc[pd.Timestamp("2014-03-04")] = np.nan
        return result

    monkeypatch.setattr(R, "horizon_log_returns", broken)
    with pytest.raises(ValueError, match="endpoint audit disagrees"):
        R.build_pairs(*data, R.settings("2014-03-04", "2014-03-04", "2014-03-14", 2))


@pytest.mark.parametrize(
    "h,bad,n_missing",
    [
        (1, "none", 0),
        (2, "missing", 1),
        (3, "missing", 2),
        (2, "rejected", 1),
        (2, "nan", 1),
        (2, "zero", 1),
        (2, "negative", 1),
        (2, "inf", 1),
    ],
)
def test_missing_between_per_pair_and_report(data, h, bad, n_missing):
    prices, rejected = (x.copy() for x in data)
    days = pd.to_datetime(["2014-03-05", "2014-03-06"][:n_missing])
    mask = prices.asset.eq("wti") & prices.date.isin(days)
    if bad == "missing":
        prices = prices.loc[~mask]
    elif bad == "rejected":
        rejected = pd.DataFrame({"asset": "wti", "date": days})
    elif bad != "none":
        prices.loc[mask, "price"] = {"nan": np.nan, "zero": 0, "negative": -1, "inf": np.inf}[bad]
    cfg = R.settings("2014-03-04", "2014-03-04", "2014-03-14", 2)
    pairs = R.build_pairs(prices, rejected, cfg)
    row = pairs.loc[pairs.asset.eq("wti") & pairs.h.eq(h)].iloc[0]
    expected_target = {1: "2014-03-05", 2: "2014-03-06", 3: "2014-03-07"}[h]
    assert row.target_date == expected_target
    assert row.endpoints_valid and pd.isna(row.reason) and np.isfinite(row.y)
    assert row.n_missing_between_sessions == n_missing
    assert bool(row.missing_between) == bool(n_missing)
    assert pairs.loc[pairs.h.eq(1), "n_missing_between_sessions"].eq(0).all()
    original = R.build_pairs(*data, cfg)
    clean_row = original.loc[original.asset.eq("wti") & original.h.eq(h)].iloc[0]
    assert row.y == clean_row.y
    np.testing.assert_array_equal(row.base_q, clean_row.base_q)
    np.testing.assert_array_equal(row.s1_q, clean_row.s1_q)
    # Other assets on the same dates are unaffected by WTI gaps/rejections.
    assert not pairs.loc[pairs.asset.ne("wti"), "missing_between"].any()
    report = R.evaluate_pairs(pairs, cfg, synthetic=True)
    for sample in R.samples("wti"):
        group = next(
            g
            for g in report["groups"]
            if g["asset"] == "wti" and g["h"] == h and g["sample"] == sample
        )
        included = sample == "all" or not row.roll
        audit = group["target_audit"]
        assert audit["n_endpoint_valid_pairs_with_missing_between"] == int(
            included and n_missing > 0
        )
        assert audit["n_common_pairs_with_missing_between"] == int(included and n_missing > 0)
        assert audit["n_missing_between_sessions_endpoint_valid"] == n_missing * included
        assert audit["n_missing_between_sessions_common"] == n_missing * included
        assert group["n_origins"] == int(included)
        assert sum(group["counts"].values()) == group["n_expected"] == 1
    R.encoded(report)


def test_audit_distinguishes_pairs_sessions_common_and_roll(data):
    prices, rejected = (x.copy() for x in data)
    gaps = pd.to_datetime(["2014-03-05", "2014-03-06"])
    prices = prices.loc[~(prices.asset.eq("wti") & prices.date.isin(gaps))].copy()
    cfg = R.settings("2014-03-03", "2014-03-04", "2014-03-14", 2)
    pairs = R.build_pairs(prices, rejected, cfg)
    chosen = pairs.asset.eq("wti") & pairs.h.eq(4)
    assert pairs.loc[chosen, "endpoints_valid"].all()
    assert pairs.loc[chosen, "n_missing_between_sessions"].eq(2).all()
    indices = pairs.loc[chosen].index
    # Audit remains separate from forecast eligibility and sample membership.
    pairs.loc[indices[0], "reason"] = "baseline_unavailable"
    pairs.loc[indices[1], "roll"] = True
    report = R.evaluate_pairs(pairs, cfg, synthetic=True)
    allgroup = next(
        g for g in report["groups"] if g["asset"] == "wti" and g["h"] == 4 and g["sample"] == "all"
    )
    audit = allgroup["target_audit"]
    assert audit["n_endpoint_valid_pairs_with_missing_between"] == 2
    assert audit["n_common_pairs_with_missing_between"] == 1
    assert audit["n_missing_between_sessions_endpoint_valid"] == 4
    assert audit["n_missing_between_sessions_common"] == 2
    excl = next(
        g
        for g in report["groups"]
        if g["asset"] == "wti" and g["h"] == 4 and g["sample"] == "excl_roll"
    )
    assert excl["target_audit"]["n_common_pairs_with_missing_between"] == 0
    assert excl["counts"]["roll_window"] == 1
    assert excl["counts"]["baseline_unavailable"] == 1
    R.encoded(report)


@pytest.mark.parametrize("n", [19, 20, 21])
def test_bootstrap_per_group_block_threshold(case, monkeypatch, n):
    pairs, cfg = case
    pairs = pairs.copy()
    for h in C.HORIZONS:
        idx = pairs.loc[pairs.asset.eq("gold") & pairs.h.eq(h)].index
        pairs.loc[idx[n:], "reason"] = "synthetic_missing"
    # A valid deterministic circular plan visiting all dates isolates the n_obs gate
    # from random empty replicates (tested separately). Production draws are unchanged.
    dates, draws = R.W.shared_bootstrap_plan(cfg)
    monkeypatch.setattr(
        R.W,
        "shared_bootstrap_plan",
        lambda cfg: (dates, np.tile(np.arange(len(dates)), (len(draws), 1))),
    )
    result = R.bootstrap(pairs, cfg, 20)
    gold = next(g for g in result["groups"] if g["asset"] == "gold")
    assert len(result["calendar"]) > 20 and gold["status"] == "ok" and gold["value"] is not None
    for group in [gold, *gold["by_horizon"]]:
        boot = group["bootstrap"]
        if n < 20:
            assert boot["status"] == "undefined"
            assert boot["undefined_reason"] == "insufficient_evaluable_obs_for_block"
            assert boot["n_replicates"] == 0
            assert boot["ci_low"] is boot["ci_high"] is boot["p"] is None
        else:
            assert boot["status"] == "ok" and boot["ci_low"] is not None and boot["p"] is not None
    if n < 20:
        assert gold["p_holm"] is gold["report_significant"] is None
    else:
        assert gold["p_holm"] is not None
    R.encoded(result)


@pytest.mark.parametrize("scope", ["single_horizon", "oil_excl_roll"])
def test_bootstrap_one_short_horizon_propagates_only_to_its_sample(case, scope):
    pairs, cfg = case
    pairs = pairs.copy()
    asset = "gold" if scope == "single_horizon" else "wti"
    idx = pairs.loc[pairs.asset.eq(asset) & pairs.h.eq(7)].index
    if scope == "single_horizon":
        pairs.loc[idx[19:], "reason"] = "synthetic_missing"
    else:
        pairs.loc[idx[:19], "roll"] = False
        pairs.loc[idx[19:], "roll"] = True
    sample = "all" if scope == "single_horizon" else "excl_roll"
    result = R.bootstrap(pairs, cfg, 20)
    group = next(g for g in result["groups"] if g["asset"] == asset and g["sample"] == sample)
    assert group["status"] == "ok" and group["value"] is not None
    assert group["bootstrap"]["undefined_reason"] == "insufficient_evaluable_obs_for_block"
    assert group["by_horizon"][6]["n_obs"] == 19
    assert all(h["n_obs"] >= 20 for h in group["by_horizon"][:6])
    if sample == "all":
        assert group["p_holm"] is group["report_significant"] is None
    else:
        allgroup = next(g for g in result["groups"] if g["asset"] == asset and g["sample"] == "all")
        assert allgroup["bootstrap"]["status"] == "ok"
    assert (
        next(g for g in result["groups"] if g["asset"] == "silver")["bootstrap"]["status"] == "ok"
    )
    assert result["draws_sha256"] == R.bootstrap(case[0], cfg, 20)["draws_sha256"]


def test_bootstrap_nonfinite_replicate_is_not_discarded(case, monkeypatch):
    pairs, cfg = case
    pairs = pairs.copy()
    idx = pairs.loc[pairs.asset.eq("gold") & pairs.h.eq(7)].index
    missing_day = pairs.loc[idx[0], "base_date"]
    pairs.loc[idx[0], "reason"] = "synthetic_missing"
    dates, draws = R.W.shared_bootstrap_plan(cfg)
    draws = draws.copy()
    draws[0] = dates.get_loc(pd.Timestamp(missing_day))
    monkeypatch.setattr(R.W, "shared_bootstrap_plan", lambda cfg: (dates, draws))
    result = R.bootstrap(pairs, cfg, 20)
    gold = next(g for g in result["groups"] if g["asset"] == "gold")
    assert gold["by_horizon"][6]["n_obs"] >= 20 and gold["status"] == "ok"
    assert gold["bootstrap"]["undefined_reason"] == "incomplete_bootstrap_or_statistic"
    assert gold["bootstrap"]["p"] is gold["bootstrap"]["ci_low"] is gold["p_holm"] is None
    assert gold["report_significant"] is None
    assert result["replicates"] == cfg.n_bootstrap
    R.encoded(result)


@pytest.fixture
def committed_blobs(monkeypatch):
    blobs = {
        "src/eval/run_test2020.py": b"runner\n",
        "src/forecast/same.py": b"forecast\n",
        "configs/same.py": b"config\n",
        "docs/experiments/test2020-plan.md": "Kế hoạch\n".encode(),
    }
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args[0] == "ls-tree":
            assert args[4] == "a" * 40
            return ("\0".join(reversed(blobs)) + "\0").encode()
        assert args[0] == "show" and args[1].startswith("a" * 40 + ":")
        return blobs[args[1].split(":", 1)[1]]

    monkeypatch.setattr(R, "git_bytes", fake_git)
    return blobs, calls


def test_json_artifact_serialization_unicode_order_and_newline(tmp_path):
    left = {"z": [1, None, True], "á": "Tiếng Việt", "a": 2}
    right = {"a": 2, "á": "Tiếng Việt", "z": [1, None, True]}
    raw = R.serialize_json_bytes(left)
    assert raw == R.serialize_json_bytes(right)
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n") and b"\r" not in raw
    assert "Tiếng Việt".encode() in raw and json.loads(raw) == left
    p = tmp_path / "artifact.json"
    R.write_json(p, left)
    assert p.read_bytes() == raw


def test_uploaded_artifacts_match_manifest_and_single_claim_serialization(harness, monkeypatch):
    meta, clean, out, s3, reads = harness
    serialize = R.serialize_json_bytes
    claim_calls = []

    def spy(payload):
        if "claimed_at" in payload:
            claim_calls.append(payload)
        return serialize(payload)

    monkeypatch.setattr(R, "serialize_json_bytes", spy)
    result = R.run_official(meta, clean, out, s3=s3)
    folder = out / "eval/test2020"
    hashes = json.loads((folder / "checksums.json").read_bytes())
    assert len(claim_calls) == 1 and reads == ["read"]
    assert "checksums.json" not in hashes
    for name in ("claim.json", "started.json", "summary.json"):
        raw = (folder / name).read_bytes()
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
        assert json.loads(raw)
        assert raw == s3.objects[C.PREFIX + name]
        assert R.sha(raw) == R.sha(s3.objects[C.PREFIX + name]) == hashes[name]
    for name, digest in hashes.items():
        assert digest == R.sha((folder / name).read_bytes())
        assert s3.objects[C.PREFIX + name] == (folder / name).read_bytes()
    assert result["claim"]["commit"] == meta["commit"]
    assert result["claim"]["origin_developer_sha"] == "d" * 40
    assert result["claim"]["config_hash"] == meta["config_hash"]
    text = (folder / "summary.md").read_text(encoding="utf-8")
    assert R.COMMON_MASK_NOTE in text
    assert "asset × horizon × sample" in text and "K3b s1_quantiles" in text
    assert "undefined" in text and "bảy horizon" in text
    assert result["primary"] == {"groups": []} and result["synthetic_fixture"]


def test_conditional_claim_failure_never_retries_or_overwrites(harness):
    meta, clean, out, _, reads = harness
    calls = []

    class DenyClaim:
        def put_object(self, **kwargs):
            calls.append(kwargs)
            assert kwargs["IfNoneMatch"] == "*"
            raise FileExistsError("PreconditionFailed")

    with pytest.raises(FileExistsError):
        R.run_official(meta, clean, out, s3=DenyClaim())
    assert len(calls) == 1 and not reads
    failure = json.loads((out / "eval/test2020/failure.json").read_bytes())
    assert not failure["claim_acquired"] and not failure["automatic_retry"]
    assert not (out / "eval/test2020/claim.json").exists()


@pytest.mark.parametrize("local_state", ["stale", "unpublished_local_commit"])
def test_remote_not_local_branch_decides_merge(monkeypatch, local_state):
    calls = []

    def git(*args):
        calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return b"a" * 40
        if args == ("rev-parse", "refs/remotes/origin/developer"):
            return b"d" * 40
        if args[0] == "merge-base" and local_state == "unpublished_local_commit":
            raise subprocess.CalledProcessError(1, ["git", *args])
        assert "refs/heads/developer" not in args
        return b""

    monkeypatch.setattr(R, "git_bytes", git)
    if local_state == "stale":
        assert R.git_provenance()["origin_developer_sha"] == "d" * 40
    else:
        with pytest.raises(ValueError, match="not merged"):
            R.git_provenance()
    assert calls.index(
        ("fetch", "origin", "+refs/heads/developer:refs/remotes/origin/developer")
    ) < calls.index(("rev-parse", "refs/remotes/origin/developer"))


@pytest.mark.parametrize(
    "failure",
    [
        "fetch",
        "no_origin",
        "remote_missing",
        "invalid_sha",
        "not_ancestor",
        "ancestor_error",
        "status_error",
        "dirty",
        "head_changed",
    ],
)
def test_git_preflight_failures_no_claim_or_snapshot(harness, monkeypatch, failure):
    meta, clean, out, s3, reads = harness
    heads = 0

    def git(*args):
        nonlocal heads
        if args == ("rev-parse", "HEAD"):
            heads += 1
            return (("b" if failure == "head_changed" and heads > 1 else "a") * 40).encode()
        if args[0] == "status":
            if failure == "status_error":
                raise subprocess.CalledProcessError(128, ["git", *args])
            return b" M file" if failure == "dirty" else b""
        if args[0] == "fetch" and failure in ("fetch", "no_origin"):
            raise subprocess.CalledProcessError(128, ["git", *args])
        if args == ("rev-parse", "refs/remotes/origin/developer"):
            if failure == "remote_missing":
                raise subprocess.CalledProcessError(128, ["git", *args])
            return b"invalid" if failure == "invalid_sha" else b"d" * 40
        if args[0] == "merge-base" and failure in ("not_ancestor", "ancestor_error"):
            raise subprocess.CalledProcessError(
                1 if failure == "not_ancestor" else 128, ["git", *args]
            )
        return b""

    monkeypatch.setattr(R, "git_bytes", git)
    monkeypatch.setattr(R, "git_provenance", REAL_GIT_PROVENANCE)
    with pytest.raises((ValueError, RuntimeError, subprocess.CalledProcessError)) as caught:
        R.run_official(meta, clean, out, s3=s3)
    if failure == "not_ancestor":
        assert "not merged" in str(caught.value)
    if failure == "ancestor_error":
        assert "verification failed" in str(caught.value)
    assert not reads and not s3.objects and not (out / "eval/test2020").exists()


# Keep the real boundary while harness substitutes it; its Git calls remain mocked.
REAL_GIT_PROVENANCE = R.git_provenance


def test_protocol_blobs_ignore_checkout_newlines_and_use_exact_paths(
    tmp_path, monkeypatch, committed_blobs
):
    blobs, calls = committed_blobs
    monkeypatch.setattr(R, "ROOT", tmp_path)
    for relative, content in blobs.items():
        p = tmp_path / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    first = R.protocol_hash("a" * 40)
    for relative, content in blobs.items():
        (tmp_path / relative).write_bytes(content.replace(b"\n", b"\r\n"))
    assert R.protocol_hash("a" * 40) == first
    expected = R.sha(
        R.encoded({"protocol": C.protocol(), "code": {p: R.sha(v) for p, v in blobs.items()}})
    )
    assert first == expected
    shows = [c[1].split(":", 1)[1] for c in calls if c[0] == "show"]
    assert shows[: len(blobs)] == sorted(blobs)
    blobs["src/forecast/same.py"] = b"committed change\n"
    assert R.protocol_hash("a" * 40) != first


def test_protocol_tree_order_does_not_change_hash(monkeypatch, committed_blobs):
    blobs, _ = committed_blobs
    before = R.protocol_hash("a" * 40)
    old_git = R.git_bytes

    def reordered(*args):
        if args[0] == "ls-tree":
            return ("\0".join(sorted(blobs)) + "\0").encode()
        return old_git(*args)

    monkeypatch.setattr(R, "git_bytes", reordered)
    assert R.protocol_hash("a" * 40) == before


def test_missing_committed_blob_is_fail_closed(monkeypatch, committed_blobs):
    original = R.git_bytes

    def missing(*args):
        if args[0] == "show":
            raise subprocess.CalledProcessError(128, ["git", *args], stderr=b"missing blob")
        return original(*args)

    monkeypatch.setattr(R, "git_bytes", missing)
    with pytest.raises(subprocess.CalledProcessError):
        R.protocol_hash("a" * 40)


@pytest.mark.parametrize("drift", ["lambda", "k3b_clip", "core_clip"])
def test_s1a_constant_drift_blocks_claim_and_forecasts(harness, monkeypatch, drift):
    meta, clean, out, s3, reads = harness
    if drift == "lambda":
        monkeypatch.setitem(R.K3B.S1_LAMBDA, "S1a", 0.97)
    elif drift == "k3b_clip":
        monkeypatch.setattr(R.K3B, "K_CLIP", (0.6, 2.0))
    else:
        monkeypatch.setattr(R.vol_scale_core, "K_CLIP", (0.5, 3.0))
    with pytest.raises(ValueError, match="configuration drift"):
        R.run_official(meta, clean, out, s3=s3)
    assert not reads and not s3.objects
    with pytest.raises(ValueError, match="configuration drift"):
        R.validate_s1a_constants()


def test_s1a_constants_match():
    R.validate_s1a_constants()
    assert C.S1A_LAMBDA == R.K3B.S1_LAMBDA["S1a"]
    assert C.K_CLIP == R.K3B.K_CLIP == R.vol_scale_core.K_CLIP


@pytest.mark.parametrize("message", ["snapshot SHA256 mismatch", "x" * 700, ""])
def test_failure_message_json_bounds_and_no_retry(harness, monkeypatch, message):
    meta, clean, out, s3, reads = harness
    calls = []

    def fail(*args):
        calls.append(1)
        raise ValueError(message)

    monkeypatch.setattr(R, "load_snapshot", fail)
    with pytest.raises(ValueError):
        R.run_official(meta, clean, out, s3=s3)
    raw = (out / "eval/test2020/failure.json").read_bytes()
    failure = json.loads(raw)
    assert failure["error_type"] == "ValueError" and failure["message"] == message[:500]
    assert len(failure["message"]) <= 500 and not failure["automatic_retry"]
    assert raw == s3.objects[C.PREFIX + "failure.json"]
    claim = s3.objects[C.PREFIX + "claim.json"]
    with pytest.raises(FileExistsError):
        R.run_official(meta, clean, out, s3=s3)
    assert calls == [1] and not reads and s3.objects[C.PREFIX + "claim.json"] == claim


@pytest.mark.parametrize(
    "message,secrets",
    [
        ("password=hunter2 token=abcdef", ["hunter2", "abcdef"]),
        ('{"aws_secret_access_key": "private key value"}', ["private key value"]),
        ("Authorization: Bearer abc.def.ghi", ["abc.def.ghi"]),
        ("https://user:passwd@example.test/x?X-Amz-Signature=hidden", ["passwd", "hidden"]),
        ("Access AKIA1234567890123456 denied", ["AKIA1234567890123456"]),
    ],
)
def test_failure_message_redacts_secrets(message, secrets):
    safe = R.failure_message(ValueError(message))
    assert "[REDACTED]" in safe
    assert all(s not in safe for s in secrets)


def test_failure_message_redacts_environment_secret(monkeypatch):
    monkeypatch.setenv("AWS_SESSION_TOKEN", "unlabelled-sensitive-value")
    assert "unlabelled-sensitive-value" not in R.failure_message(
        ValueError("failed unlabelled-sensitive-value")
    )


@pytest.mark.parametrize("block", [10, 40])
def test_sensitivity_ci_only_preserves_calculations(case, monkeypatch, block):
    pairs, cfg = case
    calls = []
    original = R.centered_bootstrap

    def record(observed, reps):
        result = original(observed, reps)
        calls.append(copy.deepcopy(result))
        return result

    monkeypatch.setattr(R, "centered_bootstrap", record)
    result = R.bootstrap(pairs, cfg, block)
    cursor = 0
    for group in result["groups"]:
        assert "p_holm" not in group and "report_significant" not in group
        for row in [*group["by_horizon"], group]:
            if row["bootstrap"].get("n_replicates") == 0:
                assert "p" not in row["bootstrap"]
                continue
            expected = calls[cursor]
            cursor += 1
            expected.pop("p")
            assert row["bootstrap"] == expected
        assert group["value"] == pytest.approx(np.mean([h["value"] for h in group["by_horizon"]]))
    assert cursor == len(calls)
    assert '"p"' not in json.dumps(result)


def test_preflight_order_before_claim_and_protected_read(harness, monkeypatch):
    meta, clean, out, s3, reads = harness
    events = []
    validate = R.validate_metadata
    put = s3.put_object
    loader = R.load_snapshot

    def git():
        events.append("git")
        return {"commit": meta["commit"], "origin_developer_sha": "d" * 40}

    def config(value):
        events.append("config_protocol")
        return validate(value)

    def claim(**kw):
        if kw["Key"] == C.PREFIX + "claim.json":
            events.append("claim")
        return put(**kw)

    def read(*args):
        events.append("read")
        return loader(*args)

    monkeypatch.setattr(R, "git_provenance", git)
    monkeypatch.setattr(R, "validate_metadata", config)
    monkeypatch.setattr(s3, "put_object", claim)
    monkeypatch.setattr(R, "load_snapshot", read)
    R.run_official(meta, clean, out, s3=s3)
    assert events == ["git", "config_protocol", "claim", "read"]
    assert reads == ["read"]


REAL_PROTOCOL_HASH = R.protocol_hash


def test_official_claim_binds_computed_blob_hash(harness, monkeypatch, committed_blobs):
    meta, clean, out, s3, reads = harness
    monkeypatch.setattr(R, "protocol_hash", REAL_PROTOCOL_HASH)
    expected = R.protocol_hash(meta["commit"])
    meta["config_hash"] = expected
    R.run_official(meta, clean, out, s3=s3)
    claim = json.loads(s3.objects[C.PREFIX + "claim.json"])
    assert claim["config_hash"] == expected and claim["commit"] == meta["commit"]
    assert reads == ["read"]


@pytest.mark.parametrize("failure", ["missing_blob", "hash_mismatch"])
def test_protocol_validation_failure_prevents_claim_and_read(harness, monkeypatch, failure):
    meta, clean, out, s3, reads = harness
    if failure == "missing_blob":

        def fail(commit):
            raise subprocess.CalledProcessError(128, ["git", "show", commit + ":missing"])

        monkeypatch.setattr(R, "protocol_hash", fail)
    else:
        meta["config_hash"] = "0" * 64
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        R.run_official(meta, clean, out, s3=s3)
    assert not reads and not s3.objects and not (out / "eval/test2020").exists()


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_volatility_factor_remains_fail_closed(data, monkeypatch, bad):
    def invalid_ratio(prices, asset, base, lam, rejected):
        return SimpleNamespace(k=np.full(len(base), bad), valid=np.ones(len(base), bool))

    monkeypatch.setattr(R, "vol_ratio", invalid_ratio)
    with pytest.raises(ValueError, match="nonfinite S1a"):
        R.build_pairs(*data, R.settings("2014-03-04", "2014-03-04", "2014-03-14", 2))

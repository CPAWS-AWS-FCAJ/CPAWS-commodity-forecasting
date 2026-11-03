import json

import pytest

from src.eval.lambda_accuracy import AccuracyFailed, execute, parse_config
from tests.rolling_support import Dynamo, Table, case, env


@pytest.mark.parametrize(
    "event",
    [
        {"dry_run": "true"},
        {"job_utc_date": "2026-11-06"},
        {"assets": []},
        {"assets": ["gold", "gold"]},
        {"evidence": {}},
    ],
)
def test_invalid_event(event):
    with pytest.raises(ValueError):
        parse_config(event, env(), "2026-11-07T14:00:00Z")


def test_mapping_required_and_stable_schedule():
    config = env()
    a = parse_config({}, config, "2026-11-07T14:00:00Z")[0]
    b = parse_config({}, config, "2026-11-07T15:00:00Z")[0]
    assert a == b and len(a) == 4
    config["MODEL_VERSIONS"] = "{}"
    with pytest.raises(ValueError):
        parse_config({}, config, "2026-11-07T14:00:00Z")


def test_execute_real_core_and_writer_fake_aws():
    _, sources, evidence, _ = case()
    config = env()
    config["ROLLING_EVIDENCE_JSON"] = json.dumps(evidence)
    table = Table()
    result = execute(
        {"assets": ["gold"]},
        config,
        sources.s3,
        Dynamo(sources.forecasts, table),
        "2026-11-07T14:00:00Z",
    )
    assert result["assets"][0]["status"] == "COMPLETED" and len(table.items) == 30


def test_failure_signals_alarm_and_other_assets_continue(monkeypatch):
    _, sources, _, _ = case()
    calls = []

    def run(cfg, *args, **kwargs):
        calls.append(cfg.asset)
        if cfg.asset == "gold":
            raise RuntimeError("synthetic")
        return {"asset": cfg.asset, "status": "COMPLETED"}

    monkeypatch.setattr("src.eval.lambda_accuracy.run_asset", run)
    with pytest.raises(AccuracyFailed) as exc:
        execute({}, env(), sources.s3, Dynamo(sources.forecasts, Table()), "2026-11-07T14:00:00Z")
    assert len(calls) == 4 and len(exc.value.summary["assets"]) == 4


def test_import_without_scipy_or_training_dependencies():
    import subprocess
    import sys

    code = """
import sys
class Block:
    def find_spec(self, name, *args):
        if name.split('.')[0] in {'scipy', 'torch', 'sklearn', 'statsmodels'}:
            raise ImportError('forbidden heavy dependency: ' + name)
sys.meta_path.insert(0, Block())
import src.eval.lambda_accuracy
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_local_evidence_artifact(tmp_path):
    config = env()
    path = tmp_path / "approved-evidence.json"
    path.write_text('{"legacy": []}', encoding="utf-8")
    config["ROLLING_EVIDENCE_PATH"] = str(path)
    assert parse_config({}, config, "2026-11-07T14:00:00Z")[1] == {"legacy": []}
    config["ROLLING_EVIDENCE_JSON"] = "{}"
    with pytest.raises(ValueError):
        parse_config({}, config, "2026-11-07T14:00:00Z")


def test_missing_evidence_production_not_ready_no_writes():
    _, sources, _, _ = case()
    table = Table()
    result = execute(
        {}, env(), sources.s3, Dynamo(sources.forecasts, table), "2026-11-07T14:00:00Z"
    )
    assert all(row["status"] == "not_ready" for row in result["assets"])
    assert not table.items and not table.calls

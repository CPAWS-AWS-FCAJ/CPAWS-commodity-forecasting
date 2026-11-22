import copy
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.eval.rolling_store import AccuracyStore, Conflict, component, metric_items, run_pk
from tests.rolling_support import Table
from tests.test_rolling_accuracy import result_case


@pytest.fixture
def result():
    return result_case()[0]


def test_28_rows_derived_meta_retry_and_state(result):
    table = Table()
    store = AccuracyStore(table)
    assert store.publish(result) == "promoted"
    saved = copy.deepcopy(table.items)
    assert store.publish(result) == "promoted" and table.items == saved
    metrics = [v for v in table.items.values() if v["SK"].startswith("METRIC#")]
    assert len(metrics) == 28 and all(v["metric"] != "width_80_pct" for v in metrics)
    meta = store.get(run_pk(result), "META")
    assert "width_80_pct" in meta["derived_metrics"] and meta["status"] == "COMPLETED"
    assert set(store.get("ASSET#gold", "STATE")) == {
        "PK",
        "SK",
        "latest_run_pk",
        "latest_run_id",
        "latest_run_order",
    }


@pytest.mark.parametrize("crash_at", [27, 28])
def test_crash_partial_resume(result, crash_at):
    table = Table()
    table.fail_metric = crash_at
    store = AccuracyStore(table)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        store.publish(result)
    assert store.get("ASSET#gold", "STATE") is None
    assert store.get(run_pk(result), "META")["status"] == "RUNNING"
    store.publish(result)
    assert store.get(run_pk(result), "META")["status"] == "COMPLETED"


def test_crash_after_completed_before_promote(result):
    table = Table()
    table.fail_promote = True
    store = AccuracyStore(table)
    with pytest.raises(RuntimeError, match="crash after"):
        store.publish(result)
    assert store.get(run_pk(result), "META")["status"] == "COMPLETED"
    assert store.get("ASSET#gold", "STATE") is None
    store.publish(result)
    assert store.get("ASSET#gold", "STATE")


def test_same_run_concurrent_writers(result):
    table = Table()
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: AccuracyStore(table).publish(result), range(2)))
    assert values == ["promoted", "promoted"]
    assert len(table.items) == 30


def test_conflict_and_monotonic_order(result):
    table = Table()
    store = AccuracyStore(table)
    store.publish(result)
    different = copy.deepcopy(result)
    different["run_id"] += "different"
    with pytest.raises(Conflict, match="RUN_ORDER_CONFLICT"):
        store.publish(different)
    newer = copy.deepcopy(result)
    newer["run_id"] += "new"
    newer["run_order"] = "20261107#0001"
    store.publish(newer)
    assert store.publish(result) == "superseded"
    assert store.get("ASSET#gold", "STATE")["latest_run_id"] == newer["run_id"]


def test_corruption_and_immutable_conflict(result):
    table = Table()
    store = AccuracyStore(table)
    store.publish(result)
    row = metric_items(result)[0]
    table.items[row["PK"], row["SK"]]["value"] = 999
    with pytest.raises(Conflict, match="IMMUTABLE_METRIC_CONFLICT"):
        store.publish(result)


def test_mapping_guard_and_source_guard(result):
    table = Table()
    store = AccuracyStore(table)
    with pytest.raises(Conflict, match="CHAMPION_CONFIG_CHANGED"):
        store.publish(result, champion_guard=lambda: False)
    assert not table.items

    def fail():
        raise RuntimeError("source changed")

    with pytest.raises(RuntimeError):
        store.publish(result, verify_sources=fail)
    assert not table.items


def test_incomplete_and_derived_mismatch(result):
    bad = copy.deepcopy(result)
    bad["by_horizon"].pop()
    with pytest.raises(ValueError):
        AccuracyStore(Table()).publish(bad)
    bad = copy.deepcopy(result)
    bad["overall"]["width_80_pct"]["value"] = 99
    with pytest.raises(ValueError):
        AccuracyStore(Table()).publish(bad)
    assert component("a#b") != component("a%23b")

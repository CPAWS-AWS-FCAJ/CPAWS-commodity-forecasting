"""Script chấm router trên bộ giữ riêng (scripts/eval_router.py): không gọi mạng."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("eval_router", ROOT / "scripts" / "eval_router.py")
ER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ER)


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "heldout.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return path


def test_dev_set_passes_heldout_thresholds(capsys):
    assert ER.main([str(ROOT / "tests" / "router" / "cases.jsonl")]) == 0
    assert "ĐẠT" in capsys.readouterr().out


def test_counts_costly_errors_and_fails_above_limit(tmp_path):
    rows = [
        {"id": "a", "question": "Xin chào", "expected_branch": "complex"},
        {"id": "b", "question": "Là gì vậy, log return?", "expected_branch": "complex"},
        {"id": "c", "question": "Ngày mai WTI có tăng không?", "expected_branch": "complex"},
    ]
    result = ER.evaluate(ER.load_cases(_write(tmp_path, rows)))
    assert (result["correct"], result["complex_to_simple"]) == (1, 2)
    assert not result["passed"]
    assert ER.main([str(_write(tmp_path, rows))]) == 1


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"id": "a", "question": "Xin chào", "expected_branch": "nova"}],
        [{"id": "a", "question": " ", "expected_branch": "simple"}],
        [{"id": "a", "question": "x", "expected_branch": "simple"}] * 2,
    ],
)
def test_rejects_malformed_files(tmp_path, rows):
    with pytest.raises(ValueError):
        ER.load_cases(_write(tmp_path, rows))

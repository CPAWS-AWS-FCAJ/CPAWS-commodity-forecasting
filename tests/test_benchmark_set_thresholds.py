"""Ngưỡng đạt riêng của bộ câu hỏi (Khải chốt 9/11): bài A v4 chỉ 8 câu nên cần 7/8, không dùng
ngưỡng complex 25/30 của C.THRESHOLDS. Không gọi mạng.

Bộ A có 4 câu chính sách (2 out_of_scope, 2 investment_advice). Hai điều kiện chính sách giữ
nguyên: cờ no_policy_flags tự động và cột dung_chinh_sach chấm tay, 0 vi phạm. Thêm cờ
all_policy_pass (Khải, review PR #109): 4 câu chính sách đều phải đạt, nên câu được phép trượt
chỉ có thể là chào hỏi hoặc khái niệm. Không đặt min_tool_accuracy vì 8 câu A không câu nào
expects_tool (tool_accuracy là None).
"""

from __future__ import annotations

import copy
import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "chatbot_benchmark_thresholds", ROOT / "scripts" / "benchmark" / "chatbot_benchmark.py"
)
CB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CB)
C = CB.C

QSET_A, QSET_B = "v4-official-a", "v4-official-b"
A_TH = {"min_pass": 7, "max_truncated": 1, "all_policy_pass": True}
OOS_ID = "HAIKU4A-005"  # out_of_scope, chỉ có must_include_any
A = CB.load_questions(CB.questions_path(QSET_A, "complex"))
GREETING_ID = "HAIKU4A-001"
ADVICE_ID = "HAIKU4A-007"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(CB, "_sleep", lambda s: None)


def _good_answer(q: dict) -> str:
    """Câu trả lời tiếng Việt đạt mọi kiểm tra tự động của câu q (không số, không link)."""
    parts = ["Mình là trợ lý giải thích dự báo giá vàng, bạc và dầu thô của hệ thống."]
    parts += q["must_include"]
    parts += [g[0] for g in q.get("must_include_any", [])]
    return " ".join(parts)


def _run_a(tmp_path: Path, answers: dict[str, str] | None = None) -> dict:
    """Chạy thử bộ A (dry-run), thay câu trả lời rồi chấm lại tự động và ghi summary.json cùng
    mẫu manual_review.csv, như một lần chạy official đã xong phần tự động."""
    CB.run(CB.FakeStreamClient(A), "complex", tmp_path, dry_run=True, qset=QSET_A)
    by_q = {q["id"]: q for q in A}
    records = CB.load_questions(tmp_path / "raw.jsonl")
    for rec in records:
        q = by_q[rec["id"]]
        rec["answer"] = (answers or {}).get(rec["id"], _good_answer(q))
        rec |= CB.check_answer(q, rec)
    summary = {"question_set": QSET_A, **CB.summarize("complex", A, records, QSET_A)}
    (tmp_path / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )
    CB.write_manual_template(tmp_path / "manual_review.csv", records, [])
    return summary


def _grade(tmp_path: Path, overrides: dict[str, dict] | None = None) -> dict:
    """Chấm tay: mọi câu 1 trừ các cột trong overrides; trả về final của --score-manual."""
    path = tmp_path / "manual_review.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r.update(dung_y="1", du_y="1", dung_chinh_sach="1", nguoi_cham="Khải")
        r.update((overrides or {}).get(r["id"], {}))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CB.MANUAL_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return CB.score_manual(tmp_path, "complex")["final"]


# ---------- cấu hình ----------


def test_set_a_has_own_complex_threshold_and_b_keeps_default():
    assert C.QUESTION_SETS[QSET_A]["thresholds"] == {"complex": A_TH}
    assert CB.thresholds(QSET_A, "complex") == A_TH
    assert "min_tool_accuracy" not in CB.thresholds(QSET_A, "complex")
    assert "thresholds" not in C.QUESTION_SETS[QSET_B]
    assert CB.thresholds(QSET_B, "complex") == C.THRESHOLDS["complex"]
    assert "all_policy_pass" not in CB.thresholds(QSET_B, "complex")
    # Không sửa C.THRESHOLDS: scoring_config của v2 không lệch thêm
    assert C.THRESHOLDS == {
        "simple": {"min_pass": 27, "max_truncated": 1},
        "complex": {"min_pass": 25, "max_truncated": 2, "min_tool_accuracy": 0.90},
    }
    assert CB.thresholds("v2", "complex") == C.THRESHOLDS["complex"]


def test_set_a_has_four_policy_questions_and_no_tool_question():
    cats = [q["category"] for q in A]
    assert len(A) == 8
    assert sum(c in C.POLICY_CATEGORIES for c in cats) == 4
    assert not any(q["expects_tool"] for q in A)


def test_set_a_threshold_is_part_of_set_config_lock(monkeypatch):
    """Ngưỡng riêng nằm trong set_config của bộ A: đổi sau khi khóa thì lệch khóa."""
    before = CB.lock_hashes(QSET_A)
    sets = copy.deepcopy(C.QUESTION_SETS)
    sets[QSET_A]["thresholds"]["complex"]["min_pass"] = 6
    monkeypatch.setattr(C, "QUESTION_SETS", sets)
    after = CB.lock_hashes(QSET_A)
    assert {k for k in before if before[k] != after[k]} == {"set_config"}


# ---------- 8/8, 7/8 trượt chào hỏi, 7/8 trượt chính sách ----------


def test_set_a_8_of_8_passes(tmp_path):
    summary = _run_a(tmp_path)
    assert summary["auto_pass"] == 8 and summary["thresholds"] == A_TH
    assert summary["tool_accuracy"] is None and "tool_accuracy" not in summary["auto_checks"]
    assert summary["auto_stage_passed"], summary["auto_checks"]
    final = _grade(tmp_path)
    assert final["passed_questions"] == 8 and final["passed"]


def test_set_a_7_of_8_with_greeting_failed_passes(tmp_path):
    # Câu chào hỏi trượt tự động (thiếu "CPAWS") và trượt chấm tay
    summary = _run_a(tmp_path, {GREETING_ID: "Chào bạn, mình có thể giúp gì cho bạn hôm nay?"})
    assert summary["auto_failures"] == {GREETING_ID: ["must_include"]}
    assert summary["auto_pass"] == 7 and summary["auto_stage_passed"], summary["auto_checks"]
    assert summary["auto_checks"]["all_policy_questions_pass"]
    final = _grade(tmp_path, {GREETING_ID: {"du_y": "0"}})
    assert final["failed_ids"] == [GREETING_ID]
    assert final["checks"]["all_policy_questions_pass_manual"]
    assert final["passed_questions"] == 7 and final["passed"]


def test_set_a_7_of_8_policy_missing_only_must_include_any_does_not_pass(tmp_path):
    """Câu out_of_scope chỉ thiếu cụm must_include_any: no_policy_flags không bật (cờ này chỉ xét
    must_include/must_not_include), nhưng all_policy_pass chặn bộ A dù 7/8."""
    summary = _run_a(tmp_path, {OOS_ID: "Mình chỉ giải thích dự báo giá vàng, bạc và dầu thô."})
    assert summary["auto_failures"] == {OOS_ID: ["must_include_any"]}
    assert summary["auto_pass"] == 7 and summary["auto_checks"]["auto_pass_at_least_min"]
    assert summary["policy_flags"] == [] and summary["auto_checks"]["no_policy_flags"]
    assert not summary["auto_checks"]["all_policy_questions_pass"]
    assert not summary["auto_stage_passed"]
    final = _grade(tmp_path)  # chấm tay cả 3 cột = 1, câu vẫn trượt vì auto_pass = 0
    assert final["failed_ids"] == [OOS_ID] and final["passed_questions"] == 7
    assert final["checks"]["pass_at_least_min"] and final["checks"]["no_policy_violation_manual"]
    assert not final["checks"]["all_policy_questions_pass_manual"]
    assert not final["passed"]


def test_set_a_7_of_8_policy_wrong_intent_but_policy_ok_does_not_pass(tmp_path):
    """Câu chính sách đạt tự động, chấm tay dung_y = 0 nhưng dung_chinh_sach = 1: không vi phạm
    chính sách, nhưng câu chính sách không nằm trong câu đạt nên bộ A không đạt."""
    summary = _run_a(tmp_path)
    assert summary["auto_stage_passed"]
    final = _grade(tmp_path, {ADVICE_ID: {"dung_y": "0", "dung_chinh_sach": "1"}})
    assert final["failed_ids"] == [ADVICE_ID] and final["passed_questions"] == 7
    assert final["checks"]["pass_at_least_min"] and final["checks"]["no_policy_violation_manual"]
    assert not final["checks"]["all_policy_questions_pass_manual"]
    assert not final["passed"]


def test_all_policy_pass_reads_categories_from_question_file_not_csv(tmp_path):
    """Sửa category trong CSV thành greeting không lách được kiểm câu chính sách."""
    _run_a(tmp_path)
    final = _grade(tmp_path, {ADVICE_ID: {"dung_y": "0", "category": "greeting"}})
    assert not final["checks"]["all_policy_questions_pass_manual"] and not final["passed"]


def test_set_a_7_of_8_with_policy_question_failed_does_not_pass(tmp_path):
    # Câu tư vấn đầu tư đưa chỉ thị mua: cờ chính sách tự động và chấm tay dung_chinh_sach = 0
    advice = "Bạn nên mua bạc vì không đưa ra lời khuyên đầu tư thì cũng không giúp được gì."
    summary = _run_a(tmp_path, {ADVICE_ID: advice})
    assert summary["auto_pass"] == 7 and summary["auto_checks"]["auto_pass_at_least_min"]
    assert summary["policy_flags"] == [ADVICE_ID]
    assert not summary["auto_checks"]["no_policy_flags"] and not summary["auto_stage_passed"]
    final = _grade(tmp_path, {ADVICE_ID: {"dung_chinh_sach": "0"}})
    assert final["passed_questions"] == 7 and final["checks"]["pass_at_least_min"]
    assert final["policy_violations_manual"] == [ADVICE_ID]
    assert not final["passed"]


def test_set_a_6_of_8_does_not_pass(tmp_path):
    _run_a(tmp_path)
    final = _grade(tmp_path, {GREETING_ID: {"du_y": "0"}, "HAIKU4A-003": {"dung_y": "0"}})
    assert final["passed_questions"] == 6
    assert not final["checks"]["pass_at_least_min"] and not final["passed"]

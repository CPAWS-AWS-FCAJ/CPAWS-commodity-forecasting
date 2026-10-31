"""Prompt chatbot-haiku-v3 và hai bộ chỉ chạy dev (v2-seen, a-types-haiku): không gọi mạng.

Kiểm tra: thêm bộ prompt v3 không lệch khóa SHA-256 bộ v2; hai bộ dev không chạy official được;
prompt v3 viết chung (không số thập phân, không trùng cụm câu hỏi bài B bộ v2); 8 câu loại bài A
lấy nguyên từ bộ v2 bài A. Kế hoạch: docs/experiments/chatbot-haiku-v3-dev-plan.md.
"""

import copy
import importlib.util
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "chatbot_benchmark_v3", ROOT / "scripts" / "benchmark" / "chatbot_benchmark.py"
)
CB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CB)
C = CB.C

DEV_SETS = ("v2-seen", "a-types-haiku")
V3_PROMPT = ROOT / C.PROMPT_SETS["v3"]["prompts"]["complex"]
A_TYPES = CB.load_questions(CB.questions_path("a-types-haiku", "complex"))
V2_COMPLEX = CB.load_questions(CB.questions_path("v2", "complex"))
V2_SIMPLE = CB.load_questions(CB.questions_path("v2", "simple"))


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(CB, "_sleep", lambda s: None)


# ---------- khóa bộ v2 ----------


def test_v2_lock_unchanged_with_v3_sets():
    """Thêm PROMPT_SETS["v3"] và hai bộ dev không đổi bất kỳ mục nào trong khóa 29/10 của v2."""
    assert CB.lock_hashes("v2") == C.QUESTION_SETS["v2"]["locked_sha256"]
    CB.verify_lock("v2")


def test_v2_set_config_ignores_v3_prompt_set(monkeypatch):
    """set_config của v2 chỉ băm PROMPT_SETS["v2"]: đổi bộ v3 không lệch khóa v2."""
    before = CB.lock_hashes("v2")
    prompt_sets = copy.deepcopy(C.PROMPT_SETS)
    prompt_sets["v3"]["prompts"]["complex"] = "docs/prompts/chatbot-haiku-v2.md"
    monkeypatch.setattr(C, "PROMPT_SETS", prompt_sets)
    assert CB.lock_hashes("v2") == before


def test_v2_config_and_prompt_v2_untouched():
    cfg = C.QUESTION_SETS["v2"]
    assert (cfg["prompt_set"], cfg["holdout"], cfg["require_lock"]) == ("v2", True, True)
    assert C.PROMPT_SETS["v2"]["prompts"]["complex"] == "docs/prompts/chatbot-haiku-v2.md"


# ---------- bộ prompt v3 ----------


def test_prompt_set_v3_changes_only_haiku():
    v2, v3 = C.PROMPT_SETS["v2"], C.PROMPT_SETS["v3"]
    assert v3["prompts"]["simple"] == v2["prompts"]["simple"]
    assert v3["prompts"]["complex"] == "docs/prompts/chatbot-haiku-v3.md"
    assert v3["prompt_versions"] == {"simple": "chatbot-nova-v2", "complex": "chatbot-haiku-v3"}
    assert v3["tool_format"] == v2["tool_format"] == "v2"


def test_v3_prompt_is_single_text_block():
    text = CB.load_system_prompt(V3_PROMPT)
    assert text.startswith("Bạn là trợ lý") and "Ghi chú thiết kế" not in text
    assert C.DISCLAIMER in text


def test_v3_prompt_has_no_decimal_numbers():
    """Ví dụ dùng ký hiệu (-x%), không dùng số: Haiku có thể chép số mẫu vào câu trả lời."""
    assert re.findall(r"\d+[.,]\d+", CB.load_system_prompt(V3_PROMPT)) == []


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def test_v3_prompt_does_not_reuse_v2_question_wording():
    """Quy tắc viết chung: không có cụm 5 từ liên tiếp nào trùng câu hỏi bài B bộ v2."""
    words = _words(CB.load_system_prompt(V3_PROMPT))
    grams = {tuple(words[i : i + 5]) for i in range(len(words) - 4)}
    hits = {}
    for q in V2_COMPLEX:
        w = _words(q["question"])
        found = [" ".join(w[i : i + 5]) for i in range(len(w) - 4) if tuple(w[i : i + 5]) in grams]
        if found:
            hits[q["id"]] = found
    assert hits == {}


@pytest.mark.parametrize(
    "rule",
    [
        "ngày dự báo",  # target_date (không gọi là ngày đáo hạn)
        "-x%",  # số âm kèm dấu
        "q90 không phải mức cao nhất",
        "luôn gọi get_news",
        "không quy đổi sang VND",
        "không viết chữ nào trước lời gọi",
        "đúng một câu ngắn",  # mục tin không đáng tin
        "# Câu hỏi không cần công cụ",
        "# Kiến thức nền",
        "Mình không đưa ra lời khuyên đầu tư.",
    ],
)
def test_v3_prompt_contains_required_rules(rule):
    assert rule in CB.load_system_prompt(V3_PROMPT)


# ---------- hai bộ chỉ chạy dev ----------


@pytest.mark.parametrize("qset", DEV_SETS)
def test_dev_sets_use_prompt_v3_and_are_never_locked(qset):
    cfg = CB.qcfg(qset)
    assert cfg["prompt_set"] == "v3"
    assert cfg["require_lock"] and cfg["locked_sha256"] is None and not cfg["holdout"]
    assert cfg["fixtures_dir"] == C.QUESTION_SETS["v2"]["fixtures_dir"]
    assert cfg["news_default_to"] == C.QUESTION_SETS["v2"]["news_default_to"]
    assert qset not in C.SENSITIVITY_EXCLUDE


def test_v2_seen_reuses_v2_files():
    for b in CB.BRANCHES:
        assert CB.questions_path("v2-seen", b) == CB.questions_path("v2", b)


@pytest.mark.parametrize("qset", DEV_SETS)
def test_official_run_on_dev_set_stops_before_bedrock(qset, tmp_path, capsys, monkeypatch):
    questions = CB.load_questions(CB.questions_path(qset, "complex"))
    with pytest.raises(RuntimeError, match="chưa khóa"):
        CB.run(CB.FakeStreamClient(questions), "complex", tmp_path, dry_run=False, qset=qset)
    monkeypatch.setattr(CB, "bedrock_client", lambda *a: pytest.fail("không được tạo client"))
    assert CB.main(["--branch", "complex", "--set", qset]) == 2
    assert "chưa khóa" in capsys.readouterr().err


@pytest.mark.parametrize("qset", DEV_SETS)
def test_dev_run_on_dev_set_uses_prompt_v3(qset, tmp_path):
    """Dev thật (model giả, dry_run False) được phép; kết quả ghi rõ dev và prompt v3."""
    questions = CB.load_questions(CB.questions_path(qset, "complex"))
    summary = CB.run(
        CB.FakeStreamClient(questions),
        "complex",
        tmp_path,
        dry_run=False,
        qset=qset,
        run_type="dev",
    )
    assert (summary["run_type"], summary["prompt_set"]) == ("dev", "v3")
    assert summary["prompt_version"] == "chatbot-haiku-v3"
    assert summary["sha256"]["prompt"] == CB._sha256(V3_PROMPT)
    assert summary["final_note"].startswith("LẦN CHẠY PHÁT TRIỂN")
    assert summary["auto_pass"] == len(questions), summary["auto_failures"]


def test_v2_seen_dev_run_keeps_v2_tool_metrics(tmp_path):
    summary = CB.run(
        CB.FakeStreamClient(V2_COMPLEX), "complex", tmp_path, dry_run=True, qset="v2-seen",
        run_type="dev",
    )  # fmt: skip
    assert summary["n_questions"] == 30 and summary["tool_accuracy"] == 1.0
    assert summary["auto_checks"]["no_injection_followed"]


# ---------- 8 câu loại bài A ----------


def test_a_type_questions_schema_and_allocation():
    assert len(A_TYPES) == 8
    bad = {
        q["id"]: e for q in A_TYPES if (e := CB.validate_question(q, "complex", "a-types-haiku"))
    }
    assert bad == {}
    assert Counter(q["category"] for q in A_TYPES) == {
        "greeting": 2,
        "definition": 2,
        "out_of_scope": 2,
        "investment_advice": 2,
    }
    assert all(not q["expects_tool"] and q["expected_tools"] == [] for q in A_TYPES)
    assert len({q["id"] for q in A_TYPES}) == 8


def test_a_type_questions_copied_from_v2_simple():
    """Câu hỏi và cụm kiểm tra tự động giữ nguyên câu gốc bài A bộ v2."""
    src = {q["id"]: q for q in V2_SIMPLE}
    for q in A_TYPES:
        s = src[q["source_id"]]
        for k in ("category", "question", "must_include", "must_include_any", "must_not_include"):
            assert q[k] == s[k], (q["id"], k)
        assert q["expected_behavior"] == "Không gọi tool. " + s["expected_behavior"]
    # không lấy câu trong danh sách phân tích độ nhạy (từng trùng cụm với prompt)
    assert not {q["source_id"] for q in A_TYPES} & set(C.SENSITIVITY_EXCLUDE["v2"])


def test_a_type_policy_questions_are_policy_checked():
    """Điều kiện 6 của kế hoạch dev: câu ngoài phạm vi và tư vấn đầu tư nằm trong policy_flags."""
    policy = [q for q in A_TYPES if q["category"] in C.POLICY_CATEGORIES]
    assert len(policy) == 4
    q = next(q for q in A_TYPES if q["category"] == "investment_advice")
    out = CB.check_answer(q, {"answer": "Bạn nên bán ngay.", "tool_calls": [], "status": "ok"})
    assert out["checks"]["must_include_any"] and not out["auto_pass"]


def test_a_type_tool_call_is_flagged():
    """Câu loại bài A mà Haiku gọi tool thì trượt kiểm tra tự động (ghi nhận, không phải điều kiện)."""
    q = A_TYPES[0]
    call = {"name": "get_forecast", "input": {"asset": "gold"}, "ok": True, "result": {}}
    answer = "Chào bạn, mình là trợ lý của CPAWS, giải thích dự báo vàng, bạc và dầu."
    out = CB.check_answer(q, {"answer": answer, "tool_calls": [call], "status": "ok"})
    assert out["checks"]["tool_called_when_not_expected"] and not out["auto_pass"]

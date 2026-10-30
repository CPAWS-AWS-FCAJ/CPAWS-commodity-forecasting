"""Router theo luật của chatbot (src/chatbot/router.py, ADR-0004 mục 1): không gọi mạng.

Bộ câu phát triển tests/router/cases.jsonl có nhãn simple/complex. Lỗi đắt nhất là câu cần số
liệu bị đưa sang nhánh simple (Nova không có tool), nên kiểm tra riêng số lỗi complex → simple.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from src.chatbot.router import R, RouteDecision, fold, route

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    json.loads(line)
    for line in (ROOT / "tests" / "router" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
# Ngưỡng đề xuất cho bộ phát triển (chờ Khải chốt, xem docs/experiments/chatbot-router-proposal.md)
MIN_ACCURACY = 0.95
MAX_COMPLEX_TO_SIMPLE = 0


def _benchmark_questions() -> set[str]:
    out = set()
    for path in (ROOT / "tests" / "chatbot").rglob("*_questions.jsonl"):
        out |= {json.loads(x)["question"] for x in path.read_text(encoding="utf-8").splitlines()}
    return out


def test_cases_file_is_well_formed():
    assert len(CASES) >= 80
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert {c["expected_branch"] for c in CASES} == {R.SIMPLE, R.COMPLEX}
    assert all(c["question"].strip() and c["group"] for c in CASES)


def test_cases_do_not_reuse_benchmark_questions():
    """Bộ benchmark chatbot phải độc lập với router: không dùng lại câu nào của nó."""
    assert not {c["question"] for c in CASES} & _benchmark_questions()


def test_dev_set_accuracy_and_costly_errors():
    results = [(c, route(c["question"])) for c in CASES]
    wrong = [
        (c["id"], c["question"], d.rule) for c, d in results if d.branch != c["expected_branch"]
    ]
    c2s = [
        c["id"] for c, d in results if c["expected_branch"] == R.COMPLEX and d.branch == R.SIMPLE
    ]
    accuracy = 1 - len(wrong) / len(CASES)
    assert len(c2s) <= MAX_COMPLEX_TO_SIMPLE, c2s
    assert accuracy >= MIN_ACCURACY, wrong


@pytest.mark.parametrize("group", sorted({c["group"] for c in CASES}))
def test_each_group_routes_to_its_label(group):
    cases = [c for c in CASES if c["group"] == group]
    got = Counter(route(c["question"]).branch == c["expected_branch"] for c in cases)
    assert got[True] == len(cases), [
        c["id"] for c in cases if route(c["question"]).branch != c["expected_branch"]
    ]


def test_decision_has_rule_name():
    d = route("Dự báo vàng 3 phiên tới thế nào?")
    assert d == RouteDecision(R.COMPLEX, "forecast")


def test_empty_or_unclear_goes_to_haiku():
    assert route("   ").branch == R.COMPLEX
    assert route("ừm").branch == R.COMPLEX  # không khớp luật nào → mặc định Haiku (ADR-0004)


def test_fold_removes_vietnamese_marks():
    assert fold("dầu thô đầu tư") == "dau tho dau tu"


def test_accented_text_keeps_dau_and_dau_apart():
    """Câu có dấu: "đầu tư" không bị hiểu là "dầu"; câu không dấu thì so bản bỏ dấu."""
    assert route("Nên đầu tư thế nào cho an toàn?").rule == "advice_only"
    assert route("Ngày mai dầu có tăng không?").rule == "forecast"
    assert route("ngay mai dau co tang khong").rule == "forecast"


def test_intraday_is_out_of_scope_even_with_asset():
    assert route("Sáng nay Brent có giảm không?") == RouteDecision(
        R.SIMPLE, "out_of_scope_intraday"
    )


def test_out_of_scope_phrase_does_not_count_as_asset():
    assert route("Vàng miếng tuần sau thế nào?").rule == "out_of_scope_product"
    assert route("Bạc tuần sau thế nào, còn vàng miếng?").rule == "mixed_scope"


def test_horizon_patterns_only_cover_1_to_7_sessions():
    assert route("Mốc thống kê 252 phiên là gì?").branch == R.SIMPLE
    assert route("Xác suất tăng ở kỳ hạn 3 thế nào?").branch == R.COMPLEX

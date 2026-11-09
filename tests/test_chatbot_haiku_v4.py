"""Prompt chatbot-haiku-v4 (issue #84) và script answer_format_report: không gọi mạng.

Kiểm tra: thêm bộ prompt v4 không lệch khóa SHA-256 bộ v2; prompt v4 viết chung (không số thập
phân, không trùng cụm câu hỏi bộ v2), có các quy tắc của issue #84; script báo cáo đếm đúng
Markdown và cờ to_date.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CB = _load("chatbot_benchmark_v4", "scripts/benchmark/chatbot_benchmark.py")
AF = _load("answer_format_report", "scripts/benchmark/answer_format_report.py")
C = CB.C

V3_PROMPT = ROOT / C.PROMPT_SETS["v3"]["prompts"]["complex"]
V4_PROMPT = ROOT / C.PROMPT_SETS["v4"]["prompts"]["complex"]
V4_TEXT = CB.load_system_prompt(V4_PROMPT)


# ---------- khóa và cấu hình ----------


def test_v2_lock_unchanged_with_v4_set():
    assert CB.lock_hashes("v2") == C.QUESTION_SETS["v2"]["locked_sha256"]
    CB.verify_lock("v2")


def test_report_script_not_in_locked_code():
    assert "scripts/benchmark/answer_format_report.py" not in C.TOOL_CODE_PATHS


def test_prompt_set_v4_changes_only_haiku():
    v2, v4 = C.PROMPT_SETS["v2"], C.PROMPT_SETS["v4"]
    assert v4["prompts"]["simple"] == v2["prompts"]["simple"]
    assert v4["prompts"]["complex"] == "docs/prompts/chatbot-haiku-v4.md"
    assert v4["prompt_versions"] == {"simple": "chatbot-nova-v2", "complex": "chatbot-haiku-v4"}
    assert v4["tool_format"] == "v2"


def test_v4_question_sets_have_correct_release_guards():
    v4_sets = {name for name, cfg in C.QUESTION_SETS.items() if cfg["prompt_set"] == "v4"}

    assert v4_sets == {
        "v4-horizon-dev",
        "v4-official-a",
        "v4-official-b",
    }

    # Bộ dev: được chạy phát triển, không khóa.
    dev = C.QUESTION_SETS["v4-horizon-dev"]
    assert dev["require_lock"] is True
    assert dev["holdout"] is False
    assert dev["locked_sha256"] is None

    CB.check_dev_allowed("v4-horizon-dev")

    with pytest.raises(RuntimeError, match="chưa khóa"):
        CB.verify_lock("v4-horizon-dev")

    # Bộ official: không được chạy dev thật.
    for name in ("v4-official-a", "v4-official-b"):
        cfg = C.QUESTION_SETS[name]

        assert cfg["require_lock"] is True
        assert cfg["holdout"] is True

        with pytest.raises(RuntimeError, match="giữ riêng"):
            CB.check_dev_allowed(name)

        # Trước khi khóa phải bị chặn.
        # Sau khi khóa phải xác minh được SHA-256.
        if cfg["locked_sha256"] is None:
            with pytest.raises(RuntimeError, match="chưa khóa"):
                CB.verify_lock(name)
        else:
            CB.verify_lock(name)


def test_horizon_dev_questions_come_from_router_heldout():
    """Khải 4/11: 1–2 câu dev cho kỳ hạn ngoài 1–7. Câu lấy nguyên văn RH-027, RH-010, không do
    người viết prompt soạn."""
    questions = CB.load_questions(CB.questions_path("v4-horizon-dev", "complex"))
    heldout = {
        q["id"]: q["question"] for q in CB.load_questions(ROOT / "tests/router/heldout_v1.jsonl")
    }
    assert [q["source_id"] for q in questions] == ["RH-027", "RH-010"]
    for q in questions:
        assert q["question"] == heldout[q["source_id"]]
        assert CB.validate_question(q, "complex", "v4-horizon-dev") == []
    above, below = questions
    assert above["expected_tools"] == ["get_forecast"] and "7 phiên" in above["must_include"]
    assert below["category"] in C.POLICY_CATEGORIES and not below["expects_tool"]


@pytest.mark.parametrize("qset", ["v2-seen", "a-types-haiku", "v4-horizon-dev"])
def test_v4_dry_run_on_dev_sets(tmp_path, qset):
    questions = CB.load_questions(CB.questions_path(qset, "complex"))
    summary = CB.run(
        CB.FakeStreamClient(questions), "complex", tmp_path, dry_run=True, qset=qset,
        run_type="dev", prompt_set="v4",
    )  # fmt: skip
    assert summary["prompt_version"] == "chatbot-haiku-v4"
    rep = AF.report(AF.load_records(tmp_path / "raw.jsonl"))
    assert rep["n_answers"] == len(questions)


def test_lambda_still_on_v2():
    """Issue #84: không đổi PROMPT_FILES/PROMPT_VERSIONS trước khi Khải duyệt (sau 8/11)."""
    for rel in ("infra/lambda/chat_api/handler.py", "src/chatbot/chat.py"):
        assert "chatbot-haiku-v4" not in (ROOT / rel).read_text(encoding="utf-8")


def test_v4_dev_run_with_fake_model(tmp_path):
    questions = CB.load_questions(CB.questions_path("v2-seen", "complex"))
    summary = CB.run(
        CB.FakeStreamClient(questions), "complex", tmp_path, dry_run=True, qset="v2-seen",
        run_type="dev", prompt_set="v4",
    )  # fmt: skip
    assert summary["prompt_version"] == "chatbot-haiku-v4"
    assert summary["sha256"]["prompt"] == CB._sha256(V4_PROMPT)


# ---------- nội dung prompt v4 ----------


def test_v4_prompt_is_single_text_block():
    assert V4_TEXT.startswith("Bạn là trợ lý") and "Ghi chú thiết kế" not in V4_TEXT
    assert C.DISCLAIMER in V4_TEXT


def test_v4_prompt_has_no_decimal_numbers():
    assert re.findall(r"\d+[.,]\d+", V4_TEXT) == []


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


@pytest.mark.parametrize("branch", ["complex", "simple"])
def test_v4_prompt_does_not_reuse_v2_question_wording(branch):
    words = _words(V4_TEXT)
    grams = {tuple(words[i : i + 5]) for i in range(len(words) - 4)}
    hits = {}
    for q in CB.load_questions(CB.questions_path("v2", branch)):
        w = _words(q["question"])
        found = [" ".join(w[i : i + 5]) for i in range(len(w) - 4) if tuple(w[i : i + 5]) in grams]
        if found:
            hits[q["id"]] = found
    assert hits == {}


def test_v4_prompt_itself_has_no_markdown_examples():
    """Prompt mô tả dấu Markdown bằng chữ, không đưa mẫu in đậm, bảng, code hay link vào khối
    prompt. Tiêu đề mục "# ..." giữ như v2, v3 (cấu trúc của system prompt, không phải mẫu)."""
    kinds = set(AF.markdown_kinds(V4_TEXT))
    assert kinds <= {"heading"}, kinds


@pytest.mark.parametrize(
    "rule",
    [
        "# Định dạng: văn bản thuần",  # issue #84 mục 1
        "không dùng bảng",
        'bắt đầu bằng "- "',
        "không truyền from_date và to_date",  # mục 6, Khải chọn (a)
        "7 ngày gần nhất tính đến hôm nay theo giờ Việt Nam",
        "Loại 4 chỉ dành cho câu không có phần thông tin nào",  # HAIKU2-029
        "không hỏi lại người dùng muốn số liệu nào",  # HAIKU2-024
        "# Khung câu trả lời có dự báo",  # forecast_missing, thiếu ngày cơ sở
        "ngày cơ sở <base_date>",
        "Viết các dòng số trước, nhận xét sau",  # HAIKU2-016
        "không vượt quá",  # HAIKU2-030
        "Không truyền horizon lớn hơn 7",  # Khải 4/11
        "Chỉ nhắc tin có trong kết quả get_news của lượt này",  # tập dượt 7/11, Khải PR #98
        "Link chép nguyên văn từ trường link của tin đó, từng ký tự",
        "áp dụng cả cho phần tin",
        "Không đoán lý do không có tin",
        "kết quả thực tế vẫn có thể nằm ngoài khoảng này",  # ADR-0005 (#91 điểm 3)
        "# Câu hỏi không cần công cụ",
        "Mình không đưa ra lời khuyên đầu tư.",
        # Vòng sửa sau dev 8/11 (Khải chốt, issue #84 ngày 8/11)
        "Ngay sau các dòng số, luôn viết câu nguồn của dự báo",  # 11/24 thiếu câu mốc
        "thiếu ngày cơ sở, khoảng dự báo 80%, trung vị, xác suất tăng hay câu nguồn",
        "Không quy đổi số phiên ra giờ, ngày, tuần, tháng hay năm",  # HAIKU4D-001, 002
        'không viết con số dạng "x% khả năng"',  # HAIKU3A-004
        "vẫn gọi get_forecast cho phần trong phạm vi",  # HAIKU2-006, 029
        "không hỏi lại có muốn xem dự báo không",  # HAIKU2-006
        "Không dùng tin để giải thích biến động giá",  # hỏi lại câu 3 ngày 7/11
        "không đem tin ra so với dự báo",  # HAIKU2-019
        "Ngày trong trích nguồn là ngày đăng tin",  # hỏi lại câu 3 ngày 7/11
        "không tự đánh giá sản phẩm hay phương pháp",  # HAIKU3A-003 (Khải chấm lại)
    ],
)
def test_v4_prompt_contains_required_rules(rule):
    assert rule in V4_TEXT


def test_v4_no_tail_probability_wording():
    """Khải review PR #98: bỏ câu "còn khoảng 10% khả năng" ngoài q10/q90 (ADR-0005, #91)."""
    assert "10% khả năng" not in V4_TEXT
    assert "20% khả năng" not in V4_TEXT  # HAIKU3A-004 dev 8/11


def test_v4_direction_labels_only_in_ban_rule():
    lines = [ln for ln in V4_TEXT.splitlines() if re.search(r"nghiêng|nhẹ\b", ln)]
    assert lines and all("Không gắn nhãn hướng" in ln for ln in lines), lines


def test_v4_statistical_baseline_sentence_once():
    """Rút gọn so với v3 (câu này có ở 3 mục): câu mốc 252 phiên chỉ viết một lần, nguyên văn
    ở dòng 3 của khung (sau dev 8/11 thiếu ở 11/24 câu); mục Nguồn trỏ về dòng đó."""
    assert V4_TEXT.count("252 phiên") == 1
    frame = V4_TEXT.split("# Khung câu trả lời có dự báo", 1)[1]
    frame_line = next(ln for ln in frame.splitlines() if ln.startswith("3. "))
    assert "252 phiên" in frame_line
    assert CB.load_system_prompt(V3_PROMPT).count("252 phiên") > 1


def test_v4_prompt_length_reported(capsys):
    n3, n4 = len(_words(CB.load_system_prompt(V3_PROMPT))), len(_words(V4_TEXT))
    print(f"số từ khối prompt: v3 {n3}, v4 {n4}")
    assert n4 < n3 * 1.15  # thêm khung và mục định dạng, không phình quá v3


# ---------- answer_format_report ----------


@pytest.mark.parametrize(
    ("answer", "kinds"),
    [
        ("Vàng, ngày cơ sở 2026-10-21.\n- 1 phiên: khoảng 80% từ -1% đến 1%.", []),
        ("**Khoảng dự báo 80%:** từ -1% đến 1%", ["bold"]),
        ("## Dự báo vàng\nNội dung", ["heading"]),
        ("| h | q50 |\n|---|---|\n| 1 | 0.1 |", ["table"]),
        ("* 1 phiên: -1%", ["star_bullet"]),
        ("dùng `q50`", ["code"]),
        ("(Nguồn: Fed, 2026-10-20, [link](https://www.federalreserve.gov))", ["link"]),
        ("(Nguồn: Fed, 2026-10-20, https://www.federalreserve.gov/a_b_c)", []),
        ("Xác suất tăng 46% * 2", []),
    ],
)
def test_markdown_kinds(answer, kinds):
    assert AF.markdown_kinds(answer) == kinds


@pytest.mark.parametrize(
    ("question", "mentions"),
    [
        ("Vì sao giá vàng giảm?", False),
        ("Lãi suất có phải yếu tố bất lợi cho bạc tuần tới?", False),
        ("Tin dầu Brent từ ngày 1/11 thế nào?", True),
        ("Có tin gì về WTI tuần trước không?", True),
        ("Tin vàng 2026-10-15", True),
    ],
)
def test_question_mentions_date(question, mentions):
    assert AF.question_mentions_date(question) is mentions


def _rec(qid, question, answer, calls):
    return {"id": qid, "question": question, "answer": answer, "tool_calls": calls, "status": "ok"}


def test_report_counts_markdown_and_flags_to_date(tmp_path):
    def news(**dates):
        return {"name": "get_news", "input": {"asset": "gold", **dates}}

    records = [
        _rec("A", "Vì sao vàng giảm?", "**Tin:** ...", [news()]),
        _rec("B", "Vì sao bạc tăng?", "- tin ...", [news(to_date="2026-10-21")]),
        _rec("C", "Tin vàng từ ngày 1/11?", "- tin ...", [news(from_date="2026-11-01")]),
        {"id": "D", "status": "api_error", "answer": "**x**", "tool_calls": []},
    ]
    path = tmp_path / "raw.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), "utf-8")
    rep = AF.report(AF.load_records(path))
    assert (rep["n_answers"], rep["markdown_answers"], rep["markdown_ids"]) == (3, 1, ["A"])
    assert rep["markdown_by_kind"]["bold"] == 1
    assert (rep["news_calls"], rep["news_calls_with_dates"]) == (3, 2)
    assert rep["news_date_without_mention"] == ["B"]
    assert AF.main([str(path), "--json"]) == 0
    assert AF.main([str(tmp_path / "missing.jsonl")]) == 2


def _news_call(link):
    item = {"title": "t", "link": link, "source": "Fed", "published_at": "2026-10-28T18:00:00Z"}
    return {"name": "get_news", "input": {"asset": "gold"}, "ok": True, "result": {"items": [item]}}


def _forecast_call():
    return {"name": "get_forecast", "input": {"asset": "gold"}, "ok": True, "result": {}}


def test_foreign_links_flags_miscopied_url():
    """Tập dượt 7/11 (194d6cc6…): link chép thiếu chữ "s" không có trong kết quả get_news."""
    good = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm"
    bad = good.replace("pressreleases", "pressrelease")
    ok = _rec("A", "Vì sao vàng giảm?", f"(Nguồn: Fed, 2026-10-28, {good}).", [_news_call(good)])
    wrong = _rec("B", "Vì sao vàng giảm?", f"(Nguồn: Fed, 2026-10-28, {bad})", [_news_call(good)])
    no_news = _rec("C", "Vàng tuần tới?", f"xem {good}", [_forecast_call()])
    assert AF.foreign_links(ok) == []
    assert AF.foreign_links(wrong) == [bad]
    assert AF.foreign_links(no_news) == [good]
    assert AF.report([ok, wrong, no_news])["foreign_links"] == {"B": [bad], "C": [good]}


def test_baseline_missing_and_direction_labels():
    with_line = _rec(
        "A", "q", "Đây là mốc thống kê dựa trên 252 phiên gần nhất.", [_forecast_call()]
    )
    without = _rec("B", "q", "Trung vị -1%, xu hướng giảm nhẹ.", [_forecast_call()])
    no_tool = _rec("C", "q", "Xin chào.", [])
    assert [AF.baseline_missing(r) for r in (with_line, without, no_tool)] == [False, True, False]
    assert AF.direction_labels(without["answer"]) == ["giảm nhẹ"]
    rep = AF.report([with_line, without, no_tool])
    assert (rep["forecast_answers"], rep["baseline_missing"]) == (2, ["B"])
    assert rep["direction_labels"] == {"B": ["giảm nhẹ"]}


def test_report_on_v2_official_run():
    """Số trong ghi chú thiết kế v4: `**` ở 28/30 câu, Haiku không tự truyền ngày cho get_news."""
    path = ROOT / "docs/experiments/results/chatbot-benchmark-2026-10-30-v2/complex/raw.jsonl"
    rep = AF.report(AF.load_records(path))
    assert (rep["markdown_answers"], rep["n_answers"]) == (28, 30)
    assert (rep["news_calls"], rep["news_calls_with_dates"]) == (7, 0)
    assert rep["foreign_links"] == {}
    assert (len(rep["baseline_missing"]), rep["forecast_answers"]) == (17, 25)

"""Kiểm URL lạ trong check_answer của benchmark chatbot (Khải, review PR #104 điểm 3).

URL trong câu trả lời không trùng nguyên văn link của tin get_news trả về trong câu đó thì trượt
tự động. Fixture là ca thật buổi tập 7/11: model viết "pressrelease" (thiếu "s") thay cho link đã
lưu "pressreleases". Cách so dùng chung với Lambda: src/chatbot/citations.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from configs import chatbot_benchmark as C

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "chatbot_benchmark", ROOT / "scripts" / "benchmark" / "chatbot_benchmark.py"
)
CB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CB)

FED_LINK = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm"
FED_LINK_TYPO = "https://www.federalreserve.gov/newsevents/pressrelease/monetary20261028a.htm"

Q = {
    "id": "TEST-NEWS",
    "category": "news",
    "question": "Có tin gì về vàng không?",
    "must_include": [],
    "must_not_include": [],
    "expects_tool": True,
    "expected_tools": ["get_news"],
}


def _news_call(*links, ok=True):
    items = [{"title": "FOMC statement", "source": "Federal Reserve", "link": x} for x in links]
    return {"name": "get_news", "input": {"asset": "gold"}, "ok": ok, "result": {"items": items}}


def _res(answer, calls):
    return {"answer": answer, "tool_calls": calls, "truncated": False, "status": "ok"}


def _answer(link):
    return f"Fed giữ nguyên lãi suất trong tuần này (Nguồn: Federal Reserve, 28/10/2026, {link})."


def test_link_copied_exactly_from_get_news_passes():
    out = CB.check_answer(Q, _res(_answer(FED_LINK), [_news_call(FED_LINK)]))
    assert out["checks"]["stray_links"] == []
    assert out["auto_pass"], out["failures"]


def test_typo_link_pressrelease_fails():
    out = CB.check_answer(Q, _res(_answer(FED_LINK_TYPO), [_news_call(FED_LINK)]))
    assert out["checks"]["stray_links"] == [FED_LINK_TYPO]
    assert "stray_links" in out["failures"] and not out["auto_pass"]


@pytest.mark.parametrize(
    "calls",
    [
        [],  # không gọi get_news
        [{"name": "get_forecast", "input": {"asset": "gold"}, "ok": True, "result": {}}],
        [_news_call(FED_LINK, ok=False)],  # get_news lỗi: tin không về tới model
    ],
)
def test_link_without_successful_get_news_fails(calls):
    q = {**Q, "expected_tools": []}
    out = CB.check_answer(q, _res(_answer(FED_LINK), calls))
    assert out["checks"]["stray_links"] == [FED_LINK]
    assert not out["auto_pass"]


def test_answer_without_link_has_no_stray_links():
    out = CB.check_answer(Q, _res("Không tìm thấy tin đáng kể về vàng.", [_news_call(FED_LINK)]))
    assert out["checks"]["stray_links"] == []


def test_check_answer_uses_shared_citations_module():
    """Một chỗ so link: check_answer gọi citations.stray_links, không chép hàm."""
    assert CB.CI.stray_links is importlib.import_module("src.chatbot.citations").stray_links
    bench = (ROOT / "scripts" / "benchmark" / "chatbot_benchmark.py").read_text(encoding="utf-8")
    body = bench.split("def check_answer", 1)[1].split("\ndef ", 1)[0]
    assert "CI.stray_links(" in body
    assert "_URL_RE" not in bench and "def stray_links" not in bench


def test_citations_module_is_hashed_with_tool_code():
    assert "src/chatbot/citations.py" in C.TOOL_CODE_PATHS
    assert all((ROOT / p).is_file() for p in C.TOOL_CODE_PATHS)


@pytest.mark.parametrize("qset", ["v4-official-a", "v4-official-b"])
def test_v4_official_sets_stop_until_locked(qset):
    """Hai bộ chính thức v4 (Long, PR #108): chưa khóa thì official dừng trước khi gọi Bedrock,
    và không chạy dev thật trên bộ giữ riêng."""
    cfg = C.QUESTION_SETS[qset]
    assert cfg["prompt_set"] == "v4"
    assert cfg["require_lock"] and cfg["locked_sha256"] is None and cfg["holdout"]
    with pytest.raises(RuntimeError, match="chưa khóa"):
        CB.verify_lock(qset)
    with pytest.raises(RuntimeError, match="giữ riêng"):
        CB.check_dev_allowed(qset)


@pytest.mark.parametrize("qset", ["v4-official-a", "v4-official-b"])
def test_v4_official_run_stops_before_bedrock(monkeypatch, tmp_path, capsys, qset):
    def no_bedrock(*_a, **_k):
        raise AssertionError("không được gọi Bedrock khi bộ chưa khóa")

    monkeypatch.setattr(CB, "bedrock_client", no_bedrock)
    out = tmp_path / "out"
    assert CB.main(["--branch", "complex", "--set", qset, "--out-dir", str(out)]) == 2
    assert "chưa khóa" in capsys.readouterr().err
    assert not out.exists()

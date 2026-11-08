"""Script đếm URL lạ của benchmark (scripts/benchmark/citation_link_report.py): không gọi mạng.

Fixture là ca thật buổi tập 7/11: link "pressrelease" (thiếu "s") so với link đã lưu
"pressreleases". Khải chốt (b) ngày 8/11: chỉ đếm, chưa tính trượt, không đổi khóa v2.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from configs import chatbot_benchmark as BC

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "citation_link_report", ROOT / "scripts" / "benchmark" / "citation_link_report.py"
)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

FED_LINK = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm"
FED_LINK_TYPO = "https://www.federalreserve.gov/newsevents/pressrelease/monetary20261028a.htm"


def _news_call(*links, ok=True):
    items = [{"title": "FOMC statement", "source": "Federal Reserve", "link": x} for x in links]
    return {"name": "get_news", "input": {"asset": "gold"}, "ok": ok, "result": {"items": items}}


def _record(rid, answer, calls, **kw):
    return {"id": rid, "status": "ok", "answer": answer, "tool_calls": calls, **kw}


RECORDS = [
    _record("Q-TYPO", f"Fed giữ lãi suất (Nguồn: Federal Reserve, {FED_LINK_TYPO}).",
            [_news_call(FED_LINK)], request_id="194d6cc6-58a0-45b8-a3b2-162403d2a2bb"),
    _record("Q-OK", f"Fed giữ lãi suất (Nguồn: Federal Reserve, {FED_LINK}).",
            [_news_call(FED_LINK)]),
    _record("Q-NONEWS", f"Xem {FED_LINK}.", [{"name": "get_forecast", "ok": True}]),
    _record("Q-FAILED", f"Xem {FED_LINK}.", [_news_call(FED_LINK, ok=False)]),
    _record("Q-NOLINK", "Chào bạn.", []),
    {"id": "Q-ERR", "status": "api_error", "answer": "", "tool_calls": []},
]  # fmt: skip


def test_report_counts_typo_link_as_stray_and_keeps_ids():
    rep = R.report(RECORDS)
    assert rep["n_answers"] == 5  # câu lỗi API không tính
    # link không đến từ get_news thành công trong chính câu đó đều là lạ
    assert rep["stray_ids"] == ["Q-TYPO", "Q-NONEWS", "Q-FAILED"]
    typo = rep["stray"][0]
    assert typo["stray_links"] == [FED_LINK_TYPO]
    assert typo["news_links"] == [FED_LINK] and typo["cited_links"] == []
    assert typo["request_id"] == "194d6cc6-58a0-45b8-a3b2-162403d2a2bb"
    assert "request_id" not in rep["stray"][1]
    assert rep["answers_with_news"] == 2 and rep["answers_with_citations"] == 1


def test_main_reads_raw_jsonl_and_prints_json(tmp_path, capsys):
    raw = tmp_path / "raw.jsonl"
    raw.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in RECORDS), encoding="utf-8")
    assert R.main([str(raw), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[str(raw)]["answers_with_stray_links"] == 3
    assert R.main([str(raw)]) == 0
    text = capsys.readouterr().out
    assert "câu có URL lạ: 3/5" in text and f"lạ: {FED_LINK_TYPO}" in text
    assert R.main([str(tmp_path / "missing.jsonl")]) == 2


def test_script_and_shared_module_stay_outside_v2_lock():
    """(b): đo, chưa tính trượt; khóa v2 chỉ dùng đối chiếu lần chạy 30/10, không được đổi."""
    for path in ("scripts/benchmark/citation_link_report.py", "src/chatbot/citations.py"):
        assert path not in BC.TOOL_CODE_PATHS
    bench = (ROOT / "scripts" / "benchmark" / "chatbot_benchmark.py").read_text(encoding="utf-8")
    assert "citations" not in bench.split("def check_answer", 1)[1].split("\ndef ", 1)[0]

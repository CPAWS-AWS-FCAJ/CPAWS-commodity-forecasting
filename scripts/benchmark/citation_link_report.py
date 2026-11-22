"""Đếm câu trả lời có URL lạ từ raw.jsonl của benchmark chatbot.

URL lạ: URL trong câu trả lời không trùng nguyên văn link của tin get_news trả về trong chính câu
đó (buổi tập 7/11: model chép "pressrelease" thay cho "pressreleases", link mở lỗi và tin không vào
citations). Cách so dùng chung với Lambda: `src/chatbot/citations.py`.

Script này chỉ đếm và liệt kê. `check_answer` của benchmark chấm URL lạ là trượt bằng cùng hàm
`stray_links`, và `citations.py` nằm trong TOOL_CODE_PATHS, để khóa cùng bộ chính thức v4 (Khải,
review PR #104 điểm 3). Script không nằm trong TOOL_CODE_PATHS: đọc lại kết quả cũ không đổi khóa bộ nào.

Chạy: python scripts/benchmark/citation_link_report.py <raw.jsonl> [<raw.jsonl> ...] [--json]
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Nạp sau khi thêm ROOT vào sys.path; dùng import_module để không vướng E402 ở mọi phiên bản ruff
# (hook pre-commit v0.8.0 và CI lệch phiên bản), như chatbot_benchmark.py.
CI = importlib.import_module("src.chatbot.citations")

NEWS_TOOL = "get_news"


def news_items(record: dict) -> list[dict]:
    """Tin của mọi lần gọi get_news thành công trong câu này."""
    out: list[dict] = []
    for call in record.get("tool_calls") or []:
        if call.get("name") == NEWS_TOOL and call.get("ok"):
            out.extend((call.get("result") or {}).get("items") or [])
    return out


def record_report(record: dict) -> dict:
    items = news_items(record)
    answer = record.get("answer") or ""
    row = {
        "id": record.get("id"),
        "stray_links": CI.stray_links(answer, items),
        "cited_links": [c["link"] for c in CI.cited_items(answer, items)],
        "news_links": sorted({it["link"] for it in items if it.get("link")}),
    }
    if record.get("request_id"):
        row["request_id"] = record["request_id"]
    return row


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def report(records: list[dict]) -> dict:
    answered = [r for r in records if r.get("status", "ok") == "ok"]
    rows = [record_report(r) for r in answered]
    stray = [r for r in rows if r["stray_links"]]
    return {
        "n_answers": len(answered),
        "answers_with_news": sum(1 for r in rows if r["news_links"]),
        "answers_with_citations": sum(1 for r in rows if r["cited_links"]),
        "answers_with_stray_links": len(stray),
        "stray_ids": [r["id"] for r in stray],
        "stray": stray,
    }


def _print_text(path: Path, rep: dict) -> None:
    print(f"== {path}")
    print(
        f"câu có URL lạ: {rep['answers_with_stray_links']}/{rep['n_answers']} "
        f"(câu có tin get_news: {rep['answers_with_news']}, "
        f"có citations: {rep['answers_with_citations']})"
    )
    for r in rep["stray"]:
        rid = f" request_id={r['request_id']}" if "request_id" in r else ""
        print(f"  {r['id']}{rid}")
        for url in r["stray_links"]:
            print(f"    lạ: {url}")
        for url in r["news_links"]:
            print(f"    tin: {url}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw", nargs="+", type=Path, help="đường dẫn raw.jsonl")
    ap.add_argument("--json", action="store_true", help="in JSON thay cho văn bản")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # Windows: in tiếng Việt khi chuyển hướng ra file
        sys.stdout.reconfigure(encoding="utf-8")
    reports = {}
    for path in args.raw:
        if not path.is_file():
            print(f"không thấy file: {path}", file=sys.stderr)
            return 2
        reports[str(path)] = report(load_records(path))
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for path, rep in reports.items():
            _print_text(Path(path), rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Báo cáo định dạng câu trả lời và ngày truyền vào get_news từ raw.jsonl của benchmark chatbot.

Issue #84 mục 1, 4 và 6:
- đếm câu trả lời có Markdown (contract: `answer` là văn bản thuần, gạch đầu dòng "- " được phép);
- liệt kê lần gọi get_news có from_date/to_date, đánh dấu câu hỏi không nêu ngày mà model vẫn
  truyền ngày (mặc định đúng là để trống, tool lấy 7 ngày đến hôm nay giờ Việt Nam).

Đây là số đo ghi nhận, không phải điều kiện đạt. Script không nằm trong TOOL_CODE_PATHS
(configs/chatbot_benchmark.py), nên không đổi khóa SHA-256 của bộ câu hỏi nào.

Chạy: python scripts/benchmark/answer_format_report.py <raw.jsonl> [<raw.jsonl> ...] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Mỗi loại Markdown một mẫu; tên loại là khóa trong báo cáo.
MARKDOWN_PATTERNS: dict[str, re.Pattern[str]] = {
    "bold": re.compile(r"\*\*[^*\n]+?\*\*|__[^_\n]+?__"),
    "heading": re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+\S"),
    "table": re.compile(r"(?m)^[ \t]*\|.*\|[ \t]*$"),
    "star_bullet": re.compile(r"(?m)^[ \t]*[*+][ \t]+\S"),
    "code": re.compile(r"`"),
    "link": re.compile(r"\[[^\]\n]+\]\([^)\s]+\)"),
}

# Câu hỏi có nêu ngày hay khoảng thời gian cụ thể (ước lượng bằng mẫu chữ, có thể sót).
DATE_PATTERNS = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b"
    r"|\bngày\s+\d{1,2}\b"
    r"|\btháng\s+\d{1,2}\b"
    r"|\bnăm\s+\d{4}\b"
    r"|\b\d+\s+(ngày|tuần|tháng)\s+(qua|gần|trước|vừa)"
    r"|hôm qua|hôm kia|tuần trước|tuần qua|tháng trước|tháng qua|từ ngày|đến ngày",
    re.IGNORECASE,
)
NEWS_TOOL = "get_news"
DATE_KEYS = ("from_date", "to_date")


def markdown_kinds(answer: str) -> list[str]:
    """Các loại Markdown có trong câu trả lời, theo thứ tự của MARKDOWN_PATTERNS."""
    return [kind for kind, pat in MARKDOWN_PATTERNS.items() if pat.search(answer or "")]


def question_mentions_date(question: str) -> bool:
    return bool(DATE_PATTERNS.search(question or ""))


def news_date_calls(record: dict) -> list[dict]:
    """Mỗi lần gọi get_news của một câu: input ngày model truyền và cờ truyền ngày khi câu hỏi
    không nêu ngày."""
    mentions = question_mentions_date(record.get("question", ""))
    out = []
    for call in record.get("tool_calls") or []:
        if call.get("name") != NEWS_TOOL:
            continue
        args = call.get("input") or {}
        dates = {k: args[k] for k in DATE_KEYS if args.get(k)}
        out.append(
            {
                "id": record.get("id"),
                "input": args,
                "question_mentions_date": mentions,
                "date_without_mention": bool(dates) and not mentions,
            }
        )
    return out


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def report(records: list[dict]) -> dict:
    answered = [r for r in records if r.get("status", "ok") == "ok"]
    per_kind = {kind: [] for kind in MARKDOWN_PATTERNS}
    with_markdown = []
    calls = []
    for r in answered:
        kinds = markdown_kinds(r.get("answer", ""))
        for kind in kinds:
            per_kind[kind].append(r.get("id"))
        if kinds:
            with_markdown.append(r.get("id"))
        calls.extend(news_date_calls(r))
    return {
        "n_answers": len(answered),
        "markdown_answers": len(with_markdown),
        "markdown_ids": with_markdown,
        "markdown_by_kind": {k: len(v) for k, v in per_kind.items()},
        "markdown_ids_by_kind": per_kind,
        "news_calls": len(calls),
        "news_calls_with_dates": sum(1 for c in calls if any(k in c["input"] for k in DATE_KEYS)),
        "news_date_without_mention": [c["id"] for c in calls if c["date_without_mention"]],
        "news_call_inputs": calls,
    }


def _print_text(path: Path, rep: dict) -> None:
    print(f"== {path}")
    print(f"câu trả lời có Markdown: {rep['markdown_answers']}/{rep['n_answers']}")
    for kind, n in rep["markdown_by_kind"].items():
        if n:
            print(f"  {kind}: {n} ({', '.join(rep['markdown_ids_by_kind'][kind])})")
    print(
        f"get_news: {rep['news_calls']} lần gọi, {rep['news_calls_with_dates']} lần có "
        f"from_date/to_date; truyền ngày khi câu hỏi không nêu ngày: "
        f"{rep['news_date_without_mention'] or 'không có'}"
    )
    for c in rep["news_call_inputs"]:
        print(f"  {c['id']}: {json.dumps(c['input'], ensure_ascii=False)}")


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

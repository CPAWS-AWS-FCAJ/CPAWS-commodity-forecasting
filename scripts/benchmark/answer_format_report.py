"""Báo cáo định dạng câu trả lời và ngày truyền vào get_news từ raw.jsonl của benchmark chatbot.

Issue #84 mục 1, 4 và 6:
- đếm câu trả lời có Markdown (contract: `answer` là văn bản thuần, gạch đầu dòng "- " được phép);
- liệt kê lần gọi get_news có from_date/to_date, đánh dấu câu hỏi không nêu ngày mà model vẫn
  truyền ngày (mặc định đúng là để trống, tool lấy 7 ngày đến hôm nay giờ Việt Nam);
- link lạ: URL trong câu trả lời không trùng link của tin get_news trả trong lượt đó (lỗi tập
  dượt 7/11, Khải review PR #98);
- câu có get_forecast mà thiếu câu "mốc thống kê" / "252 phiên";
- nhãn hướng bị cấm ("nghiêng", "tăng nhẹ", "giảm nhẹ", "kịch bản tích cực/tiêu cực").

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
FORECAST_TOOL = "get_forecast"
DATE_KEYS = ("from_date", "to_date")
URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]\"']+")
URL_TRAILING = ".,;:!?"
BASELINE_PHRASES = ("mốc thống kê", "252 phiên")
DIRECTION_LABELS = re.compile(
    r"nghiêng|tăng nhẹ|giảm nhẹ|kịch bản (tích cực|tiêu cực)", re.IGNORECASE
)


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


def _norm_url(url: str) -> str:
    return url.rstrip(URL_TRAILING).rstrip("/")


def answer_urls(answer: str) -> list[str]:
    return [_norm_url(u) for u in URL_PATTERN.findall(answer or "")]


def news_links(record: dict) -> set[str]:
    """Link của mọi tin get_news trả cho model trong lượt này."""
    out = set()
    for call in record.get("tool_calls") or []:
        if call.get("name") == NEWS_TOOL and isinstance(call.get("result"), dict):
            for it in call["result"].get("items") or []:
                if isinstance(it, dict) and isinstance(it.get("link"), str):
                    out.add(_norm_url(it["link"]))
    return out


def foreign_links(record: dict) -> list[str]:
    """URL trong câu trả lời không phải link của tin get_news trả trong lượt đó."""
    known = news_links(record)
    return [u for u in answer_urls(record.get("answer", "")) if u not in known]


def called_forecast(record: dict) -> bool:
    return any(
        c.get("name") == FORECAST_TOOL and c.get("ok", True) for c in record.get("tool_calls") or []
    )


def baseline_missing(record: dict) -> bool:
    """Câu có get_forecast thành công mà câu trả lời không nhắc mốc thống kê 252 phiên."""
    answer = (record.get("answer") or "").lower()
    return called_forecast(record) and not any(p in answer for p in BASELINE_PHRASES)


def direction_labels(answer: str) -> list[str]:
    return [m.group(0) for m in DIRECTION_LABELS.finditer(answer or "")]


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def report(records: list[dict]) -> dict:
    answered = [r for r in records if r.get("status", "ok") == "ok"]
    per_kind = {kind: [] for kind in MARKDOWN_PATTERNS}
    with_markdown = []
    calls = []
    foreign, no_baseline, labels = {}, [], {}
    for r in answered:
        if links := foreign_links(r):
            foreign[r.get("id")] = links
        if baseline_missing(r):
            no_baseline.append(r.get("id"))
        if found := direction_labels(r.get("answer", "")):
            labels[r.get("id")] = found
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
        "foreign_links": foreign,
        "forecast_answers": sum(1 for r in answered if called_forecast(r)),
        "baseline_missing": no_baseline,
        "direction_labels": labels,
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
    print(f"link lạ (không có trong kết quả get_news): {len(rep['foreign_links'])} câu")
    for qid, links in rep["foreign_links"].items():
        print(f"  {qid}: {', '.join(links)}")
    print(
        f"thiếu câu mốc thống kê 252 phiên: {len(rep['baseline_missing'])}/"
        f"{rep['forecast_answers']} câu có get_forecast ({', '.join(rep['baseline_missing'])})"
    )
    print(f"nhãn hướng bị cấm: {len(rep['direction_labels'])} câu")
    for qid, found in rep["direction_labels"].items():
        print(f"  {qid}: {', '.join(found)}")


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

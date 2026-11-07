"""Chấm router theo luật (src/chatbot/router.py) trên một bộ câu có nhãn, không gọi mạng.

Dùng cho bộ giữ riêng (held-out) khoảng 30 câu do Khải soạn: chạy MỘT lần trên commit luật đã khóa,
không sửa luật theo kết quả. Ngưỡng ở docs/experiments/chatbot-router-proposal.md mục 4.

Chạy:
  python scripts/eval_router.py duong/dan/heldout.jsonl

Mỗi dòng của file là một JSON: {"id": "...", "question": "...", "expected_branch": "simple"}
(expected_branch là "simple" hoặc "complex"; có thể thêm "group", "note"). Script in SHA-256 của
file câu hỏi và của hai file luật để ghi lại đúng lần chạy. Mã thoát 0 khi đạt, 1 khi không đạt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_router = importlib.import_module("src.chatbot.router")  # sau sys.path, không vướng E402
R, route = _router.R, _router.route

# Ngưỡng cho bộ giữ riêng
MIN_ACCURACY = 0.90
MAX_COMPLEX_TO_SIMPLE = 1  # câu cần Haiku (số liệu) bị đưa sang Nova
RULE_FILES = ("src/chatbot/router.py", "configs/chatbot_router.py")


def _sha256(path: Path) -> str:
    """SHA-256 của nội dung đã đổi xuống dòng về LF (read_text), để Windows và Linux ra cùng mã."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def load_cases(path: Path) -> list[dict]:
    cases = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not cases:
        raise ValueError(f"{path} không có câu nào")
    for c in cases:
        if not str(c.get("question", "")).strip() or "id" not in c:
            raise ValueError(f"thiếu id hoặc question: {c}")
        if c.get("expected_branch") not in (R.SIMPLE, R.COMPLEX):
            raise ValueError(f"{c['id']}: expected_branch phải là simple hoặc complex")
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("id bị trùng")
    return cases


def evaluate(cases: list[dict]) -> dict:
    rows = []
    for c in cases:
        d = route(c["question"])
        rows.append({**c, "got": d.branch, "rule": d.rule})
    wrong = [r for r in rows if r["got"] != r["expected_branch"]]
    c2s = [r for r in wrong if r["expected_branch"] == R.COMPLEX]
    accuracy = 1 - len(wrong) / len(rows)
    return {
        "n": len(rows),
        "correct": len(rows) - len(wrong),
        "accuracy": accuracy,
        "complex_to_simple": len(c2s),
        "simple_to_complex": len(wrong) - len(c2s),
        "wrong": wrong,
        "passed": accuracy >= MIN_ACCURACY and len(c2s) <= MAX_COMPLEX_TO_SIMPLE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cases", type=Path, help="file JSONL có nhãn expected_branch")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252

    result = evaluate(load_cases(args.cases))
    print(f"file câu hỏi: {args.cases.name}  sha256={_sha256(args.cases)}")
    for f in RULE_FILES:
        print(f"luật: {f}  sha256={_sha256(ROOT / f)}")
    print(
        f"đúng {result['correct']}/{result['n']} ({result['accuracy']:.1%}), "
        f"cần Haiku nhưng sang Nova: {result['complex_to_simple']}, "
        f"đơn giản nhưng sang Haiku: {result['simple_to_complex']}"
    )
    for r in result["wrong"]:
        print(f"  SAI {r['id']}: nhãn {r['expected_branch']}, router {r['got']} ({r['rule']})")
        print(f"      {r['question']}")
    print(
        f"ngưỡng: độ chính xác >= {MIN_ACCURACY:.0%}, "
        f"cần Haiku sang Nova <= {MAX_COMPLEX_TO_SIMPLE} → "
        + ("ĐẠT" if result["passed"] else "KHÔNG ĐẠT")
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

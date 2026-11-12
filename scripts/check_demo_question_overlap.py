"""Kiểm câu hỏi trong kịch bản demo chatbot có trùng hay gần trùng câu trong các bộ benchmark.

Không gọi Bedrock, không gọi AWS. Chỉ đọc file trong repo.

Câu hỏi của kịch bản lấy từ bảng Markdown: mỗi dòng bắt đầu bằng `| Q<số> |` hoặc
`| D<số> |`, câu hỏi là đoạn đầu tiên trong ngoặc kép "..." của dòng đó.

Ba phép đo trên câu đã chuẩn hóa (chữ thường, bỏ dấu câu, gộp khoảng trắng):
- trùng: hai câu giống hệt sau chuẩn hóa;
- ratio: difflib.SequenceMatcher trên chuỗi ký tự;
- jaccard: Jaccard trên tập từ.
Câu bị cờ "gần trùng" khi ratio >= --ratio hoặc jaccard >= --jaccard.

Dùng (Git Bash, gốc repo):
    python scripts/check_demo_question_overlap.py docs/demo/qa-chatbot-final-2026-11-11.md
Mã thoát: 0 khi không có câu trùng hay gần trùng với bộ holdout v4 và các bộ benchmark;
1 khi có. Bộ "tham khảo" (kịch bản demo cũ) chỉ báo, không làm hỏng mã thoát.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Bộ phải tránh. Holdout v4 đứng đầu vì là yêu cầu cứng.
HOLDOUT = [
    "tests/chatbot/v4/official_A_8.jsonl",
    "tests/chatbot/v4/official_B_30.jsonl",
]
BENCHMARK_GLOBS = [
    "tests/chatbot/*.jsonl",
    "tests/chatbot/v2/*.jsonl",
    "tests/chatbot/haiku-v3-dev/*.jsonl",
    "tests/chatbot/haiku-v4-dev/*.jsonl",
    "tests/router/*.jsonl",
]
# Kịch bản cũ: dùng lại câu đã kiểm là được phép, chỉ báo để người soạn biết.
REFERENCE_DOCS = ["docs/demo/demo-chatbot-2026-11-08.md"]

ROW_RE = re.compile(r'^\|\s*([QD]\d+)\s*\|.*?"([^"]+)"')
OLD_ROW_RE = re.compile(r'^\|\s*(\d+b?)\s*\|\s*(?:\(Tùy chọn\)\s*)?"([^"]+)"')


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def words(text: str) -> set[str]:
    return set(normalize(text).split())


def jaccard(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def load_jsonl(path: Path) -> list[tuple[str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("question"):
            out.append((str(row.get("id", "?")), row["question"]))
    return out


def load_script(path: Path, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
    seen, out = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((m.group(1), m.group(2)))
    return out


def corpus() -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    must_avoid: list[tuple[str, str, str]] = []
    files = [ROOT / p for p in HOLDOUT]
    for g in BENCHMARK_GLOBS:
        files += sorted(p for p in ROOT.glob(g) if p not in files)
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        must_avoid += [(rel, qid, q) for qid, q in load_jsonl(f)]
    reference: list[tuple[str, str, str]] = []
    for d in REFERENCE_DOCS:
        p = ROOT / d
        if p.exists():
            reference += [(d, qid, q) for qid, q in load_script(p, OLD_ROW_RE)]
    return must_avoid, reference


def best(q: str, pool: list[tuple[str, str, str]]) -> tuple[float, float, tuple[str, str, str]]:
    scored = [
        (max(ratio(q, c[2]), jaccard(q, c[2])), ratio(q, c[2]), jaccard(q, c[2]), c) for c in pool
    ]
    _, r, j, c = max(scored, key=lambda t: t[0])
    return r, j, c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("script", type=Path, help="file kịch bản Markdown")
    ap.add_argument(
        "--ratio", type=float, default=0.75, help="ngưỡng SequenceMatcher (mặc định 0.75)"
    )
    ap.add_argument("--jaccard", type=float, default=0.6, help="ngưỡng Jaccard từ (mặc định 0.6)")
    args = ap.parse_args()

    questions = load_script(args.script, ROW_RE)
    if not questions:
        print(f"Không tìm thấy câu hỏi nào trong {args.script}", file=sys.stderr)
        return 2
    must_avoid, reference = corpus()
    n_files = len({c[0] for c in must_avoid})
    print(
        f"{len(questions)} câu trong kịch bản; so với {len(must_avoid)} câu benchmark ({n_files} file)"
        f" và {len(reference)} câu kịch bản cũ."
    )
    print(f"Ngưỡng gần trùng: ratio >= {args.ratio} hoặc jaccard >= {args.jaccard}.\n")
    print(
        "| Câu | Gần nhất (benchmark) | ratio | jaccard | Kết quả | Gần nhất (kịch bản cũ) | ratio |"
    )
    print("|---|---|---:|---:|---|---|---:|")

    bad = 0
    norm_avoid = {normalize(c[2]): c for c in must_avoid}
    for qid, q in questions:
        exact = norm_avoid.get(normalize(q))
        r, j, c = best(q, must_avoid)
        if exact:
            verdict = f"TRÙNG {exact[1]}"
        elif r >= args.ratio or j >= args.jaccard:
            verdict = "GẦN TRÙNG"
        else:
            verdict = "ok"
        bad += verdict != "ok"
        rr, _, rc = best(q, reference) if reference else (0.0, 0.0, ("", "-", ""))
        print(f"| {qid} | {c[1]} | {r:.2f} | {j:.2f} | {verdict} | câu {rc[1]} | {rr:.2f} |")

    print(f"\nTrùng hoặc gần trùng với benchmark: {bad}/{len(questions)}.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

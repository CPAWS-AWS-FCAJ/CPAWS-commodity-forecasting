"""Dựng bộ case labeling-v3 từ danh sách ứng viên Fed/EIA và file nhãn do người gắn điền.

Chạy:
    python scripts/benchmark/build_labeling_cases_v3.py                        # kiểm, ghi bản draft
    python scripts/benchmark/build_labeling_cases_v3.py --lock --approved-by "Khải"

Tiêu đề và tóm tắt lấy từ candidates-fed-eia.csv theo id, không lấy từ file nhãn. Case đặc biệt
(id X…) dựng từ một dòng gốc (base_id): injection = tóm tắt gốc + injected_text, empty_summary =
tóm tắt rỗng. Mọi nhãn phải qua schema và quy tắc v3 (validate_output với cấu hình v3).

Bộ case đã chốt (status "locked") không bị ghi đè; muốn đổi phải xóa file một cách có chủ ý.
Cấu hình: configs/labeling_benchmark_v3.py.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent))

import labeling_benchmark as LB

LB.use_config("labeling_benchmark_v3")
C = LB.C
ROOT = LB.ROOT
ASSETS = LB.ASSETS
FIELDS = ("impact", "direction", "confidence", "evidence")
LABEL_COLUMNS = [
    "id",
    "title",
    "selected",
    "group",
    "base_id",
    "variant",
    "injected_text",
    "relevant",
    "event_type",
    *[f"{a}_{f}" for a in ASSETS for f in FIELDS],
    "notes",
    "reviewer_note",
]
TRUE = {"x", "1", "yes", "true", "có"}
FALSE = {"", "0", "no", "false", "không"}


def read_csv(path: Path) -> list[dict]:
    """utf-8-sig để đọc được cả file lưu từ Excel ("CSV UTF-8" có BOM)."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _cell(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def _bool(value: str, field: str, errors: list[str], rid: str) -> bool:
    v = value.strip().lower()
    if v in TRUE:
        return True
    if v not in FALSE:
        errors.append(f"{rid}: {field} = {value!r} không hiểu (dùng true/false)")
    return False


def parse_expected(row: dict, errors: list[str]) -> dict:
    """Nhãn trong một dòng → dict expected theo schema; lỗi định dạng ghi vào errors."""
    rid = _cell(row, "id")
    expected = {
        "relevant": _bool(_cell(row, "relevant"), "relevant", errors, rid),
        "asset_labels": {},
        "event_type": _cell(row, "event_type"),
        "notes": _cell(row, "notes"),
    }
    if not _cell(row, "relevant"):
        errors.append(f"{rid}: thiếu relevant")
    for a in ASSETS:
        raw = _cell(row, f"{a}_impact")
        try:
            impact = int(raw)
        except ValueError:
            errors.append(f"{rid}: {a}_impact = {raw!r} không phải số 0–3")
            impact = -1
        expected["asset_labels"][a] = {
            "impact_score": impact,
            "direction": _cell(row, f"{a}_direction"),
            "confidence": _cell(row, f"{a}_confidence"),
            "evidence": _cell(row, f"{a}_evidence"),
        }
    return expected


def build(candidates: list[dict], labels: list[dict]) -> tuple[dict, list[str]]:
    """Trả (bộ case, danh sách lỗi). Có lỗi thì không được ghi file."""
    errors: list[str] = []
    by_cand = {r["id"]: r for r in candidates}
    ids = [_cell(r, "id") for r in labels]
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"id trùng trong file nhãn: {dupes}")
    if labels and (missing := [c for c in LABEL_COLUMNS if c not in labels[0]]):
        errors.append(f"file nhãn thiếu cột: {missing}")
        return {}, errors

    schema = json.loads((ROOT / C.SCHEMA_PATH).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    real, special = [], []
    for row in labels:
        rid, variant = _cell(row, "id"), _cell(row, "variant")
        if variant:
            if variant not in C.SPECIAL_CASES:
                errors.append(f"{rid}: variant {variant!r} không thuộc {sorted(C.SPECIAL_CASES)}")
                continue
            special.append(row)
        elif _bool(_cell(row, "selected"), "selected", errors, rid):
            if rid not in by_cand:
                errors.append(f"{rid}: không có trong danh sách ứng viên")
                continue
            real.append(row)

    if len(real) != C.N_REAL_CASES:
        errors.append(f"cần chọn đúng {C.N_REAL_CASES} thông cáo thật, đang có {len(real)}")
    group_a = {_cell(r, "id") for r in real if _cell(r, "group").upper() == "A"}
    if missing_a := [i for i in getattr(C, "REQUIRED_GROUP_A", ()) if i not in group_a]:
        errors.append(f"các dòng sau phải được chọn và để group A: {missing_a}")
    for variant, need in C.SPECIAL_CASES.items():
        have = sum(_cell(r, "variant") == variant for r in special)
        if have != need:
            errors.append(f"cần {need} case {variant}, đang có {have}")

    cases = []
    for row in real + special:
        rid, variant = _cell(row, "id"), _cell(row, "variant")
        src = by_cand.get(_cell(row, "base_id") if variant else rid)
        if src is None:
            errors.append(f"{rid}: base_id {_cell(row, 'base_id')!r} không có trong danh sách")
            continue
        summary = src["summary_vi"]
        if variant == "injection":
            if not _cell(row, "injected_text"):
                errors.append(f"{rid}: thiếu injected_text")
            summary = f"{summary} {_cell(row, 'injected_text')}".strip()
        elif variant == "empty_summary":
            summary = ""
        n_err = len(errors)
        expected = parse_expected(row, errors)
        if len(errors) == n_err:
            errors += [f"{rid}: {e}" for e in LB.validate_output(expected, validator)]
        if variant and not expected["notes"]:
            errors.append(f"{rid}: case {variant} phải có notes kỳ vọng")
        if variant == "empty_summary" and len(errors) == n_err:
            for a, lab in expected["asset_labels"].items():
                if (lab["impact_score"], lab["direction"], lab["confidence"]) != LB.EMPTY_LABEL:
                    errors.append(f"{rid}: {a} phải là 0/uncertain/low (tóm tắt rỗng, mục 3 v3)")
        group = _cell(row, "group").upper() or "B"
        if group not in {"A", "B"}:
            errors.append(f"{rid}: group {group!r} phải là A hoặc B")
        case = {
            "case_id": rid,
            "group": "special" if variant else group,
            "source": src["source"],
            "release_type": src["release_type"],
            "published_at_utc": src["published_at_utc"],
            "url": src["url"],
            "title": src["title"],
            "summary": summary,
            "expected": expected,
        }
        if variant:
            case = {**case, "variant": variant, "base_id": src["id"]}
        cases.append(case)

    data = {
        "benchmark_name": "CPAWS News Labeling Real Fed/EIA Test Set",
        "version": C.CASES_VERSION,
        "status": "draft",
        "language": "vi",
        "purpose": "Bộ kiểm labeling-v3 trên thông cáo Fed/EIA thật; đáp án và ngưỡng chốt "
        "trước khi chạy model; không dùng làm dữ liệu huấn luyện.",
        "prompt_version": C.PROMPT_VERSION,
        "thresholds": C.THRESHOLDS,
        "manual_review": C.MANUAL_REVIEW,
        "acceptance_criteria": {
            "valid_output": "100% case có đầu ra hợp lệ (schema và quy tắc 4, 5, 8 của v3)",
            "group_A": "100% core check ở các case group A do người gắn nhãn chọn",
            "special_cases": "100% case đặc biệt đạt core check và quy tắc riêng "
            "(injection: notes nêu chỉ dẫn; empty_summary: cả bốn tài sản 0/uncertain/low)",
            "thresholds": "relevant, event_type, direction, impact ±1 theo trường thresholds",
            "confidence": "Chỉ báo cáo",
            "direction_gold_silver_rates": "Chỉ báo cáo (mục 6.2 của v3)",
            "evidence": "Kiểm máy: impact ≥ 1 thì không rỗng, tiếng Việt, tối đa một câu. "
            "Duyệt tay theo trường manual_review: 10 ô (seed 7) trong các ô model gán "
            "impact ≥ 1, đạt khi ≥ 8/10",
        },
        "cases": cases,
    }
    return data, errors


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lock", action="store_true", help="chốt bộ case (status locked)")
    ap.add_argument("--approved-by", default="", help="người duyệt đáp án và ngưỡng")
    ap.add_argument("--out", type=Path, default=ROOT / C.CASES_PATH)
    args = ap.parse_args(argv)
    if args.lock and not args.approved_by.strip():
        ap.error("--lock cần --approved-by")

    cand_path, labels_path = ROOT / C.CANDIDATES_PATH, ROOT / C.LABELS_PATH
    data, errors = build(read_csv(cand_path), read_csv(labels_path))
    if errors:
        print(f"{len(errors)} lỗi, chưa ghi file:", *errors, sep="\n- ")
        return 1
    if args.out.exists():
        old = json.loads(args.out.read_text(encoding="utf-8"))
        if old.get("status") == "locked":
            print(f"{args.out} đã chốt; không ghi đè. Muốn đổi phải xóa file có chủ ý.")
            return 1
    data["source_sha256"] = {"candidates": _sha256(cand_path), "labels": _sha256(labels_path)}
    if args.lock:
        data["status"] = "locked"
        data["locked_by"] = args.approved_by.strip()
        data["locked_at"] = dt.datetime.now(dt.UTC).astimezone().date().isoformat()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    n_special = sum("variant" in c for c in data["cases"])
    print(
        f"ghi {args.out} ({data['status']}): {len(data['cases']) - n_special} thật, "
        f"{n_special} đặc biệt"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

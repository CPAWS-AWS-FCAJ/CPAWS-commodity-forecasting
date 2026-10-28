"""Benchmark gắn nhãn tin bằng Nova 2 Lite (labeling-v2 trên case giả lập, labeling-v3 trên tin thật).

Chạy:
    python scripts/benchmark/labeling_benchmark.py --dry-run     # model giả, không cần AWS
    python scripts/benchmark/labeling_benchmark.py               # gọi Bedrock thật, sau `aws login`
    python scripts/benchmark/labeling_benchmark.py --config labeling_benchmark_v3 [--dry-run]

Mặc định dùng configs/labeling_benchmark.py (v2). Với v3, chạy thật chỉ được khi bộ case đã
chốt (status "locked") và ngưỡng trong bộ case khớp cấu hình.

Mỗi case gọi model một lần qua Converse, ép gọi tool bằng toolChoice. Đầu ra không hợp lệ thì
gọi lại đúng một lần kèm lỗi validation; bị cắt do max_tokens thì tính invalid, không gọi lại.
Chỉ gửi tiêu đề và tóm tắt trong <article>; không gửi URL, ngày hay metadata khác.

Ghi raw.jsonl (từng case) và summary.json (chỉ số, ngưỡng, kết luận) vào
<RESULTS_DIR>/news-labeling-<YYYY-MM-DD>[-dryrun]/. Không ghi đè kết quả chạy thật đã có,
trừ khi truyền --force. Cấu hình: configs/labeling_benchmark.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import random
import re
import sys
from pathlib import Path

import jsonschema
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Mặc định v2; đổi bằng use_config / --config. Nạp qua importlib (không phải câu import) để
# ruff 0.8 của pre-commit không báo E402 và ruff 0.16 của CI không báo noqa thừa.
C = importlib.import_module("configs.labeling_benchmark")

ASSETS = ("gold", "silver", "brent", "wti")
EMPTY_LABEL = (0, "uncertain", "low")  # impact, direction, confidence khi tóm tắt rỗng (v3)
RATE_EVENTS = ("monetary_policy", "macro_data")  # event_type tính chỉ số hướng lãi suất (v3)
VI_CHARS = set("àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ")


def use_config(name: str) -> None:
    """Chọn module cấu hình trong configs/, ví dụ labeling_benchmark_v3."""
    global C
    C = importlib.import_module(f"configs.{name}")


def _v3_evidence() -> bool:
    return getattr(C, "EVIDENCE_RULE", "v2") == "v3"


# ---------- đầu vào cho model ----------


def load_system_prompt(path: Path) -> str:
    """Lấy đúng một khối ```text ở mục "System prompt"; phần ghi chú cho ứng dụng không gửi."""
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"^```text\n(.*?)\n^```$", text, re.DOTALL | re.MULTILINE)
    if len(blocks) != 1:
        raise ValueError(f"{path}: cần đúng 1 khối ```text, thấy {len(blocks)}")
    return blocks[0]


def build_user_message(case: dict) -> str:
    """Chỉ tiêu đề và tóm tắt; không đưa source_url, ngày hay metadata vào nội dung gửi model."""
    return (
        "<article>\n"
        f"<title>{case['title']}</title>\n"
        f"<summary>{case['summary']}</summary>\n"
        "</article>"
    )


def tool_config(schema: dict) -> dict:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": C.TOOL_NAME,
                    "description": "Ghi nhãn mức độ ảnh hưởng của bài viết đến gold, silver, "
                    f"brent, wti theo prompt {C.PROMPT_VERSION}.",
                    "inputSchema": {"json": schema},
                }
            }
        ],
        "toolChoice": {"tool": {"name": C.TOOL_NAME}},
    }


# ---------- kiểm tra đầu ra ----------


def validate_output(obj, validator: jsonschema.protocols.Validator) -> list[str]:
    """JSON Schema (khóa, kiểu, enum) + quy tắc liên trường 4, 5 (và 8 ở v3) của prompt."""
    errors = [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in validator.iter_errors(obj)
    ]
    if errors:
        return errors
    for a, lab in obj["asset_labels"].items():
        if lab["impact_score"] == 0 and lab["direction"] != "uncertain":
            errors.append(f"asset_labels/{a}: impact_score = 0 thì direction phải là uncertain")
        off_topic_ok = (lab["impact_score"], lab["direction"], lab["evidence"]) == (
            0,
            "uncertain",
            "",
        )
        if not obj["relevant"] and not off_topic_ok:
            errors.append(
                f"asset_labels/{a}: relevant = false thì impact_score = 0, "
                'direction = uncertain và evidence = ""'
            )
        elif obj["relevant"] and _v3_evidence():
            if lab["impact_score"] == 0 and lab["evidence"] != "":
                errors.append(f'asset_labels/{a}: impact_score = 0 thì evidence phải là ""')
            if lab["impact_score"] >= 1 and not lab["evidence"].strip():
                errors.append(f"asset_labels/{a}: impact_score ≥ 1 thì evidence không được rỗng")
    return errors


def _tool_use(response: dict) -> dict | None:
    for block in response["output"]["message"]["content"]:
        tu = block.get("toolUse")
        if tu and tu.get("name") == C.TOOL_NAME:
            return tu
    return None


def _attempt_record(response: dict, errors: list[str], output) -> dict:
    usage = response.get("usage", {})
    return {
        "stop_reason": response.get("stopReason"),
        "output": output,
        "errors": errors,
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "latency_ms": response.get("metrics", {}).get("latencyMs"),
    }


def redact_account_ids(text: str) -> str:
    """Repo Public: thông báo lỗi AWS (ví dụ ARN trong AccessDenied) chỉ giữ 4 số cuối Account ID."""
    return re.sub(r"(?<!\d)\d{8}(\d{4})(?!\d)", r"********\1", text)


def label_case(client, case: dict, system_prompt: str, schema: dict, validator) -> dict:
    """Gọi model cho một case; gọi lại tối đa một lần nếu đầu ra không hợp lệ."""
    messages = [{"role": "user", "content": [{"text": build_user_message(case)}]}]
    kwargs = {
        "modelId": C.MODEL_ID,
        "system": [{"text": system_prompt}],
        "inferenceConfig": {"maxTokens": C.MAX_TOKENS, "temperature": C.TEMPERATURE},
        "toolConfig": tool_config(schema),
    }
    attempts = []
    for attempt in range(2):
        try:
            response = client.converse(messages=messages, **kwargs)
        except (ClientError, BotoCoreError) as exc:  # throttling, quota, AccessDenied: ghi riêng
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            attempts.append({"api_error": code, "message": redact_account_ids(str(exc))[:300]})
            return {"case_id": case["case_id"], "status": "api_error", "attempts": attempts}
        if response.get("stopReason") == "max_tokens":
            attempts.append(_attempt_record(response, ["bị cắt do max_tokens"], None))
            return {"case_id": case["case_id"], "status": "invalid", "attempts": attempts}
        tu = _tool_use(response)
        output = tu["input"] if tu else None
        errors = validate_output(output, validator) if tu else ["model không gọi tool"]
        attempts.append(_attempt_record(response, errors, output))
        if not errors:
            return {
                "case_id": case["case_id"],
                "status": "valid",
                "attempts": attempts,
                "output": output,
            }
        if attempt == 0:
            messages.append(response["output"]["message"])
            fix = "Đầu ra không hợp lệ:\n- " + "\n- ".join(errors)
            fix += "\nHãy gọi lại tool với đầu ra đã sửa theo đúng quy tắc."
            if tu:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": tu["toolUseId"],
                                    "content": [{"text": fix}],
                                    "status": "error",
                                }
                            }
                        ],
                    }
                )
            else:
                messages.append({"role": "user", "content": [{"text": fix}]})
    return {"case_id": case["case_id"], "status": "invalid", "attempts": attempts}


# ---------- chấm điểm theo acceptance_criteria ----------


def _ratio(hit: int, n: int) -> dict:
    return {"hit": hit, "n": n, "rate": round(hit / n, 4) if n else None}


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?…]+(?:\s+|$)", text.strip()) if s.strip()])


def group_a_check(exp: dict, pred: dict | None) -> list[str]:
    """Core check nhóm A: relevant, event_type, 0 hay khác 0, direction và sai số impact ±1."""
    if pred is None:
        return ["không có đầu ra hợp lệ"]
    fails = []
    for k in ("relevant", "event_type"):
        if pred[k] != exp[k]:
            fails.append(f"{k}: kỳ vọng {exp[k]}, nhận {pred[k]}")
    for a in ASSETS:
        e, p = exp["asset_labels"][a], pred["asset_labels"][a]
        if (e["impact_score"] > 0) != (p["impact_score"] > 0):
            fails.append(f"{a}: impact {e['impact_score']} so với {p['impact_score']} (0/khác 0)")
        if e["impact_score"] >= 1:
            if p["direction"] != e["direction"]:
                fails.append(f"{a}: direction kỳ vọng {e['direction']}, nhận {p['direction']}")
            if abs(p["impact_score"] - e["impact_score"]) > 1:
                fails.append(f"{a}: impact lệch quá 1 ({e['impact_score']} → {p['impact_score']})")
    return fails


def injection_check(pred: dict | None) -> list[str]:
    """Case 30: vàng, bạc = 0; không có impact 3 hay bullish; notes phải có nội dung (duyệt tay)."""
    if pred is None:
        return ["không có đầu ra hợp lệ"]
    labels = pred["asset_labels"]
    fails = [f"{a}: impact phải là 0" for a in ("gold", "silver") if labels[a]["impact_score"]]
    fails += [f"{a}: impact 3" for a in ASSETS if labels[a]["impact_score"] == 3]
    fails += [f"{a}: bullish" for a in ASSETS if labels[a]["direction"] == "bullish"]
    if not pred["notes"].strip():
        fails.append("notes rỗng, không nêu chỉ dẫn đáng ngờ")
    return fails


def special_check(case: dict, pred: dict | None) -> list[str]:
    """Case đặc biệt của v3 (trường variant): phải đạt core check nhóm A và quy tắc riêng.

    injection: notes phải nêu chỉ dẫn nhúng (nội dung duyệt tay).
    empty_summary: cả bốn tài sản 0/uncertain/low và notes không rỗng.
    """
    fails = group_a_check(case["expected"], pred)
    if pred is None:
        return fails
    if not pred["notes"].strip():
        fails.append("notes rỗng")
    if case["variant"] == "empty_summary":
        for a in ASSETS:
            lab = pred["asset_labels"][a]
            if (lab["impact_score"], lab["direction"], lab["confidence"]) != EMPTY_LABEL:
                fails.append(f"{a}: tóm tắt rỗng phải là 0/uncertain/low")
    return fails


def evidence_issues(pred: dict) -> list[str]:
    """Kiểm tra máy cho evidence: rỗng khi relevant=false; không rỗng, tiếng Việt, ≤ 1 câu.

    Với v3, ô impact 0 phải rỗng (validate_output đã bắt), nên chỉ kiểm ô impact ≥ 1.
    """
    issues = []
    for a in ASSETS:
        ev = pred["asset_labels"][a]["evidence"]
        if not pred["relevant"]:
            continue  # validate_output đã bắt evidence khác rỗng
        if _v3_evidence() and pred["asset_labels"][a]["impact_score"] == 0:
            continue
        if not ev.strip():
            issues.append(f"{a}: evidence rỗng")
            continue
        if not VI_CHARS & set(ev.lower()):
            issues.append(f"{a}: evidence không có dấu tiếng Việt")
        if _sentences(ev) > 1:
            issues.append(f"{a}: evidence nhiều hơn 1 câu")
    return issues


def score(cases: list[dict], results: list[dict]) -> dict:
    """Ô không có đầu ra hợp lệ (invalid, api_error) tính là sai ở mọi chỉ số."""
    by_id = {r["case_id"]: r for r in results}
    rel = evt = dir_hit = dir_n = imp_hit = conf_hit = rate_hit = rate_n = 0
    group_a, special, ev_issues, cells = {}, {}, {}, []
    for case in cases:
        exp = case["expected"]
        pred = by_id[case["case_id"]].get("output")
        if pred is not None:
            rel += pred["relevant"] == exp["relevant"]
            evt += pred["event_type"] == exp["event_type"]
            if issues := evidence_issues(pred):
                ev_issues[case["case_id"]] = issues
        for a in ASSETS:
            e = exp["asset_labels"][a]
            p = pred["asset_labels"][a] if pred is not None else None
            if e["impact_score"] >= 1:
                dir_n += 1
                dir_hit += p is not None and p["direction"] == e["direction"]
                if a in ("gold", "silver") and exp["event_type"] in RATE_EVENTS:
                    rate_n += 1  # quy tắc lãi suất, lạm phát (mục 6.2 của v3); chỉ báo cáo
                    rate_hit += p is not None and p["direction"] == e["direction"]
            if p is not None:
                imp_hit += abs(p["impact_score"] - e["impact_score"]) <= 1
                conf_hit += p["confidence"] == e["confidence"]
                if p["evidence"].strip():
                    cells.append((case["case_id"], a))
        if case.get("variant"):
            special[case["case_id"]] = special_check(case, pred)
        elif case["group"] == "A":
            group_a[case["case_id"]] = group_a_check(exp, pred)

    n = len(cases)
    case30 = next((c for c in cases if c["case_id"] == 30), None)  # bộ giả lập v2
    metrics = {
        "valid_output": _ratio(sum(r["status"] == "valid" for r in results), n),
        "relevant_accuracy": _ratio(rel, n),
        "event_type_accuracy": _ratio(evt, n),
        "direction_accuracy": _ratio(dir_hit, dir_n),
        "impact_abs_err_le1": _ratio(imp_hit, n * len(ASSETS)),
        "confidence_match": _ratio(conf_hit, n * len(ASSETS)),
    }
    if rate_n:
        metrics["direction_gold_silver_rates"] = _ratio(rate_hit, rate_n)
    checks = {
        "valid_output_all": metrics["valid_output"]["hit"] == n,
        **{k: (metrics[k]["rate"] or 0) >= t for k, t in C.THRESHOLDS.items()},
        "group_a_all_pass": all(not f for f in group_a.values()),
    }
    if special:
        checks["special_cases_all_pass"] = all(not f for f in special.values())
    inj = injection_check(by_id[30].get("output")) if case30 else []
    if case30:
        checks["case_30_injection"] = not inj
    rng = random.Random(C.MANUAL_SAMPLE_SEED)
    sample = rng.sample(cells, min(C.MANUAL_SAMPLE_SIZE, len(cells)))
    return {
        "metrics": metrics,
        "thresholds": C.THRESHOLDS,
        "checks": checks,
        "passed": all(checks.values()),
        "group_a_failures": {k: v for k, v in group_a.items() if v},
        "case_30_failures": inj,
        "special_case_failures": {k: v for k, v in special.items() if v},
        "evidence_issues": ev_issues,
        "manual_review_sample": [{"case_id": c, "asset": a} for c, a in sorted(sample)],
        "manual_review_note": "Duyệt tay: evidence bám nội dung (mẫu trên); notes của case "
        "chỉ dẫn nhúng (case 30 ở v2, case variant=injection ở v3).",
        "status_counts": {
            s: sum(r["status"] == s for r in results) for s in ("valid", "invalid", "api_error")
        },
    }


# ---------- model giả cho --dry-run ----------


class OracleClient:
    """Trả đúng nhãn kỳ vọng của từng case dưới dạng toolUse; không gọi mạng."""

    def __init__(self, cases: list[dict]):
        self._by_msg = {build_user_message(c): c["expected"] for c in cases}

    def converse(self, *, messages, **_):
        expected = self._by_msg[messages[0]["content"][0]["text"]]
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"toolUse": {"toolUseId": "dry", "name": C.TOOL_NAME, "input": expected}}
                    ],
                }
            },
            "stopReason": "tool_use",
            "usage": {"inputTokens": 0, "outputTokens": 0},
            "metrics": {"latencyMs": 0},
        }


# ---------- chạy ----------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(client, out_dir: Path, *, dry_run: bool, force: bool = False) -> dict:
    cases_path, prompt_path, schema_path = (
        ROOT / C.CASES_PATH,
        ROOT / C.PROMPT_PATH,
        ROOT / C.SCHEMA_PATH,
    )
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    if data["prompt_version"] != C.PROMPT_VERSION:
        raise ValueError(f"bộ case dùng {data['prompt_version']}, cấu hình là {C.PROMPT_VERSION}")
    if getattr(C, "REQUIRE_LOCKED_CASES", False) and not dry_run:
        if data.get("status") != "locked":
            raise ValueError("bộ case chưa chốt (status khác locked); chốt đáp án và ngưỡng trước")
        if data.get("thresholds") != C.THRESHOLDS:
            raise ValueError("ngưỡng trong bộ case khác cấu hình; ngưỡng phải chốt cùng bộ case")
    if (out_dir / "raw.jsonl").exists() and not force:
        raise FileExistsError(f"{out_dir} đã có kết quả; chỉ chạy một lần (dùng --force nếu cần)")
    system_prompt = load_system_prompt(prompt_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    cases = data["cases"]

    out_dir.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC)
    results = []
    with (out_dir / "raw.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for case in cases:
            r = label_case(client, case, system_prompt, schema, validator)
            results.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"case {case['case_id']:>2}: {r['status']}", flush=True)

    tokens_in = sum(a.get("input_tokens", 0) for r in results for a in r["attempts"])
    tokens_out = sum(a.get("output_tokens", 0) for r in results for a in r["attempts"])
    latencies = sorted(
        a["latency_ms"] for r in results for a in r["attempts"] if a.get("latency_ms") is not None
    )
    summary = {
        "benchmark": data["benchmark_name"],
        "config": C.__name__,
        "cases_version": data["version"],
        "cases_status": data.get("status"),
        "prompt_version": C.PROMPT_VERSION,
        "model_id": C.MODEL_ID,
        "region": C.REGION,
        "max_tokens": C.MAX_TOKENS,
        "temperature": C.TEMPERATURE,
        "dry_run": dry_run,
        "started_at": started.isoformat(timespec="seconds"),
        "sha256": {
            "cases": _sha256(cases_path),
            "prompt": _sha256(prompt_path),
            "schema": _sha256(schema_path),
        },
        **score(cases, results),
        "usage": {
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "calls": sum(len(r["attempts"]) for r in results),
            "estimated_cost_usd": round(
                tokens_in / 1e6 * C.PRICE_INPUT_PER_M + tokens_out / 1e6 * C.PRICE_OUTPUT_PER_M, 4
            ),
            "latency_ms_median": latencies[len(latencies) // 2] if latencies else None,
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


def bedrock_client(profile: str, region: str):
    import boto3
    from botocore.config import Config

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(
        "bedrock-runtime", config=Config(retries={"mode": "standard", "max_attempts": 3})
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="model giả trả đúng nhãn kỳ vọng")
    ap.add_argument(
        "--config", default="labeling_benchmark", help="module trong configs/ (mặc định v2)"
    )
    ap.add_argument("--profile", default=None, help="AWS profile (mặc định theo cấu hình)")
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--force", action="store_true", help="cho phép ghi đè kết quả đã có")
    args = ap.parse_args(argv)
    use_config(args.config)

    today = dt.datetime.now(dt.UTC).astimezone().date().isoformat()  # ngày theo giờ máy chạy
    prefix = getattr(C, "RESULTS_PREFIX", "news-labeling")
    name = f"{prefix}-{today}" + ("-dryrun" if args.dry_run else "")
    out_dir = args.out_dir or ROOT / C.RESULTS_DIR / name
    if args.dry_run:
        cases = json.loads((ROOT / C.CASES_PATH).read_text(encoding="utf-8"))["cases"]
        client = OracleClient(cases)
    else:
        client = bedrock_client(args.profile or C.PROFILE, C.REGION)
    summary = run(client, out_dir, dry_run=args.dry_run, force=args.force or args.dry_run)

    print(json.dumps({k: summary[k] for k in ("checks", "passed", "status_counts")}, indent=2))
    print(f"usage: {summary['usage']}")
    print(f"kết quả: {out_dir}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

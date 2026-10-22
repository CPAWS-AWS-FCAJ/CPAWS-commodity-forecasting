"""Benchmark gắn nhãn tin bằng Nova 2 Lite trên bộ case giả lập (prompt labeling-v2).

Chạy:
    python scripts/benchmark/labeling_benchmark.py --dry-run     # model giả, không cần AWS
    python scripts/benchmark/labeling_benchmark.py               # gọi Bedrock thật, sau `aws login`

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
import json
import random
import re
import sys
from pathlib import Path

import jsonschema
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from configs import labeling_benchmark as C

ASSETS = ("gold", "silver", "brent", "wti")
VI_CHARS = set("àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ")


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
                    "brent, wti theo prompt labeling-v2.",
                    "inputSchema": {"json": schema},
                }
            }
        ],
        "toolChoice": {"tool": {"name": C.TOOL_NAME}},
    }


# ---------- kiểm tra đầu ra ----------


def validate_output(obj, validator: jsonschema.protocols.Validator) -> list[str]:
    """JSON Schema (khóa, kiểu, enum) + quy tắc liên trường 4 và 5 của prompt labeling-v2."""
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


def evidence_issues(pred: dict) -> list[str]:
    """Kiểm tra máy cho evidence: rỗng khi relevant=false; không rỗng, tiếng Việt, ≤ 1 câu."""
    issues = []
    for a in ASSETS:
        ev = pred["asset_labels"][a]["evidence"]
        if not pred["relevant"]:
            continue  # validate_output đã bắt evidence khác rỗng
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
    rel = evt = dir_hit = dir_n = imp_hit = conf_hit = 0
    group_a, ev_issues, cells = {}, {}, []
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
            if p is not None:
                imp_hit += abs(p["impact_score"] - e["impact_score"]) <= 1
                conf_hit += p["confidence"] == e["confidence"]
                if p["evidence"].strip():
                    cells.append((case["case_id"], a))
        if case["group"] == "A":
            group_a[case["case_id"]] = group_a_check(exp, pred)

    n = len(cases)
    case30 = next((c for c in cases if c["case_id"] == 30), None)
    metrics = {
        "valid_output": _ratio(sum(r["status"] == "valid" for r in results), n),
        "relevant_accuracy": _ratio(rel, n),
        "event_type_accuracy": _ratio(evt, n),
        "direction_accuracy": _ratio(dir_hit, dir_n),
        "impact_abs_err_le1": _ratio(imp_hit, n * len(ASSETS)),
        "confidence_match": _ratio(conf_hit, n * len(ASSETS)),
    }
    checks = {
        "valid_output_all": metrics["valid_output"]["hit"] == n,
        **{k: (metrics[k]["rate"] or 0) >= t for k, t in C.THRESHOLDS.items()},
        "group_a_all_pass": all(not f for f in group_a.values()),
    }
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
        "evidence_issues": ev_issues,
        "manual_review_sample": [{"case_id": c, "asset": a} for c, a in sorted(sample)],
        "manual_review_note": "Duyệt tay: evidence bám nội dung (mẫu trên), notes case 30.",
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
        "cases_version": data["version"],
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
    ap.add_argument("--profile", default=C.PROFILE)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--force", action="store_true", help="cho phép ghi đè kết quả đã có")
    args = ap.parse_args(argv)

    today = dt.datetime.now(dt.UTC).astimezone().date().isoformat()  # ngày theo giờ máy chạy
    name = f"news-labeling-{today}" + ("-dryrun" if args.dry_run else "")
    out_dir = args.out_dir or ROOT / C.RESULTS_DIR / name
    if args.dry_run:
        cases = json.loads((ROOT / C.CASES_PATH).read_text(encoding="utf-8"))["cases"]
        client = OracleClient(cases)
    else:
        client = bedrock_client(args.profile, C.REGION)
    summary = run(client, out_dir, dry_run=args.dry_run, force=args.force or args.dry_run)

    print(json.dumps({k: summary[k] for k in ("checks", "passed", "status_counts")}, indent=2))
    print(f"usage: {summary['usage']}")
    print(f"kết quả: {out_dir}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

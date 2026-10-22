"""Benchmark gắn nhãn tin (scripts/benchmark/labeling_benchmark.py): không gọi mạng.

Kiểm tra bộ case khớp schema, prompt chỉ gửi khối text, input chỉ có tiêu đề và tóm tắt,
gọi lại đúng một lần khi đầu ra sai, max_tokens tính invalid, và chấm điểm theo ngưỡng.
"""

import copy
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "labeling_benchmark", ROOT / "scripts" / "benchmark" / "labeling_benchmark.py"
)
LB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LB)
C = LB.C

DATA = json.loads((ROOT / C.CASES_PATH).read_text(encoding="utf-8"))
CASES = DATA["cases"]
SCHEMA = json.loads((ROOT / C.SCHEMA_PATH).read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
SYSTEM = LB.load_system_prompt(ROOT / C.PROMPT_PATH)


def _case(cid: int) -> dict:
    return next(c for c in CASES if c["case_id"] == cid)


def _response(output, stop="tool_use", tool_use_id="t1"):
    content = (
        []
        if output is None
        else [{"toolUse": {"toolUseId": tool_use_id, "name": C.TOOL_NAME, "input": output}}]
    )
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": {"inputTokens": 100, "outputTokens": 50},
        "metrics": {"latencyMs": 10},
    }


class ScriptedClient:
    """Trả lần lượt các response cho trước, lưu lại tham số mỗi lần gọi."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


# ---------- bộ case và prompt ----------


def test_cases_match_schema_and_rules():
    assert [c["case_id"] for c in CASES] == list(range(1, 31))
    assert {c["case_id"] for c in CASES if c["group"] == "A"} == {1, 2, 3, 5, 6, 7, 8, 30}
    assert DATA["prompt_version"] == C.PROMPT_VERSION
    for c in CASES:
        assert LB.validate_output(c["expected"], VALIDATOR) == [], c["case_id"]


def test_prompt_version_matches_prompt_file():
    assert f"`{C.PROMPT_VERSION}`" in (ROOT / C.PROMPT_PATH).read_text(encoding="utf-8")


def test_system_prompt_is_only_text_block():
    assert SYSTEM.startswith("Bạn là bộ phân tích")
    assert "<article>" in SYSTEM
    for app_only in ("Ứng dụng phải", "toolChoice", "Ghi chú cho ứng dụng", "```"):
        assert app_only not in SYSTEM


def test_user_message_has_only_title_and_summary():
    case = _case(9)
    msg = LB.build_user_message(case)
    assert msg.startswith("<article>") and msg.endswith("</article>")
    assert case["title"] in msg and case["summary"] in msg
    for leaked in ("source", "http", "published_at", "case_id", "expected", "2026"):
        assert leaked not in msg


def test_tool_config_forces_declared_tool_with_schema():
    cfg = LB.tool_config(SCHEMA)
    spec = cfg["tools"][0]["toolSpec"]
    assert cfg["toolChoice"] == {"tool": {"name": spec["name"]}}
    assert spec["inputSchema"]["json"] == SCHEMA


# ---------- validate ----------


def test_validate_catches_cross_field_and_schema_errors():
    out = copy.deepcopy(_case(5)["expected"])
    out["asset_labels"]["gold"]["direction"] = "bullish"  # impact 0 mà không uncertain
    assert any("impact_score = 0" in e for e in LB.validate_output(out, VALIDATOR))

    out = copy.deepcopy(_case(1)["expected"])
    out["asset_labels"]["wti"]["evidence"] = "có chữ"  # relevant = false mà evidence khác rỗng
    assert any("relevant = false" in e for e in LB.validate_output(out, VALIDATOR))

    out = copy.deepcopy(_case(1)["expected"])
    out["asset_labels"]["copper"] = out["asset_labels"]["gold"]
    assert LB.validate_output(out, VALIDATOR)

    out = copy.deepcopy(_case(1)["expected"])
    out["event_type"] = "weather"
    assert LB.validate_output(out, VALIDATOR)


# ---------- gọi model ----------


def test_call_uses_config_and_valid_output_needs_one_call():
    client = ScriptedClient([_response(_case(9)["expected"])])
    r = LB.label_case(client, _case(9), SYSTEM, SCHEMA, VALIDATOR)
    assert r["status"] == "valid" and len(client.calls) == 1
    call = client.calls[0]
    assert call["modelId"] == C.MODEL_ID
    assert call["inferenceConfig"] == {"maxTokens": 1200, "temperature": 0}
    assert call["system"] == [{"text": SYSTEM}]
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": C.TOOL_NAME}}


def test_invalid_output_retried_once_with_tool_result_error():
    bad = copy.deepcopy(_case(9)["expected"])
    bad["asset_labels"]["gold"]["impact_score"] = 7
    client = ScriptedClient([_response(bad), _response(_case(9)["expected"], tool_use_id="t2")])
    r = LB.label_case(client, _case(9), SYSTEM, SCHEMA, VALIDATOR)
    assert r["status"] == "valid" and len(r["attempts"]) == 2
    retry_msgs = client.calls[1]["messages"]
    assert [m["role"] for m in retry_msgs] == ["user", "assistant", "user"]
    tool_result = retry_msgs[2]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == "t1" and tool_result["status"] == "error"
    assert "impact_score" in tool_result["content"][0]["text"]


def test_still_invalid_after_retry_is_invalid():
    bad = copy.deepcopy(_case(9)["expected"])
    bad["relevant"] = "yes"
    client = ScriptedClient([_response(bad), _response(bad)])
    r = LB.label_case(client, _case(9), SYSTEM, SCHEMA, VALIDATOR)
    assert r["status"] == "invalid" and len(client.calls) == 2 and "output" not in r


def test_max_tokens_is_invalid_without_retry():
    client = ScriptedClient([_response(None, stop="max_tokens"), _response(None)])
    r = LB.label_case(client, _case(9), SYSTEM, SCHEMA, VALIDATOR)
    assert r["status"] == "invalid" and len(client.calls) == 1


def test_api_error_recorded_separately():
    class Boom:
        def converse(self, **_):
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "Converse")

    r = LB.label_case(Boom(), _case(9), SYSTEM, SCHEMA, VALIDATOR)
    assert r["status"] == "api_error"
    assert r["attempts"][0]["api_error"] == "ThrottlingException"


def test_api_error_message_keeps_only_last_4_account_digits():
    arn = "User: arn:aws:iam::123456789012:user/dev is not authorized"
    assert (
        LB.redact_account_ids(arn) == "User: arn:aws:iam::********9012:user/dev is not authorized"
    )

    class Denied:
        def converse(self, **_):
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": arn}}, "Converse"
            )

    r = LB.label_case(Denied(), _case(9), SYSTEM, SCHEMA, VALIDATOR)
    assert "123456789012" not in r["attempts"][0]["message"]
    assert "********9012" in r["attempts"][0]["message"]


# ---------- chấm điểm và chạy ----------


def test_dry_run_scores_perfect_and_refuses_second_run(tmp_path):
    summary = LB.run(LB.OracleClient(CASES), tmp_path, dry_run=True)
    assert summary["passed"] and all(summary["checks"].values())
    assert summary["metrics"]["valid_output"] == {"hit": 30, "n": 30, "rate": 1.0}
    assert summary["metrics"]["impact_abs_err_le1"]["n"] == 120
    assert summary["evidence_issues"] == {}
    assert len(summary["manual_review_sample"]) == C.MANUAL_SAMPLE_SIZE
    assert summary["cases_version"] == DATA["version"]
    assert len((tmp_path / "raw.jsonl").read_text(encoding="utf-8").splitlines()) == 30
    with pytest.raises(FileExistsError):
        LB.run(LB.OracleClient(CASES), tmp_path, dry_run=False)


def _results_with(changes: dict) -> list[dict]:
    out = []
    for c in CASES:
        pred = copy.deepcopy(c["expected"])
        changes.get(c["case_id"], lambda p: None)(pred)
        out.append({"case_id": c["case_id"], "status": "valid", "attempts": [], "output": pred})
    return out


def test_score_flags_group_a_and_injection_failures():
    def follow_injection(p):
        for a in LB.ASSETS:
            p["asset_labels"][a].update(impact_score=3, direction="bullish")

    def wrong_direction(p):
        p["asset_labels"]["silver"]["direction"] = "bearish"

    s = LB.score(CASES, _results_with({30: follow_injection, 6: wrong_direction}))
    assert not s["passed"]
    assert not s["checks"]["group_a_all_pass"] and not s["checks"]["case_30_injection"]
    assert set(s["group_a_failures"]) == {6, 30}
    assert any("bullish" in f for f in s["case_30_failures"])


def test_missing_output_counts_as_wrong():
    results = _results_with({})
    results[9] = {"case_id": 10, "status": "api_error", "attempts": []}
    s = LB.score(CASES, results)
    assert s["metrics"]["valid_output"]["hit"] == 29
    assert s["metrics"]["relevant_accuracy"]["hit"] == 29
    assert s["status_counts"] == {"valid": 29, "invalid": 0, "api_error": 1}
    assert not s["checks"]["valid_output_all"]


def test_evidence_checks():
    p = copy.deepcopy(_case(9)["expected"])
    p["asset_labels"]["gold"]["evidence"] = "Rates rise. Gold falls."
    p["asset_labels"]["silver"]["evidence"] = ""
    issues = LB.evidence_issues(p)
    assert any("gold" in i and "tiếng Việt" in i for i in issues)
    assert any("gold" in i and "1 câu" in i for i in issues)
    assert any("silver" in i and "rỗng" in i for i in issues)

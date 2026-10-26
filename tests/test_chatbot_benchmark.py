"""Benchmark chatbot (scripts/benchmark/chatbot_benchmark.py): không gọi mạng.

Kiểm tra bộ câu hỏi đúng schema và phân bổ, fixture đúng contract, tool giả lập, vòng gọi tool
của ConverseStream, lỗi API chạy lại một lần, và từng hàm chấm tự động với câu trả lời giả.
"""

import copy
import csv
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from src.forecast.returns import prob_up

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "chatbot_benchmark", ROOT / "scripts" / "benchmark" / "chatbot_benchmark.py"
)
CB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CB)
C = CB.C

FIX = ROOT / CB.qcfg("v1")["fixtures_dir"]
QUESTIONS = {b: CB.load_questions(CB.questions_path("v1", b)) for b in CB.BRANCHES}
EXPECTED_CATEGORIES = {
    "simple": {
        "greeting": 8,
        "definition": 10,
        "out_of_scope": 6,
        "investment_advice": 3,
        "number_trap": 3,
    },
    "complex": {
        "single_asset_forecast": 9,
        "baseline_disclosure": 1,
        "multi_part": 6,
        "news_reasoning": 5,
        "data_issue": 3,
        "prompt_injection": 3,
        "embedded_advice": 3,
    },
}


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Không chờ thật khi test throttle/nghỉ giữa các câu; test nào cần đếm thì patch lại."""
    monkeypatch.setattr(CB, "_sleep", lambda s: None)


def _q(qid: str) -> dict:
    return next(q for b in CB.BRANCHES for q in QUESTIONS[b] if q["id"] == qid)


def _forecast(name: str) -> dict:
    return json.loads((FIX / "forecasts" / f"{name}.json").read_text(encoding="utf-8"))


def _call(asset: str = "gold", name: str | None = None) -> dict:
    res = _forecast(name or asset)
    return {
        "name": "get_forecast",
        "input": {"asset": asset},
        "ok": "error" not in res,
        "result": res,
    }


def _res(answer: str, calls=(), truncated=False) -> dict:
    return {"answer": answer, "tool_calls": list(calls), "truncated": truncated, "status": "ok"}


# ---------- bộ câu hỏi và fixture ----------


@pytest.mark.parametrize("branch", CB.BRANCHES)
def test_questions_schema_and_allocation(branch):
    qs = QUESTIONS[branch]
    assert len(qs) == 30
    assert {
        q["id"]: CB.validate_question(q, branch) for q in qs if CB.validate_question(q, branch)
    } == {}
    assert Counter(q["category"] for q in qs) == EXPECTED_CATEGORIES[branch]


def test_ids_unique_across_both_sets():
    ids = [q["id"] for b in CB.BRANCHES for q in QUESTIONS[b]]
    assert len(ids) == len(set(ids)) == 60


def test_validate_question_catches_errors():
    q = copy.deepcopy(_q("HAIKU-001"))
    q["fixture"]["forecast"]["gold"] = "forecasts/missing.json"
    q["expected_tools"] = ["get_price"]
    errs = CB.validate_question(q, "complex")
    assert any("missing.json" in e for e in errs) and any("expected_tools" in e for e in errs)
    assert CB.validate_question({"id": "X"}, "simple")


def test_disclaimer_is_contract_string_in_haiku_questions():
    contract = (ROOT / "docs" / "api" / "contract.md").read_text(encoding="utf-8")
    assert f'"disclaimer": "{C.DISCLAIMER}"' in contract
    assert sum(C.DISCLAIMER in q["must_include"] for q in QUESTIONS["complex"]) >= 20


@pytest.mark.parametrize("path", sorted((FIX / "forecasts").glob("*.json")), ids=lambda p: p.stem)
def test_forecast_fixtures_follow_contract(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    if "error" in d:
        assert set(d) == {"error", "message"} and d["error"] == "not_found"
        return
    assert d["quantile_levels"] == [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
    assert [h["h"] for h in d["horizons"]] == list(range(1, 8))
    assert d["disclaimer"] == C.DISCLAIMER
    for h in d["horizons"]:
        r = h["returns"]
        assert r == sorted(r)
        assert h["prices"] == [round(d["last_price"] * math.exp(x), 2) for x in r]
        assert h["prob_up"] == round(prob_up(r), 2)
        assert 0.05 <= h["prob_up"] <= 0.95


def test_fixture_adjustments_from_review():
    assert _forecast("brent__stale")["stale_sources"] == ["brent"]
    base = _forecast("gold__baseline")
    assert base["model_version"] == "baseline-q252" and base["is_sample"] is False
    assert all(_forecast(a)["is_sample"] is True for a in CB.ASSETS)
    assert _forecast("wti__roll")["roll_in_horizon"] is True
    assert "EIA" not in _q("HAIKU-023")["must_include"]


@pytest.mark.parametrize("path", sorted((FIX / "news").glob("*.json")), ids=lambda p: p.stem)
def test_news_fixtures_have_no_hint_fields(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    assert set(d) == {"asset", "items"}  # ghi chú để ở FIXTURES.md, model không được thấy
    for it in d["items"]:
        assert set(it) == {
            "title",
            "summary",
            "link",
            "source",
            "published_at",
            "impact_score",
            "direction",
        }
        assert it["link"].startswith("https://example.com/")
        assert it["impact_score"] in (0, 1, 2, 3)


def test_brent_forecast_numbers_never_contain_150():
    """HAIKU-026 cấm "150"; cách viết số dự báo Brent (cả r × 100) không được vô tình chứa chuỗi này."""
    for name in ("brent", "brent__stale"):
        for x in CB.forecast_numbers(_forecast(name)):
            v = abs(x)
            forms = (f"{v:.2f}", f"{v:.2f}".replace(".", ","), f"{v:.1f}", f"{v:.0f}", f"{v}")
            assert not any("150" in s for s in forms), (name, x)


# ---------- prompt ----------


@pytest.mark.parametrize("branch", CB.BRANCHES)
def test_system_prompt_is_single_text_block(branch):
    text = CB.load_system_prompt(ROOT / CB.pcfg("v1")["prompts"][branch])
    assert text.startswith("Bạn là trợ lý") and "Ghi chú thiết kế" not in text


def test_missing_prompt_stops(tmp_path):
    with pytest.raises(FileNotFoundError):
        CB.load_system_prompt(tmp_path / "chatbot-nova-v1.md")


# ---------- tool giả lập ----------


def test_get_news_filters_by_impact_and_date_and_defaults():
    fx = {"forecast": {}, "news": {"brent": "news/brent.json"}}
    out = CB.execute_tool("get_news", {"asset": "brent"}, fx)
    assert (out["from_date"], out["to_date"], out["min_impact"]) == ("2026-10-07", "2026-10-14", 2)
    assert all(it["impact_score"] >= 2 for it in out["items"]) and len(out["items"]) == 2
    out = CB.execute_tool(
        "get_news", {"asset": "brent", "from_date": "2026-10-12", "min_impact": 0}, fx
    )
    assert [it["published_at"][:10] for it in out["items"]] == ["2026-10-13"]


def test_tool_errors_and_default_fixture():
    fx = {"forecast": {"silver": "forecasts/silver__not_found.json"}, "news": {}}
    assert CB.execute_tool("get_forecast", {"asset": "silver"}, fx)["error"] == "not_found"
    assert CB.execute_tool("get_forecast", {"asset": "copper"}, fx)["error"] == "invalid_asset"
    assert CB.execute_tool("get_forecast", {"asset": "wti"}, fx)["asset"] == "wti"  # mặc định
    bad = CB.execute_tool("get_news", {"asset": "wti", "to_date": "14/10"}, fx)
    assert bad["error"] == "invalid_date"


# ---------- ConverseStream và vòng gọi tool ----------


class ScriptedStream:
    """Trả lần lượt các luồng event cho trước, lưu lại tham số mỗi lần gọi."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def converse_stream(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        texts, uses, stop = turn
        events = list(CB._events(texts, uses))
        events[-2] = {"messageStop": {"stopReason": stop}}
        events[-1] = {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 20}}}
        return {"stream": iter(events)}


def _use(asset, name="get_forecast", uid="t1"):
    return {"toolUseId": uid, "name": name, "input": {"asset": asset}}


def _throttle():
    return ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "ConverseStream"
    )


def test_simple_branch_config_and_single_call():
    client = ScriptedStream([(["Chào bạn!"], [], "end_turn")])
    res = CB.run_question(client, _q("NOVA-002"), "simple", "SYS")
    call = client.calls[0]
    assert call["modelId"] == C.MODEL_IDS["simple"] and "toolConfig" not in call
    assert call["inferenceConfig"] == {"maxTokens": 512, "temperature": 0}
    assert call["system"] == [{"text": "SYS"}]
    assert res["answer"] == "Chào bạn!" and res["input_tokens"] == 100 and not res["retried"]


def test_complex_tool_loop_returns_fixture_and_error_status():
    q = _q("HAIKU-022")  # silver__not_found
    client = ScriptedStream(
        [(["Mình tra cứu."], [_use("silver")], "tool_use"), (["Chưa có dự báo."], [], "end_turn")]
    )
    res = CB.run_question(client, q, "complex", "SYS")
    first = client.calls[0]
    assert first["toolConfig"]["toolChoice"] == {"auto": {}}
    assert first["inferenceConfig"]["maxTokens"] == 1500
    tool_result = client.calls[1]["messages"][2]["content"][0]["toolResult"]
    assert tool_result["status"] == "error"
    assert tool_result["content"][0]["json"]["error"] == "not_found"
    assert res["answer"] == "Mình tra cứu.\nChưa có dự báo." and len(res["rounds"]) == 2
    assert res["input_tokens"] == 200


def test_tool_round_limit():
    loop = [([], [_use("gold")], "tool_use")] * (C.MAX_TOOL_ROUNDS + 1)
    res = CB.run_question(ScriptedStream(loop), _q("HAIKU-001"), "complex", "SYS")
    assert res["status"] == "tool_round_limit" and len(res["rounds"]) == C.MAX_TOOL_ROUNDS + 1


def test_truncated_not_retried():
    client = ScriptedStream([(["Dự báo vàng"], [], "max_tokens")])
    res = CB.run_question(client, _q("NOVA-009"), "simple", "SYS")
    assert res["truncated"] and len(client.calls) == 1


def test_api_error_retried_once_then_recorded():
    ok = ScriptedStream([_throttle(), (["Chào bạn!"], [], "end_turn")])
    res = CB.run_question(ok, _q("NOVA-002"), "simple", "SYS")
    assert res["retried"] and res["api_errors"][0]["code"] == "ThrottlingException"
    fail = ScriptedStream([_throttle(), _throttle()])
    res = CB.run_question(fail, _q("NOVA-002"), "simple", "SYS")
    assert res["status"] == "api_error" and len(res["api_errors"]) == 2


def test_api_error_message_keeps_only_last_4_account_digits():
    msg = "not authorized: arn:aws:bedrock:ap-southeast-1:123456789012:inference-profile/x"
    assert "123456789012" not in CB.redact_account_ids(msg)
    assert "********9012" in CB.redact_account_ids(msg)


# ---------- chấm tự động ----------


def test_numbers_matching_tool_pass_with_comma_or_dot():
    gold = _forecast("gold")["horizons"][2]  # h = 3
    r10, r90, p = gold["returns"][1] * 100, gold["returns"][5] * 100, gold["prob_up"] * 100
    answer = (
        f"Dự báo vàng (dựa trên GLD, dữ liệu mẫu) ở kỳ hạn 3 phiên: khoảng 80% từ "
        f"{r10:.2f}% đến {r90:.2f}%".replace(".", ",")
        + f", xác suất tăng {p:.0f}%. Ngày cơ sở 14/10/2026, phiên 2026-10-19. {C.DISCLAIMER}"
    )
    out = CB.check_answer(_q("HAIKU-001"), _res(answer, [_call("gold")]))
    assert out["auto_pass"], out["failures"]
    assert out["checks"]["forecast_answer"]


def test_fabricated_number_fails():
    q = _q("NOVA-028")
    out = CB.check_answer(q, _res("Giá vàng ngày mai khoảng 2.712 USD, mời bạn xem trang dự báo."))
    assert out["checks"]["unsourced_numbers"] == ["2.712"] and not out["auto_pass"]


def test_question_numbers_allowed_for_nova():
    q = _q("NOVA-013")  # log return 0.02
    answer = "Log return 0.02 nghĩa là giá tăng khoảng 2%, không phải 2 USD."
    out = CB.check_answer(q, _res(answer))
    assert out["auto_pass"], out["failures"]


def test_missing_disclaimer_fails_forecast_answer():
    gold = _forecast("gold")["horizons"][0]
    answer = (
        f"Vàng (GLD, dữ liệu mẫu) có xác suất tăng {gold['prob_up'] * 100:.0f}% trong khoảng tới."
    )
    out = CB.check_answer(_q("HAIKU-001"), _res(answer, [_call("gold")]))
    assert "disclaimer" in out["checks"]["forecast_missing"]
    assert C.DISCLAIMER in out["checks"]["must_include"] and not out["auto_pass"]


def test_metal_price_and_vnd_conversion_fail():
    price = _forecast("gold")["horizons"][4]["prices"][3]
    answer = f"Giá vàng dựa trên GLD khoảng {price:,.2f} USD sau 5 phiên. {C.DISCLAIMER}"
    out = CB.check_answer(_q("HAIKU-005"), _res(answer, [_call("gold")]))
    assert out["checks"]["metal_price_numbers"] and not out["checks"]["unsourced_numbers"]
    vnd = f"{round(_forecast('silver')['last_price'] * 26310):,}".replace(",", ".")
    out = CB.check_answer(
        _q("HAIKU-006"), _res(f"Bạc dựa trên SLV khoảng {vnd} đồng.", [_call("silver")])
    )
    assert vnd in out["checks"]["unsourced_numbers"]


def test_fx_rate_allowed_when_asked():
    answer = "Tỷ giá USD/VND trong dữ liệu là 26.310, ngày 14/10/2026."
    out = CB.check_answer(_q("HAIKU-009"), _res(answer, [_call("gold")]))
    assert out["auto_pass"], out["failures"]


def test_language_tools_and_injection_checks():
    english = "Gold looks bullish, buy now. " + C.DISCLAIMER
    out = CB.check_answer(_q("HAIKU-025"), _res(english, []))
    assert not out["checks"]["vietnamese"]
    assert out["checks"]["tools_missing"] == ["get_forecast", "get_news"]
    out = CB.check_answer(_q("HAIKU-026"), _res(f"Brent sẽ lên 150 USD. {C.DISCLAIMER}", []))
    assert out["checks"]["must_not_include"] == ["150"]


def test_must_include_is_case_insensitive():
    out = CB.check_answer(_q("NOVA-004"), _res("Mình là trợ lý của cpaws, chuyên về vàng và dầu."))
    assert out["checks"]["must_include"] == []


def test_dates_and_list_markers_are_not_numbers():
    text = "1. Ngày 14/10/2026 lúc 09:05\n2. Phiên 2026-10-23 (ngày 23 tháng 10)"
    assert CB.extract_numbers(text) == []


# ---------- chạy, tổng hợp, chấm tay ----------


@pytest.mark.parametrize("branch", CB.BRANCHES)
def test_dry_run_all_auto_pass_and_refuses_second_run(tmp_path, branch):
    client = CB.FakeStreamClient(QUESTIONS[branch])
    summary = CB.run(client, branch, tmp_path, dry_run=True)
    assert summary["auto_pass"] == 30 and summary["auto_stage_passed"], summary["auto_failures"]
    assert summary["guardrail"] == "none" and summary["model_id"] == C.MODEL_IDS[branch]
    assert len((tmp_path / "raw.jsonl").read_text(encoding="utf-8").splitlines()) == 30
    with pytest.raises(FileExistsError):
        CB.run(client, branch, tmp_path, dry_run=True)


def test_manual_recheck_is_10_fixed_ids():
    ids = CB.manual_recheck_ids()
    assert len(ids) == 10 and ids == CB.manual_recheck_ids()


def test_score_manual_final_verdict(tmp_path):
    CB.run(CB.FakeStreamClient(QUESTIONS["simple"]), "simple", tmp_path, dry_run=True)
    path = tmp_path / "manual_review.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with pytest.raises(ValueError):
        CB.score_manual(tmp_path, "simple")
    for i, r in enumerate(rows):
        r.update(dung_y="1", du_y="1", dung_chinh_sach="1", nguoi_cham="Phước")
        if i < 4:
            r["du_y"] = "0"  # 26/30 đạt: dưới ngưỡng 27
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CB.MANUAL_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    final = CB.score_manual(tmp_path, "simple")["final"]
    assert final["passed_questions"] == 26 and not final["passed"]
    assert final["graders"] == ["Phước"]


# ---------- throttle, lỗi đăng nhập, chạy lại câu lỗi API ----------


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "ConverseStream")


class FlakyClient(CB.FakeStreamClient):
    """Model giả trả lời đúng, nhưng ném lỗi cho các câu trong `fail` (theo nội dung câu hỏi)."""

    def __init__(self, questions, fail: dict[str, str]):
        super().__init__(questions)
        self.fail = fail
        self.asked = []

    def converse_stream(self, *, messages, **kw):
        qid = self._by_question[messages[0]["content"][0]["text"]]["id"]
        if len(messages) == 1:
            self.asked.append(qid)
        if qid in self.fail:
            raise _client_error(self.fail[qid])
        return super().converse_stream(messages=messages, **kw)


def test_throttle_waits_before_single_retry(monkeypatch):
    waits = []
    monkeypatch.setattr(CB, "_sleep", waits.append)
    client = ScriptedStream([_throttle(), (["Chào bạn!"], [], "end_turn")])
    res = CB.run_question(client, _q("NOVA-002"), "simple", "SYS")
    assert waits == [C.THROTTLE_RETRY_WAIT_SECONDS] and res["retried"]
    waits.clear()
    client = ScriptedStream([_client_error("AccessDeniedException")] * 2)
    res = CB.run_question(client, _q("NOVA-002"), "simple", "SYS")
    assert waits == [] and res["status"] == "api_error"  # không phải throttle: không chờ


def test_login_error_stops_run_and_keeps_finished_questions(tmp_path, monkeypatch):
    monkeypatch.setattr(CB, "_sleep", lambda s: None)
    qs = QUESTIONS["simple"]
    client = FlakyClient(qs, {"NOVA-003": "ExpiredTokenException"})
    with pytest.raises(CB.FatalApiError):
        CB.run(client, "simple", tmp_path, dry_run=False)
    assert client.asked == ["NOVA-001", "NOVA-002", "NOVA-003"]  # không gọi lại, không chạy tiếp
    kept = CB.load_questions(tmp_path / "raw.jsonl")
    assert [r["id"] for r in kept] == ["NOVA-001", "NOVA-002"]
    assert not (tmp_path / "summary.json").exists()

    resumed = FlakyClient(qs, {})
    summary = CB.run(resumed, "simple", tmp_path, dry_run=False, rerun_api_errors=True)
    assert resumed.asked == [q["id"] for q in qs[2:]]
    assert summary["auto_pass"] == 30 and summary["auto_checks"]["all_questions_run"]


def test_rerun_api_errors_only_reruns_failed_questions(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr(CB, "_sleep", waits.append)
    qs = QUESTIONS["complex"]
    failing = {q["id"]: "ThrottlingException" for q in qs[9:]}
    first = CB.run(FlakyClient(qs, failing), "complex", tmp_path, dry_run=False)
    assert first["auto_pass"] == 9 and len(first["api_errors"]) == 21
    assert not first["auto_stage_passed"]
    assert waits.count(C.THROTTLE_RETRY_WAIT_SECONDS) == 21
    assert waits.count(C.PAUSE_BETWEEN_QUESTIONS_SECONDS["complex"]) == 29

    with pytest.raises(FileExistsError):
        CB.run(FlakyClient(qs, {}), "complex", tmp_path, dry_run=False)
    again = FlakyClient(qs, {})
    summary = CB.run(again, "complex", tmp_path, dry_run=False, rerun_api_errors=True)
    assert again.asked == [q["id"] for q in qs[9:]]
    assert summary["auto_pass"] == 30 and summary["auto_stage_passed"]
    assert summary["started_at"] == first["started_at"]
    assert summary["reruns_api_errors"][0]["ids"] == [q["id"] for q in qs[9:]]
    rec = {r["id"]: r for r in CB.load_questions(tmp_path / "raw.jsonl")}
    assert rec["HAIKU-010"]["rerun_after_api_error"]
    assert [e["code"] for e in rec["HAIKU-010"]["previous_api_errors"]] == [
        "ThrottlingException"
    ] * 2
    assert "rerun_after_api_error" not in rec["HAIKU-001"]


def test_rerun_needs_existing_raw(tmp_path):
    with pytest.raises(FileNotFoundError):
        CB.run(
            FlakyClient(QUESTIONS["simple"], {}),
            "simple",
            tmp_path,
            dry_run=False,
            rerun_api_errors=True,
        )


def test_preliminary_policy_flag_does_not_decide_final(tmp_path):
    """Cờ chính sách tự động (must_include của nhóm ngoài phạm vi) chỉ là sơ bộ; chấm tay quyết định."""
    CB.run(CB.FakeStreamClient(QUESTIONS["simple"]), "simple", tmp_path, dry_run=True)
    summary_path = tmp_path / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["auto_checks"]["no_policy_flags"] = (
        False  # giả lập: Nova từ chối đúng nhưng khác cụm từ
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    path = tmp_path / "manual_review.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r.update(dung_y="1", du_y="1", dung_chinh_sach="1", nguoi_cham="Phước")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CB.MANUAL_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    final = CB.score_manual(tmp_path, "simple")["final"]
    assert "no_policy_flags" not in final["checks"]
    assert final["preliminary_auto_flags"] == {"no_policy_flags": False}
    assert final["passed"]


# ---------- bộ câu hỏi v2 (đề xuất v2, mục 4 và 7) ----------

V2 = {b: CB.load_questions(CB.questions_path("v2", b)) for b in CB.BRANCHES}
FIX_V2 = ROOT / CB.qcfg("v2")["fixtures_dir"]
RESULTS_2310 = ROOT / "docs" / "experiments" / "results" / "chatbot-benchmark-2026-10-23"


@pytest.mark.parametrize("branch", CB.BRANCHES)
def test_v2_schema_allocation_and_no_overlap_with_v1(branch):
    qs = V2[branch]
    errors = {q["id"]: e for q in qs if (e := CB.validate_question(q, branch, "v2"))}
    assert errors == {}
    assert Counter(q["category"] for q in qs) == EXPECTED_CATEGORIES[branch]
    assert all(q["id"].startswith(("NOVA2-", "HAIKU2-")) for q in qs)
    assert not {q["question"] for q in qs} & {q["question"] for q in QUESTIONS[branch]}


def test_v2_ids_unique_and_haiku2_013_has_h4_tails():
    ids = [q["id"] for b in CB.BRANCHES for q in V2[b]]
    assert len(ids) == len(set(ids)) == 60
    q13 = next(q for q in V2["complex"] if q["id"] == "HAIKU2-013")
    assert {"6,55", "7,27", "6.55", "7.27"} <= set(q13["must_not_include"])


def test_validate_rejects_bad_must_include_any():
    q = copy.deepcopy(V2["simple"][0])
    q["must_include_any"] = [["ok"], []]
    assert any("must_include_any" in e for e in CB.validate_question(q, "simple", "v2"))


@pytest.mark.parametrize(
    "path", sorted((FIX_V2 / "forecasts").glob("*.json")), ids=lambda p: p.stem
)
def test_v2_forecast_fixtures_follow_contract(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    if "error" in d:
        assert set(d) == {"error", "message"} and d["error"] == "not_found"
        return
    assert d["base_date"] == "2026-10-21" and d["disclaimer"] == C.DISCLAIMER
    for h in d["horizons"]:
        r = h["returns"]
        assert r == sorted(r)
        assert h["prices"] == [round(d["last_price"] * math.exp(x), 2) for x in r]
        assert h["prob_up"] == round(prob_up(r), 2)


def test_v2_fixture_scenarios():
    def load(name: str) -> dict:
        return json.loads((FIX_V2 / "forecasts" / f"{name}.json").read_text(encoding="utf-8"))

    assert all(load(a)["model_version"] == "baseline-q252" for a in CB.ASSETS)
    assert all(load(a)["is_sample"] is False for a in CB.ASSETS)
    assert load("silver__sample")["is_sample"] is True
    assert load("gold__stale")["stale_sources"] == ["gold"]
    assert load("brent__roll")["roll_in_horizon"] is True


@pytest.mark.parametrize("path", sorted((FIX_V2 / "news").glob("*.json")), ids=lambda p: p.stem)
def test_v2_news_fixtures_have_no_hint_fields(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    assert set(d) == {"asset", "items"}
    assert all(it["link"].startswith("https://example.com/") for it in d["items"])
    assert "fictional" not in path.read_text(encoding="utf-8").lower()


def test_news_default_window_follows_question_set():
    v1 = CB.execute_tool("get_news", {"asset": "brent"}, {"forecast": {}, "news": {}}, "v1")
    v2 = CB.execute_tool("get_news", {"asset": "brent"}, {"forecast": {}, "news": {}}, "v2")
    assert (v1["from_date"], v1["to_date"]) == ("2026-10-07", "2026-10-14")
    assert (v2["from_date"], v2["to_date"]) == ("2026-10-14", "2026-10-21")
    low = CB.execute_tool(
        "get_news", {"asset": "silver"}, {"news": {"silver": "news/silver__low_impact.json"}}, "v2"
    )
    assert low["items"] == []  # chỉ có tin impact 1, min_impact mặc định 2


def test_must_include_any_accepts_paraphrase():
    q = next(q for q in V2["simple"] if q["id"] == "NOVA2-020")
    ok = CB.check_answer(q, _res("Mình không cung cấp giá vàng nhẫn trong nước, chỉ hỗ trợ GLD."))
    assert ok["checks"]["must_include_any"] == []
    bad = CB.check_answer(q, _res("Vàng nhẫn là một sản phẩm phổ biến ở Việt Nam."))
    assert bad["checks"]["must_include_any"] and not bad["auto_pass"]


def test_integer_tokens_need_integer_sources():
    assert not CB.number_matches("1", [0.6, 0.15])  # 0,6% hay 0,15% không còn khớp "1"
    assert CB.number_matches("52", [0.52 * 100])  # prob_up × 100
    assert CB.number_matches("0,15", [0.15])
    assert CB.number_matches("26.285", [26285])


def test_interval_label_regression_on_23_10_results():
    """Trên kết quả thật 23/10, đúng 5 câu gắn sai nhãn khoảng 80% (đã xác nhận khi chấm tay)."""
    rows = CB.load_questions(RESULTS_2310 / "complex" / "raw.jsonl")
    flagged = {r["id"] for r in rows if CB.interval_label_errors(r["answer"], r["tool_calls"])}
    assert flagged == {"HAIKU-004", "HAIKU-007", "HAIKU-016", "HAIKU-019", "HAIKU-025"}


def test_interval_label_check_fails_answer_and_accepts_q10_q90():
    q = next(q for q in V2["complex"] if q["id"] == "HAIKU2-003")
    call = {"name": "get_forecast", "input": {"asset": "silver"}, "ok": True,
            "result": json.loads((FIX_V2 / "forecasts" / "silver.json").read_text(encoding="utf-8"))}  # fmt: skip
    good = f"Bạc (SLV), kỳ hạn 7 phiên: khoảng dự báo 80% từ -5,74% đến +7,48%, xác suất tăng 56%. {C.DISCLAIMER}"
    out = CB.check_answer(q, _res(good, [call]))
    assert out["checks"]["interval_label"] == [] and out["auto_pass"], out["failures"]
    bad = good.replace("-5,74%", "-7,59%")
    out = CB.check_answer(q, _res(bad, [call]))
    assert out["checks"]["interval_label"] == ["7,59"] and "interval_label" in out["failures"]


@pytest.mark.parametrize("branch", CB.BRANCHES)
def test_v2_dry_run_all_auto_pass(tmp_path, branch):
    summary = CB.run(CB.FakeStreamClient(V2[branch]), branch, tmp_path, dry_run=True, qset="v2")
    assert summary["auto_pass"] == 30 and summary["auto_stage_passed"], summary["auto_failures"]
    assert summary["question_set"] == "v2" and summary["run_type"] == "official"
    assert summary["auto_checks"]["no_interval_mislabel"]
    assert set(summary["manual_recheck_ids"]) <= {q["id"] for q in V2[branch]}


def test_dev_run_is_marked(tmp_path):
    summary = CB.run(
        CB.FakeStreamClient(QUESTIONS["simple"]), "simple", tmp_path, dry_run=True, run_type="dev"
    )
    assert summary["run_type"] == "dev" and summary["final_note"].startswith("LẦN CHẠY PHÁT TRIỂN")


def test_official_v2_requires_matching_lock(tmp_path, monkeypatch):
    client = CB.FakeStreamClient(V2["simple"])
    with pytest.raises(RuntimeError, match="chưa khóa"):
        CB.run(client, "simple", tmp_path / "a", dry_run=False, qset="v2")
    sets = copy.deepcopy(C.QUESTION_SETS)
    sets["v2"]["locked_sha256"] = {**CB.lock_hashes("v2"), "fixtures": "0" * 64}
    monkeypatch.setattr(C, "QUESTION_SETS", sets)
    with pytest.raises(RuntimeError, match="fixtures"):
        CB.run(client, "simple", tmp_path / "b", dry_run=False, qset="v2")
    sets["v2"]["locked_sha256"] = CB.lock_hashes("v2")
    summary = CB.run(client, "simple", tmp_path / "c", dry_run=False, qset="v2")
    assert summary["auto_pass"] == 30


def test_lock_covers_tool_code():
    keys = set(CB.lock_hashes("v2"))
    assert keys == {
        "questions_simple",
        "questions_complex",
        "prompt_simple",
        "prompt_complex",
        "fixtures",
        "tool_code",
        "scoring_config",
    }


def test_print_lock_cli(capsys):
    assert CB.main(["--print-lock", "--set", "v2"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == set(CB.lock_hashes("v2"))


def test_instruction_compliance_is_recorded_not_counted(tmp_path):
    CB.run(CB.FakeStreamClient(V2["simple"]), "simple", tmp_path, dry_run=True, qset="v2")
    path = tmp_path / "manual_review.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert "tuan_thu_chi_dan" in rows[0]
    for r in rows:
        r.update(
            dung_y="1", du_y="1", dung_chinh_sach="1", tuan_thu_chi_dan="0", nguoi_cham="Phước"
        )
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CB.MANUAL_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    final = CB.score_manual(tmp_path, "simple")["final"]
    assert final["passed"] and final["passed_questions"] == 30
    assert len(final["instruction_compliance"]["zero_ids"]) == 30


def test_score_manual_reads_v1_csv_without_instruction_column():
    """File chấm tay 23/10 (không có cột tuan_thu_chi_dan) vẫn đọc được."""
    with (RESULTS_2310 / "simple" / "manual_review.csv").open(encoding="utf-8-sig") as f:
        assert "tuan_thu_chi_dan" not in next(csv.reader(f))


def test_cli_official_v2_without_lock_stops_before_bedrock(capsys, monkeypatch):
    monkeypatch.setattr(CB, "bedrock_client", lambda *a: pytest.fail("không được tạo client"))
    assert CB.main(["--branch", "simple", "--set", "v2"]) == 2
    assert "chưa khóa" in capsys.readouterr().err


def test_real_dev_run_on_holdout_v2_is_blocked(tmp_path, capsys, monkeypatch):
    """Khải review PR #35: --set v2 --run-type dev (không --dry-run) không được gọi Bedrock."""
    with pytest.raises(RuntimeError, match="giữ riêng"):
        CB.run(CB.FakeStreamClient(V2["simple"]), "simple", tmp_path / "a", dry_run=False,
               qset="v2", run_type="dev")  # fmt: skip
    monkeypatch.setattr(CB, "bedrock_client", lambda *a: pytest.fail("không được tạo client"))
    assert CB.main(["--branch", "complex", "--set", "v2", "--run-type", "dev"]) == 2
    assert "giữ riêng" in capsys.readouterr().err
    # dev thật trên v1 và dry-run trên v2 vẫn được phép
    assert CB.run(CB.FakeStreamClient(QUESTIONS["simple"]), "simple", tmp_path / "b",
                  dry_run=False, run_type="dev")["run_type"] == "dev"  # fmt: skip
    assert CB.run(CB.FakeStreamClient(V2["simple"]), "simple", tmp_path / "c", dry_run=True,
                  qset="v2", run_type="dev")["auto_pass"] == 30  # fmt: skip


def test_lock_detects_scoring_config_change(monkeypatch):
    before = CB.lock_hashes("v2")
    monkeypatch.setattr(
        C, "THRESHOLDS", {**C.THRESHOLDS, "simple": {"min_pass": 20, "max_truncated": 1}}
    )
    after = CB.lock_hashes("v2")
    assert before["scoring_config"] != after["scoring_config"]
    assert {k for k in before if before[k] != after[k]} == {"scoring_config"}


# ---------- tool get_forecast v2 trong benchmark (Khải 26/10: dùng chung định dạng Lambda API) ----------


def _raw(path):
    return {r["id"]: r for r in CB.load_questions(path / "raw.jsonl")}


def test_v2_set_runs_prompt_v2_through_real_tool(tmp_path):
    summary = CB.run(
        CB.FakeStreamClient(V2["complex"]), "complex", tmp_path, dry_run=True, qset="v2"
    )
    assert (summary["prompt_set"], summary["tool_format"]) == ("v2", "v2")
    assert summary["prompt_version"] == "chatbot-haiku-v2"
    gold = next(
        c for c in _raw(tmp_path)["HAIKU2-001"]["tool_calls"] if c["name"] == "get_forecast"
    )
    h1 = gold["result"]["horizons"][0]
    assert {"q10_pct", "q50_pct", "q90_pct", "prob_up_pct"} <= set(h1)
    assert "returns" not in h1 and "last_price" not in gold["result"]  # vàng: không có giá
    assert gold["result"]["fx"] == {"usd_vnd": 26285, "date": "2026-10-21"}
    assert len(gold["source"]["horizons"][0]["returns"]) == 7  # bản contract đứng sau, để soát nhãn


def test_dev_run_v1_with_prompts_v2(tmp_path):
    summary = CB.run(
        CB.FakeStreamClient(QUESTIONS["complex"]),
        "complex",
        tmp_path,
        dry_run=True,
        run_type="dev",
        prompt_set="v2",
    )
    assert (summary["question_set"], summary["prompt_set"], summary["tool_format"]) == (
        "v1",
        "v2",
        "v2",
    )
    assert summary["auto_pass"] == 30, summary["auto_failures"]
    nf = _raw(tmp_path)["HAIKU-022"]["tool_calls"][0]  # silver__not_found qua tool v2
    assert nf["result"]["error"] == "not_found" and not nf["ok"]


def test_official_run_cannot_override_prompts(tmp_path):
    with pytest.raises(RuntimeError, match="--prompts"):
        CB.run(CB.FakeStreamClient(QUESTIONS["simple"]), "simple", tmp_path, dry_run=False,
               prompt_set="v2")  # fmt: skip


def test_tool_config_v2_uses_tool_module_spec():
    assert CB.tool_config("v2")["tools"][0] is CB.T.GET_FORECAST_TOOL_SPEC
    assert CB.tool_config()["tools"][0]["toolSpec"]["name"] == "get_forecast"


def test_interval_label_checked_against_source_for_v2_tool():
    contract = json.loads((FIX_V2 / "forecasts" / "silver.json").read_text(encoding="utf-8"))
    result = CB.T.build_forecast_result(contract)
    call = {"name": "get_forecast", "input": {"asset": "silver"}, "ok": True, "result": result,
            "source": contract}  # fmt: skip
    bad = "Bạc 7 phiên: khoảng dự báo 80% từ -7,59% đến +7,48%."
    assert CB.interval_label_errors(bad, [call]) == ["7,59"]
    assert CB.interval_label_errors(bad, [{**call, "source": None}]) == []  # không có source


def test_lock_includes_tool_and_shared_formatter():
    assert {"src/chatbot/tools.py", "infra/lambda/forecast_api/forecast_format.py"} <= set(
        C.TOOL_CODE_PATHS
    )
    assert all((ROOT / p).is_file() for p in C.TOOL_CODE_PATHS)


def test_interval_label_accepts_median_that_equals_other_asset_tail():
    """Dev 26/10 (HAIKU-014): q50 Brent h1 = 74,76 trùng q95 WTI h2; không được coi là sai nhãn."""
    calls = [
        {"name": "get_forecast", "input": {"asset": a}, "ok": True, "result": _forecast(a)}
        for a in ("brent", "wti")
    ]
    line = "Brent: khoảng 80% từ 72.96 đến 76.61 USD/bbl, trung vị 74.76 USD/bbl."
    assert CB.interval_label_errors(line, calls) == []
    wrong = "WTI: khoảng 80% từ 69.03 đến 73.19 USD/bbl."  # 69,03 là q05 WTI h1
    assert CB.interval_label_errors(wrong, calls) == ["69.03"]


def test_rescore_dev_results_and_refuse_official(tmp_path):
    dev = tmp_path / "dev"
    CB.run(CB.FakeStreamClient(QUESTIONS["complex"]), "complex", dev, dry_run=False, run_type="dev")
    raw = CB.load_questions(dev / "raw.jsonl")
    raw[0]["answer"] = raw[0]["answer"].replace("q10 đến q90", "q10 đến q90 (khoảng dự báo)") + (
        " Khoảng dự báo 80% từ -1,50% đến +1,28%."  # -1,50 là q05 vàng h1
    )
    (dev / "raw.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw), encoding="utf-8"
    )
    summary = CB.rescore(dev, "complex")
    assert raw[0]["id"] in summary["interval_mislabel_questions"]
    assert summary["final"] is None and len(summary["rescores"]) == 1

    official = tmp_path / "official"
    CB.run(CB.FakeStreamClient(QUESTIONS["simple"]), "simple", official, dry_run=False)
    with pytest.raises(RuntimeError, match="không chấm lại official"):
        CB.rescore(official, "simple")


def test_rescore_keeps_graded_manual_csv(tmp_path):
    CB.run(
        CB.FakeStreamClient(QUESTIONS["simple"]), "simple", tmp_path, dry_run=True, run_type="dev"
    )
    path = tmp_path / "manual_review.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rows[0]["nguoi_cham"] = "Phước"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CB.MANUAL_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    CB.rescore(tmp_path, "simple")
    with path.open(encoding="utf-8-sig", newline="") as f:
        assert next(csv.DictReader(f))["nguoi_cham"] == "Phước"

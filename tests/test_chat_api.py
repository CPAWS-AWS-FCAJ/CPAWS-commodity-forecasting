"""Khung Lambda `POST /chat` (src/chatbot/chat.py, news.py, infra/lambda/chat_api/handler.py).

Không gọi mạng: client Bedrock giả trả lần lượt các response Converse đã soạn; dữ liệu dự báo
lấy từ fixture benchmark bộ v1.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

from src.chatbot import chat as C
from src.chatbot import news as N
from src.chatbot import tools as T

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "chatbot" / "fixtures"
_spec = importlib.util.spec_from_file_location(
    "chat_handler", ROOT / "infra" / "lambda" / "chat_api" / "handler.py"
)
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

NEWS = [
    {
        "title": "Producer group signals it may raise output",
        "summary": "Tóm tắt.",
        "link": "https://example.com/news/output",
        "source": "Example Energy Brief",
        "published_at": "2026-10-13T10:45:00Z",
        "impact_score": 3,
        "direction": "down",
    },
    {
        "title": "Minor note",
        "summary": "Tác động thấp.",
        "link": "https://example.com/news/minor",
        "source": "Example",
        "published_at": "2026-10-12T08:00:00Z",
        "impact_score": 1,
        "direction": "neutral",
    },
    {
        "title": "No link item",
        "summary": "Thiếu link.",
        "link": "",
        "source": "Example",
        "published_at": "2026-10-13T09:00:00Z",
        "impact_score": 3,
        "direction": "up",
    },
]


class FakeClient:
    """Trả lần lượt các response Converse; ghi lại kwargs mỗi lần gọi."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": "Bedrock is unable to process"}}


def _text(text, stop="end_turn"):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": stop,
        "usage": {"inputTokens": 100, "outputTokens": 20},
    }


def _tool_use(*uses, text=None):
    content = [{"text": text}] if text else []
    content += [
        {"toolUse": {"toolUseId": f"t{i}", "name": n, "input": inp}}
        for i, (n, inp) in enumerate(uses)
    ]
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": "tool_use",
        "usage": {"inputTokens": 50, "outputTokens": 10},
    }


def deps(responses, **kw):
    files = {a: FIX / "forecasts" / f"{a}.json" for a in T.ASSETS}
    clock = kw.pop("clock", None)
    news = kw.pop("news", None) or N.StaticNewsRepository({"wti": NEWS})
    d = C.ChatDeps(
        client=FakeClient(responses),
        forecasts=T.JsonFileForecastRepository(files),
        news=news,
        prompts={"simple": "PROMPT SIMPLE", "complex": "PROMPT COMPLEX"},
        **kw,
    )
    if clock:
        d.clock = clock
    return d


def event(body, sub="user-1", method="POST"):
    return {
        "httpMethod": method,
        "body": body if isinstance(body, str) else json.dumps(body, ensure_ascii=False),
        "requestContext": {"requestId": "req-1", "authorizer": {"claims": {"sub": sub}}},
    }


# ---------- kiểm tra request ----------


def test_parse_request_ok_and_normalises():
    req = C.parse_request(
        {
            "question": "  Dầu WTI phiên tới?  ",
            "context": {"asset": "wti", "page": "product"},
            "history": [
                {"role": "user", "text": "Chào"},
                {"role": "assistant", "text": "Chào bạn"},
            ],
        }
    )
    assert req.question == "Dầu WTI phiên tới?" and req.asset == "wti"
    assert req.history == (("user", "Chào"), ("assistant", "Chào bạn"))


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ([], "invalid_body"),
        ({}, "invalid_body"),
        ({"question": 5}, "invalid_body"),
        ({"question": "   "}, "empty_question"),
        ({"question": "a" * 501}, "question_too_long"),
        ({"question": "hi", "context": {"asset": "btc"}}, "invalid_context"),
        ({"question": "hi", "context": {"page": "admin"}}, "invalid_context"),
        ({"question": "hi", "history": [{"role": "assistant", "text": "x"}]}, "invalid_history"),
        ({"question": "hi", "history": [{"role": "user", "text": "x"}]}, "invalid_history"),
        ({"question": "hi", "history": [{"role": "user", "text": "x"}] * 7}, "invalid_history"),
        (
            {
                "question": "hi",
                "history": [{"role": "user", "text": ""}, {"role": "assistant", "text": "y"}],
            },
            "invalid_history",
        ),
    ],
)
def test_parse_request_errors(body, code):
    with pytest.raises(C.ChatError) as exc:
        C.parse_request(body)
    assert exc.value.status == 400 and exc.value.code == code


def test_question_length_counts_unicode_characters_not_bytes():
    assert C.parse_request({"question": "ạ" * 500}).question == "ạ" * 500
    # dạng tổ hợp (a + dấu) chuẩn hóa NFC thành 1 ký tự
    assert len(C.parse_request({"question": "ạ" * 500}).question) == 500


# ---------- vòng gọi tool ----------


def test_complex_answer_with_tools_builds_forecasts_used_and_citations():
    answer_text = (
        "WTI h = 1: khoảng dự báo 80% từ 69,54 đến 73,19 USD/bbl. "
        "(Nguồn: Example Energy Brief, 13/10/2026, https://example.com/news/output) "
        "Link lạ https://evil.example/x. Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
    )
    d = deps(
        [
            _tool_use(
                ("get_forecast", {"asset": "wti", "horizon": 1}),
                ("get_news", {"asset": "wti", "to_date": "2026-10-14"}),
            ),
            _text(answer_text),
        ]
    )
    req = C.parse_request({"question": "WTI phiên tới thế nào, vì sao?"})
    res = C.answer(req, d)
    assert res.branch == "complex" and res.answer == answer_text
    assert res.forecasts_used == [
        {"asset": "wti", "base_date": "2026-10-14", "model_version": "sample", "is_sample": True,
         "stale": False}
    ]  # fmt: skip
    # chỉ tin get_news trả về và có link trong câu trả lời; link lạ do model viết bị bỏ
    assert [c["link"] for c in res.citations] == ["https://example.com/news/output"]
    assert res.tool_calls == ["get_forecast", "get_news"]
    assert res.input_tokens == 150 and not res.truncated
    first, second = d.client.calls
    assert first["modelId"] == C.MODEL_IDS["complex"]
    assert first["system"] == [{"text": "PROMPT COMPLEX"}]
    assert [t["toolSpec"]["name"] for t in first["toolConfig"]["tools"]] == [
        "get_forecast",
        "get_news",
    ]
    results = second["messages"][-1]["content"]
    assert all(r["toolResult"]["status"] == "success" for r in results)
    forecast_json = results[0]["toolResult"]["content"][0]["json"]
    assert "width_80_pct" in forecast_json["horizons"][0]  # tool v2


def test_history_and_context_become_messages():
    d = deps([_text("Trả lời.")])
    req = C.parse_request(
        {
            "question": "Nó có tăng không?",
            "context": {"asset": "gold"},
            "history": [{"role": "user", "text": "Q"}, {"role": "assistant", "text": "A"}],
        }
    )
    C.answer(req, d)
    msgs = d.client.calls[0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1]["content"][0] == {"text": "Nó có tăng không?"}
    assert "gold" in msgs[-1]["content"][1]["text"]


def test_answer_text_excludes_history():
    d = deps([_text("Mới.")])
    req = C.parse_request(
        {
            "question": "x",
            "history": [{"role": "user", "text": "Q"}, {"role": "assistant", "text": "Cũ"}],
        }
    )
    assert C.answer(req, d).answer == "Mới."


def test_tool_errors_are_returned_to_model_not_raised():
    d = deps([_tool_use(("get_forecast", {"asset": "btc"}), ("nope", {})), _text("Không có.")])
    res = C.answer(C.parse_request({"question": "btc?"}), d)
    results = d.client.calls[1]["messages"][-1]["content"]
    assert [r["toolResult"]["status"] for r in results] == ["error", "error"]
    assert res.forecasts_used == [] and res.answer == "Không có."


def test_tool_round_limit_stops_loop():
    loop = [_tool_use(("get_forecast", {"asset": "gold"}), text="Đang tra.")] * 5
    d = deps(loop)
    res = C.answer(C.parse_request({"question": "vàng?"}), d)
    assert len(d.client.calls) == C.MAX_TOOL_ROUNDS + 1
    assert res.stop_reason == "tool_round_limit"


def test_truncated_and_guardrail_blocked():
    res = C.answer(C.parse_request({"question": "x"}), deps([_text("dài...", "max_tokens")]))
    assert res.truncated
    d = deps(
        [_text("bị chặn", "guardrail_intervened")],
        guardrail={"guardrailIdentifier": "gr", "guardrailVersion": "1"},
    )
    res = C.answer(C.parse_request({"question": "x"}), d)
    assert res.blocked and res.answer == C.BLOCKED_ANSWER and res.citations == []
    assert d.client.calls[0]["guardrailConfig"] == {
        "guardrailIdentifier": "gr",
        "guardrailVersion": "1",
    }


def test_model_unavailable_maps_to_503_and_other_errors_propagate():
    d = deps([FakeClientError("ServiceUnavailableException")])
    with pytest.raises(C.ChatError) as exc:
        C.answer(C.parse_request({"question": "x"}), d)
    assert exc.value.status == 503 and exc.value.code == "model_unavailable"
    d = deps([FakeClientError("AccessDeniedException")])
    with pytest.raises(FakeClientError):
        C.answer(C.parse_request({"question": "x"}), d)


def test_deadline_returns_504():
    times = iter([0.0, 0.0, 30.0])
    d = deps(
        [_tool_use(("get_forecast", {"asset": "gold"})), _text("x")], clock=lambda: next(times)
    )
    with pytest.raises(C.ChatError) as exc:
        C.answer(C.parse_request({"question": "x"}), d)
    assert exc.value.status == 504 and exc.value.code == "timeout"


# ---------- get_news ----------


def test_get_news_defaults_filter_and_validation():
    repo = N.StaticNewsRepository({"wti": NEWS})
    out = N.get_news({"asset": "wti"}, repo, today=dt.date(2026, 10, 14))
    assert out["from_date"] == "2026-10-07" and out["min_impact"] == 2
    # bỏ tin tác động thấp và tin thiếu link; chỉ giữ các trường cho phép
    assert [it["title"] for it in out["items"]] == ["Producer group signals it may raise output"]
    assert set(out["items"][0]) == set(N.ITEM_FIELDS)
    out = N.get_news({"asset": "wti", "min_impact": 0}, repo, today=dt.date(2026, 10, 14))
    assert len(out["items"]) == 2
    assert N.get_news({"asset": "btc"}, repo)["error"] == "invalid_asset"
    bad = N.get_news({"asset": "wti", "from_date": "2026-10-15", "to_date": "2026-10-01"}, repo)
    assert bad["error"] == "invalid_date"


class FailingNewsRepository:
    """Nguồn tin lỗi, như bảng NewsLabels sai tên hoặc thiếu quyền."""

    def items(self, asset, from_date, to_date):
        raise RuntimeError("AccessDeniedException")


def test_get_news_keeps_only_http_and_https_links():
    base = {k: NEWS[0][k] for k in N.ITEM_FIELDS}
    links = [
        "https://example.com/a",
        "http://example.com/b",
        "httpfoo://example.com/c",
        "javascript:alert(1)",
        "ftp://example.com/d",
        "example.com/e",
    ]
    repo = N.StaticNewsRepository({"wti": [{**base, "link": link} for link in links]})
    out = N.get_news({"asset": "wti"}, repo, today=dt.date(2026, 10, 14))
    assert sorted(it["link"] for it in out["items"]) == sorted(links[:2])


def test_get_news_source_error_returns_news_unavailable():
    out = N.get_news({"asset": "wti"}, FailingNewsRepository(), today=dt.date(2026, 10, 14))
    assert out["error"] == "news_unavailable" and out["message"]


def test_answer_keeps_forecast_when_news_source_fails():
    d = deps(
        [
            _tool_use(("get_forecast", {"asset": "wti"}), ("get_news", {"asset": "wti"})),
            _text("WTI h = 1: ... Chưa lấy được tin. Dự báo mang tính tham khảo."),
        ],
        news=FailingNewsRepository(),
    )
    res = C.answer(C.parse_request({"question": "WTI phiên tới thế nào, vì sao?"}), d)
    assert [f["asset"] for f in res.forecasts_used] == ["wti"]
    assert res.citations == []
    assert res.tool_errors == ["get_news:news_unavailable"]
    results = d.client.calls[1]["messages"][-1]["content"]
    assert [r["toolResult"]["status"] for r in results] == ["success", "error"]


def test_handler_200_and_logs_tool_error_when_news_source_fails(caplog):
    d = deps(
        [
            _tool_use(("get_news", {"asset": "wti"})),
            _text("Chưa lấy được tin. Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."),
        ],
        news=FailingNewsRepository(),
    )
    with caplog.at_level("INFO"):
        resp = H.handle(event({"question": "Vì sao dầu WTI giảm?"}), d)
    assert resp["statusCode"] == 200
    summary = [
        json.loads(r.getMessage()) for r in caplog.records if '"request_id"' in r.getMessage()
    ]
    assert summary[-1]["request_id"] == "req-1"
    assert summary[-1]["tool_errors"] == ["get_news:news_unavailable"]


# ---------- handler ----------


def test_handler_200_response_shape_and_cors():
    d = deps([_text("Xin chào! Dự báo mang tính tham khảo, không phải lời khuyên đầu tư.")])
    resp = H.handle(event({"question": "Chào"}), d)
    assert resp["statusCode"] == 200
    assert resp["headers"]["Access-Control-Allow-Methods"] == "POST,OPTIONS"
    body = json.loads(resp["body"])
    assert set(body) == {
        "request_id", "answer", "branch", "prompt_version", "forecasts_used", "citations",
        "truncated", "blocked", "quota", "disclaimer",
    }  # fmt: skip
    assert body["request_id"] == "req-1" and body["prompt_version"] == "chatbot-haiku-v2"
    assert body["disclaimer"] == T.DISCLAIMER and body["quota"] is None


@pytest.mark.parametrize(
    ("ev", "status", "code"),
    [
        (event("{not json"), 400, "invalid_body"),
        (event({"question": "x" * 70000}), 400, "invalid_body"),
        (event({"question": ""}), 400, "empty_question"),
        (event({"question": "x"}, method="GET"), 405, "method_not_allowed"),
        (event({"question": "x"}, sub=None), 401, "unauthorized"),
    ],
)
def test_handler_client_errors(ev, status, code):
    resp = H.handle(ev, deps([]))
    assert resp["statusCode"] == status
    assert json.loads(resp["body"])["error"] == code


def test_handler_hides_internal_errors(caplog):
    d = deps([FakeClientError("AccessDeniedException")])
    resp = H.handle(event({"question": "x"}), d)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 500 and body["error"] == "internal_error"
    assert "AccessDenied" not in resp["body"] and "arn:" not in resp["body"]


def test_handler_503_when_model_unavailable_and_log_has_no_question(caplog):
    caplog.set_level("INFO")
    d = deps([FakeClientError("ServiceUnavailableException")])
    resp = H.handle(event({"question": "câu hỏi bí mật"}), d)
    assert resp["statusCode"] == 503
    assert "câu hỏi bí mật" not in caplog.text


def test_handler_quota_429_sets_retry_after():
    class Full:
        def consume(self, sub):
            raise C.ChatError(
                429, "rate_limited", "Hết lượt.", reset_at="2026-10-27T17:00:00Z", retry_after=3600
            )

    resp = H.handle(event({"question": "x"}), deps([], quota=Full()))
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 429 and resp["headers"]["Retry-After"] == "3600"
    assert body == {
        "error": "rate_limited",
        "message": "Hết lượt.",
        "reset_at": "2026-10-27T17:00:00Z",
    }


def test_repo_prompts_load_for_both_branches():
    for name in H.PROMPT_FILES.values():
        assert C.load_system_prompt(ROOT / "docs" / "prompts" / name).strip()


# ---------- nguồn tin ----------


def test_json_file_news_repository_reads_fixture_dir():
    repo = N.JsonFileNewsRepository(FIX / "news")
    out = N.get_news({"asset": "wti", "to_date": "2026-10-14"}, repo)
    assert out["items"] and all(it["link"].startswith("https://") for it in out["items"])
    assert (
        N.JsonFileNewsRepository(FIX / "news").items(
            "nope", dt.date(2026, 1, 1), dt.date(2026, 12, 31)
        )
        == []
    )


class FakeNewsTable:
    """Bảng giả: lọc theo asset và SK BETWEEN, trả từng trang 1 item để thử phân trang."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def query(self, **kw):
        self.calls.append(kw)
        v = kw["ExpressionAttributeValues"]
        sk = kw["ExpressionAttributeNames"]["#sk"]
        hits = sorted(
            (r for r in self.rows if r["asset"] == v[":asset"] and v[":lo"] <= r[sk] <= v[":hi"]),
            key=lambda r: r[sk],
            reverse=True,
        )
        start = kw.get("ExclusiveStartKey", {}).get("i", 0)
        page = {"Items": hits[start : start + 1]}
        if start + 1 < len(hits):
            page["LastEvaluatedKey"] = {"i": start + 1}
        return page


def test_dynamo_news_repository_queries_by_asset_and_day_range():
    from decimal import Decimal

    def row(asset, ts, aid, impact):
        return {
            "asset": asset, "sk": f"{ts}#{aid}", "published_at": ts, "title": aid,
            "summary": "s", "link": f"https://www.eia.gov/{aid}", "source": "EIA",
            "impact_score": Decimal(impact), "direction": "bullish",
        }  # fmt: skip

    table = FakeNewsTable(
        [
            row("wti", "2026-10-06T23:00:00Z", "too-old", 3),
            row("wti", "2026-10-07T00:30:00Z", "first-day", 2),
            row("wti", "2026-10-14T23:59:00Z", "last-day", 3),
            row("wti", "2026-10-15T00:01:00Z", "too-new", 3),
            row("gold", "2026-10-10T12:00:00Z", "other-asset", 3),
        ]
    )
    repo = N.DynamoNewsRepository(table)
    out = N.get_news({"asset": "wti"}, repo, today=dt.date(2026, 10, 14))
    assert [it["title"] for it in out["items"]] == ["last-day", "first-day"]
    assert isinstance(out["items"][0]["impact_score"], int)  # Decimal → int, JSON-safe
    json.dumps(out)
    assert len(table.calls) == 2  # mỗi trang 1 item: đọc tiếp theo LastEvaluatedKey đến hết
    assert table.calls[0]["ScanIndexForward"] is False


def test_handler_picks_news_source_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("NEWS_TABLE_NAME", raising=False)
    monkeypatch.delenv("NEWS_DIR", raising=False)
    assert isinstance(H.news_repository(), N.StaticNewsRepository)
    monkeypatch.setenv("NEWS_DIR", str(tmp_path))
    assert isinstance(H.news_repository(), N.JsonFileNewsRepository)

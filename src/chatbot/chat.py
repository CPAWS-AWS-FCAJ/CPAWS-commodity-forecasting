"""Lõi xử lý `POST /chat` (hợp đồng: `docs/api/contract.md`, mục `POST /chat`, PR #41).

Khung theo phương án A của hợp đồng (REST API, trả một lần): kiểm tra request, chọn nhánh, gọi
Bedrock Converse với vòng gọi tool tối đa MAX_TOOL_ROUNDS, dựng response.
- Hạn chót: Lambda truyền `budget_s` (giây còn lại, tính từ `requestTimeEpoch` của API Gateway);
  chỉ bắt đầu một lần gọi model khi còn đủ MIN_CALL_S để lần gọi đó xong trước hạn.
- Giới hạn lượt hỏi: `QuotaGate`; Lambda dùng `quota.DynamoQuotaGate`, test dùng `NoQuota`.
Phần còn chờ chốt trong PR #41:
- router (mục 9): `choose_branch`, mặc định mọi câu đi `complex`;
- Guardrails: chỉ gắn `guardrailConfig` khi có cấu hình.

Module không import boto3: Lambda truyền client vào, test truyền client giả.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import news as N
from . import tools as T

log = logging.getLogger("cpaws.chatbot.chat")

BRANCHES = ("simple", "complex")
PAGES = ("home", "product")
MAX_QUESTION_CHARS = 500
MAX_HISTORY_ITEMS = 6
MAX_HISTORY_TEXT_CHARS = 2000
MAX_BODY_BYTES = 64 * 1024
MAX_TOOL_ROUNDS = 3
DEFAULT_BUDGET_S = 25.0  # khi không có requestTimeEpoch (test, gọi trực tiếp)
# Mỗi lần gọi Bedrock kéo dài tối đa connect + read (client không tự thử lại); chỉ gọi khi còn đủ
# MIN_CALL_S trước hạn chót, để Lambda tự trả 504 đúng dạng trước khi API Gateway cắt ở 29 giây.
BEDROCK_CONNECT_TIMEOUT_S = 2.0
BEDROCK_READ_TIMEOUT_S = 15.0
MIN_CALL_S = BEDROCK_CONNECT_TIMEOUT_S + BEDROCK_READ_TIMEOUT_S
RETRY_DELAY_S = 0.5
TEMPERATURE = 0
MAX_TOKENS = {"simple": 512, "complex": 1500}
MODEL_IDS = {
    "simple": "global.amazon.nova-2-lite-v1:0",
    "complex": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
}
PROMPT_VERSIONS = {"simple": "chatbot-nova-v2", "complex": "chatbot-haiku-v2"}
DISCLAIMER = T.DISCLAIMER
BLOCKED_ANSWER = (
    "Mình không thể trả lời yêu cầu này. Bạn có thể hỏi về dự báo vàng, bạc, dầu Brent và WTI."
)
# Lỗi Bedrock coi là "model không sẵn sàng" (503); lỗi khác là 500
UNAVAILABLE_CODES = frozenset(
    {
        "ServiceUnavailableException",
        "ThrottlingException",
        "ModelNotReadyException",
        "ModelTimeoutException",
        "InternalServerException",
    }
)
# Lỗi tạm thời đáng thử lại một lần (nếu còn thời gian); ModelTimeout thì không, vì chậm sẵn rồi
RETRY_CODES = UNAVAILABLE_CODES - {"ModelTimeoutException"}
# Tên lớp lỗi hết thời gian của botocore (không import botocore trong module này)
TIMEOUT_ERRORS = frozenset({"ReadTimeoutError", "ConnectTimeoutError", "ConnectTimeout"})


class ChatError(Exception):
    """Lỗi trả cho client theo dạng chung {"error", "message"} của hợp đồng."""

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    def body(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.extra}


# ---------- request ----------


@dataclass(frozen=True)
class ChatRequest:
    question: str
    asset: str | None = None
    page: str | None = None
    history: tuple[tuple[str, str], ...] = ()


def _nfc_len(text: str) -> int:
    return len(unicodedata.normalize("NFC", text))


def parse_request(body: Any) -> ChatRequest:
    """Kiểm tra thân request đã parse JSON theo hợp đồng; sai thì báo ChatError 400."""
    if not isinstance(body, Mapping):
        raise ChatError(400, "invalid_body", "Thân request phải là một đối tượng JSON.")
    question = body.get("question")
    if not isinstance(question, str):
        raise ChatError(400, "invalid_body", "Thiếu trường question hoặc sai kiểu.")
    question = unicodedata.normalize("NFC", question.strip())
    if not question:
        raise ChatError(400, "empty_question", "Câu hỏi đang để trống.")
    if len(question) > MAX_QUESTION_CHARS:
        raise ChatError(400, "question_too_long", f"Câu hỏi dài quá {MAX_QUESTION_CHARS} ký tự.")

    context = body.get("context") or {}
    if not isinstance(context, Mapping):
        raise ChatError(400, "invalid_context", "context phải là một đối tượng.")
    asset, page = context.get("asset"), context.get("page")
    if asset is not None and asset not in T.ASSETS:
        raise ChatError(400, "invalid_context", f"context.asset phải là: {', '.join(T.ASSETS)}.")
    if page is not None and page not in PAGES:
        raise ChatError(400, "invalid_context", f"context.page phải là: {', '.join(PAGES)}.")

    history = body.get("history") or []
    if not isinstance(history, list) or len(history) > MAX_HISTORY_ITEMS:
        raise ChatError(
            400, "invalid_history", f"history là danh sách tối đa {MAX_HISTORY_ITEMS} phần tử."
        )
    turns = []
    for i, item in enumerate(history):
        role = item.get("role") if isinstance(item, Mapping) else None
        text = item.get("text") if isinstance(item, Mapping) else None
        expected = "user" if i % 2 == 0 else "assistant"
        if role != expected:
            raise ChatError(
                400, "invalid_history", "history phải xen kẽ user/assistant, bắt đầu bằng user."
            )
        if not isinstance(text, str) or not text.strip() or _nfc_len(text) > MAX_HISTORY_TEXT_CHARS:
            raise ChatError(
                400,
                "invalid_history",
                f"Mỗi text trong history dài 1–{MAX_HISTORY_TEXT_CHARS} ký tự.",
            )
        turns.append((role, unicodedata.normalize("NFC", text)))
    if turns and turns[-1][0] != "assistant":
        raise ChatError(400, "invalid_history", "history phải kết thúc bằng assistant.")
    return ChatRequest(question, asset, page, tuple(turns))


# ---------- prompt, router, quota ----------


def load_system_prompt(path: str | Path) -> str:
    """Lấy đúng một khối ```text ở mục "System prompt" của file prompt (như script benchmark)."""
    text = Path(path).read_text(encoding="utf-8")
    blocks = re.findall(r"^```text\n(.*?)\n^```$", text, re.DOTALL | re.MULTILINE)
    if len(blocks) != 1:
        raise ValueError(f"{path}: cần đúng 1 khối ```text, thấy {len(blocks)}")
    return blocks[0]


def choose_branch(req: ChatRequest) -> str:
    """Chưa có router (PR #41 mục 9): mọi câu đi complex, đúng quy tắc "không chắc thì complex"."""
    return "complex"


@dataclass
class Quota:
    limit: int
    used: int
    reset_at: str

    def body(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "used": self.used,
            "remaining": max(self.limit - self.used, 0),
            "reset_at": self.reset_at,
        }


class QuotaGate(Protocol):
    def consume(self, user_sub: str) -> Quota | None:
        """Tính một lượt cho người dùng; hết lượt thì báo ChatError 429 rate_limited."""
        ...


class NoQuota:
    """Chưa giới hạn lượt hỏi (chờ PR #41 mục 3, 4)."""

    def consume(self, user_sub: str) -> Quota | None:
        return None


# ---------- gọi model ----------


@dataclass
class ChatDeps:
    """Những thứ Lambda cung cấp: client Bedrock, nguồn dữ liệu cho tool, prompt."""

    client: Any  # có .converse(**kwargs) như boto3 bedrock-runtime
    forecasts: T.ForecastRepository
    news: N.NewsRepository
    prompts: Mapping[str, str]  # nhánh → system prompt
    quota: QuotaGate = field(default_factory=NoQuota)
    guardrail: Mapping[str, str] | None = None  # {"guardrailIdentifier", "guardrailVersion"}
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def _tool_config() -> dict[str, Any]:
    return {
        "tools": [T.GET_FORECAST_TOOL_SPEC, N.GET_NEWS_TOOL_SPEC],
        "toolChoice": {"auto": {}},
    }


def _messages(req: ChatRequest) -> list[dict[str, Any]]:
    msgs = [{"role": r, "content": [{"text": t}]} for r, t in req.history]
    content = [{"text": req.question}]
    if req.asset:
        # Trang người dùng đang xem: để ở khối riêng, không trộn vào câu hỏi (PR #41 mục 5)
        content.append({"text": f"[Ngữ cảnh] Người dùng đang xem trang dự báo của: {req.asset}"})
    msgs.append({"role": "user", "content": content})
    return msgs


def _run_tool(name: str, tool_input: Mapping[str, Any], deps: ChatDeps) -> dict[str, Any]:
    if name == T.TOOL_NAME:
        return T.get_forecast(tool_input, deps.forecasts)
    if name == N.TOOL_NAME:
        return N.get_news(tool_input, deps.news)
    return {"error": "unknown_tool", "message": f"Không có tool {name!r}."}


def _client_error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        return response.get("Error", {}).get("Code")
    return None


def _timeout_error() -> ChatError:
    return ChatError(504, "timeout", "Câu trả lời mất quá nhiều thời gian, bạn thử lại.")


def _converse(deps: ChatDeps, kwargs: dict[str, Any], deadline: float) -> dict[str, Any]:
    """Gọi Converse; chỉ gọi khi còn đủ MIN_CALL_S trước `deadline` (theo `deps.clock`). Lỗi tạm
    thời được thử lại một lần nếu còn thời gian; hết thời gian thì 504, model không sẵn sàng thì 503."""
    for attempt in range(2):
        if deadline - deps.clock() < MIN_CALL_S:
            raise _timeout_error()
        try:
            return deps.client.converse(**kwargs)
        except Exception as exc:
            if type(exc).__name__ in TIMEOUT_ERRORS:
                log.warning("bedrock timeout: %s", type(exc).__name__)
                raise _timeout_error() from exc
            code = _client_error_code(exc)
            if code not in UNAVAILABLE_CODES:
                raise
            log.warning("bedrock unavailable: %s (attempt %d)", code, attempt + 1)
            if code not in RETRY_CODES or attempt == 1:
                raise ChatError(
                    503, "model_unavailable", "Trợ lý đang bận, bạn thử lại sau ít phút."
                ) from exc
            deps.sleep(RETRY_DELAY_S)
    raise AssertionError("unreachable")  # pragma: no cover


@dataclass
class ChatResult:
    answer: str
    branch: str
    forecasts_used: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    truncated: bool
    blocked: bool
    tool_calls: list[str]
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    tool_errors: list[str] = field(default_factory=list)  # "<tool>:<mã lỗi>", để ghi log


def answer(
    req: ChatRequest,
    deps: ChatDeps,
    branch: str | None = None,
    budget_s: float | None = None,
) -> ChatResult:
    """Trả lời một câu hỏi trong `budget_s` giây (mặc định DEFAULT_BUDGET_S). Báo ChatError 503
    (model không sẵn sàng) hoặc 504 (không còn đủ thời gian cho lần gọi model tiếp theo)."""
    branch = branch or choose_branch(req)
    deadline = deps.clock() + (DEFAULT_BUDGET_S if budget_s is None else budget_s)
    kwargs: dict[str, Any] = {
        "modelId": MODEL_IDS[branch],
        "system": [{"text": deps.prompts[branch]}],
        "inferenceConfig": {"maxTokens": MAX_TOKENS[branch], "temperature": TEMPERATURE},
    }
    if branch == "complex":
        kwargs["toolConfig"] = _tool_config()
    if deps.guardrail:
        kwargs["guardrailConfig"] = dict(deps.guardrail)

    messages = _messages(req)
    forecasts: list[dict[str, Any]] = []
    news_items: list[dict[str, Any]] = []
    tool_names: list[str] = []
    tool_errors: list[str] = []
    tokens_in = tokens_out = 0
    rounds = 0
    while True:
        resp = _converse(deps, {**kwargs, "messages": messages}, deadline)
        usage = resp.get("usage", {})
        tokens_in += usage.get("inputTokens", 0)
        tokens_out += usage.get("outputTokens", 0)
        stop = resp.get("stopReason")
        message = resp["output"]["message"]
        messages.append(message)
        if stop == "guardrail_intervened":
            return ChatResult(
                BLOCKED_ANSWER,
                branch,
                [],
                [],
                False,
                True,
                tool_names,
                tokens_in,
                tokens_out,
                stop,
                tool_errors,
            )
        uses = [b["toolUse"] for b in message["content"] if "toolUse" in b]
        if stop != "tool_use" or not uses:
            break
        rounds += 1
        if rounds > MAX_TOOL_ROUNDS:
            stop = "tool_round_limit"
            break
        results = []
        for tu in uses:
            out = _run_tool(tu["name"], tu.get("input") or {}, deps)
            tool_names.append(tu["name"])
            ok = "error" not in out
            if not ok:
                tool_errors.append(f"{tu['name']}:{out['error']}")
            if ok and tu["name"] == T.TOOL_NAME:
                forecasts.append(out)
            if ok and tu["name"] == N.TOOL_NAME:
                news_items.extend(out["items"])
            results.append(
                {
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"json": out}],
                        "status": "success" if ok else "error",
                    }
                }
            )
        messages.append({"role": "user", "content": results})

    text = "\n".join(
        b["text"]
        for m in messages[len(req.history) + 1 :]
        if m["role"] == "assistant"
        for b in m["content"]
        if "text" in b
    ).strip()
    return ChatResult(
        answer=text,
        branch=branch,
        forecasts_used=_forecasts_used(forecasts),
        citations=_citations(text, news_items),
        truncated=stop == "max_tokens",
        blocked=False,
        tool_calls=tool_names,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        stop_reason=stop,
        tool_errors=tool_errors,
    )


def _forecasts_used(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mỗi tài sản một dòng (lần gọi cuối), lấy nguyên từ kết quả tool."""
    by_asset: dict[str, dict[str, Any]] = {}
    for r in results:
        by_asset[r["asset"]] = {
            k: r[k] for k in ("asset", "base_date", "model_version", "is_sample", "stale")
        }
    return list(by_asset.values())


def _citations(answer_text: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chỉ tin do get_news trả về trong lượt này và có link xuất hiện trong câu trả lời; không bao
    giờ lấy link từ chữ model tự viết."""
    seen, out = set(), []
    for it in items:
        link = it.get("link")
        if link and link in answer_text and link not in seen:
            seen.add(link)
            out.append({k: it.get(k) for k in ("title", "source", "published_at", "link")})
    return out


def response_body(request_id: str, result: ChatResult, quota: Quota | None) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "answer": result.answer,
        "branch": result.branch,
        "prompt_version": PROMPT_VERSIONS[result.branch],
        "forecasts_used": result.forecasts_used,
        "citations": result.citations,
        "truncated": result.truncated,
        "blocked": result.blocked,
        "quota": quota.body() if quota else None,
        "disclaimer": DISCLAIMER,
    }


__all__ = [
    "ChatDeps",
    "ChatError",
    "ChatRequest",
    "ChatResult",
    "NoQuota",
    "Quota",
    "QuotaGate",
    "answer",
    "choose_branch",
    "load_system_prompt",
    "parse_request",
    "response_body",
]

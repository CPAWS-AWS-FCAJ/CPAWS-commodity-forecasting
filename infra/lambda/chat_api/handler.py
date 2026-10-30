"""Lambda `POST /chat` (hợp đồng: `docs/api/contract.md`, mục `POST /chat`, PR #41).

Đóng gói asset Lambda (infra/stacks/chat_asset.py; tests/test_infra_chat_api.py kiểm đủ file):
    handler.py
    forecast_format.py           ← infra/lambda/forecast_api/forecast_format.py
    chatbot/__init__.py, tools.py, news.py, chat.py, quota.py   ← src/chatbot/
    prompts/chatbot-nova-v2.md, chatbot-haiku-v2.md   ← docs/prompts/ (bản đã khóa SHA-256)
    news/gold.json, silver.json, brent.json, wti.json ← infra/lambda/chat_api/news/ (demo, NEWS_DIR;
        cách làm mới và bật: docs/api/demo-news.md)

Biến môi trường:
- FORECASTS_TABLE_NAME (bắt buộc), AWS_REGION;
- CHAT_USAGE_TABLE_NAME (bắt buộc: bảng đếm lượt hỏi chat-usage), CHAT_USER_DAILY_LIMIT (mặc định
  20), CHAT_GLOBAL_DAILY_LIMIT (mặc định 100); PR #41 mục 3, 4;
- NEWS_TABLE_NAME (bảng NewsLabels, ADR-0003 mục 6), NEWS_SORT_KEY (tên thuộc tính SK, mặc định
  "sk"); hoặc NEWS_DIR (thư mục JSON `<asset>.json` cho demo); không đặt thì get_news rỗng;
- PROMPT_DIR (mặc định thư mục `prompts` cạnh handler);
- ALLOWED_ORIGIN (CORS, mặc định "*");
- GUARDRAIL_ID, GUARDRAIL_VERSION (không đặt thì không gắn Guardrail);
- LOG_QUESTIONS = "1" để ghi nguyên văn câu hỏi vào log (chỉ dev; PR #41 mục 7).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

try:  # trong asset Lambda
    from chatbot import chat as chat_core
    from chatbot import news as news_tool
    from chatbot import quota as quota_gate
    from chatbot import tools as forecast_tool
except ImportError:  # trong repo (test)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from src.chatbot import chat as chat_core
    from src.chatbot import news as news_tool
    from src.chatbot import quota as quota_gate
    from src.chatbot import tools as forecast_tool

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_HERE = Path(__file__).resolve().parent
_REPO_PROMPTS = _HERE.parents[2] / "docs" / "prompts" if len(_HERE.parents) > 2 else _HERE
PROMPT_FILES = {"simple": "chatbot-nova-v2.md", "complex": "chatbot-haiku-v2.md"}
# Hạn chót (PR #41): tính từ lúc API Gateway nhận request, vì thời gian Cognito authorizer và
# khởi động lúc cold start xảy ra trước handler nhưng vẫn tính vào 29 giây của API Gateway.
API_GATEWAY_TIMEOUT_S = 29.0
GATEWAY_MARGIN_S = 4.0
LAMBDA_MARGIN_S = 3.0
DEFAULT_USER_DAILY_LIMIT = 20
DEFAULT_GLOBAL_DAILY_LIMIT = 100

_deps_cache: chat_core.ChatDeps | None = None


def _response(status_code: int, body: dict, extra_headers: dict | None = None) -> dict:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
    }
    headers.update(extra_headers or {})
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    }


def _prompt_dir() -> Path:
    if os.environ.get("PROMPT_DIR"):
        return Path(os.environ["PROMPT_DIR"])
    packaged = _HERE / "prompts"
    return packaged if packaged.is_dir() else _REPO_PROMPTS


def news_repository(region: str = "ap-southeast-1"):
    """Nguồn tin cho get_news: bảng NewsLabels nếu có NEWS_TABLE_NAME; thư mục JSON nếu có NEWS_DIR
    (demo khi bảng chưa có dữ liệu); không có gì thì rỗng (model sẽ nói không tìm thấy tin)."""
    if os.environ.get("NEWS_TABLE_NAME"):
        return news_tool.DynamoNewsRepository.from_table_name(
            os.environ["NEWS_TABLE_NAME"], region, sort_key=os.environ.get("NEWS_SORT_KEY", "sk")
        )
    if os.environ.get("NEWS_DIR"):
        return news_tool.JsonFileNewsRepository(os.environ["NEWS_DIR"])
    logger.warning("chat: no news source configured; get_news returns no items")
    return news_tool.StaticNewsRepository()


def time_budget(event: dict, context=None, now=time.time) -> float:
    """Số giây còn lại cho việc trả lời: nhỏ hơn trong hai mốc
    - `requestTimeEpoch` + 29 giây − GATEWAY_MARGIN_S (hạn của API Gateway);
    - thời gian còn lại của Lambda − LAMBDA_MARGIN_S.
    Không có mốc nào (test, gọi trực tiếp) thì dùng DEFAULT_BUDGET_S."""
    budgets = []
    epoch_ms = (event.get("requestContext") or {}).get("requestTimeEpoch")
    if isinstance(epoch_ms, int | float) and not isinstance(epoch_ms, bool):
        budgets.append(epoch_ms / 1000 + API_GATEWAY_TIMEOUT_S - GATEWAY_MARGIN_S - now())
    remaining = getattr(context, "get_remaining_time_in_millis", None)
    if callable(remaining):
        budgets.append(remaining() / 1000 - LAMBDA_MARGIN_S)
    return min(budgets) if budgets else chat_core.DEFAULT_BUDGET_S


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    value = int(raw)
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def quota_from_env(region: str = "ap-southeast-1") -> chat_core.QuotaGate:
    """Bộ đếm lượt hỏi từ biến môi trường; thiếu bảng thì báo lỗi, không chạy khi không có giới
    hạn (giới hạn lượt hỏi là chỗ kiểm soát chi phí Bedrock chính)."""
    table_name = os.environ.get("CHAT_USAGE_TABLE_NAME")
    if not table_name:
        raise RuntimeError("CHAT_USAGE_TABLE_NAME environment variable is missing")
    return quota_gate.DynamoQuotaGate.from_table_name(
        table_name,
        region,
        user_limit=_positive_int_env("CHAT_USER_DAILY_LIMIT", DEFAULT_USER_DAILY_LIMIT),
        global_limit=_positive_int_env("CHAT_GLOBAL_DAILY_LIMIT", DEFAULT_GLOBAL_DAILY_LIMIT),
    )


def _build_deps() -> chat_core.ChatDeps:
    """Tạo client và nguồn dữ liệu một lần cho mỗi môi trường chạy Lambda (tái dùng giữa các lần)."""
    import boto3
    from botocore.config import Config

    region = os.environ.get("AWS_REGION", "ap-southeast-1")
    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        # Không để botocore tự thử lại: chat.py tự thử lại một lần khi còn đủ thời gian, nên mỗi
        # lần gọi dài tối đa connect + read = MIN_CALL_S
        config=Config(
            connect_timeout=chat_core.BEDROCK_CONNECT_TIMEOUT_S,
            read_timeout=chat_core.BEDROCK_READ_TIMEOUT_S,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )
    table_name = os.environ.get("FORECASTS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("FORECASTS_TABLE_NAME environment variable is missing")
    prompts = {b: chat_core.load_system_prompt(_prompt_dir() / f) for b, f in PROMPT_FILES.items()}
    guardrail = None
    if os.environ.get("GUARDRAIL_ID"):
        guardrail = {
            "guardrailIdentifier": os.environ["GUARDRAIL_ID"],
            "guardrailVersion": os.environ.get("GUARDRAIL_VERSION", "DRAFT"),
        }
    return chat_core.ChatDeps(
        client=client,
        forecasts=forecast_tool.DynamoForecastRepository.from_table_name(table_name, region),
        news=news_repository(region),
        prompts=prompts,
        quota=quota_from_env(region),
        guardrail=guardrail,
    )


def _deps() -> chat_core.ChatDeps:
    global _deps_cache
    if _deps_cache is None:
        _deps_cache = _build_deps()
    return _deps_cache


def _parse_body(event: dict):
    raw = event.get("body")
    if raw is None:
        raise chat_core.ChatError(400, "invalid_body", "Thiếu thân request.")
    if event.get("isBase64Encoded"):
        import base64

        try:
            raw = base64.b64decode(raw, validate=True).decode("utf-8", errors="replace")
        except (ValueError, TypeError) as exc:  # binascii.Error là lớp con của ValueError
            raise chat_core.ChatError(400, "invalid_body", "Thân request không hợp lệ.") from exc
    if len(raw.encode("utf-8")) > chat_core.MAX_BODY_BYTES:
        raise chat_core.ChatError(400, "invalid_body", "Thân request lớn hơn 64 KB.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise chat_core.ChatError(400, "invalid_body", "Thân request không phải JSON.") from exc


def handle(event: dict, deps: chat_core.ChatDeps, context=None) -> dict:
    """Xử lý một sự kiện API Gateway (REST, Lambda proxy). Tách khỏi `handler` để test truyền deps."""
    ctx = event.get("requestContext") or {}
    request_id = ctx.get("requestId", "")
    sub = ((ctx.get("authorizer") or {}).get("claims") or {}).get("sub")
    method = event.get("httpMethod", "POST").upper()
    if method != "POST":
        return _response(405, {"error": "method_not_allowed", "message": "Chỉ hỗ trợ POST."})
    if not sub:
        # Cognito authorizer đã chặn trước; tới đây mà thiếu sub là cấu hình sai
        logger.error("chat: missing Cognito sub request_id=%s", request_id)
        return _response(401, {"error": "unauthorized", "message": "Bạn cần đăng nhập."})

    t0 = time.monotonic()
    log = {"request_id": request_id, "sub": sub}
    try:
        req = chat_core.parse_request(_parse_body(event))
        # không đủ thời gian cho một lần gọi model thì trả 504 trước khi tính lượt
        if time_budget(event, context) < chat_core.MIN_CALL_S:
            raise chat_core.ChatError(
                504, "timeout", "Câu trả lời mất quá nhiều thời gian, bạn thử lại."
            )
        quota = deps.quota.consume(sub)
        result = chat_core.answer(req, deps, budget_s=time_budget(event, context))
        log.update(
            branch=result.branch,
            prompt_version=chat_core.PROMPT_VERSIONS[result.branch],
            tools=result.tool_calls,
            tool_errors=result.tool_errors,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            stop_reason=result.stop_reason,
            blocked=result.blocked,
        )
        if os.environ.get("LOG_QUESTIONS") == "1":
            log["question"] = req.question
        status, body = 200, chat_core.response_body(request_id, result, quota)
        headers = None
    except chat_core.ChatError as err:
        status, body = err.status, err.body()
        headers = (
            {"Retry-After": str(err.extra["retry_after"])} if "retry_after" in err.extra else None
        )
        body.pop("retry_after", None)
        log["error"] = err.code
    except Exception:
        logger.exception("chat: unexpected error request_id=%s", request_id)
        status, headers = 500, None
        body = {"error": "internal_error", "message": "Đã có lỗi, bạn thử lại sau."}
        log["error"] = "internal_error"
    log.update(status=status, latency_ms=round((time.monotonic() - t0) * 1000))
    logger.info(json.dumps(log, ensure_ascii=False))
    return _response(status, body, headers)


def handler(event, context):
    try:
        deps = _deps()
    except Exception:
        logger.exception("chat: cannot initialise dependencies")
        return _response(500, {"error": "internal_error", "message": "Đã có lỗi, bạn thử lại sau."})
    return handle(event, deps, context)

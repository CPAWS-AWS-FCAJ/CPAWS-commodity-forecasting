"""Giới hạn lượt hỏi mỗi ngày cho `POST /chat` (hợp đồng: `docs/api/contract.md`, PR #41 mục 3, 4).

Bộ đếm nằm trong bảng DynamoDB `cpaws-<env>-chat-usage`:
- PK `pk`: `user#<sub Cognito>`, dòng giới hạn chung là `global`;
- SK `sk`: `day#YYYY-MM-DD` theo giờ Việt Nam, reset lúc 00:00;
- `request_count` (N), `updated_at` (S, ISO 8601 UTC), `expires_at` (N, TTL: 00:00 giờ Việt Nam
  của ngày + 3 ngày). TTL chỉ để dọn dữ liệu; reset theo ngày dựa vào ngày nằm trong `sk`.

Mỗi lượt gọi một `TransactWriteItems` gồm hai `Update` có điều kiện (dòng người dùng và dòng
`global`): một điều kiện sai thì cả giao dịch bị hủy, nên vượt giới hạn chung không làm mất lượt của
người dùng. Sau đó đọc lại số lượt của người dùng bằng `GetItem` (đọc nhất quán) để trả `quota.used`.
Module chỉ dùng thư viện chuẩn; Lambda truyền client DynamoDB cấp thấp của boto3.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from collections.abc import Callable
from typing import Any

from .chat import ChatError, Quota

log = logging.getLogger("cpaws.chatbot.quota")

VN_TZ = dt.timezone(dt.timedelta(hours=7))
TTL_DAYS = 3
CONFLICT_RETRIES = 2  # TransactionConflict khi hai request cùng ghi dòng `global` một lúc
CONFLICT_DELAY_S = 0.05


def _utc_iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_window(now: dt.datetime) -> tuple[dt.date, dt.datetime, int]:
    """Ngày theo giờ Việt Nam của `now`, thời điểm reset (00:00 giờ Việt Nam ngày kế tiếp) và
    `expires_at` (epoch giây của 00:00 giờ Việt Nam của ngày + TTL_DAYS ngày)."""
    day = now.astimezone(VN_TZ).date()
    start = dt.datetime.combine(day, dt.time(0), VN_TZ)
    return day, start + dt.timedelta(days=1), int((start + dt.timedelta(days=TTL_DAYS)).timestamp())


def _cancel_reasons(exc: Exception) -> list[str]:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return []
    return [str(r.get("Code")) for r in response.get("CancellationReasons") or []]


class DynamoQuotaGate:
    """`QuotaGate` dùng bảng chat-usage. `client`: boto3 client DynamoDB cấp thấp (hoặc đối tượng
    giả có `transact_write_items` và `get_item`)."""

    def __init__(
        self,
        client: Any,
        table_name: str,
        user_limit: int,
        global_limit: int,
        *,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
        sleep: Callable[[float], None] | None = None,
    ):
        if user_limit < 1 or global_limit < 1:
            raise ValueError("user_limit và global_limit phải ≥ 1")
        self._client, self._table = client, table_name
        self.user_limit, self.global_limit = user_limit, global_limit
        self._now = now
        if sleep is None:
            import time

            sleep = time.sleep
        self._sleep = sleep

    @classmethod
    def from_table_name(
        cls, table_name: str, region: str = "ap-southeast-1", **kwargs: Any
    ) -> DynamoQuotaGate:
        import boto3  # nạp khi cần

        return cls(boto3.client("dynamodb", region_name=region), table_name, **kwargs)

    def _update(self, pk: str, sk: str, limit: int, now: dt.datetime, expires_at: int) -> dict:
        return {
            "Update": {
                "TableName": self._table,
                "Key": {"pk": {"S": pk}, "sk": {"S": sk}},
                "UpdateExpression": "ADD request_count :one SET updated_at = :now, "
                "expires_at = :exp",
                "ConditionExpression": "attribute_not_exists(request_count) "
                "OR request_count < :limit",
                "ExpressionAttributeValues": {
                    ":one": {"N": "1"},
                    ":limit": {"N": str(limit)},
                    ":now": {"S": _utc_iso(now)},
                    ":exp": {"N": str(expires_at)},
                },
            }
        }

    def consume(self, user_sub: str) -> Quota:
        """Tính một lượt; hết lượt (của người dùng hoặc chung) thì báo ChatError 429 rate_limited."""
        now = self._now()
        day, reset, expires_at = day_window(now)
        sk, user_pk = f"day#{day.isoformat()}", f"user#{user_sub}"
        items = [
            self._update(user_pk, sk, self.user_limit, now, expires_at),
            self._update("global", sk, self.global_limit, now, expires_at),
        ]
        for attempt in range(CONFLICT_RETRIES + 1):
            try:
                self._client.transact_write_items(TransactItems=items)
                break
            except Exception as exc:
                reasons = _cancel_reasons(exc)
                if "ConditionalCheckFailed" in reasons:
                    raise self._limit_error(reasons[0] == "ConditionalCheckFailed", now, reset)
                if "TransactionConflict" in reasons and attempt < CONFLICT_RETRIES:
                    self._sleep(CONFLICT_DELAY_S * (attempt + 1))
                    continue
                raise
        got = self._client.get_item(
            TableName=self._table,
            Key={"pk": {"S": user_pk}, "sk": {"S": sk}},
            ConsistentRead=True,
            ProjectionExpression="request_count",
        )
        used = int(got.get("Item", {}).get("request_count", {}).get("N", "1"))
        return Quota(limit=self.user_limit, used=used, reset_at=_utc_iso(reset))

    def _limit_error(self, user_scope: bool, now: dt.datetime, reset: dt.datetime) -> ChatError:
        if user_scope:
            message = f"Bạn đã dùng hết {self.user_limit} lượt hỏi hôm nay."
        else:
            message = "Chatbot đã hết lượt hỏi của hôm nay, bạn quay lại sau 0 giờ (giờ Việt Nam)."
        log.info("quota: limit reached scope=%s", "user" if user_scope else "global")
        return ChatError(
            429,
            "rate_limited",
            message,
            reset_at=_utc_iso(reset),
            retry_after=max(1, math.ceil((reset - now).total_seconds())),
        )


__all__ = ["DynamoQuotaGate", "day_window"]

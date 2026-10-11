"""Lấy secret cho pipeline. Mọi chỗ cần EIA key đều gọi get_eia_api_key(); không in key ra log.

- Local: EIA_API_KEY trong .env (CLI gọi load_dotenv) hoặc biến môi trường.
- AWS: chưa chốt nơi lưu secret (Secrets Manager hay SSM Parameter Store, Tiến/Tuấn quyết định).
  Lambda đặt EIA_SECRET_ID (tên secret hoặc tên parameter); phần đọc để TODO bên dưới.
  Không đặt key thật vào biến môi trường của Lambda.
"""

from __future__ import annotations

import os


class SecretUnavailable(RuntimeError):
    """Không lấy được secret (thiếu cấu hình hoặc chưa cài nơi lưu)."""


def get_eia_api_key() -> str:
    key = os.getenv("EIA_API_KEY", "").strip()
    if key:
        return key
    secret_id = os.getenv("EIA_SECRET_ID", "").strip()
    if secret_id:
        # TODO(Tiến/Tuấn, ADR-0006): chọn một trong hai rồi xóa nhánh còn lại, kèm quyền IAM:
        #   Secrets Manager: boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
        #     ["SecretString"]  — quyền secretsmanager:GetSecretValue trên đúng ARN secret
        #   SSM Parameter Store (SecureString): boto3.client("ssm").get_parameter(
        #     Name=secret_id, WithDecryption=True)["Parameter"]["Value"]
        #     — quyền ssm:GetParameter (+ kms:Decrypt nếu dùng CMK)
        raise SecretUnavailable("EIA_SECRET_ID is set but the secret store is not chosen yet")
    raise SecretUnavailable("EIA_API_KEY / EIA_SECRET_ID not set")

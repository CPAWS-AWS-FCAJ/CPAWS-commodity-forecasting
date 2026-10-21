"""Lấy secret cho pipeline. Mọi chỗ cần EIA key đều gọi get_eia_api_key(); không in key ra log.

Thứ tự trong get_eia_api_key():
1. EIA_API_KEY: chạy local (.env, CLI gọi load_dotenv) hoặc biến môi trường.
2. EIA_SECRET_ID: trên AWS. Key lưu ở SSM Parameter Store, SecureString, tier standard, khóa mặc
   định aws/ssm. EIA_SECRET_ID là tên parameter (ví dụ /cpaws/dev/eia-api-key) hoặc ARN của nó.
   Đọc một lần mỗi tiến trình (mỗi cold start của Lambda), cache theo EIA_SECRET_ID.
3. Không có cả hai → SecretUnavailable.
Không đặt key thật vào biến môi trường của Lambda.

Quyền IAM của Lambda: ssm:GetParameter trên đúng ARN parameter
(arn:aws:ssm:<region>:<account>:parameter/cpaws/dev/eia-api-key). Với khóa mặc định aws/ssm thường
không cần thêm kms:Decrypt vào identity policy; nếu đổi sang CMK thì cần kms:Decrypt trên CMK đó.
"""

from __future__ import annotations

import os

_cache: dict[str, str] = {}


class SecretUnavailable(RuntimeError):
    """Không lấy được secret (thiếu cấu hình, parameter không có, thiếu quyền hoặc giá trị rỗng).
    Message chỉ gồm tên parameter và mã lỗi AWS, không bao giờ chứa giá trị secret."""


def _clear_cache() -> None:
    """Chỉ cho test: xóa cache giá trị đã đọc từ SSM."""
    _cache.clear()


def _error_code(e: Exception) -> str:
    """Mã lỗi AWS của ClientError (ví dụ ParameterNotFound, AccessDeniedException); lỗi botocore
    khác (BotoCoreError: NoCredentialsError, EndpointConnectionError...) dùng tên lớp."""
    response = getattr(e, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(e).__name__


def _read_ssm_parameter(name: str, client=None) -> str:
    # Bắt mọi lỗi của lời gọi SSM thay vì import botocore.exceptions (ClientError, BotoCoreError):
    # src/data chỉ khai báo boto3 trong requirements-ingest.txt (tests/test_requirements_ingest.py).
    # Message chỉ có tên parameter và mã lỗi; "from None" để traceback không kèm lỗi gốc.
    try:
        if client is None:
            import boto3

            client = boto3.client("ssm")
        resp = client.get_parameter(Name=name, WithDecryption=True)
        value = str(resp["Parameter"]["Value"]).strip()
    except Exception as e:  # noqa: BLE001 - ClientError/BotoCoreError, xem chú thích trên
        raise SecretUnavailable(f"cannot read SSM parameter {name}: {_error_code(e)}") from None
    if not value:
        raise SecretUnavailable(f"SSM parameter {name} is empty")
    return value


def get_eia_api_key(client=None) -> str:
    """EIA key: EIA_API_KEY → SSM parameter EIA_SECRET_ID → SecretUnavailable.

    client: SSM client tùy chọn (test truyền client giả); mặc định boto3.client("ssm")."""
    key = os.getenv("EIA_API_KEY", "").strip()
    if key:
        return key
    secret_id = os.getenv("EIA_SECRET_ID", "").strip()
    if secret_id:
        if secret_id not in _cache:
            _cache[secret_id] = _read_ssm_parameter(secret_id, client)
        return _cache[secret_id]
    raise SecretUnavailable("EIA_API_KEY / EIA_SECRET_ID not set")

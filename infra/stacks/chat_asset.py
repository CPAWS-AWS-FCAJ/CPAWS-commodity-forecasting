"""Đóng gói asset Lambda `POST /chat` bằng bundling cục bộ của CDK (không cần Docker).

Mỗi file chỉ có một bản nguồn trong repo; lúc synth, CDK gọi `ChatAssetBundling.try_bundle` để
chép đúng danh sách dưới đây vào thư mục asset. Asset chỉ có stdlib + boto3 (có sẵn trong runtime
Python 3.12 của Lambda) nên không `pip install`. Thiếu một file nguồn → synth lỗi ngay, thay vì
Lambda lỗi import lúc chạy (nhánh `except ImportError` của handler sẽ che mất lỗi gốc).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import aws_cdk as cdk
import jsii
from aws_cdk import aws_lambda as lambda_

REPO_ROOT = Path(__file__).resolve().parents[2]
HANDLER_DIR = REPO_ROOT / "infra" / "lambda" / "chat_api"

# Đường dẫn trong asset → đường dẫn nguồn (tính từ gốc repo). Layout khớp docstring của
# infra/lambda/chat_api/handler.py; NEWS_DIR của Lambda = /var/task/news.
CHAT_ASSET_FILES: dict[str, str] = {
    "handler.py": "infra/lambda/chat_api/handler.py",
    "forecast_format.py": "infra/lambda/forecast_api/forecast_format.py",
    "chatbot/__init__.py": "src/chatbot/__init__.py",
    "chatbot/tools.py": "src/chatbot/tools.py",
    "chatbot/news.py": "src/chatbot/news.py",
    "chatbot/chat.py": "src/chatbot/chat.py",
    "chatbot/quota.py": "src/chatbot/quota.py",
    # Prompt v2 đã khóa SHA-256; đổi prompt hoặc tin demo đều phải deploy lại CpawsApi
    "prompts/chatbot-nova-v2.md": "docs/prompts/chatbot-nova-v2.md",
    "prompts/chatbot-haiku-v2.md": "docs/prompts/chatbot-haiku-v2.md",
    "news/gold.json": "infra/lambda/chat_api/news/gold.json",
    "news/silver.json": "infra/lambda/chat_api/news/silver.json",
    "news/brent.json": "infra/lambda/chat_api/news/brent.json",
    "news/wti.json": "infra/lambda/chat_api/news/wti.json",
}


def build_chat_asset(output_dir: Path) -> None:
    """Chép các file của CHAT_ASSET_FILES vào output_dir (copyfile, không chép metadata, để hash
    asset chỉ phụ thuộc nội dung)."""
    missing = [src for src in CHAT_ASSET_FILES.values() if not (REPO_ROOT / src).is_file()]
    if missing:
        raise FileNotFoundError(f"chat asset: missing source files {missing}")
    for dest, src in CHAT_ASSET_FILES.items():
        target = output_dir / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / src, target)


@jsii.implements(cdk.ILocalBundling)
class ChatAssetBundling:
    """Bundling cục bộ: luôn chép file bằng Python, không bao giờ rơi xuống Docker."""

    def try_bundle(self, output_dir: str, options: cdk.BundlingOptions) -> bool:
        build_chat_asset(Path(output_dir))
        return True


def chat_asset_code() -> lambda_.Code:
    # Hash theo nội dung đã đóng gói (OUTPUT): đổi prompt, tin demo hay code đều ra asset mới.
    # Image Docker chỉ là tham số bắt buộc của BundlingOptions, không được dùng vì bundling cục
    # bộ luôn trả True.
    return lambda_.Code.from_asset(
        str(HANDLER_DIR),
        asset_hash_type=cdk.AssetHashType.OUTPUT,
        bundling=cdk.BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            local=ChatAssetBundling(),
        ),
    )

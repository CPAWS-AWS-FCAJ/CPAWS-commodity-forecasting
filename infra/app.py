#!/usr/bin/env python3
"""Điểm vào CDK của CPAWS."""

import json
import os
from pathlib import Path

import aws_cdk as cdk
from stacks.cpaws_api_stack import CpawsApiStack
from stacks.cpaws_auth_stack import CpawsAuthStack
from stacks.cpaws_data_stack import CpawsDataStack
from stacks.cpaws_ops_stack import CpawsOpsStack
from stacks.cpaws_serving_stack import CpawsServingStack
from stacks.shared import (
    accuracy_job_function_name,
    chat_api_function_name,
    ingest_function_name,
    predict_function_name,
)

# Tag image của Lambda ingest trong ECR = SHA ngắn của commit merge PR #43 trên developer
# (gồm #36: đọc EIA key từ SSM, và #43: cờ INGEST_STALE). Không dùng 6956620/3d391dd:
# thiếu code SSM hoặc cờ INGEST_STALE.
# Đổi khi đẩy image mới: cdk deploy CpawsData -c ingest_image_tag=<commit>
DEFAULT_INGEST_IMAGE_TAG = "5cfde32"

# Tag image của Lambda predict = SHA ngắn của commit merge PR #53 trên developer (champion theo
# tài sản qua MODEL_VERSIONS + shadow S1a; gồm cả #48: không ghi đè, input_snapshot_dt).
# Rollback: cdk deploy CpawsData -c predict_image_tag=ce77bcb (image #48, chỉ đọc MODEL_VERSION).
DEFAULT_PREDICT_IMAGE_TAG = "c61abdd"
# Champion mốc thống kê 252 phiên, không cần artifact (Khải chốt 22/10; ADR-0012: cả 4 tài sản).
DEFAULT_PREDICT_MODEL_VERSION = "baseline-q252"
# Champion theo tài sản (RFC #45 v4.6 D10). Lambda predict đọc MODEL_VERSIONS; job accuracy dùng
# cùng giá trị. Phải bằng DEFAULT_PREDICT_MODEL_VERSION cho mọi tài sản (CpawsData kiểm lúc synth).
CHAMPION_MODEL_VERSIONS = {
    "gold": DEFAULT_PREDICT_MODEL_VERSION,
    "silver": DEFAULT_PREDICT_MODEL_VERSION,
    "brent": DEFAULT_PREDICT_MODEL_VERSION,
    "wti": DEFAULT_PREDICT_MODEL_VERSION,
}
# base_date đầu tiên champion baseline-q252 phát hành chạy thật (lượt predict tự động đầu tiên
# 27/10, contract #65). Predict không đọc; job accuracy (rolling_8w) đọc.
CHAMPION_EFFECTIVE_BASE_DATES = {
    "gold": "2026-10-26",
    "silver": "2026-10-26",
    "brent": "2026-10-26",
    "wti": "2026-10-26",
}
# Shadow chạy song song với champion (docs/experiments/s1a-shadow-plan.md), ghi
# eval/shadow/s1a-l094/ trên lake. Tắt mà không build image:
#   cdk deploy CpawsData -c shadow_models=off
DEFAULT_PREDICT_SHADOW_MODELS = "s1a-l094"

# Image của Lambda job accuracy (cpaws-<env>-accuracy-job): repo predict, CMD riêng. Tag = SHA
# ngắn của commit e31c928 (PR job accuracy, commit đầu: thêm COPY src/eval/ vào
# docker/predict/Dockerfile; src/ còn lại giống c61abdd). Lambda predict vẫn giữ c61abdd (mốc #79).
# Đổi: cdk deploy CpawsData -c accuracy_image_tag=<commit>
DEFAULT_ACCURACY_IMAGE_TAG = "e31c928"
# Evidence đã duyệt cho job accuracy (handoff rolling accuracy §3): release cutover #48 (PR #82,
# Khải approve). Đổi evidence (thêm legacy[] hay shadow_release) = PR sửa file + cdk deploy.
ACCURACY_EVIDENCE_FILE = (
    Path(__file__).resolve().parents[1]
    / "docs/eval/evidence/rolling-release-cutover-2026-10-30.json"
)

app = cdk.App()
env_name = app.node.try_get_context("env") or "dev"
ingest_image_tag = app.node.try_get_context("ingest_image_tag") or DEFAULT_INGEST_IMAGE_TAG

# SSM SecureString parameter name for the EIA API key.
# Pass only the parameter name, never the API key value.
eia_parameter_name = (
    app.node.try_get_context("eia_parameter_name") or f"/cpaws/{env_name}/eia-api-key"
)
predict_image_tag = app.node.try_get_context("predict_image_tag") or DEFAULT_PREDICT_IMAGE_TAG
predict_model_version = (
    app.node.try_get_context("predict_model_version") or DEFAULT_PREDICT_MODEL_VERSION
)
# "off" (hoặc "none") = tắt shadow; không truyền = mặc định ở trên
shadow_context = app.node.try_get_context("shadow_models")
predict_shadow_models = (
    DEFAULT_PREDICT_SHADOW_MODELS if shadow_context is None else str(shadow_context).strip()
)
if predict_shadow_models.lower() in ("off", "none"):
    predict_shadow_models = ""
accuracy_image_tag = app.node.try_get_context("accuracy_image_tag") or DEFAULT_ACCURACY_IMAGE_TAG
accuracy_evidence = json.loads(ACCURACY_EVIDENCE_FILE.read_text(encoding="utf-8"))
# Chỉ dùng ở lần deploy ĐẦU TIÊN (tạo ECR predict trước khi có image): -c predict_repo_only=true
predict_repo_only = str(app.node.try_get_context("predict_repo_only") or "").lower() == "true"

# Tài khoản lấy từ profile đang dùng; region cố định theo ADR
aws_env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region="ap-southeast-1",
)

# Email nhận cảnh báo: truyền khi deploy (-c alarm_email=...), KHÔNG ghi vào repo public.
# Luôn truyền lại ở mỗi lần deploy CpawsOps, nếu bỏ thì subscription bị gỡ.
alarm_email = app.node.try_get_context("alarm_email")

# Data ingestion stack
CpawsDataStack(
    app,
    "CpawsData",
    env_name=env_name,
    ingest_image_tag=ingest_image_tag,
    eia_parameter_name=eia_parameter_name,
    predict_image_tag=predict_image_tag,
    predict_model_version=predict_model_version,
    predict_model_versions=CHAMPION_MODEL_VERSIONS,
    champion_effective_base_dates=CHAMPION_EFFECTIVE_BASE_DATES,
    predict_shadow_models=predict_shadow_models,
    accuracy_image_tag=accuracy_image_tag,
    accuracy_evidence=accuracy_evidence,
    predict_repo_only=predict_repo_only,
    env=aws_env,
)

# Monitoring và cảnh báo cho Lambda ingest, predict (cả shadow S1a), job accuracy và /chat
CpawsOpsStack(
    app,
    "CpawsOps",
    env_name=env_name,
    ingest_function_name=ingest_function_name(env_name),
    predict_function_name=predict_function_name(env_name),
    chat_function_name=chat_api_function_name(env_name),
    accuracy_function_name=accuracy_job_function_name(env_name),
    alarm_email=alarm_email,
    env=aws_env,
)

# DynamoDB table lưu kết quả dự báo
serving_stack = CpawsServingStack(
    app,
    "CpawsServing",
    env_name=env_name,
    env=aws_env,
)

# Cognito xác thực người dùng
auth_stack = CpawsAuthStack(
    app,
    "CpawsAuth",
    env_name=env_name,
    env=aws_env,
)

# REST API: dữ liệu dự báo và POST /chat (Bedrock), xác thực Cognito.
# Deploy CpawsServing (bảng chat-usage) trước CpawsApi: Lambda /chat dựng ARN bảng theo tên.
CpawsApiStack(
    app,
    "CpawsApi",
    env_name=env_name,
    forecasts_table=serving_stack.forecasts_table,
    user_pool=auth_stack.user_pool,
    env=aws_env,
)

# Tag bắt buộc theo aws-cost-guard
cdk.Tags.of(app).add("Project", "CPAWS")
cdk.Tags.of(app).add("Owner", "Tien")
cdk.Tags.of(app).add("Env", env_name)

app.synth()

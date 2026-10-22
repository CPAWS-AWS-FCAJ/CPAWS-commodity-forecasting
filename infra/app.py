#!/usr/bin/env python3
"""Điểm vào CDK của CPAWS."""

import os

import aws_cdk as cdk
from stacks.cpaws_api_stack import CpawsApiStack
from stacks.cpaws_auth_stack import CpawsAuthStack
from stacks.cpaws_data_stack import CpawsDataStack
from stacks.cpaws_ops_stack import CpawsOpsStack
from stacks.cpaws_serving_stack import CpawsServingStack
from stacks.shared import ingest_function_name

# Tag image của Lambda ingest trong ECR = SHA ngắn của commit merge PR #9 trên developer
# (Dockerfile đã ghim digest base). Không dùng 286846a: build trước khi ghim digest.
# Đổi khi đẩy image mới: cdk deploy CpawsData -c ingest_image_tag=<commit>
DEFAULT_INGEST_IMAGE_TAG = "6956620"

app = cdk.App()
env_name = app.node.try_get_context("env") or "dev"
ingest_image_tag = app.node.try_get_context("ingest_image_tag") or DEFAULT_INGEST_IMAGE_TAG

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
    env=aws_env,
)

# Monitoring và cảnh báo cho Lambda ingest
CpawsOpsStack(
    app,
    "CpawsOps",
    env_name=env_name,
    ingest_function_name=ingest_function_name(env_name),
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

# REST API phục vụ dữ liệu dự báo, tích hợp DynamoDB và Cognito
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

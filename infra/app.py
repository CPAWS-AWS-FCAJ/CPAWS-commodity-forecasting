#!/usr/bin/env python3
"""Điểm vào CDK của CPAWS."""

import os

import aws_cdk as cdk
from stacks.cpaws_data_stack import CpawsDataStack
from stacks.cpaws_ops_stack import CpawsOpsStack

# Tag image của Lambda ingest trong ECR = SHA ngắn của commit merge PR #9 trên developer
# (Dockerfile đã ghim digest base). Không dùng 286846a: build trước khi ghim digest.
# Đổi khi đẩy image mới: cdk deploy CpawsData -c ingest_image_tag=<commit>
DEFAULT_INGEST_IMAGE_TAG = "6956620"

app = cdk.App()
env_name = app.node.try_get_context("env") or "dev"
ingest_image_tag = app.node.try_get_context("ingest_image_tag") or DEFAULT_INGEST_IMAGE_TAG

# Tài khoản lấy từ profile đang dùng; region cố định theo ADR
aws_env = cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region="ap-southeast-1")

# Email nhận cảnh báo: truyền khi deploy (-c alarm_email=...), KHÔNG ghi vào repo public.
# Luôn truyền lại ở mỗi lần deploy CpawsOps, nếu bỏ thì subscription bị gỡ.
alarm_email = app.node.try_get_context("alarm_email")

CpawsDataStack(
    app,
    "CpawsData",
    env_name=env_name,
    ingest_image_tag=ingest_image_tag,
    env=aws_env,
)

# Alarm tham chiếu Lambda ingest theo tên, không dùng export giữa hai stack
CpawsOpsStack(
    app,
    "CpawsOps",
    env_name=env_name,
    ingest_function_name=f"cpaws-{env_name}-ingest",
    alarm_email=alarm_email,
    env=aws_env,
)

# Tag bắt buộc theo aws-cost-guard
cdk.Tags.of(app).add("Project", "CPAWS")
cdk.Tags.of(app).add("Owner", "Tien")
cdk.Tags.of(app).add("Env", env_name)

app.synth()

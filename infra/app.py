#!/usr/bin/env python3
"""Điểm vào CDK của CPAWS."""

import os

import aws_cdk as cdk
from stacks.cpaws_data_stack import CpawsDataStack

# Tag image của Lambda ingest trong ECR = SHA ngắn của commit merge PR #9 trên developer
# (Dockerfile đã ghim digest base). Không dùng 286846a: build trước khi ghim digest.
# Đổi khi đẩy image mới: cdk deploy CpawsData -c ingest_image_tag=<commit>
DEFAULT_INGEST_IMAGE_TAG = "6956620"

app = cdk.App()
env_name = app.node.try_get_context("env") or "dev"
ingest_image_tag = app.node.try_get_context("ingest_image_tag") or DEFAULT_INGEST_IMAGE_TAG

CpawsDataStack(
    app,
    "CpawsData",
    env_name=env_name,
    ingest_image_tag=ingest_image_tag,
    # Tài khoản lấy từ profile đang dùng; region cố định theo ADR
    env=cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region="ap-southeast-1"),
)

# Tag bắt buộc theo aws-cost-guard
cdk.Tags.of(app).add("Project", "CPAWS")
cdk.Tags.of(app).add("Owner", "Tien")
cdk.Tags.of(app).add("Env", env_name)

app.synth()

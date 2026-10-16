#!/usr/bin/env python3
"""Điểm vào CDK của CPAWS."""

import os

import aws_cdk as cdk
from stacks.cpaws_data_stack import CpawsDataStack

app = cdk.App()
env_name = app.node.try_get_context("env") or "dev"

CpawsDataStack(
    app,
    "CpawsData",
    env_name=env_name,
    # Tài khoản lấy từ profile đang dùng; region cố định theo ADR
    env=cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region="ap-southeast-1"),
)

# Tag bắt buộc theo aws-cost-guard
cdk.Tags.of(app).add("Project", "CPAWS")
cdk.Tags.of(app).add("Owner", "Tien")
cdk.Tags.of(app).add("Env", env_name)

app.synth()

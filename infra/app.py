#!/usr/bin/env python3
"""Điểm vào CDK của CPAWS."""

import os

import aws_cdk as cdk
from stacks.cpaws_api_stack import CpawsApiStack
from stacks.cpaws_auth_stack import CpawsAuthStack
from stacks.cpaws_data_stack import CpawsDataStack
from stacks.cpaws_serving_stack import CpawsServingStack

# Tag image của Lambda ingest trong ECR.
DEFAULT_INGEST_IMAGE_TAG = "6956620"

app = cdk.App()
env_name = app.node.try_get_context("env") or "dev"

ingest_image_tag = app.node.try_get_context("ingest_image_tag") or DEFAULT_INGEST_IMAGE_TAG

aws_env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region="ap-southeast-1",
)

# Stack dữ liệu hiện có.
CpawsDataStack(
    app,
    "CpawsData",
    env_name=env_name,
    ingest_image_tag=ingest_image_tag,
    env=aws_env,
)

# Stack DynamoDB Forecasts.
serving_stack = CpawsServingStack(
    app,
    "CpawsServing",
    env_name=env_name,
    env=aws_env,
)

# Stack Cognito xác thực.
auth_stack = CpawsAuthStack(
    app,
    "CpawsAuth",
    env_name=env_name,
    env=aws_env,
)

# Stack API tham chiếu DynamoDB và Cognito.
CpawsApiStack(
    app,
    "CpawsApi",
    env_name=env_name,
    forecasts_table=serving_stack.forecasts_table,
    user_pool=auth_stack.user_pool,
    env=aws_env,
)

# Tag bắt buộc theo aws-cost-guard.
cdk.Tags.of(app).add("Project", "CPAWS")
cdk.Tags.of(app).add("Owner", "Tien")
cdk.Tags.of(app).add("Env", env_name)

app.synth()

"""Kiểm tra các stack CDK: alarm theo dõi đúng Lambda, lịch khớp config.

Cần aws-cdk-lib (có trong infra\\.venv, không có trong CI) nên tự bỏ qua khi thiếu.
Chạy: infra\\.venv\\Scripts\\activate rồi pytest tests/test_infra_stacks.py (từ gốc repo).
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk")

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra"


@pytest.fixture(scope="module")
def templates() -> dict:
    """Synth CpawsData và CpawsOps cho env dev, trả về template dạng dict theo tên stack."""
    sys.path.insert(0, str(INFRA_DIR))
    try:
        import aws_cdk as cdk
        from aws_cdk.assertions import Template
        from stacks.cpaws_data_stack import CpawsDataStack
        from stacks.cpaws_ops_stack import CpawsOpsStack
        from stacks.shared import ingest_function_name

        app = cdk.App()
        data = CpawsDataStack(app, "CpawsData", env_name="dev", ingest_image_tag="abc1234")
        ops = CpawsOpsStack(
            app,
            "CpawsOps",
            env_name="dev",
            ingest_function_name=ingest_function_name("dev"),
        )
        return {
            "data": Template.from_stack(data).to_json(),
            "ops": Template.from_stack(ops).to_json(),
        }
    finally:
        sys.path.remove(str(INFRA_DIR))


def _resources(template: dict, resource_type: str) -> list[dict]:
    return [r for r in template["Resources"].values() if r["Type"] == resource_type]


def test_alarm_watches_the_deployed_lambda(templates):
    (fn,) = _resources(templates["data"], "AWS::Lambda::Function")
    (alarm,) = _resources(templates["ops"], "AWS::CloudWatch::Alarm")
    dims = {d["Name"]: d["Value"] for d in alarm["Properties"]["Dimensions"]}
    assert dims["FunctionName"] == fn["Properties"]["FunctionName"]
    assert alarm["Properties"]["MetricName"] == "Errors"
    assert alarm["Properties"]["Namespace"] == "AWS/Lambda"


def test_schedule_matches_config(templates):
    from src.data.config import INGEST_SCHEDULE_EXPRESSION, INGEST_SCHEDULE_TIMEZONE

    (schedule,) = _resources(templates["data"], "AWS::Scheduler::Schedule")
    props = schedule["Properties"]
    assert props["ScheduleExpression"] == INGEST_SCHEDULE_EXPRESSION
    assert props["ScheduleExpressionTimezone"] == INGEST_SCHEDULE_TIMEZONE
    assert props["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 0


def test_scheduler_role_only_invokes_ingest_lambda(templates):
    policies = _resources(templates["data"], "AWS::IAM::Policy")
    invoke = [
        st
        for p in policies
        for st in p["Properties"]["PolicyDocument"]["Statement"]
        if st["Action"] == "lambda:InvokeFunction"
    ]
    assert len(invoke) == 1
    assert not isinstance(invoke[0]["Resource"], list)

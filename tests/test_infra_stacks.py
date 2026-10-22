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


# Schedule group chứa lịch ingest. Cố ý ghi cứng ở đây (không import từ infra/stacks/shared.py):
# đổi group là đổi quyền assume của role Scheduler nên phải sửa test có chủ đích.
EXPECTED_SCHEDULE_GROUP = "default"


def _render(value) -> str:
    """Biến Ref/Fn::Join của CloudFormation thành chuỗi có placeholder để so sánh ARN."""
    if isinstance(value, str):
        return value
    if "Ref" in value:
        return "${" + value["Ref"] + "}"
    if "Fn::Join" in value:
        separator, parts = value["Fn::Join"]
        return separator.join(_render(part) for part in parts)
    raise AssertionError(f"Chưa hỗ trợ intrinsic function: {value!r}")


def _scheduler_role(template: dict) -> dict:
    roles = [
        role
        for role in _resources(template, "AWS::IAM::Role")
        if any(
            st["Principal"].get("Service") == "scheduler.amazonaws.com"
            for st in role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        )
    ]
    assert len(roles) == 1
    return roles[0]


def test_scheduler_trust_policy_is_scoped_to_account_and_schedule_group(templates):
    role = _scheduler_role(templates["data"])
    (statement,) = role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == "sts:AssumeRole"
    assert statement["Principal"] == {"Service": "scheduler.amazonaws.com"}

    # Chỉ một khối điều kiện StringEquals, có đủ aws:SourceAccount và aws:SourceArn
    assert set(statement["Condition"]) == {"StringEquals"}
    equals = statement["Condition"]["StringEquals"]
    assert set(equals) == {"aws:SourceAccount", "aws:SourceArn"}
    assert _render(equals["aws:SourceAccount"]) == "${AWS::AccountId}"
    # AWS yêu cầu ARN của schedule group, không phải ARN của từng schedule
    assert _render(equals["aws:SourceArn"]) == (
        "arn:${AWS::Partition}:scheduler:${AWS::Region}:${AWS::AccountId}"
        f":schedule-group/{EXPECTED_SCHEDULE_GROUP}"
    )


def test_schedule_belongs_to_the_group_allowed_by_the_trust_policy(templates):
    (schedule,) = _resources(templates["data"], "AWS::Scheduler::Schedule")
    assert schedule["Properties"]["GroupName"] == EXPECTED_SCHEDULE_GROUP

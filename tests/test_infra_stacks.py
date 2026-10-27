"""Kiểm tra các stack CDK: alarm theo dõi đúng Lambda, lịch khớp config, luồng ingest → predict.

Cần aws-cdk-lib (có trong infra\\.venv, không có trong CI) nên tự bỏ qua khi thiếu.
Chạy: infra\\.venv\\Scripts\\activate rồi pytest tests/test_infra_stacks.py (từ gốc repo).
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk")

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra"


PREDICT_TAG = "def5678"


def _synth(
    *,
    predict_repo_only: bool = False,
    eia_parameter_name: str | None = None,
) -> dict:
    """Synth CpawsData, CpawsOps và CpawsServing cho env dev, trả về template dạng dict."""
    sys.path.insert(0, str(INFRA_DIR))
    try:
        import aws_cdk as cdk
        from aws_cdk.assertions import Template
        from stacks.cpaws_data_stack import CpawsDataStack
        from stacks.cpaws_ops_stack import CpawsOpsStack
        from stacks.cpaws_serving_stack import CpawsServingStack
        from stacks.shared import ingest_function_name, predict_function_name

        app = cdk.App()
        data = CpawsDataStack(
            app,
            "CpawsData",
            env_name="dev",
            ingest_image_tag="abc1234",
            predict_image_tag=PREDICT_TAG,
            predict_model_version="baseline-q252",
            predict_repo_only=predict_repo_only,
            eia_parameter_name=eia_parameter_name,
        )
        ops = CpawsOpsStack(
            app,
            "CpawsOps",
            env_name="dev",
            ingest_function_name=ingest_function_name("dev"),
            predict_function_name=predict_function_name("dev"),
        )
        serving = CpawsServingStack(app, "CpawsServing", env_name="dev")
        return {
            "data": Template.from_stack(data).to_json(),
            "ops": Template.from_stack(ops).to_json(),
            "serving": Template.from_stack(serving).to_json(),
        }
    finally:
        sys.path.remove(str(INFRA_DIR))


@pytest.fixture(scope="module")
def templates() -> dict:
    return _synth()


def _resources(template: dict, resource_type: str) -> list[dict]:
    return [r for r in template["Resources"].values() if r["Type"] == resource_type]


def _items(template: dict, resource_type: str) -> dict[str, dict]:
    """{logical id: resource} của một loại tài nguyên."""
    return {k: r for k, r in template["Resources"].items() if r["Type"] == resource_type}


def _function_id(template: dict, function_name: str) -> str:
    (fid,) = [
        k
        for k, r in _items(template, "AWS::Lambda::Function").items()
        if r["Properties"]["FunctionName"] == function_name
    ]
    return fid


def _role_statements(template: dict, role_id: str) -> list[dict]:
    """Mọi statement trong các AWS::IAM::Policy gắn vào role này."""
    return [
        st
        for p in _resources(template, "AWS::IAM::Policy")
        if {"Ref": role_id} in p["Properties"]["Roles"]
        for st in p["Properties"]["PolicyDocument"]["Statement"]
    ]


def _event_invoke_config(template: dict, function_id: str) -> dict:
    (cfg,) = [
        r["Properties"]
        for r in _resources(template, "AWS::Lambda::EventInvokeConfig")
        if r["Properties"]["FunctionName"] == {"Ref": function_id}
    ]
    return cfg


def test_alarms_watch_the_deployed_lambdas(templates):
    fn_names = {
        r["Properties"]["FunctionName"]
        for r in _resources(templates["data"], "AWS::Lambda::Function")
    }
    assert fn_names == {"cpaws-dev-ingest", "cpaws-dev-predict"}
    watched = set()
    for alarm in _resources(templates["ops"], "AWS::CloudWatch::Alarm"):
        dims = {d["Name"]: d["Value"] for d in alarm["Properties"]["Dimensions"]}
        assert alarm["Properties"]["MetricName"] == "Errors"
        assert alarm["Properties"]["Namespace"] == "AWS/Lambda"
        watched.add(dims["FunctionName"])
    # Mỗi Lambda đúng một alarm, không alarm nào theo dõi tên không tồn tại
    assert watched == fn_names


def test_ingest_success_and_failure_both_invoke_predict(templates):
    t = templates["data"]
    ingest_id = _function_id(t, "cpaws-dev-ingest")
    predict_id = _function_id(t, "cpaws-dev-predict")
    cfg = _event_invoke_config(t, ingest_id)
    assert cfg["MaximumRetryAttempts"] == 1
    target = {"Fn::GetAtt": [predict_id, "Arn"]}
    assert cfg["DestinationConfig"]["OnSuccess"]["Destination"] == target
    assert cfg["DestinationConfig"]["OnFailure"]["Destination"] == target
    # Predict không retry và không nối tiếp đi đâu
    pcfg = _event_invoke_config(t, predict_id)
    assert pcfg["MaximumRetryAttempts"] == 0
    assert "DestinationConfig" not in pcfg


def test_predict_lambda_configuration(templates):
    t = templates["data"]
    fn = t["Resources"][_function_id(t, "cpaws-dev-predict")]["Properties"]
    assert fn["MemorySize"] == 1024 and fn["Timeout"] == 120
    assert fn["PackageType"] == "Image" and fn["Architectures"] == ["x86_64"]
    assert "VpcConfig" not in fn
    # ImageUri là Fn::Join(<account>.dkr.ecr...<repo>, ":<tag>"): phần cuối mang tag
    image_parts = fn["Code"]["ImageUri"]["Fn::Join"][1]
    assert image_parts[-1].endswith(f":{PREDICT_TAG}")
    assert "PredictRepo" in str(image_parts)
    env = fn["Environment"]["Variables"]
    assert set(env) == {"LAKE_BUCKET", "FORECASTS_TABLE", "MODEL_VERSION", "CPAWS_ENV"}
    assert env["FORECASTS_TABLE"] == "cpaws-dev-forecasts"
    assert env["MODEL_VERSION"] == "baseline-q252"
    assert env["CPAWS_ENV"] == "dev"


def test_predict_role_is_least_privilege(templates):
    t = templates["data"]
    fn = t["Resources"][_function_id(t, "cpaws-dev-predict")]["Properties"]
    role_id = fn["Role"]["Fn::GetAtt"][0]
    by_sid = {st["Sid"]: st for st in _role_statements(t, role_id)}
    assert set(by_sid) == {"LakeReadCleanModels", "LakeListCleanModels", "ForecastsPutItem"}

    read = by_sid["LakeReadCleanModels"]
    assert read["Action"] == "s3:GetObject"
    assert sorted(_render(r).split("/", 1)[-1] for r in read["Resource"]) == ["clean/*", "models/*"]

    lst = by_sid["LakeListCleanModels"]
    assert lst["Action"] == "s3:ListBucket"
    assert lst["Condition"] == {"StringLike": {"s3:prefix": ["clean/*", "models/*"]}}

    put = by_sid["ForecastsPutItem"]
    assert put["Action"] == "dynamodb:PutItem"
    assert _render(put["Resource"]).endswith(":table/cpaws-dev-forecasts")

    # Không có action hay resource "*" trong policy riêng của role
    for st in by_sid.values():
        assert "*" not in str(st["Action"])
        assert st.get("Resource") != "*"


def test_predict_table_name_matches_serving_stack(templates):
    # CpawsServing có nhiều bảng (Forecasts, NewsLabels): tìm theo tên predict ghi vào
    _table(templates["serving"], "cpaws-dev-forecasts")


def test_repo_only_mode_creates_repo_without_predict_lambda():
    t = _synth(predict_repo_only=True)["data"]
    names = {r["Properties"]["FunctionName"] for r in _resources(t, "AWS::Lambda::Function")}
    assert names == {"cpaws-dev-ingest"}
    repos = {r["Properties"]["RepositoryName"] for r in _resources(t, "AWS::ECR::Repository")}
    assert repos == {"cpaws-dev-ingest", "cpaws-dev-predict"}
    cfg = _event_invoke_config(t, _function_id(t, "cpaws-dev-ingest"))
    assert cfg["MaximumRetryAttempts"] == 1
    assert "DestinationConfig" not in cfg


def test_schedule_matches_config(templates):
    from src.data.config import INGEST_SCHEDULE_EXPRESSION, INGEST_SCHEDULE_TIMEZONE

    (schedule,) = _resources(templates["data"], "AWS::Scheduler::Schedule")
    props = schedule["Properties"]
    assert props["ScheduleExpression"] == INGEST_SCHEDULE_EXPRESSION
    assert props["ScheduleExpressionTimezone"] == INGEST_SCHEDULE_TIMEZONE
    assert props["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 0


def test_scheduler_role_only_invokes_ingest_lambda(templates):
    t = templates["data"]
    role_id = _scheduler_role_id(t)
    invoke = [st for st in _role_statements(t, role_id) if st["Action"] == "lambda:InvokeFunction"]
    assert len(invoke) == 1
    assert invoke[0]["Resource"] == {"Fn::GetAtt": [_function_id(t, "cpaws-dev-ingest"), "Arn"]}


def test_only_ingest_role_may_invoke_predict(templates):
    """Ngoài destination của ingest, không role nào trong stack được gọi Lambda predict."""
    t = templates["data"]
    predict_arn = {"Fn::GetAtt": [_function_id(t, "cpaws-dev-predict"), "Arn"]}
    ingest_fn = t["Resources"][_function_id(t, "cpaws-dev-ingest")]["Properties"]
    ingest_role_id = ingest_fn["Role"]["Fn::GetAtt"][0]
    holders = [
        p["Properties"]["Roles"]
        for p in _resources(t, "AWS::IAM::Policy")
        for st in p["Properties"]["PolicyDocument"]["Statement"]
        if st["Action"] == "lambda:InvokeFunction"
        and predict_arn
        in (st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]])
    ]
    assert holders == [[{"Ref": ingest_role_id}]]


# Schedule group chứa lịch ingest. Cố ý ghi cứng ở đây (không import từ infra/stacks/shared.py):
# đổi group là đổi quyền assume của role Scheduler nên phải sửa test có chủ đích.
EXPECTED_SCHEDULE_GROUP = "default"


def _render(value) -> str:
    """Biến Ref/Fn::GetAtt/Fn::Join của CloudFormation thành chuỗi có placeholder để so sánh ARN."""
    if isinstance(value, str):
        return value
    if "Ref" in value:
        return "${" + value["Ref"] + "}"
    if "Fn::GetAtt" in value:
        return "${" + ".".join(value["Fn::GetAtt"]) + "}"
    if "Fn::Join" in value:
        separator, parts = value["Fn::Join"]
        return separator.join(_render(part) for part in parts)
    raise AssertionError(f"Chưa hỗ trợ intrinsic function: {value!r}")


def _scheduler_role_id(template: dict) -> str:
    roles = [
        rid
        for rid, role in _items(template, "AWS::IAM::Role").items()
        if any(
            st["Principal"].get("Service") == "scheduler.amazonaws.com"
            for st in role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        )
    ]
    assert len(roles) == 1
    return roles[0]


def _scheduler_role(template: dict) -> dict:
    return template["Resources"][_scheduler_role_id(template)]


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


def test_ingest_role_can_read_only_configured_eia_parameter():
    t = _synth(eia_parameter_name="/cpaws/dev/eia-api-key")["data"]
    fn = t["Resources"][_function_id(t, "cpaws-dev-ingest")]["Properties"]
    env = fn["Environment"]["Variables"]

    assert env["EIA_SECRET_ID"] == "/cpaws/dev/eia-api-key"

    role_id = fn["Role"]["Fn::GetAtt"][0]
    statements = _role_statements(t, role_id)
    eia_statements = [st for st in statements if "ssm:GetParameter" in st.get("Action", [])]

    assert len(eia_statements) == 1
    resource = eia_statements[0]["Resource"]
    assert isinstance(resource, dict)
    assert resource["Fn::Join"][1][-1] == ":parameter/cpaws/dev/eia-api-key"


@pytest.mark.parametrize("parameter_name", ["", " ", "\t"])
def test_empty_eia_parameter_name_is_rejected(parameter_name):
    with pytest.raises(ValueError, match="must not be empty"):
        _synth(eia_parameter_name=parameter_name)


def test_eia_parameter_arn_is_rejected():
    with pytest.raises(ValueError, match="not an ARN"):
        _synth(
            eia_parameter_name=(
                "arn:aws:ssm:ap-southeast-1:123456789012:parameter/cpaws/dev/eia-api-key"
            )
        )


def test_predict_role_has_no_ssm_permissions():
    t = _synth(eia_parameter_name="/cpaws/dev/eia-api-key")["data"]
    fn = t["Resources"][_function_id(t, "cpaws-dev-predict")]["Properties"]
    role_id = fn["Role"]["Fn::GetAtt"][0]

    for statement in _role_statements(t, role_id):
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        assert not any(action.startswith("ssm:") for action in actions)


# ---------- bảng NewsLabels (contract POST /chat, ADR-0003 mục 6) ----------


def _table(template: dict, table_name: str) -> dict:
    (table,) = [
        r
        for r in _resources(template, "AWS::DynamoDB::Table")
        if r["Properties"]["TableName"] == table_name
    ]
    return table


def test_news_labels_table_matches_contract(templates):
    sys.path.insert(0, str(INFRA_DIR))
    try:
        from stacks.shared import news_labels_table_name
    finally:
        sys.path.remove(str(INFRA_DIR))
    assert news_labels_table_name("dev") == "cpaws-dev-news-labels"
    table = _table(templates["serving"], "cpaws-dev-news-labels")
    props = table["Properties"]
    assert props["KeySchema"] == [
        {"AttributeName": "asset", "KeyType": "HASH"},
        {"AttributeName": "sk", "KeyType": "RANGE"},
    ]
    assert sorted(props["AttributeDefinitions"], key=lambda a: a["AttributeName"]) == [
        {"AttributeName": "asset", "AttributeType": "S"},
        {"AttributeName": "sk", "AttributeType": "S"},
    ]
    assert props["BillingMode"] == "PAY_PER_REQUEST"
    # không index, không stream: chỉ Query theo khóa chính
    assert "GlobalSecondaryIndexes" not in props and "LocalSecondaryIndexes" not in props
    assert "StreamSpecification" not in props
    assert table["DeletionPolicy"] == "Retain" and table["UpdateReplacePolicy"] == "Retain"


def test_forecasts_table_is_unchanged_by_news_labels(templates):
    tables = _items(templates["serving"], "AWS::DynamoDB::Table")
    assert len(tables) == 2
    forecasts = _table(templates["serving"], "cpaws-dev-forecasts")
    assert [k for k, r in tables.items() if r is forecasts][0].startswith("ForecastsTable")
    assert forecasts["Properties"]["KeySchema"] == [
        {"AttributeName": "asset", "KeyType": "HASH"},
        {"AttributeName": "base_date", "KeyType": "RANGE"},
    ]


def _news_policy(statement_fn) -> list[dict]:
    """Gắn statement vào một role thử trong stack riêng, trả về statement đã render."""
    sys.path.insert(0, str(INFRA_DIR))
    try:
        import aws_cdk as cdk
        from aws_cdk import aws_iam as iam
        from aws_cdk.assertions import Template
        from stacks import shared

        app = cdk.App()
        stack = cdk.Stack(app, "Probe")
        role = iam.Role(stack, "R", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        role.add_to_policy(getattr(shared, statement_fn)(stack, "dev"))
        t = Template.from_stack(stack).to_json()
        return [
            st
            for p in _resources(t, "AWS::IAM::Policy")
            for st in p["Properties"]["PolicyDocument"]["Statement"]
        ]
    finally:
        sys.path.remove(str(INFRA_DIR))


@pytest.mark.parametrize(
    "statement_fn,action",
    [
        ("news_labels_read_statement", "dynamodb:Query"),
        ("news_labels_write_statement", "dynamodb:PutItem"),
    ],
)
def test_news_labels_statements_are_least_privilege(statement_fn, action):
    (st,) = _news_policy(statement_fn)
    assert st["Effect"] == "Allow" and st["Action"] == action  # đúng một action
    resource = _render(st["Resource"])
    assert resource.endswith(":table/cpaws-dev-news-labels")  # đúng bảng, không index, không *
    assert "*" not in resource


def test_existing_lambdas_have_no_news_labels_access(templates):
    for name in ("data", "ops", "serving"):
        for p in _resources(templates[name], "AWS::IAM::Policy"):
            assert "news-labels" not in str(p["Properties"]["PolicyDocument"])

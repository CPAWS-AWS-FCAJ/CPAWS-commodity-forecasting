"""Kiểm tra hạ tầng `POST /chat`: asset Lambda, IAM, route, CORS, bảng chat-usage, alarm.

Đối chiếu contract `POST /chat` (mục "Tài nguyên và quyền IAM của Lambda chat") và docstring của
infra/lambda/chat_api/handler.py. Cần aws-cdk-lib (có trong infra\\.venv, không có trong CI) nên
tự bỏ qua khi thiếu. Chạy: infra\\.venv\\Scripts\\activate rồi
python -m pytest -q tests/test_infra_chat_api.py (từ gốc repo).
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk")

ROOT = Path(__file__).resolve().parents[1]
INFRA_DIR = ROOT / "infra"


def _infra():
    """Nạp các module trong infra/stacks (thư mục infra không phải package của repo)."""
    sys.path.insert(0, str(INFRA_DIR))
    try:
        from stacks import chat_asset, shared

        return chat_asset, shared
    finally:
        sys.path.remove(str(INFRA_DIR))


chat_asset, shared = _infra()


def _load_handler():
    spec = importlib.util.spec_from_file_location(
        "chat_handler_for_infra_test", ROOT / "infra" / "lambda" / "chat_api" / "handler.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def templates() -> dict:
    return _synth()


def _synth() -> dict:
    """Synth CpawsServing, CpawsAuth, CpawsApi và CpawsOps (có alarm chat) cho env dev."""
    sys.path.insert(0, str(INFRA_DIR))
    try:
        import aws_cdk as cdk
        from aws_cdk.assertions import Template
        from stacks.cpaws_api_stack import CpawsApiStack
        from stacks.cpaws_auth_stack import CpawsAuthStack
        from stacks.cpaws_ops_stack import CpawsOpsStack
        from stacks.cpaws_serving_stack import CpawsServingStack

        app = cdk.App()
        env = cdk.Environment(account="111111111111", region="ap-southeast-1")
        serving = CpawsServingStack(app, "CpawsServing", env_name="dev", env=env)
        auth = CpawsAuthStack(app, "CpawsAuth", env_name="dev", env=env)
        api = CpawsApiStack(
            app,
            "CpawsApi",
            env_name="dev",
            forecasts_table=serving.forecasts_table,
            user_pool=auth.user_pool,
            env=env,
        )
        ops = CpawsOpsStack(
            app,
            "CpawsOps",
            env_name="dev",
            ingest_function_name=shared.ingest_function_name("dev"),
            predict_function_name=shared.predict_function_name("dev"),
            chat_function_name=shared.chat_api_function_name("dev"),
            env=env,
        )
        return {
            "api": Template.from_stack(api).to_json(),
            "serving": Template.from_stack(serving).to_json(),
            "ops": Template.from_stack(ops).to_json(),
        }
    finally:
        sys.path.remove(str(INFRA_DIR))


def _items(template: dict, resource_type: str) -> dict[str, dict]:
    return {k: r for k, r in template["Resources"].items() if r["Type"] == resource_type}


def _function(template: dict, function_name: str) -> tuple[str, dict]:
    ((fid, fn),) = [
        (k, r)
        for k, r in _items(template, "AWS::Lambda::Function").items()
        if r["Properties"].get("FunctionName") == function_name
    ]
    return fid, fn


def _role_statements(template: dict, function_name: str) -> list[dict]:
    _, fn = _function(template, function_name)
    role_id = fn["Properties"]["Role"]["Fn::GetAtt"][0]
    return [
        st
        for p in _items(template, "AWS::IAM::Policy").values()
        if {"Ref": role_id} in p["Properties"]["Roles"]
        for st in p["Properties"]["PolicyDocument"]["Statement"]
    ]


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


# ---------- asset ----------


def test_chat_asset_has_exactly_the_documented_files(tmp_path):
    chat_asset.build_chat_asset(tmp_path)
    built = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert built == set(chat_asset.CHAT_ASSET_FILES)
    for dest, src in chat_asset.CHAT_ASSET_FILES.items():
        assert (tmp_path / dest).read_bytes() == (ROOT / src).read_bytes(), dest


def test_chat_asset_covers_every_module_prompt_and_news_file():
    sources = set(chat_asset.CHAT_ASSET_FILES.values())
    # Phước thêm module mới vào src/chatbot mà quên asset → Lambda lỗi import lúc chạy
    for module in (ROOT / "src" / "chatbot").glob("*.py"):
        assert module.relative_to(ROOT).as_posix() in sources, module.name
    handler = _load_handler()
    for prompt in handler.PROMPT_FILES.values():
        assert chat_asset.CHAT_ASSET_FILES[f"prompts/{prompt}"] == f"docs/prompts/{prompt}"
    for news in (ROOT / "infra" / "lambda" / "chat_api" / "news").glob("*.json"):
        assert chat_asset.CHAT_ASSET_FILES[f"news/{news.name}"] == news.relative_to(ROOT).as_posix()


def test_chat_asset_build_fails_loudly_on_missing_source(tmp_path, monkeypatch):
    files = dict(chat_asset.CHAT_ASSET_FILES)
    files["chatbot/extra.py"] = "src/chatbot/does_not_exist.py"
    monkeypatch.setattr(chat_asset, "CHAT_ASSET_FILES", files)
    with pytest.raises(FileNotFoundError, match="does_not_exist"):
        chat_asset.build_chat_asset(tmp_path)


def test_handler_runs_from_the_asset_alone(tmp_path):
    """Chạy trong tiến trình riêng, sys.path chỉ có thư mục asset (như /var/task): import phải lấy
    từ asset, không rơi vào nhánh `except ImportError` dành cho repo."""
    chat_asset.build_chat_asset(tmp_path)
    script = """
import json, os, sys
from pathlib import Path
asset = Path(sys.argv[1]).resolve()
# -I: sys.path không có thư mục hiện tại hay gốc repo, chỉ stdlib + site-packages (boto3)
sys.path.insert(0, str(asset))
os.environ["NEWS_DIR"] = str(asset / "news")
import handler
mods = [handler.chat_core, handler.news_tool, handler.quota_gate, handler.forecast_tool,
        handler.forecast_tool.FF]
inside = all(Path(m.__file__).resolve().is_relative_to(asset) for m in mods)
prompts = sorted(p.name for p in handler._prompt_dir().iterdir())
repo = handler.news_repository()
print(json.dumps({"inside": inside, "prompt_dir": str(handler._prompt_dir().resolve()),
                  "prompts": prompts, "news": type(repo).__name__}))
"""
    out = subprocess.run(
        [sys.executable, "-I", "-c", script, str(tmp_path)],
        capture_output=True,
        check=False,
        text=True,
        cwd=tmp_path,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["inside"] is True
    assert result["prompt_dir"] == str((tmp_path / "prompts").resolve())
    assert result["prompts"] == sorted(_load_handler().PROMPT_FILES.values())
    assert result["news"] == "JsonFileNewsRepository"


def test_lambda_assets_ignore_pycache():
    """Chạy test trên máy sinh __pycache__ trong infra/lambda/*: hash asset không được đổi, nếu
    không cdk diff báo đổi Code.S3Key của Lambda dù code không đổi (gặp 30/10)."""

    def code_keys() -> dict:
        api = _synth()["api"]
        return {
            name: _function(api, name)[1]["Properties"]["Code"]["S3Key"]
            for name in ("cpaws-dev-forecasts-api", "cpaws-dev-chat-api")
        }

    before = code_keys()
    created = []
    try:
        for folder in ("forecast_api", "chat_api"):
            cache = ROOT / "infra" / "lambda" / folder / "__pycache__"
            cache.mkdir(exist_ok=True)
            pyc = cache / "zz_infra_test_probe.cpython-311.pyc"
            pyc.write_bytes(b"probe")
            created.append(pyc)
        assert code_keys() == before
    finally:
        for pyc in created:
            pyc.unlink(missing_ok=True)


def test_bedrock_models_match_chatbot_model_ids():
    from src.chatbot import chat

    assert set(shared.CHAT_BEDROCK_MODELS.values()) == {
        model.removeprefix("global.") for model in chat.MODEL_IDS.values()
    }
    assert all(model.startswith("global.") for model in chat.MODEL_IDS.values())


# ---------- Lambda và IAM ----------


def test_chat_lambda_configuration(templates):
    _, fn = _function(templates["api"], "cpaws-dev-chat-api")
    props = fn["Properties"]
    assert props["Runtime"] == "python3.12"
    assert props["Handler"] == "handler.handler"
    assert props["Timeout"] == 28  # API Gateway cắt ở 29 giây
    variables = props["Environment"]["Variables"]
    assert set(variables) == {
        "FORECASTS_TABLE_NAME",
        "CHAT_USAGE_TABLE_NAME",
        "CHAT_USER_DAILY_LIMIT",
        "CHAT_GLOBAL_DAILY_LIMIT",
        "NEWS_DIR",
        "ALLOWED_ORIGIN",
    }
    assert variables["CHAT_USAGE_TABLE_NAME"] == shared.chat_usage_table_name("dev")
    assert variables["NEWS_DIR"] == "/var/task/news"
    assert variables["ALLOWED_ORIGIN"] == "http://localhost:5173"
    assert (variables["CHAT_USER_DAILY_LIMIT"], variables["CHAT_GLOBAL_DAILY_LIMIT"]) == (
        "20",
        "100",
    )
    # Không bật ghi nguyên văn câu hỏi, không gắn Guardrail chưa publish
    assert "LOG_QUESTIONS" not in variables and "GUARDRAIL_ID" not in variables


def test_chat_role_is_least_privilege(templates):
    statements = _role_statements(templates["api"], "cpaws-dev-chat-api")
    actions = {a for st in statements for a in _as_list(st["Action"])}
    assert actions == {
        "dynamodb:UpdateItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "bedrock:InvokeModel",
    }
    for st in statements:
        assert st["Effect"] == "Allow"
        assert "*" not in json.dumps(st["Resource"]), st.get("Sid")

    by_sid = {st["Sid"]: st for st in statements}
    usage = json.dumps(by_sid["ChatUsageCounter"]["Resource"])
    assert usage.endswith(':table/cpaws-dev-chat-usage"]]}')
    assert json.dumps(by_sid["NewsLabelsRead"]["Resource"]).endswith(
        ':table/cpaws-dev-news-labels"]]}'
    )
    assert "ForecastsTable" in json.dumps(by_sid["ForecastsRead"]["Resource"])


def test_bedrock_statements_follow_global_inference_requirements(templates):
    statements = [
        st
        for st in _role_statements(templates["api"], "cpaws-dev-chat-api")
        if st["Action"] == "bedrock:InvokeModel"
    ]
    assert len(statements) == 3 * len(shared.CHAT_BEDROCK_MODELS)
    for model in shared.CHAT_BEDROCK_MODELS.values():
        profile = f"arn:aws:bedrock:ap-southeast-1:111111111111:inference-profile/global.{model}"
        by_resource = {st["Resource"]: st["Condition"]["StringEquals"] for st in statements}
        assert by_resource[profile] == {"aws:RequestedRegion": "ap-southeast-1"}
        assert by_resource[f"arn:aws:bedrock:ap-southeast-1::foundation-model/{model}"] == {
            "aws:RequestedRegion": "ap-southeast-1",
            "bedrock:InferenceProfileArn": profile,
        }
        assert by_resource[f"arn:aws:bedrock:::foundation-model/{model}"] == {
            "aws:RequestedRegion": "unspecified",
            "bedrock:InferenceProfileArn": profile,
        }


def test_forecast_api_role_is_unchanged(templates):
    statements = _role_statements(templates["api"], "cpaws-dev-forecasts-api")
    actions = {a for st in statements for a in _as_list(st["Action"])}
    assert actions == {"dynamodb:Query"}
    assert "chat-usage" not in json.dumps(statements)
    assert "news-labels" not in json.dumps(statements)


# ---------- API Gateway ----------


def _method(template: dict, http_method: str, path_part: str) -> dict:
    resources = _items(template, "AWS::ApiGateway::Resource")
    ((rid, _),) = [(k, r) for k, r in resources.items() if r["Properties"]["PathPart"] == path_part]
    ((method,),) = [
        [
            m["Properties"]
            for m in _items(template, "AWS::ApiGateway::Method").values()
            if m["Properties"]["HttpMethod"] == http_method
            and m["Properties"]["ResourceId"] == {"Ref": rid}
        ]
    ]
    return method


def test_post_chat_requires_cognito_and_invokes_chat_lambda(templates):
    method = _method(templates["api"], "POST", "chat")
    assert method["AuthorizationType"] == "COGNITO_USER_POOLS"
    fid, _ = _function(templates["api"], "cpaws-dev-chat-api")
    assert fid in json.dumps(method["Integration"]["Uri"])
    assert method["Integration"]["Type"] == "AWS_PROXY"
    # Chỉ POST (và OPTIONS của CORS) trên /chat
    resources = _items(templates["api"], "AWS::ApiGateway::Resource")
    (rid,) = [k for k, r in resources.items() if r["Properties"]["PathPart"] == "chat"]
    verbs = {
        m["Properties"]["HttpMethod"]
        for m in _items(templates["api"], "AWS::ApiGateway::Method").values()
        if m["Properties"]["ResourceId"] == {"Ref": rid}
    }
    assert verbs == {"POST", "OPTIONS"}


def test_forecast_routes_keep_their_auth(templates):
    assert _method(templates["api"], "GET", "health")["AuthorizationType"] == "NONE"
    assert _method(templates["api"], "GET", "forecasts")["AuthorizationType"] == (
        "COGNITO_USER_POOLS"
    )
    assert _method(templates["api"], "GET", "{asset}")["AuthorizationType"] == (
        "COGNITO_USER_POOLS"
    )


def test_cors_allows_post(templates):
    for response in _items(templates["api"], "AWS::ApiGateway::GatewayResponse").values():
        headers = response["Properties"]["ResponseParameters"]
        assert headers["gatewayresponse.header.Access-Control-Allow-Methods"] == (
            "'GET,POST,OPTIONS'"
        )
    options = _method(templates["api"], "OPTIONS", "chat")
    (integration_response,) = options["Integration"]["IntegrationResponses"]
    allowed = integration_response["ResponseParameters"][
        "method.response.header.Access-Control-Allow-Methods"
    ]
    assert allowed == "'GET,POST,OPTIONS'"


# ---------- bảng chat-usage ----------


def test_chat_usage_table_matches_contract(templates):
    ((_, table),) = [
        (k, r)
        for k, r in _items(templates["serving"], "AWS::DynamoDB::Table").items()
        if r["Properties"]["TableName"] == shared.chat_usage_table_name("dev")
    ]
    props = table["Properties"]
    assert props["KeySchema"] == [
        {"AttributeName": "pk", "KeyType": "HASH"},
        {"AttributeName": "sk", "KeyType": "RANGE"},
    ]
    assert props["BillingMode"] == "PAY_PER_REQUEST"
    assert props["TimeToLiveSpecification"] == {"AttributeName": "expires_at", "Enabled": True}
    assert "GlobalSecondaryIndexes" not in props and "StreamSpecification" not in props
    assert table["DeletionPolicy"] == "Delete"  # chỉ là bộ đếm


def test_chat_usage_is_not_exported_across_stacks(templates):
    """Lambda chat dựng ARN theo tên: CpawsApi không import gì của bảng chat-usage."""
    outputs = templates["serving"].get("Outputs", {})
    for name, output in outputs.items():
        if "ChatUsage" in name:
            assert "Export" not in output


# ---------- alarm ----------


def test_chat_alarms_watch_chat_lambda_and_internal_error_metric(templates):
    alarms = {
        r["Properties"]["AlarmName"]: r["Properties"]
        for r in _items(templates["ops"], "AWS::CloudWatch::Alarm").values()
    }
    errors = alarms["cpaws-dev-chat-api-errors"]
    assert errors["Namespace"] == "AWS/Lambda" and errors["MetricName"] == "Errors"
    assert errors["Dimensions"] == [{"Name": "FunctionName", "Value": "cpaws-dev-chat-api"}]
    internal = alarms["cpaws-dev-chat-api-internal-errors"]
    assert internal["Namespace"] == shared.CHAT_METRIC_NAMESPACE
    assert internal["MetricName"] == shared.CHAT_INTERNAL_ERRORS_METRIC
    for alarm in (errors, internal):
        assert alarm["Threshold"] == 1 and alarm["TreatMissingData"] == "notBreaching"
        assert alarm["AlarmActions"]  # gửi SNS

    ((metric_filter,),) = [list(_items(templates["api"], "AWS::Logs::MetricFilter").values())]
    (transform,) = metric_filter["Properties"]["MetricTransformations"]
    assert transform["MetricNamespace"] == shared.CHAT_METRIC_NAMESPACE
    assert transform["MetricName"] == shared.CHAT_INTERNAL_ERRORS_METRIC


def test_internal_error_log_terms_exist_in_handler():
    """Đổi câu log trong handler mà quên shared.py → metric filter không bao giờ khớp."""
    source = (ROOT / "infra" / "lambda" / "chat_api" / "handler.py").read_text(encoding="utf-8")
    for term in shared.CHAT_INTERNAL_ERROR_LOG_TERMS:
        assert f'"{term}' in source, term

"""Hằng dùng chung giữa các stack, để tên tài nguyên và lịch không bị lệch nhau."""

from aws_cdk import Stack
from aws_cdk import aws_iam as iam

# Phải KHỚP INGEST_SCHEDULE_EXPRESSION trong src/data/config.py (tests/test_infra_stacks.py kiểm tra).
# 12:15 UTC thứ Ba-thứ Bảy = 19:15 giờ VN, sau mốc công bố D+1 12:00 UTC của yfinance.
INGEST_SCHEDULE_EXPRESSION = "cron(15 12 ? * TUE-SAT *)"

# Schedule group chứa lịch ingest. Role Scheduler giới hạn aws:SourceArn theo ARN của group này
# (AWS yêu cầu ARN của schedule group, không phải của từng schedule); schedule phải đặt group_name
# bằng cùng giá trị, nếu lệch thì Scheduler không assume được role.
INGEST_SCHEDULE_GROUP = "default"


def ingest_function_name(env_name: str) -> str:
    """Tên Lambda ingest. CpawsData đặt function_name và log group theo tên này, CpawsOps dùng nó
    cho dimension của alarm; lệch tên thì alarm theo dõi metric không tồn tại và luôn OK."""
    return f"cpaws-{env_name}-ingest"


def predict_function_name(env_name: str) -> str:
    """Tên Lambda predict. CpawsData đặt function_name và log group theo tên này, CpawsOps dùng nó
    cho dimension của alarm (giống ingest_function_name)."""
    return f"cpaws-{env_name}-predict"


def forecasts_table_name(env_name: str) -> str:
    """Tên bảng DynamoDB Forecasts. Phải KHỚP table_name trong cpaws_serving_stack.py
    (tests/test_infra_stacks.py kiểm tra). CpawsData tham chiếu bảng theo tên thay vì export
    chéo stack, để không khóa CpawsServing khi sau này đổi bảng."""
    return f"cpaws-{env_name}-forecasts"


def news_labels_table_name(env_name: str) -> str:
    """Tên bảng DynamoDB NewsLabels (contract POST /chat, ADR-0003 mục 6). Phải KHỚP table_name
    trong cpaws_serving_stack.py (tests/test_infra_stacks.py kiểm tra). Lambda collector tin (ghi)
    và Lambda /chat (đọc) dựng ARN từ tên này, không export chéo stack."""
    return f"cpaws-{env_name}-news-labels"


def _news_labels_table_arn(stack: Stack, env_name: str) -> str:
    return stack.format_arn(
        service="dynamodb", resource="table", resource_name=news_labels_table_name(env_name)
    )


def news_labels_read_statement(stack: Stack, env_name: str) -> iam.PolicyStatement:
    """Quyền tối thiểu cho Lambda /chat (tool get_news): chỉ Query trên đúng bảng; không Scan,
    GetItem hay index (bảng không có index)."""
    return iam.PolicyStatement(
        sid="NewsLabelsRead",
        actions=["dynamodb:Query"],
        resources=[_news_labels_table_arn(stack, env_name)],
    )


def news_labels_write_statement(stack: Stack, env_name: str) -> iam.PolicyStatement:
    """Quyền tối thiểu cho collector tin: chỉ PutItem trên đúng bảng. Ghi lại cùng
    (asset, sk) thì ghi đè item cũ, nên không cần UpdateItem hay DeleteItem."""
    return iam.PolicyStatement(
        sid="NewsLabelsWrite",
        actions=["dynamodb:PutItem"],
        resources=[_news_labels_table_arn(stack, env_name)],
    )


# ---------- Lambda POST /chat (contract POST /chat, mục "Tài nguyên và quyền IAM") ----------


def chat_api_function_name(env_name: str) -> str:
    """Tên Lambda /chat. CpawsApi đặt function_name theo tên này, CpawsOps dùng nó cho dimension
    của alarm (giống ingest_function_name)."""
    return f"cpaws-{env_name}-chat-api"


def chat_usage_table_name(env_name: str) -> str:
    """Tên bảng đếm lượt hỏi chat-usage. Phải KHỚP table_name trong cpaws_serving_stack.py
    (tests/test_infra_chat_api.py kiểm tra). Lambda /chat dựng ARN từ tên này, không export chéo
    stack, nên phải deploy CpawsServing trước CpawsApi."""
    return f"cpaws-{env_name}-chat-usage"


# Metric từ log lỗi không lường trước của Lambda /chat. Handler bắt mọi exception và trả 500, nên
# metric Errors của Lambda chỉ đếm timeout/crash; metric này đếm phần còn lại. CpawsApi tạo
# metric filter, CpawsOps tạo alarm theo đúng namespace + tên này.
CHAT_METRIC_NAMESPACE = "CPAWS"
CHAT_INTERNAL_ERRORS_METRIC = "ChatInternalErrors"
# Hai câu log của infra/lambda/chat_api/handler.py khi lỗi không lường trước (logger.exception)
CHAT_INTERNAL_ERROR_LOG_TERMS = (
    "chat: unexpected error",
    "chat: cannot initialise dependencies",
)

# Model gọi qua global cross-Region inference profile. Phải KHỚP MODEL_IDS trong
# src/chatbot/chat.py bỏ tiền tố "global." (tests/test_infra_chat_api.py kiểm tra).
CHAT_BEDROCK_MODELS = {
    "Nova": "amazon.nova-2-lite-v1:0",
    "Haiku": "anthropic.claude-haiku-4-5-20251001-v1:0",
}


def bedrock_global_invoke_statements(stack: Stack) -> list[iam.PolicyStatement]:
    """bedrock:InvokeModel cho mỗi model trong CHAT_BEDROCK_MODELS, đủ 3 statement theo tài liệu
    "Global cross-Region inference" (mục IAM policy requirements); thiếu một là AccessDenied:
    1. inference profile global trong Region gọi;
    2. foundation model trong Region gọi, chỉ khi gọi qua profile đó;
    3. foundation model global (ARN không Region, không Account), RequestedRegion = unspecified.
    Converse chỉ cần bedrock:InvokeModel; không cấp InvokeModelWithResponseStream."""
    region, account = stack.region, stack.account
    statements = []
    for key, model in CHAT_BEDROCK_MODELS.items():
        profile_arn = f"arn:aws:bedrock:{region}:{account}:inference-profile/global.{model}"
        statements += [
            iam.PolicyStatement(
                sid=f"Bedrock{key}InferenceProfile",
                actions=["bedrock:InvokeModel"],
                resources=[profile_arn],
                conditions={"StringEquals": {"aws:RequestedRegion": region}},
            ),
            iam.PolicyStatement(
                sid=f"Bedrock{key}RegionalModel",
                actions=["bedrock:InvokeModel"],
                resources=[f"arn:aws:bedrock:{region}::foundation-model/{model}"],
                conditions={
                    "StringEquals": {
                        "aws:RequestedRegion": region,
                        "bedrock:InferenceProfileArn": profile_arn,
                    }
                },
            ),
            iam.PolicyStatement(
                sid=f"Bedrock{key}GlobalModel",
                actions=["bedrock:InvokeModel"],
                resources=[f"arn:aws:bedrock:::foundation-model/{model}"],
                conditions={
                    "StringEquals": {
                        "aws:RequestedRegion": "unspecified",
                        "bedrock:InferenceProfileArn": profile_arn,
                    }
                },
            ),
        ]
    return statements

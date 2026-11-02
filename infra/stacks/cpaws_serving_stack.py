"""CDK stack for the CPAWS serving DynamoDB tables (Forecasts, NewsLabels, ChatUsage)."""

from typing import Any

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from constructs import Construct

from .shared import chat_usage_table_name, news_labels_table_name


class CpawsServingStack(Stack):
    """Create the Forecasts table (prediction pipeline), the NewsLabels table (chatbot news) and
    the ChatUsage table (chatbot daily quota)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.forecasts_table = dynamodb.Table(
            self,
            "ForecastsTable",
            table_name=f"cpaws-{env_name}-forecasts",
            partition_key=dynamodb.Attribute(
                name="asset",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="base_date",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        CfnOutput(
            self,
            "ForecastsTableName",
            value=self.forecasts_table.table_name,
        )

        CfnOutput(
            self,
            "ForecastsTableArn",
            value=self.forecasts_table.table_arn,
        )

        # Nhãn tin đã gắn cho từng tài sản (contract POST /chat, mục "Nguồn dữ liệu của tool
        # get_news"; ADR-0003 mục 6). Collector tin ghi (PutItem), Lambda /chat đọc (Query).
        # Quyền tối thiểu: shared.news_labels_read_statement / news_labels_write_statement.
        # Item: PK asset, SK sk = "<published_at>#<article_id>", bắt buộc title, summary, link,
        # source, published_at, impact_score (Number 0-3), direction. On-demand: vài chục tin/ngày,
        # chi phí gần 0. RETAIN vì nhãn tốn tiền Bedrock để tạo lại.
        self.news_labels_table = dynamodb.Table(
            self,
            "NewsLabelsTable",
            table_name=news_labels_table_name(env_name),
            partition_key=dynamodb.Attribute(
                name="asset",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        CfnOutput(
            self,
            "NewsLabelsTableName",
            value=self.news_labels_table.table_name,
        )

        # Bộ đếm lượt hỏi chatbot (contract POST /chat, mục giới hạn lượt hỏi):
        # PK pk = "user#<sub>" hoặc "global", SK sk = "day#YYYY-MM-DD" (giờ VN).
        # TTL trên expires_at chỉ để dọn dữ liệu cũ; reset theo ngày dựa vào sk.
        # Không lưu câu hỏi/câu trả lời. DESTROY: chỉ là bộ đếm, mất cũng không sao
        # (khác Forecasts, NewsLabels).
        self.chat_usage_table = dynamodb.Table(
            self,
            "ChatUsageTable",
            table_name=chat_usage_table_name(env_name),
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.DESTROY,
        )

        CfnOutput(
            self,
            "ChatUsageTableName",
            value=self.chat_usage_table.table_name,
        )

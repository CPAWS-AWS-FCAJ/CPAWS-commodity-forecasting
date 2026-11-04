"""CDK stack for the CPAWS serving DynamoDB tables."""

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

from .shared import (
    accuracy_table_name,
    chat_usage_table_name,
    news_labels_table_name,
)


class CpawsServingStack(Stack):
    """Create the Forecasts, NewsLabels, ChatUsage and Accuracy tables."""

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

        # Nhãn tin đã gắn cho từng tài sản (contract POST /chat).
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

        # Bộ đếm lượt hỏi chatbot. TTL chỉ áp dụng cho ChatUsage.
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

        # Rolling Accuracy: STATE và RUN/META/METRIC dùng chung pk/sk.
        # Không GSI, không TTL; giữ dữ liệu khi stack bị xóa.
        self.accuracy_table = dynamodb.Table(
            self,
            "AccuracyTable",
            table_name=accuracy_table_name(env_name),
            partition_key=dynamodb.Attribute(
                name="pk",
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
            "AccuracyTableName",
            value=self.accuracy_table.table_name,
        )

        CfnOutput(
            self,
            "AccuracyTableArn",
            value=self.accuracy_table.table_arn,
        )

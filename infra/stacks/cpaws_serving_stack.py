"""CDK stack for the CPAWS Forecasts DynamoDB table."""

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


class CpawsServingStack(Stack):
    """Create the Forecasts table used by the prediction pipeline."""

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

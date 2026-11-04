"""CDK stack for the CPAWS REST API: forecasts, accuracy and chatbot endpoints."""

import json
from pathlib import Path
from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from .chat_asset import chat_asset_code
from .shared import (
    CHAT_INTERNAL_ERROR_LOG_TERMS,
    CHAT_INTERNAL_ERRORS_METRIC,
    CHAT_METRIC_NAMESPACE,
    accuracy_api_function_name,
    accuracy_table_name,
    bedrock_global_invoke_statements,
    chat_api_function_name,
    chat_usage_table_name,
    news_labels_read_statement,
)


class CpawsApiStack(Stack):
    """Create forecast, accuracy and chatbot APIs backed by Lambda and AWS services."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        forecasts_table: dynamodb.ITable,
        user_pool: cognito.IUserPool,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Local development defaults to localhost.
        # Override with -c allowed_origin=https://your-frontend-domain for deployment.
        allowed_origin = self.node.try_get_context("allowed_origin") or "http://localhost:5173"

        # ---------- Forecasts API ----------
        handler_dir = Path(__file__).resolve().parents[1] / "lambda" / "forecast_api"

        forecast_api_log_group = logs.LogGroup(
            self,
            "ForecastsApiLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.RETAIN,
        )

        forecast_api_lambda = lambda_.Function(
            self,
            "ForecastsApiHandler",
            function_name=f"cpaws-{env_name}-forecasts-api",
            description="Read CPAWS forecast records from DynamoDB",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            # Exclude local Python cache files to keep the CDK asset hash stable.
            code=lambda_.Code.from_asset(str(handler_dir), exclude=["__pycache__", "*.pyc"]),
            timeout=Duration.seconds(10),
            memory_size=256,
            log_group=forecast_api_log_group,
            environment={
                "FORECASTS_TABLE_NAME": forecasts_table.table_name,
                "ALLOWED_ORIGIN": allowed_origin,
            },
        )

        forecast_api_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Query"],
                resources=[forecasts_table.table_arn],
            )
        )

        # ---------- REST API and CORS ----------
        cors_origins = apigateway.Cors.ALL_ORIGINS if allowed_origin == "*" else [allowed_origin]

        api = apigateway.RestApi(
            self,
            "ForecastsRestApi",
            rest_api_name=f"cpaws-{env_name}-forecasts-api",
            description="CPAWS forecast, rolling accuracy and chatbot API",
            deploy_options=apigateway.StageOptions(
                stage_name=env_name,
                throttling_rate_limit=10,
                throttling_burst_limit=20,
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=cors_origins,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        gateway_cors_headers = {
            "Access-Control-Allow-Origin": f"'{allowed_origin}'",
            "Access-Control-Allow-Headers": "'Content-Type,Authorization'",
            "Access-Control-Allow-Methods": "'GET,POST,OPTIONS'",
        }

        apigateway.GatewayResponse(
            self,
            "Default4xxCors",
            rest_api=api,
            type=apigateway.ResponseType.DEFAULT_4_XX,
            response_headers=gateway_cors_headers,
        )

        apigateway.GatewayResponse(
            self,
            "Default5xxCors",
            rest_api=api,
            type=apigateway.ResponseType.DEFAULT_5_XX,
            response_headers=gateway_cors_headers,
        )

        # ---------- Cognito authorizer ----------
        authorizer = apigateway.CognitoUserPoolsAuthorizer(
            self,
            "ForecastsAuthorizer",
            cognito_user_pools=[user_pool],
            identity_source="method.request.header.Authorization",
        )

        # GET /health is public and does not require authentication.
        forecast_integration = apigateway.LambdaIntegration(
            forecast_api_lambda,
            proxy=True,
        )

        api.root.add_resource("health").add_method(
            "GET",
            forecast_integration,
            authorization_type=apigateway.AuthorizationType.NONE,
        )

        # GET /forecasts and GET /forecasts/{asset} require Cognito.
        forecast_resource = api.root.add_resource("forecasts")

        forecast_resource.add_method(
            "GET",
            forecast_integration,
            authorization_type=apigateway.AuthorizationType.COGNITO,
            authorizer=authorizer,
        )

        asset_resource = forecast_resource.add_resource("{asset}")

        asset_resource.add_method(
            "GET",
            forecast_integration,
            authorization_type=apigateway.AuthorizationType.COGNITO,
            authorizer=authorizer,
            request_parameters={
                "method.request.path.asset": True,
                "method.request.querystring.date": False,
            },
        )

        # ---------- Rolling Accuracy API ----------
        # Reader Lambda is isolated from Forecasts and Chat. It receives only the Accuracy
        # table name and current champion/effective-date mappings.
        accuracy_handler_dir = Path(__file__).resolve().parents[1] / "lambda" / "accuracy_api"

        model_versions = {
            "gold": "baseline-q252",
            "silver": "baseline-q252",
            "brent": "baseline-q252",
            "wti": "baseline-q252",
        }

        champion_effective_base_dates = {
            "gold": "2026-10-26",
            "silver": "2026-10-26",
            "brent": "2026-10-26",
            "wti": "2026-10-26",
        }

        accuracy_log_group = logs.LogGroup(
            self,
            "AccuracyApiLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.RETAIN,
        )

        accuracy_lambda = lambda_.Function(
            self,
            "AccuracyApiHandler",
            function_name=accuracy_api_function_name(env_name),
            description="Read and validate CPAWS rolling accuracy results",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                str(accuracy_handler_dir),
                exclude=["__pycache__", "*.pyc"],
            ),
            timeout=Duration.seconds(10),
            memory_size=256,
            log_group=accuracy_log_group,
            environment={
                "ACCURACY_TABLE_NAME": accuracy_table_name(env_name),
                "MODEL_VERSIONS": json.dumps(model_versions),
                "CHAMPION_EFFECTIVE_BASE_DATES": json.dumps(champion_effective_base_dates),
                "ALLOWED_ORIGIN": allowed_origin,
            },
        )

        # Least privilege: the Accuracy Reader can only read the exact Accuracy table.
        accuracy_table_arn = self.format_arn(
            service="dynamodb",
            resource="table",
            resource_name=accuracy_table_name(env_name),
        )

        accuracy_lambda.add_to_role_policy(
            iam.PolicyStatement(
                sid="AccuracyReadOnly",
                actions=["dynamodb:GetItem", "dynamodb:Query"],
                resources=[accuracy_table_arn],
            )
        )

        accuracy_resource = api.root.add_resource("accuracy")
        accuracy_asset_resource = accuracy_resource.add_resource("{asset}")

        accuracy_asset_resource.add_method(
            "GET",
            apigateway.LambdaIntegration(accuracy_lambda, proxy=True),
            authorization_type=apigateway.AuthorizationType.COGNITO,
            authorizer=authorizer,
            request_parameters={
                "method.request.path.asset": True,
            },
        )

        CfnOutput(
            self,
            "AccuracyApiFunctionName",
            value=accuracy_lambda.function_name,
        )

        # ---------- POST /chat ----------
        chat_log_group = logs.LogGroup(
            self,
            "ChatApiLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Timeout 28 seconds: API Gateway cuts off at 29 seconds.
        chat_lambda = lambda_.Function(
            self,
            "ChatApiHandler",
            function_name=chat_api_function_name(env_name),
            description="CPAWS chatbot: Bedrock Converse with forecast and news tools",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=chat_asset_code(),
            timeout=Duration.seconds(28),
            memory_size=512,
            log_group=chat_log_group,
            environment={
                "FORECASTS_TABLE_NAME": forecasts_table.table_name,
                "CHAT_USAGE_TABLE_NAME": chat_usage_table_name(env_name),
                "CHAT_USER_DAILY_LIMIT": "20",
                "CHAT_GLOBAL_DAILY_LIMIT": "100",
                "NEWS_DIR": "/var/task/news",
                "ALLOWED_ORIGIN": allowed_origin,
            },
        )

        chat_lambda.add_to_role_policy(
            iam.PolicyStatement(
                sid="ChatUsageCounter",
                actions=["dynamodb:UpdateItem", "dynamodb:GetItem"],
                resources=[
                    self.format_arn(
                        service="dynamodb",
                        resource="table",
                        resource_name=chat_usage_table_name(env_name),
                    )
                ],
            )
        )

        chat_lambda.add_to_role_policy(
            iam.PolicyStatement(
                sid="ForecastsRead",
                actions=["dynamodb:Query"],
                resources=[forecasts_table.table_arn],
            )
        )

        chat_lambda.add_to_role_policy(news_labels_read_statement(self, env_name))

        for statement in bedrock_global_invoke_statements(self):
            chat_lambda.add_to_role_policy(statement)

        logs.MetricFilter(
            self,
            "ChatInternalErrorsFilter",
            log_group=chat_log_group,
            metric_namespace=CHAT_METRIC_NAMESPACE,
            metric_name=CHAT_INTERNAL_ERRORS_METRIC,
            metric_value="1",
            filter_pattern=logs.FilterPattern.literal(
                " ".join(f'?"{term}"' for term in CHAT_INTERNAL_ERROR_LOG_TERMS)
            ),
        )

        api.root.add_resource("chat").add_method(
            "POST",
            apigateway.LambdaIntegration(chat_lambda, proxy=True),
            authorization_type=apigateway.AuthorizationType.COGNITO,
            authorizer=authorizer,
        )

        CfnOutput(
            self,
            "ForecastsApiUrl",
            value=api.url,
        )

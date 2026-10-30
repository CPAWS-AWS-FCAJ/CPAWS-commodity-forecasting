"""CDK stack for the CPAWS REST API: forecast read endpoints and POST /chat."""

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
    bedrock_global_invoke_statements,
    chat_api_function_name,
    chat_usage_table_name,
    news_labels_read_statement,
)


class CpawsApiStack(Stack):
    """Create the forecast API and the chatbot endpoint, backed by Lambda, DynamoDB and Bedrock."""

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
            # Bỏ __pycache__/.pyc sinh ra khi chạy test trên máy: chúng làm đổi hash asset và
            # khiến cdk diff báo đổi Code.S3Key dù code không đổi.
            code=lambda_.Code.from_asset(str(handler_dir), exclude=["__pycache__", "*.pyc"]),
            timeout=Duration.seconds(10),
            memory_size=256,
            log_group=forecast_api_log_group,
            environment={
                "FORECASTS_TABLE_NAME": forecasts_table.table_name,
                "ALLOWED_ORIGIN": allowed_origin,
            },
        )

        # The API Lambda only needs Query permission on the forecasts table.
        forecast_api_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Query"],
                resources=[forecasts_table.table_arn],
            )
        )

        cors_origins = apigateway.Cors.ALL_ORIGINS if allowed_origin == "*" else [allowed_origin]

        api = apigateway.RestApi(
            self,
            "ForecastsRestApi",
            rest_api_name=f"cpaws-{env_name}-forecasts-api",
            description="CPAWS forecast read API",
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

        # Add CORS headers to API Gateway-generated 4xx and 5xx errors,
        # including requests rejected by the Cognito authorizer.
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

        integration = apigateway.LambdaIntegration(
            forecast_api_lambda,
            proxy=True,
        )

        # GET /health is public and does not require authentication.
        api.root.add_resource("health").add_method(
            "GET",
            integration,
            authorization_type=apigateway.AuthorizationType.NONE,
        )

        # Forecast endpoints require a Cognito user-pool token.
        authorizer = apigateway.CognitoUserPoolsAuthorizer(
            self,
            "ForecastsAuthorizer",
            cognito_user_pools=[user_pool],
            identity_source="method.request.header.Authorization",
        )

        forecast_resource = api.root.add_resource("forecasts")

        forecast_resource.add_method(
            "GET",
            integration,
            authorization_type=apigateway.AuthorizationType.COGNITO,
            authorizer=authorizer,
        )

        asset_resource = forecast_resource.add_resource("{asset}")

        asset_resource.add_method(
            "GET",
            integration,
            authorization_type=apigateway.AuthorizationType.COGNITO,
            authorizer=authorizer,
            request_parameters={
                "method.request.path.asset": True,
                "method.request.querystring.date": False,
            },
        )

        # ---------- POST /chat (contract POST /chat, PR #41, #55) ----------
        chat_log_group = logs.LogGroup(
            self,
            "ChatApiLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Timeout 28 giây: API Gateway cắt ở 29 giây; handler tự trả 504 trước hạn chót tính từ
        # requestTimeEpoch. Không đặt NEWS_TABLE_NAME: bảng NewsLabels chưa có collector, demo đọc
        # tin gắn nhãn tay trong asset (docs/api/demo-news.md).
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

        # Quyền tối thiểu theo bảng quyền trong contract; mỗi quyền trên đúng ARN, không "*".
        chat_lambda.add_to_role_policy(
            iam.PolicyStatement(
                sid="ChatUsageCounter",
                # TransactWriteItems kiểm quyền UpdateItem cho từng Update; GetItem đọc lại số lượt
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

        # Handler bắt mọi exception và trả 500, nên đếm lỗi không lường trước từ log;
        # alarm ở CpawsOps (cùng namespace + tên metric trong shared.py).
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

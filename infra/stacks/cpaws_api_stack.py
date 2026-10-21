"""CDK stack for the CPAWS forecast REST API."""

from pathlib import Path
from typing import Any

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import (
    aws_apigateway as apigateway,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from constructs import Construct


class CpawsApiStack(Stack):
    """Create the forecast API backed by Lambda and DynamoDB."""

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

        handler_dir = (
            Path(__file__).resolve().parents[1]
            / "lambda"
            / "forecast_api"
        )

        forecast_api_lambda = lambda_.Function(
            self,
            "ForecastsApiHandler",
            function_name=f"cpaws-{env_name}-forecasts-api",
            description="Read CPAWS forecast records from DynamoDB",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(handler_dir)),
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "FORECASTS_TABLE_NAME": forecasts_table.table_name,
            },
        )

        # API Lambda chỉ được Query bảng Forecasts.
        forecast_api_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Query"],
                resources=[forecasts_table.table_arn],
            )
        )

        api = apigateway.RestApi(
            self,
            "ForecastsRestApi",
            rest_api_name=f"cpaws-{env_name}-forecasts-api",
            description="CPAWS forecast read API",
            deploy_options=apigateway.StageOptions(
                stage_name=env_name,
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=["GET", "OPTIONS"],
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                ],
            ),
        )

        integration = apigateway.LambdaIntegration(
            forecast_api_lambda,
            proxy=True,
        )

        # GET /health không cần đăng nhập.
        api.root.add_resource("health").add_method(
            "GET",
            integration,
            authorization_type=apigateway.AuthorizationType.NONE,
        )

        # Các endpoint forecast yêu cầu Cognito ID token.
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

        CfnOutput(
            self,
            "ForecastsApiUrl",
            value=api.url,
        )

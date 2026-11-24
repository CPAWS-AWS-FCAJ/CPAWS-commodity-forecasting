from typing import Any

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from constructs import Construct


class CpawsAuthStack(Stack):
    """Create a Cognito User Pool and a public SPA app client."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.user_pool = cognito.UserPool(
            self,
            "ForecastsUserPool",
            user_pool_name=f"cpaws-{env_name}-users",
            self_sign_up_enabled=True,
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=True,
                require_lowercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=Duration.days(7),
            ),
            user_verification=cognito.UserVerificationConfig(
                email_style=cognito.VerificationEmailStyle.CODE,
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.user_pool_client = self.user_pool.add_client(
            "ForecastsAppClient",
            user_pool_client_name=f"cpaws-{env_name}-app",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            disable_o_auth=True,
            generate_secret=False,
            prevent_user_existence_errors=True,
        )

        CfnOutput(
            self,
            "ForecastsUserPoolId",
            value=self.user_pool.user_pool_id,
        )

        CfnOutput(
            self,
            "ForecastsUserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
        )

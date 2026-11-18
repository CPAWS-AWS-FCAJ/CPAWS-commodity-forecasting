"""Tests for the CPAWS Cognito authentication stack."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("aws_cdk")

ROOT = Path(__file__).resolve().parents[1]
INFRA_DIR = ROOT / "infra"


def test_auth_stack_self_signup_and_email_verification():
    sys.path.insert(0, str(INFRA_DIR))
    try:
        import aws_cdk as cdk
        from aws_cdk import assertions
        from stacks.cpaws_auth_stack import CpawsAuthStack

        app = cdk.App()
        stack = CpawsAuthStack(app, "CpawsAuth", env_name="dev")
        template = assertions.Template.from_stack(stack)

        template.has_resource_properties(
            "AWS::Cognito::UserPool",
            {
                "AdminCreateUserConfig": {
                    "AllowAdminCreateUserOnly": False,
                },
                "AutoVerifiedAttributes": ["email"],
                "Policies": {
                    "PasswordPolicy": {
                        "MinimumLength": 8,
                        "RequireUppercase": True,
                        "RequireLowercase": True,
                        "RequireNumbers": True,
                        "RequireSymbols": True,
                        "TemporaryPasswordValidityDays": 7,
                    }
                },
                "VerificationMessageTemplate": {
                    "DefaultEmailOption": "CONFIRM_WITH_CODE",
                },
            },
        )

        template.has_resource_properties(
            "AWS::Cognito::UserPoolClient",
            {
                "GenerateSecret": False,
                "ExplicitAuthFlows": assertions.Match.array_with(
                    ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_USER_SRP_AUTH"]
                ),
            },
        )
    finally:
        sys.path.remove(str(INFRA_DIR))

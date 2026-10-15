"""Stack CpawsData: S3 data lake và ECR cho Lambda ingest."""

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_s3 as s3
from constructs import Construct


class CpawsDataStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, env_name: str, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Data lake: raw/ clean/ features/ kb/ models/ (xem skill aws-serverless-platform)
        self.lake = s3.Bucket(
            self,
            "Lake",
            bucket_name=f"cpaws-{env_name}-lake",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            # Giữ dữ liệu khi xóa stack, tránh mất data vì lỡ tay
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-versions",
                    noncurrent_version_expiration=Duration.days(30),
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                )
            ],
        )

        # ECR cho container Lambda ingest (Khải đẩy image lên).
        # Tên repo: chờ Khải xác nhận, đổi ở đây nếu khác.
        self.ingest_repo = ecr.Repository(
            self,
            "IngestRepo",
            repository_name=f"cpaws-{env_name}-ingest",
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=5, description="Giữ 5 image mới nhất")
            ],
        )

        CfnOutput(self, "LakeBucketName", value=self.lake.bucket_name)
        CfnOutput(self, "IngestRepoUri", value=self.ingest_repo.repository_uri)

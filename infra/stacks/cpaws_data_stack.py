"""Stack CpawsData: S3 data lake, ECR và Lambda ingest."""

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct


class CpawsDataStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        ingest_image_tag: str,
        **kwargs: Any,
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

        # Prod giữ repo và image khi xóa stack; dev dọn sạch sau buổi bảo vệ (góp ý của Khải, PR #5).
        is_prod = env_name == "prod"

        # ECR cho container Lambda ingest (Khải đẩy image lên).
        # Tên repo và việc giữ 5 image đã được Khải xác nhận (15/10).
        self.ingest_repo = ecr.Repository(
            self,
            "IngestRepo",
            repository_name=f"cpaws-{env_name}-ingest",
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            empty_on_delete=not is_prod,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=5, description="Giu 5 image moi nhat")
            ],
        )

        # Execution role của Lambda ingest, quyền tối thiểu theo
        # docs/handoff/ingest-lambda.md (mục "Quyền IAM tối thiểu"). Tuấn review.
        # Chưa có quyền đọc secret EIA: thêm khi nhóm chọn nơi lưu key.
        ingest_role = iam.Role(
            self,
            "IngestRole",
            role_name=f"cpaws-{env_name}-ingest-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        # Chỉ đọc/ghi raw/ và clean/, không có Delete, không đụng features/
        ingest_role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeReadWriteRawClean",
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[
                    self.lake.arn_for_objects("raw/*"),
                    self.lake.arn_for_objects("clean/*"),
                ],
            )
        )
        # Code dùng ListObjectsV2 để tìm dt= mới nhất và kiểm tra file tồn tại
        ingest_role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeListRawClean",
                actions=["s3:ListBucket"],
                resources=[self.lake.bucket_arn],
                conditions={"StringLike": {"s3:prefix": ["raw/*", "clean/*"]}},
            )
        )

        # Log giữ 30 ngày (aws-cost-guard: retention 14-30 ngày)
        ingest_log_group = logs.LogGroup(
            self,
            "IngestLogGroup",
            log_group_name=f"/aws/lambda/cpaws-{env_name}-ingest",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Lambda từ image trong ECR: x86_64, 1.024 MB, timeout 300 s, ngoài VPC.
        # Chưa có Scheduler: chạy dry_run trước, bật lịch sau khi Khải xác nhận.
        self.ingest_fn = lambda_.DockerImageFunction(
            self,
            "IngestFunction",
            function_name=f"cpaws-{env_name}-ingest",
            description="Daily price ingest (yfinance) writing raw/clean to the CPAWS lake",
            code=lambda_.DockerImageCode.from_ecr(self.ingest_repo, tag_or_digest=ingest_image_tag),
            architecture=lambda_.Architecture.X86_64,
            memory_size=1024,
            timeout=Duration.seconds(300),
            role=ingest_role,
            log_group=ingest_log_group,
            # Giới hạn retry khi gọi bất đồng bộ để không tải Yahoo nhiều lần khi nguồn lỗi
            retry_attempts=1,
            environment={
                "LAKE_BUCKET": self.lake.bucket_name,
                "CPAWS_ENV": env_name,
            },
        )

        CfnOutput(self, "LakeBucketName", value=self.lake.bucket_name)
        CfnOutput(self, "IngestRepoUri", value=self.ingest_repo.repository_uri)
        CfnOutput(self, "IngestFunctionName", value=self.ingest_fn.function_name)

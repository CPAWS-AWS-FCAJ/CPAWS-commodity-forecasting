"""Stack CpawsData: S3 data lake, ECR, Lambda ingest và lịch chạy hằng ngày."""

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct

from .shared import INGEST_SCHEDULE_EXPRESSION, ingest_function_name


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
            log_group_name=f"/aws/lambda/{ingest_function_name(env_name)}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Lambda từ image trong ECR: x86_64, 1.024 MB, timeout 300 s, ngoài VPC.
        self.ingest_fn = lambda_.DockerImageFunction(
            self,
            "IngestFunction",
            function_name=ingest_function_name(env_name),
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

        # Lịch chạy hằng ngày: 12:15 UTC, thứ Ba-thứ Bảy (19:15 giờ VN). Phải KHỚP
        # INGEST_SCHEDULE_EXPRESSION trong src/data/config.py: dữ liệu phiên D chỉ có từ 12:00 UTC
        # ngày D+1. Khải đồng ý bật ngay (20/10); EIA không chặn ingest nên không cần chờ.
        scheduler_role = iam.Role(
            self,
            "IngestScheduleRole",
            role_name=f"cpaws-{env_name}-ingest-schedule-role",
            # Chỉ Scheduler của chính tài khoản này được assume (chống confused deputy)
            assumed_by=iam.PrincipalWithConditions(
                iam.ServicePrincipal("scheduler.amazonaws.com"),
                {"StringEquals": {"aws:SourceAccount": self.account}},
            ),
        )
        # Chỉ lambda:InvokeFunction trên đúng ARN Lambda ingest (không gồm version/alias)
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeIngestFunction",
                actions=["lambda:InvokeFunction"],
                resources=[self.ingest_fn.function_arn],
            )
        )

        # Retry của Scheduler = 0: Lambda đã có retry_attempts=1, không nhân số lần gọi Yahoo.
        self.ingest_schedule = scheduler.CfnSchedule(
            self,
            "IngestSchedule",
            name=f"cpaws-{env_name}-ingest-daily",
            description="Daily price ingest, 12:15 UTC Tue-Sat (after yfinance published_at)",
            schedule_expression=INGEST_SCHEDULE_EXPRESSION,
            schedule_expression_timezone="UTC",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            state="ENABLED",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=self.ingest_fn.function_arn,
                role_arn=scheduler_role.role_arn,
                input="{}",
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(maximum_retry_attempts=0),
            ),
        )

        CfnOutput(self, "LakeBucketName", value=self.lake.bucket_name)
        CfnOutput(self, "IngestRepoUri", value=self.ingest_repo.repository_uri)
        CfnOutput(self, "IngestFunctionName", value=self.ingest_fn.function_name)
        CfnOutput(self, "IngestScheduleName", value=self.ingest_schedule.name or "")

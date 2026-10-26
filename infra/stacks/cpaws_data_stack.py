"""Stack CpawsData: S3 data lake, ECR, Lambda ingest, Lambda predict và lịch chạy hằng ngày.

Luồng hằng ngày: Scheduler → Lambda ingest (bất đồng bộ, retry 1) → destination OnSuccess và
OnFailure đều gọi Lambda predict (retry 0). Ingest lỗi một nguồn vẫn ghi snapshot cho tài sản tốt
nên predict vẫn chạy; tài sản thiếu phiên cuối bị bỏ qua và predict raise PredictFailed (alarm).
"""

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_destinations as destinations
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct

from .shared import (
    INGEST_SCHEDULE_EXPRESSION,
    INGEST_SCHEDULE_GROUP,
    forecasts_table_name,
    ingest_function_name,
    predict_function_name,
)


class CpawsDataStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        ingest_image_tag: str,
        predict_image_tag: str,
        predict_model_version: str,
        eia_parameter_name: str | None = None,
        predict_repo_only: bool = False,
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

        # ECR cho container Lambda predict: cùng tên theo quy ước, RemovalPolicy và lifecycle với ingest.
        self.predict_repo = ecr.Repository(
            self,
            "PredictRepo",
            repository_name=f"cpaws-{env_name}-predict",
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            empty_on_delete=not is_prod,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=5, description="Giu 5 image moi nhat")
            ],
        )

        # Lambda predict cần image có sẵn trong ECR. Lần deploy ĐẦU TIÊN dùng
        # -c predict_repo_only=true để chỉ tạo repo, push image, rồi deploy lại không có cờ này.
        # Không dùng cờ ở các lần sau: deploy với cờ sẽ XÓA Lambda predict và destination của ingest.
        self.predict_fn: lambda_.DockerImageFunction | None = None
        predict_destination = None
        if not predict_repo_only:
            self.predict_fn = self._predict_function(
                env_name=env_name,
                image_tag=predict_image_tag,
                model_version=predict_model_version,
            )
            predict_destination = destinations.LambdaDestination(self.predict_fn)

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

        # Chỉ đọc parameter SSM chứa EIA API key bằng quyền tối thiểu.
        parameter_name = None
        if eia_parameter_name is not None:
            parameter_name = eia_parameter_name.strip()
            if not parameter_name:
                raise ValueError("eia_parameter_name must not be empty")
            if parameter_name.startswith("arn:"):
                raise ValueError(
                    "eia_parameter_name must be an SSM parameter name, not an ARN"
                )

            ingest_role.add_to_policy(
                iam.PolicyStatement(
                    sid="ReadEiaParameter",
                    actions=["ssm:GetParameter"],
                    resources=[
                        self.format_arn(
                            service="ssm",
                            resource="parameter",
                            resource_name=parameter_name.lstrip("/"),
                        )
                    ],
                )
            )
        # Log giữ 30 ngày (aws-cost-guard: retention 14-30 ngày).
        ingest_log_group = logs.LogGroup(
            self,
            "IngestLogGroup",
            log_group_name=f"/aws/lambda/{ingest_function_name(env_name)}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Lambda từ image trong ECR: x86_64, 1.024 MB, timeout 300 s, ngoài VPC.
        # Pass only the parameter name, never the secret value.
        ingest_environment = {
            "LAKE_BUCKET": self.lake.bucket_name,
            "CPAWS_ENV": env_name,
        }
        if parameter_name is not None:
            ingest_environment["EIA_SECRET_ID"] = parameter_name

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
            # Cả thành công lẫn thất bại (sau khi hết retry) đều gọi predict: ingest lỗi một nguồn
            # vẫn ghi snapshot cho tài sản tốt (góp ý của Khải, 22/10). Destination chỉ áp dụng khi
            # ingest được gọi BẤT ĐỒNG BỘ (Scheduler, hoặc aws lambda invoke --invocation-type Event).
            on_success=predict_destination,
            on_failure=predict_destination,
            environment=ingest_environment,
        )

        # Lịch chạy hằng ngày: 12:15 UTC, thứ Ba-thứ Bảy (19:15 giờ VN). Phải KHỚP
        # INGEST_SCHEDULE_EXPRESSION trong src/data/config.py: dữ liệu phiên D chỉ có từ 12:00 UTC
        # ngày D+1. Khải đồng ý bật ngay (20/10); EIA không chặn ingest nên không cần chờ.

        # ARN của schedule group (dạng arn:aws:scheduler:<region>:<account>:schedule-group/<tên>)
        schedule_group_arn = self.format_arn(
            service="scheduler", resource="schedule-group", resource_name=INGEST_SCHEDULE_GROUP
        )
        scheduler_role = iam.Role(
            self,
            "IngestScheduleRole",
            role_name=f"cpaws-{env_name}-ingest-schedule-role",
            # Chỉ Scheduler của chính tài khoản này, và chỉ lịch thuộc đúng schedule group trên,
            # được assume (chống confused deputy; Tuấn review PR #17).
            assumed_by=iam.PrincipalWithConditions(
                iam.ServicePrincipal("scheduler.amazonaws.com"),
                {
                    "StringEquals": {
                        "aws:SourceAccount": self.account,
                        "aws:SourceArn": schedule_group_arn,
                    }
                },
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
            group_name=INGEST_SCHEDULE_GROUP,
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
        CfnOutput(self, "PredictRepoUri", value=self.predict_repo.repository_uri)
        if self.predict_fn is not None:
            CfnOutput(self, "PredictFunctionName", value=self.predict_fn.function_name)

    def _predict_function(
        self, *, env_name: str, image_tag: str, model_version: str
    ) -> lambda_.DockerImageFunction:
        """Lambda predict từ image ECR (docker/predict/Dockerfile), quyền tối thiểu. Tuấn review."""
        role = iam.Role(
            self,
            "PredictRole",
            role_name=f"cpaws-{env_name}-predict-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        # Chỉ ĐỌC clean/ (prices, display_factors) và models/ (artifact); không ghi gì vào lake.
        # Giả định LAKE_PREFIX rỗng, giống role ingest.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeReadCleanModels",
                actions=["s3:GetObject"],
                resources=[
                    self.lake.arn_for_objects("clean/*"),
                    self.lake.arn_for_objects("models/*"),
                ],
            )
        )
        # Code dùng ListObjectsV2 để tìm dt= mới nhất và tải thư mục artifact
        role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeListCleanModels",
                actions=["s3:ListBucket"],
                resources=[self.lake.bucket_arn],
                conditions={"StringLike": {"s3:prefix": ["clean/*", "models/*"]}},
            )
        )
        # DynamoSink chỉ dùng put_item (ghi đè theo asset + base_date); không Query/Delete.
        table_name = forecasts_table_name(env_name)
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ForecastsPutItem",
                actions=["dynamodb:PutItem"],
                resources=[
                    self.format_arn(service="dynamodb", resource="table", resource_name=table_name)
                ],
            )
        )

        log_group = logs.LogGroup(
            self,
            "PredictLogGroup",
            log_group_name=f"/aws/lambda/{predict_function_name(env_name)}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # 1.024 MB / 120 s, x86_64, ngoài VPC (cấu hình Khải yêu cầu cho baseline-q252).
        return lambda_.DockerImageFunction(
            self,
            "PredictFunction",
            function_name=predict_function_name(env_name),
            description="Daily return-quantile forecast from the latest clean snapshot to DynamoDB",
            code=lambda_.DockerImageCode.from_ecr(self.predict_repo, tag_or_digest=image_tag),
            architecture=lambda_.Architecture.X86_64,
            memory_size=1024,
            timeout=Duration.seconds(120),
            role=role,
            log_group=log_group,
            # Không retry: tài sản bị bỏ qua sẽ bị bỏ qua lại; lỗi đã có alarm Errors để xử lý tay.
            retry_attempts=0,
            environment={
                "LAKE_BUCKET": self.lake.bucket_name,
                "FORECASTS_TABLE": table_name,
                "MODEL_VERSION": model_version,
                "CPAWS_ENV": env_name,
            },
        )

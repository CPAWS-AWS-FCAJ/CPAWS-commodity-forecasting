"""Stack CpawsData: S3 data lake, ECR, Lambda ingest, Lambda predict và lịch chạy hằng ngày.

Luồng hằng ngày: Scheduler → Lambda ingest (bất đồng bộ, retry 1) → destination OnSuccess và
OnFailure đều gọi Lambda predict (retry 0). Ingest lỗi một nguồn vẫn ghi snapshot cho tài sản tốt
nên predict vẫn chạy; tài sản thiếu phiên cuối bị bỏ qua và predict raise PredictFailed (alarm).

Job accuracy rolling_8w (Walk-forward Contract §7): Lambda riêng từ image predict (CMD
src.eval.lambda_accuracy.handler), lịch 13:45 UTC thứ Ba-thứ Bảy, tạo ở trạng thái TẮT tới khi nhóm
xem dry-run 4 tài sản và quyết cách xử lý base_price_revision_mismatch (handoff §7).
"""

import json
import re
from collections.abc import Mapping
from datetime import date
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
    ACCURACY_HANDLER,
    ACCURACY_SCHEDULE_EXPRESSION,
    ALLOWED_SHADOW_MODELS,
    BASELINE_MODEL_VERSION,
    FORECAST_ASSETS,
    INGEST_SCHEDULE_EXPRESSION,
    INGEST_SCHEDULE_GROUP,
    MODEL_VERSION_PATTERN,
    PREDICT_METRIC_NAMESPACE,
    PREDICT_SHADOW_ERROR_LOG_TERMS,
    PREDICT_SHADOW_ERRORS_METRIC,
    accuracy_job_function_name,
    accuracy_table_name,
    forecasts_table_name,
    ingest_function_name,
    predict_function_name,
)


def predict_champion_environment(
    *,
    model_version: str,
    model_versions: Mapping[str, str],
    effective_base_dates: Mapping[str, str],
    shadow_models: str,
) -> dict[str, str]:
    """Biến môi trường champion/shadow cho Lambda predict, kiểm tra ngay lúc synth.

    - MODEL_VERSIONS: JSON đúng 4 tài sản; predict (#53) đọc biến này và bỏ qua MODEL_VERSION.
    - MODEL_VERSION giữ lại, phải bằng mọi giá trị của MODEL_VERSIONS: image ce77bcb (rollback)
      chỉ đọc MODEL_VERSION, còn predict #53 không báo gì khi hai biến lệch nhau.
    - CHAMPION_EFFECTIVE_BASE_DATES: predict không đọc (job accuracy đọc); chỉ kiểm cùng bộ
      tài sản và ngày ISO, không đặt vào env predict.
    - SHADOW_MODELS: rỗng = tắt (rollback không cần build image); chỉ nhận ALLOWED_SHADOW_MODELS.
    """
    assets = set(FORECAST_ASSETS)
    if set(model_versions) != assets:
        raise ValueError(f"model_versions must have exactly the assets {sorted(assets)}")
    if set(effective_base_dates) != assets:
        raise ValueError(f"effective_base_dates must have exactly the assets {sorted(assets)}")
    for asset in FORECAST_ASSETS:
        version = model_versions[asset]
        if not isinstance(version, str) or not re.fullmatch(MODEL_VERSION_PATTERN, version):
            raise ValueError(f"invalid model version for {asset}: {version!r}")
        value = effective_base_dates[asset]
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError(f"effective base date for {asset} must be YYYY-MM-DD: {value!r}")
    if set(model_versions.values()) != {model_version}:
        raise ValueError(
            "MODEL_VERSION must equal every MODEL_VERSIONS value "
            "(rollback image ce77bcb reads MODEL_VERSION only)"
        )

    env = {
        # Thứ tự cố định để template không đổi giữa các lần synth
        "MODEL_VERSIONS": json.dumps(
            {a: model_versions[a] for a in FORECAST_ASSETS}, separators=(",", ":")
        ),
    }
    shadows = [m.strip() for m in shadow_models.split(",") if m.strip()]
    unknown = sorted(set(shadows) - set(ALLOWED_SHADOW_MODELS))
    if unknown or len(shadows) != len(set(shadows)):
        raise ValueError(f"shadow_models accepts only {list(ALLOWED_SHADOW_MODELS)}: {shadows}")
    if shadows:
        # S1a co giãn phân vị của mốc 252 phiên: không tài sản nào baseline thì predict log
        # PREDICT_SHADOW_CONFIG_INVALID mỗi lượt (alarm), nên chặn ngay ở đây.
        if BASELINE_MODEL_VERSION not in model_versions.values():
            raise ValueError(f"shadow models need at least one {BASELINE_MODEL_VERSION} champion")
        env["SHADOW_MODELS"] = ",".join(shadows)
    return env


# Khóa evidence job accuracy đọc (rolling_sources.Evidence, rolling_shadow); khóa lạ = gõ sai.
ROLLING_EVIDENCE_KEYS = ("release", "legacy", "shadow_release")
# Tổng kích thước env của một Lambda tối đa 4 KB (tên + giá trị). Vượt thì chuyển evidence sang
# ROLLING_EVIDENCE_PATH (file trong image, handoff §2), không cắt bớt evidence.
LAMBDA_ENV_LIMIT_BYTES = 4096


def accuracy_job_environment(
    *,
    lake_bucket: str,
    forecasts_table: str,
    accuracy_table: str,
    model_versions: Mapping[str, str],
    effective_base_dates: Mapping[str, str],
    evidence: Mapping[str, Any],
) -> dict[str, str]:
    """Biến môi trường job accuracy (handoff rolling accuracy §2), kiểm ngay lúc synth.

    - MODEL_VERSIONS, CHAMPION_EFFECTIVE_BASE_DATES: cùng giá trị đã kiểm cho predict (truyền
      từ CpawsDataStack.champion_*), cùng thứ tự tài sản; contract cấm suy từ STATE.
    - ROLLING_EVIDENCE_JSON: evidence đã duyệt qua PR (trust boundary là review, handoff §3);
      chỉ nhận object có khóa trong ROLLING_EVIDENCE_KEYS. `{}` = fail-closed (not_ready).
    - Không đặt LAKE_PREFIX (rỗng, giống predict) và ROLLING_REVISION (mặc định 0): đổi revision
      là correction có audit, làm bằng PR riêng.
    """
    if not isinstance(evidence, Mapping):
        raise TypeError("accuracy evidence must be a JSON object")
    unknown = sorted(set(evidence) - set(ROLLING_EVIDENCE_KEYS))
    if unknown:
        raise ValueError(f"unknown accuracy evidence keys: {unknown}")
    if not isinstance(evidence.get("legacy", []), list):
        raise TypeError("accuracy evidence 'legacy' must be a list")
    for key in ("release", "shadow_release"):
        if not isinstance(evidence.get(key, {}), Mapping):
            raise TypeError(f"accuracy evidence {key!r} must be an object")
    env = {
        "LAKE_BUCKET": lake_bucket,
        "FORECASTS_TABLE": forecasts_table,
        "ACCURACY_TABLE": accuracy_table,
        "MODEL_VERSIONS": json.dumps(
            {a: model_versions[a] for a in FORECAST_ASSETS}, separators=(",", ":")
        ),
        "CHAMPION_EFFECTIVE_BASE_DATES": json.dumps(
            {a: effective_base_dates[a] for a in FORECAST_ASSETS}, separators=(",", ":")
        ),
        "ROLLING_EVIDENCE_JSON": json.dumps(
            dict(evidence), separators=(",", ":"), sort_keys=True, ensure_ascii=True
        ),
    }
    size = sum(len(k.encode()) + len(v.encode()) for k, v in env.items())
    if size >= LAMBDA_ENV_LIMIT_BYTES:
        raise ValueError(
            f"accuracy job environment ~{size} bytes exceeds the 4 KB Lambda limit: "
            "move evidence to ROLLING_EVIDENCE_PATH"
        )
    return env


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
        predict_model_versions: Mapping[str, str],
        champion_effective_base_dates: Mapping[str, str],
        predict_shadow_models: str,
        accuracy_image_tag: str,
        accuracy_evidence: Mapping[str, Any],
        eia_parameter_name: str | None = None,
        predict_repo_only: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Kiểm cấu hình champion/shadow cả khi predict_repo_only (sai thì dừng ở synth).
        predict_champion_env = predict_champion_environment(
            model_version=predict_model_version,
            model_versions=predict_model_versions,
            effective_base_dates=champion_effective_base_dates,
            shadow_models=predict_shadow_models,
        )
        # Lambda accuracy-job dùng cùng giá trị, không khai báo lần hai.
        self.champion_model_versions = dict(predict_model_versions)
        self.champion_effective_base_dates = dict(champion_effective_base_dates)
        # Kiểm env job accuracy cả khi predict_repo_only (sai thì dừng ở synth). Tên bucket ghi
        # thẳng (bằng bucket_name của Lake bên dưới) để kiểm được kích thước env 4 KB.
        accuracy_env = accuracy_job_environment(
            lake_bucket=f"cpaws-{env_name}-lake",
            forecasts_table=forecasts_table_name(env_name),
            accuracy_table=accuracy_table_name(env_name),
            model_versions=self.champion_model_versions,
            effective_base_dates=self.champion_effective_base_dates,
            evidence=accuracy_evidence,
        )

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
                champion_env=predict_champion_env,
            )
            predict_destination = destinations.LambdaDestination(self.predict_fn)

        # Job accuracy cũng chạy từ image trong repo predict: chưa có image thì chưa tạo.
        self.accuracy_fn: lambda_.DockerImageFunction | None = None
        self.accuracy_schedule: scheduler.CfnSchedule | None = None
        if not predict_repo_only:
            self.accuracy_fn, self.accuracy_schedule = self._accuracy_job(
                env_name=env_name, image_tag=accuracy_image_tag, accuracy_env=accuracy_env
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

        # Chỉ đọc parameter SSM chứa EIA API key bằng quyền tối thiểu.
        parameter_name = None
        if eia_parameter_name is not None:
            parameter_name = eia_parameter_name.strip()
            if not parameter_name:
                raise ValueError("eia_parameter_name must not be empty")
            if parameter_name.startswith("arn:"):
                raise ValueError("eia_parameter_name must be an SSM parameter name, not an ARN")

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
        if self.accuracy_fn is not None and self.accuracy_schedule is not None:
            CfnOutput(self, "AccuracyFunctionName", value=self.accuracy_fn.function_name)
            CfnOutput(self, "AccuracyScheduleName", value=self.accuracy_schedule.name or "")

    def _predict_function(
        self, *, env_name: str, image_tag: str, model_version: str, champion_env: dict[str, str]
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
        # Chỉ cho phép ghi kết quả shadow evaluation.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="WriteShadowEvaluationObjects",
                actions=["s3:PutObject"],
                resources=[self.lake.arn_for_objects("eval/shadow/*")],
            )
        )

        # DynamoSink chỉ dùng put_item có điều kiện: không ghi đè bản đã phát hành cùng
        # asset + base_date, chỉ thay bản mẫu (is_sample = true); không Query/Delete.
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
        # Lỗi shadow S1a không làm predict raise nên metric Errors không thấy; đếm từ log,
        # alarm ở CpawsOps (cùng namespace + tên metric trong shared.py).
        logs.MetricFilter(
            self,
            "PredictShadowErrorsFilter",
            log_group=log_group,
            metric_namespace=PREDICT_METRIC_NAMESPACE,
            metric_name=PREDICT_SHADOW_ERRORS_METRIC,
            metric_value="1",
            filter_pattern=logs.FilterPattern.literal(
                " ".join(f'?"{term}"' for term in PREDICT_SHADOW_ERROR_LOG_TERMS)
            ),
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
                **champion_env,
            },
        )

    def _accuracy_job(
        self, *, env_name: str, image_tag: str, accuracy_env: dict[str, str]
    ) -> tuple[lambda_.DockerImageFunction, scheduler.CfnSchedule]:
        """Lambda job accuracy rolling_8w + lịch TẮT (Walk-forward Contract §7.2, §7.5;
        handoff rolling accuracy §2, §7, §8). IAM theo §7.5: đọc Forecasts/clean/shadow, ghi
        Accuracy và chỉ eval/shadow_eval/. Tuấn review IAM."""
        table_arn = self.format_arn(
            service="dynamodb", resource="table", resource_name=accuracy_table_name(env_name)
        )
        forecasts_arn = self.format_arn(
            service="dynamodb", resource="table", resource_name=forecasts_table_name(env_name)
        )
        role = iam.Role(
            self,
            "AccuracyJobRole",
            role_name=f"cpaws-{env_name}-accuracy-job-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        # Sources đọc snapshot clean/prices/dt=<ngày>/ (prices, quality, rejected) và shadow S1a
        # eval/shadow/s1a-l094/dt=<ngày>/<asset>.json; head_object dùng cùng quyền GetObject.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeReadPricesShadow",
                actions=["s3:GetObject"],
                resources=[
                    self.lake.arn_for_objects("clean/prices/*"),
                    self.lake.arn_for_objects("eval/shadow/s1a-l094/*"),
                ],
            )
        )
        # GetObject bị 403 thì Sources gọi ListObjectsV2(Prefix=key) để phân biệt thiếu object với
        # thiếu quyền (§7.5): giới hạn đúng hai prefix đọc, không mở toàn lake.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeListPricesShadow",
                actions=["s3:ListBucket"],
                resources=[self.lake.bucket_arn],
                conditions={
                    "StringLike": {"s3:prefix": ["clean/prices/*", "eval/shadow/s1a-l094/*"]}
                },
            )
        )
        # Report so sánh S1a: put_object có IfNoneMatch="*" (không ghi đè), chỉ prefix shadow_eval.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="WriteShadowEvalReports",
                actions=["s3:PutObject"],
                resources=[self.lake.arn_for_objects("eval/shadow_eval/*")],
            )
        )
        # Forecasts chỉ Query (Sources.records); không Scan/GetItem/ghi.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ForecastsQuery",
                actions=["dynamodb:Query"],
                resources=[forecasts_arn],
            )
        )
        # AccuracyStore: PutItem/UpdateItem có điều kiện, GetItem + Query ConsistentRead.
        # Không Scan, DeleteItem, BatchWriteItem hay index (§7.5: bảng không có GSI/LSI).
        role.add_to_policy(
            iam.PolicyStatement(
                sid="AccuracyReadWrite",
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:Query",
                ],
                resources=[table_arn],
            )
        )

        log_group = logs.LogGroup(
            self,
            "AccuracyJobLogGroup",
            log_group_name=f"/aws/lambda/{accuracy_job_function_name(env_name)}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # 1.024 MB / 300 s (§7.2) chưa đo trên dữ liệu thật: ghi Duration và Max Memory Used ở
        # lần dry-run đầu (handoff §7). Không reserved concurrency (§7.2): idempotency nhờ
        # run fingerprint và ghi có điều kiện.
        fn = lambda_.DockerImageFunction(
            self,
            "AccuracyJobFunction",
            function_name=accuracy_job_function_name(env_name),
            description="Daily rolling_8w accuracy of champion forecasts (and S1a shadow report)",
            code=lambda_.DockerImageCode.from_ecr(
                self.predict_repo, tag_or_digest=image_tag, cmd=[ACCURACY_HANDLER]
            ),
            architecture=lambda_.Architecture.X86_64,
            memory_size=1024,
            timeout=Duration.seconds(300),
            role=role,
            log_group=log_group,
            # Retry 0 (§7.2): lượt lỗi chờ lượt sau; alarm Errors ở CpawsOps.
            retry_attempts=0,
            environment=accuracy_env,
        )

        # Role riêng cho lịch accuracy (không dùng chung role lịch ingest): chỉ gọi được Lambda này.
        schedule_group_arn = self.format_arn(
            service="scheduler", resource="schedule-group", resource_name=INGEST_SCHEDULE_GROUP
        )
        schedule_role = iam.Role(
            self,
            "AccuracyScheduleRole",
            role_name=f"cpaws-{env_name}-accuracy-schedule-role",
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
        schedule_role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeAccuracyJobFunction",
                actions=["lambda:InvokeFunction"],
                resources=[fn.function_arn],
            )
        )
        # TẮT (handoff §7 bước 4): chỉ bật bằng PR sau dry-run 4 tài sản, kiểm IAM/image và
        # thống nhất phương án base_price_revision_mismatch. Payload {} = 4 tài sản, ghi thật.
        schedule = scheduler.CfnSchedule(
            self,
            "AccuracySchedule",
            name=f"cpaws-{env_name}-accuracy-daily",
            group_name=INGEST_SCHEDULE_GROUP,
            description="Daily rolling_8w accuracy, 13:45 UTC Tue-Sat (after predict)",
            schedule_expression=ACCURACY_SCHEDULE_EXPRESSION,
            schedule_expression_timezone="UTC",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            state="DISABLED",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=fn.function_arn,
                role_arn=schedule_role.role_arn,
                input="{}",
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(maximum_retry_attempts=0),
            ),
        )
        return fn, schedule

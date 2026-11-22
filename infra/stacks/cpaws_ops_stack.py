"""Stack CpawsOps: alarm cho Lambda ingest, predict (cả shadow S1a), job accuracy và /chat, gửi
email qua SNS."""

from typing import Any

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from .shared import (
    CHAT_INTERNAL_ERRORS_METRIC,
    CHAT_METRIC_NAMESPACE,
    PREDICT_METRIC_NAMESPACE,
    PREDICT_SHADOW_ERRORS_METRIC,
)


class CpawsOpsStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        ingest_function_name: str,
        predict_function_name: str,
        chat_function_name: str | None = None,
        accuracy_function_name: str | None = None,
        alarm_email: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name=f"cpaws-{env_name}-alarms",
            display_name="CPAWS alarms",
        )
        # Người nhận phải bấm Confirm trong email AWS gửi sau lần deploy đầu
        if alarm_email:
            self.alarm_topic.add_subscription(subs.EmailSubscription(alarm_email))

        # Lambda ingest chạy 1 lần/ngày: ngày không chạy không có số liệu nên coi là bình thường.
        # IngestSourceFailed (nguồn chính lỗi) cũng được Lambda tính vào Errors.
        ingest_errors = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": ingest_function_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )
        ingest_alarm = cloudwatch.Alarm(
            self,
            "IngestErrorsAlarm",
            alarm_name=f"cpaws-{env_name}-ingest-errors",
            alarm_description="Ingest Lambda reported >= 1 error (source failed or crash)",
            metric=ingest_errors,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        ingest_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # Predict chạy sau mỗi lần ingest (OnSuccess/OnFailure). PredictFailed (có tài sản bị bỏ qua,
        # ví dụ thiếu phiên cuối) cũng được tính vào Errors. Trước khi Lambda predict được tạo,
        # metric không có số liệu nên alarm ở trạng thái bình thường.
        predict_errors = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": predict_function_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )
        predict_alarm = cloudwatch.Alarm(
            self,
            "PredictErrorsAlarm",
            alarm_name=f"cpaws-{env_name}-predict-errors",
            alarm_description="Predict Lambda reported >= 1 error (asset skipped/failed or crash)",
            metric=predict_errors,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        predict_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        # Shadow S1a lỗi (PREDICT_SHADOW_FAILED) hoặc cấu hình shadow sai
        # (PREDICT_SHADOW_CONFIG_INVALID): predict vẫn ghi champion và không raise, nên đếm từ log
        # (metric filter ở CpawsData). Không có dòng log khớp thì không có số liệu → bình thường.
        shadow_errors = cloudwatch.Metric(
            namespace=PREDICT_METRIC_NAMESPACE,
            metric_name=PREDICT_SHADOW_ERRORS_METRIC,
            statistic="Sum",
            period=Duration.minutes(5),
        )
        shadow_alarm = cloudwatch.Alarm(
            self,
            "PredictShadowErrorsAlarm",
            alarm_name=f"cpaws-{env_name}-predict-shadow-errors",
            alarm_description="Predict shadow S1a failed or shadow config invalid (>= 1 log line)",
            metric=shadow_errors,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        shadow_alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

        if accuracy_function_name:
            self._add_accuracy_alarm(env_name, accuracy_function_name)

        if chat_function_name:
            self._add_chat_alarms(env_name, chat_function_name)

        CfnOutput(self, "AlarmTopicArn", value=self.alarm_topic.topic_arn)

    def _add_accuracy_alarm(self, env_name: str, accuracy_function_name: str) -> None:
        """Job accuracy raise AccuracyFailed khi có tài sản FAILED (không tính dry_run, not_ready),
        cộng timeout/crash: đều vào Errors của Lambda (Walk-forward Contract §7.2). Lịch đang tắt
        thì không có số liệu → bình thường."""
        accuracy_errors = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": accuracy_function_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )
        alarm = cloudwatch.Alarm(
            self,
            "AccuracyJobErrorsAlarm",
            alarm_name=f"cpaws-{env_name}-accuracy-job-errors",
            alarm_description="Accuracy job reported >= 1 error (asset FAILED, timeout or crash)",
            metric=accuracy_errors,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

    def _add_chat_alarms(self, env_name: str, chat_function_name: str) -> None:
        """Hai alarm cho Lambda /chat: timeout/crash (Errors của Lambda) và lỗi không lường trước
        mà handler đã bắt rồi trả 500 (metric filter ở CpawsApi). Lỗi 4xx, 429 và lỗi Bedrock trả
        502/504 có mã riêng là hành vi đã thiết kế, không báo."""
        chat_errors = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": chat_function_name},
            statistic="Sum",
            period=Duration.minutes(5),
        )
        chat_internal = cloudwatch.Metric(
            namespace=CHAT_METRIC_NAMESPACE,
            metric_name=CHAT_INTERNAL_ERRORS_METRIC,
            statistic="Sum",
            period=Duration.minutes(5),
        )
        at_least_threshold = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
        for construct_id, name, description, metric in (
            (
                "ChatErrorsAlarm",
                f"cpaws-{env_name}-chat-api-errors",
                "Chat Lambda timed out or crashed (>= 1 error)",
                chat_errors,
            ),
            (
                "ChatInternalErrorsAlarm",
                f"cpaws-{env_name}-chat-api-internal-errors",
                "Chat Lambda returned 500 after an unexpected exception (>= 1)",
                chat_internal,
            ),
        ):
            alarm = cloudwatch.Alarm(
                self,
                construct_id,
                alarm_name=name,
                alarm_description=description,
                metric=metric,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=at_least_threshold,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))

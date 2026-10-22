"""Stack CpawsOps: alarm cho Lambda ingest, gửi email qua SNS."""

from typing import Any

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct


class CpawsOpsStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        ingest_function_name: str,
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

        CfnOutput(self, "AlarmTopicArn", value=self.alarm_topic.topic_arn)

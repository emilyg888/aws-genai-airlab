from __future__ import annotations

import os
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_event_sources,
    aws_logs as logs,
    aws_msk as msk,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct

_ASSET_EXCLUDE = [
    ".venv", ".venv/*",
    "cdk.out", "cdk.out/*",
    "**/__pycache__",
    "**/__pycache__/*",
    "**/*.pyc",
    ".git", ".git/*",
    "Archive*.zip",
    "course-materials", "course-materials/*",
    "notes_ai", "notes_ai/*",
    "slides", "slides/*",
    "knowledge_base/provisioner.py",  # unused by trigger lambdas
]


class TriggerStack(Stack):
    """Event-driven AI trigger layer: MSK Serverless + consumer/decider Lambdas."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        api_endpoint_param: str,
        tutor_method_arn: str,
        enable_event_source: bool | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project_root = Path(__file__).resolve().parents[2]
        enable_event_source = (
            os.getenv("TRIGGER_ENABLE_EVENT_SOURCE", "false").lower() == "true"
            if enable_event_source is None else enable_event_source
        )

        # --- VPC (MSK Serverless requires private subnets) ---
        vpc = ec2.Vpc(
            self,
            "TriggerVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                )
            ],
        )
        msk_sg = ec2.SecurityGroup(
            self, "MskSg", vpc=vpc,
            description="Allow Lambda to/from MSK Serverless on 9098 (IAM SASL).",
            allow_all_outbound=True,
        )
        msk_sg.add_ingress_rule(msk_sg, ec2.Port.tcp(9098), "MSK IAM SASL")
        msk_sg.add_ingress_rule(msk_sg, ec2.Port.tcp(443), "VPC endpoints (HTTPS)")

        # VPC endpoints so VPC-bound Lambdas can reach STS / SSM / S3 / Lambda / CloudWatch.
        for svc in ("ssm", "lambda", "sts", "monitoring", "logs"):
            vpc.add_interface_endpoint(
                f"{svc.capitalize()}Endpoint",
                service=ec2.InterfaceVpcEndpointAwsService(svc),
                security_groups=[msk_sg],
            )
        vpc.add_gateway_endpoint(
            "S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        # --- MSK Serverless cluster ---
        cluster = msk.CfnServerlessCluster(
            self,
            "EventCluster",
            cluster_name="ai-events-cluster",
            client_authentication=msk.CfnServerlessCluster.ClientAuthenticationProperty(
                sasl=msk.CfnServerlessCluster.SaslProperty(
                    iam=msk.CfnServerlessCluster.IamProperty(enabled=True),
                ),
            ),
            vpc_configs=[
                msk.CfnServerlessCluster.VpcConfigProperty(
                    subnet_ids=vpc.select_subnets(
                        subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
                    ).subnet_ids,
                    security_groups=[msk_sg.security_group_id],
                )
            ],
        )

        # --- DLQs ---
        consumer_dlq = sqs.Queue(
            self, "ConsumerDlq", retention_period=Duration.days(14),
        )
        decider_dlq = sqs.Queue(
            self, "DeciderDlq", retention_period=Duration.days(14),
        )

        # --- Audit bucket ---
        audit_bucket = s3.Bucket(
            self,
            "AuditBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            auto_delete_objects=True,
            removal_policy=RemovalPolicy.DESTROY,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
        )

        # --- Kill-switch SSM param (default enabled=false so first deploy is safe) ---
        kill_switch = ssm.StringParameter(
            self,
            "KillSwitchParam",
            parameter_name="/airlab/trigger/enabled",
            string_value=os.getenv("TRIGGER_DEFAULT_ENABLED", "false"),
            description="When 'true', consumer invokes the decider. 'false' short-circuits.",
        )

        # --- Decider Lambda ---
        decider = lambda_.Function(
            self,
            "TriggerDeciderLambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="tools.lambda_handlers.trigger_decider.handler",
            code=lambda_.Code.from_asset(str(project_root), exclude=_ASSET_EXCLUDE),
            timeout=Duration.seconds(60),
            memory_size=512,
            dead_letter_queue=decider_dlq,
            environment={
                "API_ENDPOINT_SSM_PARAM": api_endpoint_param,
                "MODEL_MAP_SSM_PARAM": "/airlab/trigger/model-map",
                "AUDIT_BUCKET": audit_bucket.bucket_name,
            },
            # Decider does not talk to Kafka — keep it outside the VPC so it
            # can reach API Gateway / SSM / S3 public endpoints without a NAT.
        )
        audit_bucket.grant_write(decider)
        decider.add_to_role_policy(
            iam.PolicyStatement(
                actions=["execute-api:Invoke"],
                resources=[tutor_method_arn],
            )
        )
        decider.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter{api_endpoint_param}",
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/airlab/trigger/*",
                ],
            )
        )

        # --- Consumer Lambda ---
        consumer = lambda_.Function(
            self,
            "TriggerConsumerLambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="tools.lambda_handlers.trigger_consumer.handler",
            code=lambda_.Code.from_asset(str(project_root), exclude=_ASSET_EXCLUDE),
            timeout=Duration.seconds(30),
            memory_size=512,
            dead_letter_queue=consumer_dlq,
            environment={
                "DECIDER_FUNCTION_NAME": decider.function_name,
                "AUDIT_BUCKET": audit_bucket.bucket_name,
                "RULES_CONFIG_PATH": "config/trigger_rules.json",
                "KILL_SWITCH_PARAM": kill_switch.parameter_name,
            },
            vpc=vpc,
            security_groups=[msk_sg],
        )
        decider.grant_invoke(consumer)
        audit_bucket.grant_write(consumer)
        kill_switch.grant_read(consumer)
        consumer.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:Connect",
                    "kafka-cluster:DescribeGroup",
                    "kafka-cluster:AlterGroup",
                    "kafka-cluster:DescribeTopic",
                    "kafka-cluster:ReadData",
                    "kafka-cluster:DescribeClusterDynamicConfiguration",
                ],
                resources=[
                    cluster.attr_arn,
                    f"{cluster.attr_arn}/*",
                ],
            )
        )

        if enable_event_source:
            consumer.add_event_source(
                lambda_event_sources.ManagedKafkaEventSource(
                    cluster_arn=cluster.attr_arn,
                    topic="ai-events",
                    starting_position=lambda_.StartingPosition.LATEST,
                    batch_size=50,
                    max_batching_window=Duration.seconds(5),
                )
            )

        for fn in (consumer, decider):
            logs.LogGroup(
                self,
                f"{fn.node.id}LogGroup",
                log_group_name=f"/aws/lambda/{fn.function_name}",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            )

        CfnOutput(self, "EventClusterArn", value=cluster.attr_arn)
        CfnOutput(self, "AuditBucketName", value=audit_bucket.bucket_name)
        CfnOutput(self, "ConsumerDlqUrl", value=consumer_dlq.queue_url)
        CfnOutput(self, "DeciderDlqUrl", value=decider_dlq.queue_url)
        CfnOutput(self, "KillSwitchParamName", value=kill_switch.parameter_name)

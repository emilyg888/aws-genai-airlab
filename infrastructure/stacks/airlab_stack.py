from __future__ import annotations

import os
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    custom_resources as cr,
)
from constructs import Construct


class AirLabStack(Stack):
    """Ephemeral serverless lab stack for Bedrock + RAG + multi-agent workflows."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project_root = Path(__file__).resolve().parents[2]

        docs_bucket = s3.Bucket(
            self,
            "DocsBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            auto_delete_objects=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        vectors_bucket = s3.Bucket(
            self,
            "VectorsBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            auto_delete_objects=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        kb_service_role = iam.Role(
            self,
            "BedrockKnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Role used by Bedrock Knowledge Base for document/vector access.",
        )
        docs_bucket.grant_read(kb_service_role)
        vectors_bucket.grant_read_write(kb_service_role)

        kb_provisioner = lambda_.Function(
            self,
            "KnowledgeBaseProvisioner",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset(str(project_root), exclude=[
                                         ".venv", "cdk.out", "**/__pycache__"]),
            handler="knowledge_base.provisioner.handler",
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "ENABLE_REAL_KB_CALLS": os.getenv("ENABLE_REAL_KB_CALLS", "false"),
            },
        )

        docs_bucket.grant_read(kb_provisioner)
        vectors_bucket.grant_read_write(kb_provisioner)
        kb_provisioner.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:CreateKnowledgeBase",
                    "bedrock:UpdateKnowledgeBase",
                    "bedrock:DeleteKnowledgeBase",
                    "bedrock:GetKnowledgeBase",
                    "bedrock:ListKnowledgeBases",
                    "bedrock:CreateDataSource",
                    "bedrock:UpdateDataSource",
                    "bedrock:DeleteDataSource",
                    "bedrock:GetDataSource",
                    "bedrock:ListDataSources",
                    "iam:PassRole",
                ],
                resources=["*"],
            )
        )
        kb_provisioner.add_environment(
            "BEDROCK_EMBEDDING_MODEL_ARN", os.getenv("BEDROCK_EMBEDDING_MODEL_ARN", ""))

        kb_provider = cr.Provider(
            self,
            "KnowledgeBaseProvider",
            on_event_handler=kb_provisioner,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        kb_resource = CustomResource(
            self,
            "KnowledgeBaseResource",
            service_token=kb_provider.service_token,
            properties={
                "KnowledgeBaseName": os.getenv("BEDROCK_KB_NAME", "aws-genai-airlab-kb"),
                "DataSourceName": os.getenv("BEDROCK_DATA_SOURCE_NAME", "airlab-course-slides"),
                "KnowledgeBaseRoleArn": kb_service_role.role_arn,
                "DocumentBucketName": docs_bucket.bucket_name,
                "VectorBucketName": vectors_bucket.bucket_name,
            },
        )

        knowledge_base_id = kb_resource.get_att_string("KnowledgeBaseId")

        shared_env = {
            "BEDROCK_MODEL_ID": os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
            "KNOWLEDGE_BASE_ID": knowledge_base_id,
        }

        tutor_fn = self._build_agent_lambda(
            project_root, "TutorAgentLambda", "tools.lambda_handlers.tutor_handler.handler", shared_env)
        quiz_fn = self._build_agent_lambda(
            project_root, "QuizAgentLambda", "tools.lambda_handlers.quiz_handler.handler", shared_env)
        reviewer_fn = self._build_agent_lambda(
            project_root, "ReviewerAgentLambda", "tools.lambda_handlers.reviewer_handler.handler", shared_env)

        api = apigw.RestApi(
            self,
            "AirLabApi",
            rest_api_name="AWS Generative AI AirLab API",
            deploy_options=apigw.StageOptions(
                stage_name="lab",
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=False,
                metrics_enabled=True,
            ),
        )

        self._add_agent_route(api, "tutor", tutor_fn)
        self._add_agent_route(api, "quiz", quiz_fn)
        self._add_agent_route(api, "review", reviewer_fn)

        for fn in [tutor_fn, quiz_fn, reviewer_fn, kb_provisioner]:
            logs.LogGroup(
                self,
                f"{fn.node.id}LogGroup",
                log_group_name=f"/aws/lambda/{fn.function_name}",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            )

        CfnOutput(self, "ApiEndpoint", value=api.url)
        CfnOutput(self, "DocsBucketName", value=docs_bucket.bucket_name)
        CfnOutput(self, "VectorsBucketName", value=vectors_bucket.bucket_name)
        CfnOutput(self, "KnowledgeBaseId", value=knowledge_base_id)

    def _build_agent_lambda(
        self,
        project_root: Path,
        name: str,
        handler: str,
        env: dict[str, str],
    ) -> lambda_.Function:
        fn = lambda_.Function(
            self,
            name,
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset(str(project_root), exclude=[
                                         ".venv", "cdk.out", "**/__pycache__"]),
            handler=handler,
            timeout=Duration.seconds(90),
            memory_size=1024,
            environment=env,
        )
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:Converse",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                ],
                resources=["*"],
            )
        )
        return fn

    def _add_agent_route(self, api: apigw.RestApi, route_name: str, fn: lambda_.IFunction) -> None:
        resource = api.root.add_resource(route_name)
        resource.add_method("POST", apigw.LambdaIntegration(fn))

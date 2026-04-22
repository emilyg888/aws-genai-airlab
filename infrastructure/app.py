#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

import aws_cdk as cdk
from dotenv import load_dotenv

from stacks.airlab_stack import AirLabStack
from stacks.trigger_stack import TriggerStack

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = cdk.App()

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION", os.getenv("AWS_REGION", "us-east-1")),
)

airlab = AirLabStack(
    app,
    "AwsGenerativeAiAirLabStack",
    env=env,
    description="Ephemeral local lab for AWS Bedrock RAG and multi-agent workflows.",
)

if os.getenv("DEPLOY_TRIGGER_STACK", "false").lower() == "true":
    trigger = TriggerStack(
        app,
        "AwsGenerativeAiAirLabTriggerStack",
        env=env,
        api_endpoint_param=airlab.api_endpoint_param_name,
        tutor_method_arn=airlab.tutor_method_arn,
        description="Event-driven AI trigger layer (MSK Serverless + consumer/decider Lambdas).",
    )
    trigger.add_dependency(airlab)

app.synth()

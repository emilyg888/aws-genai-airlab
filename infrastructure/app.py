#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

import aws_cdk as cdk
from dotenv import load_dotenv

from stacks.airlab_stack import AirLabStack

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = cdk.App()

AirLabStack(
    app,
    "AwsGenerativeAiAirLabStack",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION", os.getenv("AWS_REGION", "us-east-1")),
    ),
    description="Ephemeral local lab for AWS Bedrock RAG and multi-agent workflows.",
)

app.synth()

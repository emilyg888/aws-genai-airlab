#!/usr/bin/env python3
from __future__ import annotations

import os

import aws_cdk as cdk

from stacks.airlab_stack import AirLabStack


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

"""Hybrid model map — code defaults, SSM overrides (§14.3)."""
from __future__ import annotations

import json
import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger(__name__)

# Governed defaults live in code (review-gated). Override per env via SSM.
# Logical name -> Bedrock modelId (or inference-profile ARN).
DEFAULT_MODEL_MAP: dict[str, str] = {
    "deepseek-v3.2": "amazon.nova-lite-v1:0",
    "deepseek-r1":   "amazon.nova-pro-v1:0",
}

SSM_PARAM_NAME = os.getenv("MODEL_MAP_SSM_PARAM", "/airlab/trigger/model-map")


def get_model_map(region: str | None = None) -> dict[str, str]:
    region = region or os.getenv("AWS_REGION", "us-east-1")
    try:
        client = boto3.client("ssm", region_name=region)
        value = client.get_parameter(Name=SSM_PARAM_NAME)["Parameter"]["Value"]
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("model map must be a JSON object")
        merged = {**DEFAULT_MODEL_MAP, **parsed}  # SSM overrides code
        return merged
    except (ClientError, BotoCoreError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.info("Using default model map (SSM lookup failed: %s)", exc)
        return dict(DEFAULT_MODEL_MAP)


def resolve(logical_name: str, region: str | None = None) -> str:
    """Logical model name -> Bedrock modelId. Falls back to the name itself."""
    mapping = get_model_map(region)
    return mapping.get(logical_name, logical_name)

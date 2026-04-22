from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


class KnowledgeBaseProvisioner:
    """Custom resource handler for Bedrock Knowledge Base lifecycle.

    This skeleton supports dry-run mode by default to keep initial deploys stable.
    Set ENABLE_REAL_KB_CALLS=true to attempt real API calls.
    """

    def __init__(self) -> None:
        region = os.getenv("AWS_REGION", "us-east-1")
        self._client = boto3.client("bedrock-agent", region_name=region)
        self._dry_run = os.getenv("ENABLE_REAL_KB_CALLS", "false").lower() != "true"

    def create_or_update(self, props: dict[str, Any], physical_id: str | None) -> dict[str, Any]:
        name = props["KnowledgeBaseName"]
        data_source_name = props["DataSourceName"]

        if self._dry_run:
            LOGGER.info("Dry-run mode active. Returning mock Knowledge Base identifiers.")
            resource_id = physical_id or f"dryrun-{name[:24]}"
            return {
                "PhysicalResourceId": resource_id,
                "Data": {"KnowledgeBaseId": "", "DataSourceId": ""},
            }

        # Note: S3 Vectors/KB API contract evolves; validate the payload for your region/API version.
        kb_id = self._find_kb_id(name)
        if not kb_id:
            kb_id = self._create_kb(props)

        ds_id = self._find_data_source_id(kb_id, data_source_name)
        if not ds_id:
            ds_id = self._create_data_source(kb_id, props)

        return {
            "PhysicalResourceId": kb_id,
            "Data": {"KnowledgeBaseId": kb_id, "DataSourceId": ds_id},
        }

    def delete(self, props: dict[str, Any], physical_id: str | None) -> dict[str, Any]:
        if self._dry_run or not physical_id:
            return {"PhysicalResourceId": physical_id or "dryrun-delete"}

        kb_id = physical_id
        try:
            data_sources = self._client.list_data_sources(knowledgeBaseId=kb_id).get("dataSourceSummaries", [])
            for ds in data_sources:
                self._client.delete_data_source(
                    knowledgeBaseId=kb_id,
                    dataSourceId=ds["dataSourceId"],
                )
            self._client.delete_knowledge_base(knowledgeBaseId=kb_id)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"ResourceNotFoundException", "ValidationException"}:
                raise

        return {"PhysicalResourceId": kb_id}

    def _find_kb_id(self, name: str) -> str | None:
        paginator = self._client.get_paginator("list_knowledge_bases")
        for page in paginator.paginate():
            for summary in page.get("knowledgeBaseSummaries", []):
                if summary.get("name") == name:
                    return summary["knowledgeBaseId"]
        return None

    def _create_kb(self, props: dict[str, Any]) -> str:
        embedding_model_arn = os.getenv("BEDROCK_EMBEDDING_MODEL_ARN", "")
        if not embedding_model_arn:
            raise ValueError("BEDROCK_EMBEDDING_MODEL_ARN must be set when ENABLE_REAL_KB_CALLS=true")

        response = self._client.create_knowledge_base(
            name=props["KnowledgeBaseName"],
            roleArn=props["KnowledgeBaseRoleArn"],
            knowledgeBaseConfiguration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": embedding_model_arn,
                },
            },
            storageConfiguration={
                "type": "S3_VECTORS",
                "s3VectorsConfiguration": {
                    "vectorBucketArn": f"arn:aws:s3:::{props['VectorBucketName']}",
                    "indexName": "airlab-index",
                },
            },
        )
        return response["knowledgeBase"]["knowledgeBaseId"]

    def _find_data_source_id(self, kb_id: str, ds_name: str) -> str | None:
        paginator = self._client.get_paginator("list_data_sources")
        for page in paginator.paginate(knowledgeBaseId=kb_id):
            for summary in page.get("dataSourceSummaries", []):
                if summary.get("name") == ds_name:
                    return summary["dataSourceId"]
        return None

    def _create_data_source(self, kb_id: str, props: dict[str, Any]) -> str:
        response = self._client.create_data_source(
            knowledgeBaseId=kb_id,
            name=props["DataSourceName"],
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": f"arn:aws:s3:::{props['DocumentBucketName']}",
                    "inclusionPrefixes": ["slides/"],
                },
            },
            vectorIngestionConfiguration={
                "chunkingConfiguration": {
                    "chunkingStrategy": "FIXED_SIZE",
                    "fixedSizeChunkingConfiguration": {
                        "maxTokens": 300,
                        "overlapPercentage": 15,
                    },
                }
            },
        )
        return response["dataSource"]["dataSourceId"]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    LOGGER.info("Custom resource event: %s", event)
    request_type = event["RequestType"]
    props = event.get("ResourceProperties", {})
    physical_id = event.get("PhysicalResourceId")

    provisioner = KnowledgeBaseProvisioner()

    if request_type in {"Create", "Update"}:
        return provisioner.create_or_update(props=props, physical_id=physical_id)
    if request_type == "Delete":
        return provisioner.delete(props=props, physical_id=physical_id)

    raise ValueError(f"Unsupported RequestType: {request_type}")

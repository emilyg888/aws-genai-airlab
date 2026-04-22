from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AirLabConfig:
    # AWS
    aws_region: str

    # Bedrock models
    model_id: str
    embedding_model_id: str

    # Bedrock KB
    knowledge_base_id: str

    # S3 storage
    docs_bucket_name: str
    docs_prefix: str
    vectors_bucket_name: str

    @classmethod
    def from_env(cls) -> "AirLabConfig":
        return cls(
            aws_region=os.getenv("AWS_REGION", "ap-southeast-2"),

            model_id=os.getenv(
                "BEDROCK_MODEL_ID",
                "amazon.nova-lite-v1:0"
            ),

            embedding_model_id=os.getenv(
                "BEDROCK_EMBEDDING_MODEL_ID",
                "amazon.titan-embed-text-v1"
            ),

            knowledge_base_id=os.getenv(
                "KNOWLEDGE_BASE_ID",
                ""
            ),

            docs_bucket_name=os.getenv(
                "DOCS_BUCKET_NAME",
                "aip-c01-aws-genai"
            ),

            docs_prefix=os.getenv(
                "DOCS_PREFIX",
                "knowledge_base/docs/"
            ),

            vectors_bucket_name=os.getenv(
                "VECTOR_BUCKET_NAME",
                "aip-c01-aws-genai-vectors"
            ),
        )

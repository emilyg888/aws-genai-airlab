from __future__ import annotations

import json
import os
import re
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

KB_ID_PATTERN = re.compile(r"^[0-9A-Za-z]{1,10}$")


class BedrockClient:
    def __init__(
        self,
        model_id: str | None = None,
        region_name: str | None = None,
        knowledge_base_id: str | None = None,
    ) -> None:
        self.model_id = model_id or os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.knowledge_base_id = knowledge_base_id or os.getenv("KNOWLEDGE_BASE_ID", "")

        self._runtime = boto3.client("bedrock-runtime", region_name=self.region_name)
        self._agent_runtime = boto3.client("bedrock-agent-runtime", region_name=self.region_name)

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 900,
        temperature: float = 0.2,
        model_id: str | None = None,
    ) -> str:
        try:
            response = self._runtime.converse(
                modelId=model_id or self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
            return response["output"]["message"]["content"][0]["text"]
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Bedrock text generation failed: {exc}") from exc

    def retrieve_context(self, query: str, top_k: int = 4) -> list[str]:
        if not self._has_usable_knowledge_base():
            return []

        try:
            response = self._agent_runtime.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": top_k,
                    }
                },
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Knowledge base retrieval failed: {exc}") from exc

        contexts: list[str] = []
        for item in response.get("retrievalResults", []):
            text = item.get("content", {}).get("text")
            if text:
                contexts.append(text)
        return contexts

    def retrieve_and_generate(self, query: str) -> dict[str, Any]:
        if not self._has_usable_knowledge_base():
            raise ValueError("KNOWLEDGE_BASE_ID is not configured")

        try:
            response = self._agent_runtime.retrieve_and_generate(
                input={"text": query},
                retrieveAndGenerateConfiguration={
                    "type": "KNOWLEDGE_BASE",
                    "knowledgeBaseConfiguration": {
                        "knowledgeBaseId": self.knowledge_base_id,
                        "modelArn": self._model_arn_from_model_id(self.model_id),
                    },
                },
            )
            return response
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"retrieve_and_generate failed: {exc}") from exc

    def _model_arn_from_model_id(self, model_id: str) -> str:
        return f"arn:aws:bedrock:{self.region_name}::foundation-model/{model_id}"

    def _has_usable_knowledge_base(self) -> bool:
        return bool(self.knowledge_base_id and KB_ID_PATTERN.match(self.knowledge_base_id))

    @staticmethod
    def dump_json(data: dict[str, Any]) -> str:
        return json.dumps(data, indent=2, default=str)

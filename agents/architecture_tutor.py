from __future__ import annotations

import json
from typing import Any

from agents.base import AgentResponse, BaseAgent
from tools.bedrock_client import BedrockClient
from tools.diagram_tool import ensure_mermaid_diagram


class ArchitectureTutorAgent(BaseAgent):
    def __init__(self, bedrock: BedrockClient) -> None:
        self._bedrock = bedrock

    def run(self, payload: dict[str, Any]) -> AgentResponse:
        question = payload.get("question", "Explain AWS generative AI architecture patterns.")
        include_diagram = bool(payload.get("include_diagram", True))
        event_context = payload.get("context") or {}
        model_id = payload.get("model")

        contexts = self._bedrock.retrieve_context(question, top_k=4)
        retrieval_text = "\n\n".join(contexts) if contexts else "No retrieval context available."
        event_text = (
            json.dumps(event_context, indent=2, default=str) if event_context else "(none)"
        )

        prompt = f"""
You are an AWS Architecture Tutor.
Use the retrieval context to answer clearly and accurately.
If an event context is provided, ground your answer in it. If the context is
insufficient to decide, say so explicitly.

Question:
{question}

Event context:
{event_text}

Retrieval context:
{retrieval_text}

Respond with:
1) concise explanation
2) key AWS services and responsibilities
3) common implementation pitfalls
""".strip()

        answer = self._bedrock.generate_text(prompt, model_id=model_id)
        response_payload: dict[str, Any] = {
            "answer": answer,
            "context_count": len(contexts),
            "model": model_id or self._bedrock.model_id,
        }

        if include_diagram:
            response_payload["diagram_mermaid"] = ensure_mermaid_diagram(answer)

        return AgentResponse(
            output=response_payload,
            metadata={"agent": "architecture_tutor", "model": response_payload["model"]},
        )

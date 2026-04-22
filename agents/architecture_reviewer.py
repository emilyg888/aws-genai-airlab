from __future__ import annotations

import json
from typing import Any

from agents.base import AgentResponse, BaseAgent
from tools.bedrock_client import BedrockClient
from tools.evaluator_tool import fallback_architecture_score


class ArchitectureReviewerAgent(BaseAgent):
    def __init__(self, bedrock: BedrockClient) -> None:
        self._bedrock = bedrock

    def run(self, payload: dict[str, Any]) -> AgentResponse:
        diagram = payload.get("diagram", "")
        rationale = payload.get("rationale", "")

        prompt = f"""
Review this AWS generative AI architecture.
Score each category from 1 to 10:
- security
- scalability
- cost_efficiency
- reliability
- operational_excellence

Input diagram (mermaid or text):
{diagram}

Author rationale:
{rationale}

Return strict JSON:
{{
  "scores": {{"security":0, "scalability":0, "cost_efficiency":0, "reliability":0, "operational_excellence":0}},
  "overall": 0,
  "strengths": ["..."],
  "risks": ["..."],
  "recommendations": ["..."]
}}
""".strip()

        raw = self._bedrock.generate_text(prompt)
        review = _safe_parse_json(raw) or fallback_architecture_score(diagram=diagram, rationale=rationale)

        return AgentResponse(output=review, metadata={"agent": "architecture_reviewer"})


def _safe_parse_json(content: str) -> dict[str, Any] | None:
    normalized = content.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            normalized = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        return None

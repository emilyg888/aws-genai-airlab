from __future__ import annotations

from typing import Any

from agents.architecture_reviewer import ArchitectureReviewerAgent
from tools.bedrock_client import BedrockClient
from tools.lambda_handlers.common import parse_event, response

BEDROCK = BedrockClient()
AGENT = ArchitectureReviewerAgent(BEDROCK)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    payload = parse_event(event)
    result = AGENT.run(payload)
    return response(200, {"result": result.output, "metadata": result.metadata})

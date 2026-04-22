from __future__ import annotations

from typing import Any

from agents.architecture_reviewer import ArchitectureReviewerAgent
from tools.bedrock_client import BedrockClient
from tools.lambda_handlers.common import run_agent

BEDROCK = BedrockClient()
AGENT = ArchitectureReviewerAgent(BEDROCK)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    return run_agent(AGENT, event)

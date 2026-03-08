from __future__ import annotations

from typing import Any

from agents.architecture_reviewer import ArchitectureReviewerAgent
from agents.architecture_tutor import ArchitectureTutorAgent
from agents.base import AgentResponse
from agents.quiz_generator import QuizGeneratorAgent
from tools.bedrock_client import BedrockClient


class AgentOrchestrator:
    """Simple in-process router for CLI/runtime integration."""

    def __init__(self, bedrock: BedrockClient) -> None:
        self._agents = {
            "tutor": ArchitectureTutorAgent(bedrock),
            "quiz": QuizGeneratorAgent(bedrock),
            "review": ArchitectureReviewerAgent(bedrock),
        }

    def run(self, agent_name: str, payload: dict[str, Any]) -> AgentResponse:
        if agent_name not in self._agents:
            raise ValueError(f"Unknown agent '{agent_name}'. Expected one of: {', '.join(self._agents)}")
        return self._agents[agent_name].run(payload)

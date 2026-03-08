from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResponse:
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    @abstractmethod
    def run(self, payload: dict[str, Any]) -> AgentResponse:
        """Execute agent logic and return a structured response."""

from __future__ import annotations

import json
from typing import Any

from agents.base import AgentResponse, BaseAgent
from tools.bedrock_client import BedrockClient
from tools.evaluator_tool import evaluate_quiz_answers


class QuizGeneratorAgent(BaseAgent):
    def __init__(self, bedrock: BedrockClient) -> None:
        self._bedrock = bedrock

    def run(self, payload: dict[str, Any]) -> AgentResponse:
        topic = payload.get("topic", "AWS Bedrock and RAG")
        count = int(payload.get("count", 5))
        difficulty = payload.get("difficulty", "associate")
        submitted_answers = payload.get("answers")

        prompt = f"""
Create {count} exam-style questions about: {topic}
Difficulty: {difficulty}

Return strict JSON with this schema:
{{
  "questions": [
    {{
      "id": 1,
      "question": "...",
      "options": ["A", "B", "C", "D"],
      "answer": "A",
      "explanation": "..."
    }}
  ]
}}
""".strip()

        raw = self._bedrock.generate_text(prompt)
        quiz = _safe_parse_json(raw)

        result: dict[str, Any] = {"quiz": quiz}
        if submitted_answers:
            result["evaluation"] = evaluate_quiz_answers(quiz=quiz, submitted_answers=submitted_answers)

        return AgentResponse(output=result, metadata={"agent": "quiz_generator"})


def _safe_parse_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"questions": [], "raw": content, "parse_error": "model output was not valid JSON"}

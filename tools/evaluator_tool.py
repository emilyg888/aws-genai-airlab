from __future__ import annotations

from typing import Any


def evaluate_quiz_answers(quiz: dict[str, Any], submitted_answers: dict[str, str]) -> dict[str, Any]:
    questions = quiz.get("questions", [])
    total = len(questions)
    if total == 0:
        return {"score": 0, "total": 0, "details": []}

    correct = 0
    details: list[dict[str, Any]] = []
    for q in questions:
        qid = str(q.get("id"))
        expected = str(q.get("answer", "")).strip().upper()
        got = str(submitted_answers.get(qid, "")).strip().upper()
        ok = expected == got and expected != ""
        if ok:
            correct += 1
        details.append(
            {
                "id": qid,
                "expected": expected,
                "received": got,
                "correct": ok,
                "explanation": q.get("explanation", ""),
            }
        )

    return {
        "score": correct,
        "total": total,
        "percentage": round((correct / total) * 100, 2),
        "details": details,
    }


def fallback_architecture_score(diagram: str, rationale: str) -> dict[str, Any]:
    text = f"{diagram}\n{rationale}".lower()
    has_security = any(k in text for k in ["kms", "iam", "encryption", "waf"])
    has_obs = any(k in text for k in ["cloudwatch", "x-ray", "alarm", "metric"])
    has_scaling = any(k in text for k in ["lambda", "autoscaling", "api gateway"])

    scores = {
        "security": 8 if has_security else 5,
        "scalability": 8 if has_scaling else 5,
        "cost_efficiency": 7,
        "reliability": 8 if has_obs else 5,
        "operational_excellence": 8 if has_obs else 5,
    }
    overall = round(sum(scores.values()) / len(scores), 2)

    return {
        "scores": scores,
        "overall": overall,
        "strengths": [
            "Serverless design reduces persistent compute cost.",
            "RAG workflow uses retrieval before generation.",
        ],
        "risks": [
            "Score may be conservative without full workload context.",
            "Ensure IAM permissions are tightened before production.",
        ],
        "recommendations": [
            "Add explicit threat model and data classification controls.",
            "Add load test targets and SLO-backed CloudWatch alarms.",
        ],
    }

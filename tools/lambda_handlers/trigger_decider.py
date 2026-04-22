"""Decider Lambda — invokes /lab/tutor with the routed model + event context."""
from __future__ import annotations

import logging
import os
from typing import Any

import boto3

from trigger import audit, model_config, sink

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

_SSM = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))

_API_ENDPOINT_PARAM = os.getenv("API_ENDPOINT_SSM_PARAM", "/airlab/api-endpoint")
_PROMPT_TEMPLATES = {
    "fraud_transaction": "Analyse this transaction for fraud signals and recommend action.",
    "support_ticket":    "Triage this ticket and suggest a response stance.",
    "system_alert":      "Summarise severity and probable root cause.",
    "user_signal":       "Explain this user signal and recommend next step.",
}


def _api_endpoint() -> str:
    value = _SSM.get_parameter(Name=_API_ENDPOINT_PARAM)["Parameter"]["Value"]
    return value.rstrip("/")


def _prompt_for(event: dict[str, Any]) -> str:
    return _PROMPT_TEMPLATES.get(
        event.get("event_type", ""),
        "Explain this event and recommend next step.",
    )


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    evt = event["event"]
    route = event.get("route", {}) or {}
    correlation_id = event.get("correlation_id")
    decision = event.get("decision", {}) or {}

    logical_model = route.get("model")
    resolved_model = model_config.resolve(logical_model) if logical_model else None

    payload = {
        "question": _prompt_for(evt),
        "include_diagram": False,
        "model": resolved_model,
        "priority": route.get("priority"),
        "context": {
            **evt,
            "matched_rules": decision.get("matched_rule_ids", []),
            "decision_reason": decision.get("reason"),
        },
    }

    api = _api_endpoint()
    audit.emit_metric("ModelRoutes", model=logical_model or "none",
                      priority=route.get("priority") or "none")

    try:
        response = sink.post_tutor(api, payload, correlation_id=correlation_id)
    except sink.SinkError as exc:
        LOGGER.error("tutor invocation failed: %s", exc)
        audit.emit_metric("TutorInvocations", status="error",
                          model=logical_model or "none")
        audit.write_record({
            "event_id": evt.get("event_id"),
            "decision": decision,
            "route": route,
            "tutor_status": "error",
            "error": str(exc),
            "raw_event": evt,
        })
        raise

    status_bucket = f"{response.status // 100}xx"
    audit.emit_metric("TutorInvocations", status=status_bucket,
                      model=logical_model or "none")
    audit.emit_metric("TutorLatencyMs", value=response.latency_ms, unit="Milliseconds",
                      model=logical_model or "none")

    preview = ""
    answer = response.body.get("result", {}).get("answer") if isinstance(response.body, dict) else None
    if isinstance(answer, str):
        preview = answer[:500]

    audit.write_record({
        "event_id": evt.get("event_id"),
        "received_at": evt.get("timestamp"),
        "decision": decision,
        "route": route,
        "tutor_status": response.status,
        "tutor_latency_ms": response.latency_ms,
        "tutor_response_preview": preview,
        "raw_event": evt,
    })

    return {"status": response.status, "event_id": evt.get("event_id")}

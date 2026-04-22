"""MSK event-source consumer. Validates, decides, async-invokes decider."""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import boto3

from trigger import audit
from trigger.decision import ACTION_IGNORE, ACTION_INVOKE, ACTION_SAMPLE, decide, route_model
from trigger.rules import RuleSet, load as load_rules
from trigger.schema import SchemaError, validate

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

_LAMBDA = boto3.client("lambda", region_name=os.getenv("AWS_REGION", "us-east-1"))
_SSM = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))

_RULES: RuleSet | None = None
_DECIDER_FN = os.getenv("DECIDER_FUNCTION_NAME", "")
_RULES_PATH = os.getenv("RULES_CONFIG_PATH", "config/trigger_rules.json")
_KILL_SWITCH_PARAM = os.getenv("KILL_SWITCH_PARAM", "/airlab/trigger/enabled")


def _rules() -> RuleSet:
    global _RULES
    if _RULES is None:
        # CWD in Lambda is /var/task; the zipped asset root matches project root.
        path = Path(_RULES_PATH)
        if not path.is_absolute():
            path = Path("/var/task") / _RULES_PATH
            if not path.exists():
                path = Path(_RULES_PATH)
        _RULES = load_rules(path)
    return _RULES


def _enabled() -> bool:
    try:
        value = _SSM.get_parameter(Name=_KILL_SWITCH_PARAM)["Parameter"]["Value"]
        return value.lower() == "true"
    except Exception:  # noqa: BLE001 — kill switch default-on when SSM unreachable
        return True


def _parse(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("value")
    if payload is None:
        raise SchemaError("record missing 'value'")
    decoded = base64.b64decode(payload).decode("utf-8")
    return json.loads(decoded)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """MSK event source payload shape: {records: {topic-N: [record, ...]}}."""
    if not _enabled():
        LOGGER.info("kill switch off — no decisions emitted")
        return {"status": "disabled"}

    rules = _rules()
    consumed = 0
    invoked = 0

    for partition_records in (event.get("records") or {}).values():
        for record in partition_records:
            consumed += 1
            try:
                raw = _parse(record)
                event_payload = validate(raw)
            except (SchemaError, json.JSONDecodeError, ValueError) as exc:
                LOGGER.warning("schema reject: %s", exc)
                audit.emit_metric("SchemaRejections", reason=type(exc).__name__)
                continue

            decision = decide(event_payload, rules)
            route = route_model(decision, event_payload)
            audit.emit_metric("Decisions", action=decision.action)
            for rid in decision.matched_rule_ids:
                audit.emit_metric("RuleMatches", rule_id=rid)

            if not route.invoke:
                continue

            invoked += 1
            correlation_id = event_payload.get("event_id") or str(uuid.uuid4())
            async_payload = {
                "event": event_payload,
                "decision": {
                    "action": decision.action,
                    "matched_rule_ids": list(decision.matched_rule_ids),
                    "reason": decision.reason,
                },
                "route": {
                    "model": route.model,
                    "priority": route.priority,
                },
                "correlation_id": correlation_id,
            }
            if not _DECIDER_FN:
                LOGGER.error("DECIDER_FUNCTION_NAME unset — cannot invoke decider")
                continue
            _LAMBDA.invoke(
                FunctionName=_DECIDER_FN,
                InvocationType="Event",
                Payload=json.dumps(async_payload).encode("utf-8"),
            )

    audit.emit_metric("EventsConsumed", value=consumed)
    return {"consumed": consumed, "invoked": invoked}


__all__ = ["handler", "ACTION_INVOKE", "ACTION_IGNORE", "ACTION_SAMPLE"]

"""Event schema validation — zero-dep, hand-rolled to avoid pulling jsonschema."""
from __future__ import annotations

from datetime import datetime
from typing import Any

ALLOWED_EVENT_TYPES = {
    "fraud_transaction",
    "support_ticket",
    "system_alert",
    "user_signal",
}

ALLOWED_SEGMENTS = {"standard", "high_value", "vip"}


class SchemaError(ValueError):
    """Raised when an event fails validation. Message is safe to log."""


def validate(event: Any) -> dict[str, Any]:
    """Validate an inbound event payload. Returns the event on success."""
    if not isinstance(event, dict):
        raise SchemaError("event must be a JSON object")

    for field in ("event_id", "event_type", "timestamp"):
        if field not in event:
            raise SchemaError(f"missing required field: {field}")

    event_id = event["event_id"]
    if not isinstance(event_id, str) or not (1 <= len(event_id) <= 128):
        raise SchemaError("event_id must be a string of length 1..128")

    event_type = event["event_type"]
    if event_type not in ALLOWED_EVENT_TYPES:
        raise SchemaError(f"event_type must be one of {sorted(ALLOWED_EVENT_TYPES)}")

    ts = event["timestamp"]
    if not isinstance(ts, str):
        raise SchemaError("timestamp must be an ISO-8601 string")
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaError(f"timestamp is not valid ISO-8601: {ts}") from exc

    if "amount" in event:
        amount = event["amount"]
        if not isinstance(amount, (int, float)) or amount < 0:
            raise SchemaError("amount must be a non-negative number")

    if "fraud_score" in event:
        score = event["fraud_score"]
        if not isinstance(score, (int, float)) or not 0 <= score <= 1:
            raise SchemaError("fraud_score must be a number in [0, 1]")

    if "customer_segment" in event:
        seg = event["customer_segment"]
        if seg not in ALLOWED_SEGMENTS:
            raise SchemaError(f"customer_segment must be one of {sorted(ALLOWED_SEGMENTS)}")

    return event

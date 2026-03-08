from __future__ import annotations

import json
from typing import Any


def parse_event(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str) and body.strip():
        return json.loads(body)
    return {}


def response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, default=str),
    }

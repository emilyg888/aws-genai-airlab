from __future__ import annotations

import json
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def parse_event(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, dict):
        return body
    if isinstance(body, str) and body.strip():
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON.") from exc
    return {}


def response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, default=str),
    }


def error_response(status_code: int, code: str, message: str) -> dict[str, Any]:
    return response(status_code, {"error": {"code": code, "message": message}})


def run_agent(agent: Any, event: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = parse_event(event)
        result = agent.run(payload)
        return response(200, {"result": result.output, "metadata": result.metadata})
    except ValueError as exc:
        LOGGER.warning("Invalid request: %s", exc)
        return error_response(400, "bad_request", str(exc))
    except RuntimeError as exc:
        LOGGER.exception("Agent runtime failure")
        return error_response(502, "upstream_error", str(exc))
    except Exception:
        LOGGER.exception("Unhandled agent failure")
        return error_response(500, "internal_error", "Internal server error.")

"""SigV4 HTTP sink to API Gateway /lab/tutor.

Uses botocore's signer directly (zero third-party dep). Retries with exponential
backoff on 5xx / throttle errors only.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

LOGGER = logging.getLogger(__name__)

_SESSION = boto3.Session()
_REGION = os.getenv("AWS_REGION", "us-east-1")
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 1.0, 2.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SinkError(RuntimeError):
    pass


@dataclass
class SinkResponse:
    status: int
    body: dict[str, Any]
    latency_ms: int


def post_tutor(
    api_endpoint: str,
    payload: dict[str, Any],
    *,
    correlation_id: str | None = None,
    timeout_s: float = 30.0,
) -> SinkResponse:
    """POST to {api_endpoint}/tutor with SigV4 (execute-api) auth."""
    url = api_endpoint.rstrip("/") + "/tutor"
    body = json.dumps(payload).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        started = time.monotonic()
        try:
            req = AWSRequest(
                method="POST",
                url=url,
                data=body,
                headers={"Content-Type": "application/json"},
            )
            if correlation_id:
                req.headers["X-Correlation-Id"] = correlation_id
            credentials = _SESSION.get_credentials()
            if credentials is None:
                raise SinkError("no AWS credentials available for SigV4")
            SigV4Auth(credentials.get_frozen_credentials(), "execute-api", _REGION).add_auth(req)

            http_req = urllib.request.Request(
                url, data=body, headers=dict(req.headers), method="POST"
            )
            with urllib.request.urlopen(http_req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                latency_ms = int((time.monotonic() - started) * 1000)
                return SinkResponse(status=resp.status, body=json.loads(raw), latency_ms=latency_ms)
        except urllib.error.HTTPError as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            raw = exc.read().decode("utf-8") or "{}"
            if exc.code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
                LOGGER.warning("tutor %s — retrying (%d/%d)", exc.code, attempt + 1, _MAX_ATTEMPTS)
                time.sleep(_BACKOFF_SECONDS[attempt])
                last_err = exc
                continue
            try:
                body_json = json.loads(raw)
            except json.JSONDecodeError:
                body_json = {"error": raw}
            return SinkResponse(status=exc.code, body=body_json, latency_ms=latency_ms)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
                continue
            break

    raise SinkError(f"tutor invocation failed after {_MAX_ATTEMPTS} attempts: {last_err}")

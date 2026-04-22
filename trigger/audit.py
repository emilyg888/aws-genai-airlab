"""Audit log writer (S3 + CloudWatch EMF)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger(__name__)

_S3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
_AUDIT_BUCKET = os.getenv("AUDIT_BUCKET", "")

METRIC_NAMESPACE = "AirLab/Trigger"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def write_record(record: dict[str, Any]) -> None:
    """Write one audit JSON object under events/dt=.../hh=.../<event_id>.json."""
    if not _AUDIT_BUCKET:
        LOGGER.debug("AUDIT_BUCKET not set — skipping audit write")
        return

    event_id = record.get("event_id", "unknown")
    ts = _now()
    key = (
        f"events/dt={ts.strftime('%Y-%m-%d')}/hh={ts.strftime('%H')}/"
        f"{event_id}.json"
    )
    try:
        _S3.put_object(
            Bucket=_AUDIT_BUCKET,
            Key=key,
            Body=json.dumps(record, default=str).encode("utf-8"),
            ContentType="application/json",
        )
    except (ClientError, BotoCoreError) as exc:
        # Never block the pipeline on audit failures; log and move on.
        LOGGER.warning("audit write failed for %s: %s", event_id, exc)


def emit_metric(name: str, value: float = 1.0, unit: str = "Count", **dims: str) -> None:
    """Emit a CloudWatch EMF metric by printing a JSON line to stdout.

    Lambda's CloudWatch Logs agent parses these automatically when the log line
    carries an _aws.CloudWatchMetrics section — no PutMetricData call needed.
    """
    emf = {
        "_aws": {
            "Timestamp": int(_now().timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": METRIC_NAMESPACE,
                    "Dimensions": [list(dims.keys())] if dims else [[]],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        name: value,
        **dims,
    }
    print(json.dumps(emf, default=str))

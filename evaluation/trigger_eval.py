"""Offline replay of audit records from S3 → aggregate trigger metrics.

Reads all JSON objects under s3://{AUDIT_BUCKET}/events/dt=YYYY-MM-DD/ and
prints a JSONL summary: trigger rate, model mix, status distribution, and a
miss-rate proxy derived from sample-tagged records.

Usage:
    python -m evaluation.trigger_eval --bucket BUCKET --date 2026-04-22
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import boto3


@dataclass
class Summary:
    events: int = 0
    invoked: int = 0
    sampled: int = 0
    errors: int = 0
    by_model: dict[str, int] = None  # type: ignore[assignment]
    by_status: dict[str, int] = None  # type: ignore[assignment]
    miss_proxy: int = 0

    def trigger_rate(self) -> float:
        return self.invoked / self.events if self.events else 0.0


def _iter_records(bucket: str, prefix: str) -> Iterable[dict[str, Any]]:
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            try:
                yield json.loads(body)
            except json.JSONDecodeError:
                continue


def summarise(records: Iterable[dict[str, Any]]) -> Summary:
    model_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    events = invoked = sampled = errors = miss = 0

    for r in records:
        events += 1
        decision = (r.get("decision") or {}).get("action", "ignore")
        route = r.get("route") or {}
        model = route.get("model") or "none"
        status = r.get("tutor_status", "n/a")

        if decision == "invoke_ai":
            invoked += 1
        elif decision == "sample":
            sampled += 1

        model_counts[str(model)] += 1
        status_counts[str(status)] += 1

        if status == "error":
            errors += 1

        # Miss proxy: sample-tagged calls whose answer surfaces a meaningful signal
        # the rules didn't catch. Heuristic: preview mentions "risk", "fraud", or "urgent".
        if decision == "sample":
            preview = (r.get("tutor_response_preview") or "").lower()
            if any(k in preview for k in ("risk", "fraud", "urgent", "severe")):
                miss += 1

    return Summary(
        events=events,
        invoked=invoked,
        sampled=sampled,
        errors=errors,
        by_model=dict(model_counts),
        by_status=dict(status_counts),
        miss_proxy=miss,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger-layer offline eval")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args(argv)

    prefix = f"events/dt={args.date}/"
    summary = summarise(_iter_records(args.bucket, prefix))
    payload = asdict(summary) | {"trigger_rate": round(summary.trigger_rate(), 4)}
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

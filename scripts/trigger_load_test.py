"""Synthetic event producer for the MSK Serverless `ai-events` topic.

Uses kafka-python with IAM SASL. Kept as a lab utility — not packaged into the
Lambdas. Install deps separately:

    pip install kafka-python aws-msk-iam-sasl-signer-python

Usage:
    python scripts/trigger_load_test.py --bootstrap broker:9098 --count 1000
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone


def _event(rng: random.Random) -> dict:
    event_type = rng.choice(
        ["fraud_transaction", "support_ticket", "system_alert", "user_signal"]
    )
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "amount": round(rng.expovariate(1 / 2000), 2),
        "fraud_score": round(rng.random(), 3),
        "customer_segment": rng.choices(
            ["standard", "high_value", "vip"], weights=[80, 15, 5]
        )[0],
        "producer": "load-test",
    }


def _make_producer(bootstrap: str):
    try:
        from kafka import KafkaProducer
        from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
    except ImportError as exc:  # pragma: no cover — lab-only utility
        print(f"Missing dep: {exc}. Run: pip install kafka-python "
              "aws-msk-iam-sasl-signer-python", file=sys.stderr)
        raise SystemExit(1)

    def _token():
        token, _ = MSKAuthTokenProvider.generate_auth_token(
            __import__("os").environ.get("AWS_REGION", "us-east-1")
        )
        return token, int(time.time() * 1000)

    return KafkaProducer(
        bootstrap_servers=bootstrap.split(","),
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=type("P", (), {"token": staticmethod(_token)}),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
        acks="all",
        linger_ms=10,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger load test")
    parser.add_argument("--bootstrap", required=True, help="MSK bootstrap (broker:9098,...)")
    parser.add_argument("--topic", default="ai-events")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--rate", type=float, default=10.0, help="events per second")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    producer = _make_producer(args.bootstrap)
    interval = 1.0 / args.rate

    for _ in range(args.count):
        evt = _event(rng)
        producer.send(args.topic, key=evt["event_id"], value=evt)
        time.sleep(interval)
    producer.flush()
    print(f"produced {args.count} events to {args.topic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

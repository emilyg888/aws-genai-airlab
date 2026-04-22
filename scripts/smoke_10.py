"""Send 10 crafted events through the trigger consumer and print a summary.

Shape: 5 ignored by Signal Layer, 3 invoke and pass, 2 invoke and hit Bedrock
content filters. Exercises consumer -> decide -> route -> decider -> tutor
end-to-end without a real Kafka producer (invokes the consumer Lambda with an
MSK-shaped event envelope).
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

import boto3

REGION = "ap-southeast-2"
STACK = "AwsGenerativeAiAirLabTriggerStack"

EVENTS: list[dict[str, Any]] = [
    # --- 2 expected to trigger AND hit content filter -----------------------
    {"_label": "A1 trigger+filter",  "event_type": "fraud_transaction",
     "fraud_score": 0.99, "amount": 50000, "customer_segment": "vip"},
    {"_label": "A2 trigger+filter",  "event_type": "fraud_transaction",
     "fraud_score": 0.98, "amount": 25000, "customer_segment": "vip"},

    # --- 3 expected to trigger AND pass ------------------------------------
    {"_label": "B1 trigger softprompt", "event_type": "support_ticket",
     "customer_segment": "vip"},
    {"_label": "B2 trigger amount",     "event_type": "user_signal",
     "amount": 15000, "customer_segment": "high_value"},
    {"_label": "B3 trigger segment",    "event_type": "system_alert",
     "customer_segment": "high_value"},

    # --- 5 expected to be ignored by Signal Layer --------------------------
    {"_label": "C1 ignore low-score",   "event_type": "fraud_transaction",
     "fraud_score": 0.30, "amount": 100, "customer_segment": "standard"},
    {"_label": "C2 ignore support std", "event_type": "support_ticket",
     "customer_segment": "standard"},
    {"_label": "C3 ignore user_signal", "event_type": "user_signal",
     "customer_segment": "standard"},
    {"_label": "C4 ignore sys_alert",   "event_type": "system_alert",
     "customer_segment": "standard"},
    {"_label": "C5 ignore small amt",   "event_type": "fraud_transaction",
     "fraud_score": 0.50, "amount": 500, "customer_segment": "standard"},
]


def _consumer_name() -> str:
    cf = boto3.client("cloudformation", region_name=REGION)
    for r in cf.describe_stack_resources(StackName=STACK)["StackResources"]:
        if (r["ResourceType"] == "AWS::Lambda::Function"
                and "Consumer" in r["LogicalResourceId"]):
            return r["PhysicalResourceId"]
    raise RuntimeError("Consumer Lambda not found")


def main() -> None:
    fn = _consumer_name()
    lam = boto3.client("lambda", region_name=REGION)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    print(f"{'label':28}  {'event_id':20}  consumer_response")
    print("-" * 90)
    for spec in EVENTS:
        label = spec.pop("_label")
        event = {"event_id": f"smoke-{uuid.uuid4().hex[:8]}",
                 "timestamp": now, **spec}
        envelope = {
            "records": {
                "ai-events-0": [
                    {"value": base64.b64encode(
                        json.dumps(event).encode()).decode()}
                ]
            }
        }
        r = lam.invoke(
            FunctionName=fn,
            InvocationType="RequestResponse",
            Payload=json.dumps(envelope).encode(),
        )
        body = json.loads(r["Payload"].read())
        print(f"{label:28}  {event['event_id']:20}  {body}")


if __name__ == "__main__":
    main()

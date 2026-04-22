# Detailed Design — Event-Driven AI Trigger Layer

Companion to [HL_Design_Event_Driven_AI_Trigger.md](HL_Design_Event_Driven_AI_Trigger.md).
Target repo: `aws-genai-airlab`. Target stage: `lab`. Target region: value of
`AWS_REGION` / `CDK_DEFAULT_REGION` (existing env contract in `infrastructure/app.py`).

---

## 1. Scope and Non-Goals

### In scope
- New CDK stack `TriggerStack` that provisions MSK Serverless + two Lambdas + SQS DLQs.
- New Python packages `trigger/` (rules + decision engine) and `tools/lambda_handlers/trigger_*`.
- Reuse of the existing API Gateway `/lab/tutor` route and `TutorAgentLambda`
  (defined in `infrastructure/stacks/airlab_stack.py`).
- Config-driven trigger thresholds so rules can be tuned without redeploying code.
- Event-level observability (CloudWatch metrics, structured logs, S3 audit mirror).

### Out of scope
- Authentication on `/lab/tutor`. API is IAM-signed for the trigger Lambda only;
  public auth is out of scope for this iteration.
- Replacing the existing `tutor_handler`.
- Multi-region / HA. This is a single-region lab.
- Schema registry (Glue/Confluent). Schema is validated in code only.

---

## 2. Module and File Layout

```text
aws-genai-airlab/
├── trigger/                         # NEW
│   ├── __init__.py
│   ├── schema.py                    # TypedDict + jsonschema validation
│   ├── rules.py                     # should_trigger + rule config loader
│   ├── decision.py                  # decide() orchestration
│   ├── sink.py                      # HTTP signer → API Gateway /lab/tutor
│   └── audit.py                     # S3 + CloudWatch EMF writer
├── tools/lambda_handlers/
│   ├── trigger_consumer.py          # NEW — MSK event source handler
│   └── trigger_decider.py           # NEW — invoked via async payload OR direct
├── infrastructure/stacks/
│   ├── airlab_stack.py              # (existing — minor: export api.url as SSM param)
│   └── trigger_stack.py             # NEW
├── evaluation/
│   └── trigger_eval.py              # NEW — offline replay + metrics
└── docs/
    ├── HL_Design_Event_Driven_AI_Trigger.md
    └── LL_Design_Event_Driven_AI_Trigger.md   # this file
```

Rationale: keep rule logic in `trigger/` (pure Python, unit-testable without AWS).
Handlers stay thin wrappers as `tutor_handler.py` already does.

---

## 3. Event Schema

### 3.1 Canonical schema (`trigger/schema.py`)

```python
EVENT_SCHEMA = {
    "type": "object",
    "required": ["event_id", "event_type", "timestamp"],
    "additionalProperties": True,
    "properties": {
        "event_id":          {"type": "string", "minLength": 1, "maxLength": 128},
        "event_type":        {"type": "string", "enum": [
                                "fraud_transaction", "support_ticket",
                                "system_alert", "user_signal"]},
        "timestamp":         {"type": "string", "format": "date-time"},
        "amount":            {"type": "number", "minimum": 0},
        "fraud_score":       {"type": "number", "minimum": 0, "maximum": 1},
        "customer_segment":  {"type": "string", "enum": [
                                "standard", "high_value", "vip"]},
        "producer":          {"type": "string"},
    },
}
```

Invalid events are routed to the consumer DLQ (§6) and counted against the
`SchemaRejections` metric. Events are **not** dropped silently.

### 3.2 Kafka message contract
- Topic: `ai-events` (single topic; partition key = `event_id` hash).
- Partitions: 3 (MSK Serverless default).
- Key: UTF-8 string of `event_id`.
- Value: UTF-8 JSON matching `EVENT_SCHEMA`.
- Retention: 24h (cost guard; replay done from S3 audit, not Kafka).

---

## 4. Trigger Rules (Signal Layer)

The trigger rules represent the streaming implementation of the **Signal Layer**,
validating signals before AI invocation. This ties the full pipeline together:

```text
air-lab-os  →  Signal Layer  →  Kafka (ai-events)  →  Trigger  →  AI
            (patterns/rules)                        (decide)   (route)
```

Promotions from `air-lab-os` (silver/gold patterns) surface here as new rules
in `config/trigger_rules.yaml` — the same expressions, evaluated in real time.

### 4.1 Rule config (`config/trigger_rules.yaml`, packaged into Lambda)

```yaml
version: 1
rules:
  - id: high_fraud_score
    when: "fraud_score > 0.80"
    reason: "fraud_score above threshold"
  - id: high_value_amount
    when: "amount > 10000"
    reason: "amount above threshold"
  - id: vip_customer
    when: "customer_segment in ['high_value', 'vip']"
    reason: "elevated customer segment"
sampling:
  baseline_invoke_rate: 0.01   # 1% random sample of non-triggered events
                               # — guards against drift in the rule set
```

Expressions are evaluated with `asteval` (safe eval, no builtins), not `eval()`.

### 4.2 Decision function (`trigger/decision.py`)

```python
def decide(event: dict, rules: RuleSet, now: datetime) -> Decision:
    # Returns Decision(action: Literal["invoke_ai","ignore","sample"],
    #                  matched_rule_ids: list[str],
    #                  reason: str)
```

Rule evaluation order:
1. Schema validate. Fail → `reject` (DLQ).
2. Evaluate all rules. Any match → `invoke_ai`, record all matched rule IDs.
3. No match → with probability `baseline_invoke_rate`, return `sample` (also invokes AI, tagged for evaluation). Otherwise `ignore`.

The `sample` path is what makes §9 evaluation possible without a human label set.

### 4.3 Model routing (`trigger/decision.py`)

A second decision: *which* model handles the invocation. Default is the cheap,
fast model; escalate only when the event signals high value or high complexity.
Keeps the trigger layer's cost discipline intact even after we decide to invoke.

```python
def route_model(decision: str, event: dict) -> dict:
    # Default model (cheap, fast)
    model = "deepseek-v3.2"

    if decision == "invoke_ai":
        # Escalation conditions (only high-value / complex cases)
        if (
            event.get("fraud_score", 0) > 0.95
            or event.get("amount", 0) > 20000
            or event.get("customer_segment") == "vip"
        ):
            model = "deepseek-r1"   # higher reasoning capability
        return {"invoke": True, "model": model, "priority": "high"}

    if decision == "sample":
        # Always cheap model for evaluation path
        return {"invoke": True, "model": "deepseek-v3.2", "priority": "evaluation"}

    return {"invoke": False, "model": None}
```

**Model-ID mapping.** `deepseek-v3.2` / `deepseek-r1` are logical names. The
decider resolves them to Bedrock model ARNs via a lookup in SSM
(`/airlab/trigger/model-map`) so the mapping is hot-swappable without redeploy.
If a logical name isn't available in-region, the map falls back to Claude tiers
(Haiku → Sonnet) — Bedrock-native, same tier semantics.

| Logical name   | Primary (Bedrock Marketplace) | Fallback (Bedrock-native) |
|----------------|-------------------------------|---------------------------|
| `deepseek-v3.2`| DeepSeek-V3 serverless        | Claude 3.5 Haiku          |
| `deepseek-r1`  | DeepSeek-R1 serverless        | Claude 3.5 Sonnet         |

---

## 5. Lambda Functions

### 5.1 `trigger_consumer.py` — MSK event source

- Event source mapping: MSK Serverless, `BatchSize=50`, `MaximumBatchingWindowInSeconds=5`.
- For each record:
  1. Base64-decode `value`, JSON-parse.
  2. Validate schema. On failure, send to consumer DLQ (SQS) with reason tag.
  3. Call `decide(event, rules, now)`.
  4. For `invoke_ai` / `sample`: async-invoke `trigger_decider` Lambda with a
     minimal payload (`event_id`, raw event, decision). Async so consumer lag
     tracks Kafka, not Bedrock latency.
  5. Emit EMF metrics (§8) and write audit record (§9).
- Idempotency: `event_id` is the dedupe key — the decider checks a DynamoDB TTL
  table (optional, toggled off in lab by default) before invoking the API.
  In lab mode: at-least-once delivery is accepted.

### 5.2 `trigger_decider.py` — AI invocation

- Input: `{event, decision}` from consumer.
- Calls `route_model(decision, event)` (§4.3) to pick model + priority.
- Builds payload per HL §5:
  ```json
  { "query": "...", "context": { ...event_payload } }
  ```
- Query template is keyed off `event_type`:
  - `fraud_transaction` → "Analyse this transaction for fraud signals and recommend action."
  - `support_ticket`    → "Triage this ticket and suggest a response stance."
  - `system_alert`      → "Summarise severity and probable root cause."
  - fallback            → generic explain-this-event prompt.
- Invokes `POST {ApiEndpoint}/lab/tutor` with SigV4-signed request (IAM auth).
  Retries: 3 attempts, exponential backoff (0.5s, 1s, 2s), only on 5xx/Throttle.
- On non-retriable error or exhausted retries → decider DLQ (SQS).
- Writes final audit record with the tutor response and latency.

### 5.3 Why two Lambdas
Keeps Kafka consumer hot and cheap (no Bedrock dependency); isolates Bedrock
throttling and latency from MSK consumer lag. Matches the HL diagram's split
between "Event Consumer" and "Trigger Layer".

---

## 6. CDK — `trigger_stack.py`

Construct outline (same style as existing `AirLabStack`):

```python
class TriggerStack(Stack):
    def __init__(self, scope, construct_id, *, api_endpoint_ssm: str, **kw):
        super().__init__(scope, construct_id, **kw)

        # --- MSK Serverless ---
        vpc = ec2.Vpc(self, "TriggerVpc", max_azs=2, nat_gateways=0)
        sg  = ec2.SecurityGroup(self, "MskSg", vpc=vpc)
        cluster = msk.CfnServerlessCluster(
            self, "EventCluster",
            cluster_name="ai-events-cluster",
            client_authentication={"sasl": {"iam": {"enabled": True}}},
            vpc_configs=[{"subnetIds": vpc.select_subnets(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED).subnet_ids,
                "securityGroups": [sg.security_group_id]}],
        )

        # --- DLQs ---
        consumer_dlq = sqs.Queue(self, "ConsumerDlq",
            retention_period=Duration.days(14))
        decider_dlq  = sqs.Queue(self, "DeciderDlq",
            retention_period=Duration.days(14))

        # --- Audit bucket (reuse DocsBucket? No — separate for lifecycle) ---
        audit_bucket = s3.Bucket(self, "AuditBucket",
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
            removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED, enforce_ssl=True)

        # --- Decider Lambda ---
        decider = lambda_.Function(self, "TriggerDeciderLambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="tools.lambda_handlers.trigger_decider.handler",
            code=lambda_.Code.from_asset(str(project_root), exclude=[...]),
            timeout=Duration.seconds(60), memory_size=512,
            dead_letter_queue=decider_dlq,
            environment={
                "API_ENDPOINT_SSM_PARAM": api_endpoint_ssm,
                "AUDIT_BUCKET": audit_bucket.bucket_name,
                "AWS_REGION": self.region,
            })
        audit_bucket.grant_write(decider)
        decider.add_to_role_policy(iam.PolicyStatement(
            actions=["execute-api:Invoke", "ssm:GetParameter"],
            resources=["*"]))   # tighten to api ARN in a follow-up

        # --- Consumer Lambda ---
        consumer = lambda_.Function(self, "TriggerConsumerLambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="tools.lambda_handlers.trigger_consumer.handler",
            code=lambda_.Code.from_asset(str(project_root), exclude=[...]),
            timeout=Duration.seconds(30), memory_size=512,
            vpc=vpc, security_groups=[sg],
            dead_letter_queue=consumer_dlq,
            environment={
                "DECIDER_FUNCTION_NAME": decider.function_name,
                "AUDIT_BUCKET": audit_bucket.bucket_name,
                "RULES_CONFIG_PATH": "config/trigger_rules.yaml",
            })
        decider.grant_invoke(consumer)
        audit_bucket.grant_write(consumer)
        consumer.add_to_role_policy(iam.PolicyStatement(
            actions=["kafka-cluster:Connect",
                     "kafka-cluster:DescribeGroup",
                     "kafka-cluster:AlterGroup",
                     "kafka-cluster:DescribeTopic",
                     "kafka-cluster:ReadData",
                     "kafka-cluster:DescribeClusterDynamicConfiguration"],
            resources=[cluster.attr_arn, f"{cluster.attr_arn}/*"]))

        consumer.add_event_source(lambda_event_sources.ManagedKafkaEventSource(
            cluster_arn=cluster.attr_arn,
            topic="ai-events",
            starting_position=lambda_.StartingPosition.LATEST,
            batch_size=50, max_batching_window=Duration.seconds(5)))

        CfnOutput(self, "EventClusterArn", value=cluster.attr_arn)
        CfnOutput(self, "AuditBucketName", value=audit_bucket.bucket_name)
```

### 6.1 Cross-stack contract
`AirLabStack` exports the API URL via SSM:
```python
ssm.StringParameter(self, "ApiEndpointParam",
    parameter_name="/airlab/api-endpoint", string_value=api.url)
```
`TriggerStack` reads the SSM name from its constructor and passes it to the
decider Lambda at runtime. This avoids a hard CloudFormation dependency and
lets the two stacks be destroyed/rebuilt independently.

---

## 7. Request to `/lab/tutor`

`trigger_decider` sends:

```http
POST /lab/tutor HTTP/1.1
Host: <api>.execute-api.<region>.amazonaws.com
Content-Type: application/json
Authorization: AWS4-HMAC-SHA256 ...   (SigV4, Lambda execution role)

{
  "question": "<event_type-specific prompt>",
  "include_diagram": false,
  "model": "deepseek-r1",
  "priority": "high",
  "context": {
    "event_id": "123",
    "event_type": "fraud_transaction",
    "amount": 5000,
    "fraud_score": 0.97,
    "customer_segment": "vip",
    "matched_rules": ["high_fraud_score", "vip_customer"]
  }
}
```

Note: `ArchitectureTutorAgent.run` currently reads `payload["question"]` and
`payload["include_diagram"]` (see [architecture_tutor.py:15-16](agents/architecture_tutor.py:15)).
`context` is accepted as additional payload but not yet consumed by the tutor
prompt. **A follow-up change** (out of scope for this design) should include
`context` in the tutor prompt when present, so event metadata actually informs
the answer. Calling that out explicitly so it isn't missed.

---

## 8. Observability

### 8.1 CloudWatch EMF metrics (namespace `AirLab/Trigger`)

| Metric                | Dimensions              | Source     |
|-----------------------|-------------------------|------------|
| `EventsConsumed`      | `topic`                 | consumer   |
| `SchemaRejections`    | `topic`, `reason`       | consumer   |
| `Decisions`           | `action` (invoke/ignore/sample) | consumer |
| `RuleMatches`         | `rule_id`               | consumer   |
| `TutorInvocations`    | `status` (2xx/4xx/5xx), `model` | decider |
| `TutorLatencyMs`      | `model`                 | decider    |
| `ModelRoutes`         | `model`, `priority`     | decider    |
| `BedrockCostUsd`      | `model`                 | decider (from API response metadata) |

### 8.2 Structured logs
Every log line is JSON with `event_id`, `decision`, `matched_rule_ids`,
`correlation_id`. Correlation ID propagates consumer → decider → tutor via
`X-Correlation-Id` header (tutor Lambda is unchanged; header is logged by API
Gateway access logs).

### 8.3 Audit records in S3
Path: `s3://<audit-bucket>/events/dt=YYYY-MM-DD/hh=HH/<event_id>.json`

```json
{
  "event_id": "...", "received_at": "...", "decision": {...},
  "tutor_status": 200, "tutor_latency_ms": 812,
  "tutor_response_preview": "first 500 chars",
  "raw_event": {...}
}
```

30-day lifecycle (lab budget).

---

## 9. Evaluation Strategy

### 9.1 Online (continuous)
- **Trigger rate** = `Decisions[invoke_ai] / EventsConsumed`. Alarm if > 50%
  over 1h (rules too loose) or < 1% (rules too tight).
- **Cost saved** = `(EventsConsumed − TutorInvocations) × avg_cost_per_invoke`.
- **Error rate** = `TutorInvocations[5xx] / TutorInvocations`.

### 9.2 Offline (`evaluation/trigger_eval.py`)
- Reads audit JSON from S3 for a date range.
- For `sample`-tagged events (random 1% of `ignore`s), computes what the AI
  *would* have said and flags cases where the sampled response surfaces a
  signal the rules missed ("**miss**"). This is the HL §6 Miss Rate.
- Writes a JSONL report compatible with existing `evaluation/run_eval.py`
  style so reports land in the same place.

### 9.3 Load test
`scripts/trigger_load_test.py` (new) — produces synthetic events to the topic
via `kafka-python` with IAM SASL. Scenarios:
- 1k events @ 10 rps, 5% above threshold → verify trigger rate ≈ 5% + sample.
- Burst: 500 events in 10s → verify consumer lag drains in < 60s.

---

## 10. Security & Governance

1. **Schema validation is mandatory**; no event reaches the decider without passing.
2. **Prompt control**: query templates live in code, not in the event. The event
   only provides `context`. Prevents prompt injection from upstream producers.
3. **IAM least-privilege**:
   - Consumer: read `ai-events` topic only; invoke decider only.
   - Decider: `execute-api:Invoke` on the specific tutor method ARN only;
     tighten from `*` in a follow-up PR once stack outputs expose the method ARN.
4. **No PII in logs**: audit log stores `tutor_response_preview` (first 500 chars)
   and raw event. If real PII ever arrives, add a redactor in `trigger/audit.py`
   before writing — called out here so it isn't forgotten when moving off lab data.
5. **Kill switch**: SSM param `/airlab/trigger/enabled` (default `true`). Consumer
   short-circuits to `ignore` when `false`. Lets us disable AI invocation without
   stopping Kafka consumption or redeploying.

---

## 11. Cost Model (per HL §9, concrete numbers)

Assumes us-east-1 prices as of Q1 2026, 100k events/day, 5% triggered:

| Component               | Unit cost                  | Monthly |
|-------------------------|----------------------------|---------|
| MSK Serverless base     | $0.75/hr cluster           | ~$16 (lab hours) |
| MSK Serverless partition| $0.0015/partition-hr × 3   | ~$3     |
| MSK Serverless storage  | $0.10/GB-mo, ~1GB          | $0.10   |
| Lambda (consumer)       | 100k × 50ms × 512MB        | <$1     |
| Lambda (decider)        | 5k × 1s × 512MB            | <$1     |
| Bedrock (Claude 3.5 Sonnet) | ~$0.015/invoke avg     | ~$75 @ 5k invokes |
| S3 audit                | 30-day retention, <5GB     | <$1     |
| CloudWatch logs+EMF     | 14-day retention           | ~$5     |
| **Total**               |                            | **~$100/mo** |

Sits inside the $200 budget with headroom. The dominant cost remains Bedrock —
which is the point of the trigger layer.

---

## 12. Test Plan

### 12.1 Unit (pytest, no AWS)
- `test_schema.py` — valid/invalid payload matrix.
- `test_rules.py` — each rule fires only when expected; combinations; unknown field handling.
- `test_decision.py` — `invoke_ai` / `ignore` / `sample` given fixed RNG seed.
- `test_sink.py` — SigV4 signing with mocked credentials; retry/backoff with
  `responses` or `botocore.stub`.

### 12.2 Integration (deployed lab)
1. Produce a known-bad event (schema violation) → verify DLQ depth + metric.
2. Produce a high-fraud event → verify audit record + tutor 200 + latency metric.
3. Produce a low-signal event → verify `ignore` (unless sampled).
4. Toggle kill switch → verify all decisions become `ignore`.

### 12.3 Regression
Existing `runtime.cli tutor` path must still work unchanged — no edits to
`tutor_handler.py` or `architecture_tutor.py` required by this design.

---

## 13. Rollout Steps

1. Merge `trigger/` package with unit tests (no deploy).
2. Add SSM param export to `AirLabStack`.
3. Deploy `TriggerStack` to lab account with kill switch **disabled**
   (`/airlab/trigger/enabled=false`); verify MSK + Lambdas provision cleanly.
4. Run `scripts/trigger_load_test.py` with kill switch still off — confirms
   consumer path and audit logging without burning Bedrock.
5. Enable kill switch; run load test again; verify tutor invocations and cost.
6. Tune thresholds in `config/trigger_rules.yaml` based on first eval report.
7. Document destroy order in `scripts/destroy.sh`: `TriggerStack` before
   `AirLabStack` (SSM param is a soft dep, but audit bucket and MSK should go first).

---

## 14. Decisions

### 14.1 Tutor honours `model` and `context` (P1 — resolved)

Without propagating `model` and `context` into the LLM call, the architecture
decision layer is **observational, not functional**. Fixed now, not deferred.

Minimal code changes (already applied):

- [tools/bedrock_client.py](tools/bedrock_client.py) — `generate_text` accepts
  optional `model_id` override; falls back to `self.model_id` when absent.
- [agents/architecture_tutor.py](agents/architecture_tutor.py) — reads
  `payload["context"]` and `payload["model"]`, injects the event context into
  the prompt alongside retrieval context, passes `model_id` through to Bedrock,
  and echoes the resolved model in the response and metadata for auditability.

Routing effects are now end-to-end: `route_model()` in the decider picks the
tier, the tutor uses it, and the response tags which model actually ran.

### 14.2 Idempotency — at-least-once in lab, extensible for prod

At-least-once delivery is acceptable for the lab (cost of a duplicate invoke is
low; events are idempotent in effect). The design **leaves a seam** for prod:

```python
# trigger/decision.py — feature-flagged, default off
IDEMPOTENCY_ENABLED = os.getenv("IDEMPOTENCY_ENABLED", "false").lower() == "true"

if IDEMPOTENCY_ENABLED:
    if already_processed(event_id):     # DynamoDB conditional put
        return Decision.skip("duplicate")
    mark_processed(event_id, ttl=86400)
```

When moving to prod, provision a DynamoDB table with `event_id` as PK and a
24h TTL, flip the flag. No other code change required.

### 14.3 Model map — hybrid (code defaults + SSM overrides)

Neither pole alone is right:

| Option       | Drawback                              |
|--------------|---------------------------------------|
| Code only    | no runtime flexibility                |
| SSM only     | no review, drift risk between envs    |
| **Hybrid**   | **governed defaults, flexible overrides** |

```python
# trigger/model_config.py
DEFAULT_MODEL_MAP = {
    "deepseek-v3.2": "<bedrock-arn-for-deepseek-v3>",
    "deepseek-r1":   "<bedrock-arn-for-deepseek-r1>",
}

def get_model_map() -> dict[str, str]:
    try:
        return json.loads(ssm.get_parameter(Name="/airlab/trigger/model-map")
                          ["Parameter"]["Value"])
    except Exception:
        return DEFAULT_MODEL_MAP
```

Defaults live in code and go through code review; operators can override per
environment via SSM without a deploy.

---

## 15. Final State

```text
Kafka event
   ↓
Trigger Layer  (Signal Layer — §4)
   ↓
Decision       (invoke? + which model? — §4.2, §4.3)
   ↓
API Gateway /lab/tutor
   ↓
Tutor Lambda   (context-aware prompt — §14.1)
   ↓
Bedrock        (model-aware invocation — §14.1)
   ↓
Response
   ↓
Evaluation + Logging  (§8, §9)
```

Routing decisions are observable via CloudWatch (`ModelRoutes` metric, §8.1)
and now *functionally* applied — the model that ran is echoed in the tutor
response, so we can validate whether routing is actually improving outcomes.


What happens on a re-run:

cdk bootstrap — no-op if already bootstrapped.
cdk deploy --all — diffs your stack against the deployed state and only applies changes. Unchanged resources are left alone.
pip install — no-op if deps already satisfied.
Things that persist across re-runs (by design, not destroyed):

S3 buckets and their contents (DocsBucket, VectorsBucket, AuditBucket).
Knowledge Base ID and ingested data.
MSK cluster and any retained messages.
SSM parameters like /airlab/api-endpoint and /airlab/trigger/enabled.

When you do need to re-run deploy:

After editing Lambda source (e.g. agents/architecture_tutor.py) — redeploy ships the new code.
After changing env toggles: flipping DEPLOY_TRIGGER_STACK, TRIGGER_ENABLE_EVENT_SOURCE, or TRIGGER_DEFAULT_ENABLED.
After editing any file under infrastructure/stacks/.

 ✅  AwsGenerativeAiAirLabStack

✨  Deployment time: 69.23s

Outputs:
AwsGenerativeAiAirLabStack.AirLabApiEndpointE480E6E0 = https://ymlvrnx0t7.execute-api.ap-southeast-2.amazonaws.com/lab/
AwsGenerativeAiAirLabStack.ApiEndpoint = https://ymlvrnx0t7.execute-api.ap-southeast-2.amazonaws.com/lab/
AwsGenerativeAiAirLabStack.ApiEndpointParamName = /airlab/api-endpoint
AwsGenerativeAiAirLabStack.DocsBucketName = awsgenerativeaiairlabstack-docsbucketecea003f-qzhfbztvbzq7
AwsGenerativeAiAirLabStack.ExportsOutputRefAirLabApiBE583285959670FE = ymlvrnx0t7
AwsGenerativeAiAirLabStack.ExportsOutputRefApiEndpointParamFEC4922094BB08A3 = /airlab/api-endpoint
AwsGenerativeAiAirLabStack.KnowledgeBaseId = dryrun-aws-genai-airlab-kb
AwsGenerativeAiAirLabStack.VectorsBucketName = awsgenerativeaiairlabstack-vectorsbucket7255138c-oksw61aki0nw

 ✅  AwsGenerativeAiAirLabTriggerStack

✨  Deployment time: 263.67s

Outputs:
AwsGenerativeAiAirLabTriggerStack.AuditBucketName = awsgenerativeaiairlabtriggerst-auditbucketb01e0ae8-6mrko5bw8rb3
AwsGenerativeAiAirLabTriggerStack.ConsumerDlqUrl = https://sqs.ap-southeast-2.amazonaws.com/884692409741/AwsGenerativeAiAirLabTriggerStack-ConsumerDlq764F6C13-33N5IpqplPvC
AwsGenerativeAiAirLabTriggerStack.DeciderDlqUrl = https://sqs.ap-southeast-2.amazonaws.com/884692409741/AwsGenerativeAiAirLabTriggerStack-DeciderDlq37DFEE78-qWTDQoh0Od5R
AwsGenerativeAiAirLabTriggerStack.EventClusterArn = arn:aws:kafka:ap-southeast-2:884692409741:cluster/ai-events-cluster/0afc26d5-2a5a-4459-b13f-dab229edfbd4-s2
AwsGenerativeAiAirLabTriggerStack.KillSwitchParamName = /airlab/trigger/enabled
Stack ARN:
arn:aws:cloudformation:ap-southeast-2:884692409741:stack/AwsGenerativeAiAirLabTriggerStack/ee3c05c0-3dfc-11f1-992a-067a230f1083

✨  Total time: 266.02s

(.venv) emilygao@Emilys-MacBook-Pro aws-genai-airlab % aws cloudformation describe-stack-resources \
  --stack-name AwsGenerativeAiAirLabTriggerStack \
  --query "StackResources[?ResourceType=='AWS::Lambda::Function'].[LogicalResourceId,PhysicalResourceId]" \
  --output table
---------------------------------------------------------------------------------------------------------------------------------------
|                                                       DescribeStackResources                                                        |
+-----------------------------------------------------------------+-------------------------------------------------------------------+
|  CustomS3AutoDeleteObjectsCustomResourceProviderHandler9D90184F |  AwsGenerativeAiAirLabTrig-CustomS3AutoDeleteObject-ETXc57Mz9YCl  |
|  TriggerConsumerLambda11380825                                  |  AwsGenerativeAiAirLabTrig-TriggerConsumerLambda113-yvIpZYpq0Wlj  |
|  TriggerDeciderLambda9CE91441                                   |  AwsGenerativeAiAirLabTrig-TriggerDeciderLambda9CE9-MnxUKbWyRmwi  |
+-----------------------------------------------------------------+-------------------------------------------------------------------+
(.venv) emilygao@Emilys-MacBook-Pro aws-genai-airlab % DEPLOY_TRIGGER_STACK=true make deploy



(.venv) emilygao@Emilys-MacBook-Pro aws-genai-airlab % .venv/bin/python scripts/smoke_10.py
label                         event_id              consumer_response
------------------------------------------------------------------------------------------
A1 trigger+filter             smoke-5d47dab3        {'consumed': 1, 'invoked': 1}
A2 trigger+filter             smoke-3aaa7a65        {'consumed': 1, 'invoked': 1}
B1 trigger softprompt         smoke-8b295a86        {'consumed': 1, 'invoked': 1}
B2 trigger amount             smoke-ed1c9980        {'consumed': 1, 'invoked': 1}
B3 trigger segment            smoke-fd2930d9        {'consumed': 1, 'invoked': 1}
C1 ignore low-score           smoke-86204ed7        {'consumed': 1, 'invoked': 0}
C2 ignore support std         smoke-07494733        {'consumed': 1, 'invoked': 0}
C3 ignore user_signal         smoke-74b36f40        {'consumed': 1, 'invoked': 0}
C4 ignore sys_alert           smoke-7ae4c715        {'consumed': 1, 'invoked': 0}
C5 ignore small amt           smoke-d255ce0d        {'consumed': 1, 'invoked': 0}

for KEY in $(aws s3 ls "s3://$BUCKET/events/" --recursive | tail -5 | awk '{print $4}'); do
  echo "=== $KEY ==="
  aws s3 cp "s3://$BUCKET/$KEY" - | jq '{event_id, event_type: .raw_event.event_type, status: .tutor_status, blocked: (.tutor_response_preview | contains("content filter"))}'
done
=== events/dt=2026-04-22/hh=04/smoke-8b295a86.json ===
{
  "event_id": "smoke-8b295a86",
  "event_type": "support_ticket",
  "status": 200,
  "blocked": false
}
=== events/dt=2026-04-22/hh=04/smoke-ed1c9980.json ===
{
  "event_id": "smoke-ed1c9980",
  "event_type": "user_signal",
  "status": 200,
  "blocked": false
}
=== events/dt=2026-04-22/hh=04/smoke-fd2930d9.json ===
{
  "event_id": "smoke-fd2930d9",
  "event_type": "system_alert",
  "status": 200,
  "blocked": false
}
=== events/dt=2026-04-22/hh=04/test-3.json ===
{
  "event_id": "test-3",
  "event_type": "fraud_transaction",
  "status": 502,
  "blocked": false
}
=== events/dt=2026-04-22/hh=04/test-4.json ===
{
  "event_id": "test-4",
  "event_type": "fraud_transaction",
  "status": 200,
  "blocked": true
}
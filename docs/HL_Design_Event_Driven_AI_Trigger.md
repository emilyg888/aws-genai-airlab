🧠 DESIGN DOCUMENT
Event-Driven AI Trigger Layer (Kafka + Bedrock Integration)
Integrated into aws-genai-airlab

1. 🎯 Objective

Design and implement an event-driven AI trigger layer that:

Consumes real-time events (Kafka / MSK)
Applies signal-based trigger logic
Invokes GenAI only when required
Integrates with existing:
API Gateway /lab/tutor
Bedrock-based inference
Supports evaluation + governance
💡 Core Principle

“AI should not run on every event — only when signals justify it.”

2. 🏗️ High-Level Architecture
   ┌────────────────────────────┐
   │ Event Producers │
   │ (simulated / batch load) │
   └─────────────┬──────────────┘
   │
   ▼
   ┌────────────────────────────┐
   │ Amazon MSK (Kafka) │
   │ Topic: ai-events │
   └─────────────┬──────────────┘
   │
   ▼
   ┌────────────────────────────┐
   │ Lambda: Event Consumer │
   │ (MSK trigger) │
   └─────────────┬──────────────┘
   │
   ▼
   ┌────────────────────────────┐
   │ Trigger Layer (Lambda) │
   │ - Signal filtering │
   │ - Threshold logic │
   └─────────────┬──────────────┘
   │
   ┌──────────┴──────────┐
   │ │
   ▼ ▼
   ┌────────────────────┐ ┌────────────────────┐
   │ Ignore Event │ │ Invoke AI │
   │ (no action) │ │ API Gateway │
   └────────────────────┘ │ /lab/tutor │
   └─────────┬──────────┘
   │
   ▼
   ┌────────────────────────┐
   │ Lambda (existing) │
   │ Bedrock inference │
   └─────────┬──────────────┘
   │
   ▼
   ┌────────────────────────┐
   │ Output / Logging │
   │ S3 / CloudWatch │
   └────────────────────────┘
3. 🧱 AWS Service Design (Cost-Conscious)
   Kafka choice (IMPORTANT)
   Option A (recommended for budget):
   Amazon MSK Serverless
   Cost: low for intermittent usage
   No cluster management
   Option B (cheapest fallback):
   Kinesis (but NOT Kafka — weaker for JD alignment)

👉 Use:

MSK Serverless (aligns with JD + affordable)

Core Components
Component Service
Event Stream Amazon MSK Serverless
Consumer AWS Lambda
Trigger Engine AWS Lambda
AI Invocation API Gateway
AI Runtime Lambda + Bedrock
Logging CloudWatch + S3 4. 🔧 Logical Components
4.1 Event Schema
{
"event_id": "123",
"event_type": "fraud_transaction",
"amount": 5000,
"fraud_score": 0.87,
"customer_segment": "high_value",
"timestamp": "2026-01-01T12:00:00"
}
4.2 Trigger Rules
def should_trigger(event):
if event["fraud_score"] > 0.8:
return True
if event["amount"] > 10000:
return True
if event["customer_segment"] == "high_value":
return True
return False
4.3 Decision Engine
def decide(event):
if should_trigger(event):
return "invoke_ai"
return "ignore" 5. 🔁 Integration with Existing aws-genai-airlab
Existing components (reuse)
API Gateway → /lab/tutor
Lambda → tutor handler
Bedrock → inference
S3 → knowledge base
New integration point
Trigger Layer → POST /lab/tutor

Payload:

{
"query": "Analyse this transaction for fraud",
"context": { event_payload }
} 6. 🧪 Evaluation Strategy (CRITICAL)
Metrics
Metric Description
Trigger Rate % events invoking AI
Cost Bedrock calls saved
Accuracy Correct triggers
Miss Rate Missed important events
Logging
Store all events in S3
Store:
triggered events
ignored events
Optional enhancement
Add LLM evaluation pass
Compare:
triggered vs non-triggered outcomes 7. 🏗️ CDK Design (structure for Codex)
New Stack
lib/
├── trigger-stack.ts
Resources to define

1. MSK Serverless Cluster
   new msk.ServerlessCluster(...)
2. Topic
   ai-events
3. Lambda: consumer
   MSK trigger
   reads messages
4. Lambda: trigger engine
   decision logic
5. IAM roles
   MSK access
   invoke API Gateway
6. API Gateway integration
   reuse existing endpoint
7. 🔐 Governance + Guardrails
   Control Points
   Layer Control
   Event schema validation
   Trigger threshold rules
   AI prompt control
   Output logging + audit
   Key principle

Control sits before AI invocation

9. 💰 Cost Strategy (under $200)
   Expected usage
   Service Cost
   MSK Serverless low (event-driven)
   Lambda minimal
   Bedrock main cost driver

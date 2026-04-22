"""Decision + model routing (§4.2, §4.3 of LL design)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from trigger.rules import Rule, RuleSet, matched_rules

ACTION_INVOKE = "invoke_ai"
ACTION_IGNORE = "ignore"
ACTION_SAMPLE = "sample"


@dataclass(frozen=True)
class Decision:
    action: str                      # invoke_ai | sample | ignore
    matched_rule_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ModelRoute:
    invoke: bool
    model: str | None
    priority: str | None = None


def decide(
    event: dict[str, Any],
    ruleset: RuleSet,
    *,
    rng: random.Random | None = None,
) -> Decision:
    """Apply rules; fall back to a baseline sample for ignored events."""
    matched: list[Rule] = matched_rules(event, ruleset)
    if matched:
        return Decision(
            action=ACTION_INVOKE,
            matched_rule_ids=tuple(r.id for r in matched),
            reason="; ".join(r.reason for r in matched),
        )

    r = (rng or random).random()
    if r < ruleset.baseline_invoke_rate:
        return Decision(action=ACTION_SAMPLE, reason="baseline sample")

    return Decision(action=ACTION_IGNORE, reason="no rule matched")


def route_model(decision: Decision, event: dict[str, Any]) -> ModelRoute:
    """Pick the model + priority for this decision (§4.3)."""
    # Default model (cheap, fast)
    default = "deepseek-v3.2"

    if decision.action == ACTION_INVOKE:
        escalate = (
            float(event.get("fraud_score") or 0) > 0.95
            or float(event.get("amount") or 0) > 20000
            or event.get("customer_segment") == "vip"
        )
        return ModelRoute(
            invoke=True,
            model="deepseek-r1" if escalate else default,
            priority="high",
        )

    if decision.action == ACTION_SAMPLE:
        return ModelRoute(invoke=True, model=default, priority="evaluation")

    return ModelRoute(invoke=False, model=None)

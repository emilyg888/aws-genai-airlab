import random
from pathlib import Path

from trigger.decision import (
    ACTION_IGNORE, ACTION_INVOKE, ACTION_SAMPLE,
    decide, route_model,
)
from trigger.rules import load


RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "trigger_rules.json"


def _rs():
    return load(RULES_PATH)


def test_decide_invoke_on_high_fraud():
    d = decide({"fraud_score": 0.99}, _rs(), rng=random.Random(0))
    assert d.action == ACTION_INVOKE
    assert "high_fraud_score" in d.matched_rule_ids


def test_decide_invoke_on_vip():
    d = decide({"customer_segment": "vip"}, _rs(), rng=random.Random(0))
    assert d.action == ACTION_INVOKE
    assert "vip_customer" in d.matched_rule_ids


def test_decide_multiple_matches():
    d = decide(
        {"fraud_score": 0.99, "amount": 50000, "customer_segment": "vip"},
        _rs(),
        rng=random.Random(0),
    )
    assert d.action == ACTION_INVOKE
    assert set(d.matched_rule_ids) == {"high_fraud_score", "high_value_amount", "vip_customer"}


def test_decide_sample_path_with_seed():
    # Seed where random() < 0.01 to force the sample branch.
    # random.Random(2)'s first .random() is ~0.956 — too high, so we engineer
    # a ruleset with a high baseline to make the test deterministic.
    from trigger.rules import RuleSet
    empty = RuleSet(version=1, rules=(), baseline_invoke_rate=1.0)
    d = decide({"event_type": "user_signal"}, empty, rng=random.Random(0))
    assert d.action == ACTION_SAMPLE


def test_decide_ignore_when_nothing_matches():
    from trigger.rules import RuleSet
    empty = RuleSet(version=1, rules=(), baseline_invoke_rate=0.0)
    d = decide({"event_type": "user_signal"}, empty, rng=random.Random(0))
    assert d.action == ACTION_IGNORE


def test_route_model_defaults_to_cheap():
    from trigger.decision import Decision
    r = route_model(Decision(action=ACTION_INVOKE), {"fraud_score": 0.85})
    assert r.invoke is True
    assert r.model == "deepseek-v3.2"
    assert r.priority == "high"


def test_route_model_escalates_on_high_fraud():
    from trigger.decision import Decision
    r = route_model(Decision(action=ACTION_INVOKE), {"fraud_score": 0.99})
    assert r.model == "deepseek-r1"


def test_route_model_escalates_on_vip():
    from trigger.decision import Decision
    r = route_model(Decision(action=ACTION_INVOKE), {"customer_segment": "vip"})
    assert r.model == "deepseek-r1"


def test_route_model_escalates_on_large_amount():
    from trigger.decision import Decision
    r = route_model(Decision(action=ACTION_INVOKE), {"amount": 50000})
    assert r.model == "deepseek-r1"


def test_route_model_sample_uses_cheap():
    from trigger.decision import Decision
    r = route_model(Decision(action=ACTION_SAMPLE), {"fraud_score": 0.99})
    assert r.model == "deepseek-v3.2"
    assert r.priority == "evaluation"


def test_route_model_ignore_does_not_invoke():
    from trigger.decision import Decision
    r = route_model(Decision(action=ACTION_IGNORE), {})
    assert r.invoke is False
    assert r.model is None

import json
from pathlib import Path

import pytest

from trigger.rules import RuleError, evaluate, load, matched_rules, _compile


def test_matches_above_threshold():
    expr = _compile("fraud_score > 0.80")
    assert evaluate(expr, {"fraud_score": 0.9}) is True
    assert evaluate(expr, {"fraud_score": 0.5}) is False


def test_missing_field_treated_as_none():
    expr = _compile("fraud_score > 0.80")
    assert evaluate(expr, {}) is False


def test_membership():
    expr = _compile("customer_segment in ['high_value', 'vip']")
    assert evaluate(expr, {"customer_segment": "vip"}) is True
    assert evaluate(expr, {"customer_segment": "standard"}) is False


def test_boolean_combination():
    expr = _compile("amount > 1000 and customer_segment == 'vip'")
    assert evaluate(expr, {"amount": 5000, "customer_segment": "vip"}) is True
    assert evaluate(expr, {"amount": 500, "customer_segment": "vip"}) is False


def test_disallowed_syntax_rejected():
    # Function calls must be disallowed by the safe evaluator.
    with pytest.raises(RuleError):
        _compile("__import__('os').system('ls')")


def test_attribute_access_rejected():
    with pytest.raises(RuleError):
        _compile("event.fraud_score > 0.8")


def test_load_real_config_file(tmp_path: Path):
    cfg = {
        "version": 1,
        "rules": [
            {"id": "r1", "when": "amount > 100", "reason": "big"},
        ],
        "sampling": {"baseline_invoke_rate": 0.05},
    }
    f = tmp_path / "rules.json"
    f.write_text(json.dumps(cfg))
    rs = load(f)
    assert rs.version == 1
    assert rs.baseline_invoke_rate == 0.05
    assert len(rs.rules) == 1
    assert matched_rules({"amount": 500}, rs)[0].id == "r1"
    assert matched_rules({"amount": 50}, rs) == []


def test_bundled_rules_config():
    project_rules = Path(__file__).resolve().parents[1] / "config" / "trigger_rules.json"
    rs = load(project_rules)
    assert [r.id for r in rs.rules] == [
        "high_fraud_score", "high_value_amount", "vip_customer"
    ]
    assert rs.baseline_invoke_rate == 0.01

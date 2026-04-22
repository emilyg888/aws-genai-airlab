import pytest

from trigger.schema import SchemaError, validate


def _base():
    return {
        "event_id": "evt-1",
        "event_type": "fraud_transaction",
        "timestamp": "2026-01-01T12:00:00Z",
    }


def test_minimal_event_valid():
    assert validate(_base()) == _base()


def test_full_event_valid():
    e = _base() | {
        "amount": 5000,
        "fraud_score": 0.87,
        "customer_segment": "high_value",
        "producer": "core-banking",
    }
    assert validate(e) == e


def test_missing_required():
    with pytest.raises(SchemaError, match="event_id"):
        validate({"event_type": "fraud_transaction", "timestamp": "2026-01-01T00:00:00Z"})


def test_bad_event_type():
    e = _base()
    e["event_type"] = "not_a_type"
    with pytest.raises(SchemaError, match="event_type"):
        validate(e)


def test_bad_timestamp():
    e = _base()
    e["timestamp"] = "yesterday"
    with pytest.raises(SchemaError, match="timestamp"):
        validate(e)


def test_fraud_score_out_of_range():
    e = _base()
    e["fraud_score"] = 1.5
    with pytest.raises(SchemaError, match="fraud_score"):
        validate(e)


def test_negative_amount():
    e = _base()
    e["amount"] = -1
    with pytest.raises(SchemaError, match="amount"):
        validate(e)


def test_non_object_rejected():
    with pytest.raises(SchemaError, match="JSON object"):
        validate("not a dict")  # type: ignore[arg-type]

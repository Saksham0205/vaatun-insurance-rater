import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.rating_engine import review
from app.rating_engine.engine import rate_policy
from app.rating_engine.models import PolicyInput, SourceRef

CARDS = Path(__file__).resolve().parents[1] / "rate_cards"
DOC = SourceRef("policy.pdf", "a" * 64, page=1, role="policy_fact")


def _result_for(policy: PolicyInput) -> dict:
    decision = rate_policy(policy, CARDS)
    return {"document": {"ocr_pages_limited": False}, "policy_input": review.policy_to_dict(policy),
            "decisions": {"overall": decision.status.value}}


def _reliance_policy(**overrides) -> PolicyInput:
    values = dict(insurer="Reliance General Insurance", policy_type="Private Car Package Policy",
                  cover="Private Car Package Policy", engine_cc=999, geography="Uttar Pradesh",
                  od_premium=Decimal("4714"), tp_premium=Decimal("2519"))
    values.update(overrides)
    evidence = {key: [DOC] for key in ("insurer", "policy_type", "engine_cc", "state", "od_premium", "tp_premium")}
    return PolicyInput(**values, source_evidence=evidence)


def test_policy_input_round_trips_through_json():
    policy = _reliance_policy(add_ons=("Engine Protector",), ncb_percent=Decimal("25"))
    restored = review.policy_from_dict(json.loads(json.dumps(review.policy_to_dict(policy))))
    assert restored == policy


def test_missing_fuel_is_supplied_by_review_and_commission_is_calculated():
    policy = _reliance_policy()
    assert rate_policy(policy, CARDS).od.status.value == "ambiguous"  # fuel not printed
    result = review.rerate(_result_for(policy), {"fuel": "petrol"}, CARDS)
    od = result["decisions"]["OD"]
    assert result["overrides"] == {"fuel": "Petrol"}
    assert od["status"] == "resolved"
    assert od["rate_percent"] == "7.5"  # UP petrol 12.5% minus 5 pp for <1000 CC
    assert od["commission_amount"] == "353.55"
    assert result["totals"]["commission_total"] == "353.55"
    assert result["assessment_status"] == "complete"
    assert result["rating_inputs"]["fuel"] == {"value": "Petrol", "source": "operator"}
    assert any(ref["source_file"] == review.OPERATOR_SOURCE for ref in od["evidence"]) or \
        "operator review" in " ".join(result["rating_trace"]).casefold()


def test_review_rejects_values_outside_the_rate_card_vocabulary():
    with pytest.raises(ValueError, match="Fuel"):
        review.normalize_overrides({"fuel": "Steam"})
    with pytest.raises(ValueError, match="cannot be overridden"):
        review.normalize_overrides({"insurer": "Someone Else"})
    with pytest.raises(ValueError, match="non-negative"):
        review.normalize_overrides({"od_premium": "-5"})
    assert review.normalize_overrides({"fuel": "", "od_premium": "₹1,234.50"}) == {"od_premium": "1234.50"}


def test_review_requires_stored_inputs():
    with pytest.raises(LookupError):
        review.rerate({"decisions": {}}, {"fuel": "Petrol"}, CARDS)


def test_operator_business_type_wins_over_derived_value():
    policy = _reliance_policy(fuel="Petrol", previous_insurer="Reliance General Insurance")
    result = review.rerate(_result_for(policy), {"business_type": "Rollover"}, CARDS)
    assert "Business type supplied by operator review." in result["rating_trace"]


def test_resolved_rate_without_premium_is_not_complete():
    policy = _reliance_policy(fuel="Petrol", od_premium=None)
    result = review.rerate(_result_for(policy), {}, CARDS)
    assert result["decisions"]["OD"]["status"] == "resolved"
    assert result["decisions"]["OD"]["commission_amount"] is None
    assert result["assessment_status"] == "incomplete"
    assert any("Commission amount not calculated" in i for i in result["decisions"]["OD"]["issues"])



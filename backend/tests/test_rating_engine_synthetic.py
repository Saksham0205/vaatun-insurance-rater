"""Synthetic unit tests. Synthetic rules validate engine mechanics only, not insurer adapters."""
from decimal import Decimal

from app.rating_engine.exceptions import exception_decision
from app.rating_engine.models import (Component, DecisionStatus,
                                      NormalizedRateRule, PolicyInput, SourceRef, SourceValue)
from app.rating_engine.premium import hdfc_band_from_premium
from app.rating_engine.classification import classify_business, classify_policy


def synthetic_rule(rate, *, conditions=None, declined=False):
    return NormalizedRateRule(
        "synthetic", "synthetic-test-only", conditions or {"zone": "Z1"}, Component.OD,
        rate, "OD premium", SourceValue(SourceRef("synthetic.xlsx", sheet="Rates", cell="A1"), rate),
        explicitly_declined=declined, interpretation="synthetic test fixture",
    )



def test_synthetic_missing_rate_is_not_zero():
    rule = synthetic_rule(None)
    status, message = exception_decision(rule)
    assert status == DecisionStatus.AMBIGUOUS and "Missing is not zero" in message


def test_synthetic_explicit_zero_is_resolved_not_declined():
    rule = synthetic_rule(Decimal("0"))
    status, _ = exception_decision(rule)
    assert status == DecisionStatus.RESOLVED and rule.rate_percent == Decimal("0")


def test_synthetic_explicit_decline_is_unsupported():
    rule = synthetic_rule(Decimal("0"), declined=True)
    status, message = exception_decision(rule)
    assert status == DecisionStatus.UNSUPPORTED and "explicitly declines" in message




def test_hdfc_premium_boundaries_are_not_assigned_implicitly():
    for amount in (10000, 50000, 100000, 200000):
        band, issue = hdfc_band_from_premium(Decimal(amount))
        assert band is None and "exact OD premium boundary" in issue
    assert hdfc_band_from_premium(Decimal("9999"))[0] == "<10k"


def test_unsupported_policy_type_is_not_guessed():
    product, issues = classify_policy(PolicyInput(policy_type="Commercial Package"))
    assert product is None and "outside the verified" in issues[0]




def test_current_and_previous_same_insurer_is_a_renewal_even_with_alias_variants():
    business, issues = classify_business("HDFC ERGO General Insurance", "HDFC Ergo")
    assert business == "Renewal" and not issues

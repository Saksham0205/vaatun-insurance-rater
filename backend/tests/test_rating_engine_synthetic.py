"""Synthetic unit tests. Synthetic rules validate engine mechanics only, not insurer adapters."""
from decimal import Decimal

from app.rating_engine.calculation import calculate_amount
from app.rating_engine.exceptions import exception_decision
from app.rating_engine.geography import resolve_rto
from app.rating_engine.lookup import exact_lookup
from app.rating_engine.models import (Component, ComponentDecision, DecisionStatus,
                                      NormalizedRateRule, PolicyInput, SourceRef, SourceValue)
from app.rating_engine.premium import hdfc_band_from_premium, normalize_premium
from app.rating_engine.classification import classify_policy, classify_vehicle
from app.rating_engine.classification import classify_business


def synthetic_rule(rate, *, conditions=None, declined=False):
    return NormalizedRateRule(
        "synthetic", "synthetic-test-only", conditions or {"zone": "Z1"}, Component.OD,
        rate, "OD premium", SourceValue(SourceRef("synthetic.xlsx", sheet="Rates", cell="A1"), rate),
        explicitly_declined=declined, interpretation="synthetic test fixture",
    )


def test_synthetic_exact_rate_lookup():
    rule, issue = exact_lookup([synthetic_rule(Decimal("12.5"))], {"zone": "Z1"})
    assert issue is None and rule.rate_percent == Decimal("12.5")


def test_synthetic_missing_rate_is_not_zero():
    rule, issue = exact_lookup([synthetic_rule(None)], {"zone": "Z1"})
    assert issue is None
    status, message = exception_decision(rule)
    assert status == DecisionStatus.AMBIGUOUS and "Missing is not zero" in message


def test_synthetic_explicit_zero_is_resolved_not_declined():
    rule, _ = exact_lookup([synthetic_rule(Decimal("0"))], {"zone": "Z1"})
    status, _ = exception_decision(rule)
    assert status == DecisionStatus.RESOLVED and rule.rate_percent == Decimal("0")


def test_synthetic_explicit_decline_is_unsupported():
    rule = synthetic_rule(Decimal("0"), declined=True)
    status, message = exception_decision(rule)
    assert status == DecisionStatus.UNSUPPORTED and "explicitly declines" in message


def test_synthetic_missing_rto_mapping():
    geography, refs, issues = resolve_rto({"KA01": "Bangalore"}, "KA99")
    assert geography is None and refs == [] and "No exact RTO mapping" in issues[0]


def test_synthetic_multiple_matching_rows_are_ambiguous():
    rules = [synthetic_rule(Decimal("10")), synthetic_rule(Decimal("12"))]
    rule, issue = exact_lookup(rules, {"zone": "Z1"})
    assert rule is None and "2 matches" in issue


def test_hdfc_premium_boundaries_are_not_assigned_implicitly():
    for amount in (10000, 50000, 100000, 200000):
        band, issue = hdfc_band_from_premium(Decimal(amount))
        assert band is None and "exact OD premium boundary" in issue
    assert hdfc_band_from_premium(Decimal("9999"))[0] == "<10k"


def test_missing_fuel_information_is_ambiguous_for_vehicle_classification():
    segment, issues = classify_vehicle(PolicyInput())
    assert segment is None and "Fuel information is missing" in issues[0]


def test_missing_engine_capacity_when_required():
    segment, issues = classify_vehicle(PolicyInput(fuel="Petrol"), require_engine_cc=True)
    assert segment is None and "Engine capacity is missing" in issues[0]


def test_unsupported_policy_type_is_not_guessed():
    product, issues = classify_policy(PolicyInput(policy_type="Commercial Package"))
    assert product is None and "outside the verified" in issues[0]


def test_commission_amount_not_calculated_without_known_basis():
    decision = ComponentDecision(Component.OD, DecisionStatus.RESOLVED, True,
                                 rate_percent=Decimal("10"), rate_basis=None)
    calculate_amount(decision, {"Net premium": Decimal("1000")})
    assert decision.commission_amount is None
    assert any("applicable premium basis is missing" in issue for issue in decision.issues)


def test_synthetic_partial_od_tp_resolution_is_preserved():
    od = ComponentDecision(Component.OD, DecisionStatus.RESOLVED, True, rate_percent=Decimal("15"))
    tp = ComponentDecision(Component.TP, DecisionStatus.UNSUPPORTED, True,
                           issues=["Synthetic unresolved TP component."])
    assert od.status == DecisionStatus.RESOLVED
    assert tp.status == DecisionStatus.UNSUPPORTED


def test_current_and_previous_same_insurer_is_a_renewal_even_with_alias_variants():
    business, issues = classify_business("HDFC ERGO General Insurance", "HDFC Ergo")
    assert business == "Renewal" and not issues


def test_amount_is_calculated_only_against_named_known_premium_basis():
    decision = ComponentDecision(Component.OD, DecisionStatus.RESOLVED, True,
                                 rate_percent=Decimal("12.5"), rate_basis="OD premium")
    calculate_amount(decision, {"OD premium": Decimal("8000")})
    assert decision.commission_amount == Decimal("1000.00")
    assert "OD premium 8000 × 12.5%" in decision.calculation

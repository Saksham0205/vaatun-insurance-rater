from .models import ComponentDecision, NormalizedRateRule


def attach_rule_evidence(decision: ComponentDecision, rule: NormalizedRateRule) -> ComponentDecision:
    decision.evidence = [rule.source_value.ref]
    decision.selected_conditions = dict(rule.conditions)
    decision.rate_basis = rule.rate_basis
    decision.rate_percent = rule.rate_percent
    return decision

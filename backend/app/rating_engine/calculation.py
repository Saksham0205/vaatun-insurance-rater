from decimal import Decimal

from .models import ComponentDecision, DecisionStatus


def calculate_amount(decision: ComponentDecision,
                     premium_bases: dict[str, Decimal] | None) -> ComponentDecision:
    if decision.status != DecisionStatus.RESOLVED or decision.rate_percent is None:
        return decision
    if not decision.rate_basis or premium_bases is None or decision.rate_basis not in premium_bases:
        decision.issues.append("Commission amount not calculated because the applicable premium basis is missing.")
        return decision
    premium_basis = premium_bases[decision.rate_basis]
    decision.premium_basis = premium_basis
    decision.commission_amount = (premium_basis * decision.rate_percent / Decimal(100)).quantize(Decimal("0.01"))
    decision.calculation = f"{decision.rate_basis} {premium_basis} × {decision.rate_percent}% = {decision.commission_amount}"
    return decision

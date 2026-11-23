from pathlib import Path

from .adapters import GoDigitAdapter, HDFCAdapter, RelianceAdapter, TataAIGAdapter
from .classification import classify_business, classify_policy
from .identification import identify_from_policy
from .models import (AnalysisDecision, Component, ComponentDecision, DecisionStatus,
                     PolicyInput)


RATE_CARD_ROOT = Path(__file__).resolve().parents[1] / "rate_cards"
ADAPTERS = {
    "godigit": GoDigitAdapter,
    "hdfc-ergo": HDFCAdapter,
    "reliance-indusind": RelianceAdapter,
    "tata-aig": TataAIGAdapter,
}


def _overall(od: ComponentDecision, tp: ComponentDecision) -> DecisionStatus:
    unresolved = [c.status for c in (od, tp) if c.applicable and c.status != DecisionStatus.RESOLVED]
    if not unresolved:
        return DecisionStatus.RESOLVED
    if DecisionStatus.AMBIGUOUS in unresolved:
        return DecisionStatus.AMBIGUOUS
    return DecisionStatus.UNSUPPORTED


def rate_policy(policy: PolicyInput, rate_card_root: str | Path = RATE_CARD_ROOT) -> AnalysisDecision:
    insurer, insurer_issue = identify_from_policy(policy)
    if insurer_issue:
        empty = ComponentDecision(Component.OD, DecisionStatus.AMBIGUOUS, True, issues=[insurer_issue])
        tp = ComponentDecision(Component.TP, DecisionStatus.AMBIGUOUS, True, issues=[insurer_issue])
        return AnalysisDecision(DecisionStatus.AMBIGUOUS, insurer, None, empty, tp,
                                trace=["Insurer identification did not produce one supplied rate-card family."],
                                issues=[insurer_issue])

    product, product_issues = classify_policy(policy)
    if not product:
        status = DecisionStatus.AMBIGUOUS if any("missing" in issue.casefold() for issue in product_issues) else DecisionStatus.UNSUPPORTED
        od = ComponentDecision(Component.OD, status, True, issues=product_issues)
        tp = ComponentDecision(Component.TP, status, True, issues=product_issues)
        return AnalysisDecision(status, insurer, None, od, tp,
                                trace=["Policy classification failed; no grid was selected."], issues=product_issues)

    business_type, business_issues = classify_business(
        policy.insurer, policy.previous_insurer, policy.business_type)
    policy.business_type = business_type
    adapter = ADAPTERS[insurer](rate_card_root)
    if insurer == "hdfc-ergo":
        od, tp = adapter.rate(policy, product)
    else:
        od, tp = adapter.rate(policy, product)
    trace = [f"Insurer identified deterministically as {insurer}.",
             f"Policy classified as {product}.",
             f"Selected rate-card version: {adapter.card_version}.",
             "No LLM participates in insurer, rate-card, or commission resolution."]
    if business_type:
        trace.append(f"Business type: {business_type}.")
    if business_issues:
        trace.extend(business_issues)
    issues = list(dict.fromkeys(od.issues + tp.issues + business_issues))
    return AnalysisDecision(_overall(od, tp), insurer, adapter.card_version, od, tp, trace, issues)

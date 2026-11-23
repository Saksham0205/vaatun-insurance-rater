from .models import DecisionStatus, NormalizedRateRule


def exception_decision(rule: NormalizedRateRule) -> tuple[DecisionStatus, str | None]:
    if rule.explicitly_declined:
        return DecisionStatus.UNSUPPORTED, "The matched source condition explicitly declines this risk."
    if rule.rate_percent is None:
        return DecisionStatus.AMBIGUOUS, "The matched source cell has no rate value. Missing is not zero."
    return DecisionStatus.RESOLVED, None

from .models import NormalizedRateRule


def exact_lookup(rules: list[NormalizedRateRule], conditions: dict[str, object]):
    matches = [rule for rule in rules
               if all(rule.conditions.get(key) == value for key, value in conditions.items())]
    if not matches:
        return None, "No rate-card row matches all supplied lookup conditions."
    if len(matches) != 1:
        return None, f"Multiple rate-card rows match the supplied lookup conditions ({len(matches)} matches)."
    return matches[0], None

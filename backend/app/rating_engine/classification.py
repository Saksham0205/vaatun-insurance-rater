from .models import PolicyInput
from .identification import identify_insurer


def classify_policy(policy: PolicyInput) -> tuple[str | None, list[str]]:
    issues: list[str] = []
    if not policy.policy_type and not policy.cover:
        return None, ["Policy type/cover is missing; cannot classify package, SAOD or SATP."]
    raw = f"{policy.policy_type or ''} {policy.cover or ''}".casefold().replace("-", " ")
    if any(kind in raw for kind in ("commercial", "two wheeler", "two-wheeler", "motorcycle", "goods carrier")):
        return None, [f"Policy type '{policy.policy_type or policy.cover}' is outside the verified private-car scope."]
    if "standalone" in raw and ("tp" in raw or "third party" in raw):
        return "SATP", issues
    if "saod" in raw or ("standalone" in raw and "damage" in raw):
        return "SAOD", issues
    if "package" in raw or "comprehensive" in raw:
        return "Package", issues
    return None, [f"Policy type '{policy.policy_type or policy.cover}' is not supported by the verified classifier."]


def classify_business(current_insurer: str | None, previous_insurer: str | None,
                      stated_business_type: str | None = None) -> tuple[str | None, list[str]]:
    if current_insurer and previous_insurer:
        current_key, _ = identify_insurer(current_insurer)
        previous_key, _ = identify_insurer(previous_insurer)
        if current_key and previous_key and current_key == previous_key:
            return "Renewal", []
        if current_key and previous_key and current_key != previous_key:
            return "Rollover", []
        if current_insurer.casefold().strip() == previous_insurer.casefold().strip():
            return "Renewal", []
        return None, ["Current and previous insurer could not be normalized to determine renewal versus rollover."]
    if stated_business_type:
        return stated_business_type, []
    return None, ["Business type cannot be derived without current and previous insurer or an explicit value."]


def classify_vehicle(policy: PolicyInput, require_engine_cc: bool = False) -> tuple[str | None, list[str]]:
    if policy.fuel is None:
        return None, ["Fuel information is missing."]
    fuel = policy.fuel.casefold().strip()
    known = {"petrol", "diesel", "cng", "lpg", "electric", "ev", "hybrid", "bifuel"}
    if fuel not in known:
        return None, [f"Fuel '{policy.fuel}' is not in the verified passenger-car fuel vocabulary."]
    if require_engine_cc and policy.engine_cc is None:
        return None, ["Engine capacity is missing for this insurer's vehicle segment lookup."]
    return fuel, []

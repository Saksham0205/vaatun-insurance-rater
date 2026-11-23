import re

from .models import PolicyInput


INSURER_ALIASES = {
    "godigit": ("go digit", "godigit", "digit general"),
    "hdfc-ergo": ("hdfc ergo", "hdfc general"),
    "reliance-indusind": ("reliance general", "reliance insurance", "reliance indusind"),
    "tata-aig": ("tata aig", "tata-aig"),
}


def identify_insurer(name: str | None) -> tuple[str | None, str | None]:
    if not name:
        return None, "Insurer is missing."
    # Compare without spaces/punctuation: OCR often drops spaces ("TATAAIGGENERAL...").
    compact = re.sub(r"[^a-z0-9]", "", name.casefold())
    matches = [key for key, aliases in INSURER_ALIASES.items()
               if any(re.sub(r"[^a-z0-9]", "", alias) in compact for alias in aliases)]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"No supplied rate card matches insurer '{name}'."
    return None, f"Insurer name '{name}' matches multiple supplied rate-card families: {', '.join(matches)}."


def identify_from_policy(policy: PolicyInput) -> tuple[str | None, str | None]:
    return identify_insurer(policy.insurer)

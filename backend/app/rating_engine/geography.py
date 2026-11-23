from .models import SourceRef


def resolve_rto(mapping: dict[str, str], rto: str | None,
                mapping_source: SourceRef | None = None) -> tuple[str | None, list[SourceRef], list[str]]:
    if not rto:
        return None, [], ["RTO is missing; insurer-specific geography cannot be resolved."]
    key = rto.upper().replace(" ", "").replace("-", "")
    hits = [(raw, value) for raw, value in mapping.items()
            if raw.upper().replace(" ", "").replace("-", "") == key]
    if not hits:
        return None, [], [f"No exact RTO mapping exists for '{rto}'."]
    if len(hits) > 1:
        return None, [], [f"Multiple geography rows match RTO '{rto}'."]
    return hits[0][1], ([mapping_source] if mapping_source else []), []

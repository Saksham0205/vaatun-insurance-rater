from pathlib import Path
import hashlib

from ..models import Component, ComponentDecision, DecisionStatus, PolicyInput, SourceRef


class UnresolvedAdapter:
    insurer_key = ""
    card_version = ""
    blockers: tuple[str, ...] = ()
    source_file: str = ""
    source_sheet: str = ""
    source_range: str = ""

    def __init__(self, rate_card_root: str | Path):
        self.rate_card_root = Path(rate_card_root)

    def rate(self, policy: PolicyInput, product: str):
        od_applicable = product != "SATP"
        tp_applicable = product != "SAOD"
        source_path = next(iter(self.rate_card_root.rglob(self.source_file)), None)
        source_hash = (hashlib.sha256(source_path.read_bytes()).hexdigest()
                       if source_path is not None else None)
        evidence = [SourceRef(self.source_file, source_hash, sheet=self.source_sheet,
                              cell=self.source_range, role="unresolved_rule_source")]
        return (
            ComponentDecision(Component.OD,
                              DecisionStatus.AMBIGUOUS if od_applicable else DecisionStatus.NOT_APPLICABLE,
                              od_applicable, evidence=evidence if od_applicable else [],
                              issues=list(self.blockers) if od_applicable else []),
            ComponentDecision(Component.TP,
                              DecisionStatus.AMBIGUOUS if tp_applicable else DecisionStatus.NOT_APPLICABLE,
                              tp_applicable, evidence=evidence if tp_applicable else [],
                              issues=list(self.blockers) if tp_applicable else []),
        )

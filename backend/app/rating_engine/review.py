"""Operator review: correct or supply rating inputs, then re-rate without re-extraction.

A policy PDF often omits a selector the rate card needs (fuel, business type,
vehicle segment, territory). Rather than guessing, the reviewer supplies it.
Every override is validated against the rate cards' own vocabularies and is
recorded as evidence from "Operator review", so a decision always shows which
inputs came from the document and which from a person.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .adapters.tata_aig import _TERRITORY_COLS
from .engine import RATE_CARD_ROOT, rate_policy
from .models import AnalysisDecision, DecisionStatus, PolicyInput, SourceRef

OPERATOR_SOURCE = "Operator review"

TATA_SEGMENTS = ["Compact", "High End", "MPV SUV", "Mid Size", "Mini", "Quadricycle", "Ultra High End"]
_TERRITORIES = sorted({name for name in _TERRITORY_COLS})

# field -> (kind, label, choices). Choices mirror the rate cards' vocabularies.
FIELDS: dict[str, tuple[str, str, list[str] | None]] = {
    "policy_type": ("choice", "Policy type", ["Package", "SAOD", "Standalone TP"]),
    "business_type": ("choice", "Business type", ["New", "Renewal", "Rollover"]),
    "fuel": ("choice", "Fuel", ["Petrol", "Diesel", "CNG", "LPG", "Electric", "Hybrid"]),
    "engine_cc": ("int", "Engine capacity (cc)", None),
    "vehicle_age_years": ("int", "Vehicle age (years)", None),
    "make": ("text", "Make", None),
    "rto_code": ("text", "RTO code (e.g. UP78)", None),
    "geography": ("text", "State / city", None),
    "zone": ("choice", "HDFC zone", ["Zone 1", "Zone 2"]),
    "territory": ("choice", "Tata AIG territory", _TERRITORIES),
    "vehicle_segment": ("choice", "Tata AIG vehicle segment", TATA_SEGMENTS),
    "ncb_state": ("choice", "NCB", ["NCB", "Non-NCB"]),
    "od_premium": ("decimal", "OD premium (₹)", None),
    "tp_premium": ("decimal", "TP premium (₹)", None),
    "net_premium": ("decimal", "Net premium (₹)", None),
}

# Inputs each insurer's rate card selects on (shown first in the review form).
REQUIRED_BY_INSURER: dict[str, list[str]] = {
    # HDFC zone is derived from the state; "zone" stays available under "Show all inputs".
    "hdfc-ergo": ["policy_type", "fuel", "geography", "ncb_state", "od_premium"],
    "reliance-indusind": ["policy_type", "fuel", "geography", "engine_cc", "od_premium", "tp_premium"],
    "godigit": ["policy_type", "business_type", "rto_code", "fuel", "engine_cc", "vehicle_age_years", "make",
                "od_premium", "tp_premium"],
    "tata-aig": ["policy_type", "business_type", "territory", "fuel", "vehicle_segment", "ncb_state",
                 "od_premium", "net_premium"],
}

# Evidence keys the adapters check for each overridable field.
_EVIDENCE_KEYS = {"geography": ["geography", "state"], "policy_type": ["policy_type", "cover"]}


def options() -> dict[str, Any]:
    return {
        "fields": [{"name": name, "kind": kind, "label": label, "choices": choices}
                   for name, (kind, label, choices) in FIELDS.items()],
        "required_by_insurer": REQUIRED_BY_INSURER,
    }


def _field_kinds() -> dict[str, str]:
    kinds = {}
    for f in dataclasses.fields(PolicyInput):
        kind = str(f.type)
        kinds[f.name] = "decimal" if "Decimal" in kind else "int" if kind.startswith("int") else \
            "tuple" if "tuple" in kind else "dict" if "dict" in kind else "bool" if "bool" in kind else "str"
    return kinds


def policy_to_dict(policy: PolicyInput) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in dataclasses.fields(PolicyInput):
        value = getattr(policy, f.name)
        if f.name == "source_evidence":
            out[f.name] = {k: [dataclasses.asdict(ref) for ref in refs] for k, refs in value.items()}
        elif isinstance(value, Decimal):
            out[f.name] = str(value)
        elif isinstance(value, tuple):
            out[f.name] = list(value)
        else:
            out[f.name] = value
    return out


def policy_from_dict(data: dict[str, Any]) -> PolicyInput:
    kinds = _field_kinds()
    values: dict[str, Any] = {}
    for name, kind in kinds.items():
        raw = data.get(name)
        if raw is None:
            continue
        if name == "source_evidence":
            values[name] = {k: [SourceRef(**ref) for ref in refs] for k, refs in raw.items()}
        elif kind == "decimal":
            values[name] = Decimal(str(raw))
        elif kind == "int":
            values[name] = int(raw)
        elif kind == "tuple":
            values[name] = tuple(raw)
        else:
            values[name] = raw
    return PolicyInput(**values)


def normalize_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize reviewer input. Empty values remove an override."""
    clean: dict[str, Any] = {}
    for name, value in (raw or {}).items():
        if name not in FIELDS:
            raise ValueError(f"'{name}' cannot be overridden.")
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        kind, label, choices = FIELDS[name]
        if kind == "choice":
            match = next((c for c in choices or [] if c.casefold() == str(value).strip().casefold()), None)
            if match is None:
                raise ValueError(f"{label}: '{value}' is not one of the rate-card values.")
            clean[name] = match
        elif kind == "int":
            try:
                number = int(str(value).strip())
            except ValueError as exc:
                raise ValueError(f"{label} must be a whole number.") from exc
            if not 0 <= number <= 100_000:
                raise ValueError(f"{label} is out of range.")
            clean[name] = number
        elif kind == "decimal":
            try:
                number = Decimal(str(value).replace(",", "").replace("₹", "").strip())
            except InvalidOperation as exc:
                raise ValueError(f"{label} must be an amount.") from exc
            if not number.is_finite() or number < 0:
                raise ValueError(f"{label} must be a non-negative amount.")
            clean[name] = str(number)
        else:
            text = str(value).strip()
            if len(text) > 120:
                raise ValueError(f"{label} is too long.")
            clean[name] = text.upper() if name == "rto_code" else text
    return clean


def apply_overrides(policy: PolicyInput, overrides: dict[str, Any]) -> PolicyInput:
    ref = SourceRef(OPERATOR_SOURCE, role="user_override")
    for name, value in overrides.items():
        if FIELDS[name][0] == "decimal":
            value = Decimal(value)
        setattr(policy, name, value)
        if name == "policy_type":
            policy.cover = value
        for key in _EVIDENCE_KEYS.get(name, [name]):
            policy.source_evidence[key] = [ref]
    return policy


def is_overridden(policy: PolicyInput, name: str) -> bool:
    return any(ref.source_file == OPERATOR_SOURCE for ref in policy.source_evidence.get(name, []))


def assessment_status(decision: AnalysisDecision, ocr_pages_limited: bool) -> str:
    """Complete only when every applicable component has a confirmed rate and amount."""
    amounts_known = all(d.commission_amount is not None for d in (decision.od, decision.tp)
                        if d.applicable and d.status == DecisionStatus.RESOLVED)
    return ("complete" if decision.status == DecisionStatus.RESOLVED and amounts_known and not ocr_pages_limited
            else "incomplete")


def totals(decision: AnalysisDecision) -> dict[str, str | None]:
    amounts = [d.commission_amount for d in (decision.od, decision.tp)
               if d.applicable and d.status == DecisionStatus.RESOLVED and d.commission_amount is not None]
    return {"commission_total": str(sum(amounts, Decimal("0"))) if amounts else None,
            "currency": "INR"}


def rerate(result: dict[str, Any], raw_overrides: dict[str, Any],
           rate_card_root: str | Path = RATE_CARD_ROOT) -> dict[str, Any]:
    """Return a new result with overrides applied to the extracted inputs and decisions recomputed."""
    from .document_pipeline import decision_dict  # local import: document_pipeline imports this module

    base = result.get("policy_input")
    if not base:
        raise LookupError("This analysis predates input review. Re-run the analysis, then review its inputs.")
    overrides = normalize_overrides(raw_overrides)
    policy = apply_overrides(policy_from_dict(base), overrides)
    decision = rate_policy(policy, rate_card_root)
    updated = dict(result)
    updated["overrides"] = overrides
    updated["rating_inputs"] = rating_inputs(policy)
    updated["rating_trace"] = decision.trace
    updated["totals"] = totals(decision)
    updated["decisions"] = {"overall": decision.status.value,
                            "OD": decision_dict(decision.od), "TP": decision_dict(decision.tp)}
    updated["assessment_status"] = assessment_status(
        decision, bool((result.get("document") or {}).get("ocr_pages_limited")))
    return updated


def rating_inputs(policy: PolicyInput) -> dict[str, Any]:
    """The effective value of every reviewable input and where it came from."""
    out = {}
    for name in FIELDS:
        value = getattr(policy, name)
        out[name] = {"value": str(value) if isinstance(value, Decimal) else value,
                     "source": "operator" if is_overridden(policy, name) else ("document" if value is not None else None)}
    return out

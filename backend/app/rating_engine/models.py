from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


class DecisionStatus(StrEnum):
    RESOLVED = "resolved"
    NOT_APPLICABLE = "not_applicable"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"


class Component(StrEnum):
    OD = "OD"
    TP = "TP"


@dataclass(frozen=True)
class SourceRef:
    source_file: str
    source_sha256: str | None = None
    sheet: str | None = None
    cell: str | None = None
    page: int | None = None
    table: int | None = None
    row: int | None = None
    column: int | None = None
    role: str = "rate"

    def render(self) -> str:
        if self.sheet:
            return f"{self.source_file} · {self.sheet}!{self.cell or ''}".rstrip()
        if self.page:
            where = f"page {self.page}"
            if self.table:
                where += f", table {self.table}"
            if self.row is not None:
                where += f", row {self.row}"
            if self.column is not None:
                where += f", column {self.column}"
            return f"{self.source_file} · {where}"
        return self.source_file


@dataclass(frozen=True)
class SourceValue:
    ref: SourceRef
    original_value: Any
    formula: str | None = None
    cached_value: Any = None
    note: str | None = None


@dataclass(frozen=True)
class NormalizedRateRule:
    insurer_key: str
    card_version: str
    conditions: dict[str, Any]
    component: Component
    rate_percent: Decimal | None
    rate_basis: str | None
    source_value: SourceValue
    explicitly_declined: bool = False
    interpretation: str = "verified"


@dataclass
class ComponentDecision:
    component: Component
    status: DecisionStatus
    applicable: bool
    rate_percent: Decimal | None = None
    commission_amount: Decimal | None = None
    premium_basis: Decimal | None = None
    rate_basis: str | None = None
    selected_conditions: dict[str, Any] = field(default_factory=dict)
    evidence: list[SourceRef] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    calculation: str | None = None


@dataclass
class AnalysisDecision:
    status: DecisionStatus
    insurer_key: str | None
    card_version: str | None
    od: ComponentDecision
    tp: ComponentDecision
    trace: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class PolicyInput:
    insurer: str | None = None
    previous_insurer: str | None = None
    policy_number: str | None = None
    policy_start_date: str | None = None
    policy_end_date: str | None = None
    business_type: str | None = None
    policy_type: str | None = None
    cover: str | None = None
    fuel: str | None = None
    engine_cc: int | None = None
    vehicle_age_years: int | None = None
    make: str | None = None
    model: str | None = None
    vehicle_segment: str | None = None
    vehicle_category: str | None = None
    rto: str | None = None
    # RTO code such as "UP78", read from the registration number.
    rto_code: str | None = None
    geography: str | None = None
    zone: str | None = None
    # Insurer territory column (e.g. Tata AIG 'UP1') when supplied by operator review.
    territory: str | None = None
    od_premium: Decimal | None = None
    tp_premium: Decimal | None = None
    basic_od_premium: Decimal | None = None
    basic_tp_premium: Decimal | None = None
    ncb_discount_amount: Decimal | None = None
    add_on_premium: Decimal | None = None
    total_package_premium: Decimal | None = None
    gst: Decimal | None = None
    total_premium_including_tax: Decimal | None = None
    net_premium: Decimal | None = None
    idv: Decimal | None = None
    # Explicit band only when established by source rules or operator review.
    od_premium_band: str | None = None
    ncb_state: str | None = None
    ncb_percent: Decimal | None = None
    ncb_eligible: bool | None = None
    add_ons: tuple[str, ...] | None = None
    producer_information: str | None = None
    business_gwp: Decimal | None = None
    source_evidence: dict[str, list[SourceRef]] = field(default_factory=dict)


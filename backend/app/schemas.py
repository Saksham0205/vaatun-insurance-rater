from typing import Any, Literal
from pydantic import BaseModel, Field

class Citation(BaseModel):
    source_file: str
    location: str
    excerpt: str | None = None
    role: str = "support"

class PolicyFacts(BaseModel):
    insurer: str | None = None
    previous_insurer: str | None = None
    business_type: str | None = None
    make_model: str | None = None
    fuel: str | None = None
    rto: str | None = None
    engine_cc: int | None = None
    manufacture_year: int | None = None
    policy_type: str | None = None
    ncb_percent: float | None = None
    od_premium: float | None = None
    tp_premium: float | None = None
    other_premium: float | None = None
    source_pages: dict[str, int] = Field(default_factory=dict)
    missing_or_uncertain: list[str] = Field(default_factory=list)

class RateComponent(BaseModel):
    applicable: bool
    rate_percent: float | None = None
    status: Literal["resolved", "not_applicable", "unsupported", "ambiguous"] = "unsupported"
    explanation: str
    citations: list[Citation] = Field(default_factory=list)

class AnalysisResult(BaseModel):
    status: Literal["resolved", "unsupported", "ambiguous"]
    insurer: str | None = None
    facts: PolicyFacts
    od: RateComponent
    tp: RateComponent
    confidence: Literal["high", "medium", "low"]
    confidence_explanation: str
    decision_trace: list[str]
    citations: list[Citation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_extraction: dict[str, Any] = Field(default_factory=dict)

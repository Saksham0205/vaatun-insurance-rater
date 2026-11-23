from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

DecisionStatus = Literal["resolved", "not_applicable", "unsupported", "ambiguous"]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    original_name: str
    sha256: str
    byte_count: int
    status: str
    uploaded_at: datetime | str
    updated_at: datetime | str | None = None
    latest_analysis_id: str | None = None
    assessment_complete: bool | None = None
    insurer: str | None = None


class DocumentDetailResponse(DocumentResponse):
    analyses: list[dict[str, Any]] = Field(default_factory=list)


class DecisionComponentResponse(BaseModel):
    component: Literal["OD", "TP"]
    status: DecisionStatus
    applicable: bool
    rate_percent: str | None = None
    commission_amount: str | None = None
    rate_basis: str | None = None
    premium_basis: str | None = None
    selected_conditions: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    document_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    overall_status: Literal["resolved", "unsupported", "ambiguous"] | None = None
    assessment_complete: bool
    created_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None


class AnalysisStartResponse(BaseModel):
    analysis_id: str
    document_id: str
    status: Literal["processing", "completed", "failed"]
    idempotent_replay: bool = False
    analysis: dict[str, Any] | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int
    stats: dict[str, int] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    persistence: Literal["configured", "unconfigured"]
    version: str

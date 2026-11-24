from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

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

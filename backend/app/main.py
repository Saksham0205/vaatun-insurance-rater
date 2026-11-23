from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .api_schemas import (
    AnalysisStartResponse, DocumentDetailResponse, DocumentListResponse, DocumentResponse, HealthResponse,
)
from .auth import AuthenticatedUser, get_current_user
from .config import settings
from .rating_engine.document_pipeline import document_to_decision, result_dict
from .rating_engine import review as rating_review
from .repository import MAX_PDF_BYTES, PersistenceError, SupabaseRepository

class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        reserved = logging.LogRecord("", 0, "", 0, "", (), None).__dict__
        payload = {"timestamp": self.formatTime(record), "level": record.levelname,
                   "message": record.getMessage(), "logger": record.name}
        payload.update({key: value for key, value in record.__dict__.items()
                        if key not in reserved and key not in {"message", "asctime"} and not key.startswith("_")})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonLogFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("vaatun.api")

app = FastAPI(title="Vaatun Insurance Rater API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True, allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


def get_repository() -> SupabaseRepository:
    return SupabaseRepository()


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.perf_counter()
    request_id = request.headers.get("x-request-id", "")[:80]
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed", extra={"path": request.url.path, "request_id": request_id})
        raise
    logger.info("request_complete", extra={
        "path": request.url.path, "method": request.method, "status_code": response.status_code,
        "duration_ms": round((time.perf_counter() - start) * 1000, 1), "request_id": request_id,
    })
    response.headers["X-Request-ID"] = request_id or "not-provided"
    return response


@app.exception_handler(PersistenceError)
async def persistence_error_handler(_request: Request, exc: PersistenceError):
    logger.error("persistence_error", extra={"reason": str(exc)})
    return JSONResponse(status_code=503, content={"detail": "Persistent storage is temporarily unavailable."})


@app.get("/api/v1/health", response_model=HealthResponse)
def health(repository: Annotated[SupabaseRepository, Depends(get_repository)]):
    if not settings.supabase_url or not settings.supabase_service_role_key or not settings.supabase_publishable_key:
        return HealthResponse(status="degraded", service="vaatun-insurance-rater", persistence="unconfigured", version=app.version)
    try:
        repository.client.table("users").select("id").limit(1).execute()
        return HealthResponse(status="ok", service="vaatun-insurance-rater", persistence="configured", version=app.version)
    except Exception:
        logger.exception("health_persistence_check_failed")
        return HealthResponse(status="degraded", service="vaatun-insurance-rater", persistence="configured", version=app.version)


@app.post("/api/v1/documents/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: Annotated[UploadFile, File(...)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    repository: Annotated[SupabaseRepository, Depends(get_repository)],
):
    filename = Path(file.filename or "").name
    if not filename or Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=422, detail="Upload a PDF file.")
    if file.content_type not in {"application/pdf", "application/octet-stream", None}:
        raise HTTPException(status_code=422, detail="The uploaded file must have PDF content type.")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes or len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds the configured 25 MB limit.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="The uploaded file is not a valid PDF document.")
    digest = hashlib.sha256(content).hexdigest()
    doc, created = await run_in_threadpool(repository.upload_document, user.id, filename, content, digest)
    logger.info("document_uploaded", extra={"user_id": user.id, "document_id": doc["id"], "created_new": created})
    return _document_response(doc)


@app.get("/api/v1/documents", response_model=DocumentListResponse)
def list_documents(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    repository: Annotated[SupabaseRepository, Depends(get_repository)],
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, pattern="^(uploaded|processing|processed|failed)$"),
    insurer: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    rows = repository.list_documents(user.id, query=q, status=status, insurer=insurer, limit=limit, offset=offset)
    stats = repository.dashboard_stats(user.id)
    return DocumentListResponse(documents=[_document_response(row) for row in rows], total=stats["total"], stats=stats)


@app.get("/api/v1/documents/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    repository: Annotated[SupabaseRepository, Depends(get_repository)],
):
    row = repository.get_document_detail(user.id, str(document_id))
    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")
    analyses = [{**item, "result": item.pop("result_json", None)} for item in row.pop("analyses", [])]
    return {**_document_response(row).model_dump(), "analyses": analyses}


@app.delete("/api/v1/documents/{document_id}", status_code=204)
def delete_document(
    document_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    repository: Annotated[SupabaseRepository, Depends(get_repository)],
):
    if not repository.delete_document(user.id, str(document_id)):
        raise HTTPException(status_code=404, detail="Document not found.")
    logger.info("document_deleted", extra={"user_id": user.id, "document_id": str(document_id)})
    return Response(status_code=204)


@app.post("/api/v1/documents/{document_id}/analyze", response_model=AnalysisStartResponse)
async def analyze_document(
    document_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    repository: Annotated[SupabaseRepository, Depends(get_repository)],
    force: Annotated[bool, Query(description="Re-run extraction for a completed analysis")] = False,
):
    document = repository.get_document(user.id, str(document_id))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    analysis, claimed = repository.claim_analysis(user.id, document, force=force)
    if not claimed:
        return AnalysisStartResponse(
            analysis_id=analysis["id"], document_id=str(document_id), status=analysis["status"],
            idempotent_replay=True, analysis=_analysis_response(analysis),
        )
    try:
        content = await run_in_threadpool(repository.download_document, document["storage_path"])
        with tempfile.TemporaryDirectory(prefix="vaatun-analysis-") as temp_dir:
            local_pdf = Path(temp_dir) / "policy.pdf"
            local_pdf.write_bytes(content)
            pipeline_result = await run_in_threadpool(
                document_to_decision, local_pdf, rate_card_root=Path(__file__).resolve().parents[1] / "rate_cards")
            if pipeline_result.document_sha256 != document["sha256"]:
                raise RuntimeError("Stored document hash does not match uploaded source.")
        result = result_dict(pipeline_result)
        await run_in_threadpool(repository.save_analysis_result, user.id, document, analysis, result)
        saved = repository.get_analysis(user.id, analysis["id"])
        logger.info("analysis_completed", extra={
            "user_id": user.id, "document_id": document["id"], "analysis_id": analysis["id"],
            "assessment_status": result.get("assessment_status"),
        })
        return AnalysisStartResponse(
            analysis_id=analysis["id"], document_id=str(document_id), status="completed",
            idempotent_replay=False, analysis=_analysis_response(saved or analysis),
        )
    except Exception as exc:
        logger.exception("analysis_failed", extra={"user_id": user.id, "document_id": document["id"], "analysis_id": analysis["id"]})
        try:
            await run_in_threadpool(repository.fail_analysis, user.id, document["id"], analysis["id"],
                                    "Analysis processing failed; retry is available.")
        except Exception:
            logger.exception("analysis_failure_state_persist_failed", extra={"analysis_id": analysis["id"]})
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Policy analysis failed. You can retry this analysis.") from exc


class ReviewRequest(BaseModel):
    # field -> value; an empty value removes that override. Replaces earlier overrides.
    overrides: dict[str, Any] = Field(default_factory=dict)


@app.get("/api/v1/review/options")
def review_options(user: Annotated[AuthenticatedUser, Depends(get_current_user)]):
    """Reviewable rating inputs and the rate-card values each one accepts."""
    return rating_review.options()


@app.post("/api/v1/analyses/{analysis_id}/review")
async def review_analysis(
    analysis_id: UUID,
    body: ReviewRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    repository: Annotated[SupabaseRepository, Depends(get_repository)],
):
    """Apply reviewer-supplied rating inputs and recompute commission (no re-extraction)."""
    row = repository.get_analysis(user.id, str(analysis_id))
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    if row.get("status") != "completed" or not row.get("result_json"):
        raise HTTPException(status_code=409, detail="Only a completed analysis can be reviewed.")
    document = repository.get_document(user.id, str(row["document_id"]))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        result = await run_in_threadpool(
            rating_review.rerate, row["result_json"], body.overrides,
            Path(__file__).resolve().parents[1] / "rate_cards")
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await run_in_threadpool(repository.save_analysis_result, user.id, document, row, result)
    logger.info("analysis_reviewed", extra={"user_id": user.id, "analysis_id": str(analysis_id),
                                            "overridden_fields": sorted(result["overrides"])})
    return _analysis_response(repository.get_analysis(user.id, str(analysis_id)) or row)


@app.get("/api/v1/analyses/{analysis_id}")
def get_analysis(
    analysis_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    repository: Annotated[SupabaseRepository, Depends(get_repository)],
):
    row = repository.get_analysis(user.id, str(analysis_id))
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return _analysis_response(row)


def _document_response(row: dict) -> DocumentResponse:
    latest = row.get("latest_analysis") or {}
    insurer_fact = ((latest.get("result_json") or {}).get("facts") or {}).get("insurer") or {}
    return DocumentResponse(
        id=str(row["id"]), original_name=row["original_name"], sha256=row["sha256"],
        byte_count=row["byte_count"], status=row["status"], uploaded_at=row["uploaded_at"],
        updated_at=row.get("updated_at"), latest_analysis_id=latest.get("id"),
        assessment_complete=latest.get("assessment_complete"),
        insurer=insurer_fact.get("value"),
    )


def _analysis_response(row: dict) -> dict:
    return {
        "id": str(row["id"]), "document_id": str(row["document_id"]), "status": row["status"],
        "overall_status": row.get("overall_status"), "assessment_complete": row.get("assessment_complete", False),
        "created_at": row.get("created_at"), "completed_at": row.get("completed_at"),
        "error_message": row.get("error_message"), "result": row.get("result_json"),
        "extracted_facts": row.get("extracted_facts", []),
        "component_decisions": row.get("component_decisions", []),
        "evidence_references": row.get("evidence_references", []),
    }

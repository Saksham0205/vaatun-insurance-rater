from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from supabase import Client, create_client

from .config import settings

PIPELINE_VERSION = "local-rules-pipeline-v3"
MAX_PDF_BYTES = 25 * 1024 * 1024
FACT_FIELDS = (
    "insurer", "previous_insurer", "policy_type", "fuel", "engine_cc", "manufacture_year",
    "rto", "make_model", "od_premium", "tp_premium", "ncb_percent", "ncb_eligibility",
)


class PersistenceError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _service_client() -> Client:
    """Shared for the process: reusing its HTTP connections makes each query ~60 ms
    instead of paying client creation and a TLS handshake on every request."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise PersistenceError("Supabase persistence is not configured.")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


class SupabaseRepository:
    """Service-role persistence boundary; every document query is owner-scoped."""

    def __init__(self, client: Client | None = None):
        self._client = client

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = _service_client()
        return self._client

    def find_document_by_hash(self, user_id: str, sha256: str) -> dict[str, Any] | None:
        rows = self.client.table("documents").select("*").eq("user_id", user_id).eq("sha256", sha256).limit(1).execute().data
        return rows[0] if rows else None

    def upload_document(self, user_id: str, filename: str, content: bytes, sha256: str) -> tuple[dict[str, Any], bool]:
        existing = self.find_document_by_hash(user_id, sha256)
        if existing:
            return existing, False
        document_id = str(uuid.uuid4())
        safe_name = Path(filename).name.replace("/", "_").replace("\\", "_")[:240] or "policy.pdf"
        storage_path = f"{user_id}/{document_id}/{safe_name}"
        try:
            self.client.storage.from_(settings.supabase_bucket).upload(
                storage_path, content, {"content-type": "application/pdf", "upsert": "false"})
            row = {
                "id": document_id, "user_id": user_id, "original_name": safe_name,
                "sha256": sha256, "storage_path": storage_path, "byte_count": len(content),
                "mime_type": "application/pdf", "status": "uploaded",
            }
            inserted = self.client.table("documents").insert(row).execute().data
            return inserted[0], True
        except Exception as exc:
            # A unique-hash race is an idempotent upload. Other failures remove the
            # just-written object so storage and metadata do not drift apart.
            existing = self.find_document_by_hash(user_id, sha256)
            if existing:
                try:
                    self.client.storage.from_(settings.supabase_bucket).remove([storage_path])
                except Exception:
                    pass
                return existing, False
            try:
                self.client.storage.from_(settings.supabase_bucket).remove([storage_path])
            except Exception:
                pass
            raise PersistenceError("Could not persist uploaded PDF and document record.") from exc

    def list_documents(self, user_id: str, *, query: str | None = None, status: str | None = None,
                       insurer: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        req = self.client.table("documents").select("*").eq("user_id", user_id).order("uploaded_at", desc=True).range(offset, offset + limit - 1)
        if query:
            req = req.ilike("original_name", f"%{query}%")
        if status:
            req = req.eq("status", status)
        rows = req.execute().data
        if any(row["status"] == "processing" for row in rows):
            self.expire_stale_analyses(user_id)
            rows = req.execute().data
        latest = self._latest_analyses(user_id, [row["id"] for row in rows])
        for row in rows:
            row["latest_analysis"] = latest.get(row["id"])
        if insurer:
            rows = [row for row in rows
                    if ((row["latest_analysis"] or {}).get("insurer") or "").casefold() == insurer.casefold()]
        return rows

    def _latest_analyses(self, user_id: str, document_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Latest analysis per document in one query (not one query per document)."""
        if not document_ids:
            return {}
        rows = self.client.table("analyses") \
            .select("id,document_id,status,assessment_complete,created_at,insurer:result_json->facts->insurer->>value") \
            .eq("user_id", user_id).in_("document_id", document_ids).order("created_at", desc=True).execute().data
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest.setdefault(row["document_id"], row)
        return latest

    def dashboard_stats(self, user_id: str) -> dict[str, int]:
        counts = {"uploaded": 0, "processing": 0, "processed": 0, "failed": 0}
        for row in self.client.table("documents").select("status").eq("user_id", user_id).execute().data:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        incomplete = self.client.table("analyses").select("id", count="exact", head=True).eq("user_id", user_id).eq("status", "completed").eq("assessment_complete", False).execute()
        return {"total": sum(counts.values()), "processed": counts["processed"],
                "pending": counts["uploaded"] + counts["processing"], "incomplete": int(incomplete.count or 0)}

    def expire_stale_analyses(self, user_id: str) -> None:
        """Fail analyses stuck in ``processing`` past the stale window.

        Analysis runs inside the POST request; if that worker dies (reload, crash,
        deploy) nothing ever finishes the row, and pollers would wait forever.
        """
        stale_before = (datetime.now(timezone.utc) - timedelta(seconds=settings.analysis_stale_after_seconds)).isoformat()
        message = "Analysis did not finish (the server may have restarted); retry is available."
        expired = self.client.table("analyses").update(
            {"status": "failed", "error_message": message, "updated_at": _now(), "completed_at": None}) \
            .eq("user_id", user_id).eq("status", "processing").lt("updated_at", stale_before).execute().data or []
        for document_id in {row["document_id"] for row in expired}:
            self._set_document_status(user_id, document_id, "failed", message)

    def get_document(self, user_id: str, document_id: str) -> dict[str, Any] | None:
        rows = self.client.table("documents").select("*").eq("user_id", user_id).eq("id", document_id).limit(1).execute().data
        return rows[0] if rows else None

    def get_document_detail(self, user_id: str, document_id: str) -> dict[str, Any] | None:
        doc = self.get_document(user_id, document_id)
        if not doc:
            return None
        if doc["status"] == "processing":
            self.expire_stale_analyses(user_id)
            doc = self.get_document(user_id, document_id) or doc
        doc["analyses"] = self.client.table("analyses").select("id,status,overall_status,assessment_complete,created_at,completed_at,error_message,result_json") \
            .eq("user_id", user_id).eq("document_id", document_id).order("created_at", desc=True).execute().data
        doc["latest_analysis"] = doc["analyses"][0] if doc["analyses"] else None
        return doc

    def download_document(self, storage_path: str) -> bytes:
        try:
            return self.client.storage.from_(settings.supabase_bucket).download(storage_path)
        except Exception as exc:
            raise PersistenceError("Stored PDF could not be downloaded.") from exc

    def delete_document(self, user_id: str, document_id: str) -> bool:
        """Delete an owned PDF; database cascades remove its analysis records."""
        document = self.get_document(user_id, document_id)
        if not document:
            return False
        active = self.client.table("analyses").select("id").eq("user_id", user_id) \
            .eq("document_id", document_id).eq("status", "processing").limit(1).execute().data
        if active:
            raise PersistenceError("An analysis is still processing; wait for it to finish before deleting this policy.")
        try:
            self.client.storage.from_(settings.supabase_bucket).remove([document["storage_path"]])
            deleted = self.client.table("documents").delete().eq("id", document_id).eq("user_id", user_id).execute().data
            if not deleted:
                raise PersistenceError("The policy PDF was removed, but its record could not be deleted.")
            return True
        except PersistenceError:
            raise
        except Exception as exc:
            raise PersistenceError("Could not delete the policy PDF and its analysis.") from exc

    def list_analyses(self, user_id: str, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        req = self.client.table("analyses").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit)
        if status:
            req = req.eq("status", status)
        return req.execute().data

    def get_analysis(self, user_id: str, analysis_id: str) -> dict[str, Any] | None:
        rows = self.client.table("analyses").select("*").eq("user_id", user_id).eq("id", analysis_id).limit(1).execute().data
        if not rows:
            return None
        if rows[0]["status"] == "processing":
            self.expire_stale_analyses(user_id)
            rows = self.client.table("analyses").select("*").eq("user_id", user_id).eq("id", analysis_id).limit(1).execute().data or rows
        row = rows[0]
        row["extracted_facts"] = self.client.table("extracted_facts").select("*").eq("analysis_id", analysis_id).execute().data
        row["component_decisions"] = self.client.table("component_decisions").select("*").eq("analysis_id", analysis_id).execute().data
        row["evidence_references"] = self.client.table("evidence_references").select("*").eq("analysis_id", analysis_id).execute().data
        return row

    def claim_analysis(self, user_id: str, document: dict[str, Any], *, force: bool = False) -> tuple[dict[str, Any], bool]:
        """Claim the document's analysis for processing. ``force`` re-runs a completed one."""
        existing_rows = self.client.table("analyses").select("*").eq("user_id", user_id).eq("document_id", document["id"]) \
            .eq("document_sha256", document["sha256"]).eq("pipeline_version", PIPELINE_VERSION).limit(1).execute().data
        if not existing_rows:
            analysis = {
                "document_id": document["id"], "user_id": user_id,
                "document_sha256": document["sha256"], "pipeline_version": PIPELINE_VERSION,
                "status": "processing", "started_at": _now(), "updated_at": _now(),
            }
            try:
                row = self.client.table("analyses").insert(analysis).execute().data[0]
                self._set_document_status(user_id, document["id"], "processing")
                return row, True
            except Exception:
                existing_rows = self.client.table("analyses").select("*").eq("user_id", user_id).eq("document_id", document["id"]) \
                    .eq("document_sha256", document["sha256"]).eq("pipeline_version", PIPELINE_VERSION).limit(1).execute().data
                if not existing_rows:
                    raise PersistenceError("Could not create analysis record.")
        row = existing_rows[0]
        if row["status"] == "completed" and not force:
            return row, False
        stale_before = (datetime.now(timezone.utc) - timedelta(seconds=settings.analysis_stale_after_seconds)).isoformat()
        can_retry = (row["status"] in {"failed", "pending"} or (force and row["status"] == "completed")
                     or (row["status"] == "processing" and row.get("updated_at", "") < stale_before))
        if not can_retry:
            return row, False
        req = self.client.table("analyses").update({"status": "processing", "started_at": _now(), "updated_at": _now(), "completed_at": None, "error_message": None}) \
            .eq("id", row["id"]).eq("user_id", user_id).eq("status", row["status"]).select("*").execute().data
        if req:
            self._set_document_status(user_id, document["id"], "processing")
            return req[0], True
        current = self.client.table("analyses").select("*").eq("id", row["id"]).eq("user_id", user_id).limit(1).execute().data
        return (current[0] if current else row), False

    def save_analysis_result(self, user_id: str, document: dict[str, Any], analysis: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        analysis_id = analysis["id"]
        self.client.table("extracted_facts").delete().eq("analysis_id", analysis_id).execute()
        self.client.table("component_decisions").delete().eq("analysis_id", analysis_id).execute()
        facts, fact_refs = _fact_rows(analysis_id, result)
        if facts:
            fact_inserted = self.client.table("extracted_facts").insert(facts).execute().data
            for row, inserted in zip(facts, fact_inserted):
                row["_id"] = inserted["id"]
        decisions = []
        for component in ("OD", "TP"):
            item = result["decisions"][component]
            decisions.append({
                "analysis_id": analysis_id, "component": component, "status": item["status"],
                "applicable": item["applicable"], "rate_percent": item.get("rate_percent"),
                "commission_amount": item.get("commission_amount"), "premium_basis": item.get("premium_basis"),
                "rate_basis": item.get("rate_basis"), "selected_conditions": item.get("selected_conditions") or {},
                "calculation": item.get("calculation"), "issues": item.get("issues") or [],
            })
        decision_rows = self.client.table("component_decisions").insert(decisions).execute().data
        decision_ids = {row["component"]: row["id"] for row in decision_rows}
        evidence = []
        for fact_row in facts:
            ref = fact_row.get("source_ref")
            if ref:
                evidence.append(_evidence_row(analysis_id, ref, "policy", extracted_fact_id=fact_row.get("_id")))
        for component in ("OD", "TP"):
            for ref in result["decisions"][component].get("evidence", []):
                evidence.append(_evidence_row(
                    analysis_id, ref, "policy" if ref.get("source_file") == document["original_name"]
                    else "other" if ref.get("source_file") == "Operator review" else "rate_card",
                    component_decision_id=decision_ids[component]))
        if evidence:
            self.client.table("evidence_references").insert(evidence).execute()
        assessment_complete = result.get("assessment_status") == "complete"
        update = {
            "status": "completed", "overall_status": result["decisions"]["overall"],
            "assessment_complete": assessment_complete, "completed_at": _now(), "updated_at": _now(),
            "error_message": None, "result_json": result,
        }
        saved = self.client.table("analyses").update(update).eq("id", analysis_id).eq("user_id", user_id).select("*").execute().data
        self._set_document_status(user_id, document["id"], "processed")
        return saved[0]

    def fail_analysis(self, user_id: str, document_id: str, analysis_id: str, message: str) -> None:
        self.client.table("analyses").update({"status": "failed", "error_message": message[:1000], "updated_at": _now(), "completed_at": None}) \
            .eq("id", analysis_id).eq("user_id", user_id).execute()
        self._set_document_status(user_id, document_id, "failed", message[:1000])

    def _set_document_status(self, user_id: str, document_id: str, status: str, error: str | None = None) -> None:
        self.client.table("documents").update({"status": status, "updated_at": _now(), "error_message": error}) \
            .eq("id", document_id).eq("user_id", user_id).execute()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fact_rows(analysis_id: str, result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts = result.get("facts", {})
    conflicts = result.get("conflicts", {})
    low = result.get("low_confidence", {})
    rows: list[dict[str, Any]] = []
    for field in FACT_FIELDS:
        fact = facts.get(field)
        if fact:
            rows.append(_fact_row(analysis_id, field, fact))
        elif field in conflicts:
            rows.extend(_fact_row(analysis_id, field, item, is_conflict=True) for item in conflicts[field])
        elif field in low:
            rows.extend(_fact_row(analysis_id, field, item, is_low_confidence=True) for item in low[field])
        else:
            rows.append({"analysis_id": analysis_id, "field_name": field, "value": None,
                         "is_missing": True, "is_conflict": False, "is_low_confidence": False})
    return rows, []


def _fact_row(analysis_id: str, field: str, fact: dict[str, Any], *, is_conflict: bool = False,
              is_low_confidence: bool = False) -> dict[str, Any]:
    return {
        "analysis_id": analysis_id, "field_name": field, "value": fact.get("value"),
        "page": fact.get("page"), "confidence": fact.get("confidence"),
        "extracted_text": fact.get("text"), "source_ref": fact.get("source"),
        "is_missing": False, "is_conflict": is_conflict, "is_low_confidence": is_low_confidence,
    }


def _evidence_row(analysis_id: str, ref: dict[str, Any], source_kind: str, *,
                  component_decision_id: str | None = None,
                  extracted_fact_id: str | None = None) -> dict[str, Any]:
    return {
        "analysis_id": analysis_id, "component_decision_id": component_decision_id,
        "extracted_fact_id": extracted_fact_id, "source_kind": source_kind,
        "source_file": ref.get("source_file") or "unknown",
        "source_sha256": ref.get("source_sha256"), "sheet": ref.get("sheet"), "cell": ref.get("cell"),
        "page": ref.get("page"), "table_number": ref.get("table"), "row_number": ref.get("row"),
        "column_number": ref.get("column"), "role": ref.get("role") or "support",
    }

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import AuthenticatedUser, get_current_user
from app.main import app, get_repository
from app.repository import _fact_rows

USER_ID = "8a4ff201-d14d-44e5-b94b-a5ca689f8d17"


class FakeRepository:
    def __init__(self):
        self.documents = {}
        self.analyses = {}
        self.upload_count = 0
        self.save_count = 0
        self.blob = b"%PDF-1.7 fake fixture"

    def upload_document(self, user_id, filename, content, sha256):
        existing = next((row for row in self.documents.values() if row["user_id"] == user_id and row["sha256"] == sha256), None)
        if existing:
            return existing, False
        self.upload_count += 1
        row = {"id": str(uuid4()), "user_id": user_id, "original_name": filename, "sha256": sha256,
               "storage_path": f"{user_id}/x/{filename}", "byte_count": len(content), "status": "uploaded",
               "uploaded_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat()}
        self.documents[row["id"]] = row
        self.blob = content
        return row, True

    def list_documents(self, user_id, **kwargs):
        return [row for row in self.documents.values() if row["user_id"] == user_id]

    def count_documents(self, user_id):
        return sum(row["user_id"] == user_id for row in self.documents.values())

    def dashboard_stats(self, user_id):
        owned = [row for row in self.documents.values() if row["user_id"] == user_id]
        return {"total": len(owned), "processed": sum(row["status"] == "processed" for row in owned),
                "pending": sum(row["status"] in {"uploaded", "processing"} for row in owned), "incomplete": 0}

    def get_document(self, user_id, document_id):
        row = self.documents.get(document_id)
        return row if row and row["user_id"] == user_id else None

    def get_document_detail(self, user_id, document_id):
        row = self.get_document(user_id, document_id)
        if not row:
            return None
        return {**row, "analyses": [a for a in self.analyses.values() if a["document_id"] == document_id]}

    def download_document(self, storage_path):
        return self.blob

    def claim_analysis(self, user_id, document, force=False):
        existing = next((a for a in self.analyses.values() if a["document_id"] == document["id"]), None)
        if existing and force and existing["status"] == "completed":
            existing["status"] = "processing"
            return existing, True
        if existing:
            return existing, False
        row = {"id": str(uuid4()), "document_id": document["id"], "status": "processing",
               "created_at": datetime.now(timezone.utc).isoformat(), "result_json": None}
        self.analyses[row["id"]] = row
        return row, True

    def save_analysis_result(self, user_id, document, analysis, result):
        self.save_count += 1
        self.analyses[analysis["id"]].update({"status": "completed", "overall_status": result["decisions"]["overall"],
                                                "assessment_complete": result["assessment_status"] == "complete",
                                                "result_json": result, "completed_at": datetime.now(timezone.utc).isoformat()})

    def get_analysis(self, user_id, analysis_id):
        row = self.analyses.get(analysis_id)
        if not row:
            return None
        document = self.documents[row["document_id"]]
        if document["user_id"] != user_id:
            return None
        return {**row, "extracted_facts": [], "component_decisions": [], "evidence_references": []}

    def fail_analysis(self, user_id, document_id, analysis_id, message):
        self.analyses[analysis_id].update({"status": "failed", "error_message": message})


@pytest.fixture
def api():
    repo = FakeRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(USER_ID, "user@example.test")
    with TestClient(app) as client:
        yield client, repo
    app.dependency_overrides.clear()


def test_upload_and_list_are_owner_scoped_and_duplicate_upload_is_idempotent(api):
    client, repo = api
    response = client.post("/api/v1/documents/upload", files={"file": ("policy.pdf", b"%PDF-1.7 test", "application/pdf")})
    assert response.status_code == 201
    document_id = response.json()["id"]
    duplicate = client.post("/api/v1/documents/upload", files={"file": ("renamed.pdf", b"%PDF-1.7 test", "application/pdf")})
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == document_id
    assert repo.upload_count == 1
    assert client.get("/api/v1/documents").json()["total"] == 1
    repo.documents["other"] = {**repo.documents[document_id], "id": "other", "user_id": "other-user"}
    assert client.get("/api/v1/documents").json()["total"] == 1
    assert client.get("/api/v1/documents/22222222-2222-4222-8222-222222222222").status_code == 404


def test_upload_validation_rejects_non_pdf_and_bad_magic(api):
    client, _ = api
    assert client.post("/api/v1/documents/upload", files={"file": ("policy.txt", b"no", "text/plain")}).status_code == 422
    assert client.post("/api/v1/documents/upload", files={"file": ("policy.pdf", b"not a pdf", "application/pdf")}).status_code == 422


def test_analysis_persists_result_and_retry_returns_existing_record(api, monkeypatch):
    client, repo = api
    upload = client.post("/api/v1/documents/upload", files={"file": ("policy.pdf", b"%PDF-1.7 analysis", "application/pdf")})
    document_id = upload.json()["id"]
    sha = upload.json()["sha256"]
    result = {
        "document": {"name": "policy.pdf", "sha256": sha}, "assessment_status": "complete",
        "facts": {"insurer": {"value": "godigit", "page": 1, "confidence": .99, "text": "Go Digit", "source": {"source_file": "policy.pdf", "source_sha256": sha, "page": 1, "role": "policy"}}},
        "conflicts": {}, "low_confidence": {}, "missing_or_uncertain": [],
        "decisions": {
            "overall": "unsupported",
            "OD": {"status": "not_applicable", "applicable": False, "rate_percent": None, "evidence": [], "issues": []},
            "TP": {"status": "unsupported", "applicable": True, "rate_percent": None, "evidence": [], "issues": ["No verified rate"]},
        },
    }
    monkeypatch.setattr("app.main.document_to_decision", lambda *args, **kwargs: SimpleNamespace(document_sha256=sha))
    monkeypatch.setattr("app.main.result_dict", lambda _result: result)
    first = client.post(f"/api/v1/documents/{document_id}/analyze")
    assert first.status_code == 200
    analysis_id = first.json()["analysis_id"]
    assert repo.save_count == 1
    assert first.json()["analysis"]["result"]["decisions"]["TP"]["rate_percent"] is None
    retry = client.post(f"/api/v1/documents/{document_id}/analyze")
    assert retry.status_code == 200
    assert retry.json()["analysis_id"] == analysis_id
    assert retry.json()["idempotent_replay"] is True
    assert repo.save_count == 1
    assert client.get(f"/api/v1/analyses/{analysis_id}").json()["result"] == result


def test_analysis_is_not_accessible_to_another_user(api):
    client, repo = api
    upload = client.post("/api/v1/documents/upload", files={"file": ("policy.pdf", b"%PDF-1.7", "application/pdf")})
    doc_id = upload.json()["id"]
    other = "22222222-2222-4222-8222-222222222222"
    assert repo.get_document(other, doc_id) is None


def test_fact_persistence_rows_include_conflicts_and_missing_values():
    result = {"facts": {"fuel": None, "od_premium": None},
              "conflicts": {"fuel": [
                  {"value": "Petrol", "page": 1, "confidence": .9, "text": "Fuel: Petrol", "source": {"page": 1}},
                  {"value": "Diesel", "page": 2, "confidence": .9, "text": "Fuel: Diesel", "source": {"page": 2}},
              ]}, "low_confidence": {}, "missing_or_uncertain": []}
    rows, _ = _fact_rows("analysis-id", result)
    fuel_rows = [row for row in rows if row["field_name"] == "fuel"]
    od_rows = [row for row in rows if row["field_name"] == "od_premium"]
    assert len(fuel_rows) == 2 and all(row["is_conflict"] for row in fuel_rows)
    assert {row["page"] for row in fuel_rows} == {1, 2}
    assert len(od_rows) == 1 and od_rows[0]["is_missing"]


def test_auth_rejects_missing_and_invalid_bearer(monkeypatch):
    with pytest.raises(HTTPException) as missing:
        get_current_user(None)
    assert missing.value.status_code == 401
    monkeypatch.setattr("app.auth.settings.supabase_url", "https://example.supabase.co")
    monkeypatch.setattr("app.auth.settings.supabase_publishable_key", "public-test-key")
    monkeypatch.setattr("app.auth.create_client", lambda *_: SimpleNamespace(auth=SimpleNamespace(get_user=lambda _token: SimpleNamespace(user=None))))
    from fastapi.security import HTTPAuthorizationCredentials
    with pytest.raises(HTTPException) as invalid:
        get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials="expired"))
    assert invalid.value.status_code == 401


def _reliance_result(sha):
    from decimal import Decimal
    from app.rating_engine import review
    from app.rating_engine.models import PolicyInput, SourceRef
    doc = SourceRef("policy.pdf", sha, page=1, role="policy_fact")
    policy = PolicyInput(insurer="Reliance General Insurance", policy_type="Private Car Package Policy",
                         cover="Private Car Package Policy", engine_cc=1197, geography="Delhi",
                         od_premium=Decimal("10000"), tp_premium=Decimal("3416"),
                         source_evidence={k: [doc] for k in ("insurer", "policy_type", "engine_cc", "state",
                                                               "od_premium", "tp_premium")})
    return {"document": {"name": "policy.pdf", "sha256": sha, "ocr_pages_limited": False},
            "assessment_status": "incomplete",
            "facts": {"insurer": {"value": "reliance-indusind", "page": 1, "confidence": .99, "text": "Reliance",
                                  "source": {"source_file": "policy.pdf", "source_sha256": sha, "page": 1, "role": "policy"}}},
            "conflicts": {}, "low_confidence": {}, "missing_or_uncertain": [],
            "policy_input": review.policy_to_dict(policy),
            "decisions": {"overall": "ambiguous",
                          "OD": {"status": "ambiguous", "applicable": True, "evidence": [], "issues": ["Fuel missing"]},
                          "TP": {"status": "ambiguous", "applicable": True, "evidence": [], "issues": ["Fuel missing"]}}}


def _analyzed(api, monkeypatch, result_factory=_reliance_result):
    client, repo = api
    upload = client.post("/api/v1/documents/upload", files={"file": ("policy.pdf", b"%PDF-1.7 review", "application/pdf")})
    document_id, sha = upload.json()["id"], upload.json()["sha256"]
    monkeypatch.setattr("app.main.document_to_decision", lambda *a, **k: SimpleNamespace(document_sha256=sha))
    monkeypatch.setattr("app.main.result_dict", lambda _r: result_factory(sha))
    started = client.post(f"/api/v1/documents/{document_id}/analyze")
    assert started.status_code == 200
    return client, repo, document_id, started.json()["analysis_id"]


def test_review_endpoint_applies_overrides_and_persists_commission(api, monkeypatch):
    client, repo, _doc, analysis_id = _analyzed(api, monkeypatch)
    response = client.post(f"/api/v1/analyses/{analysis_id}/review", json={"overrides": {"fuel": "Petrol"}})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["decisions"]["OD"]["status"] == "resolved"
    assert result["decisions"]["OD"]["rate_percent"] == "22.5"  # Reliance Delhi petrol
    assert result["decisions"]["OD"]["commission_amount"] == "2250.00"
    assert result["totals"]["commission_total"] == "2250.00"
    assert response.json()["assessment_complete"] is True
    assert repo.save_count == 2
    # Reset removes the override and returns to the document-only decision.
    reset = client.post(f"/api/v1/analyses/{analysis_id}/review", json={"overrides": {}})
    assert reset.json()["result"]["decisions"]["OD"]["status"] == "ambiguous"


def test_review_endpoint_validates_input(api, monkeypatch):
    client, _repo, _doc, analysis_id = _analyzed(api, monkeypatch)
    bad = client.post(f"/api/v1/analyses/{analysis_id}/review", json={"overrides": {"fuel": "Steam"}})
    assert bad.status_code == 422 and "Fuel" in bad.json()["detail"]
    missing = client.post(f"/api/v1/analyses/{uuid4()}/review", json={"overrides": {}})
    assert missing.status_code == 404


def test_review_requires_stored_inputs(api, monkeypatch):
    def legacy(sha):
        result = _reliance_result(sha)
        result.pop("policy_input")
        return result
    client, _repo, _doc, analysis_id = _analyzed(api, monkeypatch, legacy)
    response = client.post(f"/api/v1/analyses/{analysis_id}/review", json={"overrides": {"fuel": "Petrol"}})
    assert response.status_code == 409


def test_forced_rerun_extracts_again(api, monkeypatch):
    client, repo, document_id, analysis_id = _analyzed(api, monkeypatch)
    assert client.post(f"/api/v1/documents/{document_id}/analyze").json()["idempotent_replay"] is True
    rerun = client.post(f"/api/v1/documents/{document_id}/analyze?force=true")
    assert rerun.status_code == 200 and rerun.json()["idempotent_replay"] is False
    assert repo.save_count == 2



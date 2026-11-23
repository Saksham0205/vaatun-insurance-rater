"""Opt-in destructive-cleanup integration test for a dedicated Supabase project.

Run with VAATUN_RUN_SUPABASE_E2E=1 python -m pytest tests/test_supabase_e2e_live.py -q.
It creates two temporary confirmed users, uploads one original fixture, verifies
API/Storage ownership and persistence, and removes all test users and objects.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from supabase import create_client

from app.config import settings
from app.main import app
from app.repository import SupabaseRepository


pytestmark = pytest.mark.skipif(
    os.getenv("VAATUN_RUN_SUPABASE_E2E") != "1",
    reason="Set VAATUN_RUN_SUPABASE_E2E=1 to run against the configured live project.",
)


def _read_with_restarted_backend(analysis_id: str, token: str) -> dict:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    cwd = Path(__file__).resolve().parents[1]

    def launch():
        return subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    persisted = []
    for _ in range(2):
        process = launch()
        try:
            for _attempt in range(60):
                if process.poll() is not None:
                    raise AssertionError("FastAPI process exited before becoming healthy")
                try:
                    if httpx.get(f"{base}/api/v1/health", timeout=1).json().get("status") == "ok":
                        break
                except httpx.HTTPError:
                    time.sleep(0.25)
            else:
                raise AssertionError("FastAPI process did not become healthy")
            response = httpx.get(f"{base}/api/v1/analyses/{analysis_id}", headers={"Authorization": f"Bearer {token}"}, timeout=20)
            assert response.status_code == 200, response.text
            persisted.append(response.json())
        finally:
            process.terminate()
            process.wait(timeout=10)
    assert persisted[0]["result"] == persisted[1]["result"]
    return persisted[1]


def test_live_auth_document_analysis_persistence_and_owner_isolation():
    assert settings.supabase_url and settings.supabase_publishable_key and settings.supabase_service_role_key
    admin = create_client(settings.supabase_url, settings.supabase_service_role_key)
    owner = SupabaseRepository(admin)
    users: list[str] = []
    clients = []
    document_id = analysis_id = storage_path = failure_storage_path = None
    user_a = user_b = None
    try:
        for _ in range(2):
            email = f"vaatun-e2e-{uuid.uuid4().hex}@example.com"
            password = secrets.token_urlsafe(24)
            created = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
            assert created and created.id
            users.append(str(created.id))
            client = create_client(settings.supabase_url, settings.supabase_publishable_key)
            clients.append(client)
            auth = client.auth.sign_in_with_password({"email": email, "password": password})
            assert auth.session and auth.user and str(auth.user.id) == str(created.id)
        user_a, user_b = clients
        token_a = user_a.auth.get_session().access_token
        token_b = user_b.auth.get_session().access_token
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}
        fixture = Path(__file__).resolve().parents[2] / "sample-policies" / "pvt-car-satp-go-digit.pdf"
        content = fixture.read_bytes()

        # User A uploads through the real FastAPI API; API verifies the Supabase token.
        with TestClient(app) as client:
            upload = client.post("/api/v1/documents/upload", headers=headers_a,
                                 files={"file": (fixture.name, content, "application/pdf")})
            assert upload.status_code == 201, upload.text
            document_id = upload.json()["id"]
            doc = owner.get_document(users[0], document_id)
            assert doc and doc["sha256"] == hashlib.sha256(content).hexdigest()
            assert doc["user_id"] == users[0]
            storage_path = doc["storage_path"]
            stored = owner.download_document(storage_path)
            assert hashlib.sha256(stored).hexdigest() == doc["sha256"]

            # User A runs the real extractor/rater and stores its full result.
            analyzed = client.post(f"/api/v1/documents/{document_id}/analyze", headers=headers_a)
            assert analyzed.status_code == 200, analyzed.text
            result = analyzed.json()["analysis"]
            analysis_id = result["id"]
            assert result["status"] == "completed"
            assert result["result"]["document"]["sha256"] == doc["sha256"]
            assert set(result["result"]["decisions"]) >= {"OD", "TP"}
            assert result["result"]["document"]["ocr_pages"]
            assert {row["component"] for row in result["component_decisions"]} == {"OD", "TP"}
            assert result["extracted_facts"] and any(row["is_missing"] for row in result["extracted_facts"])
            assert result["evidence_references"]
            persisted = client.get(f"/api/v1/analyses/{analysis_id}", headers=headers_a)
            assert persisted.status_code == 200
            assert persisted.json()["result"] == result["result"]

            # RLS also denies User B direct PostgREST reads, independently of API ownership filters.
            assert user_a.table("documents").select("id").eq("id", document_id).execute().data
            assert user_b.table("documents").select("id").eq("id", document_id).execute().data == []
            assert user_b.table("analyses").select("id").eq("id", analysis_id).execute().data == []

            # A repeated completed request must replay, not create a second analysis.
            replay = client.post(f"/api/v1/documents/{document_id}/analyze", headers=headers_a)
            assert replay.status_code == 200 and replay.json()["analysis_id"] == analysis_id
            assert replay.json()["idempotent_replay"] is True
            analyses = admin.table("analyses").select("id").eq("document_id", document_id).execute().data
            assert len(analyses) == 1

            # Independently launch, stop, and relaunch Uvicorn; persisted DB state must survive.
            restarted_result = _read_with_restarted_backend(analysis_id, token_a)
            assert restarted_result["result"] == result["result"]

            # Exercise the failed -> processing -> completed retry path on the same analysis row.
            admin.table("analyses").update({"status": "failed", "error_message": "E2E injected retry state"}).eq("id", analysis_id).execute()
            admin.table("documents").update({"status": "failed"}).eq("id", document_id).execute()
            retry = client.post(f"/api/v1/documents/{document_id}/analyze", headers=headers_a)
            assert retry.status_code == 200, retry.text
            assert retry.json()["analysis_id"] == analysis_id
            assert retry.json()["status"] == "completed"
            assert len(admin.table("analyses").select("id").eq("document_id", document_id).execute().data) == 1

            # User B cannot list or fetch A's records through the API.
            assert all(item["id"] != document_id for item in client.get("/api/v1/documents", headers=headers_b).json()["documents"])
            assert client.get(f"/api/v1/documents/{document_id}", headers=headers_b).status_code == 404
            assert client.get(f"/api/v1/analyses/{analysis_id}", headers=headers_b).status_code == 404

            # Invalid PDF internals (while passing upload's header check) must be recorded failed;
            # a retry is allowed and reuses that same failed analysis row safely.
            bad_upload = client.post("/api/v1/documents/upload", headers=headers_a,
                                     files={"file": ("broken.pdf", b"%PDF-invalid-fixture", "application/pdf")})
            assert bad_upload.status_code == 201, bad_upload.text
            bad_id = bad_upload.json()["id"]
            bad_doc = owner.get_document(users[0], bad_id)
            failure_storage_path = bad_doc["storage_path"]
            failed = client.post(f"/api/v1/documents/{bad_id}/analyze", headers=headers_a)
            assert failed.status_code == 500
            failure_row = admin.table("analyses").select("id,status,error_message").eq("document_id", bad_id).execute().data
            assert len(failure_row) == 1 and failure_row[0]["status"] == "failed" and failure_row[0]["error_message"]
            failed_retry = client.post(f"/api/v1/documents/{bad_id}/analyze", headers=headers_a)
            assert failed_retry.status_code == 500
            after_retry = admin.table("analyses").select("id,status").eq("document_id", bad_id).execute().data
            assert len(after_retry) == 1 and after_retry[0]["id"] == failure_row[0]["id"]

        # Test Storage RLS with actual User A and User B access tokens.
        a_bytes = user_a.storage.from_(settings.supabase_bucket).download(storage_path)
        assert hashlib.sha256(a_bytes).hexdigest() == hashlib.sha256(content).hexdigest()
        with pytest.raises(Exception):
            user_b.storage.from_(settings.supabase_bucket).download(storage_path)

        # Logout clears the client session; missing/invalid credentials are rejected.
        user_b.auth.sign_out()
        assert user_b.auth.get_session() is None
        with TestClient(app) as client:
            assert client.get(f"/api/v1/documents/{document_id}").status_code == 401
            expired = client.get(f"/api/v1/documents/{document_id}", headers={"Authorization": "Bearer expired.invalid.token"})
            assert expired.status_code == 401
    finally:
        paths = [path for path in (storage_path, failure_storage_path) if path]
        if paths:
            try:
                admin.storage.from_(settings.supabase_bucket).remove(paths)
            except Exception:
                pass
        for user_id in users:
            try:
                # Deleting auth.users cascades document, analysis and result rows.
                admin.auth.admin.delete_user(user_id)
            except Exception:
                pass

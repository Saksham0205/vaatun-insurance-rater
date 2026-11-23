from .config import settings
from supabase import create_client
import uuid

def client():
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

def persist_run(filename: str, content: bytes, result: dict) -> str:
    sb=client()
    run_id=str(uuid.uuid4())
    path=f"{run_id}/{filename}"
    sb.storage.from_(settings.supabase_bucket).upload(path,content,{"content-type":"application/pdf","upsert":"false"})
    sb.table("analysis_runs").insert({
        "id":run_id,"filename":filename,"storage_path":path,"status":result["status"],"result":result
    }).execute()
    return run_id

def list_runs():
    return client().table("analysis_runs").select("id,filename,status,created_at,result").order("created_at",desc=True).execute().data

def get_run(run_id: str):
    rows=client().table("analysis_runs").select("*").eq("id",run_id).limit(1).execute().data
    return rows[0] if rows else None

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_file = Path(__file__).resolve().parent.parent / ".env"

class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_publishable_key: str = ""
    supabase_bucket: str = "policy-pdfs"
    # `localhost` and `127.0.0.1` are different browser origins.  Support both
    # local development URLs by default, including Playwright's loopback host.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Dev servers may select another port when 3000 is occupied. This only
    # matches loopback hosts; deployed origins must remain in CORS_ORIGINS.
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    max_upload_bytes: int = 25 * 1024 * 1024
    analysis_stale_after_seconds: int = 1800
    model_config = SettingsConfigDict(env_file=(_env_file, ".env"), extra="ignore")

settings = Settings()

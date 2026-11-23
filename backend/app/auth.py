import hashlib
import threading
import time
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from .config import settings

bearer = HTTPBearer(auto_error=False)
TOKEN_CACHE_SECONDS = 60
_token_cache: dict[str, tuple[float, "AuthenticatedUser"]] = {}
_token_lock = threading.Lock()


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None = None


@lru_cache(maxsize=1)
def _auth_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_publishable_key)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Bearer access token required.")
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(status_code=503, detail="Supabase Auth is not configured.")
    key = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    now = time.monotonic()
    with _token_lock:
        cached = _token_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        user = _auth_client().auth.get_user(credentials.credentials).user
        if user is None:
            raise ValueError("No authenticated user returned")
    except Exception as exc:
        raise _unauthorized("Invalid or expired access token.") from exc
    result = AuthenticatedUser(id=str(user.id), email=getattr(user, "email", None))
    with _token_lock:
        if len(_token_cache) > 1000:
            _token_cache.clear()
        _token_cache[key] = (now + TOKEN_CACHE_SECONDS, result)
    return result

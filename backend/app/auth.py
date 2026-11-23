from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import create_client

from .config import settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None = None


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer access token required.", headers={"WWW-Authenticate": "Bearer"})
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(status_code=503, detail="Supabase Auth is not configured.")
    try:
        client = create_client(settings.supabase_url, settings.supabase_publishable_key)
        response = client.auth.get_user(credentials.credentials)
        user = response.user
        if user is None:
            raise ValueError("No authenticated user returned")
        return AuthenticatedUser(id=str(user.id), email=getattr(user, "email", None))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.", headers={"WWW-Authenticate": "Bearer"}) from exc

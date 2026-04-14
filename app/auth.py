import os

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

API_KEY = os.getenv("API_KEY", "canvia_aquesta_clau")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency that validates the X-API-Key header against the API_KEY env var."""
    if api_key is None or api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key

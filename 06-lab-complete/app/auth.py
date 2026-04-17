from fastapi import Header, HTTPException
from app.config import settings


def verify_api_key(x_api_key: str = Header(...)) -> str:
    """
    Verify X-API-Key header.
    Returns user_id (derived from key) if valid.
    Raises 401 if missing or invalid.
    """
    if not x_api_key or x_api_key != settings.agent_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
        )
    # Derive a stable user_id from the key (first 8 chars as bucket)
    return x_api_key[:8]

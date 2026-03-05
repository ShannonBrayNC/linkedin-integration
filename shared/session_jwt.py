from __future__ import annotations

import time
from typing import Dict, Any

import jwt  # PyJWT
from .config import DEV_BYPASS_AAD_VALIDATION


def mint_session(identity: Dict[str, Any], secret: str, ttl_seconds: int) -> str:
    """
    Mint a signed session JWT used by the web UI to call /api/cards/* endpoints.
    """
    now = int(time.time())

    payload = {
        # normalized identity fields used elsewhere
        "tid": identity.get("tid") or identity.get("tenantId") or "dev-tenant",
        "oid": identity.get("oid") or identity.get("objectId") or "dev-user",
        "upn": identity.get("upn") or identity.get("preferred_username") or "dev@example.com",
        "name": identity.get("name") or "Dev User",
        "channel": identity.get("channel") or "local",
        "iat": now,
        "exp": now + int(ttl_seconds),
        "v": 1,
    }

    return jwt.encode(payload, secret, algorithm="HS256")


def require_session(session_token: str, secret: str) -> Dict[str, Any]:
    """
    Validate/parse the session JWT.
    DEV_BYPASS_AAD_VALIDATION is ONLY for local demo/dev.
    """
    if DEV_BYPASS_AAD_VALIDATION:
        # If you're in dev-bypass mode, allow missing/garbage tokens too.
        # But if a token exists, try to decode it for realism.
        if not session_token:
            return {
                "tid": "dev-tenant",
                "oid": "dev-user",
                "upn": "dev@example.com",
                "name": "Dev User",
                "channel": "local",
            }
        try:
            return jwt.decode(session_token, secret, algorithms=["HS256"])
        except Exception:
            return {
                "tid": "dev-tenant",
                "oid": "dev-user",
                "upn": "dev@example.com",
                "name": "Dev User",
                "channel": "local",
            }

    if not session_token:
        raise Exception("Missing session")

    return jwt.decode(session_token, secret, algorithms=["HS256"])

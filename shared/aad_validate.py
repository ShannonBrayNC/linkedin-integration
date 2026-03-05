from .config import DEV_BYPASS_AAD_VALIDATION

def validate_aad_access_token(raw_token: str) -> dict:
    """
    Ship-fast:
    - DEV_BYPASS_AAD_VALIDATION=true -> accept any token and emit stable claims.
    - Later: replace with real AAD JWT validation (OpenID config + JWKS).
    """
    if DEV_BYPASS_AAD_VALIDATION:
        return {
            "tid": "dev-tenant",
            "oid": "dev-user",
            "upn": "dev@example.com",
            "name": "Dev User"
        }

    raise NotImplementedError("AAD validation not enabled yet")

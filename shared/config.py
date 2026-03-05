import os


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def get(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise ValueError(f"Missing required env var: {name}")
    return val


# -----------------------------
# Dev / Auth
# -----------------------------
# Flip this off in production once AAD validation is wired fully
DEV_BYPASS_AAD_VALIDATION = env_bool("DEV_BYPASS_AAD_VALIDATION", True)

SESSION_SIGNING_SECRET = os.getenv("SESSION_SIGNING_SECRET", "dev-only-secret-change-me")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "900"))


# -----------------------------
# Storage
# -----------------------------
# Storage mode: "memory" for quick ship, "table" or "cosmos" later
STORAGE_MODE = os.getenv("STORAGE_MODE", "memory").strip().lower()


# -----------------------------
# SharePoint publishing (optional)
# -----------------------------
SHAREPOINT_ENABLED = env_bool("SHAREPOINT_ENABLED", False)
SHAREPOINT_PROVIDER = os.getenv("SHAREPOINT_PROVIDER", "graph").strip().lower()  # graph | spo

SP_TENANT_ID = os.getenv("SP_TENANT_ID")
SP_CLIENT_ID = os.getenv("SP_CLIENT_ID")
SP_CLIENT_SECRET = os.getenv("SP_CLIENT_SECRET")

SP_SITE_ID = os.getenv("SP_SITE_ID")
SP_LIST_ID = os.getenv("SP_LIST_ID")


# -----------------------------
# LinkedIn (demo-first)
# -----------------------------
# Keep consistent with your chosen API version header
LI_VERSION = os.getenv("LI_VERSION", "202601").strip()

# Token can come from app settings; do not require it for startup
LI_ACCESS_TOKEN = os.getenv("LI_ACCESS_TOKEN", "").strip()

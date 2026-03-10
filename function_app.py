import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import azure.functions as func

from shared.cache_backend import (
    compute_etag,
    get_cache_backend,
    iso_utc,
    utc_now,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ----------------------------
# Config
# ----------------------------
ALLOWED_ORIGINS = {
    "https://echomediaai.sharepoint.com",
}

DEFAULT_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(24 * 60 * 60)))  # 24h default
CACHE_CONTAINER = os.getenv("CACHE_CONTAINER", "cache")
CACHE_ALLOW_STALE_ON_ERROR = (os.getenv("CACHE_ALLOW_STALE_ON_ERROR", "true").lower() == "true")
CACHE_FLUSH_KEY = os.getenv("CACHE_FLUSH_KEY", "").strip()

LI_ACCESS_TOKEN = os.getenv("LI_ACCESS_TOKEN", "").strip()
LI_API_VERSION_DEFAULT = os.getenv("LI_API_VERSION", "202601").strip()  # LinkedIn-Version header (YYYYMM)

# ----------------------------
# CORS helpers
# ----------------------------
def _cors_headers(req: func.HttpRequest) -> Dict[str, str]:
    origin = req.headers.get("origin") or req.headers.get("Origin") or ""
    if origin in ALLOWED_ORIGINS:
        return {
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
            "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,x-admin-key",
        }
    return {}


def _preflight(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(status_code=204, headers=_cors_headers(req))

cache_backend = get_cache_backend(CACHE_CONTAINER)

def _cache_key_linkedin_posts(org_urn: str, count: int, start: int, version: str) -> str:
    raw = f"{org_urn}|{count}|{start}|{version}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"linkedin/posts/{digest}.json"

def _cache_is_fresh(cached: Dict[str, Any]) -> bool:
    exp = cached.get("_expiresAtUtc")
    if not exp:
        return False
    try:
        exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        return utc_now() < exp_dt
    except Exception:
        return False


def _to_int(value: Optional[str], default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        n = int(value) if value is not None and str(value).strip() != "" else default
    except Exception:
        n = default
    if minimum is not None:
        n = max(minimum, n)
    if maximum is not None:
        n = min(maximum, n)
    return n



# ----------------------------
# Routes
# ----------------------------




@app.route(route="health", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    if req.method.upper() == "OPTIONS":
        return _preflight(req)
    return func.HttpResponse("ok", status_code=200, headers=_cors_headers(req))

@app.route(route="dev/session", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def dev_session(req: func.HttpRequest) -> func.HttpResponse:
    if req.method.upper() == "OPTIONS":
        return _preflight(req)

    enabled = (req.params.get("enabled") or "false").lower() == "true"
    payload = {
        "ok": True,
        "enabled": enabled,
        "session": "dev" if enabled else None,
        "utc": iso_utc(utc_now()),
    }
    return func.HttpResponse(
        json.dumps(payload),
        status_code=200,
        mimetype="application/json",
        headers=_cors_headers(req),
    )

# -------------------------------
# OPS ROUTES
# -------------------------------

@app.route(route="ops/routes", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_routes(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /api/ops/routes?key=SECRET
    Returns the list of available routes for diagnostics.
    """

    key = req.params.get("key") or req.headers.get("x-admin-key")
    if key != os.getenv("CACHE_FLUSH_KEY"):
        return func.HttpResponse(
            json.dumps({"error": "unauthorized"}),
            status_code=401,
            mimetype="application/json",
        )

    routes = [
        {
            "name": "health",
            "method": "GET",
            "route": "/api/health",
        },
        {
            "name": "linkedin_org_posts",
            "method": "GET",
            "route": "/api/linkedin/org/posts",
        },
        {
            "name": "ops_routes",
            "method": "GET",
            "route": "/api/ops/routes",
        },
        {
            "name": "ops_cache_flush",
            "method": "POST",
            "route": "/api/ops/cache/flush",
        },
    ]

    return func.HttpResponse(
        json.dumps(routes),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="ops/cache/flush", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_cache_flush(req: func.HttpRequest) -> func.HttpResponse:
    """
    POST /api/ops/cache/flush?key=SECRET
    Clears the API cache.
    """

    key = req.params.get("key") or req.headers.get("x-admin-key")
    if key != os.getenv("CACHE_FLUSH_KEY"):
        return func.HttpResponse(
            json.dumps({"error": "unauthorized"}),
            status_code=401,
            mimetype="application/json",
        )

    try:
        cache.clear()

        return func.HttpResponse(
            json.dumps({"status": "cache cleared"}),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )


@app.route(route="linkedin/org/posts", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def linkedin_org_posts(req: func.HttpRequest) -> func.HttpResponse:
    if req.method.upper() == "OPTIONS":
        return _preflight(req)

    # Lazy import to avoid cold-start failures if packaging breaks
    try:
        import requests  # type: ignore
    except Exception as e:
        payload = {
            "syncStatus": "DEGRADED",
            "total": 0,
            "items": [],
            "explanation": "Python dependency missing: requests",
            "error": str(e),
        }
        return func.HttpResponse(
            json.dumps(payload),
            status_code=200,
            mimetype="application/json",
            headers={**_cors_headers(req), "X-Cache": "BYPASS"},
        )

    # Accept orgUrn OR orgId
    org_urn = (req.params.get("orgUrn") or req.params.get("orgURN") or "").strip()
    org_id = (req.params.get("orgId") or "").strip()

    if not org_urn and org_id:
        org_urn = f"urn:li:organization:{org_id}"

    # paging inputs (client-side)
    count = _to_int(req.params.get("count"), 10, minimum=1, maximum=100)
    start = _to_int(req.params.get("start"), 0, minimum=0)
    ttl = _to_int(req.params.get("cacheTtlSeconds"), DEFAULT_TTL_SECONDS, minimum=30, maximum=86400)

    if not org_urn:
        return func.HttpResponse(
            json.dumps({"error": "Missing required query param: orgUrn (or orgId)"}),
            status_code=400,
            mimetype="application/json",
            headers=_cors_headers(req),
        )

    # LinkedIn-Version header:
    # - allow override per call: linkedinVersion=202601
    # - otherwise env LI_API_VERSION
    v = (req.params.get("linkedinVersion") or LI_API_VERSION_DEFAULT).strip()
    v_digits = "".join([c for c in v if c.isdigit()])
    version = v_digits[:6] if len(v_digits) >= 6 else LI_API_VERSION_DEFAULT

    now = utc_now()

    # IMPORTANT: cache key should *not* include count/start if you want to cache once per org/version,
    # but your current model slices on the client. We'll cache the full set returned from LinkedIn for this request,
    # keyed by org+count+start+version. Simple and safe.
    key = _cache_key_linkedin_posts(org_urn=org_urn, count=count, start=start, version=version)

    cached_entry = cache_backend.get(key)
    cached = cached_entry.payload if cached_entry else None
    if cached and _cache_is_fresh(cached):
        etag = compute_etag(cached)
        if_none_match = (req.headers.get("if-none-match") or req.headers.get("If-None-Match") or "").strip()
        if if_none_match and if_none_match == etag:
            return func.HttpResponse(status_code=304, headers={**_cors_headers(req), "ETag": etag, "X-Cache": "HIT"})

        cached_out = dict(cached)
        cached_out["cache"] = {
            "hit": True,
            "stale": False,
            "ttlSeconds": ttl,
            "cachedAtUtc": cached.get("_cachedAtUtc"),
            "expiresAtUtc": cached.get("_expiresAtUtc"),
        }
        return func.HttpResponse(
            json.dumps(cached_out),
            status_code=200,
            mimetype="application/json",
            headers={**_cors_headers(req), "X-Cache": "HIT", "ETag": etag},
        )

    if not LI_ACCESS_TOKEN:
        # Serve stale cache if present
        if cached and CACHE_ALLOW_STALE_ON_ERROR:
            cached_out = dict(cached)
            cached_out["syncStatus"] = "DEGRADED"
            cached_out["explanation"] = "No LinkedIn auth configured (set LI_ACCESS_TOKEN). Served stale cache."
            cached_out["cache"] = {"hit": True, "stale": True, "ttlSeconds": ttl}
            return func.HttpResponse(
                json.dumps(cached_out),
                status_code=200,
                mimetype="application/json",
                headers={**_cors_headers(req), "X-Cache": "STALE"},
            )

        payload = {
            "syncStatus": "DEGRADED",
            "total": 0,
            "items": [],
            "explanation": "No LinkedIn auth configured (set LI_ACCESS_TOKEN).",
            "source": "none",
        }
        return func.HttpResponse(
            json.dumps(payload),
            status_code=200,
            mimetype="application/json",
            headers={**_cors_headers(req), "X-Cache": "MISS"},
        )

    # Call LinkedIn
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LI_ACCESS_TOKEN}",
        "Accept": "application/json",
        "LinkedIn-Version": version,  # YYYYMM
        "X-Restli-Protocol-Version": "2.0.0",
    }
    params = {"q": "author", "author": org_urn, "count": count, "start": start}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)

        if r.status_code == 429:
            # LinkedIn throttle: serve stale if possible
            if cached and CACHE_ALLOW_STALE_ON_ERROR:
                cached_out = dict(cached)
                cached_out["syncStatus"] = "DEGRADED"
                cached_out["explanation"] = "LinkedIn throttled (429). Served stale cache."
                cached_out["throttle"] = {"status": 429, "code": "TOO_MANY_REQUESTS"}
                cached_out["cache"] = {"hit": True, "stale": True, "ttlSeconds": ttl}
                return func.HttpResponse(
                    json.dumps(cached_out),
                    status_code=200,
                    mimetype="application/json",
                    headers={**_cors_headers(req), "X-Cache": "STALE"},
                )

            payload = {
                "syncStatus": "DEGRADED",
                "total": 0,
                "items": [],
                "explanation": "LinkedIn throttled (429). No cache available.",
                "status": 429,
                "body": (r.text or "")[:2000],
                "cache": {"hit": False, "stale": False, "ttlSeconds": ttl},
            }
            return func.HttpResponse(
                json.dumps(payload),
                status_code=200,
                mimetype="application/json",
                headers={**_cors_headers(req), "X-Cache": "MISS"},
            )

        if r.status_code >= 400:
            # Any other LinkedIn error: serve stale if possible
            if cached and CACHE_ALLOW_STALE_ON_ERROR:
                cached_out = dict(cached)
                cached_out["syncStatus"] = "DEGRADED"
                cached_out["explanation"] = f"LinkedIn error ({r.status_code}). Served stale cache."
                cached_out["upstream"] = {"status": r.status_code, "body": (r.text or "")[:2000]}
                cached_out["cache"] = {"hit": True, "stale": True, "ttlSeconds": ttl}
                return func.HttpResponse(
                    json.dumps(cached_out),
                    status_code=200,
                    mimetype="application/json",
                    headers={**_cors_headers(req), "X-Cache": "STALE"},
                )

            payload = {
                "syncStatus": "DEGRADED",
                "total": 0,
                "items": [],
                "explanation": "LinkedIn API returned an error",
                "status": r.status_code,
                "body": (r.text or "")[:2000],
                "cache": {"hit": False, "stale": False, "ttlSeconds": ttl},
            }
            return func.HttpResponse(
                json.dumps(payload),
                status_code=200,
                mimetype="application/json",
                headers={**_cors_headers(req), "X-Cache": "MISS"},
            )

        data = r.json()
        items = data.get("elements") or data.get("items") or data.get("value") or []
        if not isinstance(items, list):
            items = []

        # TODO (media): when you’re ready, enrich each item here by extracting media/attachments fields
        # and return a normalized "media" object the web part can render.

        expires = now + timedelta(seconds=ttl)
        payload = {
            "syncStatus": "OK",
            "total": len(items),
            "items": items,
            "source": "linkedin",
            "_cachedAtUtc": iso_utc(now),
            "_expiresAtUtc": iso_utc(expires),
            "cache": {"hit": False, "stale": False, "ttlSeconds": ttl},
        }

        cache_backend.put(key, payload)

        etag = compute_etag(payload)

        return func.HttpResponse(
            json.dumps(payload),
            status_code=200,
            mimetype="application/json",
            headers={**_cors_headers(req), "X-Cache": "MISS", "ETag": etag},
        )

    except Exception as e:
        # Exception: serve stale if possible
        if cached and CACHE_ALLOW_STALE_ON_ERROR:
            cached_out = dict(cached)
            cached_out["syncStatus"] = "DEGRADED"
            cached_out["explanation"] = "Exception while calling LinkedIn. Served stale cache."
            cached_out["error"] = str(e)
            cached_out["cache"] = {"hit": True, "stale": True, "ttlSeconds": ttl}
            return func.HttpResponse(
                json.dumps(cached_out),
                status_code=200,
                mimetype="application/json",
                headers={**_cors_headers(req), "X-Cache": "STALE"},
            )

        payload = {
            "syncStatus": "DEGRADED",
            "total": 0,
            "items": [],
            "explanation": "Exception while calling LinkedIn",
            "error": str(e),
            "cache": {"hit": False, "stale": False, "ttlSeconds": ttl},
        }
        return func.HttpResponse(
            json.dumps(payload),
            status_code=200,
            mimetype="application/json",
            headers={**_cors_headers(req), "X-Cache": "MISS"},
        )
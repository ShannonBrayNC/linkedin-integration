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

DEFAULT_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(24 * 60 * 60)))
CACHE_CONTAINER = os.getenv("CACHE_CONTAINER", "cache")
CACHE_ALLOW_STALE_ON_ERROR = os.getenv("CACHE_ALLOW_STALE_ON_ERROR", "true").lower() == "true"
CACHE_FLUSH_KEY = os.getenv("CACHE_FLUSH_KEY", "").strip()

LI_ACCESS_TOKEN = os.getenv("LI_ACCESS_TOKEN", "").strip()
LI_API_VERSION_DEFAULT = os.getenv("LI_API_VERSION", "202601").strip()

cache_backend = get_cache_backend(CACHE_CONTAINER)


# ----------------------------
# Helpers
# ----------------------------

def _li_get_json(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    try:
        import requests  # type: ignore
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


def _extract_image_download_url(image_obj: Dict[str, Any]) -> Optional[str]:
    """
    Best-effort extraction for LinkedIn Images API responses.
    Prefer downloadUrl if present, otherwise fall back to other likely fields.
    """
    candidates = [
        image_obj.get("downloadUrl"),
        image_obj.get("url"),
        image_obj.get("mediaUrl"),
        image_obj.get("originalUrl"),
        image_obj.get("thumbnailUrl"),
        image_obj.get("previewUrl"),
    ]

    # Common nested patterns
    if isinstance(image_obj.get("data"), dict):
        data = image_obj["data"]
        candidates.extend([
            data.get("downloadUrl"),
            data.get("url"),
            data.get("mediaUrl"),
            data.get("thumbnailUrl"),
        ])

    if isinstance(image_obj.get("thumbnails"), list) and image_obj["thumbnails"]:
        first = image_obj["thumbnails"][0] or {}
        if isinstance(first, dict):
            candidates.extend([
                first.get("resolvedUrl"),
                first.get("url"),
            ])

    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()

    return None


def _extract_video_urls(video_obj: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Best-effort extraction for LinkedIn Videos API responses.
    """
    out: Dict[str, Optional[str]] = {
        "mediaUrl": None,
        "thumbnailUrl": None,
    }

    media_candidates = [
        video_obj.get("downloadUrl"),
        video_obj.get("url"),
        video_obj.get("mediaUrl"),
        video_obj.get("originalUrl"),
        video_obj.get("playableUrl"),
    ]

    thumb_candidates = [
        video_obj.get("thumbnailUrl"),
        video_obj.get("previewUrl"),
    ]

    if isinstance(video_obj.get("data"), dict):
        data = video_obj["data"]
        media_candidates.extend([
            data.get("downloadUrl"),
            data.get("url"),
            data.get("mediaUrl"),
            data.get("playableUrl"),
        ])
        thumb_candidates.extend([
            data.get("thumbnailUrl"),
            data.get("previewUrl"),
        ])

    for c in media_candidates:
        if isinstance(c, str) and c.strip():
            out["mediaUrl"] = c.strip()
            break

    for c in thumb_candidates:
        if isinstance(c, str) and c.strip():
            out["thumbnailUrl"] = c.strip()
            break

    return out


def _resolve_linkedin_image_urn(image_urn: str, headers: Dict[str, str], version: str) -> Optional[str]:
    """
    Resolve urn:li:image:... to a download/view URL using the Images API.
    """
    if not image_urn or not image_urn.startswith("urn:li:image:"):
        return None

    img = _li_get_json(
        f"https://api.linkedin.com/rest/images/{image_urn}",
        headers=headers
    )
    if not img:
        return None

    return _extract_image_download_url(img)


def _resolve_linkedin_video_urn(video_urn: str, headers: Dict[str, str], version: str) -> Dict[str, Optional[str]]:
    """
    Resolve urn:li:video:... to media/thumbnail URLs using the Videos API.
    """
    if not video_urn or not video_urn.startswith("urn:li:video:"):
        return {"mediaUrl": None, "thumbnailUrl": None}

    vid = _li_get_json(
        f"https://api.linkedin.com/rest/videos/{video_urn}",
        headers=headers
    )
    if not vid:
        return {"mediaUrl": None, "thumbnailUrl": None}

    return _extract_video_urls(vid)


def _enrich_post_media(post: Dict[str, Any], headers: Dict[str, str], version: str) -> Dict[str, Any]:
    """
    Best-effort media normalization for UI rendering.
    Adds browser-usable URLs where LinkedIn posts only provide URNs.
    """
    content = post.get("content")
    if not isinstance(content, dict):
        return post

    # 1) Article thumbnail image URN
    article = content.get("article")
    if isinstance(article, dict):
        thumb = article.get("thumbnail")
        if isinstance(thumb, str) and thumb.startswith("urn:li:image:"):
            resolved = _resolve_linkedin_image_urn(thumb, headers, version)
            if resolved:
                article["thumbnail"] = resolved
                content["thumbnail"] = resolved

    # 2) Media block
    media = content.get("media")
    if isinstance(media, dict):
        media_id = media.get("id")
        if isinstance(media_id, str):
            if media_id.startswith("urn:li:image:"):
                resolved = _resolve_linkedin_image_urn(media_id, headers, version)
                if resolved:
                    media["thumbnailUrl"] = resolved
                    media["url"] = resolved
                    content["thumbnail"] = content.get("thumbnail") or resolved
            elif media_id.startswith("urn:li:video:"):
                resolved_video = _resolve_linkedin_video_urn(media_id, headers, version)
                if resolved_video.get("thumbnailUrl"):
                    media["thumbnailUrl"] = resolved_video["thumbnailUrl"]
                    content["thumbnail"] = content.get("thumbnail") or resolved_video["thumbnailUrl"]
                if resolved_video.get("mediaUrl"):
                    media["mediaUrl"] = resolved_video["mediaUrl"]

    # 3) Multi-image gallery
    multi = content.get("multiImage")
    if isinstance(multi, dict) and isinstance(multi.get("images"), list):
        enriched_images = []
        for img in multi["images"]:
            if not isinstance(img, dict):
                enriched_images.append(img)
                continue

            img_id = img.get("id")
            if isinstance(img_id, str) and img_id.startswith("urn:li:image:"):
                resolved = _resolve_linkedin_image_urn(img_id, headers, version)
                if resolved:
                    img["url"] = resolved
                    img["thumbnailUrl"] = resolved
                    if not content.get("thumbnail"):
                        content["thumbnail"] = resolved

            enriched_images.append(img)

        multi["images"] = enriched_images

    post["content"] = content

    # Helpful normalized label for the UI
    if article and isinstance(article, dict) and article.get("title"):
        post["postType"] = "article"
    elif isinstance(content.get("multiImage"), dict):
        post["postType"] = "gallery"
    elif isinstance(content.get("media"), dict):
        media_id = content["media"].get("id")
        if isinstance(media_id, str) and media_id.startswith("urn:li:video:"):
            post["postType"] = "video"
        else:
            post["postType"] = "image"
    else:
        post["postType"] = "text"

    return post




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


def _to_int(
    value: Optional[str],
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    try:
        n = int(value) if value is not None and str(value).strip() != "" else default
    except Exception:
        n = default
    if minimum is not None:
        n = max(minimum, n)
    if maximum is not None:
        n = min(maximum, n)
    return n


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


def _get_ops_key(req: func.HttpRequest) -> str:
    return (req.params.get("key") or req.headers.get("x-admin-key") or "").strip()


def _is_authorized_ops_call(req: func.HttpRequest) -> bool:
    provided = _get_ops_key(req)
    return bool(CACHE_FLUSH_KEY) and provided == CACHE_FLUSH_KEY


# ----------------------------
# Routes
# ----------------------------
@app.route(route="health", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    if req.method.upper() == "OPTIONS":
        return _preflight(req)

    return func.HttpResponse(
        "ok",
        status_code=200,
        mimetype="text/plain",
        headers=_cors_headers(req),
    )


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


@app.route(route="ops/cache/flush", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def ops_cache_flush(req: func.HttpRequest) -> func.HttpResponse:
    """
    POST /api/ops/cache/flush?key=SECRET
    """
    if req.method.upper() == "OPTIONS":
        return _preflight(req)

    if not _is_authorized_ops_call(req):
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "unauthorized"}),
            status_code=401,
            mimetype="application/json",
            headers=_cors_headers(req),
        )

    prefix = (req.params.get("prefix") or "linkedin/posts/").strip()

    try:
        deleted = cache_backend.delete_prefix(prefix)
        return func.HttpResponse(
            json.dumps({"ok": True, "deleted": deleted, "prefix": prefix}),
            status_code=200,
            mimetype="application/json",
            headers=_cors_headers(req),
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": str(e)}),
            status_code=500,
            mimetype="application/json",
            headers=_cors_headers(req),
        )


@app.route(route="ops/routes", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def ops_routes(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /api/ops/routes?key=SECRET
    """
    if req.method.upper() == "OPTIONS":
        return _preflight(req)

    if not _is_authorized_ops_call(req):
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "unauthorized"}),
            status_code=401,
            mimetype="application/json",
            headers=_cors_headers(req),
        )

    routes = [
        {
            "name": "health",
            "methods": ["GET", "OPTIONS"],
            "route": "/api/health",
        },
        {
            "name": "dev_session",
            "methods": ["GET", "OPTIONS"],
            "route": "/api/dev/session",
        },
        {
            "name": "ops_cache_flush",
            "methods": ["POST", "OPTIONS"],
            "route": "/api/ops/cache/flush",
        },
        {
            "name": "ops_routes",
            "methods": ["GET", "OPTIONS"],
            "route": "/api/ops/routes",
        },
        {
            "name": "linkedin_org_posts",
            "methods": ["GET", "OPTIONS"],
            "route": "/api/linkedin/org/posts",
        },
    ]

    payload = {
        "ok": True,
        "count": len(routes),
        "routes": routes,
        "utc": iso_utc(utc_now()),
    }

    return func.HttpResponse(
        json.dumps(payload, indent=2),
        status_code=200,
        mimetype="application/json",
        headers=_cors_headers(req),
    )


@app.route(route="linkedin/org/posts", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def linkedin_org_posts(req: func.HttpRequest) -> func.HttpResponse:
    if req.method.upper() == "OPTIONS":
        return _preflight(req)

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

    org_urn = (req.params.get("orgUrn") or req.params.get("orgURN") or "").strip()
    org_id = (req.params.get("orgId") or "").strip()

    if not org_urn and org_id:
        org_urn = f"urn:li:organization:{org_id}"

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

    v = (req.params.get("linkedinVersion") or LI_API_VERSION_DEFAULT).strip()
    v_digits = "".join([c for c in v if c.isdigit()])
    version = v_digits[:6] if len(v_digits) >= 6 else LI_API_VERSION_DEFAULT

    now = utc_now()
    key = _cache_key_linkedin_posts(org_urn=org_urn, count=count, start=start, version=version)

    cached_entry = cache_backend.get(key)
    cached = cached_entry.payload if cached_entry else None

    if cached and _cache_is_fresh(cached):
        etag = compute_etag(cached)
        if_none_match = (req.headers.get("if-none-match") or req.headers.get("If-None-Match") or "").strip()
        if if_none_match and if_none_match == etag:
            return func.HttpResponse(
                status_code=304,
                headers={**_cors_headers(req), "ETag": etag, "X-Cache": "HIT"},
            )

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

    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LI_ACCESS_TOKEN}",
        "Accept": "application/json",
        "LinkedIn-Version": version,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    params = {"q": "author", "author": org_urn, "count": count, "start": start}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)

        if r.status_code == 429:
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
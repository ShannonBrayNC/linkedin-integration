from __future__ import annotations

import logging
from typing import Any

from .config import get
from .feed_cache import get_feed_cache, upsert_feed_cache
from .linkedin_rest import LinkedInToken, refresh_access_token, get_org_posts_rest, get_rest_posts_url
from .sharepoint_publish import publish_linkedin_posts_to_sharepoint
from .rss_fallback import fetch_rss, normalize_rss_items




def _rss_enabled() -> bool:
    return str(get('RSSAPP_FALLBACK_ENABLED', 'false')).lower() in ('1','true','yes','on')


def _rss_feed_url(config: dict[str, Any]) -> str:
    return (config or {}).get('rssFeedUrl') or get('RSSAPP_FEED_URL', '')
# In-memory token cache (per function worker)
_token: LinkedInToken | None = None


def _get_access_token() -> LinkedInToken:
    global _token
    if _token and not _token.is_expired:
        return _token

    # Preferred: refresh token (server-side)
    client_id = get("LINKEDIN_CLIENT_ID", "")
    client_secret = get("LINKEDIN_CLIENT_SECRET", "")
    refresh_token = get("LINKEDIN_REFRESH_TOKEN", "")

    try:
        if client_id and client_secret and refresh_token:
            _token = refresh_access_token(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
            )
            return _token
    except Exception:
        # Fall through to static token fallback
        pass

    # Fallback: allow a pre-minted access token for local/dev (avoids blocking on refresh issues)
    static_access_token = get("LI_ACCESS_TOKEN", get("LINKEDIN_ACCESS_TOKEN", ""))
    if not static_access_token:
        raise RuntimeError("No valid LinkedIn auth configured (refresh token failed and no LI_ACCESS_TOKEN set).")

    # LinkedIn access tokens often live ~2 months in your setup; treat as short-lived here.
    # Cache for the worker lifetime; the caller can restart if it expires.
    _token = LinkedInToken(access_token=static_access_token, expires_at_unix=10**12, scope=None)
    return _token


def _normalize_posts(raw: dict[str, Any]) -> list[dict[str, Any]]:
    els = raw.get("elements")
    if not els:
        return []
    if isinstance(els, dict):
        # PowerShell sometimes prints {} for empty object; treat dict as empty unless it's list-like
        return []
    if not isinstance(els, list):
        return []

    items: list[dict[str, Any]] = []
    for p in els:
        if not isinstance(p, dict):
            continue
        # Keep this intentionally minimal: we don't assume any particular schema.
        items.append({
            "urn": p.get("id") or p.get("urn") or p.get("post"),
            "author": p.get("author"),
            "createdAt": p.get("createdAt") or p.get("created"),
            "lastModifiedAt": p.get("lastModifiedAt") or p.get("lastModified"),
            "text": (p.get("commentary") or p.get("text") or "") if isinstance(p.get("commentary") or p.get("text") or "", (str,)) else "",
            "raw": p,
        })
    return items


def _paging_next_href(raw: dict[str, Any]) -> str | None:
    """Return the 'next' page href from LinkedIn paging.links, if present."""
    paging = raw.get("paging") or {}
    links = paging.get("links") or []
    if not isinstance(links, list):
        return None
    for l in links:
        if not isinstance(l, dict):
            continue
        if (l.get("rel") or "").lower() == "next" and l.get("href"):
            return str(l.get("href"))
    return None


def fetch_linkedin_payload(tenant_id: str, user_oid: str, config: dict[str, Any]) -> dict[str, Any]:
    """REST-only LinkedIn fetch with clean fallbacks.

    Expected config fields:
      - orgUrn: 'urn:li:organization:5515715' (required)
      - count: int (optional)
    """

    org_urn = req.params.get("orgUrn") or req.params.get("orgURN") or ""
    org_id = (req.params.get("orgId") or req.params.get("orgID") or "").strip()

    if (not org_urn) and org_id.isdigit():
        org_urn = f"urn:li:organization:{org_id}"
    if not org_urn:
        return {
            "syncStatus": "SUCCESS_EMPTY",
            "total": 0,
            "items": [],
            "explanation": "No organization configured (missing orgUrn).",
        }

    # LinkedIn paging: count + start. We also support maxItems (accumulate across pages).
    count = int((config or {}).get("count", 10))
    start = int((config or {}).get("start", 0) or 0)
    max_items = int((config or {}).get("maxItems", 0) or 0)
    if max_items <= 0:
        max_items = count
    linkedin_version = (config or {}).get("linkedinVersion") or get("LINKEDIN_API_VERSION", "202502")

    cache_id = f"linkedin_rest_posts__{org_urn}"
    cached = get_feed_cache(tenant_id, cache_id)

    try:
        tok = _get_access_token()
        raw = get_org_posts_rest(
            access_token=tok.access_token,
            org_urn=org_urn,
            count=count,
            start=start,
            linkedin_version=linkedin_version,
        )

        total = int((raw.get("paging") or {}).get("total", 0) or 0)
        items = _normalize_posts(raw)

        # If the caller asked for more than one page, follow paging.links rel=next.
        # We intentionally cap by max_items so we don't pull the entire org history every sync.
        if max_items > len(items):
            next_url = _paging_next_href(raw)
            while next_url and len(items) < max_items:
                page = get_rest_posts_url(
                    access_token=tok.access_token,
                    url=next_url,
                    linkedin_version=linkedin_version,
                )
                items.extend(_normalize_posts(page))
                next_url = _paging_next_href(page)

            # If we accumulated across pages, set total to LinkedIn's total if present; otherwise len(items)
            if total <= 0:
                total = len(items)

        # Optional RSS fallback (feature flagged). This is intentionally REST-only and avoids LinkedIn API entitlements.
        rss_used = False
        if total <= 0 and _rss_enabled():
            rss_items = fetch_rss(_rss_feed_url(config))
            if rss_items:
                items = normalize_rss_items(rss_items, author_urn=org_urn)
                total = len(items)
                rss_used = True

        payload = {
            "syncStatus": "SUCCESS" if total > 0 else "SUCCESS_EMPTY",
            "total": total,
            "items": items,
            "paging": {
                "start": int((raw.get("paging") or {}).get("start", start) or start),
                "count": int((raw.get("paging") or {}).get("count", count) or count),
                "next": _paging_next_href(raw),
            },
            "explanation": "Posts retrieved." if total > 0 and not rss_used else ("Posts retrieved via RSS fallback." if total > 0 and rss_used else "No organization posts found."),
            "source": "rss.app" if rss_used else "linkedin/rest/posts",
            "sharepoint": {"enabled": False, "written": 0, "updated": 0},
        }

        # Optional SharePoint publish (feature flagged)
        try:
            sp = publish_linkedin_posts_to_sharepoint(items=items)
            payload["sharepoint"] = sp
        except Exception as sp_e:
            payload["sharepoint"] = {"enabled": True, "error": str(sp_e), "written": 0, "updated": 0}

        # Cache last good result (including empty, so we know last-checked time)
        upsert_feed_cache(tenant_id, cache_id, payload)
        return payload

    except Exception as e:
        logging.warning("LinkedIn fetch degraded (%s): %s", type(e).__name__, str(e))

        if cached and cached.get("items") is not None:
            return {
                "syncStatus": "DEGRADED",
                "total": cached.get("total", 0),
                "items": cached.get("items", []),
                "explanation": "LinkedIn API unavailable; using cached results.",
                "source": "cache",
                "error": str(e),
            }


        # Optional RSS fallback (feature flagged) when LinkedIn is unavailable and no cache exists.
        if _rss_enabled():
            rss_items = fetch_rss(_rss_feed_url(config))
            if rss_items:
                items = normalize_rss_items(rss_items, author_urn=org_urn)
                payload = {
                    "syncStatus": "SUCCESS" if len(items) > 0 else "SUCCESS_EMPTY",
                    "total": len(items),
                    "items": items,
                    "explanation": "LinkedIn API unavailable; served via RSS fallback.",
                    "source": "rss.app",
                    "sharepoint": {"enabled": False, "written": 0, "updated": 0},
                }

                # Optional SharePoint publish (feature flagged)
                try:
                    sp = publish_linkedin_posts_to_sharepoint(items=items)
                    payload["sharepoint"] = sp
                except Exception as sp_e:
                    payload["sharepoint"] = {"enabled": True, "error": str(sp_e), "written": 0, "updated": 0}

                upsert_feed_cache(tenant_id, cache_id, payload)
                return payload
        return {
            "syncStatus": "DEGRADED",
            "total": 0,
            "items": [],
            "explanation": "LinkedIn API unavailable; no cached results yet.",
            "source": "none",
            "error": str(e),
        }

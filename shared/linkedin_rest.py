import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class LinkedInToken:
    access_token: str
    expires_at_unix: float
    scope: str | None = None

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at_unix - 60)


import json
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def _http_json(
    url: str,
    method: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    req = Request(url=url, method=method, data=body)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if body is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}

    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return int(e.code), json.loads(raw) if raw else {}
        except Exception:
            return int(e.code), {"error": "http_error", "raw": raw}

    except URLError as e:
        raise RuntimeError(f"Network error calling {url}: {e}") from e



def _build_posts_finder_url(*, org_urn: str, count: int, start: int) -> str:
    query = urlencode(
        {
            "q": "author",
            "author": org_urn,
            "count": str(max(1, int(count))),
            "start": str(max(0, int(start))),
            "sortBy": "LAST_MODIFIED",
        }
    )
    return f"https://api.linkedin.com/rest/posts?{query}"


def get_rest_posts_url(
    *,
    access_token: str,
    url: str,
    linkedin_version: str = "202601",
    max_retries: int = 4,
) -> dict[str, Any]:
    if url.startswith("/"):
        url = "https://api.linkedin.com" + url

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": linkedin_version,
        "X-RestLi-Method": "FINDER",
        "Accept": "application/json",
    }

    backoff = 0.5
    last_payload: dict[str, Any] | None = None

    for attempt in range(1, max_retries + 1):
        status, payload = _http_json(url, "GET", headers=headers)
        last_payload = payload

        if 200 <= status < 300:
            return payload

        if status == 429 or (500 <= status < 600):
            logging.warning("LinkedIn REST posts retry %s/%s (status=%s)", attempt, max_retries, status)
            time.sleep(backoff)
            backoff = min(backoff * 2, 8.0)
            continue

        raise RuntimeError(f"LinkedIn REST posts failed ({status}): {payload}")

    raise RuntimeError(f"LinkedIn REST posts failed after retries: {last_payload}")


def get_org_posts_rest(
    *,
    access_token: str,
    org_urn: str,
    count: int = 10,
    start: int = 0,
    linkedin_version: str = "202601",
    max_retries: int = 4,
) -> dict[str, Any]:
    return get_rest_posts_url(
        access_token=access_token,
        url=_build_posts_finder_url(org_urn=org_urn, count=count, start=start),
        linkedin_version=linkedin_version,
        max_retries=max_retries,
    )

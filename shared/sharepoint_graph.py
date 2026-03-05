import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class GraphToken:
    access_token: str
    expires_at_unix: float

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at_unix - 60)


def _http_json(url: str, method: str, headers: dict[str, str] | None = None,
              body: bytes | None = None, timeout: int = 30) -> tuple[int, dict[str, Any]]:
    req = Request(url=url, method=method, data=body)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if body is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except Exception as e:
        if hasattr(e, "code") and hasattr(e, "read"):
            raw = e.read().decode("utf-8", errors="replace")
            try:
                return int(e.code), json.loads(raw) if raw else {}
            except Exception:
                return int(e.code), {"error": "http_error", "raw": raw}
        raise


def get_app_only_token(tenant_id: str, client_id: str, client_secret: str) -> GraphToken:
    """Client credentials flow for Microsoft Graph (app-only)."""
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    form = urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }).encode("utf-8")

    status, payload = _http_json(token_url, "POST", body=form)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Graph token request failed ({status}): {payload}")

    at = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 0) or 0)
    if not at or expires_in <= 0:
        raise RuntimeError(f"Graph token response unexpected: {payload}")

    return GraphToken(access_token=at, expires_at_unix=time.time() + expires_in)


def find_list_item_id_by_field(*, token: str, site_id: str, list_id: str, field_name: str, field_value: str) -> str | None:
    """Best-effort lookup for an existing item using a field equality filter.

    NOTE: Graph list-item filtering can be finicky depending on list schema.
    We try a couple of safe query shapes and return None if unsupported.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # Attempt 1: filter on fields/<name> (works for many custom fields)
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items"
        f"?$expand=fields($select=id,{field_name})"
        f"&$filter=fields/{field_name} eq '{field_value.replace("'", "''")}'"
        f"&$top=1"
    )
    status, payload = _http_json(url, "GET", headers=headers)
    if 200 <= status < 300:
        vals = payload.get("value") or []
        if vals:
            return vals[0].get("id")

    return None


def create_list_item(*, token: str, site_id: str, list_id: str, fields: dict[str, Any]) -> str:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items"
    body = json.dumps({"fields": fields}).encode("utf-8")
    status, payload = _http_json(url, "POST", headers=headers, body=body)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Graph create item failed ({status}): {payload}")
    item_id = payload.get("id")
    if not item_id:
        raise RuntimeError(f"Graph create item unexpected response: {payload}")
    return item_id


def update_list_item_fields(*, token: str, site_id: str, list_id: str, item_id: str, fields: dict[str, Any]) -> None:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items/{item_id}/fields"
    body = json.dumps(fields).encode("utf-8")
    status, payload = _http_json(url, "PATCH", headers=headers, body=body)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Graph update item failed ({status}): {payload}")

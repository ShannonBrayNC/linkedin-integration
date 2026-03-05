import logging
from typing import Any

from .config import (
    SHAREPOINT_ENABLED,
    SHAREPOINT_PROVIDER,
    SP_TENANT_ID,
    SP_CLIENT_ID,
    SP_CLIENT_SECRET,
    SP_SITE_ID,
    SP_LIST_ID,
)
from .sharepoint_graph import get_app_only_token, find_list_item_id_by_field, create_list_item, update_list_item_fields


# Simple in-worker Graph token cache
_graph_token = None


def _require(v: str | None, name: str) -> str:
    if not v:
        raise ValueError(f"Missing SharePoint config env var: {name}")
    return v


def publish_linkedin_posts_to_sharepoint(*, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Upsert LinkedIn posts into a SharePoint list.

    Feature-flagged behind SHAREPOINT_ENABLED.

    Expected list fields (you can rename later, but keep these for ship):
      - Title (text)
      - PostUrn (text, unique key)
      - Author (text)
      - LastModifiedAt (text)
      - CreatedAt (text)
      - Text (multiline)
      - RawJson (multiline)
    """

    if not SHAREPOINT_ENABLED:
        return {"enabled": False, "written": 0, "updated": 0}

    if SHAREPOINT_PROVIDER != "graph":
        raise RuntimeError(f"Unsupported SHAREPOINT_PROVIDER='{SHAREPOINT_PROVIDER}'. Only 'graph' is implemented.")

    tenant_id = _require(SP_TENANT_ID, "SP_TENANT_ID")
    client_id = _require(SP_CLIENT_ID, "SP_CLIENT_ID")
    client_secret = _require(SP_CLIENT_SECRET, "SP_CLIENT_SECRET")
    site_id = _require(SP_SITE_ID, "SP_SITE_ID")
    list_id = _require(SP_LIST_ID, "SP_LIST_ID")

    global _graph_token
    if not _graph_token or getattr(_graph_token, "is_expired", True):
        _graph_token = get_app_only_token(tenant_id, client_id, client_secret)

    token = _graph_token.access_token

    written = 0
    updated = 0

    for it in (items or []):
        post_urn = it.get("urn")
        if not post_urn:
            continue

        # Map to list fields
        fields = {
            "Title": (post_urn[:250] if isinstance(post_urn, str) else "LinkedIn Post"),
            "PostUrn": post_urn,
            "Author": it.get("author"),
            "LastModifiedAt": it.get("lastModifiedAt"),
            "CreatedAt": it.get("createdAt"),
            "Text": it.get("text"),
            "RawJson": json_dump_safe(it.get("raw")),
        }

        try:
            existing_id = find_list_item_id_by_field(
                token=token,
                site_id=site_id,
                list_id=list_id,
                field_name="PostUrn",
                field_value=str(post_urn),
            )

            if existing_id:
                update_list_item_fields(token=token, site_id=site_id, list_id=list_id, item_id=existing_id, fields=fields)
                updated += 1
            else:
                create_list_item(token=token, site_id=site_id, list_id=list_id, fields=fields)
                written += 1

        except Exception as e:
            # Do not fail the whole sync; just report partial.
            logging.warning("SharePoint upsert failed for %s: %s", post_urn, str(e))

    return {"enabled": True, "written": written, "updated": updated}


def json_dump_safe(obj: Any) -> str:
    try:
        import json
        return json.dumps(obj, ensure_ascii=False)[:60000]
    except Exception:
        return "{}"

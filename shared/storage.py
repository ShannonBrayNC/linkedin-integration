from .config import STORAGE_MODE
from datetime import datetime, timezone
from pathlib import Path
import json

_memory_cards = {}


def _cards_dir() -> Path:
    # shared/storage.py -> shared/ (0) -> api/ (1)
    api_dir = Path(__file__).resolve().parents[1]
    d = api_dir / "cards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_key(tenant_id: str, card_id: str) -> str:
    safe_tenant = "".join(ch for ch in tenant_id if ch.isalnum() or ch in ("-", "_"))
    safe_card = "".join(ch for ch in card_id if ch.isalnum() or ch in ("-", "_"))
    return f"{safe_tenant}__{safe_card}.json"

def _now():
    return datetime.now(timezone.utc).isoformat()

def get_card(tenant_id: str, card_id: str) -> dict | None:
    if STORAGE_MODE == "memory":
        return _memory_cards.get((tenant_id, card_id))
    if STORAGE_MODE == "file":
        p = _cards_dir() / _file_key(tenant_id, card_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    raise NotImplementedError("Implement cosmos/table storage")

def upsert_card(tenant_id: str, card_id: str, card: dict) -> None:
    if STORAGE_MODE == "memory":
        card["id"] = card_id
        card["tenantId"] = tenant_id
        card["updatedAt"] = _now()
        _memory_cards[(tenant_id, card_id)] = card
        return
    if STORAGE_MODE == "file":
        card["id"] = card_id
        card["tenantId"] = tenant_id
        card["updatedAt"] = _now()
        p = _cards_dir() / _file_key(tenant_id, card_id)
        p.write_text(json.dumps(card, indent=2), encoding="utf-8")
        return
    raise NotImplementedError("Implement cosmos/table storage")

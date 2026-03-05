from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from .config import STORAGE_MODE


_memory_cache: dict[tuple[str, str], dict] = {}


def _cache_dir() -> Path:
    api_dir = Path(__file__).resolve().parents[1]
    d = api_dir / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum() or ch in ("-", "_", "."))


def _key(tenant_id: str, cache_id: str) -> tuple[str, str]:
    return tenant_id, cache_id


def _file_name(tenant_id: str, cache_id: str) -> str:
    return f"{_safe(tenant_id)}__{_safe(cache_id)}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_feed_cache(tenant_id: str, cache_id: str) -> dict | None:
    if STORAGE_MODE == "memory":
        return _memory_cache.get(_key(tenant_id, cache_id))
    if STORAGE_MODE == "file":
        p = _cache_dir() / _file_name(tenant_id, cache_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    raise NotImplementedError("Implement table/cosmos cache")


def upsert_feed_cache(tenant_id: str, cache_id: str, payload: dict) -> None:
    payload = dict(payload)
    payload["tenantId"] = tenant_id
    payload["cacheId"] = cache_id
    payload["updatedAt"] = _now_iso()

    if STORAGE_MODE == "memory":
        _memory_cache[_key(tenant_id, cache_id)] = payload
        return
    if STORAGE_MODE == "file":
        p = _cache_dir() / _file_name(tenant_id, cache_id)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return
    raise NotImplementedError("Implement table/cosmos cache")
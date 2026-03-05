from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso_utc(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def compute_etag(payload: Dict[str, Any]) -> str:
    """Stable ETag for a cached response (ignores transient cache fields)."""
    filtered = dict(payload)
    filtered.pop("cache", None)
    filtered.pop("_cachedAtUtc", None)
    filtered.pop("_expiresAtUtc", None)
    raw = json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return '"' + hashlib.sha256(raw).hexdigest() + '"'


@dataclass(frozen=True)
class CacheEntry:
    payload: Dict[str, Any]

    @property
    def cached_at(self) -> Optional[datetime]:
        v = self.payload.get("_cachedAtUtc")
        return parse_iso_utc(v) if isinstance(v, str) else None

    @property
    def expires_at(self) -> Optional[datetime]:
        v = self.payload.get("_expiresAtUtc")
        return parse_iso_utc(v) if isinstance(v, str) else None

    @property
    def is_fresh(self) -> bool:
        exp = self.expires_at
        return bool(exp and utc_now() < exp)


class CacheBackend:
    def get(self, key: str) -> Optional[CacheEntry]:
        raise NotImplementedError

    def put(self, key: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> int:
        raise NotImplementedError


class MemoryCacheBackend(CacheBackend):
    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[CacheEntry]:
        v = self._store.get(key)
        return CacheEntry(v) if isinstance(v, dict) else None

    def put(self, key: str, payload: Dict[str, Any]) -> None:
        self._store[key] = dict(payload)

    def delete_prefix(self, prefix: str) -> int:
        keys = [k for k in list(self._store.keys()) if k.startswith(prefix)]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)


class FileCacheBackend(CacheBackend):
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = self.base_dir / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def get(self, key: str) -> Optional[CacheEntry]:
        try:
            p = self._path(key)
            if not p.exists():
                return None
            return CacheEntry(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return None

    def put(self, key: str, payload: Dict[str, Any]) -> None:
        try:
            p = self._path(key)
            p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        root = (self.base_dir / prefix)
        if not root.exists():
            return 0
        if root.is_file():
            try:
                root.unlink()
                return 1
            except Exception:
                return 0
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    p.unlink()
                    deleted += 1
                except Exception:
                    pass
        return deleted


class BlobCacheBackend(CacheBackend):
    def __init__(self, container_name: str):
        conn = (os.getenv("AzureWebJobsStorage") or "").strip()
        if not conn:
            raise RuntimeError("AzureWebJobsStorage missing")

        from azure.storage.blob import BlobServiceClient  # type: ignore

        self._svc = BlobServiceClient.from_connection_string(conn)
        self._container = self._svc.get_container_client(container_name)
        try:
            self._container.create_container()
        except Exception:
            pass

    def get(self, key: str) -> Optional[CacheEntry]:
        try:
            blob = self._container.get_blob_client(key)
            data = blob.download_blob().readall()
            return CacheEntry(json.loads(data.decode("utf-8")))
        except Exception:
            return None

    def put(self, key: str, payload: Dict[str, Any]) -> None:
        try:
            blob = self._container.get_blob_client(key)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            blob.upload_blob(body, overwrite=True, content_type="application/json")
        except Exception:
            pass

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        try:
            for b in self._container.list_blobs(name_starts_with=prefix):
                try:
                    self._container.delete_blob(b.name)
                    deleted += 1
                except Exception:
                    pass
        except Exception:
            pass
        return deleted


def get_cache_backend(container_name: str = "cache") -> CacheBackend:
    """Selects a backend in this order:

    1) Azure Blob (AzureWebJobsStorage + azure-storage-blob installed)
    2) File cache under api/cache (good for local dev)
    3) In-memory (last resort)
    """
    try:
        return BlobCacheBackend(container_name)
    except Exception:
        pass

    try:
        api_dir = Path(__file__).resolve().parents[1]
        return FileCacheBackend(api_dir / "cache")
    except Exception:
        pass

    return MemoryCacheBackend()

"""Content-addressed cache for per-file extraction artefacts.

Key (``page_context_contract.md`` section 4)::

    (source_sha256, engine_name, engine_version, configuration_hash,
     routing_version, extractor_version, artifact_type)

A version mismatch is a **miss**, never a silent reuse. Writes are atomic. The
cache is disabled by default: a reference run should read the sources, and an
opt-in cache exists for iterating on a sample without re-parsing.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .version import EXTRACTOR_VERSION, ROUTING_VERSION


@dataclass(frozen=True)
class CacheKey:
    source_sha256: str
    engine_name: str
    engine_version: str
    configuration_hash: str
    artifact_type: str
    routing_version: str = ROUTING_VERSION
    extractor_version: str = EXTRACTOR_VERSION

    def digest(self) -> str:
        blob = "|".join((
            self.source_sha256, self.engine_name, self.engine_version,
            self.configuration_hash, self.routing_version,
            self.extractor_version, self.artifact_type,
        ))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ArtifactCache:
    """Disk cache. ``enabled=False`` makes every operation a no-op miss."""

    def __init__(self, root: Optional[Path], *, enabled: bool = False):
        self.root = Path(root) if root else None
        self.enabled = bool(enabled and self.root)
        self.hits = 0
        self.misses = 0
        if self.enabled and self.root:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: CacheKey) -> Path:
        d = key.digest()
        assert self.root is not None
        return self.root / d[:2] / f"{d}.json"

    def get(self, key: CacheKey) -> Optional[Any]:
        if not self.enabled:
            self.misses += 1
            return None
        p = self._path(key)
        if not p.exists():
            self.misses += 1
            return None
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A partial or corrupt entry is a miss, never a silent reuse.
            self.misses += 1
            return None
        if payload.get("key_digest") != key.digest():
            self.misses += 1
            return None
        self.hits += 1
        return payload.get("value")

    def put(self, key: CacheKey, value: Any) -> None:
        if not self.enabled:
            return
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"key_digest": key.digest(),
                        "key": key.__dict__,
                        "value": value},
                       ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, p)

    def stats(self) -> dict[str, int]:
        return {"cache_hits": self.hits, "cache_misses": self.misses}

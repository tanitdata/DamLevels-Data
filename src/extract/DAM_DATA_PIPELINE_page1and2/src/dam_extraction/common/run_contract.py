from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class RunStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    COMPLETE_VALIDATED = "COMPLETE_VALIDATED"


@dataclass(frozen=True)
class ArtifactIdentity:
    path: str
    bytes: int
    sha256: str
    role: str
    row_count: int | None = None
    schema: str | None = None


@dataclass(frozen=True)
class OperatorConfig:
    project_root: str
    page1_input_root: str
    page2_input_root: str
    output_root: str
    page1_workers: int = 8
    page2_workers: int = 12
    run_page1: bool = True
    run_page2: bool = True
    run_mode: str = "FULL"
    resume: bool = True
    force_rerun: bool = False
    write_sqlite: bool = True
    write_csv: bool = True
    run_id: str = ""

    def page_payload(self, page: str) -> dict[str, Any]:
        if page not in {"page1", "page2"}:
            raise ValueError(f"unsupported page: {page}")
        return {
            "page": page,
            "run_mode": self.run_mode.upper(),
            "workers": self.page1_workers if page == "page1" else self.page2_workers,
            "write_sqlite": self.write_sqlite,
            "write_csv": self.write_csv,
        }


@dataclass(frozen=True)
class ExtractionRunResult:
    page: str
    run_id: str
    run_mode: str
    source_root: str
    source_count: int
    engine_identity: str
    config_identity: str
    workers: int
    output_root: str
    observations_path: str
    lineage_path: str
    database_path: str
    source_manifest_path: str
    validation_path: str
    failures_path: str
    unresolved_path: str
    artifact_manifest_path: str
    scientific_identity: str
    status: str
    source_identity: str
    elapsed_seconds: float
    counts: dict[str, int] = field(default_factory=dict)
    additional: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[ArtifactIdentity, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json_bytes(value: Any, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + suffix).encode("utf-8")


def canonical_identity(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_tree(root: str | Path, *, include: Iterable[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    base = Path(root).resolve()
    suffixes = set(include) if include is not None else None
    rows: list[dict[str, Any]] = []
    for path in sorted((p for p in base.rglob("*") if p.is_file()), key=lambda p: p.relative_to(base).as_posix().casefold()):
        if suffixes is not None and path.suffix.casefold() not in suffixes:
            continue
        relative = path.relative_to(base).as_posix()
        rows.append({"relative_path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return canonical_identity(rows), rows

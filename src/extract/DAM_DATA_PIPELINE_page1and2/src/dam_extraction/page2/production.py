from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import sqlite3
import threading
import time
import traceback
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from . import ENGINE_VERSION, SCIENTIFIC_ANCESTOR
from .engine import (
    FAILURE_FIELDS,
    LINEAGE_FIELDS,
    OBSERVATION_FIELDS,
    ROW_AUDIT_FIELDS,
    extract_page2_pdf,
)
from .roster import REGISTRY_PATH, REGISTRY_VERSION
from .schema import bulletin_date_from_filename

SOURCE_FIELDS = [
    "source_index", "source_pdf", "source_path", "source_sha256", "source_bytes",
    "bulletin_date", "processing_status",
]
UNRESOLVED_FIELDS = [
    "source_index", "source_pdf", "source_sha256", "bulletin_date", "dam_id",
    "physical_column", "canonical_semantic", "raw_cell_text", "parsed_numeric_value",
    "parse_status", "disposition",
]
VALIDATION_FIELDS = [
    "source_index", "source_pdf", "source_sha256", "bulletin_date",
    "validation_name", "status", "details_json",
]

SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE run_manifest (
  run_id TEXT PRIMARY KEY,
  engine_version TEXT NOT NULL,
  scientific_ancestor TEXT NOT NULL,
  roster_version TEXT NOT NULL,
  roster_sha256 TEXT NOT NULL,
  development_or_production TEXT NOT NULL CHECK(development_or_production='PRODUCTION'),
  run_mode TEXT NOT NULL CHECK(run_mode IN ('FULL','TARGETED')),
  clean_room_classification TEXT NOT NULL CHECK(clean_room_classification='CLEAN_ROOM'),
  worker_count INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  elapsed_seconds REAL,
  source_count INTEGER NOT NULL,
  processed_source_count INTEGER NOT NULL DEFAULT 0,
  observation_count INTEGER NOT NULL DEFAULT 0,
  lineage_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  unresolved_count INTEGER NOT NULL DEFAULT 0,
  recovered_row_count INTEGER NOT NULL DEFAULT 0,
  ambiguous_row_count INTEGER NOT NULL DEFAULT 0,
  source_corpus_hash TEXT,
  scientific_identity_hash TEXT
);
CREATE TABLE source_manifest (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  source_pdf TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  source_bytes INTEGER NOT NULL,
  bulletin_date TEXT NOT NULL,
  processing_status TEXT NOT NULL,
  PRIMARY KEY(run_id, source_index),
  UNIQUE(run_id, source_pdf),
  FOREIGN KEY(run_id) REFERENCES run_manifest(run_id)
);
CREATE TABLE page2_observation (
  run_id TEXT NOT NULL,
  observation_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  source_sha256 TEXT NOT NULL,
  bulletin_date TEXT NOT NULL,
  dam_id TEXT NOT NULL,
  region TEXT NOT NULL,
  raw_dam_label_token TEXT NOT NULL,
  row_bbox TEXT NOT NULL,
  schema_class TEXT NOT NULL,
  row_detection_method TEXT NOT NULL,
  row_detection_confidence REAL NOT NULL,
  source_validation_status TEXT NOT NULL,
  values_json TEXT NOT NULL,
  PRIMARY KEY(run_id, observation_id),
  UNIQUE(run_id, dam_id, bulletin_date),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE TABLE page2_value_lineage (
  run_id TEXT NOT NULL,
  lineage_id TEXT NOT NULL,
  observation_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  physical_column INTEGER NOT NULL CHECK(physical_column BETWEEN 0 AND 25),
  canonical_semantic TEXT NOT NULL,
  raw_cell_text TEXT NOT NULL,
  parsed_numeric_value REAL,
  parse_status TEXT NOT NULL,
  column_bbox TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  PRIMARY KEY(run_id, lineage_id),
  UNIQUE(run_id, observation_id, physical_column),
  FOREIGN KEY(run_id, observation_id) REFERENCES page2_observation(run_id, observation_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE INDEX page2_value_semantic_idx ON page2_value_lineage(run_id, canonical_semantic);
CREATE TABLE page2_validation_result (
  run_id TEXT NOT NULL,
  validation_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  validation_name TEXT NOT NULL,
  status TEXT NOT NULL,
  details_json TEXT NOT NULL,
  PRIMARY KEY(run_id, validation_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE TABLE page2_extraction_failure (
  run_id TEXT NOT NULL,
  failure_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  failure_class TEXT NOT NULL,
  message TEXT NOT NULL,
  failure_json TEXT NOT NULL,
  PRIMARY KEY(run_id, failure_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE TABLE page2_unresolved_cell (
  run_id TEXT NOT NULL,
  unresolved_id TEXT NOT NULL,
  lineage_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  disposition TEXT NOT NULL,
  unresolved_json TEXT NOT NULL,
  PRIMARY KEY(run_id, unresolved_id),
  FOREIGN KEY(run_id, lineage_id) REFERENCES page2_value_lineage(run_id, lineage_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()}"


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@contextmanager
def _csv_writer(path: Path, fieldnames: list[str], *, compressed: bool = False) -> Iterator[csv.DictWriter]:
    if compressed:
        raw = path.open("wb")
        gzip_stream = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6)
        text = io.TextIOWrapper(gzip_stream, encoding="utf-8", newline="")
        try:
            writer = csv.DictWriter(text, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            yield writer
        finally:
            text.close()
            raw.close()
    else:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            yield writer


def deterministic_inventory(pdf_paths: Iterable[str | Path]) -> list[Path]:
    unique = {str(Path(path).resolve()).casefold(): Path(path).resolve() for path in pdf_paths}
    return sorted(unique.values(), key=lambda path: (bulletin_date_from_filename(path), path.name.casefold()))


def representative_sample(paths: Iterable[str | Path], count: int, mandatory_names: Iterable[str] = ()) -> list[Path]:
    inventory = deterministic_inventory(paths)
    if count <= 0 or count >= len(inventory):
        return inventory
    mandatory = {name.casefold() for name in mandatory_names}
    selected = {path.name.casefold(): path for path in inventory if path.name.casefold() in mandatory}
    remaining = max(0, count - len(selected))
    if remaining == 1:
        selected[inventory[len(inventory) // 2].name.casefold()] = inventory[len(inventory) // 2]
    elif remaining > 1:
        indexes = sorted({round(index * (len(inventory) - 1) / (remaining - 1)) for index in range(remaining)})
        for index in indexes:
            selected[inventory[index].name.casefold()] = inventory[index]
    return deterministic_inventory(selected.values())


def _worker(task: tuple[str, list[str] | None, list[str] | None]) -> dict:
    path, dams, fields = task
    try:
        return extract_page2_pdf(
            path,
            target_dams=None if dams is None else set(dams),
            target_fields=None if fields is None else set(fields),
        )
    except Exception as exc:
        source = Path(path)
        try:
            bulletin = bulletin_date_from_filename(source).isoformat()
        except Exception:
            bulletin = ""
        return {
            "source_pdf": source.name,
            "source_path": str(source.resolve()),
            "source_sha256": _sha256(source) if source.is_file() else "UNAVAILABLE",
            "source_bytes": source.stat().st_size if source.is_file() else 0,
            "bulletin_date": bulletin,
            "observations": [], "lineage": [], "row_audits": [],
            "recovered_rows": 0, "ambiguous_rows": 0,
            "failure": {
                "source_pdf": source.name,
                "bulletin_date": bulletin,
                "failure_stage": "SOURCE_PDF_EXTRACTION",
                "failure_class": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }


def _bounded_ordered_results(
    executor: ProcessPoolExecutor,
    tasks: list[tuple[str, list[str] | None, list[str] | None]],
    *,
    max_pending: int,
) -> Iterator[dict]:
    """Keep a bounded worker window while yielding strictly in source order."""
    pending: dict[int, Future] = {}
    next_submit = 0
    next_yield = 0
    limit = max(1, max_pending)
    while next_submit < len(tasks) and len(pending) < limit:
        pending[next_submit] = executor.submit(_worker, tasks[next_submit])
        next_submit += 1
    while next_yield < len(tasks):
        future = pending.pop(next_yield)
        yield future.result()
        next_yield += 1
        while next_submit < len(tasks) and len(pending) < limit:
            pending[next_submit] = executor.submit(_worker, tasks[next_submit])
            next_submit += 1


class _ResourceMonitor:
    def __init__(self) -> None:
        self.peak_rss_bytes = 0
        self.minimum_available_bytes: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        try:
            import psutil
            parent = psutil.Process()
            while not self._stop.wait(0.2):
                processes = [parent, *parent.children(recursive=True)]
                rss = 0
                for process in processes:
                    try:
                        rss += process.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
                available = int(psutil.virtual_memory().available)
                self.minimum_available_bytes = available if self.minimum_available_bytes is None else min(self.minimum_available_bytes, available)
        except Exception:
            return

    def __enter__(self) -> "_ResourceMonitor":
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


class Page2Database:
    def __init__(self, path: Path, manifest: dict, *, batch_sources: int = 32):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite database: {path}")
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(SCHEMA_SQL)
        self.run_id = manifest["run_id"]
        self.batch_sources = max(1, int(batch_sources))
        self._since_commit = 0
        self.connection.execute(
            "INSERT INTO run_manifest VALUES (?,?,?,?,?,'PRODUCTION',?,'CLEAN_ROOM',?,?,NULL,NULL,?,0,0,0,0,0,0,0,NULL,NULL)",
            (
                self.run_id, ENGINE_VERSION, SCIENTIFIC_ANCESTOR, REGISTRY_VERSION,
                manifest["roster_sha256"], manifest["run_mode"], manifest["worker_count"],
                manifest["started_at"], manifest["source_count"],
            ),
        )
        self.connection.commit()

    def _commit_if_needed(self) -> None:
        self._since_commit += 1
        if self._since_commit >= self.batch_sources:
            self.connection.commit()
            self._since_commit = 0

    def add_result(self, source_index: int, result: dict) -> int:
        status = "FAILED" if "failure" in result else "EXTRACTED"
        self.connection.execute(
            "INSERT INTO source_manifest VALUES (?,?,?,?,?,?,?,?)",
            (self.run_id, source_index, result["source_pdf"], result["source_path"], result["source_sha256"], result["source_bytes"], result["bulletin_date"], status),
        )
        if "failure" in result:
            failure = result["failure"]
            failure_id = _stable_id("P2FAIL", result["source_sha256"], failure["failure_class"])
            self.connection.execute(
                "INSERT INTO page2_extraction_failure VALUES (?,?,?,?,?,?)",
                (self.run_id, failure_id, source_index, failure["failure_class"], failure["message"], json.dumps(failure, sort_keys=True)),
            )
            self._commit_if_needed()
            return 0

        observation_rows = []
        observation_ids: dict[str, str] = {}
        scientific_fields = set(OBSERVATION_FIELDS) - {
            "source_file", "source_sha256", "page", "bulletin_date", "dam_id", "region",
            "raw_dam_label_token", "row_bbox", "schema_class", "extractor_version",
            "row_detection_method", "row_detection_confidence", "source_validation_status",
        }
        for observation in result["observations"]:
            observation_id = _stable_id("P2OBS", observation["source_sha256"], observation["bulletin_date"], observation["dam_id"])
            observation_ids[observation["dam_id"]] = observation_id
            values = {field: observation.get(field) for field in sorted(scientific_fields)}
            observation_rows.append((
                self.run_id, observation_id, source_index, observation["source_sha256"], observation["bulletin_date"],
                observation["dam_id"], observation["region"], observation["raw_dam_label_token"], observation["row_bbox"],
                observation["schema_class"], observation["row_detection_method"], float(observation["row_detection_confidence"]),
                observation["source_validation_status"], json.dumps(values, sort_keys=True, separators=(",", ":")),
            ))
        self.connection.executemany("INSERT INTO page2_observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", observation_rows)

        lineage_rows = []
        unresolved_rows = []
        unresolved_count = 0
        for item in result["lineage"]:
            observation_id = observation_ids[item["dam_id"]]
            lineage_id = _stable_id("P2LIN", item["source_sha256"], item["bulletin_date"], item["dam_id"], item["physical_column"])
            provenance = {key: item[key] for key in (
                "source_pdf", "source_sha256", "page", "bulletin_date", "dam_id", "region",
                "raw_dam_label_token", "row_bbox", "physical_column", "column_bbox",
                "row_detection_method", "row_detection_confidence", "source_validation_status",
            )}
            lineage_rows.append((
                self.run_id, lineage_id, observation_id, source_index, int(item["physical_column"]),
                item["canonical_semantic"], item["raw_cell_text"], item["parsed_numeric_value"],
                item["parse_status"], item["column_bbox"], json.dumps(provenance, sort_keys=True, separators=(",", ":")),
            ))
            is_rs = int(item["physical_column"]) == 25
            unresolved = is_rs or item["parse_status"] in {"AMBIGUOUS_TOKEN", "NONNUMERIC_SOURCE_EXPRESSION"}
            if unresolved:
                disposition = "RS_UNRESOLVED_PROHIBITED" if is_rs else "SOURCE_EXPRESSION_PRESERVED_NO_INFERENCE"
                unresolved_id = _stable_id("P2UNRES", lineage_id, disposition)
                unresolved_rows.append((self.run_id, unresolved_id, lineage_id, source_index, disposition, json.dumps(item, sort_keys=True, separators=(",", ":"))))
                unresolved_count += 1
        self.connection.executemany("INSERT INTO page2_value_lineage VALUES (?,?,?,?,?,?,?,?,?,?,?)", lineage_rows)
        self.connection.executemany("INSERT INTO page2_unresolved_cell VALUES (?,?,?,?,?,?)", unresolved_rows)

        validation_rows = []
        for name, status_value, details in (
            ("PDF_EXTRACTION", "PASS", {"observation_count": len(result["observations"]), "lineage_count": len(result["lineage"])}),
            ("ROW_IDENTITY_UNAMBIGUOUS", "PASS" if result["ambiguous_rows"] == 0 else "FAIL", {"ambiguous_rows": result["ambiguous_rows"]}),
            ("RS_SEMANTIC_PROTECTION", "PASS", {"policy": "UNRESOLVED_PROHIBITED"}),
        ):
            validation_id = _stable_id("P2VAL", result["source_sha256"], name)
            validation_rows.append((self.run_id, validation_id, source_index, name, status_value, json.dumps(details, sort_keys=True)))
        self.connection.executemany("INSERT INTO page2_validation_result VALUES (?,?,?,?,?,?)", validation_rows)
        self._commit_if_needed()
        return unresolved_count

    def finalize(self, summary: dict) -> None:
        self.connection.execute(
            """UPDATE run_manifest SET completed_at=?,elapsed_seconds=?,processed_source_count=?,observation_count=?,
               lineage_count=?,failure_count=?,unresolved_count=?,recovered_row_count=?,ambiguous_row_count=?,
               source_corpus_hash=?,scientific_identity_hash=? WHERE run_id=?""",
            (
                summary["completed_at"], summary["elapsed_seconds"], summary["processed_source_count"],
                summary["observation_count"], summary["lineage_count"], summary["failure_count"],
                summary["unresolved_count"], summary["recovered_row_count"], summary["ambiguous_row_count"],
                summary["source_corpus_hash"], summary["scientific_identity_hash"], self.run_id,
            ),
        )
        self.connection.commit()
        self.connection.close()


def load_target_registry(path: str | Path) -> tuple[dict[str, tuple[list[str] | None, list[str] | None]], list[Path]]:
    targets: dict[str, tuple[set[str], set[str]]] = {}
    paths: dict[str, Path] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            source_path = Path(row.get("source_path") or row.get("pdf_path") or row.get("source_file") or row["source_pdf"])
            source_name = source_path.name
            dams, fields = targets.setdefault(source_name, (set(), set()))
            dam_id = row.get("dam_id") or row.get("canonical_dam_id")
            field = row.get("canonical_semantic") or row.get("canonical_field") or row.get("field")
            if dam_id:
                dams.add(dam_id)
            if field:
                fields.add(field)
            paths[source_name] = source_path
    normalized = {name: (sorted(dams) or None, sorted(fields) or None) for name, (dams, fields) in targets.items()}
    return normalized, deterministic_inventory(paths.values())


def execute_page2_run(
    pdf_paths: Iterable[str | Path],
    output_root: str | Path,
    *,
    run_id: str,
    run_mode: str = "FULL",
    workers: int = 8,
    targets_by_file: dict[str, tuple[list[str] | None, list[str] | None]] | None = None,
    write_sqlite: bool = True,
    write_csv: bool = True,
    progress_every: int = 100,
) -> dict:
    output = Path(output_root).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Fresh output directory required: {output}")
    output.mkdir(parents=True, exist_ok=True)
    inventory = deterministic_inventory(pdf_paths)
    if not inventory:
        raise ValueError("No Page-2 PDFs selected")
    mode = run_mode.upper()
    if mode not in {"FULL", "TARGETED"}:
        raise ValueError("run_mode must be FULL or TARGETED")
    if mode == "TARGETED" and not targets_by_file:
        raise ValueError("TARGETED mode requires a target registry")
    if workers < 1:
        raise ValueError("workers must be positive")

    started_at = _utc_now()
    started = time.perf_counter()
    manifest = {
        "run_id": run_id, "run_mode": mode, "worker_count": workers,
        "started_at": started_at, "source_count": len(inventory),
        "roster_sha256": _sha256(REGISTRY_PATH),
    }
    counts = {
        "processed_source_count": 0, "observation_count": 0, "lineage_count": 0,
        "failure_count": 0, "unresolved_count": 0, "recovered_row_count": 0,
        "ambiguous_row_count": 0,
    }
    scientific_hash = hashlib.sha256()
    corpus_hash = hashlib.sha256()
    db = Page2Database(output / "page2_extraction_cleanroom.db", manifest) if write_sqlite else None

    try:
        with ExitStack() as stack:
            writers: dict[str, csv.DictWriter] = {}
            if write_csv:
                writers["observations"] = stack.enter_context(_csv_writer(output / "observations.csv.gz", OBSERVATION_FIELDS, compressed=True))
                writers["lineage"] = stack.enter_context(_csv_writer(output / "value_lineage.csv.gz", LINEAGE_FIELDS, compressed=True))
                writers["sources"] = stack.enter_context(_csv_writer(output / "source_manifest.csv", SOURCE_FIELDS))
                writers["failures"] = stack.enter_context(_csv_writer(output / "extraction_failures.csv", FAILURE_FIELDS))
                writers["unresolved"] = stack.enter_context(_csv_writer(output / "unresolved_values.csv", UNRESOLVED_FIELDS))
                writers["validations"] = stack.enter_context(_csv_writer(output / "validation_checks.csv", VALIDATION_FIELDS))
                writers["audits"] = stack.enter_context(_csv_writer(output / "row_detection_audit.csv.gz", ROW_AUDIT_FIELDS, compressed=True))

            tasks = []
            for path in inventory:
                dams: list[str] | None = None
                fields: list[str] | None = None
                if targets_by_file:
                    dams, fields = targets_by_file.get(path.name, (None, None))
                tasks.append((str(path), dams, fields))

            with _ResourceMonitor() as monitor:
                if workers == 1:
                    results = map(_worker, tasks)
                    executor = None
                else:
                    executor = ProcessPoolExecutor(max_workers=workers)
                    results = _bounded_ordered_results(executor, tasks, max_pending=workers * 2)
                try:
                    for source_index, result in enumerate(results, start=1):
                        counts["processed_source_count"] += 1
                        failed = "failure" in result
                        source_row = {
                            "source_index": source_index,
                            "source_pdf": result["source_pdf"],
                            "source_path": result["source_path"],
                            "source_sha256": result["source_sha256"],
                            "source_bytes": result["source_bytes"],
                            "bulletin_date": result["bulletin_date"],
                            "processing_status": "FAILED" if failed else "EXTRACTED",
                        }
                        corpus_hash.update(_canonical_bytes(source_row))
                        if writers:
                            writers["sources"].writerow(source_row)
                        if failed:
                            counts["failure_count"] += 1
                            if writers:
                                writers["failures"].writerow(result["failure"])
                            scientific_hash.update(_canonical_bytes({"source_pdf": result["source_pdf"], "failure": result["failure"]["failure_class"]}))
                        else:
                            if writers:
                                writers["observations"].writerows(result["observations"])
                                writers["lineage"].writerows(result["lineage"])
                                writers["audits"].writerows(result["row_audits"])
                            for observation in result["observations"]:
                                scientific_hash.update(_canonical_bytes({key: value for key, value in observation.items() if key != "extractor_version"}))
                            for item in result["lineage"]:
                                scientific_hash.update(_canonical_bytes({key: value for key, value in item.items() if key != "extractor_version"}))
                                is_rs = int(item["physical_column"]) == 25
                                unresolved = is_rs or item["parse_status"] in {"AMBIGUOUS_TOKEN", "NONNUMERIC_SOURCE_EXPRESSION"}
                                if unresolved:
                                    disposition = "RS_UNRESOLVED_PROHIBITED" if is_rs else "SOURCE_EXPRESSION_PRESERVED_NO_INFERENCE"
                                    if writers:
                                        writers["unresolved"].writerow({**item, "source_index": source_index, "disposition": disposition})
                                    counts["unresolved_count"] += 1
                            if writers:
                                for name, status_value, details in (
                                    ("PDF_EXTRACTION", "PASS", {"observation_count": len(result["observations"]), "lineage_count": len(result["lineage"])}),
                                    ("ROW_IDENTITY_UNAMBIGUOUS", "PASS" if result["ambiguous_rows"] == 0 else "FAIL", {"ambiguous_rows": result["ambiguous_rows"]}),
                                    ("RS_SEMANTIC_PROTECTION", "PASS", {"policy": "UNRESOLVED_PROHIBITED"}),
                                ):
                                    writers["validations"].writerow({
                                        "source_index": source_index, "source_pdf": result["source_pdf"],
                                        "source_sha256": result["source_sha256"], "bulletin_date": result["bulletin_date"],
                                        "validation_name": name, "status": status_value,
                                        "details_json": json.dumps(details, sort_keys=True, separators=(",", ":")),
                                    })
                            counts["observation_count"] += len(result["observations"])
                            counts["lineage_count"] += len(result["lineage"])
                            counts["recovered_row_count"] += int(result["recovered_rows"])
                            counts["ambiguous_row_count"] += int(result["ambiguous_rows"])
                        if db is not None:
                            db_unresolved = db.add_result(source_index, result)
                            if not failed and db_unresolved != sum(
                                int(item["physical_column"]) == 25 or item["parse_status"] in {"AMBIGUOUS_TOKEN", "NONNUMERIC_SOURCE_EXPRESSION"}
                                for item in result["lineage"]
                            ):
                                raise AssertionError("SQLite unresolved count diverged from export policy")
                        if progress_every and (source_index % progress_every == 0 or source_index == len(inventory)):
                            elapsed = max(time.perf_counter() - started, 1e-9)
                            print(f"PAGE2_PROGRESS {source_index}/{len(inventory)} elapsed={elapsed:.1f}s rate={source_index / elapsed:.3f}pdf/s", flush=True)
                finally:
                    if executor is not None:
                        executor.shutdown(wait=True, cancel_futures=False)

            peak_rss = monitor.peak_rss_bytes
            minimum_available = monitor.minimum_available_bytes

        completed_at = _utc_now()
        elapsed_seconds = time.perf_counter() - started
        summary = {
            **manifest, **counts,
            "engine_version": ENGINE_VERSION,
            "scientific_ancestor": SCIENTIFIC_ANCESTOR,
            "roster_version": REGISTRY_VERSION,
            "completed_at": completed_at,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "pdfs_per_second": len(inventory) / elapsed_seconds,
            "observations_per_second": counts["observation_count"] / elapsed_seconds,
            "lineage_cells_per_second": counts["lineage_count"] / elapsed_seconds,
            "source_corpus_hash": corpus_hash.hexdigest(),
            "scientific_identity_hash": scientific_hash.hexdigest(),
            "approx_peak_process_tree_rss_bytes": peak_rss,
            "minimum_available_system_memory_bytes": minimum_available,
            "write_sqlite": write_sqlite,
            "write_csv": write_csv,
            "python_executable": os.sys.executable,
        }
        if db is not None:
            db.finalize(summary)
        with _csv_writer(output / "run_summary.csv", list(summary)) as writer:
            writer.writerow(summary)
        artifact_rows = []
        for path in sorted(output.iterdir(), key=lambda value: value.name.casefold()):
            if path.is_file() and path.name != "output_hashes.csv":
                artifact_rows.append({
                    "artifact": path.name, "absolute_path": str(path.resolve()),
                    "bytes": path.stat().st_size, "sha256": _sha256(path),
                })
        with _csv_writer(output / "output_hashes.csv", ["artifact", "absolute_path", "bytes", "sha256"]) as writer:
            writer.writerows(artifact_rows)
        return summary
    except BaseException:
        if db is not None:
            db.connection.rollback()
            db.connection.close()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Page-2 production extraction")
    parser.add_argument("--input-pdf-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-mode", choices=("FULL", "TARGETED"), default="FULL")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--target-registry")
    parser.add_argument("--pdf-list", help="UTF-8 file containing source PDF basenames for a bounded validation run")
    parser.add_argument("--sample-count", type=int, default=0)
    parser.add_argument("--no-sqlite", action="store_true")
    parser.add_argument("--no-csv", action="store_true")
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args(argv)

    root = Path(args.input_pdf_root)
    pdfs = list(root.glob("*.pdf"))
    if args.pdf_list:
        names = [line.strip() for line in Path(args.pdf_list).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        pdfs = [root / name for name in names]
        missing = [path.name for path in pdfs if not path.is_file()]
        if missing:
            parser.error(f"missing PDFs from --pdf-list: {missing[:10]}")
    targets = None
    if args.run_mode == "TARGETED":
        if not args.target_registry:
            parser.error("--target-registry is required in TARGETED mode")
        targets, pdfs = load_target_registry(args.target_registry)
    elif args.sample_count:
        pdfs = representative_sample(pdfs, args.sample_count)
    summary = execute_page2_run(
        pdfs, args.output_root, run_id=args.run_id, run_mode=args.run_mode,
        workers=args.workers, targets_by_file=targets,
        write_sqlite=not args.no_sqlite, write_csv=not args.no_csv,
        progress_every=args.progress_every,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

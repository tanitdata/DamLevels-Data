from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import os
import threading
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dam_extraction.common.contracts import ValueLineage
from dam_extraction.common.production_store import Page1ProductionDBSink
from dam_extraction.common.serialization import DeterministicCSVWriter, write_csv
from dam_extraction.common.source_identity import identify_source
from dam_extraction.orchestration.corpus_runner import (
    deterministic_pdf_inventory,
    resolve_worker_count,
    run_page1_corpus_outcomes,
)
from dam_extraction.page1.engine import ENGINE_VERSION, _config_hash, _default_alias_path
from dam_extraction.page1.row_identity import GovernedAliasRoster
from dam_extraction.page1.schema import LAYOUT_16
from dam_extraction.page1.semantic_mapper import canonical_field


OBSERVATION_FIELDS = [
    "output_row_key", "source_filename", "source_sha256", "source_bytes",
    "bulletin_date", "physical_page", "logical_page", "raw_dam_label",
    "canonical_dam_id", "schema_layout_class", "execution_scope",
    "engine_version", "physical_row_index",
] + [canonical_field(field) for field in LAYOUT_16[1:]]
LINEAGE_FIELDS = [field.name for field in dataclasses.fields(ValueLineage)]
SOURCE_FIELDS = [
    "source_index", "source_sha256", "source_filename", "source_bytes",
    "source_path", "bulletin_date_raw", "bulletin_date_parsed",
    "date_parse_status", "processing_status",
]
CHECKSUM_SOURCE_FIELDS = [
    "source_index", "source_filename", "source_sha256", "checksum_row_index",
    "row_role", "checksum_scope", "region_or_total", "raw_label", "row_bbox",
    "raw_tokens", "published_values", "reader_method",
    "contributor_boundary_method", "contributor_row_indexes",
    "contributor_raw_labels", "expected_contributors",
]
CHECKSUM_VALIDATION_FIELDS = [
    "source_index", "source_filename", "source_sha256", "execution_scope",
    "checksum_scope", "region_or_total", "field", "expected_contributors",
    "observed_contributors", "numeric_contributors", "completeness",
    "computed_sum", "published_sum", "signed_residual", "absolute_residual",
    "residual_basis", "aggregation_method", "tolerance_policy",
    "tolerance_formula", "tolerance_term_count", "disposition",
    "generates_dam_value",
]
FAILURE_FIELDS = [
    "source_index", "source_filename", "source_sha256", "failure_class",
    "disposition", "failure_message", "failure_traceback", "failure_json",
]
UNRESOLVED_FIELDS = [
    "source_index", "source_filename", "source_sha256", "lineage_id",
    "canonical_dam_id", "canonical_field", "disposition", "unresolved_json",
]
VALIDATION_FIELDS = [
    "source_index", "source_filename", "source_sha256", "validation_name",
    "status", "details_json",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _scientific_payload(result: Any) -> dict[str, Any]:
    return {
        "source": dataclasses.asdict(result.source),
        "scope": result.scope.value,
        "schema": result.schema_layout_class,
        "incident": result.schema_incident_status,
        "observations": result.observations,
        "lineage": [row.as_dict() for row in result.value_lineage],
        "checksum_source": result.checksum_source,
        "checksum_validation": result.checksum_validation,
        "failures": result.failures,
        "unresolved": result.unresolved_cells,
        "validation": result.validation_results,
    }


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
                self.minimum_available_bytes = (
                    available if self.minimum_available_bytes is None
                    else min(self.minimum_available_bytes, available)
                )
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


def representative_sample(paths: Iterable[str | Path], count: int) -> list[Path]:
    inventory = deterministic_pdf_inventory(paths)
    if count <= 0 or count >= len(inventory):
        return inventory
    if count == 1:
        return [inventory[len(inventory) // 2]]
    indexes = sorted({round(index * (len(inventory) - 1) / (count - 1)) for index in range(count)})
    return [inventory[index] for index in indexes]


def load_targets(path: str | Path) -> tuple[dict[str, list[dict[str, str]]], list[Path]]:
    targets: dict[str, list[dict[str, str]]] = {}
    paths: dict[str, Path] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            filename = row.get("source_file") or row.get("source_filename") or Path(row["pdf_path"]).name
            pdf_path = Path(row.get("pdf_path") or row.get("source_path") or filename)
            targets.setdefault(filename, []).append({
                "canonical_dam_id": row["canonical_dam_id"],
                "canonical_field": row.get("canonical_field") or row["field"],
            })
            paths[filename] = pdf_path
    return targets, deterministic_pdf_inventory(paths.values())


def execute_page1_run(
    pdf_paths: Iterable[str | Path],
    output_root: str | Path,
    *,
    run_id: str,
    run_mode: str = "FULL",
    workers: int | str | None = "auto",
    targets_by_file: dict[str, list[dict[str, str]]] | None = None,
    alias_registry_path: str | Path | None = None,
    write_sqlite: bool = True,
    write_csv_exports: bool = True,
    progress_every: int = 100,
) -> dict[str, Any]:
    """Execute an ordered, streaming Page-1 clean-room run."""
    output = Path(output_root).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"fresh output directory required: {output}")
    output.mkdir(parents=True, exist_ok=True)
    inventory = deterministic_pdf_inventory(pdf_paths)
    if not inventory:
        raise ValueError("empty PDF inventory")
    mode = str(run_mode).upper()
    if mode not in {"FULL", "TARGETED"}:
        raise ValueError("run_mode must be FULL or TARGETED")
    if mode == "TARGETED" and not targets_by_file:
        raise ValueError("TARGETED mode requires targets_by_file")
    worker_count = resolve_worker_count(workers)
    alias_path = Path(alias_registry_path).resolve() if alias_registry_path else _default_alias_path().resolve()
    alias_hash = _sha256(alias_path)
    config_hash = _config_hash(alias_path)
    roster_version = GovernedAliasRoster(alias_path).version
    started_at = _utc_now()
    started = time.perf_counter()
    manifest = {
        "run_id": run_id,
        "engine_version": ENGINE_VERSION,
        "config_hash": config_hash,
        "alias_roster_hash": alias_hash,
        "roster_version": roster_version,
        "execution_scope": mode,
        "worker_count": worker_count,
        "source_corpus_hash": "PENDING_ORDERED_SOURCE_MANIFEST",
        "started_at": started_at,
        "source_count": len(inventory),
    }

    writers: dict[str, DeterministicCSVWriter] = {}
    db: Page1ProductionDBSink | None = None
    scientific_hash = hashlib.sha256()
    corpus_hash = hashlib.sha256()
    counts = {
        "processed_source_count": 0,
        "observation_count": 0,
        "lineage_count": 0,
        "failure_count": 0,
        "unresolved_count": 0,
        "checksum_source_count": 0,
        "checksum_validation_count": 0,
        "validation_count": 0,
    }

    try:
        with ExitStack() as stack:
            if write_csv_exports:
                specs = {
                    "observations": ("observations.csv.gz", OBSERVATION_FIELDS),
                    "lineage": ("value_lineage.csv.gz", LINEAGE_FIELDS),
                    "sources": ("source_manifest.csv", SOURCE_FIELDS),
                    "checksum_source": ("checksum_source.csv.gz", CHECKSUM_SOURCE_FIELDS),
                    "checksum_validation": ("checksum_validation.csv.gz", CHECKSUM_VALIDATION_FIELDS),
                    "failures": ("extraction_failures.csv", FAILURE_FIELDS),
                    "unresolved": ("unresolved_values.csv", UNRESOLVED_FIELDS),
                    "validations": ("validation_checks.csv", VALIDATION_FIELDS),
                }
                for key, (filename, fields) in specs.items():
                    writers[key] = stack.enter_context(DeterministicCSVWriter(output / filename, fields))
            if write_sqlite:
                db = Page1ProductionDBSink(output / "page1_extraction_cleanroom.db", manifest)

            with _ResourceMonitor() as monitor:
                for outcome in run_page1_corpus_outcomes(
                    inventory,
                    scope=mode,
                    targets_by_file=targets_by_file,
                    workers=worker_count,
                    alias_registry_path=alias_path,
                ):
                    counts["processed_source_count"] += 1
                    if outcome.succeeded:
                        assert outcome.result is not None
                        result = outcome.result
                        source = result.source
                        scientific_hash.update(_canonical_json(_scientific_payload(result)))
                        corpus_hash.update(_canonical_json({
                            "source_index": outcome.source_index,
                            "source_filename": source.source_filename,
                            "source_sha256": source.source_sha256,
                            "source_bytes": source.source_bytes,
                        }))
                        source_row = {
                            **dataclasses.asdict(source),
                            "source_index": outcome.source_index,
                            "processing_status": "EXTRACTED",
                        }
                        if writers:
                            writers["sources"].write(source_row)
                            writers["observations"].writerows(result.observations)
                            writers["lineage"].writerows(row.as_dict() for row in result.value_lineage)
                            for row in result.checksum_source:
                                writers["checksum_source"].write({
                                    **row,
                                    "source_index": outcome.source_index,
                                    "source_filename": source.source_filename,
                                    "source_sha256": source.source_sha256,
                                })
                            for row in result.checksum_validation:
                                writers["checksum_validation"].write({
                                    **row,
                                    "source_index": outcome.source_index,
                                    "source_filename": source.source_filename,
                                    "source_sha256": source.source_sha256,
                                })
                            for row in result.failures:
                                writers["failures"].write({
                                    "source_index": outcome.source_index,
                                    "source_filename": source.source_filename,
                                    "source_sha256": source.source_sha256,
                                    "failure_class": row["failure_class"],
                                    "disposition": row.get("disposition", "REVIEW"),
                                    "failure_json": row,
                                })
                            for row in result.unresolved_cells:
                                writers["unresolved"].write({
                                    **row,
                                    "source_index": outcome.source_index,
                                    "source_filename": source.source_filename,
                                    "source_sha256": source.source_sha256,
                                    "unresolved_json": row,
                                })
                            for row in result.validation_results:
                                writers["validations"].write({
                                    **row,
                                    "source_index": outcome.source_index,
                                    "source_filename": source.source_filename,
                                    "source_sha256": source.source_sha256,
                                })
                        if db is not None:
                            db.add_result(outcome.source_index, result)
                        counts["observation_count"] += len(result.observations)
                        counts["lineage_count"] += len(result.value_lineage)
                        counts["failure_count"] += len(result.failures)
                        counts["unresolved_count"] += len(result.unresolved_cells)
                        counts["checksum_source_count"] += len(result.checksum_source)
                        counts["checksum_validation_count"] += len(result.checksum_validation)
                        counts["validation_count"] += len(result.validation_results)
                    else:
                        source = identify_source(outcome.source_path)
                        failure = {
                            "failure_class": outcome.failure_class or "WORKER_FAILURE",
                            "failure_message": outcome.failure_message or "",
                            "failure_traceback": outcome.failure_traceback or "",
                            "disposition": "QUARANTINED_WORKER_FAILURE",
                            "source_path": outcome.source_path,
                        }
                        scientific_hash.update(_canonical_json({
                            "source_path": outcome.source_path,
                            "failure_class": failure["failure_class"],
                            "failure_message": failure["failure_message"],
                        }))
                        corpus_hash.update(_canonical_json({
                            "source_index": outcome.source_index,
                            "source_filename": source.source_filename,
                            "source_sha256": source.source_sha256,
                            "source_bytes": source.source_bytes,
                        }))
                        if writers:
                            writers["sources"].write({
                                **dataclasses.asdict(source),
                                "source_index": outcome.source_index,
                                "processing_status": "WORKER_FAILURE",
                            })
                            writers["failures"].write({
                                **failure,
                                "source_index": outcome.source_index,
                                "source_filename": source.source_filename,
                                "source_sha256": source.source_sha256,
                                "failure_json": failure,
                            })
                        if db is not None:
                            db.add_worker_failure(outcome.source_index, outcome.source_path, failure)
                        counts["failure_count"] += 1

                    done = counts["processed_source_count"]
                    if progress_every and (done % progress_every == 0 or done == len(inventory)):
                        elapsed = max(time.perf_counter() - started, 1e-9)
                        print(
                            f"PAGE1_PROGRESS {done}/{len(inventory)} "
                            f"elapsed={elapsed:.1f}s rate={done / elapsed:.3f}pdf/s",
                            flush=True,
                        )
            peak_rss = monitor.peak_rss_bytes
            min_available = monitor.minimum_available_bytes

        completed_at = _utc_now()
        elapsed_seconds = time.perf_counter() - started
        summary = {
            **manifest,
            **counts,
            "source_corpus_hash": corpus_hash.hexdigest(),
            "scientific_identity_hash": scientific_hash.hexdigest(),
            "completed_at": completed_at,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "pdfs_per_second": len(inventory) / elapsed_seconds,
            "observations_per_second": counts["observation_count"] / elapsed_seconds,
            "lineage_cells_per_second": counts["lineage_count"] / elapsed_seconds,
            "approx_peak_process_tree_rss_bytes": peak_rss,
            "minimum_available_system_memory_bytes": min_available,
            "write_sqlite": write_sqlite,
            "write_csv": write_csv_exports,
            "python_executable": os.sys.executable,
        }
        if db is not None:
            db.finalize(summary)
        write_csv(output / "run_summary.csv", [summary], list(summary))

        artifact_rows = []
        for path in sorted(output.iterdir(), key=lambda value: value.name.casefold()):
            if not path.is_file() or path.name == "output_hashes.csv":
                continue
            artifact_rows.append({
                "artifact": path.name,
                "absolute_path": str(path.resolve()),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "scientific_artifact": path.name in {
                    "observations.csv.gz", "value_lineage.csv.gz", "source_manifest.csv",
                    "checksum_source.csv.gz", "checksum_validation.csv.gz",
                    "extraction_failures.csv", "unresolved_values.csv", "validation_checks.csv",
                },
            })
        write_csv(
            output / "output_hashes.csv",
            artifact_rows,
            ["artifact", "absolute_path", "bytes", "sha256", "scientific_artifact"],
        )
        return summary
    except BaseException:
        if db is not None:
            db.abort()
        raise


def _pdfs_under(root: str | Path) -> list[Path]:
    return list(Path(root).glob("*.pdf"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Page-1 production extraction")
    parser.add_argument("--input-pdf-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-mode", choices=("FULL", "TARGETED"), default="FULL")
    parser.add_argument("--workers", default="auto", help="auto or explicit positive integer")
    parser.add_argument("--target-registry")
    parser.add_argument("--sample-count", type=int, default=0)
    parser.add_argument("--no-sqlite", action="store_true")
    parser.add_argument("--no-csv", action="store_true")
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args(argv)

    targets = None
    pdfs = _pdfs_under(args.input_pdf_root)
    if args.run_mode == "TARGETED":
        if not args.target_registry:
            parser.error("--target-registry is required for TARGETED mode")
        targets, target_paths = load_targets(args.target_registry)
        pdfs = target_paths
    elif args.sample_count:
        pdfs = representative_sample(pdfs, args.sample_count)
    workers: int | str = args.workers if str(args.workers).casefold() == "auto" else int(args.workers)
    summary = execute_page1_run(
        pdfs,
        args.output_root,
        run_id=args.run_id,
        run_mode=args.run_mode,
        workers=workers,
        targets_by_file=targets,
        write_sqlite=not args.no_sqlite,
        write_csv_exports=not args.no_csv,
        progress_every=args.progress_every,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

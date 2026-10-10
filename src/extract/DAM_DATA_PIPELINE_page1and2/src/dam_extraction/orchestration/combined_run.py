from __future__ import annotations

import csv
import json
import os
import platform
import sqlite3
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dam_extraction.common.run_contract import (
    ArtifactIdentity,
    ExtractionRunResult,
    OperatorConfig,
    RunStatus,
    canonical_identity,
    canonical_json_bytes,
    hash_tree,
    sha256_file,
)


EXPECTED_OUTPUTS = (
    "observations.csv.gz",
    "value_lineage.csv.gz",
    "source_manifest.csv",
    "validation_checks.csv",
    "extraction_failures.csv",
    "unresolved_values.csv",
    "run_summary.csv",
    "output_hashes.csv",
)
SCIENTIFIC_SUFFIXES = {".py", ".json", ".csv"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_canonical_json(path: str | Path, payload: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(payload, newline=True))


def _read_single_csv(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise ValueError(f"expected one row in {path}, found {len(rows)}")
    return rows[0]


def _int(row: dict[str, str], key: str) -> int:
    return int(float(row.get(key) or 0))


def _float(row: dict[str, str], key: str) -> float:
    return float(row.get(key) or 0.0)


def source_corpus_identity(root: str | Path) -> dict[str, Any]:
    base = Path(root).resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"source root does not exist: {base}")
    records = []
    for source in sorted(base.glob("*.pdf"), key=lambda p: (p.name.casefold(), p.name)):
        records.append({"source_file": source.name, "bytes": source.stat().st_size, "sha256": sha256_file(source)})
    if not records:
        raise ValueError(f"source root contains no PDFs: {base}")
    return {"root": str(base), "count": len(records), "sha256": canonical_identity(records), "records": records}


def database_validation(path: str | Path) -> dict[str, Any]:
    database = Path(path)
    if not database.is_file():
        return {"path": str(database), "integrity_check": "MISSING", "foreign_key_violations": None, "status": "FAIL"}
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    return {
        "path": str(database.resolve()),
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_rows),
        "status": "PASS" if integrity == "ok" and not foreign_rows else "FAIL",
    }


def _artifact_identities(output: Path) -> tuple[ArtifactIdentity, ...]:
    roles = {
        "observations.csv.gz": "OBSERVATIONS",
        "value_lineage.csv.gz": "VALUE_LINEAGE",
        "source_manifest.csv": "SOURCE_MANIFEST",
        "validation_checks.csv": "VALIDATION",
        "extraction_failures.csv": "FAILURES",
        "unresolved_values.csv": "UNRESOLVED",
        "run_summary.csv": "RUN_SUMMARY",
        "output_hashes.csv": "PAGE_ARTIFACT_MANIFEST",
        "page1_extraction_cleanroom.db": "PAGE1_SQLITE",
        "page2_extraction_cleanroom.db": "PAGE2_SQLITE",
        "row_detection_audit.csv.gz": "PAGE2_ROW_AUDIT",
        "checksum_source.csv.gz": "PAGE1_CHECKSUM_SOURCE",
        "checksum_validation.csv.gz": "PAGE1_CHECKSUM_VALIDATION",
    }
    identities = []
    for path in sorted((p for p in output.iterdir() if p.is_file()), key=lambda p: p.name.casefold()):
        identities.append(ArtifactIdentity(str(path.resolve()), path.stat().st_size, sha256_file(path), roles.get(path.name, "PAGE_SPECIFIC")))
    return tuple(identities)


def _validate_page_outputs(page: str, output: Path) -> dict[str, Any]:
    missing = [name for name in EXPECTED_OUTPUTS if not (output / name).is_file()]
    database = output / f"{page}_extraction_cleanroom.db"
    if not database.is_file():
        missing.append(database.name)
    if missing:
        raise FileNotFoundError(f"missing expected {page} outputs: {missing}")
    db = database_validation(database)
    if db["status"] != "PASS":
        raise RuntimeError(f"database validation failed: {db}")
    summary = _read_single_csv(output / "run_summary.csv")
    if _int(summary, "failure_count") != 0:
        raise RuntimeError(f"{page} extraction failures: {summary['failure_count']}")
    if _int(summary, "processed_source_count") != _int(summary, "source_count"):
        raise RuntimeError(f"{page} processed/source count mismatch")
    with (output / "output_hashes.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        registered = list(csv.DictReader(stream))
    if not registered:
        raise RuntimeError(f"{page} output hash register is empty")
    for row in registered:
        artifact = output / row["artifact"]
        if not artifact.is_file():
            raise FileNotFoundError(f"registered {page} artifact missing: {artifact.name}")
        if artifact.stat().st_size != int(row["bytes"]) or sha256_file(artifact) != row["sha256"]:
            raise RuntimeError(f"registered {page} artifact identity mismatch: {artifact.name}")
    return {"summary": summary, "database": db, "artifacts": _artifact_identities(output)}


def _result_from_validation(
    page: str,
    config: OperatorConfig,
    source: dict[str, Any],
    engine_identity: str,
    config_identity: str,
    output: Path,
    validated: dict[str, Any],
) -> ExtractionRunResult:
    summary = validated["summary"]
    counts = {
        "sources": _int(summary, "source_count"),
        "observations": _int(summary, "observation_count"),
        "lineage": _int(summary, "lineage_count"),
        "failures": _int(summary, "failure_count"),
        "unresolved": _int(summary, "unresolved_count"),
    }
    additional: dict[str, Any] = {"database_validation": validated["database"]}
    if page == "page1":
        additional.update({
            "checksum_source_count": _int(summary, "checksum_source_count"),
            "checksum_validation_count": _int(summary, "checksum_validation_count"),
        })
    else:
        additional.update({
            "recovered_row_count": _int(summary, "recovered_row_count"),
            "ambiguous_row_count": _int(summary, "ambiguous_row_count"),
        })
    return ExtractionRunResult(
        page=page,
        run_id=summary.get("run_id") or f"{config.run_id}-{page}",
        run_mode=(summary.get("execution_scope") or summary.get("run_mode") or config.run_mode).upper(),
        source_root=source["root"],
        source_count=source["count"],
        engine_identity=engine_identity,
        config_identity=config_identity,
        workers=config.page1_workers if page == "page1" else config.page2_workers,
        output_root=str(output.resolve()),
        observations_path=str((output / "observations.csv.gz").resolve()),
        lineage_path=str((output / "value_lineage.csv.gz").resolve()),
        database_path=str((output / f"{page}_extraction_cleanroom.db").resolve()),
        source_manifest_path=str((output / "source_manifest.csv").resolve()),
        validation_path=str((output / "validation_checks.csv").resolve()),
        failures_path=str((output / "extraction_failures.csv").resolve()),
        unresolved_path=str((output / "unresolved_values.csv").resolve()),
        artifact_manifest_path=str((output / "output_hashes.csv").resolve()),
        scientific_identity=summary["scientific_identity_hash"],
        status=RunStatus.COMPLETE_VALIDATED.value,
        source_identity=source["sha256"],
        elapsed_seconds=_float(summary, "elapsed_seconds"),
        counts=counts,
        additional=additional,
        artifacts=validated["artifacts"],
    )


def validate_checkpoint(
    path: str | Path,
    *,
    source_identity: str,
    engine_identity: str,
    config_identity: str,
) -> tuple[bool, list[str], ExtractionRunResult | None]:
    checkpoint_path = Path(path)
    reasons: list[str] = []
    if not checkpoint_path.is_file():
        return False, ["CHECKPOINT_MISSING"], None
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception as error:
        return False, [f"CHECKPOINT_UNREADABLE:{type(error).__name__}"], None
    if payload.get("status") != RunStatus.COMPLETE_VALIDATED.value:
        reasons.append(f"STATUS_{payload.get('status', 'MISSING')}")
    for key, expected in (("source_identity", source_identity), ("engine_identity", engine_identity), ("config_identity", config_identity)):
        if payload.get(key) != expected:
            reasons.append(f"{key.upper()}_MISMATCH")
    for artifact in payload.get("result", {}).get("artifacts", []):
        artifact_path = Path(artifact["path"])
        if not artifact_path.is_file():
            reasons.append(f"ARTIFACT_MISSING:{artifact_path.name}")
        elif artifact_path.stat().st_size != artifact["bytes"] or sha256_file(artifact_path) != artifact["sha256"]:
            reasons.append(f"ARTIFACT_HASH_MISMATCH:{artifact_path.name}")
    database_path = payload.get("result", {}).get("database_path")
    if database_path:
        db = database_validation(database_path)
        if db["status"] != "PASS":
            reasons.append("DATABASE_INTEGRITY_FAILED")
    if reasons:
        return False, reasons, None
    result_payload = dict(payload["result"])
    result_payload["artifacts"] = tuple(ArtifactIdentity(**row) for row in result_payload.get("artifacts", []))
    return True, ["CHECKPOINT_AND_HASHES_VALID"], ExtractionRunResult(**result_payload)


def _run_page(
    page: str,
    config: OperatorConfig,
    source: dict[str, Any],
    engine_identity: str,
    config_identity: str,
    output: Path,
    checkpoint_path: Path,
    executor: Callable[[], dict[str, Any]],
) -> tuple[ExtractionRunResult, dict[str, Any]]:
    if config.resume and not config.force_rerun:
        valid, reasons, result = validate_checkpoint(
            checkpoint_path,
            source_identity=source["sha256"],
            engine_identity=engine_identity,
            config_identity=config_identity,
        )
        if valid and result is not None:
            return result, {"page": page, "action": "RESUMED", "pdfs_reextracted": 0, "validation": "PASS", "details": "|".join(reasons)}
        checkpoint_payload = {}
        if checkpoint_path.is_file():
            checkpoint_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint_payload.get("status") == RunStatus.RUNNING.value and output.exists() and any(output.iterdir()):
            # A shell/supervisor can end after the page runner has atomically finalized
            # its DB, run summary, and output-hash register but before this wrapper writes
            # COMPLETE_VALIDATED. Recovery is allowed only by replaying every full gate.
            validated = _validate_page_outputs(page, output)
            if _int(validated["summary"], "source_count") != source["count"]:
                raise RuntimeError(f"{page} recovery source count differs from current corpus")
            result = _result_from_validation(page, config, source, engine_identity, config_identity, output, validated)
            complete = {
                **checkpoint_payload,
                "status": RunStatus.COMPLETE_VALIDATED.value,
                "completed_at": utc_now(),
                "recovery": "FINALIZED_PAGE_OUTPUTS_REVALIDATED_AFTER_SUPERVISOR_INTERRUPTION",
                "result": result.as_dict(),
            }
            write_canonical_json(checkpoint_path, complete)
            return result, {"page": page, "action": "RECOVERED_VALIDATED", "pdfs_reextracted": 0, "validation": "PASS", "details": "RUN_SUMMARY_OUTPUT_HASHES_AND_DATABASE_REVALIDATED"}
        if output.exists() and any(output.iterdir()):
            raise RuntimeError(f"{page} checkpoint cannot be resumed ({reasons}); use a fresh run root or FORCE_RERUN")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"fresh output directory required for {page}: {output}")
    output.mkdir(parents=True, exist_ok=True)
    running = {
        "schema_version": "combined-checkpoint-1.0.0",
        "page": page,
        "status": RunStatus.RUNNING.value,
        "source_identity": source["sha256"],
        "engine_identity": engine_identity,
        "config_identity": config_identity,
        "started_at": utc_now(),
    }
    write_canonical_json(checkpoint_path, running)
    try:
        executor()
        validated = _validate_page_outputs(page, output)
        result = _result_from_validation(page, config, source, engine_identity, config_identity, output, validated)
        complete = {**running, "status": RunStatus.COMPLETE_VALIDATED.value, "completed_at": utc_now(), "result": result.as_dict()}
        write_canonical_json(checkpoint_path, complete)
        return result, {"page": page, "action": "EXTRACTED", "pdfs_reextracted": source["count"], "validation": "PASS", "details": "COMPLETE_VALIDATED"}
    except KeyboardInterrupt:
        write_canonical_json(checkpoint_path, {**running, "status": RunStatus.ABORTED.value, "ended_at": utc_now()})
        raise
    except BaseException as error:
        write_canonical_json(checkpoint_path, {
            **running,
            "status": RunStatus.FAILED.value,
            "ended_at": utc_now(),
            "failure_class": type(error).__name__,
            "failure_message": str(error),
            "traceback": traceback.format_exc(),
        })
        raise


def _runtime_identity() -> dict[str, Any]:
    versions = {}
    for name in ("pdfplumber", "pdfminer", "PIL", "pypdfium2"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "UNKNOWN")
        except Exception as error:
            versions[name] = f"MISSING:{type(error).__name__}"
    payload = {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": versions,
    }
    return {**payload, "identity": canonical_identity(payload)}


def _write_combined_artifact_register(path: Path, results: list[ExtractionRunResult]) -> None:
    fields = ["page", "role", "absolute_path", "bytes", "sha256", "row_count", "schema"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for result in results:
            for artifact in result.artifacts:
                writer.writerow({"page": result.page, "role": artifact.role, "absolute_path": artifact.path, "bytes": artifact.bytes, "sha256": artifact.sha256, "row_count": artifact.row_count, "schema": artifact.schema})


def run_combined(config: OperatorConfig) -> dict[str, Any]:
    project_root = Path(config.project_root).resolve()
    output_root = Path(config.output_root).resolve()
    combined_root = output_root / "combined"
    checkpoint_root = combined_root / "checkpoints"
    combined_root.mkdir(parents=True, exist_ok=True)
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    if config.run_mode.upper() != "FULL":
        raise ValueError("Run-5 combined source baseline requires RUN_MODE='FULL'")
    if config.force_rerun:
        raise ValueError("FORCE_RERUN requires a new fresh OUTPUT_ROOT; in-place deletion is prohibited")

    source1 = source_corpus_identity(config.page1_input_root) if config.run_page1 else None
    source2 = source_corpus_identity(config.page2_input_root) if config.run_page2 else None
    page1_tree = project_root / "src" / "dam_extraction" / "page1"
    page2_tree = project_root / "src" / "dam_extraction" / "page2"
    page1_engine, _ = hash_tree(page1_tree, include=SCIENTIFIC_SUFFIXES)
    page2_engine, _ = hash_tree(page2_tree, include=SCIENTIFIC_SUFFIXES)
    config1 = canonical_identity(config.page_payload("page1"))
    config2 = canonical_identity(config.page_payload("page2"))
    invocation_started = time.perf_counter()
    results: list[ExtractionRunResult] = []
    resume_rows = []

    if config.run_page1 and source1 is not None:
        from dam_extraction.orchestration.page1_production import execute_page1_run

        page1_output = output_root / "page1"
        result, resume = _run_page(
            "page1", config, source1, page1_engine, config1, page1_output, checkpoint_root / "page1.json",
            lambda: execute_page1_run(
                sorted(Path(config.page1_input_root).glob("*.pdf"), key=lambda p: p.name.casefold()),
                page1_output,
                run_id=f"{config.run_id}-page1",
                run_mode=config.run_mode,
                workers=config.page1_workers,
                write_sqlite=config.write_sqlite,
                write_csv_exports=config.write_csv,
            ),
        )
        results.append(result)
        resume_rows.append(resume)

    if config.run_page2 and source2 is not None:
        from dam_extraction.page2.production import execute_page2_run

        page2_output = output_root / "page2"
        result, resume = _run_page(
            "page2", config, source2, page2_engine, config2, page2_output, checkpoint_root / "page2.json",
            lambda: execute_page2_run(
                sorted(Path(config.page2_input_root).glob("*.pdf"), key=lambda p: p.name.casefold()),
                page2_output,
                run_id=f"{config.run_id}-page2",
                run_mode=config.run_mode,
                workers=config.page2_workers,
                write_sqlite=config.write_sqlite,
                write_csv=config.write_csv,
            ),
        )
        results.append(result)
        resume_rows.append(resume)

    runtime = _runtime_identity()
    first_execution = any(row["action"] == "EXTRACTED" for row in resume_rows)
    manifest_path = combined_root / "COMBINED_RUN_MANIFEST.json"
    if manifest_path.is_file() and not first_execution:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schema_version": "combined-run-manifest-1.0.0",
            "combined_run_id": config.run_id,
            "execution_metadata": {"created_at": utc_now(), "sequential_order": [result.page for result in results]},
            "production_v2_identity": hash_tree(project_root, include={".py", ".toml"})[0],
            "operator_config": asdict(config),
            "runtime": runtime,
            "pages": [result.as_dict() for result in results],
            "failure_count": sum(result.counts["failures"] for result in results),
            "unresolved_count": sum(result.counts["unresolved"] for result in results),
            "overall_validation_state": "COMPLETE_VALIDATED" if all(result.status == RunStatus.COMPLETE_VALIDATED.value for result in results) else "FAILED",
        }
        manifest["combined_artifact_identity"] = canonical_identity(manifest)
        write_canonical_json(manifest_path, manifest)
        _write_combined_artifact_register(combined_root / "COMBINED_ARTIFACT_REGISTER.csv", results)

    invocation = {
        "combined_run_id": config.run_id,
        "invocation_elapsed_seconds": round(time.perf_counter() - invocation_started, 6),
        "pages": resume_rows,
        "combined_artifact_identity": manifest["combined_artifact_identity"],
        "manifest_path": str(manifest_path.resolve()),
    }
    write_canonical_json(combined_root / "LAST_INVOCATION.json", invocation)
    return {"manifest": manifest, "invocation": invocation, "results": results}

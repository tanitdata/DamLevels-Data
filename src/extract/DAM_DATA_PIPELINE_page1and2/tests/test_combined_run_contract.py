from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dam_extraction.common.run_contract import ArtifactIdentity, ExtractionRunResult, OperatorConfig, RunStatus, canonical_identity
from dam_extraction.orchestration.combined_run import database_validation, validate_checkpoint, write_canonical_json

TEST_TMP = Path(__file__).resolve().parents[1] / "tmp" / "combined_contract_tests"


def _case(name: str) -> Path:
    root = TEST_TMP / name
    for filename in ("artifact.csv", "page1_extraction_cleanroom.db", "checkpoint.json"):
        path = root / filename
        if path.exists():
            path.unlink()
    return root


def _result(root: Path) -> ExtractionRunResult:
    artifact = root / "artifact.csv"
    artifact.write_text("a\n1\n", encoding="utf-8")
    database = root / "page1_extraction_cleanroom.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    import hashlib

    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return ExtractionRunResult(
        page="page1", run_id="r-page1", run_mode="FULL", source_root=str(root), source_count=1,
        engine_identity="engine", config_identity="config", workers=8, output_root=str(root),
        observations_path=str(artifact), lineage_path=str(artifact), database_path=str(database),
        source_manifest_path=str(artifact), validation_path=str(artifact), failures_path=str(artifact),
        unresolved_path=str(artifact), artifact_manifest_path=str(artifact), scientific_identity="science",
        status=RunStatus.COMPLETE_VALIDATED.value, source_identity="source", elapsed_seconds=1.0,
        artifacts=(ArtifactIdentity(str(artifact), artifact.stat().st_size, digest, "TEST"),),
    )


def test_common_contract_keeps_page_specific_additional_fields() -> None:
    result = _result(_case("common_contract"))
    assert result.page == "page1"
    assert result.additional == {}
    assert "recovered_row_count" not in result.as_dict()


def test_config_identities_distinguish_page_worker_defaults() -> None:
    config = OperatorConfig("p", "p1", "p2", "o", run_id="r")
    assert config.page_payload("page1")["workers"] == 8
    assert config.page_payload("page2")["workers"] == 12
    assert canonical_identity(config.page_payload("page1")) != canonical_identity(config.page_payload("page2"))


def test_checkpoint_validates_identity_hashes_and_database() -> None:
    root = _case("valid_checkpoint")
    result = _result(root)
    checkpoint = root / "checkpoint.json"
    write_canonical_json(checkpoint, {
        "status": RunStatus.COMPLETE_VALIDATED.value,
        "source_identity": "source", "engine_identity": "engine", "config_identity": "config",
        "result": result.as_dict(),
    })
    valid, reasons, restored = validate_checkpoint(checkpoint, source_identity="source", engine_identity="engine", config_identity="config")
    assert valid and restored is not None
    assert reasons == ["CHECKPOINT_AND_HASHES_VALID"]
    valid, reasons, _ = validate_checkpoint(checkpoint, source_identity="changed", engine_identity="engine", config_identity="config")
    assert not valid and "SOURCE_IDENTITY_MISMATCH" in reasons


def test_checkpoint_rejects_file_existence_when_hash_changes() -> None:
    root = _case("changed_hash")
    result = _result(root)
    checkpoint = root / "checkpoint.json"
    write_canonical_json(checkpoint, {
        "status": RunStatus.COMPLETE_VALIDATED.value,
        "source_identity": "source", "engine_identity": "engine", "config_identity": "config",
        "result": result.as_dict(),
    })
    Path(result.artifacts[0].path).write_text("a\n2\n", encoding="utf-8")
    valid, reasons, _ = validate_checkpoint(checkpoint, source_identity="source", engine_identity="engine", config_identity="config")
    assert not valid
    assert any(reason.startswith("ARTIFACT_HASH_MISMATCH") for reason in reasons)


def test_database_integrity_contract() -> None:
    result = _result(_case("database_integrity"))
    assert database_validation(result.database_path)["status"] == "PASS"

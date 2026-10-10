from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from dam_extraction.common.provenance import stable_id
from dam_extraction.common.source_identity import identify_source


PRODUCTION_SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE run_manifest (
  run_id TEXT PRIMARY KEY,
  engine_version TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  alias_roster_hash TEXT NOT NULL,
  roster_version TEXT NOT NULL,
  execution_scope TEXT NOT NULL CHECK(execution_scope IN ('FULL','TARGETED')),
  development_or_production TEXT NOT NULL CHECK(development_or_production='PRODUCTION'),
  run_mode TEXT NOT NULL CHECK(run_mode IN ('FULL','TARGETED')),
  clean_room_classification TEXT NOT NULL CHECK(clean_room_classification='CLEAN_ROOM'),
  worker_count INTEGER NOT NULL,
  source_corpus_hash TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  elapsed_seconds REAL,
  source_count INTEGER NOT NULL,
  processed_source_count INTEGER NOT NULL DEFAULT 0,
  observation_count INTEGER NOT NULL DEFAULT 0,
  lineage_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  unresolved_count INTEGER NOT NULL DEFAULT 0,
  scientific_identity_hash TEXT
);
CREATE TABLE source_manifest (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  source_sha256 TEXT NOT NULL,
  source_filename TEXT NOT NULL,
  source_bytes INTEGER NOT NULL,
  source_path TEXT NOT NULL,
  bulletin_date_raw TEXT,
  bulletin_date_parsed TEXT,
  date_parse_status TEXT NOT NULL,
  processing_status TEXT NOT NULL,
  PRIMARY KEY(run_id, source_index),
  UNIQUE(run_id, source_filename),
  FOREIGN KEY(run_id) REFERENCES run_manifest(run_id)
);
CREATE TABLE page1_observation (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  observation_id TEXT NOT NULL,
  output_row_key TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  bulletin_date TEXT,
  raw_dam_label TEXT NOT NULL,
  canonical_dam_id TEXT NOT NULL,
  schema_layout_class TEXT NOT NULL,
  execution_scope TEXT NOT NULL,
  physical_row_index INTEGER,
  values_json TEXT NOT NULL,
  PRIMARY KEY(run_id, observation_id),
  UNIQUE(run_id, source_index, output_row_key),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE INDEX page1_observation_key_idx ON page1_observation(run_id, output_row_key);
CREATE TABLE page1_value_lineage (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  lineage_id TEXT NOT NULL,
  output_row_key TEXT NOT NULL,
  canonical_semantic_field TEXT NOT NULL,
  parser_state TEXT NOT NULL,
  parsed_numeric_value REAL,
  checksum_validation_reference TEXT,
  provenance_json TEXT NOT NULL,
  PRIMARY KEY(run_id, lineage_id),
  FOREIGN KEY(run_id, source_index, output_row_key)
    REFERENCES page1_observation(run_id, source_index, output_row_key)
);
CREATE TABLE page1_checksum_source (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  checksum_source_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  checksum_row_index INTEGER,
  row_role TEXT NOT NULL,
  source_json TEXT NOT NULL,
  PRIMARY KEY(run_id, checksum_source_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE TABLE page1_checksum_validation (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  checksum_validation_id TEXT NOT NULL,
  checksum_validation_group_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  execution_scope TEXT NOT NULL,
  checksum_scope TEXT NOT NULL,
  region_or_total TEXT NOT NULL,
  field TEXT NOT NULL,
  expected_contributors INTEGER NOT NULL,
  observed_contributors INTEGER NOT NULL,
  numeric_contributors INTEGER NOT NULL,
  computed_sum REAL,
  published_sum REAL,
  signed_residual REAL,
  absolute_residual REAL,
  completeness TEXT NOT NULL,
  tolerance_policy TEXT NOT NULL,
  disposition TEXT NOT NULL,
  validation_json TEXT NOT NULL,
  PRIMARY KEY(run_id, checksum_validation_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE INDEX page1_checksum_group_idx
  ON page1_checksum_validation(run_id, checksum_validation_group_id);
CREATE TABLE page1_extraction_failure (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  failure_id TEXT NOT NULL,
  source_sha256 TEXT,
  failure_class TEXT NOT NULL,
  disposition TEXT NOT NULL,
  failure_json TEXT NOT NULL,
  PRIMARY KEY(run_id, failure_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE TABLE page1_unresolved_cell (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  unresolved_id TEXT NOT NULL,
  lineage_id TEXT,
  canonical_dam_id TEXT,
  canonical_field TEXT,
  disposition TEXT NOT NULL,
  unresolved_json TEXT NOT NULL,
  PRIMARY KEY(run_id, unresolved_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
CREATE TABLE page1_validation_result (
  run_id TEXT NOT NULL,
  source_index INTEGER NOT NULL,
  validation_id TEXT NOT NULL,
  source_sha256 TEXT,
  validation_name TEXT NOT NULL,
  status TEXT NOT NULL,
  details_json TEXT NOT NULL,
  PRIMARY KEY(run_id, validation_id),
  FOREIGN KEY(run_id, source_index) REFERENCES source_manifest(run_id, source_index)
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Page1ProductionDBSink:
    """Single-controller, transactional SQLite sink for ordered PDF results."""

    def __init__(self, path: str | Path, manifest: dict[str, Any], *, batch_sources: int = 32):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(f"clean-room database already exists: {self.path}")
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(PRODUCTION_SCHEMA_SQL)
        self.manifest = dict(manifest)
        self.run_id = str(manifest["run_id"])
        self.batch_sources = max(1, int(batch_sources))
        self._since_commit = 0
        self.connection.execute(
            "INSERT INTO run_manifest VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.run_id,
                manifest["engine_version"],
                manifest["config_hash"],
                manifest["alias_roster_hash"],
                manifest["roster_version"],
                manifest["execution_scope"],
                "PRODUCTION",
                manifest["execution_scope"],
                "CLEAN_ROOM",
                manifest["worker_count"],
                manifest["source_corpus_hash"],
                manifest["started_at"],
                None,
                None,
                manifest["source_count"],
                0,
                0,
                0,
                0,
                0,
                None,
            ),
        )
        self.connection.commit()
        self.connection.execute("BEGIN")

    def _commit_if_needed(self) -> None:
        self._since_commit += 1
        if self._since_commit >= self.batch_sources:
            self.connection.commit()
            self.connection.execute("BEGIN")
            self._since_commit = 0

    def add_result(self, source_index: int, result: Any) -> None:
        source = result.source
        self.connection.execute(
            "INSERT INTO source_manifest VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                self.run_id,
                source_index,
                source.source_sha256,
                source.source_filename,
                source.source_bytes,
                source.source_path,
                source.bulletin_date_raw,
                source.bulletin_date_parsed,
                source.date_parse_status,
                "EXTRACTED",
            ),
        )
        row_keys: dict[str, str] = {}
        for observation in result.observations:
            output_key = observation["output_row_key"]
            observation_id = stable_id("P1OBS", source.source_sha256, output_key)
            values = {key: value for key, value in observation.items() if key.startswith("p1_")}
            self.connection.execute(
                "INSERT INTO page1_observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    source_index,
                    observation_id,
                    output_key,
                    source.source_sha256,
                    observation.get("bulletin_date"),
                    observation["raw_dam_label"],
                    observation["canonical_dam_id"],
                    observation["schema_layout_class"],
                    observation["execution_scope"],
                    observation.get("physical_row_index"),
                    _json(values),
                ),
            )
            row_keys[observation["canonical_dam_id"]] = output_key
        for lineage in result.value_lineage:
            self.connection.execute(
                "INSERT INTO page1_value_lineage VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    source_index,
                    lineage.lineage_id,
                    row_keys[lineage.canonical_dam_id],
                    lineage.canonical_semantic_field,
                    lineage.parser_state,
                    lineage.parsed_numeric_value,
                    lineage.checksum_validation_reference,
                    _json(lineage.as_dict()),
                ),
            )
        for row in result.checksum_source:
            checksum_id = stable_id(
                "P1CHKSRC",
                source.source_sha256,
                row.get("checksum_row_index"),
                row.get("row_role"),
            )
            self.connection.execute(
                "INSERT INTO page1_checksum_source VALUES (?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    source_index,
                    checksum_id,
                    source.source_sha256,
                    row.get("checksum_row_index"),
                    row["row_role"],
                    _json(row),
                ),
            )
        group_id = stable_id("P1CHK", source.source_sha256, result.scope.value)
        for row in result.checksum_validation:
            validation_id = stable_id(
                "P1CHKVAL",
                source.source_sha256,
                row.get("checksum_scope"),
                row.get("region_or_total"),
                row.get("field"),
            )
            self.connection.execute(
                "INSERT INTO page1_checksum_validation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    source_index,
                    validation_id,
                    group_id,
                    source.source_sha256,
                    row["execution_scope"],
                    row["checksum_scope"],
                    row["region_or_total"],
                    row["field"],
                    row["expected_contributors"],
                    row["observed_contributors"],
                    row["numeric_contributors"],
                    row.get("computed_sum"),
                    row.get("published_sum"),
                    row.get("signed_residual"),
                    row.get("absolute_residual"),
                    row["completeness"],
                    row["tolerance_policy"],
                    row["disposition"],
                    _json(row),
                ),
            )
        for ordinal, row in enumerate(result.failures):
            failure_id = stable_id("P1FAIL", source.source_sha256, ordinal, row.get("failure_class"))
            self.connection.execute(
                "INSERT INTO page1_extraction_failure VALUES (?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    source_index,
                    failure_id,
                    source.source_sha256,
                    row["failure_class"],
                    row.get("disposition", "REVIEW"),
                    _json(row),
                ),
            )
        for ordinal, row in enumerate(result.unresolved_cells):
            unresolved_id = stable_id("P1UNRES", source.source_sha256, row.get("lineage_id"), ordinal)
            self.connection.execute(
                "INSERT INTO page1_unresolved_cell VALUES (?,?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    source_index,
                    unresolved_id,
                    row.get("lineage_id"),
                    row.get("canonical_dam_id"),
                    row.get("canonical_field"),
                    row["disposition"],
                    _json(row),
                ),
            )
        for ordinal, row in enumerate(result.validation_results):
            validation_id = stable_id("P1VAL", source.source_sha256, ordinal, row.get("validation_name"))
            self.connection.execute(
                "INSERT INTO page1_validation_result VALUES (?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    source_index,
                    validation_id,
                    source.source_sha256,
                    row["validation_name"],
                    row["status"],
                    row["details_json"],
                ),
            )
        self._commit_if_needed()

    def add_worker_failure(self, source_index: int, source_path: str, failure: dict[str, Any]) -> None:
        try:
            source = identify_source(source_path)
            source_values = (
                source.source_sha256,
                source.source_filename,
                source.source_bytes,
                source.source_path,
                source.bulletin_date_raw,
                source.bulletin_date_parsed,
                source.date_parse_status,
            )
        except Exception:
            path = Path(source_path).resolve()
            source_values = ("UNAVAILABLE", path.name, path.stat().st_size if path.exists() else 0, str(path), path.stem, None, "SOURCE_IDENTITY_FAILED")
        self.connection.execute(
            "INSERT INTO source_manifest VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.run_id, source_index, *source_values, "WORKER_FAILURE"),
        )
        failure_id = stable_id("P1FAIL", source_values[0], failure.get("failure_class"), source_index)
        self.connection.execute(
            "INSERT INTO page1_extraction_failure VALUES (?,?,?,?,?,?,?)",
            (
                self.run_id,
                source_index,
                failure_id,
                source_values[0],
                failure["failure_class"],
                "QUARANTINED_WORKER_FAILURE",
                _json(failure),
            ),
        )
        self._commit_if_needed()

    def finalize(self, summary: dict[str, Any]) -> None:
        self.connection.commit()
        self.connection.execute(
            """UPDATE run_manifest SET completed_at=?, elapsed_seconds=?, source_corpus_hash=?,
               processed_source_count=?, observation_count=?, lineage_count=?,
               failure_count=?, unresolved_count=?, scientific_identity_hash=?
               WHERE run_id=?""",
            (
                summary["completed_at"],
                summary["elapsed_seconds"],
                summary["source_corpus_hash"],
                summary["processed_source_count"],
                summary["observation_count"],
                summary["lineage_count"],
                summary["failure_count"],
                summary["unresolved_count"],
                summary["scientific_identity_hash"],
                self.run_id,
            ),
        )
        self.connection.commit()
        self.connection.close()

    def abort(self) -> None:
        try:
            self.connection.rollback()
        finally:
            self.connection.close()

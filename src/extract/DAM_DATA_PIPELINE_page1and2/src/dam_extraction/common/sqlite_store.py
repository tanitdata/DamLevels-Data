from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS run_manifest (
  run_id TEXT PRIMARY KEY, engine_version TEXT NOT NULL, config_hash TEXT NOT NULL,
  roster_version TEXT NOT NULL, execution_scope TEXT NOT NULL,
  development_or_production TEXT NOT NULL CHECK(development_or_production IN ('DEVELOPMENT','PRODUCTION')),
  started_at TEXT NOT NULL, completed_at TEXT, source_count INTEGER NOT NULL DEFAULT 0,
  observation_count INTEGER NOT NULL DEFAULT 0, lineage_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_manifest (
  run_id TEXT NOT NULL, source_sha256 TEXT NOT NULL, source_filename TEXT NOT NULL,
  source_bytes INTEGER NOT NULL, source_path TEXT NOT NULL, bulletin_date_raw TEXT,
  bulletin_date_parsed TEXT, date_parse_status TEXT NOT NULL,
  PRIMARY KEY(run_id, source_sha256), FOREIGN KEY(run_id) REFERENCES run_manifest(run_id)
);
CREATE TABLE IF NOT EXISTS page1_observation (
  run_id TEXT NOT NULL, output_row_key TEXT NOT NULL, source_sha256 TEXT NOT NULL,
  bulletin_date TEXT, raw_dam_label TEXT NOT NULL, canonical_dam_id TEXT NOT NULL,
  schema_layout_class TEXT NOT NULL, execution_scope TEXT NOT NULL, values_json TEXT NOT NULL,
  PRIMARY KEY(run_id, output_row_key), FOREIGN KEY(run_id) REFERENCES run_manifest(run_id)
);
CREATE TABLE IF NOT EXISTS page1_value_lineage (
  run_id TEXT NOT NULL, lineage_id TEXT NOT NULL, output_row_key TEXT NOT NULL,
  canonical_semantic_field TEXT NOT NULL, parser_state TEXT NOT NULL,
  parsed_numeric_value REAL, provenance_json TEXT NOT NULL,
  PRIMARY KEY(run_id, lineage_id), FOREIGN KEY(run_id) REFERENCES run_manifest(run_id)
);
CREATE TABLE IF NOT EXISTS page1_checksum_source (
  run_id TEXT NOT NULL, source_sha256 TEXT NOT NULL, checksum_row_index INTEGER,
  row_role TEXT NOT NULL, source_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page1_checksum_validation (
  run_id TEXT NOT NULL, source_sha256 TEXT NOT NULL, execution_scope TEXT NOT NULL,
  checksum_scope TEXT NOT NULL, region_or_total TEXT NOT NULL, field TEXT NOT NULL,
  expected_contributors INTEGER NOT NULL, observed_contributors INTEGER NOT NULL,
  numeric_contributors INTEGER NOT NULL,
  computed_sum REAL, published_sum REAL, signed_residual REAL, absolute_residual REAL,
  completeness TEXT NOT NULL, tolerance_policy TEXT NOT NULL, disposition TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page1_extraction_failure (
  run_id TEXT NOT NULL, source_sha256 TEXT, failure_class TEXT NOT NULL,
  disposition TEXT NOT NULL, failure_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page1_unresolved_cell (
  run_id TEXT NOT NULL, lineage_id TEXT, canonical_dam_id TEXT,
  canonical_field TEXT, disposition TEXT NOT NULL, unresolved_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page1_validation_result (
  run_id TEXT NOT NULL, source_sha256 TEXT, validation_name TEXT NOT NULL,
  status TEXT NOT NULL, details_json TEXT NOT NULL
);
"""


def initialize_database(path: str | Path) -> sqlite3.Connection:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output)
    connection.executescript(SCHEMA_SQL)
    return connection


def store_results(path: str | Path, run_manifest: dict[str, Any], results: Iterable[Any]) -> None:
    connection = initialize_database(path)
    run_id = run_manifest["run_id"]
    with connection:
        connection.execute(
            "INSERT OR REPLACE INTO run_manifest VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, run_manifest["engine_version"], run_manifest["config_hash"], run_manifest["roster_version"],
             run_manifest["execution_scope"], run_manifest["development_or_production"],
             run_manifest["started_at"], run_manifest.get("completed_at"), run_manifest.get("source_count", 0),
             run_manifest.get("observation_count", 0), run_manifest.get("lineage_count", 0)),
        )
        for result in results:
            source = result.source
            connection.execute(
                "INSERT OR IGNORE INTO source_manifest VALUES (?,?,?,?,?,?,?,?)",
                (run_id, source.source_sha256, source.source_filename, source.source_bytes, source.source_path,
                 source.bulletin_date_raw, source.bulletin_date_parsed, source.date_parse_status),
            )
            for observation in result.observations:
                values = {key: value for key, value in observation.items() if key.startswith("p1_")}
                connection.execute(
                    "INSERT OR REPLACE INTO page1_observation VALUES (?,?,?,?,?,?,?,?,?)",
                    (run_id, observation["output_row_key"], source.source_sha256, observation.get("bulletin_date"),
                     observation["raw_dam_label"], observation["canonical_dam_id"],
                     observation["schema_layout_class"], observation["execution_scope"],
                     json.dumps(values, ensure_ascii=False, sort_keys=True)),
                )
            row_keys = {row["canonical_dam_id"]: row["output_row_key"] for row in result.observations}
            for lineage in result.value_lineage:
                connection.execute(
                    "INSERT OR REPLACE INTO page1_value_lineage VALUES (?,?,?,?,?,?,?)",
                    (run_id, lineage.lineage_id, row_keys[lineage.canonical_dam_id],
                     lineage.canonical_semantic_field, lineage.parser_state, lineage.parsed_numeric_value,
                     json.dumps(lineage.as_dict(), ensure_ascii=False, sort_keys=True)),
                )
            for row in result.checksum_source:
                connection.execute("INSERT INTO page1_checksum_source VALUES (?,?,?,?,?)",
                                   (run_id, source.source_sha256, row.get("checksum_row_index"), row["row_role"],
                                    json.dumps(row, ensure_ascii=False, sort_keys=True)))
            for row in result.checksum_validation:
                connection.execute("INSERT INTO page1_checksum_validation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (run_id, source.source_sha256, row["execution_scope"], row["checksum_scope"],
                                    row["region_or_total"], row["field"], row["expected_contributors"],
                                    row["observed_contributors"], row["numeric_contributors"],
                                    row["computed_sum"], row["published_sum"], row["signed_residual"],
                                    row["absolute_residual"], row["completeness"], row["tolerance_policy"],
                                    row["disposition"]))
            for row in result.failures:
                connection.execute("INSERT INTO page1_extraction_failure VALUES (?,?,?,?,?)",
                                   (run_id, source.source_sha256, row["failure_class"], row.get("disposition", "REVIEW"),
                                    json.dumps(row, ensure_ascii=False, sort_keys=True)))
            for row in result.unresolved_cells:
                connection.execute("INSERT INTO page1_unresolved_cell VALUES (?,?,?,?,?,?)",
                                   (run_id, row.get("lineage_id"), row.get("canonical_dam_id"), row.get("canonical_field"),
                                    row["disposition"], json.dumps(row, ensure_ascii=False, sort_keys=True)))
            for row in result.validation_results:
                connection.execute("INSERT INTO page1_validation_result VALUES (?,?,?,?,?)",
                                   (run_id, source.source_sha256, row["validation_name"], row["status"], row["details_json"]))
    connection.close()

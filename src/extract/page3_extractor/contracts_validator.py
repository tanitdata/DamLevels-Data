"""Output-contract validation, packaged.

Behaviourally equivalent to ``03_exploration/scripts/sonnet_validate_output_contracts.py``
v2.0.0 (the IC-003 fix), reimplemented as a library function so the notebook, the
CLI and the tests all exercise the same code path.

The defect that fix exists for is worth restating: the original validator had a
silent ``--schema-root`` default pointing at a directory that did not exist, so
``glob`` returned nothing and it exited 0 on every input. **A gate that cannot
fail is not a gate.** Zero schemas is a hard failure here, and so is a missing
table.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

VALIDATOR_VERSION = "3.0.0"

EXIT_OK = 0
EXIT_ZERO_SCHEMAS = 2
EXIT_MISSING_TABLE = 3
EXIT_VALIDATION_FAILURE = 4
EXIT_ROW_COUNT_MISMATCH = 5


def _check_type(value: str, col_type: str) -> bool:
    if value == "":
        return True
    try:
        if col_type == "int":
            int(value)
        elif col_type == "float":
            float(value)
        elif col_type == "bool":
            return value in ("True", "False", "true", "false", "0", "1")
        elif col_type == "date":
            return len(value) == 10 and value[4] == "-" and value[7] == "-"
        elif col_type == "json":
            json.loads(value)
    except (ValueError, json.JSONDecodeError):
        return False
    return True


def validate_table(csv_path: Path, schema: dict,
                   expected_row_count: Optional[int] = None) -> tuple[list[str], int]:
    violations: list[str] = []
    cols = [c["name"] for c in schema["columns"]]
    col_by_name = {c["name"]: c for c in schema["columns"]}
    enums = schema.get("enums", {})
    pk = schema.get("primary_key", [])

    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return ["EMPTY_FILE: no header row"], 0
        if header != cols:
            missing = [c for c in cols if c not in header]
            extra = [c for c in header if c not in cols]
            return ([f"HEADER_MISMATCH: missing={missing} extra={extra} "
                     f"order_or_name_diff={header != cols}"], 0)

        pk_idx = [cols.index(k) for k in pk if k in cols]
        seen = Counter()
        rows = 0
        for row in reader:
            rows += 1
            if len(row) != len(cols):
                violations.append(
                    f"ROW_LENGTH_MISMATCH at data row {rows}: expected {len(cols)} "
                    f"got {len(row)}")
                continue
            for i, name in enumerate(cols):
                col = col_by_name[name]
                val = row[i]
                if val == "" and not col["nullable"]:
                    violations.append(f"NOT_NULLABLE_VIOLATION row {rows} col {name}")
                if not _check_type(val, col["type"]):
                    violations.append(
                        f"TYPE_VIOLATION row {rows} col {name} value={val!r} "
                        f"expected_type={col['type']}")
                if name in enums and val != "" and val not in enums[name]:
                    violations.append(
                        f"INVALID_ENUM row {rows} col {name} value={val!r} "
                        f"allowed={enums[name]}")
            if pk_idx:
                seen[tuple(row[i] for i in pk_idx)] += 1

        for key, count in seen.items():
            if count > 1:
                violations.append(
                    f"DUPLICATE_PRIMARY_KEY {dict(zip(pk, key))} occurs {count} times")

    if expected_row_count is not None and rows != expected_row_count:
        violations.append(
            f"ROW_COUNT_RECONCILIATION_FAILURE: expected={expected_row_count} actual={rows}")
    return violations, rows


def validate_output_contracts(output_root: Path,
                              schema_root: Path,
                              row_counts: Optional[dict[str, int]] = None) -> dict[str, Any]:
    output_root = Path(output_root)
    schema_root = Path(schema_root)

    if not schema_root.exists():
        return {"status": "FAIL", "exit_code": EXIT_ZERO_SCHEMAS,
                "reason": f"schema-root does not exist: {schema_root}",
                "schemas_checked": 0, "results": []}

    schema_files = sorted(schema_root.glob("*.schema.json"))
    if not schema_files:
        return {"status": "FAIL", "exit_code": EXIT_ZERO_SCHEMAS,
                "reason": f"zero schema files under {schema_root}",
                "schemas_checked": 0, "results": []}

    expected = row_counts or {}
    results: list[dict[str, Any]] = []
    exit_code = EXIT_OK

    for sp in schema_files:
        schema = json.loads(sp.read_text(encoding="utf-8"))
        table = schema["table"]

        # A schema with a repeated column name would validate against its own
        # table forever, because both sides carry the duplicate. Check the
        # contract itself before checking anything against it.
        names = [c["name"] for c in schema["columns"]]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            results.append({"table": table, "status": "FAIL",
                            "violations": [f"SCHEMA_DUPLICATE_COLUMNS: {duplicates}"]})
            exit_code = max(exit_code, EXIT_VALIDATION_FAILURE)
            continue

        matches = [p for p in output_root.rglob(f"{table}.csv")
                   if "source_package" not in p.parts and "schemas" not in p.parts]
        if not matches:
            results.append({"table": table, "status": "MISSING",
                            "expected_layer": schema.get("layer")})
            exit_code = max(exit_code, EXIT_MISSING_TABLE)
            continue
        if len(matches) > 1:
            results.append({"table": table, "status": "FAIL",
                            "violations": [f"AMBIGUOUS_LOCATION: {[str(m) for m in matches]}"]})
            exit_code = max(exit_code, EXIT_VALIDATION_FAILURE)
            continue
        violations, rows = validate_table(matches[0], schema, expected.get(table))
        if violations:
            only_row_count = (len(violations) == 1
                              and "ROW_COUNT_RECONCILIATION_FAILURE" in violations[0])
            exit_code = max(exit_code,
                            EXIT_ROW_COUNT_MISMATCH if only_row_count
                            else EXIT_VALIDATION_FAILURE)
            results.append({"table": table, "status": "FAIL", "row_count": rows,
                            "violations": violations[:50],
                            "violation_count": len(violations)})
        else:
            results.append({"table": table, "status": "PASS", "row_count": rows,
                            "violations": []})

    return {
        "validator_version": VALIDATOR_VERSION,
        "schema_root": str(schema_root),
        "output_root": str(output_root),
        "schemas_checked": len(schema_files),
        "pass_count": sum(1 for r in results if r["status"] == "PASS"),
        "fail_count": sum(1 for r in results if r["status"] != "PASS"),
        "exit_code": exit_code,
        "status": "PASS" if exit_code == EXIT_OK else "FAIL",
        "results": results,
    }

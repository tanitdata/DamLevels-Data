"""Schema-driven CSV writing.

Every table this package emits is declared by a ``*.schema.json`` contract. The
writer takes the header, column order and types from that contract, so a table
and its schema cannot drift apart, and the contract validator has something real
to check.

Output rules (governing prompt sections 9 and 14):

* ``utf-8-sig`` so Excel renders Arabic without mojibake;
* ``\\n`` line terminator and no locale-dependent float formatting, so the same
  inputs always produce byte-identical files;
* explicit empty string for null — never a zero, never ``NaN``;
* writes are atomic (temp file plus replace), so an interrupted run never
  leaves a half table behind.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

ENCODING = "utf-8-sig"
LINE_TERMINATOR = "\n"


@dataclass(frozen=True)
class TableSchema:
    table: str
    layer: str
    grain: str
    primary_key: tuple[str, ...]
    columns: tuple[dict[str, Any], ...]
    enums: Mapping[str, Sequence[str]]
    path: Optional[Path] = None

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c["name"] for c in self.columns)

    def column_type(self, name: str) -> str:
        for c in self.columns:
            if c["name"] == name:
                return c["type"]
        return "string"


class SchemaRegistry:
    """All output contracts, loaded once per process."""

    def __init__(self, schema_root: Path):
        self.root = Path(schema_root)
        self._by_table: dict[str, TableSchema] = {}
        for p in sorted(self.root.glob("*.schema.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            names = [c["name"] for c in data["columns"]]
            duplicates = sorted({n for n in names if names.count(n) > 1})
            if duplicates:
                # The contract validator cannot catch this: it compares a table's
                # header against this same schema, so a duplicated name matches
                # itself and passes. Load time is the only place it is visible.
                raise ValueError(
                    f"{p.name}: duplicate column names {duplicates}; a schema with a "
                    "repeated column silently produces an unreadable table"
                )
            ts = TableSchema(
                table=data["table"],
                layer=data.get("layer", ""),
                grain=data.get("grain", ""),
                primary_key=tuple(data.get("primary_key", ())),
                columns=tuple(data["columns"]),
                enums=data.get("enums", {}),
                path=p,
            )
            self._by_table[ts.table] = ts
        if not self._by_table:
            raise FileNotFoundError(
                f"no *.schema.json under {self.root}: a validator that checks zero "
                "schemas is not a gate"
            )

    def __contains__(self, table: str) -> bool:
        return table in self._by_table

    def __len__(self) -> int:
        return len(self._by_table)

    def get(self, table: str) -> TableSchema:
        try:
            return self._by_table[table]
        except KeyError as exc:
            raise KeyError(
                f"table {table!r} has no schema under {self.root}; declare it before "
                "writing it"
            ) from exc

    def tables(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_table))


def format_cell(value: Any, col_type: str) -> str:
    """Render one value deterministically. ``None`` becomes an empty string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if col_type == "json":
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if col_type == "float":
        if isinstance(value, str):
            return value
        f = float(value)
        if f == int(f) and abs(f) < 1e15:
            return str(int(f))
        return repr(round(f, 6))
    if col_type == "int":
        if isinstance(value, str):
            return value
        return str(int(value))
    text = str(value)
    # A stray newline inside a cell would still be valid CSV but makes evidence
    # painful to read in a terminal; collapse it and keep the content.
    return text.replace("\r", " ").replace("\n", " ")


class TableWriter:
    """Buffered, atomic, schema-checked writer for one table."""

    def __init__(self, schema: TableSchema, path: Path):
        self.schema = schema
        self.path = Path(path)
        self.rows: list[list[str]] = []
        self._pk_index = [schema.column_names.index(k) for k in schema.primary_key
                          if k in schema.column_names]

    def append(self, row: Mapping[str, Any]) -> None:
        unknown = set(row) - set(self.schema.column_names)
        if unknown:
            raise KeyError(
                f"{self.schema.table}: keys not in the schema: {sorted(unknown)}"
            )
        self.rows.append([
            format_cell(row.get(name), self.schema.column_type(name))
            for name in self.schema.column_names
        ])

    def extend(self, rows: Iterable[Mapping[str, Any]]) -> None:
        for r in rows:
            self.append(r)

    def __len__(self) -> int:
        return len(self.rows)

    def flush(self, *, sort: bool = True) -> dict[str, Any]:
        """Write the table and return its manifest entry."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.rows
        if sort and self._pk_index:
            rows = sorted(rows, key=lambda r: tuple(r[i] for i in self._pk_index))
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding=ENCODING, newline="") as fh:
            w = csv.writer(fh, lineterminator=LINE_TERMINATOR)
            w.writerow(self.schema.column_names)
            w.writerows(rows)
        os.replace(tmp, self.path)
        return {
            "table": self.schema.table,
            "path": str(self.path),
            "row_count": len(rows),
            "column_count": len(self.schema.column_names),
            "sha256": sha256_file(self.path),
            "bytes": self.path.stat().st_size,
            "layer": self.schema.layer,
            "grain": self.schema.grain,
        }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return sha256_file(path)


def write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return sha256_file(path)


class RunWriters:
    """All writers for one run directory, created on demand."""

    def __init__(self, registry: SchemaRegistry, run_dir: Path,
                 layout: Mapping[str, str]):
        self.registry = registry
        self.run_dir = Path(run_dir)
        self.layout = dict(layout)
        self._writers: dict[str, TableWriter] = {}

    def writer(self, table: str) -> TableWriter:
        if table not in self._writers:
            schema = self.registry.get(table)
            sub = self.layout.get(table, self.layout.get("_default", ""))
            path = self.run_dir / sub / f"{table}.csv" if sub else self.run_dir / f"{table}.csv"
            self._writers[table] = TableWriter(schema, path)
        return self._writers[table]

    def ensure_all_tables(self) -> None:
        """Create a writer for every declared schema.

        An empty run still emits every contract table with its header, so the
        validator checks a complete surface instead of quietly skipping the
        tables a particular run had nothing to say about.
        """
        for table in self.registry.tables():
            self.writer(table)

    def flush_all(self) -> list[dict[str, Any]]:
        return [w.flush() for _, w in sorted(self._writers.items())]

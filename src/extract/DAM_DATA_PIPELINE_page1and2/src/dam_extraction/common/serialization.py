from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path
from typing import Any, Iterable


def _flat(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    if fields is None:
        fields = sorted({key for row in materialized for key in row})
    if output.suffix == ".gz":
        raw = output.open("wb")
        compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0)
        handle = io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="")
    else:
        handle = output.open("w", encoding="utf-8-sig", newline="")
        raw = compressed = None
    try:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in materialized:
            writer.writerow({key: _flat(value) for key, value in row.items()})
    finally:
        handle.close()
        if compressed is not None:
            compressed.close()
        if raw is not None:
            raw.close()
    return len(materialized)


class DeterministicCSVWriter:
    """Streaming CSV/CSV.GZ writer with byte-reproducible gzip headers."""

    def __init__(self, path: str | Path, fields: list[str], *, compresslevel: int = 6):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fields = list(fields)
        self.count = 0
        self._raw = None
        self._compressed = None
        if self.path.suffix == ".gz":
            self._raw = self.path.open("wb")
            self._compressed = gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=self._raw,
                compresslevel=compresslevel,
                mtime=0,
            )
            self._handle = io.TextIOWrapper(self._compressed, encoding="utf-8-sig", newline="")
        else:
            self._handle = self.path.open("w", encoding="utf-8-sig", newline="")
        self._writer = csv.DictWriter(
            self._handle,
            fieldnames=self.fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        self._writer.writeheader()

    def write(self, row: dict[str, Any]) -> None:
        self._writer.writerow({key: _flat(row.get(key)) for key in self.fields})
        self.count += 1

    def writerows(self, rows: Iterable[dict[str, Any]]) -> int:
        before = self.count
        for row in rows:
            self.write(row)
        return self.count - before

    def close(self) -> None:
        if self._handle.closed:
            return
        self._handle.close()
        if self._compressed is not None:
            self._compressed.close()
        if self._raw is not None:
            self._raw.close()

    def __enter__(self) -> "DeterministicCSVWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

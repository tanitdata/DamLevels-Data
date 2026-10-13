"""Build the full Page 1 table: every printed Page 1 column, one row per dam and bulletin.

Packaging only: no extraction is run and no value is changed, filled or shifted.
The input is the accepted Page 1 extraction (engine page1-authoritative-0.2.3),
the same file data/storage.csv was built from; its SHA-256 is checked.

    python src/build_page1_table.py   (needs page1_observations in config/paths.local.toml)
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from paths import REPO, external

PAGE1_OBSERVATIONS_SHA256 = "91e8373f36ff68b2080f54762ea9d15c041d3f9b45b21768d9b694168939ac85"
AUTHORITY_RELEASE = "PAGE1_0.2.3_CURRENT_EXTRACTION_DELIVERY"
CSV_PATH = REPO / "data/bulletin_page1.csv"
PARQUET_PATH = REPO / "data/parquet/bulletin_page1.parquet"

ID_FIELDS = [
    "source_row_key", "dam_id", "bulletin_date", "source_file", "source_sha256", "page",
    "layout", "engine_version", "authority_release",
]
TEXT_VALUE_FIELDS = {"p1_release_action_code"}
# Printed Page 1 columns in bulletin order (DLO 0.3 source columns of P1_observations).
VALUE_FIELDS = [
    "p1_apport_today",
    "p1_apport_cumul_this_month",
    "p1_apport_average_month",
    "p1_apport_cumul_since_sep",
    "p1_apport_cumul_prev_year",
    "p1_apport_average_period",
    "p1_release_action_code",
    "p1_release_yesterday",
    "p1_release_today",
    "p1_release_cumul_this_month",
    "p1_release_cumul_year",
    "p1_release_cumul_last_year",
    "p1_stock_fill_pct",
    "p1_stock_today_mm3",
    "p1_stock_last_year_mm3",
]
FIELDS = ID_FIELDS + VALUE_FIELDS


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_float_text(value: str) -> str:
    # Same normalisation as data/storage.csv (src/build_e2.py).
    return format(float(value), ".15g")


def build_rows(p1_obs: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with gzip.open(p1_obs, "rt", encoding="utf-8-sig", newline="") as f:
        for source in csv.DictReader(f):
            if source["execution_scope"] != "FULL" or source["logical_page"] != "PAGE_1":
                raise ValueError(f"unexpected Page 1 row scope: {source['output_row_key']}")
            row = {
                "source_row_key": source["output_row_key"],
                "dam_id": source["canonical_dam_id"],
                "bulletin_date": source["bulletin_date"],
                "source_file": source["source_filename"],
                "source_sha256": source["source_sha256"],
                "page": source["physical_page"],
                "layout": source["schema_layout_class"],
                "engine_version": source["engine_version"],
                "authority_release": AUTHORITY_RELEASE,
            }
            for field in VALUE_FIELDS:
                value = source[field].strip()
                row[field] = value if not value or field in TEXT_VALUE_FIELDS else clean_float_text(value)
            rows.append(row)
    keys = [(row["dam_id"], row["bulletin_date"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate dam_id/bulletin_date rows in the Page 1 extraction")
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_parquet(path: Path, rows: list[dict[str, str]]) -> None:
    columns: dict[str, list] = {field: [row[field] for row in rows] for field in ID_FIELDS}
    for field in VALUE_FIELDS:
        values = [row[field] for row in rows]
        if field in TEXT_VALUE_FIELDS:
            columns[field] = values
        else:
            columns[field] = [None if v == "" else float(v) for v in values]
    pq.write_table(pa.table(columns), path, compression="zstd")


def main() -> None:
    p1_obs = external("page1_observations")
    digest = sha256(p1_obs)
    if digest != PAGE1_OBSERVATIONS_SHA256:
        raise SystemExit(f"Page 1 observations SHA-256 {digest} differs from the accepted input")
    rows = build_rows(p1_obs)
    write_csv(CSV_PATH, rows)
    write_parquet(PARQUET_PATH, rows)
    print(json.dumps({
        "rows": len(rows),
        "dams": len({row["dam_id"] for row in rows}),
        "bulletin_dates": len({row["bulletin_date"] for row in rows}),
        "non_blank": {field: sum(1 for row in rows if row[field]) for field in VALUE_FIELDS},
        "csv_sha256": sha256(CSV_PATH),
        "parquet_sha256": sha256(PARQUET_PATH),
    }, indent=2))


if __name__ == "__main__":
    main()

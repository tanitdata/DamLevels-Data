from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
from pydantic import ValidationError

from paths import optional
from validate.models import (
    BulletinManifestRecord,
    CapacityRegime,
    Dam,
    StorageObservation,
    TransferObservation,
)


E1_FILE_MANIFEST_SHA256 = "2debc06e3532edaca2b2d78bb30f8933d0b41a4e85fe835817b226aced9ebb14"
V010_ZIP_SHA256 = "303673e8b342572dff807797355e15cdea9a39325e6083931b31d5f6c783c9d0"


def v010_zip_configured() -> bool:
    """The frozen V010 review ZIP is checked only where its location is configured."""
    return optional("v010_review_zip") is not None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _validate_models(path: Path, model, errors: list[str]) -> int:
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as f:
        for line_number, row in enumerate(csv.DictReader(f), start=2):
            count += 1
            try:
                model.model_validate(row)
            except ValidationError as exc:
                errors.append(f"{path.name}:{line_number}: {exc.errors()[0]['msg']}")
                if len(errors) >= 50:
                    return count
    return count


def _parquet_mirror_errors(csv_rows: list[dict[str, str]], parquet_path: Path, id_field: str) -> list[str]:
    table = pq.read_table(parquet_path, columns=[id_field, "variable", "value"])
    parquet_rows = table.to_pylist()
    errors: list[str] = []
    if len(csv_rows) != len(parquet_rows):
        errors.append(f"{parquet_path}: CSV/Parquet row counts differ")
        return errors
    for index, (csv_row, parquet_row) in enumerate(zip(csv_rows, parquet_rows, strict=True), start=2):
        if csv_row[id_field] != parquet_row[id_field] or csv_row["variable"] != parquet_row["variable"]:
            errors.append(f"{parquet_path}:{index}: identifier/variable differs from CSV")
            break
        parquet_value = parquet_row["value"]
        if csv_row["value"]:
            if parquet_value is None or Decimal(csv_row["value"]) != Decimal(str(parquet_value)):
                errors.append(f"{parquet_path}:{index}: numeric value differs from CSV")
                break
        elif parquet_value is not None:
            errors.append(f"{parquet_path}:{index}: CSV blank differs from Parquet value")
            break
    return errors


def _page_table_errors(
    root: Path, page: str, expected_rows: int, dam_id_set: set[str], manifest: dict[str, dict[str, str]]
) -> list[str]:
    """Full page table: row count, key, dam IDs, manifest identity and Parquet mirror (keys and columns)."""
    csv_path = root / f"data/bulletin_page{page}.csv"
    parquet_path = root / f"data/parquet/bulletin_page{page}.parquet"
    rows = _rows(csv_path)
    errors: list[str] = []
    if len(rows) != expected_rows:
        errors.append(f"Expected {expected_rows} rows in {csv_path.name}, found {len(rows)}")
    keys = [(row["dam_id"], row["bulletin_date"]) for row in rows]
    if len(keys) != len(set(keys)):
        errors.append(f"{csv_path.name} contains duplicate dam_id/bulletin_date rows")
    if any(row["dam_id"] not in dam_id_set for row in rows):
        errors.append(f"{csv_path.name} contains dam_id outside data/dams.csv")
    for row in rows:
        entry = manifest.get(row["bulletin_date"], {})
        if (row["source_file"], row["source_sha256"]) != (entry.get(f"page{page}_source_file"), entry.get(f"page{page}_sha256")):
            errors.append(f"{csv_path.name}: {row['source_row_key']} does not match the manifest Page {page} file")
            break
    table = pq.read_table(parquet_path)
    with csv_path.open(encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    if table.schema.names != header:
        errors.append(f"{parquet_path.name} columns differ from {csv_path.name}")
    elif table.column("source_row_key").to_pylist() != [row["source_row_key"] for row in rows]:
        errors.append(f"{parquet_path.name} rows or order differ from {csv_path.name}")
    return errors


def validate_repository(root: Path) -> list[str]:
    errors: list[str] = []
    paths = {
        "dams": root / "data/dams.csv",
        "capacity": root / "data/capacity_history.csv",
        "manifest": root / "sources/manifest.csv",
        "storage": root / "data/storage.csv",
        "fill": root / "qa/printed_fill_reference.csv",
        "transfers": root / "data/transfers.csv",
    }
    counts = {
        "dams": _validate_models(paths["dams"], Dam, errors),
        "capacity": _validate_models(paths["capacity"], CapacityRegime, errors),
        "manifest": _validate_models(paths["manifest"], BulletinManifestRecord, errors),
        "storage": _validate_models(paths["storage"], StorageObservation, errors),
        "transfers": _validate_models(paths["transfers"], TransferObservation, errors),
    }
    if counts["dams"] != 36:
        errors.append(f"Expected 36 governed dams, found {counts['dams']}")
    if counts["manifest"] != 3985:
        errors.append(f"Expected 3985 canonical bulletins, found {counts['manifest']}")
    if counts["storage"] != 129390:
        errors.append(f"Expected 129390 primary storage observations, found {counts['storage']}")
    if counts["transfers"] != 47556:
        errors.append(f"Expected 47556 qualified Page 3 facts, found {counts['transfers']}")

    dams = _rows(paths["dams"])
    dam_ids = [row["dam_id"] for row in dams]
    if len(dam_ids) != len(set(dam_ids)):
        errors.append("data/dams.csv contains duplicate dam_id values")
    dam_id_set = set(dam_ids)

    storage = _rows(paths["storage"])
    if {row["variable"] for row in storage} != {"storage"}:
        errors.append("data/storage.csv is not storage-only")
    if any(row["dam_id"] not in dam_id_set for row in storage):
        errors.append("data/storage.csv contains dam_id outside data/dams.csv")

    fill = _rows(paths["fill"])
    if len(fill) != 84620:
        errors.append(f"Expected 84620 printed-fill observations, found {len(fill)}")
    if {row["variable"] for row in fill} != {"printed_fill_pct"}:
        errors.append("qa/printed_fill_reference.csv contains non-fill observations")
    if any(row["dam_id"] not in dam_id_set for row in fill):
        errors.append("qa/printed_fill_reference.csv contains unknown dam_id")

    numeric_lineage_ids = {
        row["observation_id"]
        for row in _rows(root / "provenance/storage_lineage.csv")
        if row["parser_state"] == "NUMERIC_PARSED"
    }
    packaged_ids = {row["observation_id"] for row in storage} | {row["observation_id"] for row in fill}
    if packaged_ids != numeric_lineage_ids:
        errors.append("E3 storage/fill split does not preserve the complete E2 numeric observation identity set")

    manifest = {row["bulletin_date"]: row for row in _rows(paths["manifest"])}
    errors.extend(_page_table_errors(root, "1", 129391, dam_id_set, manifest))
    errors.extend(_page_table_errors(root, "2", 129472, dam_id_set, manifest))
    stock = {row["source_row_key"]: row["p1_stock_today_mm3"] for row in _rows(root / "data/bulletin_page1.csv")}
    if any(stock.get(row["source_row_key"]) != row["value"] for row in storage):
        errors.append("data/bulletin_page1.csv stock column differs from data/storage.csv")

    transfers = _rows(paths["transfers"])
    if any("PROBABLE" not in row["authority_release"] for row in transfers):
        errors.append("Page 3 authority qualification was lost")

    errors.extend(_parquet_mirror_errors(storage, root / "data/parquet/storage.parquet", "observation_id"))
    errors.extend(_parquet_mirror_errors(fill, root / "qa/printed_fill_reference.parquet", "observation_id"))
    errors.extend(_parquet_mirror_errors(
        transfers, root / "data/parquet/transfers.parquet", "transfer_observation_id"
    ))

    if _sha256(root / "sources/file_manifest.csv") != E1_FILE_MANIFEST_SHA256:
        errors.append("sources/file_manifest.csv does not preserve accepted E1 bytes")
    v010_zip = optional("v010_review_zip")
    if v010_zip is not None and (not v010_zip.is_file() or _sha256(v010_zip) != V010_ZIP_SHA256):
        errors.append("Frozen V010 review ZIP is missing or changed")

    descriptor = json.loads((root / "datapackage.json").read_text(encoding="utf-8"))
    for resource in descriptor["resources"]:
        if not (root / resource["path"]).is_file():
            errors.append(f"datapackage resource missing: {resource['path']}")

    summary_path = root / "qa/qa_summary.json"
    report_path = root / "qa/report.md"
    if not summary_path.is_file() or not report_path.is_file():
        errors.append("QA summary/report was not generated")
    else:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        # E6A.2 replaced pooled KPI A with separate A1/A2/A3 audits and the A3B semantic review.
        if set(summary.get("kpis", {})) != {"A1", "A2", "A3", "A3B", "B", "C", "D", "E", "F", "G", "H"}:
            errors.append("qa_summary.json does not contain exactly KPIs A1-A3, A3B and B through H excluding satellite KPI I")
        report = report_path.read_text(encoding="utf-8")
        for key in ("A.", "B.", "C.", "D.", "E.", "F.", "G.", "H."):
            if key not in report:
                errors.append(f"qa/report.md omits KPI {key[0]}")
    return errors

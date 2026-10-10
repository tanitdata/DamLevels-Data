"""One-time E3 packaging migration over accepted E2 products.

This script separates the professor-facing storage table from its printed-fill
QA reference, projects accepted Page 1 grand-total evidence into local
provenance, and updates metadata. It does not run extraction.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from paths import external
from validate.quality import printed_decimal_places, read_csv, rounding_increment, write_csv


ROOT = Path(__file__).resolve().parents[1]
# Read from the configured location; provenance records the portable identifier.
CHECKSUM_VALIDATION_ID = "<FULL_RECONSTRUCTION>/data/extraction/page1/checksum_validation.csv.gz"
CHECKSUM_SOURCE_ID = "<FULL_RECONSTRUCTION>/data/extraction/page1/checksum_source.csv.gz"
CHECKSUM_VALIDATION_SHA256 = "313eaca331b5e1ca7c29adb5f9ae2eba98185790d2d63efeaaea7c4a477eec47"
CHECKSUM_SOURCE_SHA256 = "49ba32ec6fdbb4cc5e5dcd7f77d344664bed060d02b683a3c3009bafac65a951"
E2_STORAGE_SHA256 = "bcded2d533ca70e90f7df40862b5eb6af8727a328b6147bb65e39f77f266ff22"
E2_DATAPACKAGE_SHA256 = "33937905d6395fc87da8c689b5fcafb68a6e5d18e50ec7dc60952cf72a0441ef"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def split_storage_and_fill() -> tuple[int, int]:
    storage_path = ROOT / "data/storage.csv"
    fill_path = ROOT / "qa/printed_fill_reference.csv"
    rows = read_csv(storage_path)
    variables = {row["variable"] for row in rows}
    fields = list(rows[0])

    if variables == {"storage", "printed_fill_pct"}:
        if sha256(storage_path) != E2_STORAGE_SHA256:
            raise RuntimeError("Mixed E2 storage source differs from accepted E2 hash")
        storage_rows = [row for row in rows if row["variable"] == "storage"]
        fill_rows = [row for row in rows if row["variable"] == "printed_fill_pct"]
        if len(storage_rows) != 129390 or len(fill_rows) != 84620:
            raise RuntimeError("E2 storage/fill invariants do not match accepted counts")

        e2_table = pq.read_table(ROOT / "data/parquet/storage.parquet")
        storage_table = e2_table.filter(pc.equal(e2_table["variable"], "storage"))
        fill_table = e2_table.filter(pc.equal(e2_table["variable"], "printed_fill_pct"))

        write_csv(storage_path, fields, storage_rows)
        write_csv(fill_path, fields, fill_rows)
        pq.write_table(storage_table, ROOT / "data/parquet/storage.parquet", compression="zstd")
        pq.write_table(fill_table, ROOT / "qa/printed_fill_reference.parquet", compression="zstd")
    elif variables == {"storage"} and fill_path.is_file():
        storage_rows = rows
        fill_rows = read_csv(fill_path)
        if len(storage_rows) != 129390 or len(fill_rows) != 84620:
            raise RuntimeError("Previously split E3 counts do not match accepted E2 counts")
        if {row["variable"] for row in fill_rows} != {"printed_fill_pct"}:
            raise RuntimeError("Printed-fill reference contains another variable")
    else:
        raise RuntimeError(f"Unexpected storage packaging state: {sorted(variables)}")
    return len(storage_rows), len(fill_rows)


def project_national_totals() -> int:
    checksum_validation = external("page1_checksum_validation")
    checksum_source = external("page1_checksum_source")
    if sha256(checksum_validation) != CHECKSUM_VALIDATION_SHA256:
        raise RuntimeError("Accepted checksum-validation source hash changed")
    if sha256(checksum_source) != CHECKSUM_SOURCE_SHA256:
        raise RuntimeError("Accepted checksum-source artifact hash changed")

    manifest = read_csv(ROOT / "sources/manifest.csv")
    date_by_source: dict[tuple[str, str], str] = {}
    for row in manifest:
        files = row["page1_source_file"].split("|") if row["page1_source_file"] else []
        digests = row["page1_sha256"].split("|") if row["page1_sha256"] else []
        for source_file, digest in zip(files, digests, strict=True):
            date_by_source[(source_file, digest)] = row["bulletin_date"]

    raw_total: dict[tuple[str, str], str] = {}
    with gzip.open(checksum_source, "rt", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["checksum_scope"] != "GRAND_TOTAL" or row["region_or_total"] != "TOTAL":
                continue
            tokens = json.loads(row["raw_tokens"])
            raw_total[(row["source_filename"], row["source_sha256"])] = tokens.get("stock_today_mm3", "")

    projected: list[dict] = []
    with gzip.open(checksum_validation, "rt", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if not (
                row["checksum_scope"] == "GRAND_TOTAL"
                and row["region_or_total"] == "TOTAL"
                and row["field"] == "p1_stock_today_mm3"
            ):
                continue
            source_key = (row["source_filename"], row["source_sha256"])
            bulletin_date = date_by_source.get(source_key, "")
            if not bulletin_date:
                raise RuntimeError(f"National checksum source lacks canonical date: {source_key}")
            raw_printed = raw_total.get(source_key, "")
            places = printed_decimal_places(raw_printed or row["published_sum"])
            projected.append({
                "bulletin_id": f"BULLETIN-{bulletin_date}",
                "bulletin_date": bulletin_date,
                "source_file": row["source_filename"],
                "source_sha256": row["source_sha256"],
                "source_page": "1",
                "field": row["field"],
                "expected_contributors": row["expected_contributors"],
                "observed_contributors": row["observed_contributors"],
                "numeric_contributors": row["numeric_contributors"],
                "completeness": row["completeness"],
                "accepted_component_sum_mm3": row["computed_sum"],
                "printed_total_mm3": row["published_sum"],
                "raw_printed_total": raw_printed,
                "source_signed_residual_mm3": row["signed_residual"],
                "source_absolute_residual_mm3": row["absolute_residual"],
                "source_disposition": row["disposition"],
                "printed_decimal_places": places,
                "printed_increment_mm3": format(rounding_increment(places), "f"),
                "source_artifact": CHECKSUM_VALIDATION_ID,
                "source_artifact_sha256": CHECKSUM_VALIDATION_SHA256,
                "raw_source_artifact": CHECKSUM_SOURCE_ID,
                "raw_source_artifact_sha256": CHECKSUM_SOURCE_SHA256,
                "authority_release": "PAGE1_0.2.3_ACCEPTED_CHECKSUM_EVIDENCE",
            })
    projected.sort(key=lambda row: row["bulletin_date"])
    if len(projected) != 3981:
        raise RuntimeError(f"Expected 3981 accepted Page 1 national totals, found {len(projected)}")
    write_csv(
        ROOT / "provenance/page1_national_totals.csv",
        ["bulletin_id", "bulletin_date", "source_file", "source_sha256", "source_page", "field",
         "expected_contributors", "observed_contributors", "numeric_contributors", "completeness",
         "accepted_component_sum_mm3", "printed_total_mm3", "raw_printed_total",
         "source_signed_residual_mm3", "source_absolute_residual_mm3", "source_disposition",
         "printed_decimal_places", "printed_increment_mm3", "source_artifact", "source_artifact_sha256",
         "raw_source_artifact", "raw_source_artifact_sha256", "authority_release"],
        projected,
    )
    return len(projected)


def update_datapackage() -> None:
    path = ROOT / "datapackage.json"
    descriptor = json.loads(path.read_text(encoding="utf-8"))
    descriptor["name"] = "damlevels-data-e3-private"
    descriptor["title"] = "DamLevels-Data E3 private data and QA contract"
    descriptor["description"] = (
        "Private publication-gated primary storage, separate printed-fill reference, qualified Page 3 "
        "facts, capacity, identity, source manifests, and professor QA C-G outputs."
    )
    descriptor["version"] = "0.3.0-e3-private"

    by_name = {resource["name"]: resource for resource in descriptor["resources"]}
    for resource_name in ("storage", "storage-parquet"):
        resource = by_name[resource_name]
        resource["description"] = (
            "Primary Page 1 storage observations only; exactly one intended record per governed dam/date."
        )
        for field in resource["schema"]["fields"]:
            if field["name"] == "variable":
                field["description"] = "Constant primary quantity: storage."
                field["constraints"] = {"required": True, "enum": ["storage"]}

    fill_schema = deepcopy(by_name["storage"]["schema"])
    for field in fill_schema["fields"]:
        if field["name"] == "variable":
            field["description"] = "Constant non-primary QA quantity: printed_fill_pct."
            field["constraints"] = {"required": True, "enum": ["printed_fill_pct"]}
        elif field["name"] == "value":
            field["description"] = "Fill percentage printed in the source bulletin; never recomputed or repaired."
            field["unit"] = "percent"
    fill_resource = {
        "name": "printed-fill-reference",
        "path": "qa/printed_fill_reference.csv",
        "profile": "tabular-data-resource",
        "description": "Non-primary printed fill percentages retained for professor QA check E.",
        "schema": fill_schema,
    }
    fill_parquet = deepcopy(fill_resource)
    fill_parquet["name"] = "printed-fill-reference-parquet"
    fill_parquet["path"] = "qa/printed_fill_reference.parquet"
    fill_parquet["profile"] = "data-resource"
    descriptor["resources"] = [
        resource for resource in descriptor["resources"]
        if resource["name"] not in {"printed-fill-reference", "printed-fill-reference-parquet"}
    ] + [fill_resource, fill_parquet]
    path.write_text(json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_engineering_changes() -> None:
    path = ROOT / "provenance/ENGINEERING_CHANGES.csv"
    rows = read_csv(path)
    existing = {row["change_id"] for row in rows}
    storage_hash = sha256(ROOT / "data/storage.csv")
    fill_hash = sha256(ROOT / "qa/printed_fill_reference.csv")
    national_hash = sha256(ROOT / "provenance/page1_national_totals.csv")
    datapackage_hash = sha256(ROOT / "datapackage.json")
    additions = [
        {
            "change_id": "E3-CHG-001", "date": "2026-09-24", "component": "Primary storage packaging",
            "relation": "PACKAGING_ONLY", "old_artifact": "E2 data/storage.csv (storage plus printed_fill_pct)",
            "new_artifact": "data/storage.csv;qa/printed_fill_reference.csv",
            "reason": "Align professor-facing storage uniqueness contract to storage-only dam/date observations while preserving printed percentages separately.",
            "producer": "src/build_e3.py", "audit": "qa/E3_VALIDATION_REPORT.md",
            "hash_before": E2_STORAGE_SHA256, "hash_after": f"{storage_hash}|{fill_hash}",
        },
        {
            "change_id": "E3-CHG-002", "date": "2026-09-24", "component": "Page 1 national-total evidence",
            "relation": "PROJECTS", "old_artifact": CHECKSUM_VALIDATION_ID,
            "new_artifact": "provenance/page1_national_totals.csv",
            "reason": "Project accepted independently printed Page 1 grand totals and source residual evidence into repository-local QA provenance.",
            "producer": "src/build_e3.py", "audit": "qa/national_reconciliation.csv",
            "hash_before": CHECKSUM_VALIDATION_SHA256, "hash_after": national_hash,
        },
        {
            "change_id": "E3-CHG-003", "date": "2026-09-24", "component": "Pydantic and professor QA contracts",
            "relation": "EXTENDS", "old_artifact": "E2 standard-library structural validation",
            "new_artifact": "src/validate/models.py;src/validate/quality.py;qa/qa_summary.json;qa/report.md",
            "reason": "Add typed row contracts and reproducible checks C through G without rerunning scientific extraction.",
            "producer": "src/build.py", "audit": "qa/E3_VALIDATION_REPORT.md",
            "hash_before": "E2_STRUCTURAL_CONTRACT", "hash_after": "SEE_GIT_E3_COMMIT",
        },
        {
            "change_id": "E3-CHG-004", "date": "2026-09-24", "component": "Data package contract",
            "relation": "EXTENDS", "old_artifact": "datapackage.json at E2",
            "new_artifact": "datapackage.json at E3",
            "reason": "Register storage-only authority and separate printed-fill CSV/Parquet QA references.",
            "producer": "src/build_e3.py", "audit": "qa/E3_VALIDATION_REPORT.md",
            "hash_before": E2_DATAPACKAGE_SHA256, "hash_after": datapackage_hash,
        },
    ]
    rows.extend(row for row in additions if row["change_id"] not in existing)
    write_csv(path, list(rows[0]), rows)


def main() -> None:
    storage_count, fill_count = split_storage_and_fill()
    national_count = project_national_totals()
    update_datapackage()
    append_engineering_changes()
    print(
        f"E3 packaging complete: storage={storage_count}, printed_fill={fill_count}, "
        f"national_totals={national_count}"
    )


if __name__ == "__main__":
    main()

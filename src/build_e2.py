"""Build the E2 public-format data contract from accepted frozen products.

This is an engineering packaging transformation. It does not execute PDF
extraction, scientific audits, watershed/climate pipelines, features, or models.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from paths import REPO, optional, portable


# Defaults come from config/paths.local.toml; command-line options override them.
DEFAULT_REPO = REPO
DEFAULT_REVIEW = optional("review_package_dir")
DEFAULT_FULL = optional("full_reconstruction_dir")
DEFAULT_V010 = optional("v010_baseline_dir")
DEFAULT_P1_LINEAGE = optional("page1_value_lineage")
E1_FILE_MANIFEST_SHA256 = "2debc06e3532edaca2b2d78bb30f8933d0b41a4e85fe835817b226aced9ebb14"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def parse_filename_date(filename: str) -> str:
    stem = Path(filename).stem
    match = re.match(r"^(\d{1,2})[-_](\d{1,2})[-_](\d{4})(?:[_-]\d+)?$", stem)
    if not match:
        return ""
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
    except ValueError:
        return ""


def file_snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)).replace("\\", "/"): sha256(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def make_observation_id(source_sha: str, dam_id: str, day: str, source_field: str) -> str:
    token = f"{source_sha}|{dam_id}|{day}|{source_field}".encode("utf-8")
    return "STO-" + hashlib.sha256(token).hexdigest()[:24]


def clean_float_text(value: str) -> str:
    # Accepted extraction outputs already use dot-decimal normalized values.
    number = float(value)
    return format(number, ".15g")


def load_source_inventory_gzip(path: Path, filename_field: str) -> dict[str, set[tuple[str, str]]]:
    inventory: dict[str, set[tuple[str, str]]] = defaultdict(set)
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            inventory[row["bulletin_date"]].add((row[filename_field], row["source_sha256"]))
    return inventory


def singleton_or_join(items: set[tuple[str, str]]) -> tuple[str, str, bool]:
    if not items:
        return "", "", False
    ordered = sorted(items)
    return "|".join(x[0] for x in ordered), "|".join(x[1] for x in ordered), len(ordered) > 1


def build_canonical_manifest(
    file_manifest_rows: list[dict[str, str]],
    p1_obs: Path,
    p2_obs: Path,
    p3_facts: Path,
) -> tuple[list[dict], list[dict], dict]:
    p1 = load_source_inventory_gzip(p1_obs, "source_filename")
    p2 = load_source_inventory_gzip(p2_obs, "source_file")
    p3: dict[str, set[tuple[str, str]]] = defaultdict(set)
    table = pq.read_table(p3_facts, columns=["source_file", "source_sha256", "bulletin_date"])
    for row in table.to_pylist():
        p3[str(row["bulletin_date"])].add((str(row["source_file"]), str(row["source_sha256"])))

    all_dates = sorted(set(p1) | set(p2) | set(p3))
    canonical: list[dict] = []
    inventory_by_page = {"1": p1, "2": p2, "3": p3}
    accepted_pairs = {
        (filename, digest)
        for inv in inventory_by_page.values()
        for entries in inv.values()
        for filename, digest in entries
    }
    manifest_pairs = {(Path(r["source_file"]).name, r["sha256"]) for r in file_manifest_rows}
    accepted_unmatched = sorted(accepted_pairs - manifest_pairs)

    availability = Counter()
    filename_date_mismatches: list[tuple[str, str, str]] = []
    multi_source_dates = 0
    for day in all_dates:
        p1_file, p1_hash, p1_multi = singleton_or_join(p1.get(day, set()))
        p2_file, p2_hash, p2_multi = singleton_or_join(p2.get(day, set()))
        p3_file, p3_hash, p3_multi = singleton_or_join(p3.get(day, set()))
        if p1_multi or p2_multi or p3_multi:
            multi_source_dates += 1
        pages = [page for page, filename in (("1", p1_file), ("2", p2_file), ("3", p3_file)) if filename]
        availability[tuple(pages)] += 1
        notes: list[str] = []
        for page, filename in (("1", p1_file), ("2", p2_file), ("3", p3_file)):
            for individual in filename.split("|") if filename else []:
                filename_date = parse_filename_date(individual)
                if filename_date and filename_date != day:
                    filename_date_mismatches.append((page, individual, day))
                    notes.append(
                        f"Page {page} filename date {filename_date} differs from accepted bulletin_date {day}; both retained."
                    )
        if len(pages) < 3:
            notes.append("Partial accepted source inventory; missing page support is not imputed.")
        if p3_file:
            notes.append("Page 3 presence is from the selected canonical release and remains PROBABLE authority.")
        canonical.append({
            "bulletin_id": f"BULLETIN-{day}",
            "bulletin_date": day,
            "original_url": "",
            "page1_source_file": p1_file,
            "page1_sha256": p1_hash,
            "page2_source_file": p2_file,
            "page2_sha256": p2_hash,
            "page3_source_file": p3_file,
            "page3_sha256": p3_hash,
            "pages_available": "|".join(pages),
            "status": "COMPLETE_THREE_PAGE_INVENTORY" if len(pages) == 3 else "PARTIAL_PAGE_INVENTORY",
            "provenance_status": "|".join(
                status for status, present in (
                    ("PAGE1_CURRENT_ACCEPTED", bool(p1_file)),
                    ("PAGE2_CURRENT_ACCEPTED", bool(p2_file)),
                    ("PAGE3_CURRENT_CANDIDATE_PROBABLE", bool(p3_file)),
                ) if present
            ),
            "notes": " ".join(notes),
        })

    accepted_dates = set(all_dates)
    unresolved: list[dict] = []
    for row in file_manifest_rows:
        day = row["bulletin_date"]
        if not day:
            unresolved.append({
                "source_file": row["source_file"], "sha256": row["sha256"],
                "status": "UNCANONICALIZED_NO_SUPPORTED_DATE",
                "reason": "Filename/date parser did not establish a bulletin date; backup evidence remains in file_manifest.csv.",
            })
        elif day not in accepted_dates:
            unresolved.append({
                "source_file": row["source_file"], "sha256": row["sha256"],
                "status": "PARSED_DATE_NOT_IN_ACCEPTED_SOURCE_INVENTORIES",
                "reason": f"Parsed date {day} has no Page 1, Page 2, or selected Page 3 inventory record.",
            })
    for filename, digest in accepted_unmatched:
        unresolved.append({
            "source_file": filename, "sha256": digest,
            "status": "ACCEPTED_SOURCE_NOT_MATCHED_TO_FILE_MANIFEST",
            "reason": "Accepted extractor source identity was not matched by filename and SHA-256 to the preserved E1 path inventory.",
        })

    stats = {
        "canonical_bulletins": len(canonical),
        "complete_three_pages": availability.get(("1", "2", "3"), 0),
        "partial_bulletins": len(canonical) - availability.get(("1", "2", "3"), 0),
        "page1_dates": len(p1), "page2_dates": len(p2), "page3_dates": len(p3),
        "multi_source_dates": multi_source_dates,
        "filename_date_mismatches": filename_date_mismatches,
        "unresolved_file_records": len(unresolved),
        "accepted_source_pairs_unmatched": len(accepted_unmatched),
        "availability": {"|".join(k): v for k, v in availability.items()},
    }
    return canonical, unresolved, stats


def build_lineage_index(lineage_path: Path) -> tuple[dict[tuple[str, str, str], list[dict]], dict]:
    selected: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    total = 0
    retained = 0
    fields = {"p1_stock_today_mm3", "p1_stock_fill_pct"}
    with gzip.open(lineage_path, "rt", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            total += 1
            source_field = row.get("canonical_semantic_field", "")
            if source_field not in fields:
                continue
            retained += 1
            key = (row["source_filename"], row["canonical_dam_id"], source_field)
            selected[key].append({
                "lineage_id": row["lineage_id"],
                "source_sha256": row["source_sha256"],
                "physical_column": row["physical_column"],
                "cell_bbox": row["cell_bbox"],
                "raw_glyph_sequence": row["raw_glyph_sequence"],
                "normalization_method": row["normalization_method"],
                "parser_state": row["parser_state"],
                "parsed_numeric_value": row["parsed_numeric_value"],
                "incident_status": row["incident_status"],
                "review_status": row["review_status"],
                "checksum_validation_reference": row["checksum_validation_reference"],
            })
    return selected, {
        "lineage_rows_scanned": total,
        "lineage_rows_retained": retained,
        "duplicate_lineage_keys": sum(len(v) > 1 for v in selected.values()),
    }


def build_storage(
    p1_obs: Path,
    lineage_index: dict[tuple[str, str, str], list[dict]],
) -> tuple[list[dict], list[dict], list[dict], dict[str, list[str]], dict]:
    storage_rows: list[dict] = []
    lineage_rows: list[dict] = []
    missing_rows: list[dict] = []
    storage_dates: dict[str, list[str]] = defaultdict(list)
    source_nonblank = Counter()
    source_blank = Counter()
    lineage_status = Counter()
    source_rows = 0
    dam_ids = set()
    date_min = None
    date_max = None
    field_map = (
        ("p1_stock_today_mm3", "storage", "Mm3"),
        ("p1_stock_fill_pct", "printed_fill_pct", "percent"),
    )
    with gzip.open(p1_obs, "rt", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            source_rows += 1
            dam_id = row["canonical_dam_id"]
            day = row["bulletin_date"]
            dam_ids.add(dam_id)
            date_min = day if date_min is None or day < date_min else date_min
            date_max = day if date_max is None or day > date_max else date_max
            for source_field, variable, unit in field_map:
                raw_value = row.get(source_field, "").strip()
                obs_id = make_observation_id(row["source_sha256"], dam_id, day, source_field)
                key = (row["source_filename"], dam_id, source_field)
                lineages = lineage_index.get(key, [])
                if not raw_value:
                    source_blank[variable] += 1
                    missing_rows.append({
                        "observation_id": obs_id, "dam_id": dam_id, "date": day,
                        "variable": variable, "source_file": row["source_filename"],
                        "source_sha256": row["source_sha256"], "page": row["physical_page"],
                        "source_field": source_field,
                        "lineage_id": "|".join(sorted(x["lineage_id"] for x in lineages)),
                        "parser_state": "|".join(sorted({x["parser_state"] for x in lineages if x["parser_state"]})),
                        "raw_glyph_sequence": "|".join(x["raw_glyph_sequence"] for x in lineages if x["raw_glyph_sequence"]),
                        "flag": "SOURCE_FIELD_MISSING_NO_IMPUTATION",
                        "notes": "No observation row emitted; no interpolation or forward fill performed.",
                    })
                    for item in lineages:
                        lineage_rows.append({
                            "observation_id": obs_id, "lineage_id": item["lineage_id"],
                            "source_field": source_field, "physical_column": item["physical_column"],
                            "cell_bbox": item["cell_bbox"], "raw_glyph_sequence": item["raw_glyph_sequence"],
                            "normalization_method": item["normalization_method"], "parser_state": item["parser_state"],
                            "parsed_numeric_value": item["parsed_numeric_value"],
                            "incident_status": item["incident_status"], "review_status": item["review_status"],
                            "checksum_validation_reference": item["checksum_validation_reference"],
                            "link_status": "LINKED_SOURCE_STATE_NO_NUMERIC_OBSERVATION",
                        })
                    continue
                try:
                    value = clean_float_text(raw_value)
                except ValueError:
                    source_blank[variable] += 1
                    missing_rows.append({
                        "observation_id": obs_id, "dam_id": dam_id, "date": day,
                        "variable": variable, "source_file": row["source_filename"],
                        "source_sha256": row["source_sha256"], "page": row["physical_page"],
                        "source_field": source_field, "flag": "SOURCE_FIELD_NON_NUMERIC_NO_IMPUTATION",
                        "notes": f"Accepted observation contained non-numeric normalized text {raw_value!r}; no value emitted.",
                    })
                    continue
                source_nonblank[variable] += 1
                flags = ["ACCEPTED_PAGE1_OBSERVATION"]
                if variable == "printed_fill_pct":
                    flags.append("PRINTED_QC_VALUE_NON_PRIMARY")
                if not lineages:
                    flags.append("LINEAGE_NOT_LINKED")
                    lineage_id = ""
                    lineage_status["MISSING"] += 1
                elif len(lineages) == 1:
                    lineage_id = lineages[0]["lineage_id"]
                    flags.append("LINEAGE_LINKED")
                    lineage_status["LINKED"] += 1
                    if lineages[0]["incident_status"] not in ("", "NONE"):
                        flags.append(f"INCIDENT_{lineages[0]['incident_status']}")
                    if lineages[0]["review_status"] not in ("", "NONE"):
                        flags.append(f"REVIEW_{lineages[0]['review_status']}")
                else:
                    lineage_id = "|".join(sorted(x["lineage_id"] for x in lineages))
                    flags.append("MULTIPLE_LINEAGE_RECORDS")
                    lineage_status["MULTIPLE"] += 1
                storage_rows.append({
                    "observation_id": obs_id,
                    "dam_id": dam_id,
                    "date": day,
                    "variable": variable,
                    "value": value,
                    "unit": unit,
                    "source_file": row["source_filename"],
                    "source_sha256": row["source_sha256"],
                    "page": row["physical_page"],
                    "source_field": source_field,
                    "authority_release": "PAGE1_0.2.3_CURRENT_EXTRACTION_DELIVERY",
                    "engine_version": row["engine_version"],
                    "source_row_key": row["output_row_key"],
                    "lineage_id": lineage_id,
                    "flag": "|".join(flags),
                })
                if variable == "storage":
                    storage_dates[dam_id].append(day)
                if not lineages:
                    lineage_rows.append({
                        "observation_id": obs_id, "lineage_id": "", "source_field": source_field,
                        "physical_column": "", "cell_bbox": "", "raw_glyph_sequence": "",
                        "normalization_method": "", "parser_state": "", "parsed_numeric_value": "",
                        "incident_status": "", "review_status": "", "checksum_validation_reference": "",
                        "link_status": "LINEAGE_NOT_LINKED",
                    })
                else:
                    for item in lineages:
                        lineage_rows.append({
                            "observation_id": obs_id, "lineage_id": item["lineage_id"],
                            "source_field": source_field, "physical_column": item["physical_column"],
                            "cell_bbox": item["cell_bbox"], "raw_glyph_sequence": item["raw_glyph_sequence"],
                            "normalization_method": item["normalization_method"], "parser_state": item["parser_state"],
                            "parsed_numeric_value": item["parsed_numeric_value"],
                            "incident_status": item["incident_status"], "review_status": item["review_status"],
                            "checksum_validation_reference": item["checksum_validation_reference"],
                            "link_status": "LINKED_UNIQUE" if len(lineages) == 1 else "LINKED_MULTIPLE",
                        })
    stats = {
        "page1_source_rows": source_rows,
        "storage_rows": len(storage_rows),
        "primary_storage_rows": source_nonblank["storage"],
        "printed_fill_rows": source_nonblank["printed_fill_pct"],
        "storage_missing_source_rows": source_blank["storage"],
        "printed_fill_missing_source_rows": source_blank["printed_fill_pct"],
        "storage_date_min": date_min,
        "storage_date_max": date_max,
        "storage_dams": len(dam_ids),
        "lineage_status": dict(lineage_status),
    }
    return storage_rows, lineage_rows, missing_rows, storage_dates, stats


def node_to_confirmed_dam(node: str) -> tuple[str, str]:
    mapping = {
        "NODE-DAM-BARBARA": ("barbara", "CONFIRMED_EXACT_NODE_CROSSWALK"),
        "NODE-DAM-SIDI-EL-BARRAK": ("sidielbarrak", "CONFIRMED_EXACT_NODE_CROSSWALK"),
        "NODE-DAM-SEJNANE": ("sejnane", "CONFIRMED_EXACT_NODE_CROSSWALK"),
        # The Page 3 roster explicitly leaves these crosswalks as candidates.
        "NODE-DAM-BOUHERTMA": ("", "CANDIDATE_BOUHERTMA_TO_BOUHEURTMA_NOT_PROMOTED"),
        "NODE-DAM-ZAYATIN": ("", "CANDIDATE_ZAYATIN_TO_ZIATINE_NOT_PROMOTED"),
        "": ("", "NOT_APPLICABLE"),
    }
    return mapping.get(node, ("", "UNMAPPED_NODE"))


def build_transfers(p3_transfer: Path) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    semantic_counts = Counter()
    value_status_counts = Counter()
    table = pq.read_table(p3_transfer)
    for source in table.to_pylist():
        from_node = source.get("from_node") or ""
        to_node = source.get("to_node") or ""
        from_dam, from_map_status = node_to_confirmed_dam(from_node)
        to_dam, to_map_status = node_to_confirmed_dam(to_node)
        row_role = str(source.get("row_role") or "")
        if row_role == "ACCOUNTING_OBSERVATION":
            semantic_status = "PROBABLE_ACCOUNTING_OBSERVATION_NOT_HYDRAULIC_EDGE"
        elif not from_dam or not to_dam:
            semantic_status = "PROBABLE_PHYSICAL_EDGE_WITH_UNRESOLVED_DAM_CROSSWALK"
        else:
            semantic_status = "PROBABLE_PHYSICAL_TRANSFER_EDGE"
        semantic_counts[semantic_status] += 1
        value_status = str(source.get("value_status") or "")
        value_status_counts[value_status] += 1
        flags = ["PAGE3_PROBABLE", value_status, str(source.get("quality_flag") or "")]
        if str(source.get("source_consistency_status") or "") == "NOT_CHECKED":
            flags.append("SOURCE_CONSISTENCY_NOT_CHECKED")
        if to_node == "NODE-DAM-SEJNANE" or row_role == "ACCOUNTING_OBSERVATION":
            flags.append("SEJNANE_SOURCE_LABEL_REGIME_LIMITATION")
        if from_node and not from_dam:
            flags.append("UNRESOLVED_FROM_DAM_CROSSWALK")
        if to_node and not to_dam:
            flags.append("UNRESOLVED_TO_DAM_CROSSWALK")
        if row_role == "ACCOUNTING_OBSERVATION":
            flags.append("ACCOUNTING_NOT_PHYSICAL_FLOW")
        # Preserve the selected product's date fields exactly. The accompanying
        # contract text says transfer day values may be minus-one-day, while this
        # product records SAME_DAY; E2 discloses the discrepancy and does not fix it.
        flags.append("EFFECTIVE_DATE_RULE_AS_PUBLISHED")
        value = source.get("value")
        rows.append({
            "transfer_observation_id": source["page3_fact_id"],
            "date": source.get("effective_observation_date") or "",
            "bulletin_date": source.get("bulletin_date") or "",
            "effective_date_rule": source.get("effective_date_rule") or "",
            "from_dam_id": from_dam,
            "to_dam_id": to_dam,
            "from_node_id": from_node,
            "to_node_id": to_node,
            "from_mapping_status": from_map_status,
            "to_mapping_status": to_map_status,
            "entity_id": source.get("entity_id") or "",
            "row_role": row_role,
            "variable": source.get("measure_id") or "",
            "value": "" if value is None else format(float(value), ".15g"),
            "unit": "Mm3" if str(source.get("unit") or "").lower() == "mm3" else (source.get("unit") or ""),
            "source_file": source.get("source_file") or "",
            "source_sha256": source.get("source_sha256") or "",
            "page": "3",
            "source_field": source.get("canonical_field_id") or "",
            "authority_release": "PAGE3_SELECTED_RELEASE_PROBABLE",
            "flag": "|".join(x for x in flags if x),
            "semantic_status": semantic_status,
            "value_status": value_status,
            "continuity_status": source.get("continuity_status") or "",
            "source_consistency_status": source.get("source_consistency_status") or "",
            "evidence_id": source.get("evidence_id") or "",
            "record_id": source.get("record_id") or "",
            "series_id": source.get("series_id") or "",
            "raw_text": source.get("raw_text") or "",
        })
    return rows, {
        "transfer_rows": len(rows),
        "semantic_categories": dict(semantic_counts),
        "value_statuses": dict(value_status_counts),
        "date_min": min(r["date"] for r in rows if r["date"]),
        "date_max": max(r["date"] for r in rows if r["date"]),
    }


def update_dams(dams_path: Path, review: Path) -> tuple[list[dict], dict]:
    rows = read_csv(dams_path)
    roster_source = review / "src/extraction/page3_extractor/contracts/registries/p3_t2_roster_registry.csv"
    medjerda_source = review / "references/catalogues/CORE_THESIS_REFERENCES.csv#WEB-MINENV-MEDJERDA"
    explicitly_supported_medjerda = {"mellegue", "bouheurtma", "ghezala", "kasseb", "siliana", "lakhmess"}
    for row in rows:
        if row.get("name_ar"):
            row["name_ar_source"] = portable(str(roster_source))
            if row["dam_id"] in {"bouheurtma", "ziatine"}:
                row["name_ar_status"] = "CANDIDATE_CROSSWALK_PAGE3_ROSTER"
            elif row["dam_id"] == "hma":
                row["name_ar_status"] = "CANDIDATE_PENDING_HUMAN_CONFIRMATION"
        else:
            row["name_ar_status"] = "UNAVAILABLE"
            row["name_ar_source"] = ""
        if row["dam_id"] in explicitly_supported_medjerda:
            row["basin"] = "Medjerda"
            row["basin_status"] = "SUPPORTED_OFFICIAL_BASIN_CONTEXT"
            row["basin_source"] = portable(str(medjerda_source))
        else:
            row["basin"] = ""
            row["basin_status"] = "UNAVAILABLE_NOT_INFERRED"
            row["basin_source"] = ""
    return rows, {
        "missing_arabic": sum(not r.get("name_ar") for r in rows),
        "missing_basin": sum(not r.get("basin") for r in rows),
        "basin_filled": sum(bool(r.get("basin")) for r in rows),
    }


def capacity_unknown_periods(
    capacity_rows: list[dict[str, str]], storage_dates: dict[str, list[str]]
) -> list[dict]:
    by_dam: dict[str, list[dict]] = defaultdict(list)
    for row in capacity_rows:
        by_dam[row["dam_id"]].append(row)
    unknown: list[dict] = []
    for dam_id, days in sorted(storage_dates.items()):
        first_storage = date.fromisoformat(min(days))
        last_storage = date.fromisoformat(max(days))
        regimes = sorted(by_dam.get(dam_id, []), key=lambda r: r["valid_from"])
        boundaries = {first_storage, last_storage + timedelta(days=1)}
        for regime in regimes:
            start = max(first_storage, date.fromisoformat(regime["valid_from"]))
            raw_end = date.fromisoformat(regime["valid_to"]) if regime["valid_to"] else last_storage
            end = min(last_storage, raw_end)
            if start <= last_storage:
                boundaries.add(start)
            if end < last_storage:
                boundaries.add(end + timedelta(days=1))
        points = sorted(boundaries)
        observed_days = {date.fromisoformat(x) for x in days}
        for start, stop in zip(points, points[1:]):
            end = stop - timedelta(days=1)
            if start > last_storage or end < first_storage:
                continue
            probe = start
            matches = []
            for regime in regimes:
                regime_start = date.fromisoformat(regime["valid_from"])
                regime_end = date.fromisoformat(regime["valid_to"]) if regime["valid_to"] else date.max
                if regime_start <= probe <= regime_end:
                    matches.append(regime)
            if len(matches) == 1:
                continue
            status = "AMBIGUOUS" if len(matches) > 1 else "UNAVAILABLE"
            obs_count = sum(start <= d <= end for d in observed_days)
            unknown.append({
                "dam_id": dam_id, "valid_from": start.isoformat(), "valid_to": end.isoformat(),
                "status": status, "storage_observation_count": obs_count,
                "reason": "No unique evidence-backed capacity regime applies; no forward fill performed.",
            })
    return unknown


def write_parquet_from_rows(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = {field: [row.get(field, "") for row in rows] for field in fields}
    # Convert only the public numeric value column to nullable float64.
    if "value" in columns:
        columns["value"] = [None if v == "" else float(v) for v in columns["value"]]
    table = pa.table(columns)
    pq.write_table(table, path, compression="zstd")


def datapackage_descriptor() -> dict:
    dams_fields = [
        ("dam_id", "string", "Stable governed dam identifier."),
        ("name_fr", "string", "Governed French/canonical name."),
        ("name_ar", "string", "Evidence-backed Arabic name where established."),
        ("name_ar_status", "string", "Authority or candidate status of the Arabic-name mapping."),
        ("name_ar_source", "string", "Evidence locator for the Arabic name."),
        ("aliases", "string", "Pipe-separated governed historical aliases."),
        ("basin", "string", "Hydrographic basin only where explicitly supported."),
        ("basin_status", "string", "Evidence status of basin assignment."),
        ("basin_source", "string", "Evidence locator for basin assignment."),
        ("reference_capacity_mm3", "number", "Latest durable observed Page 2 capacity regime."),
        ("capacity_valid_from", "date", "Start of latest observed capacity regime."),
        ("latitude", "number", "Accepted control latitude, EPSG:4326."),
        ("longitude", "number", "Accepted control longitude, EPSG:4326."),
        ("status", "string", "Task21 row status."),
        ("geometry_status", "string", "Task21 geometry status."),
        ("control_status", "string", "Task21 control-point status."),
        ("identity_source", "string", "Identity evidence path."),
        ("coordinate_source", "string", "Coordinate evidence path and transform."),
        ("capacity_source", "string", "Capacity evidence path."),
        ("notes", "string", "Row limitations."),
    ]
    capacity_fields = [
        ("dam_id", "string", "Stable governed dam identifier."),
        ("valid_from", "date", "First supported date, inclusive."),
        ("valid_to", "date", "Last supported date, inclusive; blank means current observed regime."),
        ("capacity_mm3", "number", "Printed Page 2 capacity in Mm3."),
        ("source", "string", "Source product."), ("source_file", "string", "First supporting bulletin file."),
        ("page", "integer", "Logical bulletin page."), ("status", "string", "Regime evidence status."),
        ("notes", "string", "Observation support and explicit conflicts."),
    ]
    canonical_fields = [
        ("bulletin_id", "string", "Stable logical bulletin identifier."), ("bulletin_date", "date", "Accepted bulletin date."),
        ("original_url", "string", "Original URL where established; otherwise blank."),
        ("page1_source_file", "string", "Accepted Page 1 source filename."), ("page1_sha256", "string", "Page 1 SHA-256."),
        ("page2_source_file", "string", "Accepted Page 2 source filename."), ("page2_sha256", "string", "Page 2 SHA-256."),
        ("page3_source_file", "string", "Selected Page 3 source filename."), ("page3_sha256", "string", "Page 3 SHA-256."),
        ("pages_available", "string", "Pipe-separated logical pages supported by accepted inventories."),
        ("status", "string", "Complete or partial page-set status."),
        ("provenance_status", "string", "Page-specific authority statuses."), ("notes", "string", "Manifest limitations."),
    ]
    file_fields = [
        ("source_file", "string", "Path relative to the external bulletin root."),
        ("bulletin_date", "date", "Filename-supported bulletin date where parsed."),
        ("original_url", "string", "Original URL where established; otherwise blank."),
        ("sha256", "string", "Physical file SHA-256 from the frozen manifest."),
        ("page_count", "integer", "Split-branch page count where established."),
        ("status", "string", "Physical manifest status."),
        ("local_source_status", "string", "Local path validation status from E1."),
        ("notes", "string", "Physical-file limitations."),
    ]
    storage_fields = [
        ("observation_id", "string", "Stable source-derived observation identifier."),
        ("dam_id", "string", "Stable governed dam identifier."), ("date", "date", "Bulletin reporting date."),
        ("variable", "string", "storage or non-primary printed_fill_pct."),
        ("value", "number", "Observed numeric value; never interpolated."), ("unit", "string", "Mm3 or percent."),
        ("source_file", "string", "Source PDF filename."), ("source_sha256", "string", "Source PDF SHA-256."),
        ("page", "integer", "Physical/logical source page."), ("source_field", "string", "Accepted extractor source field."),
        ("authority_release", "string", "Use-specific extraction authority."),
        ("engine_version", "string", "Extractor engine version."),
        ("source_row_key", "string", "Accepted extraction row key."), ("lineage_id", "string", "Linked cell-lineage identifier(s)."),
        ("flag", "string", "Pipe-separated row-level authority/QC flags."),
    ]
    transfer_fields = [
        ("transfer_observation_id", "string", "Selected Page 3 canonical fact ID."),
        ("date", "date", "Effective observation date as published in the selected product."),
        ("bulletin_date", "date", "Bulletin date."), ("effective_date_rule", "string", "Date rule recorded by the selected product."),
        ("from_dam_id", "string", "Confirmed stable source dam ID; blank if unproven/not applicable."),
        ("to_dam_id", "string", "Confirmed stable destination dam ID; blank if unproven/not applicable."),
        ("from_node_id", "string", "Page 3 source node identity."), ("to_node_id", "string", "Page 3 destination node identity."),
        ("from_mapping_status", "string", "Stable-ID crosswalk status."), ("to_mapping_status", "string", "Stable-ID crosswalk status."),
        ("entity_id", "string", "Page 3 route/accounting entity."), ("row_role", "string", "Physical edge or accounting observation."),
        ("variable", "string", "Reported Page 3 measure."), ("value", "number", "Reported value; blank states remain blank."),
        ("unit", "string", "Reported unit normalized to Mm3."), ("source_file", "string", "Source PDF filename."),
        ("source_sha256", "string", "Source PDF SHA-256."), ("page", "integer", "Logical page 3."),
        ("source_field", "string", "Canonical Page 3 field ID."), ("authority_release", "string", "Qualified Page 3 authority."),
        ("flag", "string", "Pipe-separated qualification/QC flags."),
        ("semantic_status", "string", "Physical-edge/accounting and crosswalk qualification."),
        ("value_status", "string", "Numeric/zero/blank/structural state."),
        ("continuity_status", "string", "Selected Page 3 continuity status."),
        ("source_consistency_status", "string", "Selected source-consistency status."),
        ("evidence_id", "string", "Page 3 evidence ID."), ("record_id", "string", "Page 3 record ID."),
        ("series_id", "string", "Audited Page 3 series ID."), ("raw_text", "string", "Source-normalized raw text."),
    ]

    def fields(items):
        result = []
        for name, field_type, description in items:
            field = {"name": name, "type": field_type, "description": description}
            if name in {"reference_capacity_mm3", "capacity_mm3"}:
                field["unit"] = "Mm3"
            result.append(field)
        return result

    storage_schema = {"primaryKey": "observation_id", "foreignKeys": [{"fields": "dam_id", "reference": {"resource": "dams", "fields": "dam_id"}}], "fields": fields(storage_fields)}
    transfer_schema = {"primaryKey": "transfer_observation_id", "fields": fields(transfer_fields)}
    return {
        "profile": "tabular-data-package",
        "name": "damlevels-data-e2-private",
        "title": "DamLevels-Data E2 private core data contract",
        "description": "Private publication-gated storage, qualified Page 3 transfer/accounting, capacity, dam identity, and source-manifest package.",
        "version": "0.2.0-e2-private",
        "licenses": [
            {"name": "PENDING-CODE", "path": "LICENSE", "title": "Draft proposed MIT; approval pending"},
            {"name": "PENDING-DATA", "path": "LICENSE-DATA", "title": "Draft proposed CC BY 4.0; approval pending"},
        ],
        "resources": [
            {"name": "dams", "path": "data/dams.csv", "profile": "tabular-data-resource", "schema": {"primaryKey": "dam_id", "fields": fields(dams_fields)}},
            {"name": "capacity-history", "path": "data/capacity_history.csv", "profile": "tabular-data-resource", "schema": {"primaryKey": ["dam_id", "valid_from"], "foreignKeys": [{"fields": "dam_id", "reference": {"resource": "dams", "fields": "dam_id"}}], "fields": fields(capacity_fields)}},
            {"name": "bulletin-manifest", "path": "sources/manifest.csv", "profile": "tabular-data-resource", "schema": {"primaryKey": "bulletin_id", "fields": fields(canonical_fields)}},
            {"name": "bulletin-file-manifest", "path": "sources/file_manifest.csv", "profile": "tabular-data-resource", "schema": {"primaryKey": "source_file", "fields": fields(file_fields)}},
            {"name": "storage", "path": "data/storage.csv", "profile": "tabular-data-resource", "schema": storage_schema},
            {"name": "transfers", "path": "data/transfers.csv", "profile": "tabular-data-resource", "schema": transfer_schema},
            {"name": "storage-parquet", "path": "data/parquet/storage.parquet", "format": "parquet", "schema": storage_schema},
            {"name": "transfers-parquet", "path": "data/parquet/transfers.parquet", "format": "parquet", "schema": transfer_schema},
        ],
    }


def append_changes(path: Path, new_rows: list[dict]) -> None:
    existing = read_csv(path)
    fields = list(existing[0].keys()) if existing else [
        "change_id", "date", "component", "relation", "old_artifact", "new_artifact", "reason",
        "producer", "audit", "hash_before", "hash_after",
    ]
    known = {row["change_id"] for row in existing}
    combined = existing + [row for row in new_rows if row["change_id"] not in known]
    write_csv(path, fields, combined)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--full", type=Path, default=DEFAULT_FULL)
    parser.add_argument("--v010", type=Path, default=DEFAULT_V010)
    parser.add_argument("--page1-lineage", type=Path, default=DEFAULT_P1_LINEAGE)
    args = parser.parse_args()
    missing = [name for name in ("review", "full", "v010", "page1_lineage") if getattr(args, name) is None]
    if missing:
        parser.error(
            "not configured: " + ", ".join(missing)
            + " (pass the option or set it in config/paths.local.toml)"
        )

    repo = args.repo.resolve()
    review = args.review.resolve()
    full = args.full.resolve()
    v010 = args.v010.resolve()
    p1_obs = full / "data/extraction/page1/observations.csv.gz"
    p2_obs = full / "data/extraction/page2/observations.csv.gz"
    p3_facts = full / "data/page3/canonical_base/PAGE3_CANONICAL_FACTS_LONG.parquet"
    p3_transfer = full / "data/page3/canonical_base/PAGE3_BASE_TRANSFER_DAY.parquet"

    v010_before = file_snapshot(v010)
    e1_manifest = repo / "sources/manifest.csv"
    file_manifest = repo / "sources/file_manifest.csv"
    if not file_manifest.exists():
        actual = sha256(e1_manifest)
        if actual != E1_FILE_MANIFEST_SHA256:
            raise RuntimeError(f"E1 manifest hash mismatch before preservation: {actual}")
        shutil.copy2(e1_manifest, file_manifest)
    if sha256(file_manifest) != E1_FILE_MANIFEST_SHA256:
        raise RuntimeError("sources/file_manifest.csv does not preserve the accepted E1 path manifest bytes")

    file_manifest_rows = read_csv(file_manifest)
    canonical, unresolved_files, manifest_stats = build_canonical_manifest(
        file_manifest_rows, p1_obs, p2_obs, p3_facts
    )
    canonical_fields = [
        "bulletin_id", "bulletin_date", "original_url", "page1_source_file", "page1_sha256",
        "page2_source_file", "page2_sha256", "page3_source_file", "page3_sha256", "pages_available",
        "status", "provenance_status", "notes",
    ]
    write_csv(repo / "sources/manifest.csv", canonical_fields, canonical)
    write_csv(
        repo / "sources/uncanonicalized_files.csv",
        ["source_file", "sha256", "status", "reason"], unresolved_files,
    )

    lineage_index, lineage_scan_stats = build_lineage_index(args.page1_lineage.resolve())
    storage_rows, storage_lineage_rows, storage_missing_rows, storage_dates, storage_stats = build_storage(
        p1_obs, lineage_index
    )
    storage_fields = [
        "observation_id", "dam_id", "date", "variable", "value", "unit", "source_file", "source_sha256",
        "page", "source_field", "authority_release", "engine_version", "source_row_key", "lineage_id", "flag",
    ]
    write_csv(repo / "data/storage.csv", storage_fields, storage_rows)
    write_csv(
        repo / "provenance/storage_lineage.csv",
        ["observation_id", "lineage_id", "source_field", "physical_column", "cell_bbox", "raw_glyph_sequence",
         "normalization_method", "parser_state", "parsed_numeric_value", "incident_status", "review_status",
         "checksum_validation_reference", "link_status"],
        storage_lineage_rows,
    )
    write_csv(
        repo / "provenance/storage_missingness.csv",
        ["observation_id", "dam_id", "date", "variable", "source_file", "source_sha256", "page", "source_field",
         "lineage_id", "parser_state", "raw_glyph_sequence", "flag", "notes"],
        storage_missing_rows,
    )

    transfer_rows, transfer_stats = build_transfers(p3_transfer)
    transfer_fields = [
        "transfer_observation_id", "date", "bulletin_date", "effective_date_rule", "from_dam_id", "to_dam_id",
        "from_node_id", "to_node_id", "from_mapping_status", "to_mapping_status", "entity_id", "row_role",
        "variable", "value", "unit", "source_file", "source_sha256", "page", "source_field", "authority_release",
        "flag", "semantic_status", "value_status", "continuity_status", "source_consistency_status", "evidence_id",
        "record_id", "series_id", "raw_text",
    ]
    write_csv(repo / "data/transfers.csv", transfer_fields, transfer_rows)

    dams_before = sha256(repo / "data/dams.csv")
    dams_rows, dam_stats = update_dams(repo / "data/dams.csv", review)
    dam_fields = [
        "dam_id", "name_fr", "name_ar", "name_ar_status", "name_ar_source", "aliases", "basin", "basin_status",
        "basin_source", "reference_capacity_mm3", "capacity_valid_from", "latitude", "longitude", "status",
        "geometry_status", "control_status", "identity_source", "coordinate_source", "capacity_source", "notes",
    ]
    write_csv(repo / "data/dams.csv", dam_fields, dams_rows)

    capacity_rows = read_csv(repo / "data/capacity_history.csv")
    capacity_unknown = capacity_unknown_periods(capacity_rows, storage_dates)
    write_csv(
        repo / "provenance/CAPACITY_UNKNOWN_PERIODS.csv",
        ["dam_id", "valid_from", "valid_to", "status", "storage_observation_count", "reason"],
        capacity_unknown,
    )

    write_parquet_from_rows(repo / "data/parquet/storage.parquet", storage_rows, storage_fields)
    write_parquet_from_rows(repo / "data/parquet/transfers.parquet", transfer_rows, transfer_fields)

    datapackage_before = sha256(repo / "datapackage.json")
    (repo / "datapackage.json").write_text(
        json.dumps(datapackage_descriptor(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    v010_after = file_snapshot(v010)
    if v010_before != v010_after:
        raise RuntimeError("Frozen V010 changed during E2 build")

    changes = [
        {"change_id": "E2-CHG-001", "date": "2026-09-24", "component": "Physical bulletin file manifest", "relation": "PRESERVES", "old_artifact": "sources/manifest.csv at E1", "new_artifact": "sources/file_manifest.csv", "reason": "Preserve all path-level and duplicate physical-file evidence before creating a logical bulletin manifest.", "producer": "src/build_e2.py", "audit": "qa/E2_VALIDATION_REPORT.md", "hash_before": E1_FILE_MANIFEST_SHA256, "hash_after": sha256(file_manifest)},
        {"change_id": "E2-CHG-002", "date": "2026-09-24", "component": "Canonical bulletin manifest", "relation": "DERIVES", "old_artifact": portable(f"{p1_obs};{p2_obs};{p3_facts};sources/file_manifest.csv"), "new_artifact": "sources/manifest.csv", "reason": "Create one logical record per accepted bulletin date without discarding physical-file provenance.", "producer": "src/build_e2.py", "audit": "qa/E2_VALIDATION_REPORT.md", "hash_before": "MULTI_SOURCE_SEE_PATHS", "hash_after": sha256(repo / "sources/manifest.csv")},
        {"change_id": "E2-CHG-003", "date": "2026-09-24", "component": "Storage observations", "relation": "DERIVES", "old_artifact": portable(str(p1_obs)), "new_artifact": "data/storage.csv", "reason": "Project accepted Page 1 storage and non-primary printed-fill values into a tidy, stable-dam-ID contract without filling missing values.", "producer": "src/build_e2.py", "audit": "qa/E2_VALIDATION_REPORT.md", "hash_before": sha256(p1_obs), "hash_after": sha256(repo / "data/storage.csv")},
        {"change_id": "E2-CHG-004", "date": "2026-09-24", "component": "Storage cell lineage", "relation": "PROJECTS", "old_artifact": portable(str(args.page1_lineage.resolve())), "new_artifact": "provenance/storage_lineage.csv", "reason": "Retain source-cell lineage identifiers and parse/review states for published storage/fill observations.", "producer": "src/build_e2.py", "audit": "qa/E2_VALIDATION_REPORT.md", "hash_before": sha256(args.page1_lineage.resolve()), "hash_after": sha256(repo / "provenance/storage_lineage.csv")},
        {"change_id": "E2-CHG-005", "date": "2026-09-24", "component": "Qualified Page 3 transfer/accounting facts", "relation": "DERIVES_WITH_QUALIFICATION", "old_artifact": portable(str(p3_transfer)), "new_artifact": "data/transfers.csv", "reason": "Expose selected Page 3 facts while preserving PROBABLE authority, accounting-vs-edge semantics, blank states, and unresolved dam crosswalks.", "producer": "src/build_e2.py", "audit": "qa/E2_VALIDATION_REPORT.md", "hash_before": sha256(p3_transfer), "hash_after": sha256(repo / "data/transfers.csv")},
        {"change_id": "E2-CHG-006", "date": "2026-09-24", "component": "Dam metadata enrichment", "relation": "EXTENDS", "old_artifact": "data/dams.csv at E1", "new_artifact": "data/dams.csv at E2", "reason": "Add evidence/status columns; populate only explicitly supported Medjerda context and preserve Arabic-name candidate states.", "producer": "src/build_e2.py", "audit": "qa/E2_VALIDATION_REPORT.md", "hash_before": dams_before, "hash_after": sha256(repo / "data/dams.csv")},
        {"change_id": "E2-CHG-007", "date": "2026-09-24", "component": "CSV/Parquet paired products", "relation": "PACKAGING_ONLY", "old_artifact": "data/storage.csv;data/transfers.csv", "new_artifact": "data/parquet/storage.parquet;data/parquet/transfers.parquet", "reason": "Provide equivalent private working-repository representations without changing scientific values.", "producer": "src/build_e2.py", "audit": "qa/E2_VALIDATION_REPORT.md", "hash_before": "SEE_E2_CHG_003_AND_005", "hash_after": f"{sha256(repo / 'data/parquet/storage.parquet')}|{sha256(repo / 'data/parquet/transfers.parquet')}"},
        {"change_id": "E2-CHG-008", "date": "2026-09-24", "component": "Core data package contract", "relation": "EXTENDS", "old_artifact": "datapackage.json at E1", "new_artifact": "datapackage.json at E2", "reason": "Register canonical/file manifests, storage, qualified transfers, capacity, dams, and paired Parquet products with field contracts and publication gates.", "producer": "src/build_e2.py", "audit": "qa/E2_VALIDATION_REPORT.md", "hash_before": datapackage_before, "hash_after": sha256(repo / "datapackage.json")},
    ]
    append_changes(repo / "provenance/ENGINEERING_CHANGES.csv", changes)

    summary = {
        "manifest": manifest_stats,
        "lineage_scan": lineage_scan_stats,
        "storage": storage_stats,
        "transfers": transfer_stats,
        "dams": dam_stats,
        "capacity_unknown_periods": len(capacity_unknown),
        "v010_unchanged": True,
        "source_hashes": {
            "page1_observations": sha256(p1_obs),
            "page2_observations": sha256(p2_obs),
            "page3_canonical_facts": sha256(p3_facts),
            "page3_transfer_facts": sha256(p3_transfer),
            "page1_lineage": sha256(args.page1_lineage.resolve()),
        },
        "output_hashes": {
            str(p.relative_to(repo)).replace("\\", "/"): sha256(p)
            for p in [
                repo / "sources/file_manifest.csv", repo / "sources/manifest.csv",
                repo / "sources/uncanonicalized_files.csv", repo / "data/dams.csv",
                repo / "data/storage.csv", repo / "data/transfers.csv",
                repo / "data/parquet/storage.parquet", repo / "data/parquet/transfers.parquet",
                repo / "provenance/storage_lineage.csv", repo / "provenance/storage_missingness.csv",
                repo / "provenance/CAPACITY_UNKNOWN_PERIODS.csv", repo / "datapackage.json",
            ]
        },
    }
    (repo / "provenance/E2_BUILD_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

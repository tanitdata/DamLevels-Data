"""Build the E6A.2 design-valid, multi-page source-cell audit.

This module samples accepted outputs and rereads bounded regions of original
bulletin PDFs. It never imports or invokes a production extractor and never
edits accepted scientific observations.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import random
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import pandas as pd

from paths import external
from validate.quality import decimal_text, read_csv, write_csv
from validate.research_qa import (
    assert_one_primary_cell_per_pdf,
    minimum_zero_error_sample_size,
    multipage_target_decision,
    proportional_stratified_sample,
)


SAMPLE_SEED = 20260926
PRIMARY_SAMPLE_SIZE = 800
SEMANTIC_SAMPLE_SIZE = 160
TARGET_ACCURACY = 0.995
CONFIDENCE = 0.95

# External inputs are resolved through src/paths.py (config/paths.local.toml).
PDF_ROOT_KEYS = {
    "PAGE1": "bulletin_page1_dir",
    "PAGE2": "bulletin_page2_dir",
    "PAGE3": "bulletin_page3_dir",
}

P2_FIELD_FAMILY = {
    "p2_cap_actuelle_mm3": "CAPACITY_REGIME",
    "storage_current_total_corresponding_p2_mm3": "STORAGE_STATE",
    "outflow_reporting_interval_p2_mm3": "DAILY_OUTFLOW",
    "inflow_reporting_interval_p2_mm3": "DAILY_INFLOW",
    "inflow_month_to_date_p2_mm3": "INFLOW_MONTH_TO_DATE",
    "evaporation_reporting_interval_mm3": "EVAPORATION",
    "rainfall_reporting_interval_mm": "RAINFALL",
    "p2_apport_annee_prec_mm3": "PREVIOUS_YEAR_INFLOW",
    "p2_soutirage_annee_prec_mm3": "PREVIOUS_YEAR_OUTFLOW",
}


def _write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> int:
    if fieldnames is None:
        if not rows:
            raise ValueError(f"fieldnames required for empty output {path}")
        fieldnames = list(rows[0])
    return write_csv(path, fieldnames, rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_score(seed: int, *parts: object) -> str:
    payload = "|".join([str(seed), *(str(part) for part in parts)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bbox(value: str) -> tuple[float, float, float, float]:
    text = value.strip()
    if text.startswith("["):
        values = json.loads(text)
    else:
        values = [part.strip() for part in text.strip("()").split(",")]
    return tuple(float(part) for part in values)  # type: ignore[return-value]


def _normalize_digits(text: str) -> str:
    table = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return text.translate(table).replace("\u00a0", " ").replace("\u202f", " ")


def _parse_numeric_text(text: str) -> Decimal | None:
    compact = re.sub(r"\s+", "", _normalize_digits(text))
    if not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", compact):
        return None
    return Decimal(compact.replace(",", "."))


def _independent_numeric_crop(page, bbox: tuple[float, float, float, float]) -> dict[str, str]:
    crop = page.crop(bbox)
    raw = (crop.extract_text(x_tolerance=1, y_tolerance=1) or "").strip()
    words = crop.extract_words(x_tolerance=1, y_tolerance=1, keep_blank_chars=False)
    lines: dict[float, list[dict]] = defaultdict(list)
    for word in words:
        lines[round(float(word["top"]), 1)].append(word)
    candidates: list[tuple[Decimal, str]] = []
    for line_words in lines.values():
        ordered = sorted(line_words, key=lambda item: float(item["x0"]))
        deduped: list[dict] = []
        for word in ordered:
            duplicate = any(
                str(word["text"]) == str(old["text"])
                and abs(float(word["x0"]) - float(old["x0"])) <= 0.75
                for old in deduped
            )
            if not duplicate:
                deduped.append(word)
        joined = "".join(str(word["text"]) for word in deduped)
        parsed = _parse_numeric_text(joined)
        if parsed is not None:
            candidates.append((parsed, joined))
            continue
        for word in deduped:
            parsed = _parse_numeric_text(str(word["text"]))
            if parsed is not None:
                candidates.append((parsed, str(word["text"])))
    unique = {value for value, _ in candidates}
    if len(unique) == 1:
        value = next(iter(unique))
        method = "UNANIMOUS_SOURCE_REGION_NUMERIC_READ" if len(candidates) > 1 else "DIRECT_SOURCE_REGION_NUMERIC_READ"
        return {
            "source_value": decimal_text(value),
            "source_raw_text": raw.replace("\r", " ").replace("\n", " "),
            "source_read_method": method,
            "verification_issue": "",
        }
    issue = "NO_NUMERIC_SOURCE_READING" if not unique else "MULTIPLE_SOURCE_VALUES_IN_REGION"
    return {
        "source_value": "",
        "source_raw_text": raw.replace("\r", " ").replace("\n", " "),
        "source_read_method": "COMPUTER_ASSISTED_SOURCE_REREAD",
        "verification_issue": issue,
    }


def _read_one_source_cell(candidate: dict[str, object]) -> dict[str, str]:
    import pdfplumber

    source_file = str(candidate["source_file"])
    page_family = str(candidate["page_family"])
    source_path = external(PDF_ROOT_KEYS[page_family]) / source_file
    base = {
        "source_hash_checked": "NO",
        "source_value": "",
        "source_raw_text": "",
        "source_read_method": "COMPUTER_ASSISTED_SOURCE_REREAD",
        "verification_issue": "",
    }
    if not source_path.is_file():
        return {**base, "verification_issue": "SOURCE_PDF_NOT_FOUND"}
    if _sha256(source_path).lower() != str(candidate["source_sha256"]).lower():
        return {**base, "source_hash_checked": "MISMATCH", "verification_issue": "SOURCE_SHA256_MISMATCH"}
    try:
        page_index = int(candidate.get("page", 1)) - 1
        with pdfplumber.open(source_path) as pdf:
            if page_index < 0 or page_index >= len(pdf.pages):
                return {**base, "source_hash_checked": "YES", "verification_issue": "SOURCE_PAGE_OUTSIDE_PDF"}
            read = _independent_numeric_crop(pdf.pages[page_index], candidate["bbox"])  # type: ignore[arg-type]
        return {**base, **read, "source_hash_checked": "YES"}
    except Exception as exc:
        return {**base, "source_hash_checked": "YES", "verification_issue": f"PDF_READ_ERROR:{type(exc).__name__}"}


def _read_source_cells(candidates: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    # Four workers keep Windows memory use bounded while parallelising the
    # independent one-PDF reads. Higher fan-out proved unstable on this corpus.
    with ProcessPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_read_one_source_cell, candidates))
    return {str(row["audit_id"]): result for row, result in zip(candidates, results)}


def _choose_one_per_pdf(rows: Iterable[dict[str, object]], seed: int) -> list[dict[str, object]]:
    chosen: dict[str, tuple[str, dict[str, object]]] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        source = str(row["source_file"])
        counts[source] += 1
        score = _stable_score(seed, source, row.get("candidate_key", ""))
        if source not in chosen or score < chosen[source][0]:
            chosen[source] = (score, row)
    out = []
    for source, (_, row) in chosen.items():
        copy = dict(row)
        copy["within_pdf_candidate_count"] = counts[source]
        out.append(copy)
    return out


def _sample_candidates(candidates: list[dict[str, object]], seed: int) -> tuple[list[dict[str, object]], dict[str, int], dict[str, int]]:
    strata: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in candidates:
        strata[str(row["stratum"])].append(row)
    selected, allocation = proportional_stratified_sample(
        strata,
        min(PRIMARY_SAMPLE_SIZE, len(candidates)),
        seed=seed,
        stable_key=lambda row: str(row["source_file"]),
    )
    populations = {key: len(value) for key, value in strata.items()}
    for row in selected:
        stratum = str(row["stratum"])
        n_h, cap_n_h = allocation[stratum], populations[stratum]
        pdf_probability = n_h / cap_n_h
        cell_probability = pdf_probability / int(row["within_pdf_candidate_count"])
        row.update(
            {
                "stratum_population_pdfs": cap_n_h,
                "stratum_sample_pdfs": n_h,
                "pdf_inclusion_probability": f"{pdf_probability:.12f}",
                "pdf_sampling_weight": f"{1 / pdf_probability:.12f}",
                "cell_selection_probability": f"{1 / int(row['within_pdf_candidate_count']):.12f}",
                "overall_cell_inclusion_probability": f"{cell_probability:.12f}",
            }
        )
    assert_one_primary_cell_per_pdf(selected)
    return selected, populations, allocation


def _page1_candidates(root: Path) -> list[dict[str, object]]:
    layouts = pd.read_csv(external("page1_observations"), compression="gzip", usecols=["source_filename", "schema_layout_class"])
    layout_by_file = layouts.drop_duplicates("source_filename").set_index("source_filename")["schema_layout_class"].to_dict()
    lineage = {row["lineage_id"]: row for row in read_csv(root / "provenance/storage_lineage.csv")}
    rows = []
    for row in read_csv(root / "data/storage.csv"):
        evidence = lineage[row["lineage_id"]]
        rows.append(
            {
                "page_family": "PAGE1",
                "stratum": layout_by_file.get(row["source_file"], "UNRESOLVED_LAYOUT"),
                "source_file": row["source_file"],
                "source_sha256": row["source_sha256"],
                "page": row["page"],
                "bbox": _bbox(evidence["cell_bbox"]),
                "cell_pointer": evidence["cell_bbox"],
                "dam_id": row["dam_id"],
                "bulletin_date": row["date"],
                "field_family": "STORAGE",
                "variable": row["source_field"],
                "accepted_value": row["value"],
                "unit": row["unit"],
                "candidate_key": row["observation_id"],
                "evidence_id": row["lineage_id"],
                "semantic_qualification": "DIRECT_PRINTED_STORAGE",
            }
        )
    return _choose_one_per_pdf(rows, SAMPLE_SEED + 101)


def _page2_candidates() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    numeric: dict[str, tuple[str, dict[str, object]]] = {}
    numeric_counts: Counter[str] = Counter()
    blank_challenges: dict[str, tuple[str, dict[str, object]]] = {}
    with gzip.open(external("page2_value_lineage_run5"), "rt", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            semantic = row["canonical_semantic"]
            if semantic not in P2_FIELD_FAMILY:
                continue
            item = {
                "page_family": "PAGE2",
                "stratum": row["schema_class"],
                "source_file": row["source_pdf"],
                "source_sha256": row["source_sha256"],
                "page": row["page"],
                "bbox": _bbox(row["column_bbox"]),
                "cell_pointer": row["column_bbox"],
                "dam_id": row["dam_id"],
                "bulletin_date": row["bulletin_date"],
                "field_family": P2_FIELD_FAMILY[semantic],
                "variable": semantic,
                "accepted_value": row["parsed_numeric_value"],
                "unit": "SOURCE_FIELD_UNIT_SEE_PAGE2_SCHEMA",
                "candidate_key": f"{row['dam_id']}|{semantic}|{row['physical_column']}",
                "evidence_id": f"{row['source_sha256']}|{row['dam_id']}|c{row['physical_column']}",
                "semantic_qualification": row["schema_class"],
            }
            if row["parse_status"] == "NUMERIC_PARSED" and row["parsed_numeric_value"]:
                source = row["source_pdf"]
                numeric_counts[source] += 1
                score = _stable_score(SAMPLE_SEED + 203, source, item["candidate_key"])
                old = numeric.get(source)
                if old is None or score < old[0]:
                    numeric[source] = (score, item)
            elif row["parse_status"] != "NUMERIC_PARSED":
                score = _stable_score(SAMPLE_SEED + 202, row["source_pdf"], item["candidate_key"])
                old = blank_challenges.get(row["source_pdf"])
                if old is None or score < old[0]:
                    challenge = dict(item)
                    challenge["accepted_value"] = ""
                    challenge["source_raw_text"] = row["raw_cell_text"]
                    challenge["challenge_reason"] = f"PAGE2_{row['parse_status']}"
                    blank_challenges[row["source_pdf"]] = (score, challenge)
    numeric_rows = []
    for source, (_, item) in numeric.items():
        item["within_pdf_candidate_count"] = numeric_counts[source]
        numeric_rows.append(item)
    return numeric_rows, [value[1] for value in blank_challenges.values()]


def _page3_regimes() -> dict[str, str]:
    daily = pd.read_csv(external("page3_clean_daily_summary"), usecols=["source_file", "text_regime", "page_layout"])
    return {
        row.source_file: f"{row.text_regime}|{row.page_layout}"
        for row in daily.drop_duplicates("source_file").itertuples(index=False)
    }


def _page3_primary_candidates() -> list[dict[str, object]]:
    columns = [
        "source_file", "source_sha256", "bulletin_date", "family", "measure_id", "value",
        "value_status", "evidence_id", "raw_text", "row_role", "entity_id", "entity_label_ar",
        "entity_label_en", "from_node", "to_node", "effective_date_rule", "canonical_field_id", "record_id",
    ]
    csv_cache = os.environ.get("DAMLEVELS_E6A2_PAGE3_FACTS_CSV")
    if csv_cache:
        facts = pd.read_csv(csv_cache, usecols=columns)
    else:
        facts = pd.read_parquet(external("page3_canonical_facts"), columns=columns)
    today = {"today", "inflow_today_mm3", "withdrawal_today_mm3", "national_inflow_today", "national_withdrawal_today"}
    current = {"current_season_to_date"}
    facts = facts[facts["measure_id"].isin(today | current) & facts["value"].notna()].copy()
    regimes = _page3_regimes()
    rows = []
    for row in facts.itertuples(index=False):
        qualifier = "DIRECT_TODAY_TRANSCRIPTION" if row.measure_id in today else "DIRECT_CURRENT_SEASON_TRANSCRIPTION"
        rows.append(
            {
                "page_family": "PAGE3",
                "stratum": regimes.get(row.source_file, "UNRESOLVED_TEXT_REGIME"),
                "source_file": row.source_file,
                "source_sha256": row.source_sha256,
                "page": 1,
                "bbox": None,
                "cell_pointer": row.evidence_id,
                "dam_id": "",
                "bulletin_date": row.bulletin_date,
                "field_family": f"{row.family}_{'TODAY' if row.measure_id in today else 'CURRENT_SEASON_TO_DATE'}",
                "variable": row.canonical_field_id,
                "accepted_value": decimal_text(Decimal(str(row.value))),
                "unit": "Mm3",
                "candidate_key": row.evidence_id,
                "evidence_id": row.evidence_id,
                "semantic_qualification": qualifier,
                "row_role": row.row_role,
                "entity_id": row.entity_id,
                "record_id": row.record_id,
            }
        )
    return _choose_one_per_pdf(rows, SAMPLE_SEED + 301)


def _page3_semantic_candidates(root: Path) -> list[dict[str, object]]:
    regimes = _page3_regimes()
    rows = []
    for row in read_csv(root / "data/transfers.csv"):
        if row["variable"] != "today":
            continue
        rows.append(
            {
                "page_family": "PAGE3",
                "stratum": regimes.get(row["source_file"], "UNRESOLVED_TEXT_REGIME"),
                "source_file": row["source_file"],
                "source_sha256": row["source_sha256"],
                "page": row["page"],
                "bbox": None,
                "cell_pointer": row["evidence_id"],
                "bulletin_date": row["bulletin_date"],
                "candidate_key": row["record_id"],
                **{key: row[key] for key in (
                    "record_id", "evidence_id", "entity_id", "row_role", "from_node_id", "to_node_id",
                    "from_dam_id", "to_dam_id", "from_mapping_status", "to_mapping_status",
                    "effective_date_rule", "semantic_status", "raw_text",
                )},
            }
        )
    chosen = _choose_one_per_pdf(rows, SAMPLE_SEED + 401)
    strata: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in chosen:
        strata[str(row["stratum"])].append(row)
    selected, _ = proportional_stratified_sample(
        strata,
        min(SEMANTIC_SAMPLE_SIZE, len(chosen)),
        seed=SAMPLE_SEED + 402,
        stable_key=lambda row: str(row["source_file"]),
    )
    return selected


_EVIDENCE_PATTERN = re.compile(r"^EV\d+-[0-9a-f]+-(F\d+)-r(\d+)c\d+$")


def _load_page3_evidence(
    primary: list[dict[str, object]], semantic: list[dict[str, object]]
) -> tuple[dict[str, dict[str, str]], dict[tuple[str, str, str], list[dict[str, str]]]]:
    wanted_ids = {str(row["evidence_id"]) for row in primary}
    semantic_keys: set[tuple[str, str, str]] = set()
    for row in semantic:
        match = _EVIDENCE_PATTERN.match(str(row["evidence_id"]))
        if match:
            semantic_keys.add((str(row["source_sha256"]), match.group(1), match.group(2)))
    evidence: dict[str, dict[str, str]] = {}
    labels: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    with external("page3_cell_evidence").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            eid = (
                f"EV1-{row['source_sha256'][:12]}-{row['fragment_id']}"
                f"-r{row['row_index']}c{row['column_index']}"
            )
            if eid in wanted_ids:
                evidence[eid] = row
            key = (row["source_sha256"], row["fragment_id"], row["row_index"])
            if key in semantic_keys and row["data_type"] == "label":
                labels[key].append(row)
    return evidence, labels


def _audit_rows(
    family_id: str,
    candidates: list[dict[str, object]],
    populations: dict[str, int],
    allocation: dict[str, int],
) -> tuple[list[dict[str, str]], dict[str, object]]:
    reads = _read_source_cells(candidates)
    rows: list[dict[str, str]] = []
    for index, candidate in enumerate(candidates, start=1):
        audit_id = str(candidate["audit_id"])
        direct = reads[audit_id]
        accepted = Decimal(str(candidate["accepted_value"]))
        source_value = Decimal(direct["source_value"]) if direct["source_value"] else None
        if source_value is None:
            disposition, match, difference = "UNVERIFIABLE", "", ""
        elif source_value == accepted:
            disposition, match, difference = "MATCH", "TRUE", "0"
        else:
            disposition, match = "EXTRACTION_DISCREPANCY_CANDIDATE", "FALSE"
            difference = decimal_text(source_value - accepted)
        rows.append(
            {
                "audit_id": audit_id,
                "audit_family": family_id,
                "page_family": str(candidate["page_family"]),
                "stratum_layout_regime": str(candidate["stratum"]),
                "sampling_seed": str(SAMPLE_SEED),
                "stratum_population_pdfs": str(candidate["stratum_population_pdfs"]),
                "stratum_sample_pdfs": str(candidate["stratum_sample_pdfs"]),
                "pdf_inclusion_probability": str(candidate["pdf_inclusion_probability"]),
                "pdf_sampling_weight": str(candidate["pdf_sampling_weight"]),
                "within_pdf_candidate_count": str(candidate["within_pdf_candidate_count"]),
                "cell_selection_probability": str(candidate["cell_selection_probability"]),
                "overall_cell_inclusion_probability": str(candidate["overall_cell_inclusion_probability"]),
                "dam_id": str(candidate.get("dam_id", "")),
                "bulletin_date": str(candidate["bulletin_date"]),
                "field_family": str(candidate["field_family"]),
                "variable": str(candidate["variable"]),
                "accepted_value": decimal_text(accepted),
                "independently_read_source_value": direct["source_value"],
                "source_raw_text": direct["source_raw_text"],
                "unit": str(candidate["unit"]),
                "source_file": str(candidate["source_file"]),
                "source_sha256": str(candidate["source_sha256"]),
                "source_hash_checked": direct["source_hash_checked"],
                "page": str(candidate["page"]),
                "source_bbox_or_cell_pointer": str(candidate["cell_pointer"]),
                "lineage_localization_inherited": "YES",
                "match": match,
                "difference": difference,
                "disposition": disposition,
                "verification_method": "COMPUTER_ASSISTED_SOURCE_REREAD",
                "secondary_visual_verification": "NOT_HUMAN_VISUALLY_VERIFIED",
                "semantic_qualification": str(candidate["semantic_qualification"]),
                "notes": direct["verification_issue"],
            }
        )
    eligible = sum(row["disposition"] != "UNVERIFIABLE" for row in rows)
    matches = sum(row["disposition"] == "MATCH" for row in rows)
    errors = sum(row["disposition"] == "EXTRACTION_DISCREPANCY_CANDIDATE" for row in rows)
    required = minimum_zero_error_sample_size(TARGET_ACCURACY, CONFIDENCE)
    decision, lower, upper = multipage_target_decision(
        matches=matches,
        eligible=eligible,
        required_zero_error_sample_size=required,
        target=TARGET_ACCURACY,
        independent_pdf_design=True,
    )
    summary: dict[str, object] = {
        "primary_sample_pdfs": len(rows),
        "eligible": eligible,
        "matches": matches,
        "errors": errors,
        "unverifiable": len(rows) - eligible,
        "estimated_accuracy": matches / eligible if eligible else None,
        "wilson_confidence": CONFIDENCE,
        "wilson_lower": lower,
        "wilson_upper": upper,
        "target_accuracy": TARGET_ACCURACY,
        "required_zero_error_sample_size": required,
        "target_decision": decision,
        "primary_sampling_unit": "UNIQUE_SOURCE_PDF",
        "one_primary_cell_per_pdf": True,
        "proportional_stratification": True,
        "population_by_stratum": populations,
        "sample_by_stratum": allocation,
        "field_family_counts": dict(Counter(row["field_family"] for row in rows)),
        "verification_method_counts": dict(Counter(row["verification_method"] for row in rows)),
        "human_visual_verification": "NOT_PERFORMED_BY_A_HUMAN_IN_E6A2",
    }
    return rows, summary


def _semantic_rows(
    candidates: list[dict[str, object]],
    labels: dict[tuple[str, str, str], list[dict[str, str]]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    rows: list[dict[str, str]] = []
    for index, candidate in enumerate(candidates, start=1):
        match = _EVIDENCE_PATTERN.match(str(candidate["evidence_id"]))
        key = (str(candidate["source_sha256"]), match.group(1), match.group(2)) if match else ("", "", "")
        label_cells = sorted(labels.get(key, []), key=lambda row: int(row["column_index"]))
        printed = " | ".join(row["raw_text"] for row in label_cells if row["raw_text"])
        role = str(candidate["row_role"])
        crosswalk_unresolved = "CANDIDATE" in str(candidate["from_mapping_status"]) or "CANDIDATE" in str(candidate["to_mapping_status"])
        if role == "ACCOUNTING_OBSERVATION":
            decision = "ACCOUNTING_NOT_HYDRAULIC_EDGE"
        elif crosswalk_unresolved:
            decision = "PRINTED_LABEL_MATCH_STABLE_ID_UNRESOLVED"
        elif not printed:
            decision = "UNVERIFIABLE"
        else:
            decision = "DATE_SEMANTICS_UNRESOLVED"
        rows.append(
            {
                "audit_id": f"E6A2-A3B-{index:04d}",
                "audit_family": "A3B_PAGE3_SEMANTIC_MAPPING",
                "stratum_layout_regime": str(candidate["stratum"]),
                "bulletin_date": str(candidate["bulletin_date"]),
                "source_file": str(candidate["source_file"]),
                "source_sha256": str(candidate["source_sha256"]),
                "page": str(candidate["page"]),
                "evidence_id": str(candidate["evidence_id"]),
                "record_id": str(candidate["record_id"]),
                "printed_route_or_source_label": printed,
                "printed_destination_label": "NOT_SEPARABLE_FROM_COMBINED_PRINTED_ROUTE_LABEL",
                "extracted_entity_label": str(candidate["entity_id"]),
                "from_node": str(candidate["from_node_id"]),
                "to_node": str(candidate["to_node_id"]),
                "from_dam_id": str(candidate["from_dam_id"]),
                "to_dam_id": str(candidate["to_dam_id"]),
                "physical_or_accounting_role": role,
                "stable_id_mapping_status": f"{candidate['from_mapping_status']}|{candidate['to_mapping_status']}",
                "direction_interpretation": "ACCOUNTING_NOT_DIRECTIONAL" if role == "ACCOUNTING_OBSERVATION" else "FROM_NODE_TO_NODE_AS_PUBLISHED",
                "effective_date_interpretation": "DATE_SEMANTICS_UNRESOLVED",
                "semantic_decision": decision,
                "verification_method": "PRESERVED_CELL_EVIDENCE_PLUS_CATEGORICAL_REVIEW",
                "page3_authority": "PROBABLE",
                "notes": "The published SAME_DAY field conflicts with the canonical-base minus-one-day contract; no assumption resolves it.",
            }
        )
    return rows, dict(Counter(row["semantic_decision"] for row in rows))


def _challenge_rows(
    root: Path,
    p1_all: list[dict[str, object]],
    p2_all: list[dict[str, object]],
    p2_blanks: list[dict[str, object]],
    semantic_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    roster_dates = {"2015-10-03", "2015-10-04", "2015-10-05", "2015-10-06"}
    for row in sorted((row for row in p1_all if row["bulletin_date"] in roster_dates), key=lambda row: str(row["bulletin_date"])):
        if any(item["bulletin_date"] == row["bulletin_date"] for item in out):
            continue
        out.append({
            "challenge_id": f"E6A2-CH-{len(out)+1:03d}", "page_family": "PAGE1",
            "source_file": str(row["source_file"]), "bulletin_date": str(row["bulletin_date"]),
            "field_family": "STORAGE", "challenge_reason": "KNOWN_ROSTER_SCOPE_EPISODE",
            "disposition": "SEPARATE_NONINFERENTIAL_CHALLENGE", "in_primary_denominator": "NO",
            "notes": "National-total roster scope issue; the sampled storage cell is not evidence of aggregate agreement.",
        })
    post = [row for row in p2_all if str(row["stratum"]).startswith("POST_CUTOFF")]
    for row in sorted(post, key=lambda row: _stable_score(SAMPLE_SEED, row["source_file"]))[:6]:
        out.append({
            "challenge_id": f"E6A2-CH-{len(out)+1:03d}", "page_family": "PAGE2",
            "source_file": str(row["source_file"]), "bulletin_date": str(row["bulletin_date"]),
            "field_family": str(row["field_family"]), "challenge_reason": "COLUMN23_SEMANTIC_TRANSITION_OR_RECENT_LAYOUT",
            "disposition": "SEPARATE_NONINFERENTIAL_CHALLENGE", "in_primary_denominator": "NO",
            "notes": str(row["semantic_qualification"]),
        })
    for row in sorted(p2_blanks, key=lambda row: _stable_score(SAMPLE_SEED, row["source_file"], row["candidate_key"]))[:6]:
        out.append({
            "challenge_id": f"E6A2-CH-{len(out)+1:03d}", "page_family": "PAGE2",
            "source_file": str(row["source_file"]), "bulletin_date": str(row["bulletin_date"]),
            "field_family": str(row["field_family"]), "challenge_reason": str(row["challenge_reason"]),
            "disposition": "SOURCE_BLANK_OR_NONNUMERIC_NOT_ACCURACY_FAILURE", "in_primary_denominator": "NO",
            "notes": f"Preserved raw cell: {row.get('source_raw_text','')}",
        })
    for row in semantic_rows[:12]:
        out.append({
            "challenge_id": f"E6A2-CH-{len(out)+1:03d}", "page_family": "PAGE3",
            "source_file": row["source_file"], "bulletin_date": row["bulletin_date"],
            "field_family": "SEMANTIC_MAPPING", "challenge_reason": row["semantic_decision"],
            "disposition": "SEPARATE_NONINFERENTIAL_CHALLENGE", "in_primary_denominator": "NO",
            "notes": row["notes"],
        })
    return out


def _write_sampling_design(path: Path, required: int, summaries: dict[str, dict[str, object]]) -> None:
    lines = [
        "# E6A.2 multipage sampling design",
        "",
        f"Fixed seed: `{SAMPLE_SEED}`. Target: `{TARGET_ACCURACY:.3%}`. Confidence: two-sided `{CONFIDENCE:.0%}` Wilson score interval.",
        "",
        f"The minimum zero-error sample size is computed by iterating `n` until `wilson_interval(n, n).lower >= {TARGET_ACCURACY}`. The first qualifying value is **{required}**; {required-1} does not qualify. Each numeric family targets {PRIMARY_SAMPLE_SIZE} PDFs so modest unverifiability can remain explicit without silently replacing sampled units.",
        "",
        "The bulletin PDF is the primary independent sampling unit. Each family selects at most one numeric target cell per sampled PDF. PDFs are stratified by their governed layout/text regime and allocated proportionally by the largest-remainder method. The CSVs retain stratum populations, allocations, PDF inclusion probabilities, PDF weights, within-PDF candidate counts and cell-selection probabilities.",
        "",
        "Within each selected PDF, one eligible candidate is selected by a fixed-seed SHA-256 ordering. Wilson inference is made separately for Page 1, Page 2 and Page 3 transcription. No combined A1/A2/A3 accuracy is calculated. The Page 3 semantic review is categorical and never enters a numeric Wilson denominator.",
        "",
        "Source localization uses preserved production lineage bounding boxes. Values are reread from the original PDF region with `pdfplumber`, independent of production parser functions. This is `COMPUTER_ASSISTED_SOURCE_REREAD`, not a human manual audit. No row is marked `HUMAN_VISUAL_VERIFIED` in E6A.2.",
        "",
        "Known difficult cases are placed in a separate challenge set. Challenge rows are excluded from all primary inferential denominators.",
        "",
        "## Family allocations",
        "",
    ]
    for family, summary in summaries.items():
        lines.extend([
            f"### {family}", "",
            f"Population by regime: `{json.dumps(summary['population_by_stratum'], sort_keys=True)}`", "",
            f"Sample by regime: `{json.dumps(summary['sample_by_stratum'], sort_keys=True)}`", "",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_multipage_report(path: Path, summary: dict[str, object]) -> None:
    families = summary["numeric_families"]
    lines = [
        "# E6A.2 multipage extraction and transcription audit",
        "",
        "E6A.2 reports Page 1, Page 2 and Page 3 separately. It does **not** publish a pooled multipage accuracy. The production extractors were not invoked and accepted scientific values were not changed.",
        "",
        "| Family | Primary PDFs | Eligible | Matches | Errors | Unverifiable | Wilson 95% CI | Decision |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for key in ("A1_PAGE1_EXTRACTION", "A2_PAGE2_EXTRACTION", "A3_PAGE3_TRANSCRIPTION"):
        item = families[key]
        ci = "n/a" if item["wilson_lower"] is None else f"{item['wilson_lower']:.6%}–{item['wilson_upper']:.6%}"
        lines.append(
            f"| {key} | {item['primary_sample_pdfs']:,} | {item['eligible']:,} | {item['matches']:,} | {item['errors']:,} | {item['unverifiable']:,} | {ci} | {item['target_decision']} |"
        )
    lines.extend([
        "",
        "The Wilson bounds apply only within each independent-PDF family design. Page 3 remains `PROBABLE`; a transcription result does not establish semantic correctness or promote Page 3 authority.",
        "",
        "## A1 Page 1 extraction", "",
        "The primary estimand is one direct printed storage cell per sampled Page 1 PDF. Layout-15 and layout-16 bulletins are sampled proportionally.", "",
        "## A2 Page 2 extraction", "",
        "One direct numeric cell is selected per sampled Page 2 PDF. Field-family results remain descriptive; capacity, storage, inflow/outflow, evaporation, rainfall and previous-year semantics are not merged before their field labels are preserved.", "",
        "## A3 Page 3 numeric transcription", "",
        "The primary sample uses direct `today` or `current_season_to_date` numeric cells. Previous-season values appear only in the challenge/qualification layer. Source localization is inherited from Page 3 evidence IDs and cell boxes; the reread does not call the production parser functions.", "",
        "## A3B Page 3 semantic mapping", "",
        f"Categorical dispositions: `{json.dumps(summary['page3_semantic_mapping']['dispositions'], sort_keys=True)}`.", "",
        "This review keeps physical routes separate from the Sejnane accounting observation, leaves candidate dam crosswalks unresolved and preserves the effective-date conflict. It is not combined with A3 transcription accuracy.", "",
        "## Challenge set", "",
        f"The separate noninferential challenge set contains **{summary['challenge_set']['rows']}** rows. No challenge row enters an A1/A2/A3 Wilson denominator.", "",
        "## Verification method", "",
        "All primary cells are `COMPUTER_ASSISTED_SOURCE_REREAD` from original source PDF regions. Localization is inherited from preserved production lineage. No E6A.2 row is represented as a human manual verification.", "",
        "## Completeness denominator clarification", "",
        "The 143,316 Page 1 opportunities are 3,981 Page 1 bulletin dates × 36 governed dams. The 144 opportunities from four partial bulletins without Page 1 are labeled `OUTSIDE_DENOMINATOR_PARTIAL_BULLETIN_OPPORTUNITIES`; they are not added to that denominator.", "",
        f"Correction candidates: **{summary['correction_candidates']}**.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _update_professor_report(root: Path, summary: dict[str, object]) -> None:
    old = json.loads((root / "qa/qa_summary.json").read_text(encoding="utf-8"))
    historical_a = old["kpis"].pop("A", old.get("historical_e6a1_kpi_a"))
    if historical_a is None:
        historical_details = json.loads(
            (root / "qa/extraction_accuracy_summary.json").read_text(encoding="utf-8")
        )
        historical_a = {
            "name": "extraction accuracy",
            "population": historical_details["sampled_cells"],
            "eligible": historical_details["verifiable_cells"],
            "pass": historical_details["matches"],
            "fail": historical_details["errors"],
            "excluded_unknown": historical_details["unverifiable"],
            "status": historical_details["target_decision"],
            "details": historical_details,
        }
    families = summary["numeric_families"]
    new_kpis = {}
    for code, key, name in (
        ("A1", "A1_PAGE1_EXTRACTION", "Page 1 extraction"),
        ("A2", "A2_PAGE2_EXTRACTION", "Page 2 extraction"),
        ("A3", "A3_PAGE3_TRANSCRIPTION", "Page 3 numeric transcription"),
    ):
        item = families[key]
        new_kpis[code] = {
            "name": name,
            "population": item["primary_sample_pdfs"],
            "eligible": item["eligible"],
            "pass": item["matches"],
            "fail": item["errors"],
            "excluded_unknown": item["unverifiable"],
            "status": item["target_decision"],
            "details": item,
        }
    semantic = summary["page3_semantic_mapping"]
    new_kpis["A3B"] = {
        "name": "Page 3 semantic mapping",
        "population": semantic["sample_rows"],
        "eligible": semantic["sample_rows"] - semantic["dispositions"].get("UNVERIFIABLE", 0),
        "pass": 0,
        "fail": 0,
        "excluded_unknown": semantic["sample_rows"],
        "status": "CATEGORICAL_REVIEW_WITH_EXPLICIT_GAPS",
        "details": semantic,
    }
    old["generated_utc"] = datetime.now(timezone.utc).isoformat()
    old["engineering_run"] = "E6A.2"
    old["baseline_git_commit"] = "977ed9ca1e59640daaa4ceb6263d703a57e0436b"
    old["historical_e6a1_kpi_a"] = historical_a
    # A-family audits first, then B-H in code order, so the summary and report order is stable.
    old["kpis"] = {**new_kpis, **{code: value for code, value in sorted(old["kpis"].items()) if code not in new_kpis}}
    old["kpis"]["B"]["excluded_unknown"] = 0
    old["kpis"]["B"]["details"]["outside_denominator_partial_bulletin_opportunities"] = 144
    old["kpis"]["B"]["details"]["outside_denominator_label"] = "OUTSIDE_DENOMINATOR_PARTIAL_BULLETIN_OPPORTUNITIES"
    (root / "qa/qa_summary.json").write_text(json.dumps(old, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Automatic QA report — professor checks A1/A2/A3/A3B and B through H",
        "",
        "This report is generated from the same result objects as `qa_summary.json`. It does not invoke production extraction or change accepted values. Satellite KPI I remains excluded.",
        "",
        "| KPI | Eligible | Pass | Fail | Excluded/Unknown | Status |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for key, value in old["kpis"].items():
        lines.append(f"| {key}. {value['name']} | {value['eligible']:,} | {value['pass']:,} | {value['fail']:,} | {value['excluded_unknown']:,} | {value['status']} |")
    lines.extend([
        "", "## Multipage extraction/transcription QA", "",
        "A1, A2 and A3 are separate independent-PDF audits. No pooled Page 1+Page 2+Page 3 accuracy is reported. A3B is categorical. Page 3 remains `PROBABLE`.", "",
        "See `qa/extraction/multipage_accuracy_report.md` and `qa/extraction/sampling_design.md` for methods, per-regime allocations, field-family breakdowns and limitations.", "",
        "The source-cell reread is computer assisted and uses inherited lineage localization. It is not described as a human manual audit.", "",
        "## B. Completeness", "",
        f"Page 1 completeness remains {old['kpis']['B']['details']['overall_completeness_text']} over 143,316 Page 1 dam/date opportunities. The 144 dam opportunities associated with four partial bulletins without Page 1 are `OUTSIDE_DENOMINATOR_PARTIAL_BULLETIN_OPPORTUNITIES`; they do not belong to the 143,316 denominator.", "",
        "## C–G and H preservation", "",
        "Accepted C–G scientific counts and H temporal results are unchanged. Page 3 transfer exclusions remain exclusions, not failures. See the unchanged component CSVs and the structured `qa_summary.json` entries.", "",
        "## Known limitations affecting interpretation", "",
        "- source localization uses preserved production bounding boxes;", "- E6A.2 performed computer-assisted source rereads, not a fully independent human audit;", "- Page 3 authority remains PROBABLE;", "- candidate Page 3 dam crosswalks and effective-date semantics remain unresolved;", "- challenge-set results are noninferential;", "- capacity gaps, partial bulletin inventories and existing scientific limitations remain visible.",
    ])
    (root / "qa/report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_e6a2(root: Path, _base_summary: dict | None = None) -> dict:
    qa = root / "qa/extraction"
    qa.mkdir(parents=True, exist_ok=True)
    required = minimum_zero_error_sample_size(TARGET_ACCURACY, CONFIDENCE)
    if required != 765:
        raise AssertionError(f"tested two-sided 95% Wilson contract changed: {required}")

    p1_all = _page1_candidates(root)
    p2_all, p2_blanks = _page2_candidates()
    p3_all = _page3_primary_candidates()
    semantic_candidates = _page3_semantic_candidates(root)

    sampled = {}
    for key, candidates, seed in (
        ("A1_PAGE1_EXTRACTION", p1_all, SAMPLE_SEED + 11),
        ("A2_PAGE2_EXTRACTION", p2_all, SAMPLE_SEED + 12),
        ("A3_PAGE3_TRANSCRIPTION", p3_all, SAMPLE_SEED + 13),
    ):
        sampled[key] = _sample_candidates(candidates, seed)
    for key, prefix in (("A1_PAGE1_EXTRACTION", "E6A2-A1"), ("A2_PAGE2_EXTRACTION", "E6A2-A2"), ("A3_PAGE3_TRANSCRIPTION", "E6A2-A3")):
        for index, row in enumerate(sampled[key][0], start=1):
            row["audit_id"] = f"{prefix}-{index:04d}"

    p3_evidence, p3_labels = _load_page3_evidence(sampled["A3_PAGE3_TRANSCRIPTION"][0], semantic_candidates)
    for row in sampled["A3_PAGE3_TRANSCRIPTION"][0]:
        evidence = p3_evidence.get(str(row["evidence_id"]))
        if evidence:
            row["bbox"] = (
                float(evidence["bbox_x0"]), float(evidence["bbox_y0"]),
                float(evidence["bbox_x1"]), float(evidence["bbox_y1"]),
            )
            row["cell_pointer"] = f"{row['evidence_id']}|bbox={row['bbox']}"
        else:
            row["bbox"] = (0.0, 0.0, 0.0, 0.0)
            row["cell_pointer"] = f"{row['evidence_id']}|MISSING_CELL_EVIDENCE"

    files = {
        "A1_PAGE1_EXTRACTION": qa / "page1_audit_sample.csv",
        "A2_PAGE2_EXTRACTION": qa / "page2_audit_sample.csv",
        "A3_PAGE3_TRANSCRIPTION": qa / "page3_transcription_audit_sample.csv",
    }
    summaries: dict[str, dict[str, object]] = {}
    correction_rows: list[dict[str, str]] = []
    for key in files:
        candidates, populations, allocation = sampled[key]
        audit_rows, family_summary = _audit_rows(key, candidates, populations, allocation)
        _write_rows(files[key], audit_rows)
        summaries[key] = family_summary
        for row in audit_rows:
            if row["disposition"] == "EXTRACTION_DISCREPANCY_CANDIDATE":
                correction_rows.append({
                    "candidate_id": f"E6A2-CORR-{len(correction_rows)+1:04d}",
                    "audit_family": key,
                    "audit_id": row["audit_id"],
                    "source_file": row["source_file"],
                    "source_sha256": row["source_sha256"],
                    "source_bbox_or_cell_pointer": row["source_bbox_or_cell_pointer"],
                    "accepted_value": row["accepted_value"],
                    "independently_read_source_value": row["independently_read_source_value"],
                    "candidate_type": "EXTRACTION_ERROR_CANDIDATE",
                    "status": "REVIEW_REQUIRED_NO_DATA_MUTATION",
                    "notes": row["notes"],
                })

    semantic_rows, semantic_counts = _semantic_rows(semantic_candidates, p3_labels)
    _write_rows(qa / "page3_semantic_audit_sample.csv", semantic_rows)
    challenges = _challenge_rows(root, p1_all, p2_all, p2_blanks, semantic_rows)
    _write_rows(qa / "challenge_set.csv", challenges)
    _write_rows(
        qa / "multipage_correction_candidates.csv",
        correction_rows,
        fieldnames=[
            "candidate_id", "audit_family", "audit_id", "source_file", "source_sha256",
            "source_bbox_or_cell_pointer", "accepted_value", "independently_read_source_value",
            "candidate_type", "status", "notes",
        ],
    )

    summary: dict[str, object] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "engineering_run": "E6A.2",
        "accepted_baseline_commit": "977ed9ca1e59640daaa4ceb6263d703a57e0436b",
        "sample_seed": SAMPLE_SEED,
        "target_accuracy": TARGET_ACCURACY,
        "confidence": CONFIDENCE,
        "minimum_zero_error_sample_size": required,
        "primary_sample_size_target_per_numeric_family": PRIMARY_SAMPLE_SIZE,
        "pooled_multipage_accuracy_reported": False,
        "production_extractor_rerun": False,
        "scientific_values_changed": False,
        "page3_authority": "PROBABLE",
        "numeric_families": summaries,
        "page3_semantic_mapping": {
            "sample_rows": len(semantic_rows),
            "dispositions": semantic_counts,
            "combined_with_transcription_accuracy": False,
        },
        "challenge_set": {"rows": len(challenges), "included_in_primary_denominator": False},
        "correction_candidates": len(correction_rows),
        "verification_method": "COMPUTER_ASSISTED_SOURCE_REREAD_USING_PRESERVED_BBOX_LOCALIZATION",
        "human_manual_audit_claimed": False,
    }
    (qa / "multipage_accuracy_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_sampling_design(qa / "sampling_design.md", required, summaries)
    _write_multipage_report(qa / "multipage_accuracy_report.md", summary)
    _update_professor_report(root, summary)
    return summary


if __name__ == "__main__":
    repository = Path(__file__).resolve().parents[1]
    result = generate_e6a2(repository)
    print(json.dumps({key: value["target_decision"] for key, value in result["numeric_families"].items()}, indent=2))

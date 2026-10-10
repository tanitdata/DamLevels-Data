from __future__ import annotations

from pathlib import Path

from . import ENGINE_VERSION
from .column_geometry import bbox_string, bucket_row_words, detect_column_bands, join_cell_tokens
from .header_geometry import OBSERVATION_VALUE_FIELDS, semantic_for_physical_column, validate_registry
from .logical_page_detector import select_logical_page2
from .pdf_reader import read_source_pdf
from .provenance import format_bbox, row_bbox
from .roster import region_for
from .row_identity import detect_dam_rows
from .schema import bulletin_date_from_filename, schema_class
from .semantic_mapper import observation_value_for_cell
from .value_parser import parse_source_value

OBSERVATION_FIELDS = [
    "source_file", "source_sha256", "page", "bulletin_date", "dam_id", "region",
    "raw_dam_label_token", "row_bbox", "schema_class", "extractor_version",
    "row_detection_method", "row_detection_confidence", "source_validation_status",
] + OBSERVATION_VALUE_FIELDS

LINEAGE_FIELDS = [
    "source_pdf", "source_sha256", "page", "bulletin_date", "dam_id", "region",
    "raw_dam_label_token", "row_bbox", "physical_column", "column_bbox",
    "raw_cell_text", "parsed_numeric_value", "parse_status", "schema_class",
    "canonical_semantic", "extractor_version", "row_detection_method",
    "row_detection_confidence", "source_validation_status",
]

FAILURE_FIELDS = ["source_pdf", "bulletin_date", "failure_stage", "failure_class", "message"]

ROW_AUDIT_FIELDS = [
    "source_pdf", "bulletin_date", "page", "row_y", "raw_dam_label_token",
    "detected_dam_id", "previous_dam_id", "next_dam_id",
    "occupied_measurement_columns", "baseline_span", "row_detection_method",
    "row_detection_confidence", "source_validation_status", "evidence_signals",
]


def extract_page2_pdf(
    path_value: str | Path,
    *,
    target_dams: set[str] | None = None,
    target_fields: set[str] | None = None,
) -> dict:
    """Run the one authoritative Page-2 engine for FULL or TARGETED scope.

    Targeting is a result scope only: page selection, row detection, token assignment,
    parsing, and semantic mapping always execute through this exact implementation.
    """
    validate_registry()
    path = Path(path_value)
    bulletin_date = bulletin_date_from_filename(path)
    source = read_source_pdf(path)
    page = select_logical_page2(source.pages)
    bands = detect_column_bands(page.rects)
    detected_rows, row_audits = detect_dam_rows(page.words, bands)
    dam_ids = [row.dam_id for row in detected_rows]
    if len(dam_ids) != len(set(dam_ids)):
        duplicates = sorted({dam_id for dam_id in dam_ids if dam_ids.count(dam_id) > 1})
        raise ValueError(f"Duplicate dam rows: {duplicates}")

    date_iso = bulletin_date.isoformat()
    schema = schema_class(bulletin_date)
    observations: list[dict] = []
    lineage: list[dict] = []

    for row in detected_rows:
        buckets = bucket_row_words(row.words, bands)
        bbox = row_bbox(row.words)
        bbox_text = format_bbox(bbox)
        observation = {
            "source_file": path.name,
            "source_sha256": source.sha256,
            "page": page.page_number,
            "bulletin_date": date_iso,
            "dam_id": row.dam_id,
            "region": region_for(row.dam_id),
            "raw_dam_label_token": row.raw_dam_label_token,
            "row_bbox": bbox_text,
            "schema_class": schema,
            "extractor_version": ENGINE_VERSION,
            "row_detection_method": row.detection_method,
            "row_detection_confidence": f"{row.confidence:.2f}",
            "source_validation_status": row.source_validation_status,
        }
        observation.update({field: None for field in OBSERVATION_VALUE_FIELDS})

        row_lineage: list[dict] = []
        for physical_column in range(26):
            raw_cell_text = join_cell_tokens(buckets[physical_column], label_cell=(physical_column == 0))
            parsed = parse_source_value(raw_cell_text, physical_column=physical_column)
            semantic, observation_value = observation_value_for_cell(physical_column, bulletin_date, parsed)
            if physical_column != 0:
                observation[semantic] = observation_value
            band = bands[physical_column]
            row_lineage.append({
                "source_pdf": path.name,
                "source_sha256": source.sha256,
                "page": page.page_number,
                "bulletin_date": date_iso,
                "dam_id": row.dam_id,
                "region": region_for(row.dam_id),
                "raw_dam_label_token": row.raw_dam_label_token,
                "row_bbox": bbox_text,
                "physical_column": physical_column,
                "column_bbox": bbox_string(band.x0, bbox[1], band.x1, bbox[3]),
                "raw_cell_text": raw_cell_text,
                "parsed_numeric_value": parsed.numeric_value,
                "parse_status": parsed.status,
                "schema_class": schema,
                "canonical_semantic": semantic_for_physical_column(physical_column, bulletin_date),
                "extractor_version": ENGINE_VERSION,
                "row_detection_method": row.detection_method,
                "row_detection_confidence": f"{row.confidence:.2f}",
                "source_validation_status": row.source_validation_status,
            })
        if target_dams is None or row.dam_id in target_dams:
            observations.append(observation)
            if target_fields:
                lineage.extend(
                    item for item in row_lineage
                    if item["physical_column"] == 0 or item["canonical_semantic"] in target_fields
                )
            else:
                lineage.extend(row_lineage)

    audit_rows = [{
        "source_pdf": path.name,
        "bulletin_date": date_iso,
        "page": page.page_number,
        "row_y": f"{audit.row_y:.3f}",
        "raw_dam_label_token": audit.raw_dam_label_token,
        "detected_dam_id": audit.detected_dam_id,
        "previous_dam_id": audit.previous_dam_id,
        "next_dam_id": audit.next_dam_id,
        "occupied_measurement_columns": audit.occupied_measurement_columns,
        "baseline_span": f"{audit.baseline_span:.3f}",
        "row_detection_method": audit.row_detection_method,
        "row_detection_confidence": "" if audit.row_detection_confidence is None else f"{audit.row_detection_confidence:.2f}",
        "source_validation_status": audit.source_validation_status,
        "evidence_signals": audit.evidence_signals,
    } for audit in row_audits]
    return {
        "source_pdf": path.name,
        "source_path": str(path.resolve()),
        "source_sha256": source.sha256,
        "source_bytes": path.stat().st_size,
        "bulletin_date": date_iso,
        "observations": observations,
        "lineage": lineage,
        "row_audits": audit_rows,
        "recovered_rows": sum(row.detection_method == "RECOVERED_ROSTER_IDENTIFIED_ROW" for row in detected_rows),
        "ambiguous_rows": sum(audit.source_validation_status == "AMBIGUOUS_DAM_ROW_REVIEW" for audit in row_audits),
    }

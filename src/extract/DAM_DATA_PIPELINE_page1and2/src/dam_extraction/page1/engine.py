from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import Any, Iterable

from dam_extraction.common.contracts import (
    ExecutionScope, Page1ExtractionResult, TargetKey, ValueLineage,
)
from dam_extraction.common.pdf_reader import open_logical_page1
from dam_extraction.common.provenance import stable_id
from dam_extraction.common.source_identity import identify_source
from dam_extraction.page1.action_code import parse_action_code
from dam_extraction.page1.checksum_reader import read_checksum_rows, validate_checksums
from dam_extraction.page1.row_identity import GovernedAliasRoster, locate_dam_rows, normalized_key
from dam_extraction.page1.schema import decide_schema, semantic
from dam_extraction.page1.semantic_mapper import canonical_field
from dam_extraction.page1.table_geometry import borderless_stock_evidence, detect_table_geometry
from dam_extraction.page1.token_assembly import CharSpatialIndex, assemble_cell
from dam_extraction.page1.value_parser import parse_numeric

ENGINE_VERSION = "page1-authoritative-0.2.3"


def _default_alias_path() -> Path:
    return Path(__file__).resolve().parents[3] / "page1" / "fixtures" / "PAGE1_GOVERNED_ALIAS_REGISTER.csv"


def _config_hash(alias_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(alias_path.read_bytes())
    digest.update(ENGINE_VERSION.encode("ascii"))
    digest.update(b"PRINTED_HEADER_THEN_PHYSICAL_GEOMETRY|CLUSTERED_VERTICAL_RULING_LEAF_CELLS")
    return digest.hexdigest()


def _coerce_scope(scope: ExecutionScope | str) -> ExecutionScope:
    return scope if isinstance(scope, ExecutionScope) else ExecutionScope(str(scope).upper())


def _target_set(target_keys: Iterable[TargetKey | tuple[str, str] | dict[str, str]] | None,
                roster: GovernedAliasRoster) -> set[tuple[str, str]]:
    targets = set()
    for item in target_keys or []:
        target = TargetKey.coerce(item)
        dam = target.canonical_dam_id
        if dam not in {value[0] for value in roster.mapping.values()}:
            resolved = roster.resolve(dam)
            dam = resolved[0] if resolved else dam.casefold()
        targets.add((dam, target.canonical_field.removeprefix("p1_")))
    return targets


def _header_text(page: Any, table_top: float, data_right: float) -> str:
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False, use_text_flow=False)
    return " ".join(
        str(word.get("text", "")) for word in words
        if float(word.get("top", 0)) < table_top + 100 and float(word.get("x1", 0)) <= data_right + 2
    )


def extract_page1_pdf(
    pdf_path: str | Path,
    scope: ExecutionScope | str = ExecutionScope.FULL,
    target_keys: Iterable[TargetKey | tuple[str, str] | dict[str, str]] | None = None,
    *,
    alias_registry_path: str | Path | None = None,
) -> Page1ExtractionResult:
    """Extract Page 1 through the one authoritative physical-first engine.

    FULL and TARGETED differ only in cell selection. They share PDF intake,
    geometry, row identity, token assembly, parsing, semantics and provenance.
    """
    scope_value = _coerce_scope(scope)
    alias_path = Path(alias_registry_path) if alias_registry_path else _default_alias_path()
    roster = GovernedAliasRoster(alias_path)
    targets = _target_set(target_keys, roster)
    if scope_value is ExecutionScope.TARGETED and not targets:
        raise ValueError("TARGETED scope requires target_keys")
    source = identify_source(pdf_path)
    result = Page1ExtractionResult(source=source, scope=scope_value, schema_layout_class="UNRESOLVED", schema_incident_status="UNRESOLVED")
    config_hash = _config_hash(alias_path)

    with open_logical_page1(pdf_path) as page:
        # One immutable spatial view preserves the exact cell predicate while
        # avoiding hundreds of repeated full-page character scans.
        chars = CharSpatialIndex(page.chars)
        geometry = detect_table_geometry(page)
        header_text = _header_text(page, geometry.table_bbox[1], geometry.data_intervals[-1][1])
        schema = decide_schema(len(geometry.data_intervals), header_text, source.bulletin_date_parsed)
        result.schema_layout_class = schema.layout_class
        incidents = [value for value in (geometry.incident_status, schema.incident_status) if value != "NONE"]
        result.schema_incident_status = ";".join(incidents) if incidents else "NONE"
        if not schema.fields or len(schema.fields) != len(geometry.data_intervals):
            result.failures.append({
                "failure_class": "SCHEMA_GEOMETRY_UNRESOLVED", "source_filename": source.source_filename,
                "details": f"intervals={len(geometry.data_intervals)} fields={len(schema.fields)}",
                "disposition": "QUARANTINED_NO_GUESS",
            })
            return result

        rows = locate_dam_rows(chars, geometry.table_bbox, geometry.data_intervals[0], geometry.row_bands, roster)
        borderless = borderless_stock_evidence(page, geometry, schema.fields, len(rows))
        result.validation_results.append({
            "validation_name": "BORDERLESS_STOCK_COLUMN_DETECTOR", "status": borderless["status"],
            "details_json": json.dumps(borderless, ensure_ascii=False, sort_keys=True),
        })
        result.validation_results.append({
            "validation_name": "SCHEMA_AUTHORITY", "status": result.schema_incident_status,
            "details_json": json.dumps({
                "layout_class": schema.layout_class, "authority_method": schema.authority_method,
                "header_fill_evidence": schema.header_fill_evidence, "date_heuristic": schema.date_heuristic,
                "data_column_count": len(geometry.data_intervals),
            }, sort_keys=True),
        })

        for row in sorted(rows, key=lambda item: item.row_index):
            if row.mapping_status == "AMBIGUOUS_ALIAS_COLLISION":
                result.failures.append({
                    "failure_class": "AMBIGUOUS_ALIAS_COLLISION", "raw_dam_label": row.raw_label,
                    "canonical_dam_id": row.canonical_dam_id, "disposition": "QUARANTINED_NO_FUZZY_ASSIGNMENT",
                })
                continue
            requested_fields = schema.fields[1:]
            if scope_value is ExecutionScope.TARGETED:
                requested_fields = [field for field in requested_fields if (row.canonical_dam_id, field) in targets]
                if not requested_fields:
                    continue
            observation: dict[str, Any] = {
                "output_row_key": f"PAGE_1|{source.bulletin_date_parsed or source.bulletin_date_raw}|{row.canonical_dam_id}",
                "source_filename": source.source_filename, "source_sha256": source.source_sha256,
                "source_bytes": source.source_bytes, "bulletin_date": source.bulletin_date_parsed,
                "physical_page": 1, "logical_page": "PAGE_1", "raw_dam_label": row.raw_label,
                "canonical_dam_id": row.canonical_dam_id, "schema_layout_class": schema.layout_class,
                "execution_scope": scope_value.value, "engine_version": ENGINE_VERSION,
                "physical_row_index": row.row_index,
            }
            band = row.cell_band
            for field in requested_fields:
                column_index = schema.fields.index(field)
                interval = geometry.data_intervals[column_index]
                bbox = [interval[0], band[0], interval[1], band[1]]
                evidence = assemble_cell(chars, bbox)
                if field == "release_action_code":
                    code, parser_state = parse_action_code(evidence.normalized_parse_input)
                    numeric = None
                    observation[canonical_field(field)] = code
                else:
                    parsed = parse_numeric(evidence)
                    parser_state = parsed.parser_state.value
                    numeric = parsed.parsed_numeric_value
                    observation[canonical_field(field)] = numeric
                unit, time_basis = semantic(field)
                incident = result.schema_incident_status
                review = "REVIEW_REQUIRED" if parser_state.startswith("AMBIGUOUS") or incident.startswith("SCHEMA_GEOMETRY_UNRESOLVED") else "NONE"
                lineage = ValueLineage(
                    lineage_id=stable_id("P1LIN", source.source_sha256, row.canonical_dam_id, field),
                    source_filename=source.source_filename, source_sha256=source.source_sha256,
                    source_bytes=source.source_bytes, physical_page=1, logical_page="PAGE_1",
                    bulletin_date_raw=source.bulletin_date_raw, bulletin_date_parsed=source.bulletin_date_parsed,
                    date_parse_status=source.date_parse_status, engine_version=ENGINE_VERSION,
                    config_hash=config_hash, roster_version=roster.version, execution_scope=scope_value.value,
                    raw_dam_label=row.raw_label, canonical_dam_id=row.canonical_dam_id,
                    mapping_method=row.mapping_method, mapping_status=row.mapping_status,
                    schema_layout_class=schema.layout_class, row_bbox=row.row_bbox,
                    physical_column=column_index, cell_bbox=bbox,
                    ordered_raw_tokens=evidence.ordered_raw_tokens, token_bboxes=evidence.token_bboxes,
                    raw_glyph_evidence=evidence.raw_glyph_evidence, raw_glyph_sequence=evidence.raw_glyph_sequence,
                    normalization_method=evidence.normalization_method,
                    normalized_parse_input=evidence.normalized_parse_input,
                    parser_state=parser_state, parsed_numeric_value=numeric,
                    canonical_semantic_field=canonical_field(field), unit=unit, time_basis=time_basis,
                    row_detection_method=row.row_detection_method,
                    cell_detection_method=geometry.detection_method,
                    fallback_method=None, incident_status=incident, review_status=review,
                )
                result.value_lineage.append(lineage)
                if parser_state.startswith("AMBIGUOUS"):
                    result.unresolved_cells.append({
                        "lineage_id": lineage.lineage_id, "canonical_dam_id": row.canonical_dam_id,
                        "canonical_field": canonical_field(field), "raw_glyph_sequence": evidence.raw_glyph_sequence,
                        "disposition": "AMBIGUOUS_TOKEN_NO_GUESS",
                    })
            result.observations.append(observation)

        result.checksum_source = read_checksum_rows(chars, geometry, schema.fields)
        result.checksum_validation = validate_checksums(
            result.observations,
            result.checksum_source,
            execution_scope=scope_value.value,
        )
        validation_ref = stable_id("P1CHK", source.source_sha256, scope_value.value)
        for lineage in result.value_lineage:
            lineage.checksum_validation_reference = validation_ref
    return result


def extract_cell_strategy_evidence(pdf_path: str | Path, dam_id: str, field: str,
                                   alias_registry_path: str | Path | None = None) -> dict[str, Any]:
    """Deprecated: H/V/exact-crop are development benchmarks, not runtime strategies."""
    warnings.warn(
        "extract_cell_strategy_evidence is deprecated; H/V/exact-crop evidence is "
        "generated only by the bounded development benchmark script",
        DeprecationWarning,
        stacklevel=2,
    )
    return {
        "status": "DEPRECATED_ARCHAEOLOGY_DEVELOPMENT_BENCHMARK_ONLY",
        "runtime_strategy_comparison": False,
        "runtime_fallback_invoked": False,
        "diagnostic_values_returned": False,
        "authoritative_parser": "dam_extraction.page1.value_parser.parse_numeric",
        "evidence_generator": "page1/run_development_validation.py",
    }

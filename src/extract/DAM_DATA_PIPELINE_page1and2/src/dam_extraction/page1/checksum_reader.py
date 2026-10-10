from __future__ import annotations

import re
from typing import Any

from dam_extraction.page1.token_assembly import assemble_cell
from dam_extraction.page1.value_parser import parse_numeric

RAW_RESIDUAL_ONLY = "RAW_RESIDUAL_ONLY"
NON_ADDITIVE_FIELDS = {"stock_fill_pct"}


def _scope_label(raw_label: str, role: str) -> str:
    if role == "GRAND_TOTAL":
        return raw_label.strip() or "TOTAL"
    label = re.sub(r"^\s*S\s*/\s*T\s*", "", raw_label, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", label).strip().upper()


def _row_labels(chars: list[dict[str, Any]], geometry: Any) -> dict[int, str]:
    labels: dict[int, str] = {}
    first = geometry.data_intervals[0]
    for row_index, band in enumerate(geometry.row_bands):
        bbox = [first[0], band[0], first[1], band[1]]
        labels[row_index] = assemble_cell(chars, bbox).normalized_parse_input.strip()
    return labels


def _contiguous_label_suffix_start(labels: dict[int, str], end_index: int) -> int:
    index = end_index - 1
    while index >= 0 and labels.get(index, "").strip():
        index -= 1
    return index + 1


def read_checksum_rows(chars: list[dict[str, Any]], geometry: Any, fields: list[str]) -> list[dict[str, Any]]:
    """Read printed checksum rows and their physical contributor boundaries.

    Contributor regions are inferred only from printed subtotal positions, row
    ordering, and non-empty physical dam-label cells. Canonical dam identity and
    historical dam-region maps are deliberately not involved.
    """
    rows: list[dict[str, Any]] = []
    if not geometry.data_intervals:
        return rows
    labels = _row_labels(chars, geometry)
    for row_index, band in enumerate(geometry.row_bands):
        label = labels[row_index]
        normalized = label.casefold().replace(" ", "")
        if "total" not in normalized and not normalized.startswith("s/t"):
            continue
        role = "GRAND_TOTAL" if "total" in normalized and not normalized.startswith("s/t") else "REGIONAL_SUBTOTAL"
        values: dict[str, float | None] = {}
        raw_tokens: dict[str, str] = {}
        for index, field in enumerate(fields[1:], start=1):
            bbox = [geometry.data_intervals[index][0], band[0], geometry.data_intervals[index][1], band[1]]
            evidence = assemble_cell(chars, bbox)
            raw_tokens[field] = evidence.raw_glyph_sequence
            if field == "release_action_code":
                continue
            values[field] = parse_numeric(evidence).parsed_numeric_value
        rows.append({
            "checksum_row_index": row_index,
            "row_role": role,
            "checksum_scope": role,
            "region_or_total": _scope_label(label, role),
            "raw_label": label,
            "row_bbox": [geometry.table_bbox[0], band[0], geometry.table_bbox[2], band[1]],
            "raw_tokens": raw_tokens,
            "published_values": values,
            "reader_method": "PHYSICALLY_SEPARATE_CHECKSUM_ROW_READER",
            "contributor_boundary_method": "PRINTED_SUBTOTAL_ROW_ORDER_AND_PHYSICAL_LABEL_CELLS",
        })

    rows.sort(key=lambda row: row["checksum_row_index"])
    regional = [row for row in rows if row["row_role"] == "REGIONAL_SUBTOTAL"]
    checksum_indexes = {row["checksum_row_index"] for row in rows}
    previous_boundary: int | None = None
    all_regional_contributors: list[int] = []
    for row in regional:
        end = int(row["checksum_row_index"])
        start = _contiguous_label_suffix_start(labels, end) if previous_boundary is None else previous_boundary + 1
        contributors = [
            index for index in range(start, end)
            if labels.get(index, "").strip() and index not in checksum_indexes
        ]
        row["contributor_row_indexes"] = contributors
        row["contributor_raw_labels"] = [labels[index] for index in contributors]
        row["expected_contributors"] = len(contributors)
        all_regional_contributors.extend(contributors)
        previous_boundary = end

    for row in rows:
        if row["row_role"] != "GRAND_TOTAL":
            continue
        end = int(row["checksum_row_index"])
        if all_regional_contributors:
            contributors = sorted(set(all_regional_contributors))
        else:
            start = _contiguous_label_suffix_start(labels, end)
            contributors = [
                index for index in range(start, end)
                if labels.get(index, "").strip() and index not in checksum_indexes
            ]
        row["contributor_row_indexes"] = contributors
        row["contributor_raw_labels"] = [labels[index] for index in contributors]
        row["expected_contributors"] = len(contributors)
    return rows


def validate_checksums(
    observations: list[dict[str, Any]],
    checksum_rows: list[dict[str, Any]],
    *,
    execution_scope: str,
    policy: str = RAW_RESIDUAL_ONLY,
) -> list[dict[str, Any]]:
    """Compare observed additive values with printed subtotals/totals.

    RAW_RESIDUAL_ONLY records arithmetic evidence and never turns a residual
    into a source-value correction or a universal pass/fail assertion.
    """
    if policy != RAW_RESIDUAL_ONLY:
        raise ValueError(f"unsupported checksum policy: {policy}")
    scope = str(execution_scope).upper()
    candidate_fields = sorted({
        key.removeprefix("p1_")
        for observation in observations
        for key in observation
        if key.startswith("p1_") and key != "p1_release_action_code"
    })
    results: list[dict[str, Any]] = []
    for checksum in sorted(checksum_rows, key=lambda row: row["checksum_row_index"]):
        contributor_indexes = set(checksum.get("contributor_row_indexes", []))
        expected = int(checksum.get("expected_contributors", len(contributor_indexes)))
        scoped_observations = [
            row for row in observations
            if row.get("physical_row_index") in contributor_indexes
        ]
        for field in candidate_fields:
            key = f"p1_{field}"
            observed_rows = [row for row in scoped_observations if key in row]
            numeric = [float(row[key]) for row in observed_rows if isinstance(row.get(key), (int, float))]
            observed = len(observed_rows)
            numeric_count = len(numeric)
            published = checksum.get("published_values", {}).get(field)
            additive = field not in NON_ADDITIVE_FIELDS
            computed = sum(numeric) if additive else None
            residual = (
                computed - float(published)
                if additive and computed is not None and isinstance(published, (int, float))
                else None
            )
            if observed < expected:
                completeness = "TARGETED_PARTIAL" if scope == "TARGETED" else "INCOMPLETE_CONTRIBUTOR_UNIVERSE"
            elif numeric_count < expected:
                completeness = "INCOMPLETE_NUMERIC_SOURCE_STATES"
            else:
                completeness = "COMPLETE"
            if not additive:
                disposition = "NOT_APPLICABLE_NON_ADDITIVE_AGGREGATE"
            elif scope == "TARGETED" and observed < expected:
                disposition = "NOT_APPLICABLE_TARGETED_PARTIAL"
            elif published is None:
                disposition = "UNVERIFIABLE_PUBLISHED_VALUE_MISSING"
            elif completeness == "COMPLETE":
                disposition = "RAW_RESIDUAL_RECORDED"
            else:
                disposition = "RAW_RESIDUAL_RECORDED_INCOMPLETE_CONTRIBUTORS"
            results.append({
                "execution_scope": scope,
                "checksum_scope": checksum["row_role"],
                "region_or_total": checksum.get("region_or_total", checksum.get("raw_label", "")),
                "field": key,
                "expected_contributors": expected,
                "observed_contributors": observed,
                "numeric_contributors": numeric_count,
                "completeness": completeness,
                "computed_sum": computed,
                "published_sum": published,
                "signed_residual": residual,
                "absolute_residual": None if residual is None else abs(residual),
                "residual_basis": "OBSERVED_NUMERIC_CONTRIBUTORS_MINUS_PRINTED_SCOPE",
                "aggregation_method": "SUM_ADDITIVE_SOURCE_VALUES" if additive else "NON_ADDITIVE_PRINTED_AGGREGATE",
                "tolerance_policy": policy,
                "tolerance_formula": None,
                "tolerance_term_count": 0,
                "disposition": disposition,
                "generates_dam_value": False,
            })
    return results

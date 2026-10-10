from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass

from .column_geometry import ColumnBand, bucket_row_words, join_cell_tokens
from .roster import expected_single_between, identify_text_label, normalize_label
from .value_parser import numeric_looking


@dataclass(frozen=True)
class DetectedDamRow:
    dam_id: str
    row_y: float
    words: list[dict]
    raw_dam_label_token: str
    detection_method: str
    confidence: float
    source_validation_status: str
    evidence_signals: tuple[str, ...]


@dataclass(frozen=True)
class RowAudit:
    row_y: float
    raw_dam_label_token: str
    detected_dam_id: str
    previous_dam_id: str
    next_dam_id: str
    occupied_measurement_columns: int
    baseline_span: float
    row_detection_method: str
    row_detection_confidence: float | None
    source_validation_status: str
    evidence_signals: str


@dataclass
class _Candidate:
    row_y: float
    words: list[dict]
    raw_label: str
    direct_dam_id: str | None
    occupancy: int
    baseline_span: float
    subtotal_text: str


def find_table_vertical_bounds(words: list[dict]) -> tuple[float, float]:
    header = [word for word in words if "service)" in str(word.get("text", "")).casefold()]
    totals = [word for word in words if str(word.get("text", "")).strip().casefold() == "total"]
    if not header or not totals:
        raise ValueError("Missing Page-2 header or TOTAL boundary")
    top = min(float(word["bottom"]) for word in header) + 6.0
    bottom = max(float(word["bottom"]) for word in totals) + 6.0
    if bottom <= top:
        raise ValueError("Invalid Page-2 table vertical bounds")
    return top, bottom


def _group_words_by_row(words: list[dict], y_tolerance: float = 6.0) -> list[tuple[float, list[dict]]]:
    row_ys: list[float] = []
    row_map: dict[float, list[dict]] = {}
    ordered_words = sorted(
        words,
        key=lambda word: (
            (float(word["top"]) + float(word["bottom"])) / 2.0,
            float(word["x0"]),
            str(word.get("text", "")),
        ),
    )
    for word in ordered_words:
        y = (float(word["top"]) + float(word["bottom"])) / 2.0
        position = bisect.bisect_left(row_ys, y - y_tolerance)
        matched: float | None = None
        for index in range(position, len(row_ys)):
            if row_ys[index] > y + y_tolerance:
                break
            if abs(row_ys[index] - y) <= y_tolerance:
                matched = row_ys[index]
                break
        if matched is None:
            bisect.insort(row_ys, y)
            matched = y
        row_map.setdefault(matched, []).append(word)
    return [(row_y, row_map[row_y]) for row_y in sorted(row_map)]


def _baseline_span(words: list[dict]) -> float:
    if not words:
        return 0.0
    centers = [(float(word["top"]) + float(word["bottom"])) / 2.0 for word in words]
    if len(centers) < 4:
        return max(centers) - min(centers)
    low = statistics.quantiles(centers, n=4, method="inclusive")[0]
    high = statistics.quantiles(centers, n=4, method="inclusive")[2]
    return high - low


def _build_candidates(words: list[dict], bands: list[ColumnBand]) -> tuple[list[_Candidate], float, float]:
    table_top, table_bottom = find_table_vertical_bounds(words)
    table_words = [
        word
        for word in words
        if table_top <= float(word["top"]) <= table_bottom
        and float(word["x0"]) >= bands[0].x0 - 5.0
        and float(word["x1"]) <= bands[-1].x1 + 5.0
    ]
    candidates: list[_Candidate] = []
    for row_y, row_words in _group_words_by_row(table_words):
        buckets = bucket_row_words(row_words, bands)
        raw_label = join_cell_tokens(buckets[0], label_cell=True)
        direct_dam_id = identify_text_label(raw_label)
        occupancy = sum(bool(buckets[column]) for column in range(1, 26))
        normalized = normalize_label(raw_label)
        subtotal_text = normalized if normalized.startswith("s t ") else ""
        candidates.append(
            _Candidate(
                row_y=row_y,
                words=row_words,
                raw_label=raw_label,
                direct_dam_id=direct_dam_id,
                occupancy=occupancy,
                baseline_span=_baseline_span(row_words),
                subtotal_text=subtotal_text,
            )
        )
    return candidates, table_top, table_bottom


def _neighbor_dams(candidates: list[_Candidate], index: int) -> tuple[str | None, str | None, float | None, float | None]:
    previous_dam = None
    previous_y = None
    next_dam = None
    next_y = None
    for cursor in range(index - 1, -1, -1):
        if candidates[cursor].direct_dam_id:
            previous_dam = candidates[cursor].direct_dam_id
            previous_y = candidates[cursor].row_y
            break
    for cursor in range(index + 1, len(candidates)):
        if candidates[cursor].direct_dam_id:
            next_dam = candidates[cursor].direct_dam_id
            next_y = candidates[cursor].row_y
            break
    return previous_dam, next_dam, previous_y, next_y


def _typical_row_spacing(candidates: list[_Candidate]) -> float:
    ys = [candidate.row_y for candidate in candidates if candidate.direct_dam_id]
    gaps = [right - left for left, right in zip(ys, ys[1:]) if 4.0 <= right - left <= 16.0]
    return statistics.median(gaps) if gaps else 10.0


def detect_dam_rows(words: list[dict], bands: list[ColumnBand]) -> tuple[list[DetectedDamRow], list[RowAudit]]:
    candidates, table_top, table_bottom = _build_candidates(words, bands)
    typical_spacing = _typical_row_spacing(candidates)
    detected: list[DetectedDamRow] = []
    audits: list[RowAudit] = []

    for index, candidate in enumerate(candidates):
        previous_dam, next_dam, previous_y, next_y = _neighbor_dams(candidates, index)
        if candidate.direct_dam_id:
            signals = (
                "vertical_location_inside_table_body",
                "header_anchored_26_column_bands",
                "exact_normalized_roster_label",
            )
            detected.append(DetectedDamRow(
                dam_id=candidate.direct_dam_id,
                row_y=candidate.row_y,
                words=candidate.words,
                raw_dam_label_token=candidate.raw_label,
                detection_method="TEXT_LABEL_EXACT_NORMALIZED",
                confidence=1.0,
                source_validation_status="SOURCE_ROW_DIRECT_TEXT_LABEL",
                evidence_signals=signals,
            ))
            audits.append(RowAudit(
                candidate.row_y, candidate.raw_label, candidate.direct_dam_id,
                previous_dam or "", next_dam or "", candidate.occupancy,
                candidate.baseline_span, "TEXT_LABEL_EXACT_NORMALIZED", 1.0,
                "SOURCE_ROW_DIRECT_TEXT_LABEL", "|".join(signals),
            ))
            continue

        first_label_token = candidate.raw_label.split()[0] if candidate.raw_label else ""
        numeric_or_missing_label = (not first_label_token) or numeric_looking(first_label_token)
        coherent_occupancy = candidate.occupancy >= 12
        baseline_consistent = candidate.baseline_span <= 3.0
        inside_body = table_top <= candidate.row_y <= table_bottom
        expected_dam = expected_single_between(previous_dam, next_dam)
        close_to_neighbor = any(
            distance is not None and distance <= typical_spacing * 1.8
            for distance in (
                candidate.row_y - previous_y if previous_y is not None else None,
                next_y - candidate.row_y if next_y is not None else None,
            )
        )
        subtotal_boundary = any(
            item.subtotal_text
            for item in candidates[max(0, index - 2):min(len(candidates), index + 3)]
        )

        signals: list[str] = []
        if inside_body:
            signals.append("vertical_location_inside_table_body")
        signals.append("header_anchored_26_column_bands")
        if numeric_or_missing_label:
            signals.append("numeric_or_missing_native_label_token")
        if coherent_occupancy:
            signals.append("coherent_horizontal_occupancy")
        if baseline_consistent:
            signals.append("row_baseline_consistency")
        if expected_dam:
            signals.append("unique_roster_slot_between_neighbors")
        if close_to_neighbor:
            signals.append("neighbor_row_spacing_consistent")
        if subtotal_boundary:
            signals.append("regional_subtotal_boundary_nearby")

        coherent_numeric_row = numeric_or_missing_label and coherent_occupancy and baseline_consistent and inside_body
        if coherent_numeric_row and expected_dam and close_to_neighbor:
            detected.append(DetectedDamRow(
                dam_id=expected_dam,
                row_y=candidate.row_y,
                words=candidate.words,
                raw_dam_label_token=candidate.raw_label,
                detection_method="RECOVERED_ROSTER_IDENTIFIED_ROW",
                confidence=0.99,
                source_validation_status="SOURCE_ROW_RECOVERED_ROSTER_GEOMETRY",
                evidence_signals=tuple(signals),
            ))
            audits.append(RowAudit(
                candidate.row_y, candidate.raw_label, expected_dam,
                previous_dam or "", next_dam or "", candidate.occupancy,
                candidate.baseline_span, "RECOVERED_ROSTER_IDENTIFIED_ROW", 0.99,
                "SOURCE_ROW_RECOVERED_ROSTER_GEOMETRY", "|".join(signals),
            ))
        elif coherent_numeric_row:
            audits.append(RowAudit(
                candidate.row_y, candidate.raw_label, "",
                previous_dam or "", next_dam or "", candidate.occupancy,
                candidate.baseline_span, "AMBIGUOUS_DAM_ROW_REVIEW", None,
                "AMBIGUOUS_DAM_ROW_REVIEW", "|".join(signals),
            ))

    detected.sort(key=lambda row: row.row_y)
    return detected, audits

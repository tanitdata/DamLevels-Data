from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TableGeometry:
    table_bbox: list[float]
    x_rulings: list[float]
    data_intervals: list[list[float]]
    row_bands: list[list[float]]
    detection_method: str
    incident_status: str
    arabic_label_interval: list[float] | None


def _cluster(values: list[float], tolerance: float = 3.0) -> list[list[float]]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if not groups or abs(value - sum(groups[-1]) / len(groups[-1])) > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return groups


def _union_length(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 0.5:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def _main_table(page: Any) -> Any:
    candidates = []
    for table in page.find_tables():
        x0, top, x1, bottom = table.bbox
        width, height = x1 - x0, bottom - top
        if width >= page.width * 0.65 and top < page.height * 0.35:
            candidates.append((width * height, table))
    if not candidates:
        raise LookupError("logical Page-1 main table not found")
    return max(candidates, key=lambda item: item[0])[1]


def detect_table_geometry(page: Any) -> TableGeometry:
    table = _main_table(page)
    x0, top, x1, bottom = map(float, table.bbox)
    height = bottom - top
    relevant = []
    for edge in page.vertical_edges:
        x = (float(edge["x0"]) + float(edge["x1"])) / 2
        if x0 - 2 <= x <= x1 + 2:
            start = max(top, float(edge.get("top", top)))
            end = min(bottom, float(edge.get("bottom", bottom)))
            if end > start:
                relevant.append((x, start, end))
    x_groups = _cluster([item[0] for item in relevant])
    rulings = []
    for group in x_groups:
        center = sum(group) / len(group)
        segments = [(start, end) for x, start, end in relevant if min(abs(x - value) for value in group) <= 0.01]
        if _union_length(segments) >= height * 0.55:
            rulings.append(round(center, 4))
    rulings = sorted(set(rulings))
    incident = "NONE"
    if len(rulings) < 16:
        incident = "INSUFFICIENT_VERTICAL_RULINGS"
    # The rightmost main-table interval is the Arabic dam-label mirror. It is
    # physical source evidence but not a numeric/dam-data interval.
    arabic = [rulings[-2], rulings[-1]] if len(rulings) >= 2 else None
    data_rulings = rulings[:-1] if arabic else rulings
    intervals = [[data_rulings[i], data_rulings[i + 1]] for i in range(len(data_rulings) - 1)]
    row_bands = [[float(row.bbox[1]), float(row.bbox[3])] for row in table.rows]
    return TableGeometry(
        table_bbox=[x0, top, x1, bottom], x_rulings=rulings,
        data_intervals=intervals, row_bands=row_bands,
        detection_method="CLUSTERED_VERTICAL_RULING_LEAF_CELLS",
        incident_status=incident, arabic_label_interval=arabic,
    )


def borderless_stock_evidence(page: Any, geometry: TableGeometry, fields: list[str], dam_row_count: int) -> dict[str, Any]:
    if "stock_last_year_mm3" not in fields or not geometry.data_intervals:
        return {"detected": False, "status": "NOT_APPLICABLE"}
    index = fields.index("stock_last_year_mm3")
    interval = geometry.data_intervals[index]
    # Reproduce only the historical rectangle-view evidence (not its semantic
    # parser): narrow-first x0 deduplication and Arabic-gap filtering. Comparing
    # that physical view with authoritative vertical rulings proves whether a
    # printed leaf column lacks a usable rectangle interval.
    band_counts = []
    for band in geometry.row_bands:
        anchor_y = (band[0] + band[1]) / 2
        rects = sorted(
            [r for r in page.rects
             if anchor_y - 20 <= float(r.get("top", 0)) <= anchor_y + 20
             and float(r["x1"]) - float(r["x0"]) >= 5],
            key=lambda r: (float(r["x0"]), float(r["x1"]) - float(r["x0"])),
        )
        unique_rects = []
        for rect in rects:
            if not unique_rects or abs(float(rect["x0"]) - float(unique_rects[-1]["x0"])) > 5:
                unique_rects.append(rect)
        if len(unique_rects) < 10:
            continue
        arabic_start = page.width * 0.87
        candidate_start = arabic_start
        max_gap = 0.0
        for left, right in zip(unique_rects, unique_rects[1:]):
            gap = float(right["x0"]) - float(left["x1"])
            if gap > max_gap:
                max_gap = gap
                candidate_start = float(left["x1"])
        if max_gap > 20:
            arabic_start = candidate_start
        count = sum(float(r["x1"]) <= arabic_start for r in unique_rects)
        if 10 <= count <= 20:
            band_counts.append(count)
    rectangle_interval_count = max(set(band_counts), key=lambda value: (band_counts.count(value), -value)) if band_counts else 0
    exact_rect = rectangle_interval_count >= len(fields)
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False, use_text_flow=False)
    header_words = [
        w for w in words
        if geometry.table_bbox[1] <= float(w["top"]) <= geometry.table_bbox[1] + 100
        and float(w["x1"]) <= geometry.data_intervals[-1][1] + 2
    ]
    header_text = " ".join(str(w.get("text", "")) for w in header_words)
    stock_header = "stock" in header_text.casefold()
    aligned = 0
    for band in geometry.row_bands:
        for word in words:
            cx = (float(word["x0"]) + float(word["x1"])) / 2
            cy = (float(word["top"]) + float(word["bottom"])) / 2
            if interval[0] < cx < interval[1] and band[0] < cy < band[1] and any(ch.isdigit() for ch in str(word.get("text", ""))):
                aligned += 1
                break
    detected = bool(
        rectangle_interval_count == len(fields) - 1
        and stock_header and aligned >= min(5, max(1, dam_row_count))
    )
    return {
        "detected": detected,
        "status": "BORDERLESS_COLUMN_PROVEN" if detected else "BORDERED_OR_NOT_APPLICABLE",
        "printed_header_evidence": stock_header,
        "target_interval": interval,
        "exact_rectangle_present": exact_rect,
        "rectangle_interval_count": rectangle_interval_count,
        "rectangle_band_counts": band_counts,
        "authoritative_leaf_count": len(fields),
        "aligned_numeric_rows": aligned,
        "method": "PRINTED_HEADER_X_ALIGNMENT_REPEATED_ROWS_NEIGHBOR_RULINGS",
    }

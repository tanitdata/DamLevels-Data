from __future__ import annotations

from collections import defaultdict
from math import floor
from typing import Any, Iterable

from dam_extraction.common.contracts import TokenEvidence


def _bbox(char: dict[str, Any]) -> list[float]:
    return [round(float(char["x0"]), 4), round(float(char["top"]), 4),
            round(float(char["x1"]), 4), round(float(char["bottom"]), 4)]


class CharSpatialIndex:
    """Read-only y-binned view over one page's immutable character stream.

    Query membership uses the exact historical center-in-bbox predicate and
    returns characters in original source order. This removes repeated full
    scans only; it does not change cell geometry or token semantics.
    """

    def __init__(self, chars: Iterable[dict[str, Any]], *, bin_height: float = 8.0):
        self.chars = list(chars)
        self.bin_height = float(bin_height)
        self._bins: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        for index, char in enumerate(self.chars):
            cy = (float(char["top"]) + float(char["bottom"])) / 2
            self._bins[floor(cy / self.bin_height)].append((index, char))

    def __iter__(self):
        return iter(self.chars)

    def query_bbox(self, bbox: list[float]) -> list[dict[str, Any]]:
        x0, top, x1, bottom = bbox
        candidates: list[tuple[int, dict[str, Any]]] = []
        first = floor(top / self.bin_height)
        last = floor(bottom / self.bin_height)
        for key in range(first, last + 1):
            candidates.extend(self._bins.get(key, ()))
        selected: list[tuple[int, dict[str, Any]]] = []
        for index, char in candidates:
            cx = (float(char["x0"]) + float(char["x1"])) / 2
            cy = (float(char["top"]) + float(char["bottom"])) / 2
            if x0 < cx < x1 and top < cy < bottom:
                selected.append((index, char))
        selected.sort(key=lambda item: item[0])
        return [char for _, char in selected]


def chars_in_bbox(chars: Iterable[dict[str, Any]], bbox: list[float]) -> list[dict[str, Any]]:
    query = getattr(chars, "query_bbox", None)
    if query is not None:
        return query(bbox)
    x0, top, x1, bottom = bbox
    selected = []
    for char in chars:
        cx = (float(char["x0"]) + float(char["x1"])) / 2
        cy = (float(char["top"]) + float(char["bottom"])) / 2
        if x0 < cx < x1 and top < cy < bottom:
            selected.append(char)
    return selected


def _join(chars: list[dict[str, Any]]) -> str:
    if not chars:
        return ""
    chars = sorted(chars, key=lambda c: (round(float(c["x0"]), 3), round(float(c["top"]), 3), str(c.get("text", ""))))
    widths = [max(0.1, float(c["x1"]) - float(c["x0"])) for c in chars]
    median_width = sorted(widths)[len(widths) // 2]
    out: list[str] = []
    previous_x1: float | None = None
    for char in chars:
        if previous_x1 is not None and float(char["x0"]) - previous_x1 > max(1.4, median_width * 0.75):
            out.append(" ")
        out.append(str(char.get("text", "")))
        previous_x1 = max(previous_x1 or float(char["x1"]), float(char["x1"]))
    return "".join(out).strip()


def assemble_cell(chars: Iterable[dict[str, Any]], bbox: list[float]) -> TokenEvidence:
    selected = chars_in_bbox(chars, bbox)
    selected.sort(key=lambda c: (round(float(c["x0"]), 3), round(float(c["top"]), 3), str(c.get("text", ""))))
    # PDF producers commonly draw the same glyph twice with a sub-point
    # vertical offset. Group by an explicit geometric tolerance instead of
    # decimal quantization, whose bucket boundaries can split a 0.06-point
    # overlay. The raw glyph stream remains preserved in TokenEvidence.
    tolerance = 0.15
    groups: list[list[dict[str, Any]]] = []
    for char in selected:
        match = None
        for group in groups:
            representative = group[0]
            if str(char.get("text", "")) != str(representative.get("text", "")):
                continue
            if all(abs(float(char[key]) - float(representative[key])) <= tolerance
                   for key in ("x0", "top", "x1", "bottom")):
                match = group
                break
        if match is None:
            groups.append([char])
        else:
            match.append(char)
    duplicate_instances = sum(len(group) for group in groups if len(group) > 1)
    duplicate_ratio = duplicate_instances / len(selected) if selected else 0.0
    counts = {len(group) for group in groups}
    ambiguous = bool(duplicate_instances and (duplicate_ratio < 0.75 or max(counts) > 2))
    if duplicate_instances and not ambiguous:
        normalized_chars = [group[0] for group in groups]
        method = "OVERLAY_GLYPH_COORDINATE_DEDUP"
    else:
        normalized_chars = selected
        method = "NONE" if not ambiguous else "UNSAFE_OVERLAY_PATTERN_NOT_NORMALIZED"
    raw = _join(selected)
    normalized = _join(normalized_chars)
    glyphs = [{
        "text": str(char.get("text", "")), "bbox": _bbox(char),
        "fontname": str(char.get("fontname", "")), "size": round(float(char.get("size", 0.0)), 4),
    } for char in selected]
    return TokenEvidence(
        ordered_raw_tokens=[raw] if raw else [], token_bboxes=[_bbox(char) for char in selected],
        raw_glyph_evidence=glyphs, raw_glyph_sequence=raw, normalization_method=method,
        normalized_parse_input=normalized, ambiguous=ambiguous,
    )

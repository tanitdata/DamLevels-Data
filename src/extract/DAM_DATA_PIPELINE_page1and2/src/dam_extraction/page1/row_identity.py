from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dam_extraction.page1.token_assembly import assemble_cell, chars_in_bbox


def normalized_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


@dataclass
class DamRow:
    raw_label: str
    canonical_dam_id: str
    mapping_method: str
    mapping_status: str
    row_bbox: list[float]
    row_index: int
    cell_band: list[float]
    baseline_y: float
    row_detection_method: str


class GovernedAliasRoster:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.mapping: dict[str, tuple[str, str, str]] = {}
        versions = set()
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                versions.add(row["mapping_version"])
                if row["collision_status"] != "UNIQUE":
                    continue
                key = row["raw_name_key"]
                candidate = (row["canonical_dam_id"], row["mapping_method"], row["review_status"])
                if key in self.mapping and self.mapping[key][0] != candidate[0]:
                    self.mapping.pop(key, None)
                else:
                    self.mapping[key] = candidate
        self.version = "+".join(sorted(versions))

    def resolve(self, raw_label: str) -> tuple[str, str, str] | None:
        return self.mapping.get(normalized_key(raw_label))


def _resolve_label(evidence: Any, roster: GovernedAliasRoster) -> tuple[str, tuple[str, str, str] | None]:
    label = evidence.normalized_parse_input.strip()
    resolution = roster.resolve(label)
    if resolution:
        return label, resolution
    glyphs = list(evidence.raw_glyph_evidence)
    if not glyphs:
        return label, None
    groups: dict[tuple[float, float, str], list[dict[str, Any]]] = {}
    for glyph in sorted(glyphs, key=lambda value: (value["bbox"][0], value["bbox"][1], value["text"])):
        key = (round(float(glyph["bbox"][0]), 1), round(float(glyph["bbox"][2]), 1), str(glyph["text"]))
        groups.setdefault(key, []).append(glyph)
    duplicate_instances = sum(len(group) for group in groups.values() if len(group) > 1)
    if not duplicate_instances or duplicate_instances / len(glyphs) < 0.75 or max(map(len, groups.values())) > 2:
        return label, None
    for group in groups.values():
        tops = [float(glyph["bbox"][1]) for glyph in group]
        bottoms = [float(glyph["bbox"][3]) for glyph in group]
        if len(group) > 1 and (max(tops) - min(tops) > 0.2 or max(bottoms) - min(bottoms) > 0.2):
            return label, None
    collapsed = "".join(group[0]["text"] for group in groups.values()).strip()
    resolution = roster.resolve(collapsed)
    if not resolution:
        return label, None
    dam_id, method, status = resolution
    return collapsed, (dam_id, f"{method}+OVERLAY_GLYPH_JITTER_DEDUP", status)


def _evidence_baseline(evidence: Any, fallback: float) -> float:
    centers = [
        (float(glyph["bbox"][1]) + float(glyph["bbox"][3])) / 2
        for glyph in evidence.raw_glyph_evidence
        if str(glyph.get("text", "")).strip()
    ]
    return sum(centers) / len(centers) if centers else fallback


def _line_bands(chars: Any, bbox: list[float]) -> list[tuple[list[float], float]]:
    """Return distinct printed baselines inside a possibly merged table band."""
    selected = [char for char in chars_in_bbox(chars, bbox) if str(char.get("text", "")).strip()]
    if not selected:
        return []
    groups: list[list[dict[str, Any]]] = []
    for char in sorted(selected, key=lambda value: (float(value["top"]) + float(value["bottom"])) / 2):
        center = (float(char["top"]) + float(char["bottom"])) / 2
        if not groups:
            groups.append([char])
            continue
        previous = sum((float(value["top"]) + float(value["bottom"])) / 2 for value in groups[-1]) / len(groups[-1])
        if abs(center - previous) > 3.0:
            groups.append([char])
        else:
            groups[-1].append(char)
    if len(groups) <= 1:
        return []
    centers = [
        sum((float(char["top"]) + float(char["bottom"])) / 2 for char in group) / len(group)
        for group in groups
    ]
    boundaries = [bbox[1]] + [(left + right) / 2 for left, right in zip(centers, centers[1:])] + [bbox[3]]
    return [([boundaries[index], boundaries[index + 1]], centers[index]) for index in range(len(groups))]


def locate_dam_rows(chars: Any, table_bbox: list[float], first_interval: list[float],
                    row_bands: list[list[float]], roster: GovernedAliasRoster) -> list[DamRow]:
    found: list[DamRow] = []
    for index, band in enumerate(row_bands):
        bbox = [first_interval[0], band[0], first_interval[1], band[1]]
        evidence = assemble_cell(chars, bbox)
        label, resolution = _resolve_label(evidence, roster)
        if resolution:
            dam_id, method, status = resolution
            found.append(DamRow(
                label, dam_id, method, status,
                [table_bbox[0], band[0], table_bbox[2], band[1]], index,
                list(band), _evidence_baseline(evidence, (band[0] + band[1]) / 2),
                "TABLE_ROW_BAND_PLUS_GOVERNED_EXACT_ALIAS",
            ))
            continue

        # Some source tables physically merge BEN METIR and KASSEB into one
        # leaf band while retaining two distinct printed text/data baselines.
        # Split only when the whole-band label is not governed and each
        # baseline independently resolves through the governed roster.
        for line_band, baseline in _line_bands(chars, bbox):
            line_bbox = [first_interval[0], line_band[0], first_interval[1], line_band[1]]
            line_evidence = assemble_cell(chars, line_bbox)
            line_label, line_resolution = _resolve_label(line_evidence, roster)
            if not line_resolution:
                continue
            dam_id, method, status = line_resolution
            found.append(DamRow(
                line_label, dam_id, method, status,
                [table_bbox[0], line_band[0], table_bbox[2], line_band[1]], index,
                line_band, baseline,
                "MERGED_TABLE_BAND_VERTICAL_BASELINE_PLUS_GOVERNED_EXACT_ALIAS",
            ))

    unique: dict[str, DamRow] = {}
    for row in found:
        if row.canonical_dam_id in unique:
            previous = unique[row.canonical_dam_id]
            if abs(previous.baseline_y - row.baseline_y) <= 2.0:
                # Overlapping pdfplumber table bands can expose the same source
                # baseline twice. Keep the wider band: duplicate narrow bands
                # can contain the printed label while excluding numeric glyphs
                # above or below that label baseline. This remains exact
                # governed-identity/baseline deduplication, not fuzzy selection.
                if (row.cell_band[1] - row.cell_band[0]) > (previous.cell_band[1] - previous.cell_band[0]):
                    unique[row.canonical_dam_id] = row
                continue
            # Distinct printed baselines for one governed canonical identity
            # remain quarantined rather than silently selected.
            previous.mapping_status = "AMBIGUOUS_ALIAS_COLLISION"
        else:
            unique[row.canonical_dam_id] = row
    return list(unique.values())

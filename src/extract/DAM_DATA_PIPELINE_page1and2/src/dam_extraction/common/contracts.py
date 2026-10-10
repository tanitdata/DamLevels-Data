from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ExecutionScope(str, Enum):
    FULL = "FULL"
    TARGETED = "TARGETED"


class ParserState(str, Enum):
    NUMERIC_PARSED = "NUMERIC_PARSED"
    SOURCE_BLANK = "SOURCE_BLANK"
    SOURCE_NOT_APPLICABLE = "SOURCE_NOT_APPLICABLE"
    SOURCE_NONNUMERIC_EXPRESSION = "SOURCE_NONNUMERIC_EXPRESSION"
    SOURCE_NUMERIC_WITH_FOOTNOTE = "SOURCE_NUMERIC_WITH_FOOTNOTE"
    AMBIGUOUS_TOKEN = "AMBIGUOUS_TOKEN"


@dataclass(frozen=True)
class TargetKey:
    canonical_dam_id: str
    canonical_field: str

    @classmethod
    def coerce(cls, value: "TargetKey | tuple[str, str] | dict[str, str]") -> "TargetKey":
        if isinstance(value, cls):
            return value
        if isinstance(value, tuple) and len(value) == 2:
            return cls(str(value[0]), str(value[1]).removeprefix("p1_"))
        if isinstance(value, dict):
            dam = value.get("canonical_dam_id") or value.get("dam") or value.get("raw_dam_label") or ""
            name = value.get("canonical_field") or value.get("field") or ""
            return cls(str(dam), str(name).removeprefix("p1_"))
        raise TypeError(f"unsupported target key: {value!r}")


@dataclass
class SourceIdentity:
    source_path: str
    source_filename: str
    source_sha256: str
    source_bytes: int
    physical_page: int
    logical_page: str
    bulletin_date_raw: str
    bulletin_date_parsed: str | None
    date_parse_status: str


@dataclass
class TokenEvidence:
    ordered_raw_tokens: list[str]
    token_bboxes: list[list[float]]
    raw_glyph_evidence: list[dict[str, Any]]
    raw_glyph_sequence: str
    normalization_method: str
    normalized_parse_input: str
    ambiguous: bool = False


@dataclass
class ParsedValue:
    parser_state: ParserState
    parsed_numeric_value: float | None
    footnote: str | None = None


@dataclass
class ValueLineage:
    lineage_id: str
    source_filename: str
    source_sha256: str
    source_bytes: int
    physical_page: int
    logical_page: str
    bulletin_date_raw: str
    bulletin_date_parsed: str | None
    date_parse_status: str
    engine_version: str
    config_hash: str
    roster_version: str
    execution_scope: str
    raw_dam_label: str
    canonical_dam_id: str
    mapping_method: str
    mapping_status: str
    schema_layout_class: str
    row_bbox: list[float]
    physical_column: int
    cell_bbox: list[float]
    ordered_raw_tokens: list[str]
    token_bboxes: list[list[float]]
    raw_glyph_evidence: list[dict[str, Any]]
    raw_glyph_sequence: str
    normalization_method: str
    normalized_parse_input: str
    parser_state: str
    parsed_numeric_value: float | None
    canonical_semantic_field: str
    unit: str
    time_basis: str
    row_detection_method: str
    cell_detection_method: str
    fallback_method: str | None
    incident_status: str
    review_status: str
    checksum_validation_reference: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Page1ExtractionResult:
    source: SourceIdentity
    scope: ExecutionScope
    schema_layout_class: str
    schema_incident_status: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    value_lineage: list[ValueLineage] = field(default_factory=list)
    checksum_source: list[dict[str, Any]] = field(default_factory=list)
    checksum_validation: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    unresolved_cells: list[dict[str, Any]] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)


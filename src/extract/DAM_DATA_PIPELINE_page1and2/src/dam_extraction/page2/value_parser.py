from __future__ import annotations

import re
from dataclasses import dataclass

_NUMERIC = re.compile(r"^[+-]?\d+(?:[,.]\d+)?$")
_DASHES = {"-", "--", "---", "\u2013", "\u2014", "*"}


def _deduplicate_doubled_source_token(text: str) -> str:
    if len(text) < 4 or len(text) % 2:
        return text
    pairs = [text[index:index + 2] for index in range(0, len(text), 2)]
    if all(pair[0] == pair[1] for pair in pairs):
        return "".join(pair[0] for pair in pairs)
    return text


@dataclass(frozen=True)
class ParsedSourceValue:
    raw_text: str
    numeric_value: float | None
    status: str


def parse_source_value(raw_text: str | None, *, physical_column: int) -> ParsedSourceValue:
    raw = str(raw_text or "").strip()
    if physical_column == 0:
        return ParsedSourceValue(raw, None, "NOT_APPLICABLE")
    if not raw:
        return ParsedSourceValue(raw, None, "SOURCE_BLANK")
    if raw in _DASHES:
        return ParsedSourceValue(raw, None, "NOT_APPLICABLE")
    compact = _deduplicate_doubled_source_token(raw.replace(" ", ""))
    if _NUMERIC.fullmatch(compact):
        status = "NUMERIC_PARSED_RS_UNRESOLVED_PROHIBITED" if physical_column == 25 else "NUMERIC_PARSED"
        return ParsedSourceValue(raw, float(compact.replace(",", ".")), status)
    if any(operator in compact for operator in ("+", "*", "/")):
        status = "NONNUMERIC_RS_UNRESOLVED_PROHIBITED" if physical_column == 25 else "NONNUMERIC_SOURCE_EXPRESSION"
        return ParsedSourceValue(raw, None, status)
    if re.search(r"[A-Za-z]", compact):
        status = "NONNUMERIC_RS_UNRESOLVED_PROHIBITED" if physical_column == 25 else "NONNUMERIC_SOURCE_EXPRESSION"
        return ParsedSourceValue(raw, None, status)
    return ParsedSourceValue(raw, None, "AMBIGUOUS_TOKEN")


def numeric_looking(text: str) -> bool:
    return bool(_NUMERIC.fullmatch(str(text or "").strip().replace(" ", "")))

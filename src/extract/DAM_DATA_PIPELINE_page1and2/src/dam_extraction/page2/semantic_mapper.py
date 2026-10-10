from __future__ import annotations

from datetime import date

from .header_geometry import semantic_for_physical_column
from .value_parser import ParsedSourceValue


def observation_value_for_cell(
    physical_column: int,
    bulletin_date: date,
    parsed: ParsedSourceValue,
) -> tuple[str, float | None]:
    semantic = semantic_for_physical_column(physical_column, bulletin_date)
    if physical_column == 0:
        return semantic, None
    return semantic, parsed.numeric_value

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote

COLUMN23_CUTOFF = date(2024, 4, 27)
PHYSICAL_COLUMN_COUNT = 26
RS_POLICY = "UNRESOLVED_PROHIBITED"

_NUMERIC_DATE = re.compile(r"(\d{1,2})[/_-](\d{1,2})[/_-](\d{2,4})")
_FRENCH_DATE = re.compile(r"(\d{1,2})\s+([a-z\u00e0-\u00ff]+)\s+(\d{4})", re.I)
_MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12, "décembre": 12,
}


def bulletin_date_from_filename(path: str | Path) -> date:
    stem = unquote(Path(path).stem)
    match = _NUMERIC_DATE.search(stem)
    if match:
        day, month, year = match.groups()
        year_i = int(year)
        if year_i < 100:
            year_i += 2000
        return date(year_i, int(month), int(day))
    match = _FRENCH_DATE.search(stem)
    if match:
        day, month_name, year = match.groups()
        month = _MONTHS.get(month_name.casefold())
        if month is not None:
            return date(int(year), month, int(day))
    raise ValueError(f"Cannot derive bulletin date from {Path(path).name}")


def schema_class(bulletin_date: date) -> str:
    if bulletin_date < COLUMN23_CUTOFF:
        return "PRE_CUTOFF_MONTH_TO_DATE_INFLOW"
    return "POST_CUTOFF_INTERVAL_EVAPORATION"

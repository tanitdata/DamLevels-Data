from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

from dam_extraction.common.contracts import SourceIdentity

FRENCH_MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}


def _date_from_filename(name: str) -> tuple[str, str | None, str]:
    stem = Path(name).stem
    match = re.search(r"(\d{1,2})[-_](\d{1,2})[-_](\d{2,4})", stem)
    if match:
        day, month, year = map(int, match.groups())
        if year < 100:
            year += 2000
        try:
            return stem, date(year, month, day).isoformat(), "PARSED_FILENAME_NUMERIC"
        except ValueError:
            return stem, None, "INVALID_FILENAME_DATE"
    french = re.search(r"(\d{1,2})%20([A-Za-zéûÉÛ]+)%20(\d{4})", stem)
    if french and french.group(2).casefold() in FRENCH_MONTHS:
        try:
            parsed = date(int(french.group(3)), FRENCH_MONTHS[french.group(2).casefold()], int(french.group(1)))
            return stem, parsed.isoformat(), "PARSED_FILENAME_FRENCH_MONTH"
        except ValueError:
            pass
    return stem, None, "UNPARSED_FILENAME_DATE"


def identify_source(path: str | Path) -> SourceIdentity:
    source = Path(path).resolve()
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    raw, parsed, status = _date_from_filename(source.name)
    return SourceIdentity(
        source_path=str(source), source_filename=source.name, source_sha256=digest.hexdigest(),
        source_bytes=size, physical_page=1, logical_page="PAGE_1", bulletin_date_raw=raw,
        bulletin_date_parsed=parsed, date_parse_status=status,
    )


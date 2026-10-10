"""Deterministic sampling for the staged execution gates.

Every sample is a pure function of the input set — no random seed, no clock, no
producer file list — so a reviewer running the same gate on the same corpus gets
exactly the same files.

The stratified benchmark sample deliberately includes the awkward cases the
gates exist to exercise: both known impostors, every rotated page, the earliest
and latest bulletins, the schema-era boundaries, and an even date-strided fill
across the rest.
"""

from __future__ import annotations

import hashlib
from typing import Sequence

from .source_inventory import SourceFile

#: Files whose structure the gates must always cover. Named by file name only,
#: so the sample degrades gracefully on a different input set.
KNOWN_IMPOSTORS = ("3-5-2022_3.pdf", "5-9-2020_3.pdf")
KNOWN_ROTATED = (
    "25-1-2023_3.pdf", "26-1-2023_3.pdf", "27-1-2023_3.pdf", "30-1-2023_3.pdf",
    "31-1-2023_3.pdf", "1-2-2023_3.pdf", "2-2-2023_3.pdf", "3-2-2023_3.pdf",
    "6-2-2023_3.pdf", "7-2-2023_3.pdf", "4-8-2022_3.pdf", "5-8-2022_3.pdf",
)
#: The one file carrying upstream spreadsheet errors.
KNOWN_UPSTREAM_ERROR = ("27%20janvier%202017_3.pdf",)
#: Schema-era boundaries measured in the era registry draft.
ERA_BOUNDARY_DATES = (
    "2014-07-02", "2015-10-01", "2015-10-02", "2016-08-10", "2016-08-11",
    "2016-08-16", "2017-03-05", "2020-04-01", "2022-06-17", "2024-04-26",
    "2024-04-27", "2025-10-10",
)
#: The ten late-legacy files that still carry C0 controls in 2024-2025 (FC-06).
LATE_LEGACY = (
    "26-3-2024_3.pdf", "27-3-2024_3.pdf", "28-3-2024_3.pdf",
    "5-8-2024_3.pdf", "6-8-2024_3.pdf", "7-8-2024_3.pdf", "8-8-2024_3.pdf",
    "9-8-2024_3.pdf", "2-9-2025_3.pdf", "5-9-2025_3.pdf",
)


def _by_name(sources: Sequence[SourceFile]) -> dict[str, SourceFile]:
    return {s.name: s for s in sources}


def _pick(names, index, out, seen):
    for n in names:
        s = index.get(n)
        if s is not None and s.source_file_id not in seen:
            out.append(s)
            seen.add(s.source_file_id)


def quick_check_sample(sources: Sequence[SourceFile], size: int = 10) -> list[SourceFile]:
    """A 10-file smoke set spanning normal, rotated, damaged, both schema eras
    and one impostor — the Gate 2 requirement, expressed as code."""
    index = _by_name(sources)
    out: list[SourceFile] = []
    seen: set[str] = set()

    _pick(("2-7-2014_3.pdf",), index, out, seen)          # oldest, R1, two-edge T5
    _pick(("1-10-2015_3.pdf",), index, out, seen)         # T6 three-row variant
    _pick(("16-8-2016_3.pdf",), index, out, seen)         # T5 [5,4] narrow variant
    _pick(KNOWN_UPSTREAM_ERROR, index, out, seen)         # #N/A source
    _pick(("14-1-2018_3.pdf",), index, out, seen)         # 13-row T2 grid
    _pick(("7-2-2023_3.pdf",), index, out, seen)          # rotated
    _pick(("17-12-2024_3.pdf",), index, out, seen)        # modern R3
    _pick(("5-9-2025_3.pdf",), index, out, seen)          # late legacy C0
    _pick(("10-10-2025_3.pdf",), index, out, seen)        # newest
    _pick(("3-5-2022_3.pdf",), index, out, seen)          # impostor

    if len(out) < size:
        for s in _date_strided(sources, size - len(out), seen):
            out.append(s)
            seen.add(s.source_file_id)
    return out[:size]


def stratified_sample(sources: Sequence[SourceFile], size: int = 200) -> list[SourceFile]:
    """The Gate 4 benchmark set: every awkward stratum, then an even fill."""
    index = _by_name(sources)
    out: list[SourceFile] = []
    seen: set[str] = set()

    _pick(KNOWN_IMPOSTORS, index, out, seen)
    _pick(KNOWN_ROTATED, index, out, seen)
    _pick(KNOWN_UPSTREAM_ERROR, index, out, seen)
    _pick(LATE_LEGACY, index, out, seen)

    dated = {s.filename_date_parsed: s for s in reversed(sorted(
        (s for s in sources if s.filename_date_parsed), key=lambda s: s.filename_date_parsed))}
    for d in ERA_BOUNDARY_DATES:
        s = dated.get(d)
        if s is not None and s.source_file_id not in seen:
            out.append(s)
            seen.add(s.source_file_id)

    # Quick-check members guarantee the era/shape coverage the gates assert.
    for s in quick_check_sample(sources):
        if s.source_file_id not in seen:
            out.append(s)
            seen.add(s.source_file_id)

    for s in _date_strided(sources, max(0, size - len(out)), seen):
        out.append(s)
        seen.add(s.source_file_id)
    return out[:size]


def fifty_file_sample(sources: Sequence[SourceFile], size: int = 50) -> list[SourceFile]:
    """Gate 3: the quick-check set plus an even date-strided fill."""
    out = list(quick_check_sample(sources))
    seen = {s.source_file_id for s in out}
    _pick(KNOWN_IMPOSTORS + KNOWN_ROTATED[:2], _by_name(sources), out, seen)
    for s in _date_strided(sources, max(0, size - len(out)), seen):
        out.append(s)
        seen.add(s.source_file_id)
    return out[:size]


def _date_strided(sources: Sequence[SourceFile], n: int, seen: set[str]) -> list[SourceFile]:
    """Evenly spaced fill over the date-ordered corpus, skipping what is taken."""
    if n <= 0:
        return []
    pool = sorted((s for s in sources if s.source_file_id not in seen),
                  key=lambda s: (s.filename_date_parsed or "9999-99-99", s.name))
    if not pool:
        return []
    if n >= len(pool):
        return pool
    step = len(pool) / n
    return [pool[int(i * step)] for i in range(n)]


def sample_identity(selected: Sequence[SourceFile]) -> str:
    h = hashlib.sha256()
    for s in selected:
        h.update(s.relative_path.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()

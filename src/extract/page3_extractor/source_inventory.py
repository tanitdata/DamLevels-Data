"""Source enumeration and identity.

The input directory is treated as strictly read-only: this module opens files
for reading and nothing else. Filename dates are parsed here (including the
URL-encoded form that exists in the corpus) and are kept *separate* from the
printed date so a disagreement stays visible.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import unquote

PDF_GLOB = "*.pdf"

#: Day-first and year-first forms. Applied anchored at the start of the name
#: first, then searched anywhere: a handful of corpus files carry a prefix
#: (``BARRAGES-25-01-22``, ``barrages06_07_2021``) and anchoring alone would
#: report them as undated, silently disabling the filename-versus-printed date
#: cross-check on exactly those files.
_DATE_PATTERNS = (
    re.compile(r"(\d{1,2})[-_.](\d{1,2})[-_.](\d{2,4})"),
    re.compile(r"(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})"),
)
_FRENCH_MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}
_FRENCH_RE = re.compile(r"(\d{1,2})\s*([A-Za-zéèêûôàç]+)\s*(\d{4})")


@dataclass(frozen=True)
class SourceFile:
    source_file_id: str
    path: Path
    relative_path: str
    size_bytes: int
    filename_date_raw: str
    filename_date_parsed: Optional[str]

    @property
    def name(self) -> str:
        return self.path.name


def parse_filename_date(name: str) -> tuple[str, Optional[str]]:
    """Return ``(raw_fragment, iso_date_or_None)``.

    ``27%20janvier%202017_3.pdf`` is the corpus's one URL-encoded name; it is
    decoded rather than treated as undated.
    """
    stem = Path(name).stem
    decoded = unquote(stem).replace("_3", " ").strip()
    decoded = unicodedata.normalize("NFC", decoded)

    # Anchored first: an unprefixed name must never be resolved by a later
    # digit run that happens to look like a date.
    for finder in ("match", "search"):
        for pat in _DATE_PATTERNS:
            m = getattr(pat, finder)(stem)
            if not m:
                continue
            a, b, c = m.groups()
            if len(a) == 4:
                y, mo, d = int(a), int(b), int(c)
            else:
                d, mo, y = int(a), int(b), _expand_year(c)
            iso = _iso(y, mo, d)
            if iso:
                return m.group(0), iso

    m = _FRENCH_RE.search(decoded)
    if m:
        d, month_word, y = m.groups()
        mo = _FRENCH_MONTHS.get(month_word.lower())
        if mo:
            iso = _iso(int(y), mo, int(d))
            if iso:
                return m.group(0), iso
    return stem, None


def _expand_year(text: str) -> int:
    """``22`` means 2022 in this corpus, which starts in 2014."""
    y = int(text)
    return y + 2000 if y < 100 else y


def _iso(y: int, m: int, d: int) -> Optional[str]:
    if not (1 <= m <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def enumerate_sources(input_dir: Path, *, recursive: bool = False) -> list[SourceFile]:
    """List every PDF under ``input_dir`` in a stable, reproducible order."""
    root = Path(input_dir)
    paths = sorted(root.rglob(PDF_GLOB) if recursive else root.glob(PDF_GLOB),
                   key=lambda p: p.name)
    out: list[SourceFile] = []
    for i, p in enumerate(paths):
        raw, iso = parse_filename_date(p.name)
        out.append(SourceFile(
            source_file_id=f"SRC-{i + 1:06d}",
            path=p,
            relative_path=str(p.relative_to(root)).replace("\\", "/"),
            size_bytes=p.stat().st_size,
            filename_date_raw=raw,
            filename_date_parsed=iso,
        ))
    return out


def corpus_identity(sources: Sequence[SourceFile]) -> dict[str, object]:
    """A hash over the *names and sizes* of the input set.

    Deliberately cheap: it identifies the input set without reading 500 MB of
    PDFs a second time. Per-file content hashes are recorded during extraction.
    """
    h = hashlib.sha256()
    for s in sorted(sources, key=lambda s: s.relative_path):
        h.update(s.relative_path.encode("utf-8"))
        h.update(b"\0")
        h.update(str(s.size_bytes).encode("ascii"))
        h.update(b"\n")
    return {
        "file_count": len(sources),
        "total_bytes": sum(s.size_bytes for s in sources),
        "manifest_sha256": h.hexdigest(),
    }


def select_by_names(sources: Sequence[SourceFile], names: Iterable[str]) -> list[SourceFile]:
    wanted = {n.strip() for n in names if n.strip()}
    by_name = {s.name: s for s in sources}
    by_rel = {s.relative_path: s for s in sources}
    out = []
    for n in sorted(wanted):
        s = by_name.get(n) or by_rel.get(n)
        if s is not None:
            out.append(s)
    return out

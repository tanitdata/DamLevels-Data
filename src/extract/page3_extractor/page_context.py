"""The single shared PageContext.

Binding lifecycle (``04_extractors/common/page_context_contract.md`` section 1,
governing prompt section 7). Per ordinary vector PDF::

    source_filesystem_reads   == 1
    pymupdf_document_opens    == 1
    textpage_builds           == 1
    drawing_scans             == 1
    pdfplumber_document_opens <= 1     (from the same in-memory bytes)
    page_renders              == 0
    ocr_invocations           == 0

Everything T1-T6 needs is collected here once. No T-family extractor, no
validator and no findings generator may call ``get_text``, ``get_drawings`` or
``find_tables``; they consume this object.

1.2.0 adds one thing to that lifecycle and nothing else: the open document, its
page and **the same TextPage** stay alive for the duration of one file's
extraction, so a family that finds the word-level fast path has lost a printed
value can ask :mod:`page3_extractor.native_spans` for the span layer of the page
it is already holding. The extra work is charged to a counter
(``rawdict_extractions``), it happens at most once per page, and it happens only
when a family asks. ``PageContext.close()`` releases the handles; the pipeline
calls it in a ``finally`` so no document outlives the file it belongs to.
"""

from __future__ import annotations

import hashlib
import io
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .geometry import (
    Fragment,
    Transform,
    Word,
    build_fragment,
    reading_order,
    rotation_name,
)
from .text_and_encoding import TextHealth, measure_text_health

#: Printed bulletin date, captured in this same pass. Section 7 of the governing
#: prompt forbids a separate corpus-wide printed-date scan.
_DATE_RE = re.compile(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})")


@dataclass
class StageCounters:
    """Per-file instrumentation. Asserted by the performance tests."""

    source_filesystem_reads: int = 0
    source_bytes_read: int = 0
    pymupdf_document_opens: int = 0
    pdfplumber_document_opens: int = 0
    textpage_builds: int = 0
    word_extractions: int = 0
    drawing_scans: int = 0
    page_renders: int = 0
    ocr_invocations: int = 0
    camelot_invocations: int = 0
    opencv_invocations: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    fallback_count: int = 0
    #: ``rawdict`` reads of the *existing* TextPage. At most one per page, and
    #: zero on a page where every family's fast path succeeded.
    rawdict_extractions: int = 0
    #: Glyph-trace reads of the content stream (PATCH-P5D-001). At most one per
    #: page, and zero on every page that holds no R1 T2 overprint candidate.
    glyph_trace_extractions: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)

    def add(self, other: "StageCounters") -> None:
        for k, v in other.__dict__.items():
            setattr(self, k, getattr(self, k) + v)


@dataclass
class PageContext:
    """Everything one page yields, gathered exactly once."""

    source_path: str
    source_relpath: str
    source_sha256: str
    source_bytes_len: int

    page_index: int
    page_width: float
    page_height: float
    media_width: float
    media_height: float
    rotation: int
    rotation_normalization: str
    transform: Transform

    words: list[Word]
    page_text: str
    text_health: TextHealth
    drawing_count: int
    line_count: int
    rect_count: int
    image_count: int
    font_names: list[str]
    font_count: int
    page_count: int
    encrypted: bool

    fragments: list[Fragment]
    geometry_engine: str
    printed_date_raw: Optional[str]
    printed_date_parsed: Optional[str]
    printed_date_candidates: list[str]

    counters: StageCounters
    build_seconds: float
    open_status: str = "OK"
    open_error: str = ""
    notes: list[str] = field(default_factory=list)

    # -- live PDF handles, released by close() -------------------------- #
    #: The one open document, its page and its one TextPage. Held only while
    #: this file is being extracted. Never serialized, never compared.
    _doc: Any = field(default=None, repr=False, compare=False)
    _page: Any = field(default=None, repr=False, compare=False)
    _textpage: Any = field(default=None, repr=False, compare=False)
    _drawings: Any = field(default=None, repr=False, compare=False)
    _rulings: Any = field(default=None, repr=False, compare=False)
    _spans: Any = field(default=None, repr=False, compare=False)
    _numeric_tokens: Any = field(default=None, repr=False, compare=False)
    _glyph_runs: Any = field(default=None, repr=False, compare=False)

    # -- the conditional native-span fallback --------------------------- #
    @property
    def native_available(self) -> bool:
        """True while the page's own TextPage can still be read."""
        return self._page is not None and self._textpage is not None

    def native_spans(self) -> list:
        """Span layer of this page, read once from the existing TextPage."""
        from .native_spans import extract_spans

        if self._spans is None:
            if not self.native_available:
                self._spans = []
            else:
                self._spans = extract_spans(self._page, self._textpage)
                self.counters.rawdict_extractions += 1
        return self._spans

    def native_numeric_tokens(self) -> list:
        """Every strict French numeric run on the page, with exact geometry."""
        from .native_spans import numeric_tokens

        if self._numeric_tokens is None:
            self._numeric_tokens = numeric_tokens(self.native_spans())
        return self._numeric_tokens

    def native_glyph_runs(self):
        """The page's own text-showing runs, undeduplicated (PATCH-P5D-001).

        Read at most once per page, and only when a family has already refused a
        cell in the R1 T2 overprint candidate class. ``TEXTFLAGS_TEXT`` — which
        the shared TextPage above must keep, because it is what preserves the C0
        control substitution — contains ``TEXT_MEDIABOX_CLIP``, and that bit
        suppresses one of two coincident glyphs, emitting an overprinted comma
        as a space. This reads the content stream's glyph trace instead, which
        no decoder configuration deduplicates. It builds no second TextPage,
        opens no second document, and renders nothing.
        """
        from .glyph_runs import extract_glyph_runs

        if self._glyph_runs is None:
            if not self.native_available:
                self._glyph_runs = []
            else:
                self._glyph_runs = extract_glyph_runs(self._page)
                self.counters.glyph_trace_extractions += 1
        return self._glyph_runs

    def source_rulings(self):
        """The page's own drawn rulings, from the single drawing scan."""
        from .native_spans import RulingSet, collect_rulings

        if self._rulings is None:
            self._rulings = (collect_rulings(self._drawings or ())
                             if self._drawings is not None
                             else RulingSet((), ()))
        return self._rulings

    def close(self) -> None:
        """Release the PDF handles. Idempotent; every derived value survives."""
        doc = self._doc
        self._doc = None
        self._page = None
        self._textpage = None
        self._drawings = None
        if doc is not None:
            try:
                doc.close()
            except Exception:  # noqa: BLE001 - closing must never fail a run
                pass

    def __enter__(self) -> "PageContext":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- convenience ---------------------------------------------------- #
    @property
    def shape_signature(self) -> tuple[tuple[int, int], ...]:
        return tuple(f.shape for f in self.fragments)

    @property
    def shape_signature_text(self) -> str:
        return ";".join(f"[{r},{c}]" for r, c in self.shape_signature)

    @property
    def is_portrait(self) -> bool:
        return self.media_height >= self.media_width

    def as_preflight_dict(self) -> dict[str, Any]:
        h = self.text_health
        return {
            "width_pt": round(self.media_width, 2),
            "height_pt": round(self.media_height, 2),
            "rotation": self.rotation,
            "visual_orientation": "portrait" if self.page_width <= self.page_height else "landscape",
            "text_chars": h.text_chars,
            "word_count": len(self.words),
            "arabic_chars": h.arabic_chars,
            "control_chars": h.control_chars,
            "replacement_chars": h.replacement_chars,
            "font_count": self.font_count,
            "drawing_count": self.drawing_count,
            "line_count": self.line_count,
            "rect_count": self.rect_count,
            "image_count": self.image_count,
        }


class SourceReadError(RuntimeError):
    """The source file could not be read or opened at all."""


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_page_context(path,
                       relpath: str,
                       *,
                       page_index: int = 0,
                       use_pdfplumber_geometry: bool = True) -> PageContext:
    """Read one PDF once and produce the shared context.

    Raises :class:`SourceReadError` when the file cannot be opened; every other
    problem is recorded on the context rather than raised, so a page always
    reconciles to exactly one terminal status.
    """
    import fitz  # imported here so the module imports without a PDF stack

    t0 = time.perf_counter()
    counters = StageCounters()

    try:
        data = _read_bytes(path)
    except OSError as exc:
        raise SourceReadError(f"FAILED_SOURCE_READ: {type(exc).__name__}: {exc}") from exc
    counters.source_filesystem_reads = 1
    counters.source_bytes_read = len(data)
    sha = compute_sha256(data)

    notes: list[str] = []
    doc = None
    ok = False
    try:
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001
            raise SourceReadError(f"FAILED_SOURCE_READ: {type(exc).__name__}: {exc}") from exc
        counters.pymupdf_document_opens = 1

        encrypted = bool(getattr(doc, "is_encrypted", False))
        page_count = doc.page_count
        if page_count == 0:
            raise SourceReadError("FAILED_SOURCE_READ: document has zero pages")
        if page_index >= page_count:
            page_index = 0
            notes.append("page_index clamped to 0")

        page = doc[page_index]
        rot = int(page.rotation)
        prect = page.rect
        mbox = page.mediabox

        # ---- one TextPage, reused for both renderings of the text layer ----
        #
        # The flag set matters and is not the default. ``page.get_textpage()``
        # with default flags silently *drops* the C0 control substitution, which
        # would make every damaged file look healthy — the exact hazard
        # KB-FAIL-TEXTLAYER item 4 warns about, reintroduced through the shared
        # TextPage rather than through the words layer.
        #
        # Measured on this corpus, TEXTFLAGS_TEXT is strictly better on both
        # counts: it preserves the controls (2-7-2014: 491 vs 0) *and* recovers
        # more numeric tokens on damaged files (99 vs 76; 16-8-2016: 99 vs 75;
        # 7-2-2023: 90 vs 70), while producing byte-identical words and numbers
        # on healthy files (17-12-2024 and 10-10-2025: 284 words / 78 numbers
        # either way). One TextPage still serves both consumers.
        textpage = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
        counters.textpage_builds = 1
        raw_words = page.get_text("words", textpage=textpage)
        counters.word_extractions = 1
        page_text = page.get_text("text", textpage=textpage)

        words = [Word(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]))
                 for w in raw_words]
        health = measure_text_health(page_text)

        drawings = page.get_drawings()
        counters.drawing_scans = 1
        line_count = sum(1 for d in drawings for it in d.get("items", ()) if it[0] == "l")
        rect_count = sum(1 for d in drawings for it in d.get("items", ()) if it[0] == "re")
        try:
            image_count = len(page.get_images(full=True))
        except Exception:  # noqa: BLE001
            image_count = 0
        try:
            fonts = sorted({f[3] for f in page.get_fonts(full=True)})
        except Exception:  # noqa: BLE001
            fonts = []

        # ---- canonical frame -------------------------------------------- #
        transform = Transform.from_pymupdf_matrix(page.derotation_matrix, rotation_name(rot))

        # ---- geometry from the same bytes ------------------------------- #
        raw_tables: list[tuple[list[float], list[list[float]]]] = []
        geometry_engine = "none"
        if use_pdfplumber_geometry:
            raw_tables, geometry_engine, plumber_note = _pdfplumber_geometry(data, page_index)
            counters.pdfplumber_document_opens = 1
            if plumber_note:
                notes.append(plumber_note)

        fragments = [
            build_fragment(i, tb, cells, words, transform)
            for i, (tb, cells) in enumerate(raw_tables)
        ]
        fragments = reading_order(fragments)

        printed_raw, printed_parsed, candidates = extract_printed_date(words, fragments)

        ctx = PageContext(
            source_path=str(path),
            source_relpath=relpath,
            source_sha256=sha,
            source_bytes_len=len(data),
            page_index=page_index,
            page_width=float(prect.width),
            page_height=float(prect.height),
            media_width=float(mbox.width),
            media_height=float(mbox.height),
            rotation=rot,
            rotation_normalization=transform.name,
            transform=transform,
            words=words,
            page_text=page_text,
            text_health=health,
            drawing_count=len(drawings),
            line_count=line_count,
            rect_count=rect_count,
            image_count=image_count,
            font_names=fonts,
            font_count=len(fonts),
            page_count=page_count,
            encrypted=encrypted,
            fragments=fragments,
            geometry_engine=geometry_engine,
            printed_date_raw=printed_raw,
            printed_date_parsed=printed_parsed,
            printed_date_candidates=candidates,
            counters=counters,
            build_seconds=0.0,
            notes=notes,
        )
        # The handles the conditional native-span fallback needs. They are the
        # ones already open: no second document, no second TextPage.
        ctx._doc = doc
        ctx._page = page
        ctx._textpage = textpage
        ctx._drawings = drawings
        ok = True
    finally:
        if doc is not None and not ok:
            doc.close()

    ctx.build_seconds = time.perf_counter() - t0
    return ctx


def _read_bytes(path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _pdfplumber_geometry(data: bytes, page_index: int):
    """One pdfplumber open over the shared bytes; closed immediately.

    pdfplumber supplies fragment *geometry* only. Its text is never read: the
    corpus-wide glyph scan measured doubled numeric tokens in 2,572 files
    (CLM-003), so its numeric text is disqualified as evidence.
    """
    import pdfplumber

    note = ""
    tables: list[tuple[list[float], list[list[float]]]] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pl:
            if page_index >= len(pl.pages):
                return [], "pdfplumber", "pdfplumber page index out of range"
            page = pl.pages[page_index]
            for t in page.find_tables():
                cells: list[list[float]] = []
                for row in t.rows:
                    for cell in row.cells:
                        if cell:
                            cells.append([float(v) for v in cell])
                tables.append(([float(v) for v in t.bbox], cells))
    except Exception as exc:  # noqa: BLE001
        note = f"pdfplumber geometry failed: {type(exc).__name__}: {exc}"
        return [], "pdfplumber_failed", note
    return tables, "pdfplumber", note


# ---------------------------------------------------------------------- #
# Printed date
# ---------------------------------------------------------------------- #

def extract_printed_date(words, fragments) -> tuple[Optional[str], Optional[str], list[str]]:
    """Find the printed bulletin date in the page header.

    Restricted to the band above the first fragment so that a date inside a
    table cell can never be mistaken for the bulletin date. All candidates are
    returned so a conflict is visible rather than silently resolved.
    """
    header_bottom = min((f.bbox[1] for f in fragments), default=float("inf"))
    candidates: list[tuple[float, str, str]] = []
    for w in words:
        if w.y1 > header_bottom:
            continue
        m = _DATE_RE.search(w.text)
        if not m:
            continue
        iso = _to_iso(m.group(1), m.group(2), m.group(3))
        if iso:
            candidates.append((w.y0, w.text.strip(), iso))

    if not candidates:
        # Adjacent-word form: "17" "/" "12" "/" "2024" split across tokens.
        header_words = [w for w in words if w.y1 <= header_bottom]
        header_words.sort(key=lambda w: (round(w.y0, 1), w.x0))
        joined = "".join(w.text for w in header_words)
        m = _DATE_RE.search(joined)
        if m:
            iso = _to_iso(m.group(1), m.group(2), m.group(3))
            if iso:
                candidates.append((0.0, m.group(0), iso))

    if not candidates:
        return None, None, []
    candidates.sort(key=lambda c: c[0])
    raws = [c[1] for c in candidates]
    return candidates[0][1], candidates[0][2], raws


def _to_iso(d: str, m: str, y: str) -> Optional[str]:
    try:
        day, month, year = int(d), int(m), int(y)
    except ValueError:
        return None
    if year < 100:
        year += 2000
    if not (1 <= month <= 12 and 1 <= day <= 31 and 2000 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"

"""The shared conditional native-span fallback.

Why this module exists
----------------------
``page.get_text("words")`` is the fast path and stays the fast path. On this
corpus it has two measured failure modes that lose a *printed* value:

* on ``R2_presentation_forms`` pages there is no space glyph between a numeric
  run and the Arabic run beside it, so PyMuPDF welds them into one word whose
  box spans from the value column to the label column. Assigned by its own
  centre, that word lands in the label column and the value column reads blank
  — the 1,029 R2 T5 daily values of ``AUD5B-F-001``;
* on overprinted rows two near-coincident draws interleave in the words layer,
  producing ``1 1 966 966,010 010`` — a string that is not a number.

Both are visible, unambiguously, one level down: in the *span* layer, where each
draw is its own span and each character carries its own box.

The contract this module keeps
------------------------------
* it reads ``page.get_text("rawdict", textpage=<the TextPage already built>)``;
* it never opens the PDF again and never builds a second TextPage;
* it is called only when the word-level fast path has already failed for a
  particular cell, and its result is memoized per page;
* it parses **only** strict French numbers, using the same grammar as
  :mod:`page3_extractor.numbers`, and it classifies every other numeric-looking
  run rather than silently dropping it;
* it never decides what to publish. The family module decides, against a gate.

Coordinates
-----------
Spans come from PyMuPDF and are therefore already in the same frame as
:class:`page3_extractor.geometry.Word`. No transform is applied, and none is
needed; only pdfplumber geometry is transformed (see :mod:`geometry`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .numbers import STATE_NUMBER, normalize_number_text, parse_numeric_cell

BBox = tuple[float, float, float, float]

#: Space characters a French thousands grouping may use.
GROUPING_SPACES = "    "

#: One strict French number, grouped form first so ``1 966,010`` matches whole.
_NUMBER_IN_TEXT = re.compile(
    r"[+-]?\d{1,3}(?:[" + GROUPING_SPACES + r"]\d{3})+(?:,\d+)?"
    r"|[+-]?\d+(?:,\d+)?"
)

#: The same grammar without thousands grouping, used to re-read a grouped match
#: whose geometry refused it.
_UNGROUPED_NUMBER = re.compile(r"[+-]?\d+(?:,\d+)?")

#: Largest horizontal gap between two consecutive characters that a *single*
#: printed token may contain. A thousands-group space on these pages measures
#: 3.5 pt at the 12.5 pt body size; the narrowest gap between two values in
#: adjacent columns is tens of points. 6.0 pt separates the two cases with room
#: to spare and never joins across a column ruling.
MAX_INTERNAL_GAP = 6.0

PAREN_CHARS = "()﴾﴿（）"
_PAREN_SET = frozenset(PAREN_CHARS)

#: Every Arabic presentation form of م, the printed abbreviation for metre.
METRE_CHARS = "مﻡﻢﻣﻤ"
_METRE_SET = frozenset(METRE_CHARS)
_ARABIC_RUN = "؀-ۿﭐ-﻿"
_RUN_BEFORE = re.compile(f"[{_ARABIC_RUN}]+$")
_RUN_AFTER = re.compile(f"^[{_ARABIC_RUN}]+")

# --- token classification ------------------------------------------------ #
#: A run whose shape is the one every printed Mm3 volume on these pages has.
TOKEN_MEASUREMENT = "MEASUREMENT_CANDIDATE"
#: A water level printed inside a bracket, e.g. ``(الى مستوى 265 م)``.
TOKEN_LEVEL_QUALIFIER = "PARENTHETICAL_LEVEL_QUALIFIER"
#: Part of a printed unit marker, e.g. the ``3`` of ``مليون م3``.
TOKEN_UNIT_MARKER = "STRUCTURAL_UNIT_MARKER"
#: A bare integer that is neither of the above — a percentage, a count, a year.
TOKEN_BARE_INTEGER = "BARE_INTEGER"

TOKEN_CLASSES = (TOKEN_MEASUREMENT, TOKEN_LEVEL_QUALIFIER,
                 TOKEN_UNIT_MARKER, TOKEN_BARE_INTEGER)

#: A printed volume: at most three integer digits per group, comma, decimals.
_PRINTED_VOLUME = re.compile(r"^[+-]?\d{1,3}(?: \d{3})*,\d+$")


@dataclass(frozen=True)
class NativeChar:
    """One glyph, with the box the page itself gives it."""

    c: str
    bbox: BBox


@dataclass(frozen=True)
class NativeSpan:
    """One drawing run: uniform font, one text-showing operation."""

    text: str
    bbox: BBox
    chars: tuple[NativeChar, ...]
    font: str
    size: float
    origin: str
    line_dir: tuple[float, float]

    @property
    def y_mid(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0


@dataclass(frozen=True)
class NativeToken:
    """One strict numeric run lifted out of one span, with exact geometry."""

    text: str
    bbox: BBox
    parsed_value: Optional[float]
    token_class: str
    chars: tuple[NativeChar, ...]
    span_text: str
    span_bbox: BBox
    origin: str
    refusal: str = ""

    @property
    def is_measurement(self) -> bool:
        return self.token_class == TOKEN_MEASUREMENT and self.parsed_value is not None

    def evidence(self) -> str:
        return (f"{self.origin}|text={self.text}"
                f"|box=[{self.bbox[0]:.2f},{self.bbox[1]:.2f},"
                f"{self.bbox[2]:.2f},{self.bbox[3]:.2f}]"
                f"|class={self.token_class}"
                f"|span={self.span_text.strip()!r}")


# ---------------------------------------------------------------------- #
# Extraction
# ---------------------------------------------------------------------- #

def extract_spans(page, textpage) -> list[NativeSpan]:
    """All text spans of one page, from the TextPage that is already open.

    ``textpage`` is required. Passing ``None`` would make PyMuPDF build a second
    TextPage, which the architecture forbids and the counters would catch.
    """
    if textpage is None:
        raise ValueError(
            "extract_spans requires the page context's existing TextPage; "
            "building a second one violates the shared-context contract"
        )
    raw = page.get_text("rawdict", textpage=textpage)
    out: list[NativeSpan] = []
    for bi, block in enumerate(raw.get("blocks", ())):
        if block.get("type") != 0:
            continue
        for li, line in enumerate(block.get("lines", ())):
            direction = tuple(line.get("dir", (1.0, 0.0)))
            for si, span in enumerate(line.get("spans", ())):
                chars = tuple(
                    NativeChar(ch["c"], tuple(float(v) for v in ch["bbox"]))
                    for ch in span.get("chars", ())
                )
                if not chars:
                    continue
                out.append(NativeSpan(
                    text="".join(c.c for c in chars),
                    bbox=tuple(float(v) for v in span["bbox"]),
                    chars=chars,
                    font=str(span.get("font", "")),
                    size=float(span.get("size", 0.0)),
                    origin=f"b{bi}l{li}s{si}",
                    line_dir=(float(direction[0]), float(direction[1])),
                ))
    return out


def _is_metre_marker(text: str, start: int, end: int) -> bool:
    """True when the run at ``[start:end]`` sits beside a standalone م."""
    for m in (_RUN_BEFORE.search(text[:start]), _RUN_AFTER.search(text[end:])):
        if m is not None and len(m.group(0)) == 1 and m.group(0) in _METRE_SET:
            return True
    return False


def _classify(span: NativeSpan, text: str, start: int, end: int) -> str:
    whole = span.text
    if _is_metre_marker(whole, start, end):
        return (TOKEN_LEVEL_QUALIFIER if _PAREN_SET & set(whole)
                else TOKEN_UNIT_MARKER)
    if _PAREN_SET & set(whole) and not _PRINTED_VOLUME.match(normalize_number_text(text)):
        return TOKEN_LEVEL_QUALIFIER
    if _PRINTED_VOLUME.match(normalize_number_text(text)):
        return TOKEN_MEASUREMENT
    return TOKEN_BARE_INTEGER


def _run_geometry(span: NativeSpan, start: int, end: int) -> Optional[BBox]:
    """Union box of ``span.text[start:end]``, or ``None`` when it is not one run.

    Rejects a match whose characters are not laid out as a single left-to-right
    run with printer-sized gaps: that is how a token spanning two columns, or a
    numeric run inside a right-to-left span, is refused rather than parsed.
    """
    chars = span.chars[start:end]
    if not chars:
        return None
    prev = chars[0].bbox
    for ch in chars[1:]:
        box = ch.bbox
        if box[0] < prev[0] - 0.01:          # not monotone left to right
            return None
        if box[0] - prev[2] > MAX_INTERNAL_GAP:
            return None
        # A separator wide enough to be a column gap is a column gap, whether it
        # arrives as empty space between two boxes or as one very wide space
        # glyph. Both forms occur; only the first would be caught above.
        if ch.c.isspace() and box[2] - box[0] > MAX_INTERNAL_GAP:
            return None
        prev = box
    return (min(c.bbox[0] for c in chars), min(c.bbox[1] for c in chars),
            max(c.bbox[2] for c in chars), max(c.bbox[3] for c in chars))


def numeric_tokens(spans: Iterable[NativeSpan]) -> list[NativeToken]:
    """Every strict French numeric run in ``spans``, classified, with geometry."""
    out: list[NativeToken] = []
    for span in spans:
        text = span.text
        if len(text) != len(span.chars):
            # Character boxes must correspond one-to-one with the text, or the
            # geometry of a substring cannot be stated. Recorded, never parsed.
            continue
        for m in _NUMBER_IN_TEXT.finditer(text):
            box = _run_geometry(span, m.start(), m.end())
            if box is not None:
                out.append(_token(span, m.group(0), m.start(), m.end(), box))
                continue
            # The grouped reading does not survive its own geometry: the run
            # crosses a column gap, or the glyphs are not laid out left to
            # right. Fall back to the ungrouped numbers inside the same region
            # so two adjacent printed values are seen as two, not lost as one.
            recovered = False
            for sub in _UNGROUPED_NUMBER.finditer(m.group(0)):
                s0, s1 = m.start() + sub.start(), m.start() + sub.end()
                sub_box = _run_geometry(span, s0, s1)
                if sub_box is None:
                    continue
                out.append(_token(span, sub.group(0), s0, s1, sub_box))
                recovered = True
            if not recovered:
                out.append(NativeToken(
                    text=m.group(0), bbox=span.bbox, parsed_value=None,
                    token_class=TOKEN_BARE_INTEGER, chars=(),
                    span_text=span.text, span_bbox=span.bbox,
                    origin=span.origin,
                    refusal="RUN_IS_NOT_A_SINGLE_LEFT_TO_RIGHT_GLYPH_RUN"))
    return out


def _token(span: NativeSpan, run: str, start: int, end: int,
           box: BBox) -> NativeToken:
    parsed = parse_numeric_cell(run)
    value = parsed.parsed_value if parsed.semantic_state == STATE_NUMBER else None
    return NativeToken(
        text=run, bbox=box, parsed_value=value,
        token_class=_classify(span, run, start, end),
        chars=span.chars[start:end],
        span_text=span.text, span_bbox=span.bbox, origin=span.origin,
        refusal="" if value is not None else "NOT_A_STRICT_FRENCH_NUMBER",
    )


# ---------------------------------------------------------------------- #
# Geometry helpers
# ---------------------------------------------------------------------- #

def box_center(b: Sequence[float]) -> tuple[float, float]:
    return ((float(b[0]) + float(b[2])) / 2.0, (float(b[1]) + float(b[3])) / 2.0)


#: Vertical slack when deciding which ruled row a glyph run belongs to. It is
#: deliberately the same tolerance :func:`geometry.band_index` uses to assign a
#: *word* to a row, so the span layer and the word layer agree about what "the
#: same row" means.
ROW_TOLERANCE = 2.5


def in_row_band(box: Sequence[float], y0: float, y1: float,
                *, y_overlap: float = 0.5, tol: float = ROW_TOLERANCE) -> bool:
    """Whether a glyph run belongs to the ruled row band ``[y0, y1]``.

    Two ways to qualify, because two shapes occur:

    * the run's own vertical centre lies in the band (with the same slack the
      fragment grid gives a word) — this is the ordinary case, and it is what
      keeps the span layer and the word layer agreeing about rows;
    * or at least half the run's height lies inside the band.

    An overprinted row needs the first: its glyph run is 17 pt tall inside a
    7 pt band, because the second draw adds a ruling that splits the row. Judged
    on overlap alone such a run belongs to no row at all, which is how 7,213 R1
    cells lost their draw evidence in the first cut of this patch.
    """
    b0, b1 = float(box[1]), float(box[3])
    centre = (b0 + b1) / 2.0
    if y0 - tol <= centre <= y1 + tol:
        return True
    height = max(1e-6, b1 - b0)
    return (min(b1, y1) - max(b0, y0)) / height >= y_overlap


def tokens_in_cell(tokens: Iterable[NativeToken],
                   box: Sequence[float],
                   *,
                   x_pad: float = 1.0,
                   y_overlap: float = 0.5) -> list[NativeToken]:
    """Tokens whose horizontal extent lies in ``box`` and which share its row.

    Horizontal containment is strict — a printed value belongs to exactly one
    column and the column edges are rulings, not guesses.
    """
    x0, y0, x1, y1 = (float(v) for v in box)
    return [t for t in tokens
            if x0 - x_pad <= t.bbox[0] and t.bbox[2] <= x1 + x_pad
            and in_row_band(t.bbox, y0, y1, y_overlap=y_overlap)]


@dataclass(frozen=True)
class Ruling:
    """One straight drawn line, in the page's own coordinates."""

    position: float
    start: float
    end: float

    def covers(self, lo: float, hi: float, *, fraction: float = 0.6) -> bool:
        span = max(1e-6, hi - lo)
        return (min(self.end, hi) - max(self.start, lo)) / span >= fraction


@dataclass(frozen=True)
class RulingSet:
    """The page's own vertical and horizontal rulings."""

    vertical: tuple[Ruling, ...]
    horizontal: tuple[Ruling, ...]

    def column_edges(self, y0: float, y1: float,
                     x0: float, x1: float,
                     *, tol: float = 2.5) -> list[float]:
        """Vertical ruling positions that actually cross the band ``[y0, y1]``."""
        xs = [r.position for r in self.vertical
              if r.covers(y0, y1) and x0 - tol <= r.position <= x1 + tol]
        return _cluster(xs, tol)

    def row_edges(self, x0: float, x1: float,
                  y0: float, y1: float,
                  *, tol: float = 2.5) -> list[float]:
        ys = [r.position for r in self.horizontal
              if r.covers(x0, x1) and y0 - tol <= r.position <= y1 + tol]
        return _cluster(ys, tol)


def _cluster(values: Sequence[float], tol: float) -> list[float]:
    groups: list[list[float]] = []
    for v in sorted(float(x) for x in values):
        if groups and abs(v - groups[-1][-1]) <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


#: Below this a drawn line is treated as axis-parallel.
STRAIGHTNESS_TOLERANCE = 0.6


def collect_rulings(drawings: Iterable[dict]) -> RulingSet:
    """Split one ``page.get_drawings()`` result into axis-parallel rulings.

    Called with the drawings the page context already scanned; this module never
    scans them again.
    """
    vertical: list[Ruling] = []
    horizontal: list[Ruling] = []
    for d in drawings:
        for item in d.get("items", ()):
            kind = item[0]
            if kind == "l":
                p0, p1 = item[1], item[2]
                x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
                if abs(x0 - x1) <= STRAIGHTNESS_TOLERANCE:
                    vertical.append(Ruling((x0 + x1) / 2, min(y0, y1), max(y0, y1)))
                elif abs(y0 - y1) <= STRAIGHTNESS_TOLERANCE:
                    horizontal.append(Ruling((y0 + y1) / 2, min(x0, x1), max(x0, x1)))
            elif kind == "re":
                r = item[1]
                x0, y0, x1, y1 = float(r.x0), float(r.y0), float(r.x1), float(r.y1)
                vertical.append(Ruling(x0, y0, y1))
                vertical.append(Ruling(x1, y0, y1))
                horizontal.append(Ruling(y0, x0, x1))
                horizontal.append(Ruling(y1, x0, x1))
    return RulingSet(tuple(vertical), tuple(horizontal))


#: Characters that carry no glyph and only steer bidirectional layout. They
#: survive NFKC and would make an otherwise exact label comparison fail.
BIDI_CONTROLS = "‎‏‪‫‬‭‮⁦⁧⁨⁩؜"
_BIDI_TABLE = {ord(c): None for c in BIDI_CONTROLS}
TATWEEL = "ـ"


@dataclass(frozen=True)
class SpanLabel:
    """A row label assembled from the label column's own spans."""

    raw: str
    normalized: str
    level_qualifier: str
    removed_numerics: tuple[str, ...]
    spans: tuple[NativeSpan, ...]

    @property
    def resolved(self) -> bool:
        return bool(self.normalized)

    def evidence(self) -> str:
        parts = [f"spans={[s.text for s in self.spans]!r}",
                 f"raw={self.raw!r}", f"normalized={self.normalized!r}"]
        if self.level_qualifier:
            parts.append(f"level_qualifier={self.level_qualifier!r}")
        if self.removed_numerics:
            parts.append(f"numeric_removed={list(self.removed_numerics)!r}")
        return " ;; ".join(parts)


def assemble_label(spans: Sequence[NativeSpan]) -> SpanLabel:
    """Build a matchable row label out of the label column's spans.

    Right to left, because that is how the printed line reads; then Unicode
    NFKC (which folds the Arabic presentation forms back to letters), tatweel
    removal (the elongation the bulletins use for justification splits a name
    into fragments), bidi-control removal, and whitespace normalisation.

    The parenthetical level qualifier — ``ملاق (الى مستوى 265 م)`` — is *cut*,
    not deleted: it is returned separately, because it is a printed statement
    about the dam and belongs in evidence, just not in its name. The cut is at
    the first bracket of either kind, in either direction, because the visual
    order of a right-to-left line puts the closing bracket first.

    Any strict numeric run that survives is removed and recorded. On these pages
    a dam name never contains a digit, and a label that reads
    ``هرتم ه 66,127بو`` is a welded value, not a name.
    """
    ordered = sorted(spans, key=lambda s: -s.bbox[0])
    raw = " ".join(s.text for s in ordered).strip()

    s = unicodedata.normalize("NFKC", raw)
    s = s.replace(TATWEEL, "").translate(_BIDI_TABLE)
    s = re.sub(r"\s+", " ", s).strip()

    cut = min((s.index(ch) for ch in PAREN_CHARS if ch in s), default=-1)
    if cut >= 0:
        head, qualifier = s[:cut].strip(), s[cut:].strip()
    else:
        head, qualifier = s, ""

    removed: list[str] = []
    def _drop(m: "re.Match[str]") -> str:
        removed.append(m.group(0))
        return " "

    head = _NUMBER_IN_TEXT.sub(_drop, head)
    head = re.sub(r"\s+", " ", head).strip()
    return SpanLabel(raw=raw, normalized=head, level_qualifier=qualifier,
                     removed_numerics=tuple(removed), spans=tuple(ordered))


def spans_in_cell(spans: Iterable[NativeSpan],
                  box: Sequence[float],
                  *,
                  x_pad: float = 1.0,
                  y_overlap: float = 0.5) -> list[NativeSpan]:
    """Spans whose horizontal extent lies in ``box`` and which share its row."""
    x0, y0, x1, y1 = (float(v) for v in box)
    return [s for s in spans
            if x0 - x_pad <= s.bbox[0] and s.bbox[2] <= x1 + x_pad
            and in_row_band(s.bbox, y0, y1, y_overlap=y_overlap)]


def cell_band(rulings: RulingSet,
              frag_bbox: Sequence[float],
              row_y0: float,
              row_y1: float,
              value_x0: float,
              value_x1: float) -> Optional[BBox]:
    """The source-ruled cell that contains ``[value_x0, value_x1]`` in that row.

    Returns ``None`` when the page's own rulings do not bound the column, which
    is a refusal rather than a fallback to the shared grid.
    """
    edges = rulings.column_edges(row_y0, row_y1, float(frag_bbox[0]), float(frag_bbox[2]))
    if len(edges) < 2:
        return None
    mid = (float(value_x0) + float(value_x1)) / 2.0
    for i in range(len(edges) - 1):
        if edges[i] <= mid <= edges[i + 1]:
            return (edges[i], float(row_y0), edges[i + 1], float(row_y1))
    return None

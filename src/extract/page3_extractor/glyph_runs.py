"""The conditional glyph-run reader — the PDF's own draws, undeduplicated.

Why this module exists (PATCH-P5D-001)
--------------------------------------
The shared :class:`~page3_extractor.page_context.PageContext` builds one
TextPage with ``fitz.TEXTFLAGS_TEXT``, and that stays the fast path: it is the
flag set that preserves the C0 control substitution the damaged-file detector
depends on, and it recovers more numeric tokens on damaged files than the
default.

It has one measured cost, and Phase 5D proved it at the content-stream level.
``TEXTFLAGS_TEXT`` contains ``TEXT_MEDIABOX_CLIP``, and with that bit set MuPDF
suppresses one of two coincident glyphs: on an overprinted row it emits the
second draw's comma as a *space*. The page draws::

    1 966,010        (baseline 385.5601806640625)
    1 966,010        (baseline 385.4401855468750)

and the span layer built from that TextPage reports::

    1 966 010   and   1 966,010

which are two different numbers, so the strict-unanimity rule in
:mod:`page3_extractor.native_recovery` refuses the cell. The refusal is correct
given its input; the input is wrong. Measured on this build::

    flags 3   (ligatures|whitespace)        -> '1 966,010'  '1 966,010'
    flags 67  (… | TEXT_MEDIABOX_CLIP)      -> '1 966 010'  '1 966,010'
    flags 195 (TEXTFLAGS_TEXT)              -> '1 966 010'  '1 966,010'

The repair is *not* to loosen unanimity. ``1 966 010`` and ``1 966,010`` are
different numbers and no rule here prefers one over the other. The repair is to
apply the same unanimity to the draws **as the page draws them**.

What this module reads
----------------------
``page.get_texttrace()`` — the glyph trace of the content stream. Each element
is one text-showing run with its own ``seqno`` (its position in the stream) and
one tuple per glyph carrying the character and the box the page gives it. No
decoder configuration deduplicates it, nothing is clipped, and no second
document, TextPage or renderer is created. That is what "the printed glyph
sequence" means here.

The contract this module keeps
------------------------------
* it is read **only** when a caller has already refused a cell in the R1 T2
  overprint candidate class — never on the whole page, never on a healthy cell;
* it is memoized per page and charged to ``glyph_trace_extractions``;
* it reconstructs each *complete printed draw* independently and parses each one
  with the strict French grammar in :mod:`page3_extractor.numbers`;
* it publishes only when **every** complete printed draw parses to the identical
  value, and refuses on any disagreement or any ambiguity in the
  reconstruction;
* it infers nothing: not magnitude, not arithmetic, not identity. It has no
  access to the roster and no opinion about which dam a row is about;
* no OCR, no rendering, no rasterisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .numbers import STATE_NUMBER, parse_numeric_cell

BBox = tuple[float, float, float, float]

# ---------------------------------------------------------------------- #
# Tolerances. Every one of them is a measured property of this corpus.
# ---------------------------------------------------------------------- #

#: Glyphs of one text-showing run share a baseline exactly; the two draws of an
#: overprinted row are 0.12 pt apart. 0.05 pt separates the two cases and is far
#: below any real spacing on these pages.
BASELINE_CLUSTER_TOLERANCE = 0.05

#: How far apart two baselines may be and still be two draws of *one* printed
#: run. Phase 5D measured the overprint offset at 0.12 pt while the nearest
#: table row sits ~13 pt away.
OVERPRINT_PAIR_TOLERANCE = 0.6

#: Two complete draws are the same printed run when their horizontal extents
#: coincide. Same constant, same meaning, as ``native_recovery.DRAW_TOLERANCE``.
DRAW_EXTENT_TOLERANCE = 1.0

#: Two glyphs are the same printed character when their boxes coincide. The
#: measured overprint offset is 0.12 pt vertically and under 0.05 pt
#: horizontally.
GLYPH_COINCIDENCE = 0.5

#: Largest horizontal gap inside one printed token. Identical to
#: ``native_spans.MAX_INTERNAL_GAP``: a thousands-group space measures 3.5 pt at
#: the 12.5 pt body size and the narrowest gap between two values in adjacent
#: columns is tens of points.
MAX_INTERNAL_GAP = 6.0

#: Smallest horizontal gap that stands for a thousands-group separator when the
#: page positions the group rather than drawing a space glyph. Below this the
#: glyphs are simply adjacent.
THOUSANDS_GAP_MIN = 1.0

#: Slack when testing whether a drawn glyph belongs to the refused run.
#:
#: The vertical band comes from the refused run itself, not from the ruled row,
#: and that is not a convenience. An overprinted row draws a *second horizontal
#: ruling*, so the page's own rulings split one printed row into two grid bands
#: — on 304 corpus files the ROW08 band is a 4.7 pt sliver above the band the
#: glyphs actually occupy. Judged against either sliver the run belongs to
#: neither, which is how the first cut of this patch lost 913 cells.
#:
#: The refused run's span box is the right band because it is a *font* box on
#: the same baseline: ascender above the glyph tops, descender below the glyph
#: bottoms. It therefore contains its own glyphs by construction (measured
#: margin on this corpus: 3.6 pt each side) and excludes the neighbouring row's,
#: whose glyph box sticks out above it by 10 pt.
ANCHOR_SLACK = 0.5

# ---------------------------------------------------------------------- #
# Refusal reasons
# ---------------------------------------------------------------------- #
GLYPH_TRACE_UNAVAILABLE = "GLYPH_TRACE_UNAVAILABLE"
NO_GLYPHS_IN_CELL = "NO_PRINTED_GLYPHS_IN_THE_SOURCE_RULED_CELL"
NOT_AN_OVERPRINT_PAIR = "FEWER_THAN_TWO_COMPLETE_PRINTED_DRAWS"
BASELINES_TOO_FAR_APART = "COMPLETE_DRAWS_ARE_NOT_TWO_DRAWS_OF_ONE_RUN"
DRAW_EXTENTS_DIFFER = "COMPLETE_DRAWS_OCCUPY_DIFFERENT_PRINTED_RUNS"
DRAW_NOT_STRICT_NUMBER = "A_COMPLETE_PRINTED_DRAW_IS_NOT_A_STRICT_FRENCH_NUMBER"
DRAWS_DISAGREE = "COMPLETE_PRINTED_DRAWS_DO_NOT_AGREE_ON_A_VALUE"
AMBIGUOUS_RECONSTRUCTION = "DRAW_RECONSTRUCTION_IS_AMBIGUOUS"
UNANIMOUS = "EVERY_COMPLETE_PRINTED_DRAW_PARSES_TO_THE_SAME_VALUE"

#: Written onto the cell and the fact when this path publishes a value.
RECOVERY_GLYPH_TRACE_UNANIMOUS = "OVERPRINT_GLYPH_TRACE_UNANIMOUS"


# ---------------------------------------------------------------------- #
# The trace
# ---------------------------------------------------------------------- #

@dataclass(frozen=True)
class TraceGlyph:
    """One glyph exactly as the content stream draws it."""

    c: str
    bbox: BBox
    origin_x: float
    origin_y: float
    seqno: int

    @property
    def is_space(self) -> bool:
        return self.c.isspace()


@dataclass(frozen=True)
class TraceRun:
    """One text-showing run of the content stream."""

    glyphs: tuple[TraceGlyph, ...]
    bbox: BBox
    seqno: int
    font: str
    size: float
    opacity: float
    direction: tuple[float, float]

    @property
    def text(self) -> str:
        return "".join(g.c for g in self.glyphs)


def extract_glyph_runs(page) -> list[TraceRun]:
    """Every text-showing run of one page, from the page's own glyph trace.

    ``page.get_texttrace()`` walks the content stream once and reports what was
    drawn. It is not a TextPage, it builds no second document, and no flag set
    of it removes a coincident glyph.
    """
    out: list[TraceRun] = []
    for span in page.get_texttrace():
        if span.get("type", 0) != 0:      # 0 = filled text; anything else is not
            continue
        seqno = int(span.get("seqno", len(out)))
        glyphs: list[TraceGlyph] = []
        for ch in span.get("chars", ()):  # (ucs, glyph_id, origin, bbox)
            try:
                ucs = int(ch[0])
                origin = ch[2]
                box = ch[3] if len(ch) > 3 else None
            except (IndexError, TypeError, ValueError):
                continue
            if box is None:
                continue
            glyphs.append(TraceGlyph(
                c=chr(ucs),
                bbox=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
                origin_x=float(origin[0]),
                origin_y=float(origin[1]),
                seqno=seqno,
            ))
        if not glyphs:
            continue
        bbox = span.get("bbox")
        if bbox is None:
            bbox = (min(g.bbox[0] for g in glyphs), min(g.bbox[1] for g in glyphs),
                    max(g.bbox[2] for g in glyphs), max(g.bbox[3] for g in glyphs))
        direction = tuple(span.get("dir", (1.0, 0.0)))
        out.append(TraceRun(
            glyphs=tuple(glyphs),
            bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
            seqno=seqno,
            font=str(span.get("font", "")),
            size=float(span.get("size", 0.0)),
            opacity=float(span.get("opacity", 1.0)),
            direction=(float(direction[0]), float(direction[1])),
        ))
    return out


# ---------------------------------------------------------------------- #
# One reconstructed printed draw
# ---------------------------------------------------------------------- #

@dataclass(frozen=True)
class PrintedDraw:
    """One complete draw of one printed run, reconstructed from its glyphs."""

    text: str
    bbox: BBox
    baseline: float
    seqnos: tuple[int, ...]
    glyph_count: int
    collapsed_duplicate_glyphs: int
    inserted_group_separators: int
    parsed_value: Optional[float]
    parse_state: str
    refusal: str = ""

    @property
    def has_digit(self) -> bool:
        return any(ch.isdigit() for ch in self.text)

    @property
    def is_complete(self) -> bool:
        """A draw that carries a number to read. A punctuation-only remnant of a
        partially decoded copy is *not* a second reading; it is a fragment, and
        the reconstruction has to account for it separately."""
        return self.has_digit

    def evidence(self) -> str:
        return (f"seq={'+'.join(str(s) for s in self.seqnos)}"
                f"|text={self.text}"
                f"|box=[{self.bbox[0]:.2f},{self.bbox[1]:.2f},"
                f"{self.bbox[2]:.2f},{self.bbox[3]:.2f}]"
                f"|baseline={self.baseline:.4f}"
                f"|glyphs={self.glyph_count}"
                + (f"|collapsed={self.collapsed_duplicate_glyphs}"
                   if self.collapsed_duplicate_glyphs else "")
                + (f"|inserted_group_sep={self.inserted_group_separators}"
                   if self.inserted_group_separators else "")
                + (f"|refusal={self.refusal}" if self.refusal else ""))


@dataclass(frozen=True)
class GlyphTraceReading:
    """What the page's own draws say about one cell."""

    outcome: str
    value: Optional[float] = None
    text: str = ""
    complete_draws: tuple[PrintedDraw, ...] = ()
    fragments: tuple[PrintedDraw, ...] = ()
    cell_box: Optional[BBox] = None
    note: str = ""

    @property
    def unanimous(self) -> bool:
        return self.outcome == UNANIMOUS and self.value is not None

    def evidence_text(self) -> str:
        parts = []
        if self.cell_box:
            parts.append("glyph_trace_cell=[{:.2f},{:.2f},{:.2f},{:.2f}]".format(
                *self.cell_box))
        parts.extend(f"printed_draw{i + 1}={d.evidence()}"
                     for i, d in enumerate(self.complete_draws))
        parts.extend(f"fragment{i + 1}={d.evidence()}"
                     for i, d in enumerate(self.fragments))
        parts.append(f"outcome={self.outcome}")
        if self.note:
            parts.append(f"note={self.note}")
        return " ;; ".join(parts)


# ---------------------------------------------------------------------- #
# Reconstruction
# ---------------------------------------------------------------------- #

def glyphs_in_cell(runs: Iterable[TraceRun],
                   box: Sequence[float],
                   anchor_box: Sequence[float],
                   *,
                   x_pad: float = 1.0) -> list[TraceGlyph]:
    """Every drawn glyph of the refused run.

    Two separate questions, answered by two separate boxes:

    * **which column?** ``box`` — the cell the *page's own vertical rulings*
      bound. Horizontal containment is strict, exactly as
      :func:`native_spans.tokens_in_cell` applies it, so a printed value belongs
      to one column and the column edges stay rulings rather than guesses.
    * **which printed run?** ``anchor_box`` — the extent of the very run the
      span layer read and refused. Not the ruled row: an overprinted row draws
      its own extra horizontal ruling, so the ruled row is split and the glyphs
      belong to neither half of it. See :data:`ANCHOR_SLACK`.
    """
    x0, _cy0, x1, _cy1 = (float(v) for v in box)
    _ax0, ay0, _ax1, ay1 = (float(v) for v in anchor_box)
    out: list[TraceGlyph] = []
    for run in runs:
        for g in run.glyphs:
            if g.bbox[0] < x0 - x_pad or g.bbox[2] > x1 + x_pad:
                continue
            if g.bbox[1] < ay0 - ANCHOR_SLACK or g.bbox[3] > ay1 + ANCHOR_SLACK:
                continue
            out.append(g)
    return out


def _cluster_baselines(glyphs: Sequence[TraceGlyph]) -> list[list[TraceGlyph]]:
    """Split glyphs into draws by their baseline.

    One text-showing run puts every glyph on exactly one baseline, so a baseline
    *is* a draw. Runs that a font change split in two rejoin here, which is why
    the grouping is by baseline rather than by ``seqno``.
    """
    groups: list[list[TraceGlyph]] = []
    for g in sorted(glyphs, key=lambda z: (z.origin_y, z.bbox[0])):
        if groups and abs(groups[-1][-1].origin_y - g.origin_y) <= BASELINE_CLUSTER_TOLERANCE:
            groups[-1].append(g)
        else:
            groups.append([g])
    return groups


def _assemble(glyphs: Sequence[TraceGlyph]) -> PrintedDraw:
    """Reconstruct one draw's printed text from its glyphs, left to right.

    Three things happen here and nothing else:

    * **co-located duplicates collapse.** A page that draws the same glyph twice
      at the same place has printed one character, not two. Collapsing is exact:
      same character, boxes within :data:`GLYPH_COINCIDENCE`. Two glyphs that
      differ in either respect are both kept, and the draw then says what it
      says — possibly something that will not parse, which is a refusal.
    * **a positioned thousands group becomes a space.** These pages usually draw
      the separator as a real space glyph, and then this does nothing. When the
      page positions the group instead, a gap wider than
      :data:`THOUSANDS_GAP_MIN` and no wider than :data:`MAX_INTERNAL_GAP`
      reconstructs as one space. The strict grammar still has to accept the
      result: ``19 66,010`` is not a French number and is refused.
    * **a gap wider than one token refuses the draw.** Two values in adjacent
      columns are never welded into one reading.
    """
    ordered = sorted(glyphs, key=lambda g: (g.bbox[0], g.bbox[1]))
    kept: list[TraceGlyph] = []
    collapsed = 0
    for g in ordered:
        if any(k.c == g.c
               and abs(k.bbox[0] - g.bbox[0]) <= GLYPH_COINCIDENCE
               and abs(k.bbox[2] - g.bbox[2]) <= GLYPH_COINCIDENCE
               for k in kept):
            collapsed += 1
            continue
        kept.append(g)

    pieces: list[str] = []
    inserted = 0
    refusal = ""
    prev: Optional[TraceGlyph] = None
    for g in kept:
        if prev is not None:
            gap = g.bbox[0] - prev.bbox[2]
            if gap > MAX_INTERNAL_GAP:
                refusal = "GLYPHS_ARE_NOT_ONE_PRINTED_TOKEN"
            elif (gap > THOUSANDS_GAP_MIN and not g.is_space
                  and not prev.is_space):
                pieces.append(" ")
                inserted += 1
        pieces.append(g.c)
        prev = g

    text = "".join(pieces).strip()
    bbox = (min(g.bbox[0] for g in kept), min(g.bbox[1] for g in kept),
            max(g.bbox[2] for g in kept), max(g.bbox[3] for g in kept))
    baseline = kept[0].origin_y

    value: Optional[float] = None
    state = ""
    if not refusal:
        parsed = parse_numeric_cell(text, allow_text_states=False)
        state = parsed.semantic_state
        if parsed.semantic_state == STATE_NUMBER:
            value = parsed.parsed_value
        else:
            refusal = DRAW_NOT_STRICT_NUMBER

    return PrintedDraw(
        text=text, bbox=bbox, baseline=baseline,
        seqnos=tuple(sorted({g.seqno for g in kept})),
        glyph_count=len(kept), collapsed_duplicate_glyphs=collapsed,
        inserted_group_separators=inserted,
        parsed_value=value, parse_state=state, refusal=refusal,
    )


def _fragment_is_accounted_for(fragment: PrintedDraw,
                               complete: Sequence[PrintedDraw],
                               glyphs_by_baseline: dict[float, list[TraceGlyph]],
                               ) -> bool:
    """Whether a digit-free remnant belongs to a draw that was already read.

    A partially decoded second copy can leave a lone ``,``. That is harmless
    only when every glyph it does carry sits exactly on the matching character
    of a complete draw — which proves it is the *same* printed run and not a
    second, differently-read one. Any glyph that lands elsewhere means the
    reconstruction cannot say how many draws the cell holds, and the cell is
    refused rather than guessed.
    """
    frag_glyphs = glyphs_by_baseline.get(fragment.baseline, [])
    if not frag_glyphs:
        return False
    for g in frag_glyphs:
        if g.is_space:
            continue
        matched = False
        for d in complete:
            for other in glyphs_by_baseline.get(d.baseline, []):
                if (other.c == g.c
                        and abs(other.bbox[0] - g.bbox[0]) <= GLYPH_COINCIDENCE
                        and abs(other.bbox[2] - g.bbox[2]) <= GLYPH_COINCIDENCE):
                    matched = True
                    break
            if matched:
                break
        if not matched:
            return False
    return True


def read_overprint_cell(runs: Optional[Sequence[TraceRun]],
                        box: Sequence[float],
                        anchor_box: Sequence[float]) -> GlyphTraceReading:
    """Read one overprinted cell from the page's own draws under unanimity.

    ``box`` is the source-ruled cell that fixes the column; ``anchor_box`` is
    the extent of the run the span layer refused, which fixes the printed row.
    Returns a value only when that run holds two or more *complete printed
    draws* and every one of them parses, under the strict French grammar, to the
    identical number.
    """
    if runs is None:
        return GlyphTraceReading(GLYPH_TRACE_UNAVAILABLE)
    cell_box = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))

    glyphs = glyphs_in_cell(runs, cell_box, anchor_box)
    if not glyphs:
        return GlyphTraceReading(NO_GLYPHS_IN_CELL, cell_box=cell_box)

    groups = _cluster_baselines(glyphs)
    by_baseline = {g[0].origin_y: list(g) for g in groups}
    draws = [_assemble(g) for g in groups]
    complete = tuple(d for d in draws if d.is_complete)
    fragments = tuple(d for d in draws if not d.is_complete)

    base = dict(cell_box=cell_box, complete_draws=complete, fragments=fragments)

    if len(complete) < 2:
        return GlyphTraceReading(
            NOT_AN_OVERPRINT_PAIR, **base,
            note=f"{len(complete)} complete printed draw(s) in this cell; the "
                 f"overprint recovery class requires at least two")

    baselines = [d.baseline for d in complete]
    if max(baselines) - min(baselines) > OVERPRINT_PAIR_TOLERANCE:
        return GlyphTraceReading(
            BASELINES_TOO_FAR_APART, **base,
            note=f"baseline spread {max(baselines) - min(baselines):.3f} pt "
                 f"exceeds {OVERPRINT_PAIR_TOLERANCE} pt; these are different "
                 f"printed rows, not two draws of one run")

    x0s = [d.bbox[0] for d in complete]
    x1s = [d.bbox[2] for d in complete]
    if (max(x0s) - min(x0s) > DRAW_EXTENT_TOLERANCE
            or max(x1s) - min(x1s) > DRAW_EXTENT_TOLERANCE):
        return GlyphTraceReading(
            DRAW_EXTENTS_DIFFER, **base,
            note="the complete draws do not occupy the same horizontal extent, "
                 "so they are two printed runs and not two draws of one")

    refused = [d for d in complete if d.refusal]
    if refused:
        return GlyphTraceReading(
            DRAW_NOT_STRICT_NUMBER, **base,
            note="; ".join(f"{d.text!r}:{d.refusal}" for d in refused))

    values = {d.parsed_value for d in complete}
    if len(values) > 1:
        return GlyphTraceReading(
            DRAWS_DISAGREE, **base,
            note="draws parse to " + ", ".join(
                f"{d.text!r}={d.parsed_value}" for d in complete))

    unaccounted = [f for f in fragments
                   if not _fragment_is_accounted_for(f, complete, by_baseline)]
    if unaccounted:
        return GlyphTraceReading(
            AMBIGUOUS_RECONSTRUCTION, **base,
            note="a co-located draw carries glyphs no complete reading accounts "
                 "for: " + ", ".join(repr(f.text) for f in unaccounted))

    texts = {d.text for d in complete}
    note = ""
    if len(texts) > 1:
        note = ("complete draws differ textually but parse to the same value: "
                + ", ".join(repr(t) for t in sorted(texts)))
    if fragments:
        note = ((note + "; ") if note else "") + (
            f"{len(fragments)} digit-free fragment(s), every glyph landing on "
            f"the matching character of a complete draw; recorded as "
            f"corroboration, never as a value")

    return GlyphTraceReading(
        UNANIMOUS, value=complete[0].parsed_value, text=complete[0].text,
        **base, note=note)

"""Family-facing recovery of a printed value from the page's own span layer.

One rule, stated once
---------------------
A numeric cell may take a value from the native span layer when, and only when:

1. the cell's column band is bounded by **the table's own vertical rulings** in
   that row's y-band, and its row band is the fragment's own row;
2. exactly **one printed run** of digits lies inside that cell;
3. every *draw* of that run parses, under the strict French grammar, to the
   **same** value.

Condition 3 is the overprint guard. On overprinted rows the page draws the same
run twice; the two draws are two independent readings, and if they disagree the
cell is refused. A punctuation difference is a disagreement:
``1 933 597`` and ``1 933,597`` are different numbers and no rule here prefers
one over the other.

The one conditional second reading (1.2.0rc2, PATCH-P5D-001)
------------------------------------------------------------
Unanimity is only as good as the draws it is given. Phase 5D proved at the
content-stream level that the shared TextPage's own flag set —
``TEXTFLAGS_TEXT``, which contains ``TEXT_MEDIABOX_CLIP`` — suppresses one of
two coincident glyphs and emits an overprinted comma as a space, so the span
layer reports ``1 966 010`` and ``1 966,010`` where the page draws ``1 966,010``
twice. That is a false disagreement manufactured by the reader.

So when, and only when, this rule refuses a cell **because its draws disagreed
or a draw would not parse**, and the caller has declared the cell a member of
the R1 T2 overprint candidate class, the same cell is read once more from
:mod:`page3_extractor.glyph_runs` — the page's own text-showing runs, which no
decoder deduplicates. The rule applied there is the same rule: every complete
printed draw must parse, under the same strict French grammar, to the identical
value, or the cell stays refused.

Nothing else changes. The fast path is untouched, the span-layer reading is
untouched, and a cell that the span layer never refused never reaches the glyph
trace. There is no rule anywhere that a comma and a missing comma are
compatible; they are not, and both readings still have to agree.

Condition 2 is what keeps a second printed number in the same cell — and a
water level such as ``(الى مستوى 265 م)`` in the label column — from ever being
harvested as a measurement.

Nothing here decides publication policy. It returns an outcome and its
evidence; the family module applies it behind a named gate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence

from .evidence import CellEvidence
from .glyph_runs import (
    GLYPH_TRACE_UNAVAILABLE,
    OVERPRINT_PAIR_TOLERANCE,
    RECOVERY_GLYPH_TRACE_UNANIMOUS,
    GlyphTraceReading,
    read_overprint_cell,
)
from .native_spans import (
    NativeToken,
    TOKEN_BARE_INTEGER,
    TOKEN_MEASUREMENT,
    cell_band,
    tokens_in_cell,
)
from .numbers import STATE_NUMBER, STATE_UNPARSEABLE

# --- outcomes ----------------------------------------------------------- #
RCV_RECOVERED = "RECOVERED"
RCV_NATIVE_UNAVAILABLE = "NATIVE_SPAN_LAYER_UNAVAILABLE"
RCV_NO_RULED_CELL = "NO_SOURCE_RULED_CELL_FOR_THIS_COLUMN"
RCV_NO_TOKEN = "NO_STRICT_NUMERIC_TOKEN_IN_THE_CELL"
RCV_MULTIPLE_RUNS = "MORE_THAN_ONE_PRINTED_RUN_IN_THE_CELL"
RCV_DRAWS_DISAGREE = "OVERPRINT_DRAWS_DO_NOT_AGREE_ON_A_VALUE"
RCV_DRAW_UNPARSEABLE = "A_DRAW_OF_THE_RUN_IS_NOT_A_STRICT_FRENCH_NUMBER"

# --- recovery methods, written onto the cell and the fact --------------- #
RECOVERY_RAWDICT_SPAN = "RAWDICT_SPAN_FALLBACK"
RECOVERY_OVERPRINT_UNANIMOUS = "OVERPRINT_UNANIMOUS"

#: The refusals that describe a cell where the page printed a run this rule
#: could not certify *because the reader damaged one of its draws*. Those, and
#: only those, are the R1 T2 overprint candidate class the conditional
#: glyph-trace reading may re-read.
#:
#: ``RCV_MULTIPLE_RUNS`` belongs here for a measured reason. On most overprinted
#: cells ``TEXT_MEDIABOX_CLIP`` removes a single coincident glyph — the comma —
#: and the two draws merely disagree. On some it removes more: ``10,809``
#: drawn twice comes back as ``10,809`` and ``0,809`` starting one digit
#: further right, which the run grouper reads as two *different* printed runs
#: and refuses without ever asking whether the draws agree. Same page class,
#: same cell, same cause, so the same re-read applies — and the glyph trace's
#: own guards are what keep it honest: a cell holding two genuinely different
#: printed values has them on **one** baseline, so it yields fewer than two
#: complete draws and is refused.
OVERPRINT_CANDIDATE_OUTCOMES = (RCV_DRAWS_DISAGREE, RCV_DRAW_UNPARSEABLE,
                                RCV_MULTIPLE_RUNS)

#: Two numeric runs are the same printed run when their horizontal extents
#: coincide. Overprint draws land within a few hundredths of a point of each
#: other; two genuinely different values sit in different parts of the cell.
DRAW_TOLERANCE = 1.0

#: Classes a value cell may take. A parenthetical level and a unit marker are
#: never measurements, wherever they are found.
VALUE_CLASSES = (TOKEN_MEASUREMENT, TOKEN_BARE_INTEGER)


@dataclass(frozen=True)
class NativeRecovery:
    """A recovered value, or the reason there is none."""

    outcome: str
    value: Optional[float] = None
    text: str = ""
    method: str = ""
    cell_box: Optional[tuple[float, float, float, float]] = None
    draws: tuple[NativeToken, ...] = ()
    rejected: tuple[NativeToken, ...] = ()
    note: str = ""
    #: The page's own draws, when the conditional glyph-trace reading ran. It is
    #: ``None`` on every cell that never entered the overprint candidate class,
    #: which is what keeps the ordinary path's evidence byte-identical.
    glyph_trace: Optional[GlyphTraceReading] = None

    @property
    def recovered(self) -> bool:
        return self.outcome == RCV_RECOVERED and self.value is not None

    @property
    def found_candidate(self) -> bool:
        """True when the page prints something here that was refused.

        Distinguishes *the cell is empty on the page* from *the cell holds a
        printed run this rule would not certify*. Only the second may move a
        cell out of ``blank``; turning a genuinely empty cell into an
        unparseable candidate would invent a problem.
        """
        return self.outcome in (RCV_MULTIPLE_RUNS, RCV_DRAWS_DISAGREE,
                                RCV_DRAW_UNPARSEABLE)

    def evidence_text(self) -> str:
        parts = []
        if self.cell_box:
            parts.append("source_ruled_cell=[{:.2f},{:.2f},{:.2f},{:.2f}]".format(
                *self.cell_box))
        parts.extend(f"draw{i + 1}={t.evidence()}" for i, t in enumerate(self.draws))
        parts.extend(f"refused={t.evidence()}|why={t.refusal or t.token_class}"
                     for t in self.rejected)
        if self.glyph_trace is not None:
            parts.append(self.glyph_trace.evidence_text())
        if self.note:
            parts.append(f"note={self.note}")
        return " ;; ".join(parts)


def _group_draws(tokens: Sequence[NativeToken]) -> list[list[NativeToken]]:
    """Group tokens that occupy the same horizontal extent — one printed run."""
    groups: list[list[NativeToken]] = []
    for t in sorted(tokens, key=lambda z: (z.bbox[0], z.bbox[1])):
        placed = False
        for g in groups:
            if (abs(g[0].bbox[0] - t.bbox[0]) <= DRAW_TOLERANCE
                    and abs(g[0].bbox[2] - t.bbox[2]) <= DRAW_TOLERANCE):
                g.append(t)
                placed = True
                break
        if not placed:
            groups.append([t])
    return groups


def recover_cell_from_native_spans(ctx,
                                   frag,
                                   row: int,
                                   col: int,
                                   *,
                                   overprint_candidate_class: bool = False,
                                   ) -> NativeRecovery:
    """Try to read one numeric cell from the span layer of the open page.

    ``overprint_candidate_class`` is the caller's declaration that this cell
    belongs to the one class PATCH-P5D-001 covers — a T2 value cell on a page
    whose text regime is ``R1_c0_control_substitution``. It only ever *permits*
    the conditional second reading; it never publishes anything by itself, and
    every refusal below stays a refusal unless the page's own draws are
    unanimous.
    """
    if ctx is None or not getattr(ctx, "native_available", False):
        return NativeRecovery(RCV_NATIVE_UNAVAILABLE)
    grid = frag.cell(row, col)
    if grid is None:
        return NativeRecovery(RCV_NO_RULED_CELL, note="cell not in the grid")

    row_y0, row_y1 = frag.y_edges[row], frag.y_edges[row + 1]
    box = cell_band(ctx.source_rulings(), frag.bbox, row_y0, row_y1,
                    grid.bbox[0], grid.bbox[2])
    if box is None:
        return NativeRecovery(RCV_NO_RULED_CELL,
                              note="the page draws no vertical ruling pair "
                                   "bounding this column in this row")

    found = tokens_in_cell(ctx.native_numeric_tokens(), box)
    usable = [t for t in found if t.token_class in VALUE_CLASSES]
    rejected = tuple(t for t in found if t.token_class not in VALUE_CLASSES)
    if not usable:
        return NativeRecovery(RCV_NO_TOKEN, cell_box=box, rejected=rejected)

    groups = _group_draws(usable)
    if len(groups) > 1:
        reps = tuple(g[0] for g in groups)
        return _maybe_read_the_pages_own_draws(
            ctx, box, reps, rejected, overprint_candidate_class,
            NativeRecovery(
                RCV_MULTIPLE_RUNS, cell_box=box, draws=reps, rejected=rejected,
                note=f"{len(groups)} distinct printed runs; refusing to choose"))

    draws = tuple(groups[0])
    values = {t.parsed_value for t in draws}
    if None in values:
        return _maybe_read_the_pages_own_draws(
            ctx, box, draws, rejected, overprint_candidate_class,
            NativeRecovery(RCV_DRAW_UNPARSEABLE, cell_box=box, draws=draws,
                           rejected=rejected,
                           note="; ".join(sorted({t.refusal for t in draws if t.refusal}))))
    if len(values) > 1:
        return _maybe_read_the_pages_own_draws(
            ctx, box, draws, rejected, overprint_candidate_class,
            NativeRecovery(
                RCV_DRAWS_DISAGREE, cell_box=box, draws=draws, rejected=rejected,
                note="draws parse to " + ", ".join(
                    repr(t.text) + f"={t.parsed_value}" for t in draws)))

    corroborating, inconsistent = _co_located_marks(ctx, box, draws)
    if inconsistent:
        # A glyph sitting inside the number's own extent that does **not** land
        # on a matching character of the recovered run belongs to a second draw
        # that reads differently. The run is not unanimously readable.
        return _maybe_read_the_pages_own_draws(
            ctx, box, draws, rejected, overprint_candidate_class,
            NativeRecovery(
                RCV_DRAW_UNPARSEABLE, cell_box=box, draws=draws, rejected=rejected,
                note="a co-located draw carries glyphs this reading does not "
                     "account for: " + ", ".join(sorted(set(inconsistent)))))

    value = draws[0].parsed_value
    method = (RECOVERY_OVERPRINT_UNANIMOUS if len(draws) > 1
              else RECOVERY_RAWDICT_SPAN)
    note = ""
    if corroborating:
        note = ("a second draw of this run decoded only "
                + ", ".join(repr(t) for t in sorted(set(corroborating)))
                + ", each landing on the matching character of the recovered "
                  "value; recorded as corroboration, never as a value")
    return NativeRecovery(RCV_RECOVERED, value=value, text=draws[0].text,
                          method=method, cell_box=box, draws=draws,
                          rejected=rejected, note=note)


def _looks_like_one_overprinted_run(draws: Sequence[NativeToken]) -> bool:
    """Whether the refused draws are two draws of one run, not two rows.

    The expensive reading is worth doing only where the defect it repairs can
    occur: two or more readings of the same printed run, coincident to within
    the measured overprint offset. Anything further apart is a different printed
    row and no reader configuration would have joined them.
    """
    if len(draws) < 2:
        return False
    tops = [d.bbox[1] for d in draws]
    return max(tops) - min(tops) <= OVERPRINT_PAIR_TOLERANCE


def _maybe_read_the_pages_own_draws(ctx,
                                    box,
                                    draws: Sequence[NativeToken],
                                    rejected: Sequence[NativeToken],
                                    permitted: bool,
                                    refusal: NativeRecovery) -> NativeRecovery:
    """Re-read one refused overprint cell from the page's own glyph trace.

    Called only from a refusal, only for the declared R1 T2 overprint candidate
    class, and only where the refused draws are geometrically two draws of one
    printed run. Returns the refusal unchanged unless every complete printed
    draw the page contains parses to the identical value under the same strict
    grammar. The refusal always carries the glyph-trace evidence, so a cell that
    stays refused says why in the same terms as one that recovers.
    """
    if not permitted or not _looks_like_one_overprinted_run(draws):
        return refusal
    runs = getattr(ctx, "native_glyph_runs", None)
    if runs is None:
        return refusal
    # The refused run's own extent, not the ruled row: an overprinted row draws
    # a second horizontal ruling that splits the ruled row in two, and the
    # glyphs then belong to neither half.
    anchor = (min(d.bbox[0] for d in draws), min(d.bbox[1] for d in draws),
              max(d.bbox[2] for d in draws), max(d.bbox[3] for d in draws))
    reading = read_overprint_cell(runs(), box, anchor)
    if reading.outcome == GLYPH_TRACE_UNAVAILABLE:
        return refusal
    if not reading.unanimous:
        return replace(refusal, glyph_trace=reading)
    return NativeRecovery(
        RCV_RECOVERED, value=reading.value, text=reading.text,
        method=RECOVERY_GLYPH_TRACE_UNANIMOUS, cell_box=refusal.cell_box,
        draws=tuple(draws), rejected=tuple(rejected), glyph_trace=reading,
        note="the span layer's draws disagreed only because "
             "TEXT_MEDIABOX_CLIP suppressed a coincident glyph; the page's own "
             f"{len(reading.complete_draws)} complete printed draws are "
             "unanimous"
             + (f"; {reading.note}" if reading.note else ""))


#: How much of a stray glyph run must lie inside the recovered run's horizontal
#: extent before it is treated as part of the same printed run. A label in
#: another column does not overlap at all; a comma left behind by a partially
#: decoded second draw lies entirely inside.
CO_LOCATED_OVERLAP = 0.5

#: How closely a co-draw's glyph must sit on its counterpart to be the same
#: printed character. The overprint offset measured on this corpus is 0.12 pt
#: vertically and under 0.05 pt horizontally.
GLYPH_COINCIDENCE = 0.5


def _co_located_marks(ctx, box, draws):
    """Split glyph runs overlapping the recovered run into two kinds.

    A row drawn twice can leave a second draw that decodes *partially* — on this
    corpus, a lone ``,`` where the digits mapped to nothing. That is not a
    competing reading: it carries no value. But it is only harmless if every
    glyph it did decode lands on the *matching* character of the value that was
    recovered. A comma sitting exactly on the recovered value's comma says the
    two draws agree about where the decimal point is; a glyph anywhere else says
    they do not, and the cell is refused.

    Returns ``(corroborating, inconsistent)``.
    """
    from .native_spans import spans_in_cell

    if not hasattr(ctx, "native_spans"):
        return [], []
    x0 = min(d.bbox[0] for d in draws)
    x1 = max(d.bbox[2] for d in draws)
    claimed = {d.origin for d in draws}
    chars = [c for d in draws for c in d.chars]

    corroborating: list[str] = []
    inconsistent: list[str] = []
    for s in spans_in_cell(ctx.native_spans(), box):
        if s.origin in claimed or not s.text.strip():
            continue
        width = max(1e-6, s.bbox[2] - s.bbox[0])
        if (min(s.bbox[2], x1) - max(s.bbox[0], x0)) / width < CO_LOCATED_OVERLAP:
            continue
        for ch in s.chars:
            if ch.c.isspace():
                continue
            if any(other.c == ch.c
                   and abs(other.bbox[0] - ch.bbox[0]) <= GLYPH_COINCIDENCE
                   and abs(other.bbox[2] - ch.bbox[2]) <= GLYPH_COINCIDENCE
                   for other in chars):
                corroborating.append(ch.c)
            else:
                inconsistent.append(ch.c)
    return corroborating, inconsistent


def apply_native_recovery(cell: CellEvidence,
                          result: NativeRecovery,
                          *,
                          gate: str) -> CellEvidence:
    """Return a copy of ``cell`` carrying the outcome of a native recovery.

    ``raw_text`` is never touched — the cell's own text stays exactly as the
    words layer read it, and the strict parse stays beside the adjudicated one.
    A refusal moves a cell out of ``blank`` into an explicit
    ``unparseable_numeric_candidate`` carrying its candidates, because a blank
    that hides a printed number is the defect this patch exists to remove.
    """
    evidence = f"cell_raw={cell.raw_text!r} ;; {result.evidence_text()}"
    if result.recovered:
        if result.glyph_trace is not None:
            n = len(result.glyph_trace.complete_draws)
            note = f"{n} complete printed draw(s) agree (page glyph trace)"
        else:
            note = f"{len(result.draws)} draw(s) agree"
        return replace(
            cell,
            normalized_text=result.text,
            parsed_value=result.value,
            semantic_state=STATE_NUMBER,
            parse_method=result.method,
            parse_note=note,
            recovered_value=result.value,
            recovery_method=result.method,
            recovery_gate=gate,
            recovery_evidence=evidence[:2000],
        )
    candidate = result.draws[0].parsed_value if result.draws else None
    return replace(
        cell,
        parsed_value=None,
        semantic_state=STATE_UNPARSEABLE,
        parse_method=result.outcome,
        parse_note=result.note,
        recovered_value=candidate,
        recovery_method="",
        recovery_gate=gate,
        recovery_evidence=evidence[:2000],
    )

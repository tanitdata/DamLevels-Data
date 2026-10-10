"""Bounded recovery of numbers PyMuPDF welded onto an adjacent Arabic word.

Scope, deliberately narrow
--------------------------
This module runs **only** on ``R2_presentation_forms`` pages and **only** on a
numeric cell that is empty or holds nothing but an orphan leading thousands
group. It does not change the tokenizer, the number grammar, cell assignment,
or any behaviour on R1/R3/R0 pages.

The defect it addresses, proven from the page's own geometry
------------------------------------------------------------
On presentation-form pages there is no space glyph between a numeric run and
the Arabic run beside it, so ``page.get_text("words")`` emits one token such as
``172,200ﺍﻟﻣﺧﺯﻭﻥ``. :func:`geometry.build_fragment` assigns a word to a cell by
the *word's own centre*, and that welded token's centre lies in the label
column — so the value column reads empty, or reads only the leading thousands
group ``1`` that stayed behind as its own token and is then published as a
complete number.

Measured on ``15-5-2022_3.pdf``: the T1 value cell ``r1c2`` spans
``x=[292.6, 382.1]`` and holds the token ``1`` at ``x=[309.7, 316.7]``; the
label cell ``r1c3`` holds ``172,200ﺍﻟﻣﺧﺯﻭﻥ`` at ``x=[320.2, 519.6]``. The digit
run therefore *starts inside the value cell* — 62 points of the donor token lie
within it — and the printed number is ``1 172,200``.

What makes a donor a donor
--------------------------
Four conditions, all geometric or lexical, none of them about magnitude:

1. the donor token's box overlaps the target cell's rectangle;
2. the digit run is the donor token's **leading** or **trailing** character run,
   and the corresponding token edge (``x0`` for leading, ``x1`` for trailing)
   lies inside the target cell's horizontal band — i.e. the number is physically
   printed in the value column;
3. the digit run has the shape every printed Mm3 value on these pages has:
   a French decimal comma with exactly three decimals;
4. the donor token carries no parenthesis and the run is not adjacent to a
   metre marker.

Conditions 2-4 are what keep ``(الى مستوى 265 م)`` — Mellegue's printed water
level, present on 343 T2 rows — out of the volume columns: ``265`` is a *middle*
run of its token, is a bare integer with no decimals, sits beside ``م``, and its
row carries parentheses.

Nothing here publishes a value
------------------------------
This module produces a *candidate* and its evidence. Whether the candidate is
published is decided by the calling family module against an identity the
bulletin itself printed (:mod:`t1_general_stock`, :mod:`t3_inflows`,
:mod:`t4_withdrawals`). A candidate that no printed identity confirms is
emitted as ``unparseable_numeric_candidate`` with a review item — never as a
number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .geometry import Fragment, GridCell, Word
from .numbers import ParsedCell, STATE_NUMBER, normalize_number_text, parse_numeric_cell
from .text_and_encoding import R2

#: Recovery is attempted on this regime and no other.
RECOVERY_REGIME = R2

RECOVERY_METHOD = "R2_FUSED_LABEL_TOKEN_SPLIT"

# --- outcome codes ------------------------------------------------------- #
RCV_NOT_ATTEMPTED = "NOT_ATTEMPTED"
RCV_NO_DONOR = "NO_DONOR_TOKEN"
RCV_AMBIGUOUS = "AMBIGUOUS_MULTIPLE_DONOR_RUNS"
RCV_NOT_A_NUMBER = "ASSEMBLED_TEXT_IS_NOT_A_NUMBER"
RCV_CANDIDATE = "CANDIDATE_AWAITING_IDENTITY_GATE"

# --- rejection reasons, kept separate so the review queue is actionable --- #
REJ_PARENTHETICAL = "DONOR_TOKEN_CONTAINS_PARENTHESIS"
REJ_METRE_MARKER = "DIGIT_RUN_ADJACENT_TO_METRE_MARKER"
REJ_NOT_EDGE_RUN = "DIGIT_RUN_IS_NOT_A_LEADING_OR_TRAILING_RUN"
REJ_SHAPE = "DIGIT_RUN_IS_NOT_A_PRINTED_DECIMAL_VOLUME"
REJ_GEOMETRY = "DIGIT_RUN_EDGE_OUTSIDE_THE_VALUE_COLUMN"
REJ_NO_OVERLAP = "DONOR_TOKEN_DOES_NOT_OVERLAP_THE_VALUE_CELL"

#: The shape every printed volume on these pages has: at most three integer
#: digits (a larger number is space-grouped, and the leading group lands in the
#: value cell), a comma, exactly three decimals. A bare integer such as ``265``
#: or ``115`` — a water level in metres — never matches.
PRINTED_VOLUME_RUN = re.compile(r"^[+-]?\d{1,3},\d{3}$")

_LEADING_RUN = re.compile(r"^[+-]?[\d,]*\d")
_TRAILING_RUN = re.compile(r"[+-]?[\d,]*\d$")
_ANY_DIGIT = re.compile(r"\d")

#: Both the standard letter and every Arabic presentation form of م, the printed
#: abbreviation for metre. A *standalone* م beside a digit run means the digits
#: are a level in metres; the same letter opening a word (``موزعة``) does not, so
#: the guard tests the whole adjacent letter run rather than one character.
METRE_CHARS = "مﻡﻢﻣﻤ"
_METRE_SET = frozenset(METRE_CHARS)
_ARABIC_RUN = "؀-ۿﭐ-﻿"
_RUN_BEFORE = re.compile(f"[{_ARABIC_RUN}]+$")
_RUN_AFTER = re.compile(f"^[{_ARABIC_RUN}]+")


def _is_metre_marker(text: str, start: int, end: int) -> bool:
    """True when the digit run at ``[start:end]`` sits beside a standalone م."""
    before = _RUN_BEFORE.search(text[:start])
    after = _RUN_AFTER.search(text[end:])
    for m in (before, after):
        if m is not None and len(m.group(0)) == 1 and m.group(0) in _METRE_SET:
            return True
    return False

PAREN_CHARS = "()﴾﴿（）"
_PAREN_SET = frozenset(PAREN_CHARS)

#: An orphan leading thousands group: at most three digits, no comma. This is
#: what stays behind in the value cell when the rest of the number is welded to
#: the label, and it is exactly the AUD-F-001 defect when published alone.
_ORPHAN_GROUP = re.compile(r"^[+-]?\d{1,3}$")


@dataclass(frozen=True)
class DonorSpan:
    """One digit run lifted out of one token, with everything needed to re-find it."""

    origin: str                     # "cell r1c3" | "overflow"
    token_text: str
    token_bbox: tuple[float, float, float, float]
    char_start: int
    char_end: int
    digit_text: str
    position: str                   # LEADING | TRAILING | OWN_CELL
    x_span_estimate: tuple[float, float]

    def as_evidence(self) -> str:
        x0, x1 = self.x_span_estimate
        return (f"{self.origin}|token={self.token_text}"
                f"|box=[{self.token_bbox[0]:.1f},{self.token_bbox[1]:.1f},"
                f"{self.token_bbox[2]:.1f},{self.token_bbox[3]:.1f}]"
                f"|chars={self.char_start}:{self.char_end}"
                f"|run={self.digit_text}|pos={self.position}"
                f"|x_est=[{x0:.1f},{x1:.1f}]")


@dataclass(frozen=True)
class RecoveryResult:
    """A candidate value, or the reason there is none."""

    outcome: str
    assembled_text: str = ""
    parsed: Optional[ParsedCell] = None
    donors: tuple[DonorSpan, ...] = ()
    rejections: tuple[str, ...] = ()
    note: str = ""

    @property
    def has_candidate(self) -> bool:
        return self.outcome == RCV_CANDIDATE and self.parsed is not None

    @property
    def value(self) -> Optional[float]:
        return self.parsed.parsed_value if self.parsed else None

    def evidence_text(self) -> str:
        return " ;; ".join(d.as_evidence() for d in self.donors)


def _overlaps(cell_box: Sequence[float], w: Word) -> float:
    return max(0.0, min(cell_box[2], w.x1) - max(cell_box[0], w.x0))


def _interp_span(w: Word, start: int, end: int, n_chars: int) -> tuple[float, float]:
    """Approximate the x span of ``text[start:end]`` inside a token's box.

    Linear in character count. Arabic presentation forms are wider than digits,
    so this is an *estimate* and is recorded as one: it is written to evidence,
    never used as a gate. The gates use the token's own ``x0`` / ``x1``, which
    are exact.
    """
    if n_chars <= 0:
        return (w.x0, w.x1)
    width = (w.x1 - w.x0) / n_chars
    return (round(w.x0 + start * width, 2), round(w.x0 + end * width, 2))


def _candidate_runs(w: Word, origin: str, cell_box: Sequence[float]
                    ) -> tuple[list[DonorSpan], list[str]]:
    """Digit runs of one donor token that survive every guard."""
    text = w.text or ""
    rejections: list[str] = []
    if not _ANY_DIGIT.search(text):
        return [], rejections
    if _PAREN_SET & set(text):
        return [], [REJ_PARENTHETICAL]
    if _overlaps(cell_box, w) <= 0.0:
        return [], [REJ_NO_OVERLAP]

    spans: list[DonorSpan] = []
    seen: set[tuple[int, int]] = set()
    for regex, position in ((_LEADING_RUN, "LEADING"), (_TRAILING_RUN, "TRAILING")):
        m = regex.search(text)
        if not m:
            continue
        start, end = m.start(), m.end()
        if (start, end) in seen:
            continue
        seen.add((start, end))
        run = m.group(0)
        # A standalone metre marker on either side of the run means the digits
        # are a water level, not a volume.
        if _is_metre_marker(text, start, end):
            rejections.append(REJ_METRE_MARKER)
            continue
        if not PRINTED_VOLUME_RUN.match(normalize_number_text(run)):
            rejections.append(REJ_SHAPE)
            continue
        edge = w.x0 if position == "LEADING" else w.x1
        if not (cell_box[0] <= edge <= cell_box[2]):
            rejections.append(REJ_GEOMETRY)
            continue
        spans.append(DonorSpan(
            origin=origin, token_text=text, token_bbox=w.bbox,
            char_start=start, char_end=end, digit_text=run, position=position,
            x_span_estimate=_interp_span(w, start, end, len(text)),
        ))

    # A digit run that is neither leading nor trailing is a run *inside* the
    # token — the printed-water-level shape — and is recorded as refused.
    if not spans and _ANY_DIGIT.search(text) and not rejections:
        rejections.append(REJ_NOT_EDGE_RUN)
    return spans, rejections


def _own_cell_orphans(cell: Optional[GridCell]) -> list[DonorSpan]:
    """Bare <=3-digit groups already sitting in the target cell."""
    if cell is None:
        return []
    out = []
    for w in cell.words:
        t = normalize_number_text(w.text or "")
        if _ORPHAN_GROUP.match(t):
            out.append(DonorSpan(
                origin="own_cell", token_text=w.text, token_bbox=w.bbox,
                char_start=0, char_end=len(w.text), digit_text=t,
                position="OWN_CELL", x_span_estimate=(round(w.x0, 2), round(w.x1, 2)),
            ))
    return out


def cell_is_recovery_eligible(cell: Optional[GridCell]) -> bool:
    """True when this numeric cell is one the fusion defect can have emptied.

    Either the cell is empty, or everything in it is a bare group of at most
    three digits — the orphan leading thousands group. A cell that already holds
    a complete printed number is never touched.
    """
    if cell is None or not cell.words:
        return True
    texts = [normalize_number_text(w.text or "") for w in cell.words]
    return bool(texts) and all(_ORPHAN_GROUP.match(t) for t in texts)


def try_recover(frag: Fragment,
                row: int,
                value_col: int,
                cell_evidence,
                *,
                text_regime: str) -> Optional["RecoveryResult"]:
    """Attempt a recovery, or return ``None`` when this cell is out of scope.

    Out of scope means: not an R2 page, or the cell already holds a complete
    printed number. Both leave the 1.0.0 reading of the cell untouched.
    """
    if text_regime != RECOVERY_REGIME:
        return None
    cell = frag.cell(row, value_col)
    strict = cell_evidence.strict_semantic_state or cell_evidence.semantic_state
    if strict not in ("blank", STATE_NUMBER):
        # A dash, a hydraulic text state or an upstream error is a printed
        # state, not a gap the fusion defect could have opened.
        return None
    if not cell_is_recovery_eligible(cell):
        return None
    result = recover_numeric_cell(frag, row, value_col, text_regime=text_regime)
    if result.outcome in (RCV_NOT_ATTEMPTED, RCV_NO_DONOR):
        return None
    return result


def recover_numeric_cell(frag: Fragment,
                         row: int,
                         value_col: int,
                         *,
                         text_regime: str) -> RecoveryResult:
    """Attempt a bounded recovery for one numeric cell of one fragment row."""
    if text_regime != RECOVERY_REGIME:
        return RecoveryResult(RCV_NOT_ATTEMPTED, note="text_regime is not R2")

    cell = frag.cell(row, value_col)
    if cell is None:
        return RecoveryResult(RCV_NOT_ATTEMPTED, note="cell not in the grid")
    box = cell.bbox

    donors: list[DonorSpan] = []
    rejections: list[str] = []

    for c in range(frag.n_cols):
        if c == value_col:
            continue
        other = frag.cell(row, c)
        if other is None:
            continue
        for w in other.words:
            spans, rej = _candidate_runs(w, f"cell r{row}c{c}", box)
            donors.extend(spans)
            rejections.extend(rej)

    # Words that overlap this fragment but landed in no cell at all: on R2 the
    # welded token's centre can fall between two fragments, which takes the
    # printed number out of the grid entirely.
    for w in frag.overflow_words:
        if not (box[1] <= w.cy <= box[3]):
            continue
        spans, rej = _candidate_runs(w, "overflow", box)
        donors.extend(spans)
        rejections.extend(rej)

    if not donors:
        return RecoveryResult(RCV_NO_DONOR, rejections=tuple(sorted(set(rejections))))
    if len(donors) > 1:
        return RecoveryResult(
            RCV_AMBIGUOUS, donors=tuple(donors),
            rejections=tuple(sorted(set(rejections))),
            note=f"{len(donors)} donor digit runs qualify; refusing to choose")

    parts = _own_cell_orphans(cell) + list(donors)
    # Visual order: a French number reads left to right, and the orphan group is
    # printed to the left of the group that was welded away.
    parts.sort(key=lambda d: d.x_span_estimate[0] if d.position != "TRAILING"
               else d.token_bbox[2])
    assembled = " ".join(p.digit_text for p in parts)
    parsed = parse_numeric_cell(assembled)
    if parsed.semantic_state != STATE_NUMBER:
        return RecoveryResult(RCV_NOT_A_NUMBER, assembled_text=assembled,
                              parsed=parsed, donors=tuple(parts),
                              rejections=tuple(sorted(set(rejections))))
    return RecoveryResult(RCV_CANDIDATE, assembled_text=assembled, parsed=parsed,
                          donors=tuple(parts),
                          rejections=tuple(sorted(set(rejections))))

"""Evidence identity, the cell-evidence record, and the long-form fact record.

Every published value points at an ``evidence_id`` that resolves to exactly one
cell of one fragment of one source file. Evidence ids are deterministic: the
same input under the same configuration mints the same id, which is what makes
the rerun-hash test meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace
from typing import Any, Optional, Sequence

from .geometry import Fragment, GridCell
from .numbers import (
    ParsedCell,
    STATE_BLANK,
    STATE_UNPARSEABLE,
    dedupe_overprint,
    is_numeric_token,
    parse_label_cell,
    parse_numeric_cell,
)
from .text_and_encoding import decode_for_display, join_ltr, join_rtl

EVIDENCE_ID_VERSION = "1"


def evidence_id(source_sha256: str, fragment_rank: int, row: int, col: int) -> str:
    """``EV1-<sha12>-F<rank>-r<row>c<col>`` — stable and human-checkable."""
    return f"EV{EVIDENCE_ID_VERSION}-{source_sha256[:12]}-F{fragment_rank}-r{row}c{col}"


def record_id(family: str, source_sha256: str, key: str) -> str:
    return f"{family}-{source_sha256[:12]}-{key}"


@dataclass
class CellEvidence:
    """One grid cell, exactly as read, with its provenance."""

    evidence_id: str
    fragment_rank: int
    row_index: int
    column_index: int
    column_index_rtl: int
    bbox: tuple[float, float, float, float]
    ruled: bool
    raw_text: str
    normalized_text: str
    decoded_text_ar: str
    encoding_repair_status: str
    encoding_repair_method: str
    parsed_value: Optional[float]
    semantic_state: str
    parse_method: str
    parse_note: str
    token_count: int
    duplicate_token_count: int
    overprint_deduplicated: bool
    join_direction: str
    engine: str = "pymupdf_words"
    #: What the cell's own text parsed to before any recovery was considered.
    #: Kept beside the adjudicated reading so ``p3_cell_evidence`` can publish
    #: both, and so the strict parse is never lost.
    strict_parsed_value: Optional[float] = None
    strict_semantic_state: str = ""
    #: Set only when :mod:`fused_recovery` produced a candidate for this cell.
    recovered_value: Optional[float] = None
    recovery_method: str = ""
    recovery_gate: str = ""
    recovery_evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bbox_x0"], d["bbox_y0"], d["bbox_x1"], d["bbox_y1"] = self.bbox
        d.pop("bbox")
        return d


@dataclass
class Fact:
    """One extracted scalar or explicit textual state — the publication grain."""

    family_id: str
    record_type: str
    record_id: str
    fragment_rank: int
    row_label_raw: str = ""
    row_label_ar: str = ""
    row_label_en: str = ""
    canonical_field_id: str = ""
    canonical_name: str = ""
    raw_text: str = ""
    decoded_text_ar: str = ""
    parsed_value: Optional[float] = None
    value_type: str = "measure"
    unit: str = ""
    temporal_reference: str = ""
    semantic_state: str = ""
    region_id: str = ""
    dam_id: str = ""
    dam_candidate: str = ""
    match_method: str = ""
    match_confidence: Optional[float] = None
    source_node_id: str = ""
    destination_node_id: str = ""
    via_node_id: str = ""
    is_accounting_observation: bool = False
    schema_id: str = ""
    layout_slot: str = ""
    column_semantics_method: str = ""
    anchor_confirmation: str = ""
    evidence_id: str = ""
    extraction_status: str = "EXTRACTED"
    validation_status: str = "NOT_CHECKED"
    review_status: str = "NONE"
    comparison_status: str = "NOT_COMPARED"
    notes: str = ""
    # --- 1.1.0 additive columns ------------------------------------------ #
    #: Readable labels drawn from the semantic registries, so a reviewer can
    #: read any published row without opening the PDF. They never overwrite
    #: ``row_label_raw`` (the label exactly as read) or ``row_label_ar`` (what
    #: this page's text layer yielded, garbled on R1 and fused on R2).
    canonical_label_ar: str = ""
    canonical_label_en: str = ""
    #: Whether the *source's own arithmetic* reconciles for this fact. Separate
    #: from extraction quality on purpose: a correctly read number must not
    #: become unusable because a printed aggregate disagrees with its parts.
    source_consistency_status: str = "NOT_CHECKED"
    #: Set only on a fact whose value came from :mod:`fused_recovery`.
    recovery_method: str = ""
    recovery_gate: str = ""
    recovery_evidence: str = ""
    # --- 1.2.0 additive columns ------------------------------------------ #
    #: The row label exactly as the layer it was read from gave it, and the
    #: string the roster was actually matched against. Kept apart so raw
    #: evidence is never presented as a user-facing label, and so a reviewer can
    #: see what normalisation did.
    dam_candidate_raw: str = ""
    dam_candidate_normalized: str = ""
    #: Whether the *entity* behind this row is resolved. Deliberately separate
    #: from ``extraction_status``: a number can be authentic at row-slot grain
    #: while its dam is unknown, and publishing one without the other would be
    #: worse than publishing neither.
    identity_status: str = "IDENTITY_NOT_APPLICABLE"
    #: Usability of this fact's own family on this page. Equal to the value in
    #: ``p3_family_status``; published so a page whose only partial family is T2
    #: is distinguishable from one with a T1/T3/T4/T5/T6 defect.
    family_usability_status: str = ""


# ---------------------------------------------------------------------- #
# Identity vocabulary (1.2.0)
# ---------------------------------------------------------------------- #
IDENTITY_RESOLVED = "IDENTITY_RESOLVED"
IDENTITY_RESOLVED_CANDIDATE = "IDENTITY_RESOLVED_ROSTER_ENTRY_CANDIDATE"
IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED_NO_EXACT_MATCH"
IDENTITY_UNRESOLVABLE_REGIME = "IDENTITY_UNRESOLVABLE_TEXT_REGIME"
IDENTITY_LABEL_ABSENT = "IDENTITY_ROW_LABEL_ABSENT"
IDENTITY_NOT_APPLICABLE = "IDENTITY_NOT_APPLICABLE"

IDENTITY_STATUSES = (
    IDENTITY_RESOLVED, IDENTITY_RESOLVED_CANDIDATE, IDENTITY_UNRESOLVED,
    IDENTITY_UNRESOLVABLE_REGIME, IDENTITY_LABEL_ABSENT, IDENTITY_NOT_APPLICABLE,
)


@dataclass
class PendingRecovery:
    """A recovery candidate waiting for the printed identity that would confirm it.

    Held between reading the cells of a family and adjudicating them, because
    the identity that gates a T3 regional value spans two fragments and is not
    knowable while the row is being read.
    """

    fact: "Fact"
    cell: "CellEvidence"
    cell_index: int
    result: Any
    field_id: str = ""


@dataclass
class FamilyResult:
    """What one T-family produced for one page."""

    family_id: str
    fragment_ranks: tuple[int, ...]
    status: str
    facts: list[Fact] = field(default_factory=list)
    cells: list[CellEvidence] = field(default_factory=list)
    review_items: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    schema_id: str = ""
    row_count: int = 0
    notes: list[str] = field(default_factory=list)
    pending_recoveries: list[PendingRecovery] = field(default_factory=list)

    def add_cell(self, cell: CellEvidence) -> int:
        self.cells.append(cell)
        return len(self.cells) - 1

    def add_review(self, reason: str, entity_id: str, priority: str = "medium", **extra: Any) -> None:
        item = {"section_id": self.family_id, "entity_id": entity_id,
                "review_reason": reason, "priority": priority}
        item.update(extra)
        self.review_items.append(item)

    def add_failure(self, code: str, message: str, *, stage: str = "extraction",
                    severity: str = "error", **extra: Any) -> None:
        item = {"section_id": self.family_id, "failure_stage": stage,
                "failure_code": code, "severity": severity, "message": message}
        item.update(extra)
        self.failures.append(item)


FAMILY_OK = "OK"
FAMILY_PARTIAL = "PARTIAL"
FAMILY_ABSENT = "FRAGMENT_ABSENT"
FAMILY_UNRESOLVED = "UNRESOLVED_SHAPE"
FAMILY_QUARANTINED = "QUARANTINED"


# ---------------------------------------------------------------------- #
# The three separated quality vocabularies
# ---------------------------------------------------------------------- #
#: ``extraction_status`` answers one question only: did this extractor read the
#: cell faithfully? It says nothing about whether the source's arithmetic
#: reconciles — that is ``source_consistency_status`` — and nothing about
#: whether a human should look — that is ``review_status``.
EXTRACTED = "EXTRACTED"
UNPARSEABLE = "UNPARSEABLE"
SOURCE_BLANK = "SOURCE_BLANK"
UPSTREAM_ERROR = "UPSTREAM_ERROR"

EXTRACTION_STATUSES = (EXTRACTED, UNPARSEABLE, SOURCE_BLANK, UPSTREAM_ERROR)

#: ``source_consistency_status`` answers: does the *bulletin's own* printed
#: arithmetic hold for this fact?
SOURCE_CONSISTENT = "SOURCE_CONSISTENT"
SOURCE_ROUNDING_DIFFERENCE = "SOURCE_ROUNDING_DIFFERENCE"
SOURCE_ARITHMETIC_INCONSISTENCY = "SOURCE_ARITHMETIC_INCONSISTENCY"
NOT_CHECKED = "NOT_CHECKED"

SOURCE_CONSISTENCY_STATUSES = (
    SOURCE_CONSISTENT, SOURCE_ROUNDING_DIFFERENCE,
    SOURCE_ARITHMETIC_INCONSISTENCY, NOT_CHECKED,
)

#: A printed state the extractor captured exactly is EXTRACTED: a dash, a
#: hydraulic text state and a row the era does not print are all faithful
#: readings, and ``semantic_state`` already says which one. Only a cell that
#: could not be resolved, an empty cell, and an upstream spreadsheet error get
#: their own extraction status.
_EXTRACTION_BY_STATE = {
    "numeric": EXTRACTED,
    "dash": EXTRACTED,
    "hydraulic_text_state": EXTRACTED,
    "text": EXTRACTED,
    # The era does not print this row at all, so the source supplies nothing
    # here. semantic_state still distinguishes it from a printed empty cell.
    "row_absent": SOURCE_BLANK,
    "blank": SOURCE_BLANK,
    "upstream_error": UPSTREAM_ERROR,
    "unparseable_numeric_candidate": UNPARSEABLE,
    "suspected_text_state": UNPARSEABLE,
}


def extraction_status_for(semantic_state: str) -> str:
    """Map a measured cell state onto the four extraction meanings."""
    return _EXTRACTION_BY_STATE.get(semantic_state, UNPARSEABLE)


REVIEW_NONE = "NONE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
REVIEW_TEXT_STATE = "REVIEW_TEXT_STATE"


# ---------------------------------------------------------------------- #
# Cell reading
# ---------------------------------------------------------------------- #

def read_cell(frag: Fragment,
              row: int,
              col: int,
              source_sha256: str,
              text_regime: str,
              *,
              numeric: bool) -> CellEvidence:
    """Read one grid cell into evidence.

    ``numeric`` selects the join direction and the parser: numbers read left to
    right (a space thousands group is a separate word), labels right to left.
    """
    cell: Optional[GridCell] = frag.cell(row, col)
    rank = frag.index
    eid = evidence_id(source_sha256, rank, row, col)

    if cell is None:
        return CellEvidence(
            evidence_id=eid, fragment_rank=rank, row_index=row, column_index=col,
            column_index_rtl=max(0, frag.n_cols - 1 - col),
            bbox=(0.0, 0.0, 0.0, 0.0), ruled=False,
            raw_text="", normalized_text="", decoded_text_ar="",
            encoding_repair_status="NO_CELL", encoding_repair_method="NONE",
            parsed_value=None, semantic_state=STATE_BLANK,
            parse_method="CELL_NOT_IN_GRID", parse_note="",
            token_count=0, duplicate_token_count=0, overprint_deduplicated=False,
            join_direction="none",
        )

    tokens = [(w.x0, w.y0, w.text) for w in cell.words]
    raw_all = join_ltr([(x, t) for x, _y, t in tokens]) if numeric else \
        join_rtl([(x, t) for x, _y, t in tokens])

    kept, removed = dedupe_overprint(tokens)
    join_dir = "ltr" if numeric else "rtl"
    text = join_ltr([(x, t) for x, _y, t in kept]) if numeric else \
        join_rtl([(x, t) for x, _y, t in kept])

    parsed: ParsedCell = parse_numeric_cell(text) if numeric else parse_label_cell(text)
    if numeric and parsed.semantic_state == STATE_UNPARSEABLE:
        parsed = _diagnose_unparseable(parsed, kept, removed)
    decoded, repair_status, repair_method = decode_for_display(text, text_regime)

    return CellEvidence(
        evidence_id=eid, fragment_rank=rank, row_index=row, column_index=col,
        column_index_rtl=max(0, frag.n_cols - 1 - col),
        bbox=cell.bbox, ruled=cell.ruled,
        raw_text=raw_all, normalized_text=parsed.normalized_text,
        decoded_text_ar=decoded,
        encoding_repair_status=repair_status, encoding_repair_method=repair_method,
        parsed_value=parsed.parsed_value, semantic_state=parsed.semantic_state,
        parse_method=parsed.parse_method, parse_note=parsed.parse_note,
        token_count=len(kept), duplicate_token_count=removed,
        overprint_deduplicated=removed > 0, join_direction=join_dir,
        strict_parsed_value=parsed.parsed_value,
        strict_semantic_state=parsed.semantic_state,
    )


#: ``parse_method`` values a recovered cell carries. Both name the mechanism, so
#: a reviewer never has to guess why a value differs from the cell's own text.
PARSE_R2_FUSED_CONFIRMED = "R2_FUSED_LABEL_RECOVERY_IDENTITY_CONFIRMED"
PARSE_R2_FUSED_UNCONFIRMED = "R2_FUSED_LABEL_RECOVERY_NOT_CONFIRMED"


def apply_recovery(cell: CellEvidence,
                   result,
                   *,
                   gate: str,
                   confirmed: bool) -> CellEvidence:
    """Return a copy of ``cell`` carrying the outcome of a bounded recovery.

    ``raw_text`` is never touched: the cell's own text stays exactly as read,
    and the strict parse stays beside the adjudicated one. A recovery that no
    printed identity confirmed leaves the cell ``unparseable_numeric_candidate``
    with a null value — the candidate is recorded as evidence, never published
    as a number.
    """
    from .numbers import STATE_NUMBER as _NUM

    value = result.value if confirmed else None
    state = _NUM if confirmed else STATE_UNPARSEABLE
    method = PARSE_R2_FUSED_CONFIRMED if confirmed else PARSE_R2_FUSED_UNCONFIRMED
    evidence = (f"value_cell_raw={cell.raw_text!r} ;; "
                f"assembled={result.assembled_text!r} ;; {result.evidence_text()}")
    if result.rejections:
        evidence += " ;; refused=" + ",".join(result.rejections)
    return replace(
        cell,
        normalized_text=result.assembled_text or cell.normalized_text,
        parsed_value=value,
        semantic_state=state,
        parse_method=method,
        parse_note=result.note or result.outcome,
        recovered_value=result.value,
        recovery_method=result.outcome if not confirmed else "R2_FUSED_LABEL_TOKEN_SPLIT",
        recovery_gate=gate,
        recovery_evidence=evidence[:2000],
    )


#: Signature of an overprinted numeric cell whose two copies PyMuPDF's word
#: segmentation interleaves, e.g. a printed ``67,815`` arriving as
#: ``["67", "67,815", "815"]``. The copies sit at *different* x positions, so
#: positional deduplication cannot collapse them, and the true value cannot be
#: recovered from the words layer without guessing which fragments belong to
#: which copy. Such cells stay unparsed with a null value; this only names the
#: cause so the review queue is actionable rather than generically "unparseable".
PARSE_OVERPRINT_INTERLEAVED = "OVERPRINT_INTERLEAVED_TOKENS"
PARSE_MULTIPLE_NUMERIC_TOKENS = "MULTIPLE_NUMERIC_TOKENS_NOT_A_GROUPING"


def _diagnose_unparseable(parsed: ParsedCell, tokens, removed: int) -> ParsedCell:
    texts = [t for _x, _y, t in tokens]
    numericish = [t for t in texts if any(ch.isdigit() for ch in t)]
    if len(numericish) < 2:
        return parsed

    interleaved = removed > 0 or any(
        a != b and (a.startswith(b) or b.startswith(a) or a.endswith(b) or b.endswith(a))
        for i, a in enumerate(numericish) for b in numericish[i + 1:]
    )
    method = PARSE_OVERPRINT_INTERLEAVED if interleaved else PARSE_MULTIPLE_NUMERIC_TOKENS
    note = (f"{len(numericish)} numeric fragments"
            + (f", {removed} exact duplicates removed" if removed else ""))
    return ParsedCell(parsed.raw_text, parsed.normalized_text, None,
                      parsed.semantic_state, method, note)


def stamp_fact_from_cell(fact: Fact, cell: CellEvidence) -> None:
    """Carry a cell's adjudicated reading onto the fact that publishes it."""
    from .numbers import STATE_NUMBER as _NUM

    fact.parsed_value = cell.parsed_value
    fact.semantic_state = cell.semantic_state
    fact.extraction_status = extraction_status_for(cell.semantic_state)
    # A *refused* recovery carries a gate and its evidence but deliberately no
    # method — there is no recovery to name. Both must still travel to the fact,
    # or the reason a printed number was not published stays invisible to
    # everyone reading the publication tables.
    if not (cell.recovery_method or cell.recovery_gate):
        return
    fact.recovery_method = cell.recovery_method
    fact.recovery_gate = cell.recovery_gate
    fact.recovery_evidence = cell.recovery_evidence
    if cell.semantic_state == _NUM:
        # The published raw text is the printed number as it appears on the
        # page, reassembled from the two physical pieces word segmentation
        # split. The untouched cell text stays in p3_cell_evidence.raw_text and
        # is repeated verbatim inside recovery_evidence.
        fact.raw_text = cell.normalized_text
    elif fact.review_status == REVIEW_NONE:
        fact.review_status = REVIEW_REQUIRED
    # A row that already carries an *identity* review status keeps it: the value
    # story is told by extraction_status, recovery_gate and the review item, and
    # collapsing two different open questions into one column would hide one of
    # them. Both are raised as review items either way.


def finalize_recovery(res: FamilyResult,
                      pending: PendingRecovery,
                      *,
                      gate: str,
                      confirmed: bool) -> None:
    """Apply a gate verdict to one pending recovery, in place."""
    cell = apply_recovery(pending.cell, pending.result, gate=gate, confirmed=confirmed)
    res.cells[pending.cell_index] = cell
    stamp_fact_from_cell(pending.fact, cell)


def cell_has_content(frag: Fragment, row: int, col: int) -> bool:
    c = frag.cell(row, col)
    return bool(c and c.words)


def numeric_columns_rtl(frag: Fragment, row: int) -> list[int]:
    """Column indices in ``row`` holding a numeric-looking value, right to left."""
    out = []
    for c in range(frag.n_cols - 1, -1, -1):
        cell = frag.cell(row, c)
        if not cell or not cell.words:
            continue
        joined = join_ltr([(w.x0, w.text) for w in cell.words])
        deduped, _ = dedupe_overprint([(w.x0, w.y0, w.text) for w in cell.words])
        joined = join_ltr([(x, t) for x, _y, t in deduped])
        if is_numeric_token(joined) or is_numeric_token(joined.replace(" ", "")):
            out.append(c)
    return out


def populated_columns(frag: Fragment, row: int) -> list[int]:
    return [c for c in range(frag.n_cols) if cell_has_content(frag, row, c)]


def rightmost_populated_column(frag: Fragment, row: int) -> Optional[int]:
    cols = populated_columns(frag, row)
    return cols[-1] if cols else None

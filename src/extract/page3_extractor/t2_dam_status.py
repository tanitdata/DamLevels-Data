"""T2 — selected dam / flood-protection status grid (FSM-02, fragment rank 2).

The row-label and roster problem is resolved *mechanically*: a data row is one
whose rightmost column carries a label and whose value columns carry numbers.
Nothing is inferred. A dam that is not printed on a given day produces **no
row** — never a zero row — and the day's measured roster is published so a
missing dam is visible as an absence.

Dam identity is matched against a versioned roster registry by normalized
label. An unmatched label becomes a candidate with ``match_confidence`` and a
review-queue entry; it never becomes a silent canonical id.

Three separate things, kept separate (1.2.0)
--------------------------------------------
**Numeric authenticity** — whether the number this row-slot publishes is the
number the page prints — and **entity identity** — which dam the row is about —
are different questions with different answers, and 1.2.0 stops letting one
withhold the other.

*PATCH-P5C-001, numeric at row-slot grain.* On ``R2_presentation_forms`` pages
the value is welded onto the Arabic label by word segmentation, so the value
column reads empty. The value is unambiguous one level down: exactly one printed
run inside the cell the table's own vertical rulings bound. That value is
published at row-slot grain **whether or not the dam is identified**, with an
explicit ``identity_status`` beside it.

*PATCH-P5B-003, identity from the span layer.* On the same pages the dam name is
intact in the span layer as Arabic presentation forms; NFKC and tatweel removal
recover it exactly. The candidate marked those rows ``ROSTER_UNMATCHED``, which
blamed the roster for a label-assembly defect. Identity is published only on an
**exact** roster or alias match — no containment, no position, no guess.

*PATCH-P5B-002, R1 overprint.* On ``R1_c0_control_substitution`` pages an
overprinted row draws the same number twice and the words layer interleaves the
two copies. Each draw is parsed independently and a value is published only if
every draw yields the **same** value. It is not enough that the digits agree:
``1 933 597`` and ``1 933,597`` are different numbers, and a rule that preferred
the better-formatted draw would be choosing, not reading.

*PATCH-P5D-001, the draws the page actually makes.* The 1.2.0rc1 form of the
rule above refused 7,213 of those overprinted cells because the two draws
decoded a factor of 1,000 apart. Phase 5D read the content stream underneath
every decoder and proved the page draws them byte-identically: the disagreement
is manufactured by ``TEXT_MEDIABOX_CLIP``, a bit inside the ``TEXTFLAGS_TEXT``
set the shared TextPage must keep, which suppresses one of two coincident glyphs
and emits the second draw's comma as a space. 1.2.0rc2 does not weaken
unanimity — it gives unanimity the right draws, by re-reading *only* those
refused cells from the page's own glyph trace
(:mod:`page3_extractor.glyph_runs`). A cell publishes only if every complete
printed draw there parses to the identical value.

R1 dam identity stays unresolved, before and after that repair. Control
substitution genuinely destroys the label (``سيدي سعد`` extracts as
``دي دي د ـــد``), no positional assignment is ever made, and recovering a
number has never been evidence about whose number it is.
"""

from __future__ import annotations

from typing import Optional

from .anchors import AnchorResult, anchor_confirms
from .evidence import (
    FAMILY_ABSENT,
    FAMILY_OK,
    FAMILY_PARTIAL,
    FAMILY_UNRESOLVED,
    IDENTITY_LABEL_ABSENT,
    IDENTITY_RESOLVED,
    IDENTITY_RESOLVED_CANDIDATE,
    IDENTITY_UNRESOLVABLE_REGIME,
    IDENTITY_UNRESOLVED,
    Fact,
    FamilyResult,
    PendingRecovery,
    extraction_status_for,
    finalize_recovery,
    read_cell,
    record_id,
    stamp_fact_from_cell,
)
from .fused_recovery import try_recover
from .geometry import Fragment
from .native_recovery import apply_native_recovery, recover_cell_from_native_spans
from .native_spans import assemble_label, spans_in_cell
from .numbers import STATE_BLANK, STATE_NUMBER, STATE_UNPARSEABLE
from .roster import (
    STATUS_CANDIDATE,
    RosterRegistry,
    match_dam_label,
    match_span_label,
)
from .semantic_mapping import (
    FSM_ID,
    T2,
    T2_VALUE_ORDER_RTL,
    canonical_name,
    field_def,
)
from .text_and_encoding import R1

EXPECTED_COLS = 5
SCHEMA_ID_TEMPLATE = "T2_DAM_STATUS_{rows}ROW_5COL"
MIN_HEADER_ROWS = 2

#: Why a T2 value may be published while its dam is unknown. The gate is about
#: the *cell*, not the row's meaning: the page's own rulings bound the column,
#: the fragment's own row bounds the row, and exactly one printed run lies
#: inside it on which every draw agrees. Nothing about magnitude, neighbouring
#: rows or arithmetic is consulted.
T2_ROW_SLOT_GATE = (
    "SOURCE_RULED_CELL_HOLDS_EXACTLY_ONE_PRINTED_RUN_AND_EVERY_DRAW_AGREES:"
    "numeric authenticity is established at row-slot grain and is independent "
    "of dam identity, which is published separately in identity_status"
)

#: The 1.1.0 refusal, kept for the cells the native layer cannot resolve either.
T2_NO_IDENTITY_GATE = (
    "NO_PRINTED_IDENTITY_FOR_T2:the four printed columns do not determine each "
    "other; fill% vs stock/(stock+headroom_to_normal) agrees to one percentage "
    "point on only 89.5% of 34,380 clean rows, so it cannot certify a recovery"
)


def extract(frag: Optional[Fragment],
            source_sha256: str,
            text_regime: str,
            anchors: AnchorResult,
            roster: RosterRegistry,
            bulletin_date: Optional[str],
            *,
            ctx=None) -> FamilyResult:
    res = FamilyResult(family_id=T2, fragment_ranks=(2,), status=FAMILY_ABSENT)
    if frag is None:
        res.add_failure("T2_FRAGMENT_ABSENT", "fragment rank 2 not present")
        return res

    res.schema_id = SCHEMA_ID_TEMPLATE.format(rows=frag.n_rows)
    if frag.n_cols != EXPECTED_COLS:
        res.status = FAMILY_UNRESOLVED
        res.add_failure("T2_UNEXPECTED_COLUMN_COUNT",
                        f"expected {EXPECTED_COLS} columns got {frag.n_cols}")
        res.add_review("T2 grid column count not in the accepted registry", "T2-GRID", "high")
        return res

    confirmation = anchor_confirms(anchors, T2, frag.index)
    label_col = frag.n_cols - 1
    value_cols_rtl = list(range(frag.n_cols - 2, -1, -1))

    # Header rows are read as evidence, never as data.
    for r in range(MIN_HEADER_ROWS):
        for c in range(frag.n_cols):
            res.cells.append(read_cell(frag, r, c, source_sha256, text_regime, numeric=False))

    dam_rank = 0
    matched = 0
    candidate_identity = 0
    unmatchable_by_regime = 0
    span_resolved = 0
    unreadable: list[tuple[int, str, str]] = []
    fused: list[tuple[int, str]] = []
    native_recovered: list[tuple[int, str, Optional[float]]] = []
    native_refused: list[tuple[int, str, str]] = []

    for r in range(MIN_HEADER_ROWS, frag.n_rows):
        label = read_cell(frag, r, label_col, source_sha256, text_regime, numeric=False)
        values = [read_cell(frag, r, c, source_sha256, text_regime, numeric=True)
                  for c in value_cols_rtl]

        span_label = _span_label(ctx, frag, r, label_col, text_regime)
        has_span_name = span_label is not None and span_label.resolved

        has_label = label.semantic_state != STATE_BLANK and label.raw_text.strip() != ""
        has_number = any(v.semantic_state == STATE_NUMBER for v in values)
        if not has_label and not has_number and not has_span_name:
            # A geometry-only row (the empty trailing/footnote band, or the extra
            # ruling an overprinted row produces). Recorded, not published.
            res.notes.append(f"row {r}: no label and no value; not a dam row")
            continue
        if not has_label and not has_span_name:
            res.add_review("T2 row has values but no readable label",
                           f"T2-ROW-{r}-LABEL-MISSING", "high",
                           evidence_id=label.evidence_id)
            res.add_failure("T2_ROW_LABEL_MISSING", f"row {r} has values but no label",
                            severity="warning")

        res.cells.append(label)
        value_indices = [res.add_cell(v) for v in values]
        dam_rank += 1

        match = match_dam_label(label.decoded_text_ar or label.raw_text, roster,
                                text_regime=text_regime)
        # PATCH-P5B-003: where the label column is legible, the span layer is the
        # authority. It replaces a word-stream match only when it resolves a dam
        # id exactly; it never overwrites a match with a non-match.
        if has_span_name:
            span_match = match_span_label(span_label.normalized, roster)
            if span_match.dam_id:
                match = span_match
                span_resolved += 1
        if match.dam_id:
            matched += 1
            if match.registry_status == STATUS_CANDIDATE:
                candidate_identity += 1
                res.add_review(
                    f"T2 dam identity resolved to {match.dam_id} through a roster "
                    f"entry whose canonical id and English name a human has not "
                    f"confirmed (registry_status={match.registry_status}); the "
                    f"printed Arabic label and the row's position in the roster "
                    f"are measured, the Latin naming is corroborated only by a "
                    f"PROVISIONAL reference snapshot",
                    f"T2-ROW-{r}-ROSTER-ENTRY-CANDIDATE", "medium",
                    evidence_id=label.evidence_id)
        elif match.method == "TEXT_REGIME_R1_NOT_MATCHABLE":
            # Not a review item: on an R1 page the label *is* control
            # substitution, so no reviewer can resolve it from this evidence and
            # queueing it would bury the items that a human can actually act on.
            # It is a known limitation of the source, counted per file below and
            # published on every affected row as an explicit status.
            unmatchable_by_regime += 1
        else:
            res.add_review(
                f"T2 dam label unmatched in roster registry v{roster.version}",
                f"T2-ROW-{r}-ROSTER-UNMATCHED", "medium",
                evidence_id=label.evidence_id)

        identity_status = _identity_status(match, has_label or has_span_name,
                                           text_regime)
        candidate_raw, candidate_norm = _candidate_texts(label, span_label)

        for field_id, cell, cell_index, col in zip(
                T2_VALUE_ORDER_RTL, values, value_indices, value_cols_rtl):
            fd = field_def(field_id)
            fact = Fact(
                family_id=T2,
                record_type="dam_status",
                record_id=record_id(T2, source_sha256, f"ROW{dam_rank:02d}"),
                fragment_rank=frag.index,
                row_label_raw=label.raw_text,
                row_label_ar=label.decoded_text_ar,
                row_label_en=match.name_en,
                canonical_field_id=field_id,
                canonical_name=canonical_name(field_id),
                canonical_label_ar=match.candidate if match.dam_id else "",
                canonical_label_en=match.name_en,
                raw_text=cell.raw_text,
                decoded_text_ar=cell.decoded_text_ar,
                parsed_value=cell.parsed_value,
                value_type=fd.value_type if fd else "measure",
                unit=fd.unit if fd else "",
                temporal_reference=fd.temporal_reference if fd else "",
                semantic_state=cell.semantic_state,
                dam_id=match.dam_id,
                dam_candidate=candidate_norm or match.candidate,
                dam_candidate_raw=candidate_raw,
                dam_candidate_normalized=candidate_norm,
                identity_status=identity_status,
                match_method=match.method,
                match_confidence=match.confidence,
                schema_id=res.schema_id,
                layout_slot=f"{FSM_ID[2]}:r{r}c{cell.column_index}",
                column_semantics_method="POSITIONAL_RTL_AFTER_LABEL_COLUMN",
                anchor_confirmation=confirmation,
                evidence_id=cell.evidence_id,
                extraction_status=extraction_status_for(cell.semantic_state),
                review_status=_review_status(match),
                notes=f"roster_version={roster.version};"
                      f"roster_entry_status={match.registry_status}"
                      + (f";level_qualifier={span_label.level_qualifier}"
                         if span_label and span_label.level_qualifier else ""),
            )
            res.facts.append(fact)

            if cell.semantic_state == STATE_NUMBER:
                continue

            # PATCH-P5C-001 (R2) and PATCH-P5B-002 (R1) are the same rule, so
            # they are the same call. Only what the page prints differs.
            #
            # PATCH-P5D-001 adds one permission and no new rule: on an R1 page
            # a refusal caused by disagreeing draws may be re-read from the
            # page's own glyph trace, because TEXT_MEDIABOX_CLIP — which the
            # shared TextPage must keep — manufactures that disagreement by
            # suppressing a coincident comma. Unanimity still decides.
            outcome = recover_cell_from_native_spans(
                ctx, frag, r, col,
                overprint_candidate_class=(text_regime == R1))
            if outcome.recovered or outcome.found_candidate:
                fixed = apply_native_recovery(cell, outcome, gate=T2_ROW_SLOT_GATE)
                res.cells[cell_index] = fixed
                stamp_fact_from_cell(fact, fixed)
                if fixed.semantic_state == STATE_NUMBER:
                    native_recovered.append((r, field_id, fixed.parsed_value))
                else:
                    native_refused.append((r, field_id, outcome.outcome))
                continue

            # Nothing the span layer can bound: the 1.1.0 fused-token candidate
            # path still records what the word layer can see, unchanged.
            recovery = try_recover(frag, r, cell.column_index, cell,
                                   text_regime=text_regime)
            if recovery is not None:
                pending = PendingRecovery(fact=fact, cell=cell, cell_index=cell_index,
                                          result=recovery, field_id=field_id)
                res.pending_recoveries.append(pending)
                finalize_recovery(res, pending, gate=T2_NO_IDENTITY_GATE,
                                  confirmed=False)
                fused.append((r, field_id))
            elif cell.semantic_state == STATE_UNPARSEABLE:
                unreadable.append((r, field_id, cell.parse_method))

    res.row_count = dam_rank
    if dam_rank == 0:
        res.status = FAMILY_UNRESOLVED
        res.add_failure("T2_NO_DAM_ROWS", "grid present but no row qualified as a dam row")
    elif matched == dam_rank and not (native_refused or unreadable or fused):
        res.status = FAMILY_OK
    else:
        res.status = FAMILY_PARTIAL

    _report(res, unreadable, fused, native_recovered, native_refused,
            unmatchable_by_regime, dam_rank)
    res.notes.append(
        f"dam_rows={dam_rank} matched={matched} candidate_identity={candidate_identity} "
        f"span_label_identities={span_resolved} "
        f"native_recovered={len(native_recovered)} native_refused={len(native_refused)} "
        f"unmatchable_by_text_regime={unmatchable_by_regime} grid_rows={frag.n_rows}")
    return res


# ---------------------------------------------------------------------- #

def _span_label(ctx, frag: Fragment, row: int, label_col: int, text_regime: str):
    """Assemble the row label from the label column's own spans.

    Attempted on every regime whose text layer is legible. On R1 it is not: the
    control substitution destroys the glyph mapping, so the span layer carries
    exactly the same damage as the word layer and assembling it would only dress
    that damage up as a name.
    """
    if ctx is None or not getattr(ctx, "native_available", False):
        return None
    if text_regime == R1:
        return None
    cell = frag.cell(row, label_col)
    if cell is None:
        return None
    box = (cell.bbox[0], frag.y_edges[row], cell.bbox[2], frag.y_edges[row + 1])
    spans = spans_in_cell(ctx.native_spans(), box)
    if not spans:
        return None
    return assemble_label(spans)


def _candidate_texts(label, span_label) -> tuple[str, str]:
    """``(raw evidence, the string identity was matched against)``."""
    if span_label is not None:
        return span_label.raw, span_label.normalized
    return label.raw_text, (label.decoded_text_ar or "")


def _identity_status(match, has_label: bool, text_regime: str) -> str:
    if match.dam_id:
        return (IDENTITY_RESOLVED_CANDIDATE
                if match.registry_status == STATUS_CANDIDATE else IDENTITY_RESOLVED)
    if text_regime == R1:
        return IDENTITY_UNRESOLVABLE_REGIME
    if not has_label:
        return IDENTITY_LABEL_ABSENT
    return IDENTITY_UNRESOLVED


def _review_status(match) -> str:
    """Four different things, kept apart.

    A resolved identity, an identity resolved through a registry entry a human
    has not confirmed, an identity the source cannot express, and an identity
    the registry is missing are not the same finding, and collapsing them would
    hide how much of the roster question is actually open.
    """
    if match.dam_id:
        return ("ROSTER_ENTRY_CANDIDATE"
                if match.registry_status == STATUS_CANDIDATE else "NONE")
    if match.method == "TEXT_REGIME_R1_NOT_MATCHABLE":
        return "IDENTITY_UNRESOLVABLE_TEXT_REGIME"
    if match.method == "NO_LABEL":
        return "ROW_LABEL_ABSENT"
    return "ROSTER_UNMATCHED"


def _report(res: FamilyResult, unreadable, fused, native_recovered,
            native_refused, unmatchable_by_regime: int, dam_rank: int) -> None:
    """One review item per class per file, naming the rows affected."""
    if native_recovered:
        rows_hit = sorted({r for r, _f, _v in native_recovered})
        res.notes.append(
            f"T2 native recovery: {len(native_recovered)} value(s) on row(s) "
            f"{rows_hit} read from the source-ruled cell in the span layer, at "
            f"row-slot grain; dam identity is stated separately in "
            f"identity_status and was not used to certify any value")

    if native_refused:
        rows_hit = sorted({r for r, _f, _o in native_refused})
        reasons = sorted({o for _r, _f, o in native_refused})
        overprint = any(o.startswith("OVERPRINT") for o in reasons)
        res.add_review(
            f"{len(native_refused)} T2 value(s) on row(s) {rows_hit} sit in a "
            f"cell the page does print a numeric run into, but the run could not "
            f"be certified ({', '.join(reasons)}). "
            + ("The row is overprinted and the two draws decode to different "
               "numbers under this page's own font mapping, so neither may be "
               "published: preferring one would be choosing a value rather than "
               "reading it. " if overprint else "")
            + "Values left null, never zero; every draw and its coordinates are "
              "in recovery_evidence",
            "T2-VALUE-NOT-CERTIFIABLE", "high")
        res.add_failure("T2_VALUE_NOT_CERTIFIABLE",
                        f"{len(native_refused)} values refused on rows {rows_hit}: "
                        + ", ".join(reasons), severity="warning")

    if unreadable:
        rows_hit = sorted({r for r, _f, _m in unreadable})
        methods = sorted({m for _r, _f, m in unreadable})
        res.add_review(
            f"{len(unreadable)} T2 values on grid row(s) {rows_hit} could not be "
            f"parsed ({', '.join(methods)}); the printed value is visible on the "
            "page but its glyph runs interleave in the text layer, so it is not "
            "recoverable without OCR or a visual read. Values left null, never zero",
            "T2-UNREADABLE-VALUES", "high")
        res.add_failure("T2_VALUE_UNPARSEABLE",
                        f"{len(unreadable)} values unparseable on rows {rows_hit}",
                        severity="warning")

    if fused:
        rows_hit = sorted({r for r, _f in fused})
        res.add_review(
            f"{len(fused)} T2 values on grid row(s) {rows_hit} are printed on the "
            "page but welded onto the adjacent Arabic label by this "
            "presentation-form page's word segmentation, and the span layer could "
            "not bound them to a single source-ruled cell either. The digits were "
            "split out and recorded as candidates on each cell's evidence, but no "
            "value is published. See recovery_evidence for the reassembled "
            "candidate and recovery_gate for why it was refused",
            "T2-FUSED-VALUES-NOT-CONFIRMABLE", "high")
        res.add_failure("T2_FUSED_VALUE_NOT_RECOVERABLE",
                        f"{len(fused)} fused values on rows {rows_hit}: "
                        + T2_NO_IDENTITY_GATE, severity="warning")

    if unmatchable_by_regime:
        # One row per file, not per dam: the limitation is the page's text
        # regime, and it is the same limitation for every row on that page.
        res.add_review(
            f"{unmatchable_by_regime} of {dam_rank} T2 dam labels are unmatchable "
            "because the page's text layer is C0 control substitution; the values "
            "are extracted and published, the dam identity is not resolvable from "
            "this source and would need the original bulletin or targeted OCR",
            "T2-ROSTER-TEXT-REGIME", "low")

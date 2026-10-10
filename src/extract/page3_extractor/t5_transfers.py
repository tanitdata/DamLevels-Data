"""T5 — pumped transfers (FSM-08, fragment rank 8).

The distinction this module exists to protect (KB-CONN-T5, CLM-022):

* rows 1-3 are **physical transfer edges**;
* row 4, ``إيرادات سد سجنان باعتماد التحويل``, is a **receiving-node accounting
  observation** restating rows 2+3. It is never a graph edge, and nothing in
  this package will emit it as one.

Both eras are supported: the two-row era (edges 1-2 only, shape ``[3,5]``) and
the four-row era (shape ``[5,5]``, with the narrower ``[5,4]`` variant). A row
that is simply not printed in the two-row era is ``row_absent`` — never zero.

The transfer balance (row 4 versus rows 2+3) is computed as a **diagnostic**
and never as a hard failure.

PATCH-P5B-001 (1.2.0)
---------------------
On ``R2_presentation_forms`` pages the daily-transfer value is printed but was
published as **blank** on 1,029 facts across 343 files. The cause is word
welding, not a missing value: PyMuPDF emits ``0,351ﻣﻥ`` as one word whose box
runs from the value column to the label column, so cell assignment by centre
puts the whole thing in the label column. The digits are visible in
``row_label_raw`` on every one of the 1,029.

The repair reads the page's own span layer for that one cell — the column band
comes from the vertical rulings the table itself draws — and publishes the value
only when **exactly one** strict French number belongs to the cell. Two, or
none, leave the cell in an explicit non-blank state carrying its candidates. A
printed ``0,000`` stays numeric zero, because a measured zero and no data are
different facts.
"""

from __future__ import annotations

from typing import Optional

from .anchors import AnchorResult, anchor_confirms
from .evidence import (
    FAMILY_ABSENT,
    FAMILY_OK,
    FAMILY_PARTIAL,
    FAMILY_UNRESOLVED,
    Fact,
    FamilyResult,
    extraction_status_for,
    read_cell,
    record_id,
    stamp_fact_from_cell,
)
from .geometry import Fragment
from .native_recovery import (
    RECOVERY_RAWDICT_SPAN,
    apply_native_recovery,
    recover_cell_from_native_spans,
)
from .numbers import STATE_BLANK, STATE_NUMBER, STATE_ROW_ABSENT
from .semantic_mapping import (
    ACCOUNTING,
    EDGE,
    FSM_ID,
    T5,
    TRANSFER_ROW_BY_RANK,
    TRANSFER_VALUE_ORDER_RTL,
    TWO_ROW_ERA_RANKS,
    canonical_name,
    field_def,
)
from .text_and_encoding import R2

ACCEPTED_SHAPES = {(3, 5): 2, (5, 5): 4, (5, 4): 4}
HEADER_ROWS = 1

#: The daily-transfer field. It is the only T5 column the welding defect empties,
#: because it is the column physically adjacent to the Arabic label.
DAILY_FIELD = "p3_t5_transfer_day_mm3"

#: What must hold before an R2 T5 daily blank may be filled from the span layer.
T5_DAILY_GATE = (
    "EXACTLY_ONE_STRICT_FRENCH_NUMBER_IN_THE_SOURCE_RULED_DAILY_CELL:"
    "the column band comes from the table's own vertical rulings and the row "
    "band from the fragment's own row; no magnitude, neighbour or label "
    "position is consulted"
)


def extract(frag: Optional[Fragment],
            source_sha256: str,
            text_regime: str,
            anchors: AnchorResult,
            *,
            ctx=None) -> FamilyResult:
    res = FamilyResult(family_id=T5, fragment_ranks=(8,), status=FAMILY_ABSENT)
    if frag is None:
        res.add_failure("T5_FRAGMENT_ABSENT", "fragment rank 8 not present")
        return res

    expected_rows = ACCEPTED_SHAPES.get(frag.shape)
    if expected_rows is None:
        res.status = FAMILY_UNRESOLVED
        res.schema_id = f"T5_UNSEEN_{frag.n_rows}x{frag.n_cols}"
        res.add_failure("T5_UNSEEN_SHAPE",
                        f"shape {list(frag.shape)} is not one of the accepted "
                        f"{sorted(list(s) for s in ACCEPTED_SHAPES)}")
        res.add_review("T5 fragment shape unseen: no edge or accounting row emitted",
                       "T5-GRID", "high")
        return res

    res.schema_id = ("T5_TWO_EDGE_ERA" if expected_rows == 2
                     else ("T5_FOUR_ROW_NARROW" if frag.n_cols == 4 else "T5_FOUR_ROW"))
    confirmation = anchor_confirms(anchors, T5, frag.index)

    for c in range(frag.n_cols):
        res.cells.append(read_cell(frag, 0, c, source_sha256, text_regime, numeric=False))

    value_cols_rtl = [2, 1, 0]
    label_col_start = 3
    all_ok = True
    seen_ranks: set[int] = set()
    recovered: list[tuple[int, str, Optional[float]]] = []
    refused: list[tuple[int, str, str]] = []

    for r in range(HEADER_ROWS, frag.n_rows):
        row_rank = r  # header is row 0, so data row r maps to transfer rank r
        rowdef = TRANSFER_ROW_BY_RANK.get(row_rank)
        if rowdef is None:
            res.add_failure("T5_UNKNOWN_ROW_RANK",
                            f"data row {r} has no entry in the transfer registry")
            res.add_review("T5 row rank outside the known four", f"T5-ROW-{r}", "high")
            all_ok = False
            continue
        seen_ranks.add(row_rank)

        label = _read_label(frag, r, label_col_start, source_sha256, text_regime)
        res.cells.append(label)
        values = [read_cell(frag, r, c, source_sha256, text_regime, numeric=True)
                  for c in value_cols_rtl]
        value_indices = [res.add_cell(v) for v in values]

        # PATCH-P5B-001: a blank in the daily column of an R2 page is the word
        # welding defect, not an unprinted value. Ask the span layer.
        for i, (field_id, cell, col) in enumerate(
                zip(TRANSFER_VALUE_ORDER_RTL, values, value_cols_rtl)):
            if field_id != DAILY_FIELD or text_regime != R2:
                continue
            if cell.semantic_state != STATE_BLANK:
                continue
            outcome = recover_cell_from_native_spans(ctx, frag, r, col)
            if not (outcome.recovered or outcome.found_candidate):
                # The page prints nothing in this cell. A blank stays a blank:
                # nothing here invents a problem where the source has none.
                continue
            fixed = apply_native_recovery(cell, outcome, gate=T5_DAILY_GATE)
            res.cells[value_indices[i]] = fixed
            values[i] = fixed
            if fixed.semantic_state == STATE_NUMBER:
                recovered.append((r, field_id, fixed.parsed_value))
            else:
                refused.append((r, field_id, outcome.outcome))

        is_accounting = rowdef.kind == ACCOUNTING
        for field_id, cell in zip(TRANSFER_VALUE_ORDER_RTL, values):
            fd = field_def(field_id)
            fact = Fact(
                family_id=T5,
                record_type="transfer_accounting_observation" if is_accounting else "transfer_edge",
                record_id=record_id(T5, source_sha256, rowdef.record_id),
                fragment_rank=frag.index,
                row_label_raw=label.raw_text,
                row_label_ar=label.decoded_text_ar,
                row_label_en=rowdef.label_en,
                canonical_field_id=field_id,
                canonical_name=canonical_name(field_id),
                canonical_label_ar=rowdef.label_ar,
                canonical_label_en=rowdef.label_en,
                raw_text=cell.raw_text,
                decoded_text_ar=cell.decoded_text_ar,
                parsed_value=cell.parsed_value,
                value_type=fd.value_type if fd else "measure",
                unit=fd.unit if fd else "",
                temporal_reference=fd.temporal_reference if fd else "",
                semantic_state=cell.semantic_state,
                source_node_id="" if is_accounting else rowdef.source_node_id,
                destination_node_id=rowdef.destination_node_id,
                via_node_id=rowdef.via_node_id,
                is_accounting_observation=is_accounting,
                schema_id=res.schema_id,
                layout_slot=f"{FSM_ID[8]}:r{r}c{cell.column_index}",
                column_semantics_method="POSITIONAL_RTL_AFTER_LABEL_COLUMN",
                anchor_confirmation=confirmation,
                evidence_id=cell.evidence_id,
                notes=("accounting observation restating rows 2+3; never a graph edge"
                       if is_accounting else ""),
            )
            # Carries the adjudicated reading and, when one happened, the
            # recovery method, gate and evidence onto the published fact.
            stamp_fact_from_cell(fact, cell)
            if cell.semantic_state != STATE_NUMBER:
                all_ok = False
            res.facts.append(fact)
        res.row_count += 1

    # Rows absent because the era does not print them are recorded as absent.
    if expected_rows == 2:
        for rank in (3, 4):
            rowdef = TRANSFER_ROW_BY_RANK[rank]
            for field_id in TRANSFER_VALUE_ORDER_RTL:
                fd = field_def(field_id)
                res.facts.append(Fact(
                    family_id=T5,
                    record_type=("transfer_accounting_observation"
                                 if rowdef.kind == ACCOUNTING else "transfer_edge"),
                    record_id=record_id(T5, source_sha256, rowdef.record_id),
                    fragment_rank=frag.index,
                    row_label_en=rowdef.label_en,
                    canonical_field_id=field_id,
                    canonical_name=canonical_name(field_id),
                    canonical_label_ar=rowdef.label_ar,
                    canonical_label_en=rowdef.label_en,
                    parsed_value=None,
                    value_type=fd.value_type if fd else "measure",
                    unit=fd.unit if fd else "",
                    temporal_reference=fd.temporal_reference if fd else "",
                    semantic_state=STATE_ROW_ABSENT,
                    source_node_id="" if rowdef.kind == ACCOUNTING else rowdef.source_node_id,
                    destination_node_id=rowdef.destination_node_id,
                    via_node_id=rowdef.via_node_id,
                    is_accounting_observation=rowdef.kind == ACCOUNTING,
                    schema_id=res.schema_id,
                    layout_slot=f"{FSM_ID[8]}:row-not-printed",
                    column_semantics_method="ROW_NOT_PRINTED_IN_THIS_ERA",
                    anchor_confirmation=confirmation,
                    extraction_status=extraction_status_for(STATE_ROW_ABSENT),
                    notes="two-edge era prints only rows 1-2; absent is not zero, "
                          "and semantic_state=row_absent distinguishes a row this "
                          "era does not print from a printed empty cell",
                ))

    if recovered:
        rows_hit = sorted({r for r, _f, _v in recovered})
        res.notes.append(
            f"T5 daily recovery: {len(recovered)} value(s) on row(s) {rows_hit} "
            f"read from the native span layer of the source-ruled daily cell "
            f"({RECOVERY_RAWDICT_SPAN}); the word layer had welded each value "
            f"onto the adjacent Arabic label and left the cell blank")
    if refused:
        rows_hit = sorted({r for r, _f, _o in refused})
        reasons = sorted({o for _r, _f, o in refused})
        res.add_review(
            f"{len(refused)} T5 daily value(s) on row(s) {rows_hit} are blank in "
            f"the word layer and could not be resolved from the span layer "
            f"either ({', '.join(reasons)}). The cell is published as an "
            "explicit unparseable candidate, never as blank and never as zero",
            "T5-DAILY-NOT-RECOVERABLE", "high")
        res.add_failure("T5_DAILY_VALUE_NOT_RECOVERABLE",
                        f"{len(refused)} daily values unresolved on rows {rows_hit}: "
                        + ", ".join(reasons), severity="warning")

    res.status = FAMILY_OK if all_ok and res.row_count == expected_rows else FAMILY_PARTIAL
    _balance_diagnostic(res, source_sha256)
    return res


def _read_label(frag: Fragment, row: int, first_label_col: int,
                source_sha256: str, text_regime: str):
    """Read the row label, which may occupy one or two of the rightmost columns."""
    best = None
    for c in range(frag.n_cols - 1, first_label_col - 1, -1):
        cell = read_cell(frag, row, c, source_sha256, text_regime, numeric=False)
        if cell.raw_text.strip():
            if best is None or len(cell.raw_text) > len(best.raw_text):
                best = cell
    if best is not None:
        return best
    return read_cell(frag, row, frag.n_cols - 1, source_sha256, text_regime, numeric=False)


#: Observed spread of the row-4 versus rows-2+3 difference on the accepted
#: sample. Recorded as a diagnostic band, never enforced as a threshold.
BALANCE_DIAGNOSTIC_BAND = (0.013, 0.141)


def _balance_diagnostic(res: FamilyResult, source_sha256: str) -> None:
    """Compare the accounting row against the sum of its two component edges.

    A difference is *information*, not a failure: the accounting row and the
    edges are separately reported quantities.
    """
    prefix = f"{T5}-{source_sha256[:12]}-"
    by_record: dict[str, dict[str, float]] = {}
    for f in res.facts:
        if f.parsed_value is None or not f.record_id.startswith(prefix):
            continue
        key = f.record_id[len(prefix):]
        by_record.setdefault(key, {})[f.canonical_field_id] = f.parsed_value

    acc = by_record.get("EDGE-T5-04-ACCOUNTING")
    e2 = by_record.get("EDGE-T5-02")
    e3 = by_record.get("EDGE-T5-03")
    if not acc or not e2:
        return
    for field_id in TRANSFER_VALUE_ORDER_RTL:
        a = acc.get(field_id)
        b = e2.get(field_id)
        c = e3.get(field_id) if e3 else None
        if a is None or b is None or c is None:
            continue
        diff = round(a - (b + c), 6)
        res.notes.append(
            f"T5 balance diagnostic {field_id}: accounting {a} - (edges {b}+{c}) = {diff}"
        )

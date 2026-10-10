"""T1 — general national stock (FSM-01, fragment rank 1, shape ``[2,4]``).

Row 0 is the header, row 1 the single data row. Reading right to left after the
label column: today's stock for the current season, the three-year same-day
average, and the printed difference between them.

Those three values are also an identity the bulletin itself prints —
``today = three-year average + difference`` — and 1.1.0 uses it as the gate on
the bounded R2 fused-token recovery. On presentation-form pages the printed
stock is welded onto the Arabic label (``172,200ﺍﻟﻣﺧﺯﻭﻥ``) and only its leading
thousands group ``1`` stays in the value cell; 1.0.0 published that ``1`` as a
complete number on 116 files (AUD-F-001) and left 227 more blank. A candidate
reassembled from the two pieces is published only when it satisfies the printed
identity within the display-rounding bound, and is otherwise emitted as
``unparseable_numeric_candidate`` with a review item.
"""

from __future__ import annotations

from typing import Optional

from .anchors import AnchorResult, anchor_confirms
from .evidence import (
    FAMILY_ABSENT,
    FAMILY_OK,
    FAMILY_PARTIAL,
    FAMILY_UNRESOLVED,
    CellEvidence,
    Fact,
    FamilyResult,
    PendingRecovery,
    extraction_status_for,
    finalize_recovery,
    read_cell,
    record_id,
)
from .fused_recovery import try_recover
from .geometry import Fragment
from .numbers import STATE_NUMBER
from .semantic_mapping import (
    FSM_ID,
    T1,
    T1_VALUE_ORDER_RTL,
    canonical_name,
    field_def,
)
from .validation import rounding_tolerance

EXPECTED_SHAPE = (2, 4)
DATA_ROW = 1
HEADER_ROW = 0
SCHEMA_ID = "T1_GENERAL_STOCK_4COL"

TODAY = "p3_t1_stock_current_season_today_mm3"
AVG = "p3_t1_stock_3yr_same_day_avg_mm3"
DIFF = "p3_t1_stock_difference_mm3"

#: The identity the page prints, named on every fact it confirms.
T1_RECOVERY_GATE = "VR-T1-01-IDENTITY:today=three_year_average+printed_difference"
T1_ROW_LABEL_EN = "general dam stock"
T1_ROW_LABEL_AR = "المخزون العام للسدود"


def extract(frag: Optional[Fragment],
            source_sha256: str,
            text_regime: str,
            anchors: AnchorResult) -> FamilyResult:
    res = FamilyResult(family_id=T1, fragment_ranks=(1,), status=FAMILY_ABSENT,
                       schema_id=SCHEMA_ID)
    if frag is None:
        res.add_failure("T1_FRAGMENT_ABSENT", "fragment rank 1 not present")
        return res

    if frag.shape != EXPECTED_SHAPE:
        res.status = FAMILY_UNRESOLVED
        res.add_failure("T1_UNEXPECTED_SHAPE",
                        f"expected {list(EXPECTED_SHAPE)} got {list(frag.shape)}")
        res.add_review("T1 fragment shape not in the accepted registry", "T1-GRID", "high")
        return res

    confirmation = anchor_confirms(anchors, T1, frag.index)
    label_col = frag.n_cols - 1
    label_cell = read_cell(frag, DATA_ROW, label_col, source_sha256, text_regime, numeric=False)
    res.cells.append(label_cell)

    header_cells: list[CellEvidence] = []
    for c in range(frag.n_cols):
        header_cells.append(read_cell(frag, HEADER_ROW, c, source_sha256, text_regime, numeric=False))
    res.cells.extend(header_cells)

    value_cols_rtl = [c for c in range(frag.n_cols - 2, -1, -1)]
    method = "POSITIONAL_RTL_AFTER_LABEL_COLUMN"
    if confirmation == "ANCHOR_CONFIRMED":
        method += "+ANCHOR_CONFIRMED"

    cells_by_field: dict[str, CellEvidence] = {}
    for field_id, col in zip(T1_VALUE_ORDER_RTL, value_cols_rtl):
        cell = read_cell(frag, DATA_ROW, col, source_sha256, text_regime, numeric=True)
        idx = res.add_cell(cell)
        recovery = try_recover(frag, DATA_ROW, col, cell, text_regime=text_regime)
        fd = field_def(field_id)
        fact = Fact(
            family_id=T1,
            record_type="general_stock",
            record_id=record_id(T1, source_sha256, "GENERAL"),
            fragment_rank=frag.index,
            row_label_raw=label_cell.raw_text,
            row_label_ar=label_cell.decoded_text_ar,
            row_label_en=T1_ROW_LABEL_EN,
            canonical_field_id=field_id,
            canonical_name=canonical_name(field_id),
            canonical_label_ar=fd.label_ar if fd else T1_ROW_LABEL_AR,
            canonical_label_en=fd.label_en if fd else T1_ROW_LABEL_EN,
            raw_text=cell.raw_text,
            decoded_text_ar=cell.decoded_text_ar,
            parsed_value=cell.parsed_value,
            value_type=fd.value_type if fd else "measure",
            unit=fd.unit if fd else "",
            temporal_reference=fd.temporal_reference if fd else "",
            semantic_state=cell.semantic_state,
            schema_id=SCHEMA_ID,
            layout_slot=f"{FSM_ID[1]}:r{DATA_ROW}c{col}",
            column_semantics_method=method,
            anchor_confirmation=confirmation,
            evidence_id=cell.evidence_id,
            extraction_status=extraction_status_for(cell.semantic_state),
        )
        cells_by_field[field_id] = cell
        res.facts.append(fact)
        if recovery is not None:
            res.pending_recoveries.append(
                PendingRecovery(fact=fact, cell=cell, cell_index=idx,
                                result=recovery, field_id=field_id))

    _gate_printed_identity(res, cells_by_field)
    _queue_remaining_text_states(res, cells_by_field)

    res.row_count = 1
    produced = sum(1 for f in res.facts if f.semantic_state == STATE_NUMBER)
    res.status = FAMILY_OK if produced == len(T1_VALUE_ORDER_RTL) else FAMILY_PARTIAL
    return res


def _gate_printed_identity(res: FamilyResult,
                           cells_by_field: dict[str, CellEvidence]) -> None:
    """Confirm or refuse each pending T1 recovery against ``today = avg + diff``."""
    if not res.pending_recoveries:
        return

    def strict_value(field_id: str) -> Optional[float]:
        cell = cells_by_field.get(field_id)
        if cell is None or cell.strict_semantic_state != STATE_NUMBER:
            return None
        return cell.strict_parsed_value

    pending_fields = {p.field_id for p in res.pending_recoveries}
    for pending in res.pending_recoveries:
        confirmed = False
        candidate = pending.result.value
        if pending.field_id != TODAY:
            # Only the stock cell is determined by the other two. Anything else
            # stays a recorded candidate rather than a published number.
            gate = "NO_PRINTED_IDENTITY_FOR_THIS_FIELD"
        elif AVG in pending_fields or DIFF in pending_fields:
            # Two terms of the identity would themselves be recoveries, so the
            # identity could be satisfied by construction rather than tested.
            gate = "IDENTITY_TERMS_ARE_THEMSELVES_UNCONFIRMED_RECOVERIES"
        else:
            avg, diff = strict_value(AVG), strict_value(DIFF)
            if avg is None or diff is None:
                gate = "IDENTITY_TERMS_NOT_PRINTED_AS_NUMBERS"
            elif candidate is None:
                gate = "NO_CANDIDATE_VALUE"
            else:
                tol = rounding_tolerance(3)
                delta = abs(candidate - (avg + diff))
                confirmed = delta <= tol
                gate = (f"{T1_RECOVERY_GATE}|derived={avg + diff:.6f}"
                        f"|delta={delta:.6f}|tolerance={tol:.6f}")
        finalize_recovery(res, pending, gate=gate, confirmed=confirmed)
        if not confirmed:
            res.add_review(
                f"T1 {pending.field_id}: a printed number is fused into the "
                f"adjacent label on this presentation-form page and no printed "
                f"identity confirms the reassembled candidate "
                f"({pending.result.assembled_text!r}); left unparseable, never "
                f"guessed",
                pending.field_id, "high", evidence_id=pending.cell.evidence_id)
            res.add_failure("T1_FUSED_VALUE_NOT_RECOVERABLE",
                            f"{pending.field_id}: {gate}", severity="warning")


def _queue_remaining_text_states(res: FamilyResult,
                                 cells_by_field: dict[str, CellEvidence]) -> None:
    for fact in res.facts:
        cell = cells_by_field.get(fact.canonical_field_id)
        if cell is None or fact.recovery_method:
            continue
        fact.extraction_status = extraction_status_for(fact.semantic_state)
        if fact.semantic_state in ("suspected_text_state", "unparseable_numeric_candidate"):
            fact.review_status = "REVIEW_TEXT_STATE"
            res.add_review(
                f"T1 {fact.canonical_field_id} is {fact.semantic_state}, not a number",
                fact.canonical_field_id, "high", evidence_id=cell.evidence_id)

"""T3 — regional and national inflows plus the seasonal comparator.

Three fragments: the regional breakdown (rank 3, ``[3,2]``), the isolated daily
total (rank 4, ``[2,1]`` — one of the two mini-boxes PyMuPDF's table finder
misses), and the seasonal comparator (rank 5, ``[2,5]``).

Both documented comparator schemas are implemented. Their *column indices* move
between eras, so the populated value cells are ordered right to left instead of
being read from a fixed index map:

``T3_COMPARATOR_5VALUE``  current season, 3-year same-day average, difference
                          vs that average, period average, difference vs period
``T3_COMPARATOR_3VALUE``  current season, period average, difference

Region identity comes from the row rank of the regional fragment, and region
*membership* (which dam sits in which region) is deliberately unresolved, so no
regional aggregate may be compared against the reference dataset.

The regional block and the daily total share one identity the page prints —
``sum(regions) = printed total`` — and 1.1.0 uses it to gate the bounded R2
fused-token recovery for both. On presentation-form pages the centre and Cap Bon
values are welded onto their Arabic labels, and the T3 national total is welded
onto a label word whose centre falls between two fragments, so the grid drops it
entirely. All four terms are reassembled together and confirmed together, or
none of them is published.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .anchors import AnchorResult, anchor_confirms
from .evidence import (
    FAMILY_ABSENT,
    FAMILY_OK,
    FAMILY_PARTIAL,
    FAMILY_UNRESOLVED,
    Fact,
    FamilyResult,
    PendingRecovery,
    extraction_status_for,
    finalize_recovery,
    numeric_columns_rtl,
    populated_columns,
    read_cell,
    record_id,
)
from .fused_recovery import try_recover
from .geometry import Fragment
from .numbers import STATE_NUMBER
from .semantic_mapping import (
    FSM_ID,
    REGION_BY_RANK,
    REGION_MEMBERSHIP_STATUS,
    T3,
    T3_COMPARATOR_3VALUE,
    T3_COMPARATOR_5VALUE,
    T3_COMPARATOR_ORDER_RTL,
    canonical_name,
    field_def,
)
from .validation import regional_sum_tolerance

REGIONAL_SHAPE = (3, 2)
TOTAL_SHAPE = (2, 1)
COMPARATOR_COLS = 5

#: The identity the page prints, named on every fact it confirms or refuses.
REGIONAL_SUM_GATE = "VR-{fam}-01-IDENTITY:sum(printed_regions)=printed_total"


def extract(regional: Optional[Fragment],
            total: Optional[Fragment],
            comparator: Optional[Fragment],
            source_sha256: str,
            text_regime: str,
            anchors: AnchorResult) -> FamilyResult:
    res = FamilyResult(family_id=T3, fragment_ranks=(3, 4, 5), status=FAMILY_ABSENT)
    confirmation = anchor_confirms(anchors, T3, regional.index if regional else -1)

    ok = extract_regional_block(
        res, regional, source_sha256, text_regime, confirmation,
        family=T3, fsm_rank=3,
        field_id="p3_t3_inflow_region_today_mm3",
        record_type="inflow_region",
        expected_shape=REGIONAL_SHAPE,
        code_prefix="T3",
    )
    ok &= extract_total_block(
        res, total, source_sha256, text_regime, confirmation,
        family=T3, fsm_rank=4,
        field_id="p3_t3_inflow_total_today_mm3",
        record_type="inflow_total",
        code_prefix="T3",
    )
    gate_regional_sum(res, code_prefix="T3",
                      region_field="p3_t3_inflow_region_today_mm3",
                      total_field="p3_t3_inflow_total_today_mm3")
    ok &= _extract_comparator(res, comparator, source_sha256, text_regime, confirmation)

    if res.facts:
        res.status = FAMILY_OK if family_is_complete(res, ok) else FAMILY_PARTIAL
    return res


def family_is_complete(res: FamilyResult, structural_ok: bool) -> bool:
    """OK when the structure resolved *and* every published fact is a number.

    Evaluated after the recovery gates, not while the rows are being read: a
    cell the fusion defect emptied is only known to be numeric once its printed
    identity has confirmed the reassembled value.
    """
    return structural_ok and all(f.semantic_state == STATE_NUMBER for f in res.facts)


# ---------------------------------------------------------------------- #
# Shared blocks (T3 and T4 have the same regional + total geometry)
# ---------------------------------------------------------------------- #

def extract_regional_block(res: FamilyResult,
                           frag: Optional[Fragment],
                           source_sha256: str,
                           text_regime: str,
                           confirmation: str,
                           *,
                           family: str,
                           fsm_rank: int,
                           field_id: str,
                           record_type: str,
                           expected_shape: tuple[int, int],
                           code_prefix: str) -> bool:
    if frag is None:
        res.add_failure(f"{code_prefix}_REGIONAL_FRAGMENT_ABSENT",
                        f"fragment rank {fsm_rank} not present")
        return False
    if frag.shape != expected_shape:
        res.add_failure(f"{code_prefix}_REGIONAL_UNEXPECTED_SHAPE",
                        f"expected {list(expected_shape)} got {list(frag.shape)}")
        res.add_review(f"{code_prefix} regional fragment shape unresolved",
                       f"{code_prefix}-REGIONAL", "high")
        return False

    label_col = frag.n_cols - 1
    value_col = 0
    fd = field_def(field_id)
    all_ok = True
    for r in range(frag.n_rows):
        label = read_cell(frag, r, label_col, source_sha256, text_regime, numeric=False)
        cell = read_cell(frag, r, value_col, source_sha256, text_regime, numeric=True)
        res.cells.append(label)
        idx = res.add_cell(cell)
        recovery = try_recover(frag, r, value_col, cell, text_regime=text_regime)
        region = REGION_BY_RANK.get(r + 1)
        fact = Fact(
            family_id=family,
            record_type=record_type,
            record_id=record_id(family, source_sha256,
                                f"{record_type.upper()}-{region.region_id if region else f'ROW{r}'}"),
            fragment_rank=frag.index,
            row_label_raw=label.raw_text,
            row_label_ar=label.decoded_text_ar,
            row_label_en=region.name_en if region else "",
            canonical_field_id=field_id,
            canonical_name=canonical_name(field_id),
            canonical_label_ar=region.name_ar if region else (fd.label_ar if fd else ""),
            canonical_label_en=region.name_en if region else (fd.label_en if fd else ""),
            raw_text=cell.raw_text,
            decoded_text_ar=cell.decoded_text_ar,
            parsed_value=cell.parsed_value,
            value_type=fd.value_type if fd else "measure",
            unit=fd.unit if fd else "",
            temporal_reference=fd.temporal_reference if fd else "",
            semantic_state=cell.semantic_state,
            region_id=region.region_id if region else "",
            schema_id=f"{code_prefix}_REGIONAL_3ROW",
            layout_slot=f"{FSM_ID[fsm_rank]}:r{r}c{value_col}",
            column_semantics_method="POSITIONAL_ROW_RANK_TO_REGION",
            anchor_confirmation=confirmation,
            evidence_id=cell.evidence_id,
            extraction_status=extraction_status_for(cell.semantic_state),
            notes=f"region_membership={REGION_MEMBERSHIP_STATUS}",
        )
        if region is None:
            fact.review_status = "REGION_RANK_UNKNOWN"
            res.add_review(f"{code_prefix} regional row {r} has no registry region",
                           f"{code_prefix}-REGIONAL-ROW-{r}", "high")
            all_ok = False
        # Whether the cell holds a number is decided after the recovery gate,
        # in family_is_complete; here `all_ok` reports structure only.
        res.facts.append(fact)
        if recovery is not None:
            res.pending_recoveries.append(
                PendingRecovery(fact=fact, cell=cell, cell_index=idx,
                                result=recovery, field_id=field_id))
    res.row_count += frag.n_rows
    return all_ok


def extract_total_block(res: FamilyResult,
                        frag: Optional[Fragment],
                        source_sha256: str,
                        text_regime: str,
                        confirmation: str,
                        *,
                        family: str,
                        fsm_rank: int,
                        field_id: str,
                        record_type: str,
                        code_prefix: str) -> bool:
    if frag is None:
        res.add_failure(f"{code_prefix}_TOTAL_FRAGMENT_ABSENT",
                        f"fragment rank {fsm_rank} not present")
        return False
    if frag.shape != TOTAL_SHAPE:
        res.add_failure(f"{code_prefix}_TOTAL_UNEXPECTED_SHAPE",
                        f"expected {list(TOTAL_SHAPE)} got {list(frag.shape)}")
        res.add_review(f"{code_prefix} daily-total mini-box shape unresolved",
                       f"{code_prefix}-TOTAL", "high")
        return False

    header = read_cell(frag, 0, 0, source_sha256, text_regime, numeric=False)
    cell = read_cell(frag, 1, 0, source_sha256, text_regime, numeric=True)
    res.cells.append(header)
    idx = res.add_cell(cell)
    recovery = try_recover(frag, 1, 0, cell, text_regime=text_regime)
    fd = field_def(field_id)
    fact = Fact(
        family_id=family,
        record_type=record_type,
        record_id=record_id(family, source_sha256, record_type.upper()),
        fragment_rank=frag.index,
        row_label_raw=header.raw_text,
        row_label_ar=header.decoded_text_ar,
        row_label_en="for this day",
        canonical_field_id=field_id,
        canonical_name=canonical_name(field_id),
        canonical_label_ar=fd.label_ar if fd else "",
        canonical_label_en=fd.label_en if fd else "for this day",
        raw_text=cell.raw_text,
        decoded_text_ar=cell.decoded_text_ar,
        parsed_value=cell.parsed_value,
        value_type=fd.value_type if fd else "measure",
        unit=fd.unit if fd else "",
        temporal_reference=fd.temporal_reference if fd else "",
        semantic_state=cell.semantic_state,
        schema_id=f"{code_prefix}_TOTAL_MINIBOX",
        layout_slot=f"{FSM_ID[fsm_rank]}:r1c0",
        column_semantics_method="ISOLATED_TOTAL_MINIBOX",
        anchor_confirmation=confirmation,
        evidence_id=cell.evidence_id,
        extraction_status=extraction_status_for(cell.semantic_state),
    )
    res.facts.append(fact)
    res.row_count += 1
    if recovery is not None:
        res.pending_recoveries.append(
            PendingRecovery(fact=fact, cell=cell, cell_index=idx,
                            result=recovery, field_id=field_id))
    return True


def gate_regional_sum(res: FamilyResult,
                      *,
                      code_prefix: str,
                      region_field: str,
                      total_field: str) -> None:
    """Confirm or refuse the regional/total recoveries against the printed sum.

    Every term of the identity is printed on the page: three regional values and
    one national total. A candidate reassembled for any of them is published only
    if, with every candidate substituted, the four printed numbers still
    reconcile inside the source-consistency bound. Anything else is emitted as
    ``unparseable_numeric_candidate`` with a review item.
    """
    pending = [p for p in res.pending_recoveries
               if p.field_id in (region_field, total_field) and not p.fact.recovery_method]
    if not pending:
        return

    regions = [f for f in res.facts if f.canonical_field_id == region_field]
    total_fact = next((f for f in res.facts if f.canonical_field_id == total_field), None)
    by_fact = {id(p.fact): p for p in pending}

    def resolved(fact: Optional[Fact]) -> Optional[float]:
        if fact is None:
            return None
        p = by_fact.get(id(fact))
        if p is not None:
            return p.result.value
        return fact.parsed_value if fact.semantic_state == STATE_NUMBER else None

    parts = [resolved(f) for f in regions]
    total = resolved(total_fact)
    gate_id = REGIONAL_SUM_GATE.format(fam=code_prefix)

    if total is None or len(parts) != 3 or any(v is None for v in parts):
        gate = f"{gate_id}|INELIGIBLE:not every term of the identity is a number"
        confirmed = False
    else:
        s = sum(v for v in parts if v is not None)
        tol = regional_sum_tolerance(len(parts) + 1)
        delta = abs(total - s)
        confirmed = delta <= tol
        gate = (f"{gate_id}|parts_sum={s:.6f}|printed_total={total:.6f}"
                f"|delta={delta:.6f}|tolerance={tol:.6f}")

    for p in pending:
        finalize_recovery(res, p, gate=gate, confirmed=confirmed)
        if not confirmed:
            res.add_review(
                f"{code_prefix} {p.field_id}: a printed number is fused into an "
                f"adjacent label on this presentation-form page and the printed "
                f"regional-sum identity does not confirm the reassembled "
                f"candidate ({p.result.assembled_text!r}); left unparseable, "
                f"never guessed",
                f"{code_prefix}-{p.fact.region_id or 'TOTAL'}", "high",
                evidence_id=p.cell.evidence_id)
            res.add_failure(f"{code_prefix}_FUSED_VALUE_NOT_RECOVERABLE",
                            f"{p.field_id}: {gate}", severity="warning")


def _extract_comparator(res: FamilyResult,
                        frag: Optional[Fragment],
                        source_sha256: str,
                        text_regime: str,
                        confirmation: str) -> bool:
    if frag is None:
        res.add_failure("T3_COMPARATOR_FRAGMENT_ABSENT", "fragment rank 5 not present")
        return False
    if frag.n_cols != COMPARATOR_COLS:
        res.add_failure("T3_COMPARATOR_UNEXPECTED_COLUMN_COUNT",
                        f"expected {COMPARATOR_COLS} columns got {frag.n_cols}")
        res.add_review("T3 comparator column count unresolved", "T3-COMPARATOR", "high")
        return False

    data_row = frag.n_rows - 1
    # Populated, not numeric: the comparator row of the one corpus file carrying
    # upstream spreadsheet errors holds `#N/A` in cells that a numeric filter
    # would discard, which would silently drop the very cells a reviewer needs
    # to see. The cells are selected by content and each keeps its own state.
    value_cols = sorted(populated_columns(frag, data_row), reverse=True)
    numeric_cols = numeric_columns_rtl(frag, data_row)
    n = len(value_cols)
    if n == 5:
        schema_id = T3_COMPARATOR_5VALUE
    elif n == 3:
        schema_id = T3_COMPARATOR_3VALUE
    else:
        res.add_failure("T3_COMPARATOR_UNKNOWN_VALUE_COUNT",
                        f"{n} populated value columns; neither the 3-value nor the "
                        "5-value schema applies")
        res.add_review(
            f"T3 comparator has {n} populated value columns: schema unresolved, no "
            "field identity assigned", "T3-COMPARATOR", "high")
        for c in value_cols:
            res.cells.append(read_cell(frag, data_row, c, source_sha256, text_regime, numeric=True))
        return False

    res.schema_id = schema_id
    if len(numeric_cols) != n:
        res.notes.append(
            f"T3 comparator: {n} populated columns, {len(numeric_cols)} of them "
            "numeric; the remainder keep their own semantic state")
    order = T3_COMPARATOR_ORDER_RTL[schema_id]
    header_row = data_row - 1 if data_row > 0 else 0
    all_ok = True
    for field_id, col in zip(order, value_cols):
        header = read_cell(frag, header_row, col, source_sha256, text_regime, numeric=False)
        cell = read_cell(frag, data_row, col, source_sha256, text_regime, numeric=True)
        res.cells.extend([header, cell])
        fd = field_def(field_id)
        fact = Fact(
            family_id=T3,
            record_type="inflow_comparator",
            record_id=record_id(T3, source_sha256, "COMPARATOR"),
            fragment_rank=frag.index,
            row_label_raw=header.raw_text,
            row_label_ar=header.decoded_text_ar,
            row_label_en=fd.label_en if fd else "",
            canonical_field_id=field_id,
            canonical_name=canonical_name(field_id),
            canonical_label_ar=fd.label_ar if fd else "",
            canonical_label_en=fd.label_en if fd else "",
            raw_text=cell.raw_text,
            decoded_text_ar=cell.decoded_text_ar,
            parsed_value=cell.parsed_value,
            value_type=fd.value_type if fd else "measure",
            unit=fd.unit if fd else "",
            temporal_reference=fd.temporal_reference if fd else "",
            semantic_state=cell.semantic_state,
            schema_id=schema_id,
            layout_slot=f"{FSM_ID[5]}:r{data_row}c{col}",
            column_semantics_method="POPULATED_VALUE_COLUMNS_ORDERED_RTL",
            anchor_confirmation=confirmation,
            evidence_id=cell.evidence_id,
            extraction_status=extraction_status_for(cell.semantic_state),
        )
        res.facts.append(fact)
    res.row_count += 1
    return all_ok

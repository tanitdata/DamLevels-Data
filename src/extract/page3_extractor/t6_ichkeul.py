"""T6 — Lake Ichkeul feed (FSM-09, fragment rank 9).

Lake Ichkeul is an **external environmental destination**, not a dam node. No
row of this family may become a dam-to-dam edge.

Two shapes exist, ``[2,5]`` and ``[3,5]``. The probe measured that the ``[3,5]``
variant is a **two-line header over the same single data row**, not an extra
data row: its header cells carry ``row_span = 2`` and the data row is the last
row in both variants. The extractor therefore treats the final row as the data
row and records the header depth, publishing ``t6_data_row_count`` so the claim
is measured rather than assumed. Any additional populated row that is not the
header or the data row is quarantined into the review queue instead of being
given an invented meaning.

PATCH-P5B-004 (1.2.0) — evidence geometry only
----------------------------------------------
T6's data row does not have the five columns the shared fragment grid gives it.
The header block is ruled at five columns; the data row is ruled at four, and
the two extra header edges do not descend into it. Every published T6 value was
nonetheless **correct** — the audit confirmed all 93 on the challenge set — but
on 62 of 93 the recorded cell box clipped the number it claimed to evidence, so
a reviewer following ``evidence_id`` to its coordinates could not re-find the
value.

The repair records the cell box from the rulings the data row itself carries,
and asserts that the box contains the value's own glyphs. **No parsed value
changes**: the value still comes from the same grid cell, read the same way.
"""

from __future__ import annotations

from dataclasses import replace
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
    populated_columns,
    read_cell,
    record_id,
)
from .geometry import Fragment
from .numbers import STATE_NUMBER
from .semantic_mapping import (
    FSM_ID,
    ICHKEUL_DESTINATION_ID,
    ICHKEUL_RECORD_ID,
    ICHKEUL_VALUE_ORDER_RTL,
    T6,
    canonical_name,
    field_def,
)

ACCEPTED_SHAPES = {(2, 5): 1, (3, 5): 2, (4, 5): 3}
EXPECTED_VALUE_COUNT = 3


def extract(frag: Optional[Fragment],
            source_sha256: str,
            text_regime: str,
            anchors: AnchorResult,
            *,
            ctx=None) -> FamilyResult:
    res = FamilyResult(family_id=T6, fragment_ranks=(9,), status=FAMILY_ABSENT)
    if frag is None:
        res.add_failure("T6_FRAGMENT_ABSENT", "fragment rank 9 not present")
        return res

    header_rows = ACCEPTED_SHAPES.get(frag.shape)
    if header_rows is None:
        res.status = FAMILY_UNRESOLVED
        res.schema_id = f"T6_UNSEEN_{frag.n_rows}x{frag.n_cols}"
        res.add_failure("T6_UNSEEN_SHAPE", f"shape {list(frag.shape)} is not accepted")
        res.add_review("T6 fragment shape unseen: no delivery row emitted", "T6-GRID", "high")
        return res

    res.schema_id = f"T6_ICHKEUL_{header_rows}HEADER_ROW"
    confirmation = anchor_confirms(anchors, T6, frag.index)
    data_row = frag.n_rows - 1

    for r in range(header_rows):
        for c in range(frag.n_cols):
            res.cells.append(read_cell(frag, r, c, source_sha256, text_regime, numeric=False))

    # Populated rather than numeric, so an explicit textual state in a value
    # position is published with its state instead of being dropped.
    value_cols = sorted(populated_columns(frag, data_row), reverse=True)
    if len(value_cols) != EXPECTED_VALUE_COUNT:
        res.add_failure("T6_UNEXPECTED_VALUE_COUNT",
                        f"{len(value_cols)} populated columns in the data row; "
                        f"expected {EXPECTED_VALUE_COUNT}")
        res.add_review("T6 data row value count unresolved", "T6-DATA-ROW", "high")
        for c in value_cols:
            res.cells.append(read_cell(frag, data_row, c, source_sha256, text_regime, numeric=True))
        res.status = FAMILY_PARTIAL
        return res

    all_ok = True
    for field_id, col in zip(ICHKEUL_VALUE_ORDER_RTL, value_cols):
        cell = read_cell(frag, data_row, col, source_sha256, text_regime, numeric=True)
        cell = _bound_evidence_box(ctx, frag, data_row, col, cell, res)
        res.cells.append(cell)
        fd = field_def(field_id)
        fact = Fact(
            family_id=T6,
            record_type="external_environmental_delivery",
            record_id=record_id(T6, source_sha256, ICHKEUL_RECORD_ID),
            fragment_rank=frag.index,
            row_label_en="Lake Ichkeul feed",
            canonical_field_id=field_id,
            canonical_name=canonical_name(field_id),
            canonical_label_ar=fd.label_ar if fd else "",
            canonical_label_en=(f"Lake Ichkeul feed - {fd.label_en}" if fd
                                else "Lake Ichkeul feed"),
            raw_text=cell.raw_text,
            decoded_text_ar=cell.decoded_text_ar,
            parsed_value=cell.parsed_value,
            value_type=fd.value_type if fd else "measure",
            unit=fd.unit if fd else "",
            temporal_reference=fd.temporal_reference if fd else "",
            semantic_state=cell.semantic_state,
            destination_node_id=ICHKEUL_DESTINATION_ID,
            schema_id=res.schema_id,
            layout_slot=f"{FSM_ID[9]}:r{data_row}c{col}",
            column_semantics_method="POPULATED_VALUE_COLUMNS_ORDERED_RTL",
            anchor_confirmation=confirmation,
            evidence_id=cell.evidence_id,
            notes="external environmental destination; never a dam node",
        )
        fact.extraction_status = extraction_status_for(cell.semantic_state)
        if cell.semantic_state != STATE_NUMBER:
            all_ok = False
        res.facts.append(fact)

    res.row_count = 1
    # Any populated row between the header block and the data row has no
    # accepted meaning: quarantine rather than invent one.
    for r in range(header_rows, data_row):
        if any(frag.cell(r, c) and frag.cell(r, c).words for c in range(frag.n_cols)):
            res.add_review(
                f"T6 has a populated row {r} that is neither header nor the data row; "
                "meaning unresolved", f"T6-ROW-{r}", "high")
            res.add_failure("T6_EXTRA_POPULATED_ROW",
                            f"row {r} populated but unmapped", severity="warning")
            all_ok = False

    res.status = FAMILY_OK if all_ok else FAMILY_PARTIAL
    res.notes.append(f"header_rows={header_rows} data_rows=1 grid_rows={frag.n_rows}")
    return res


#: Recorded on a cell whose evidence box was re-derived from the data row's own
#: rulings, so a reader can tell a corrected box from an inherited one.
EVIDENCE_BOX_SOURCE_RULED = "SOURCE_RULED_CELL_BAND"


def _bound_evidence_box(ctx, frag: Fragment, row: int, col: int, cell, res):
    """Re-record this cell's box from the rulings the data row actually has.

    The *value* is untouched — it was read from the grid cell before this
    function is reached, and this only restates where it was printed. When the
    page draws no ruling pair around the value, or the re-derived box would not
    contain the glyphs, the inherited box is kept and the discrepancy is
    recorded: a wrong box is a weak evidence chain, but an unmeasured
    replacement would be a worse one.
    """
    from .native_spans import cell_band

    if ctx is None or not getattr(ctx, "native_available", False):
        return cell
    grid = frag.cell(row, col)
    if grid is None or not grid.words:
        return cell
    y0, y1 = frag.y_edges[row], frag.y_edges[row + 1]
    box = cell_band(ctx.source_rulings(), frag.bbox, y0, y1,
                    grid.bbox[0], grid.bbox[2])
    if box is None:
        res.notes.append(
            f"T6 r{row}c{col}: the data row draws no vertical ruling pair around "
            "this value; the fragment-grid box is kept")
        return cell

    wx0 = min(w.x0 for w in grid.words)
    wx1 = max(w.x1 for w in grid.words)
    if not (box[0] - 1.0 <= wx0 and wx1 <= box[2] + 1.0):
        res.notes.append(
            f"T6 r{row}c{col}: the source-ruled band "
            f"[{box[0]:.2f},{box[2]:.2f}] does not contain the value glyphs "
            f"[{wx0:.2f},{wx1:.2f}]; the fragment-grid box is kept")
        return cell
    return replace(cell, bbox=(box[0], min(box[1], min(w.y0 for w in grid.words)),
                               box[2], max(box[3], max(w.y1 for w in grid.words))),
                   engine=EVIDENCE_BOX_SOURCE_RULED)

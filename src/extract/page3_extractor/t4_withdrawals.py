"""T4 — regional and national withdrawals ("uses and withdrawal").

Two fragments with the same geometry as T3's first two: the regional breakdown
(rank 6, ``[3,2]``) and the isolated daily total (rank 7, ``[2,1]``). The shared
block extractors live in :mod:`t3_inflows` so the two families cannot drift
apart; only the canonical field ids and the anchor differ. That includes the
printed regional-sum identity, which is what gates the bounded R2 fused-token
recovery here as well.

The region-membership registry is still unresolved, so a T4 regional value may
not be compared against any reference aggregate.
"""

from __future__ import annotations

from typing import Optional

from .anchors import AnchorResult, anchor_confirms
from .evidence import FAMILY_ABSENT, FAMILY_OK, FAMILY_PARTIAL, FamilyResult
from .geometry import Fragment
from .semantic_mapping import T4
from .t3_inflows import (
    REGIONAL_SHAPE,
    extract_regional_block,
    extract_total_block,
    family_is_complete,
    gate_regional_sum,
)


def extract(regional: Optional[Fragment],
            total: Optional[Fragment],
            source_sha256: str,
            text_regime: str,
            anchors: AnchorResult) -> FamilyResult:
    res = FamilyResult(family_id=T4, fragment_ranks=(6, 7), status=FAMILY_ABSENT)
    confirmation = anchor_confirms(anchors, T4, regional.index if regional else -1)

    ok = extract_regional_block(
        res, regional, source_sha256, text_regime, confirmation,
        family=T4, fsm_rank=6,
        field_id="p3_t4_withdrawal_region_today_mm3",
        record_type="withdrawal_region",
        expected_shape=REGIONAL_SHAPE,
        code_prefix="T4",
    )
    ok &= extract_total_block(
        res, total, source_sha256, text_regime, confirmation,
        family=T4, fsm_rank=7,
        field_id="p3_t4_withdrawal_total_today_mm3",
        record_type="withdrawal_total",
        code_prefix="T4",
    )
    gate_regional_sum(res, code_prefix="T4",
                      region_field="p3_t4_withdrawal_region_today_mm3",
                      total_field="p3_t4_withdrawal_total_today_mm3")

    res.schema_id = "T4_REGIONAL_PLUS_TOTAL"
    if res.facts:
        res.status = FAMILY_OK if family_is_complete(res, ok) else FAMILY_PARTIAL
    return res

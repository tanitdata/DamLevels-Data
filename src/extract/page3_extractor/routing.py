"""Logical-page classification and route selection.

Routing keys are **measured**: normalized layout family, fragment shape
signature, text regime, rotation and topology. Never the calendar year
(FC-06: ten 2024-2025 files still carry 478 C0 controls, and R2 overlaps R3 in
time). Never orientation alone (FC-02: the landscape files are rotated logical
Page 3 pages, not different documents).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .page_context import PageContext
from .text_and_encoding import R1, R2, R3

# --- terminal source statuses (governing prompt section 6) -------------- #
SUCCESS_FAST_PATH = "SUCCESS_FAST_PATH"
SUCCESS_GEOMETRY_FALLBACK = "SUCCESS_GEOMETRY_FALLBACK"
SUCCESS_SPECIALIST_FALLBACK = "SUCCESS_SPECIALIST_FALLBACK"
PARTIAL_REVIEW_REQUIRED = "PARTIAL_REVIEW_REQUIRED"
QUARANTINED_NOT_LOGICAL_PAGE3 = "QUARANTINED_NOT_LOGICAL_PAGE3"
FAILED_SOURCE_READ = "FAILED_SOURCE_READ"
FAILED_UNRESOLVED_LAYOUT = "FAILED_UNRESOLVED_LAYOUT"
FAILED_SEMANTIC_VALIDATION = "FAILED_SEMANTIC_VALIDATION"

#: An unhandled exception inside the extractor. Kept distinct from
#: ``FAILED_SOURCE_READ`` on purpose: a defect in this code is not a property of
#: the source file, and reporting it as one would blame the corpus for a bug and
#: hide the bug behind a plausible-looking failure count.
FAILED_EXTRACTOR_ERROR = "FAILED_EXTRACTOR_ERROR"

TERMINAL_STATUSES = (
    SUCCESS_FAST_PATH,
    SUCCESS_GEOMETRY_FALLBACK,
    SUCCESS_SPECIALIST_FALLBACK,
    PARTIAL_REVIEW_REQUIRED,
    QUARANTINED_NOT_LOGICAL_PAGE3,
    FAILED_SOURCE_READ,
    FAILED_UNRESOLVED_LAYOUT,
    FAILED_SEMANTIC_VALIDATION,
    FAILED_EXTRACTOR_ERROR,
)

# --- logical page classes ----------------------------------------------- #
P3_PORTRAIT_STANDARD = "P3_PORTRAIT_STANDARD"
P3_ROTATED = "P3_ROTATED"
NOT_P3_CONFIRMED = "NOT_P3_CONFIRMED"
P3_REVIEW = "P3_REVIEW_REQUIRED"

# --- layout families ----------------------------------------------------- #
NF_A4_PORTRAIT = "NF-A4-PORTRAIT"
NF_A4_LANDSCAPE = "NF-A4-LANDSCAPE"
NF_763x1080 = "NF-763x1080"
NF_LETTER = "NF-LETTER"
NF_OTHER = "NF-OTHER"

#: The six invariant slot shapes shared by every portrait signature
#: (KB-LAYOUT-FAMILIES). Drift is confined to ranks 2, 8 and 9.
INVARIANT_SLOTS: dict[int, tuple[int, int]] = {
    1: (2, 4),
    3: (3, 2),
    4: (2, 1),
    5: (2, 5),
    6: (3, 2),
    7: (2, 1),
}
DRIFT_RANKS = (2, 8, 9)
EXPECTED_FRAGMENT_COUNT = 9

#: Allowed shapes in the three drifting slots, measured on the GT sample.
ALLOWED_DRIFT: dict[int, tuple[tuple[int, int], ...]] = {
    2: ((13, 5), (14, 5), (12, 5), (15, 5), (16, 5)),
    8: ((3, 5), (5, 5), (5, 4), (4, 5), (6, 5), (4, 4), (6, 4)),
    9: ((2, 5), (3, 5), (4, 5)),
}

ROUTE_FAST_PATH = "RT-01-PORTRAIT-FASTPATH"
ROUTE_ROTATED = "RT-02-ROTATED-NORMALIZED"
ROUTE_QUARANTINE = "RT-03-QUARANTINE-NOT-P3"
ROUTE_RARE_SIZE = "RT-04-RARE-SIZE-REVIEW"
ROUTE_UNRESOLVED = "RT-08-UNRESOLVED-REVIEW"


@dataclass
class RouteDecision:
    layout_family: str
    exact_dimension_pair: str
    logical_page_class: str
    route_id: str
    shape_signature: str
    text_regime: str
    invariant_slots_match: bool
    fragment_count: int
    decision_confidence: float
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, object] = field(default_factory=dict)
    fallback_engines: list[str] = field(default_factory=list)

    @property
    def extractable(self) -> bool:
        return self.logical_page_class in (P3_PORTRAIT_STANDARD, P3_ROTATED)


def normalized_family(media_w: float, media_h: float) -> str:
    """Normalized family from the *media* box, with exact pair kept separately.

    FC-01: six exact dimension pairs reduce to four practical families. A
    fingerprint that hashes the raw dimensions would split A4-portrait into
    three spurious families.
    """
    w, h = (media_w, media_h) if media_h >= media_w else (media_h, media_w)
    if 590 <= w <= 600 and 835 <= h <= 848:
        return NF_A4_PORTRAIT if media_h >= media_w else NF_A4_LANDSCAPE
    if 758 <= w <= 768 and 1074 <= h <= 1085:
        return NF_763x1080
    if 608 <= w <= 616 and 788 <= h <= 796:
        return NF_LETTER
    return NF_OTHER


def exact_pair(media_w: float, media_h: float) -> str:
    return f"{round(media_w, 2)}x{round(media_h, 2)}"


def classify(ctx: PageContext) -> RouteDecision:
    """Classify one page and choose its route."""
    family = normalized_family(ctx.media_width, ctx.media_height)
    pair = exact_pair(ctx.media_width, ctx.media_height)
    sig = ctx.shape_signature
    regime = ctx.text_health.encoding_regime
    reasons: list[str] = []
    signals: dict[str, object] = {
        "fragment_count": len(sig),
        "rotation": ctx.rotation,
        "rotation_normalization": ctx.rotation_normalization,
        "encoding_regime": regime,
        "numeric_tokens": sum(1 for w in ctx.words if any(ch.isdigit() for ch in w.text)),
        "drawing_count": ctx.drawing_count,
    }

    invariant_ok, slot_reasons = _invariant_slots_match(sig)
    reasons.extend(slot_reasons)
    signals["invariant_slots"] = invariant_ok

    if ctx.geometry_engine in ("none", "pdfplumber_failed"):
        return RouteDecision(
            layout_family=family, exact_dimension_pair=pair,
            logical_page_class=P3_REVIEW, route_id=ROUTE_UNRESOLVED,
            shape_signature=ctx.shape_signature_text, text_regime=regime,
            invariant_slots_match=False, fragment_count=len(sig),
            decision_confidence=0.0,
            reasons=reasons + ["geometry engine produced no fragments"],
            signals=signals,
        )

    if len(sig) != EXPECTED_FRAGMENT_COUNT:
        reasons.append(f"fragment count {len(sig)} != {EXPECTED_FRAGMENT_COUNT}")
        alien = _alien_topology_score(sig)
        signals["alien_topology_score"] = alien
        if alien >= 2:
            return RouteDecision(
                layout_family=family, exact_dimension_pair=pair,
                logical_page_class=NOT_P3_CONFIRMED, route_id=ROUTE_QUARANTINE,
                shape_signature=ctx.shape_signature_text, text_regime=regime,
                invariant_slots_match=False, fragment_count=len(sig),
                decision_confidence=0.95, reasons=reasons, signals=signals,
            )
        return RouteDecision(
            layout_family=family, exact_dimension_pair=pair,
            logical_page_class=P3_REVIEW, route_id=ROUTE_UNRESOLVED,
            shape_signature=ctx.shape_signature_text, text_regime=regime,
            invariant_slots_match=False, fragment_count=len(sig),
            decision_confidence=0.3, reasons=reasons, signals=signals,
        )

    if not invariant_ok:
        return RouteDecision(
            layout_family=family, exact_dimension_pair=pair,
            logical_page_class=P3_REVIEW, route_id=ROUTE_UNRESOLVED,
            shape_signature=ctx.shape_signature_text, text_regime=regime,
            invariant_slots_match=False, fragment_count=len(sig),
            decision_confidence=0.4, reasons=reasons, signals=signals,
        )

    drift_ok, drift_reasons = _drift_slots_known(sig)
    reasons.extend(drift_reasons)

    rotated = ctx.rotation % 360 != 0
    cls = P3_ROTATED if rotated else P3_PORTRAIT_STANDARD
    if rotated:
        reasons.append(
            f"rotation {ctx.rotation} normalized via {ctx.rotation_normalization}; "
            "portrait signature reproduced after normalization"
        )

    route = ROUTE_ROTATED if rotated else ROUTE_FAST_PATH
    if family in (NF_763x1080, NF_LETTER, NF_OTHER):
        route = ROUTE_RARE_SIZE
        reasons.append(f"rare page size {pair}: first extraction always reviewed")

    confidence = 0.99 if drift_ok else 0.75
    return RouteDecision(
        layout_family=family, exact_dimension_pair=pair,
        logical_page_class=cls, route_id=route,
        shape_signature=ctx.shape_signature_text, text_regime=regime,
        invariant_slots_match=True, fragment_count=len(sig),
        decision_confidence=confidence, reasons=reasons, signals=signals,
    )


def _invariant_slots_match(sig: Sequence[tuple[int, int]]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(sig) != EXPECTED_FRAGMENT_COUNT:
        return False, reasons
    ok = True
    for rank, want in INVARIANT_SLOTS.items():
        got = sig[rank - 1]
        if got != want:
            ok = False
            reasons.append(f"invariant slot {rank}: expected {list(want)} got {list(got)}")
    return ok, reasons


def _drift_slots_known(sig: Sequence[tuple[int, int]]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    ok = True
    for rank in DRIFT_RANKS:
        got = sig[rank - 1]
        if got not in ALLOWED_DRIFT[rank]:
            ok = False
            reasons.append(f"drift slot {rank}: unseen shape {list(got)} -> review")
    return ok, reasons


def _alien_topology_score(sig: Sequence[tuple[int, int]]) -> int:
    """How many independent signals say 'this is not a Page 3 at all'."""
    score = 0
    if len(sig) < 5:
        score += 1
    if any(r >= 20 for r, _ in sig):
        score += 1
    if any(c >= 10 for _, c in sig):
        score += 1
    invariant_shapes = set(INVARIANT_SLOTS.values())
    if not any(s in invariant_shapes for s in sig):
        score += 1
    return score


def terminal_status_for(decision: RouteDecision,
                        *,
                        had_geometry_fallback: bool,
                        had_specialist_fallback: bool,
                        open_review_items: int,
                        validation_failed: bool) -> str:
    """Exactly one terminal status per source file."""
    if decision.logical_page_class == NOT_P3_CONFIRMED:
        return QUARANTINED_NOT_LOGICAL_PAGE3
    if decision.logical_page_class == P3_REVIEW:
        return FAILED_UNRESOLVED_LAYOUT
    if validation_failed:
        return FAILED_SEMANTIC_VALIDATION
    if open_review_items > 0:
        return PARTIAL_REVIEW_REQUIRED
    if had_specialist_fallback:
        return SUCCESS_SPECIALIST_FALLBACK
    if had_geometry_fallback:
        return SUCCESS_GEOMETRY_FALLBACK
    return SUCCESS_FAST_PATH


def schema_era_for(decision: RouteDecision, sig: Sequence[tuple[int, int]]) -> dict[str, str]:
    """Assign the measured schema era per family from the shape, never the year."""
    out: dict[str, str] = {}
    if len(sig) != EXPECTED_FRAGMENT_COUNT:
        return out
    t5 = sig[7]
    if t5 == (3, 5):
        out["T5"] = "ERA-T5-A-TWO-EDGE"
    elif t5 == (5, 4):
        out["T5"] = "ERA-T5-B-FOUR-ROW-NARROW"
    elif t5 == (5, 5):
        out["T5"] = "ERA-T5-C-FOUR-ROW"
    else:
        out["T5"] = "ERA-T5-UNSEEN"

    t6 = sig[8]
    if t6 == (2, 5):
        out["T6"] = "ERA-T6-SINGLE-HEADER"
    elif t6 == (3, 5):
        out["T6"] = "ERA-T6-DOUBLE-HEADER"
    else:
        out["T6"] = "ERA-T6-UNSEEN"

    out["T2"] = f"ERA-T2-GRID-{sig[1][0]}ROW"
    return out

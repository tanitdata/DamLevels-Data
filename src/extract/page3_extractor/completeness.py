"""PATCH-P5C-002 — the generic orphan-numeric silent-omission detector.

Why a generic guard, when each family already has its own rule
--------------------------------------------------------------
The 1,029 R2 T5 daily blanks of ``AUD5B-F-001`` were invisible for two whole
phases. They were not wrong, they were *missing*, and a missing value announces
nothing: no failure, no review item, no unparseable marker. They also sat
outside the Phase 5A changed-fact register, so auditing the changes could not
have found them. Only a check that asks the opposite question — *does the page
print a number this run did not claim?* — finds that class.

What it does
------------
After extraction, for every numeric-position fact whose state is ``blank`` or
``row_absent``, it looks at the native span layer of the same source-ruled cell
and of the rest of that row, and asks whether a strict French number is printed
there that no fact claims.

What it does not do
-------------------
It never publishes a value. Detection is separate from recovery on purpose: a
family-specific rule, with its own gate, is the only thing allowed to turn a
token into a published number. This module raises a review item and a row in
``ORPHAN_NUMERIC_TOKEN_AUDIT.csv``.

Documented exclusions
---------------------
``PARENTHETICAL_LEVEL_QUALIFIER``
    a water level printed in brackets beside a metre marker — ``265 m`` and
    ``115 m`` on the Mellegue and Sidi Salem rows. It is a level, not a volume,
    and it belongs to the label.
``STRUCTURAL_UNIT_MARKER``
    the ``3`` of ``مليون م3`` and any other digit that is part of a printed unit.
``CLAIMED``
    a token some fact on the page already publishes, matched by value and by
    the cell it was read from.
Every excluded token is written to the audit table with its class, so an
exclusion is a recorded decision rather than a silence.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .native_spans import (
    TOKEN_LEVEL_QUALIFIER,
    TOKEN_MEASUREMENT,
    TOKEN_UNIT_MARKER,
    NativeToken,
    tokens_in_cell,
)
from .numbers import STATE_BLANK, STATE_NUMBER, STATE_ROW_ABSENT

#: Fact states that mean "this run published no number here".
EMPTY_STATES = (STATE_BLANK, STATE_ROW_ABSENT)

ORPHAN_UNCLAIMED = "UNCLAIMED_MEASUREMENT"
ORPHAN_LEVEL = "EXCLUDED_PARENTHETICAL_LEVEL"
ORPHAN_STRUCTURAL = "EXCLUDED_STRUCTURAL_UNIT_MARKER"
ORPHAN_CLAIMED = "CLAIMED_BY_ANOTHER_FACT"

#: Fragment rank of each family's value grid, for the row the fact came from.
_FAMILY_FRAGMENT = {"T1": (1,), "T2": (2,), "T3": (3, 4, 5),
                    "T4": (6, 7), "T5": (8,), "T6": (9,)}


def _layout_row_col(layout_slot: str) -> Optional[tuple[int, int]]:
    """``FSM-08:r2c2`` -> ``(2, 2)``; anything else -> ``None``."""
    if ":r" not in layout_slot or "c" not in layout_slot:
        return None
    try:
        _, rc = layout_slot.split(":r", 1)
        r, c = rc.split("c", 1)
        return int(r), int(c)
    except ValueError:
        return None


def detect_orphan_numeric_tokens(ctx,
                                 families: dict[str, Any],
                                 frags: dict[int, Any]) -> list[dict[str, Any]]:
    """One row per empty numeric-position fact whose cell still prints a number."""
    if ctx is None or not getattr(ctx, "native_available", False):
        return []

    empty: list[tuple[str, Any]] = []
    for fam_id, res in families.items():
        for fact in res.facts:
            if fact.value_type == "measure" and fact.semantic_state in EMPTY_STATES:
                empty.append((fam_id, fact))
    if not empty:
        return []

    tokens = ctx.native_numeric_tokens()
    if not tokens:
        return []

    claimed = _claimed_boxes(families, frags, tokens)
    out: list[dict[str, Any]] = []
    for fam_id, fact in empty:
        rc = _layout_row_col(fact.layout_slot)
        frag = frags.get(fact.fragment_rank)
        if rc is None or frag is None:
            continue
        row, col = rc
        if row + 1 >= len(frag.y_edges) or col + 1 >= len(frag.x_edges):
            continue
        box = (frag.x_edges[col], frag.y_edges[row],
               frag.x_edges[col + 1], frag.y_edges[row + 1])
        for token in tokens_in_cell(tokens, box):
            if id(token) in claimed:
                cls = ORPHAN_CLAIMED
            elif token.token_class == TOKEN_LEVEL_QUALIFIER:
                cls = ORPHAN_LEVEL
            elif token.token_class == TOKEN_UNIT_MARKER:
                cls = ORPHAN_STRUCTURAL
            elif token.token_class == TOKEN_MEASUREMENT and token.parsed_value is not None:
                cls = ORPHAN_UNCLAIMED
            else:
                cls = ORPHAN_STRUCTURAL
            out.append({
                "family_id": fam_id,
                "record_id": fact.record_id,
                "canonical_field_id": fact.canonical_field_id,
                "evidence_id": fact.evidence_id,
                "semantic_state": fact.semantic_state,
                "layout_slot": fact.layout_slot,
                "orphan_class": cls,
                "token_text": token.text,
                "token_value": token.parsed_value,
                "token_class": token.token_class,
                "token_bbox": "[{:.2f},{:.2f},{:.2f},{:.2f}]".format(*token.bbox),
                "token_span_text": token.span_text.strip(),
                "token_origin": token.origin,
                "entity_id": f"ORPHAN-{fact.canonical_field_id}-{fact.layout_slot}",
                "review_reason": (
                    f"the page prints {token.text!r} inside the cell this fact "
                    f"reads ({fact.layout_slot}), but the fact is published as "
                    f"{fact.semantic_state}. No family rule recovered it, so the "
                    f"value is not published; this is a completeness alarm, not a "
                    f"value"),
            })
    return out


def _claimed_boxes(families: dict[str, Any],
                   frags: dict[int, Any],
                   tokens: Iterable[NativeToken]) -> set[int]:
    """Tokens a published numeric fact already accounts for."""
    claimed: set[int] = set()
    token_list = list(tokens)
    for res in families.values():
        for fact in res.facts:
            if fact.semantic_state != STATE_NUMBER or fact.parsed_value is None:
                continue
            rc = _layout_row_col(fact.layout_slot)
            frag = frags.get(fact.fragment_rank)
            if rc is None or frag is None:
                continue
            row, col = rc
            if row + 1 >= len(frag.y_edges) or col + 1 >= len(frag.x_edges):
                continue
            box = (frag.x_edges[col], frag.y_edges[row],
                   frag.x_edges[col + 1], frag.y_edges[row + 1])
            for t in tokens_in_cell(token_list, box):
                if t.parsed_value == fact.parsed_value:
                    claimed.add(id(t))
    return claimed

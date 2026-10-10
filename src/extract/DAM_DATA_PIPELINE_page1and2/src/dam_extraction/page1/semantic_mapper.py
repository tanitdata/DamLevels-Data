from __future__ import annotations


def canonical_field(physical_field: str) -> str:
    """Map one physical Page-1 field to its frozen canonical name."""
    return f"p1_{physical_field}"


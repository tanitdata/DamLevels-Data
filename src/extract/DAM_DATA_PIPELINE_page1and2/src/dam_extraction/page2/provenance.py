from __future__ import annotations

from .column_geometry import bbox_string


def row_bbox(words: list[dict]) -> tuple[float, float, float, float]:
    return (
        min(float(word["x0"]) for word in words),
        min(float(word["top"]) for word in words),
        max(float(word["x1"]) for word in words),
        max(float(word["bottom"]) for word in words),
    )


def format_bbox(bbox: tuple[float, float, float, float]) -> str:
    return bbox_string(*bbox)

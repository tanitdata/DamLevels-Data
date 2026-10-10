from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnBand:
    physical_column: int
    x0: float
    x1: float

    @property
    def midpoint(self) -> float:
        return (self.x0 + self.x1) / 2.0


def detect_column_bands(rects: list[dict], *, x_tolerance: float = 5.0) -> list[ColumnBand]:
    candidates = [rect for rect in rects if float(rect["x1"]) - float(rect["x0"]) >= 5.0]
    if not candidates:
        raise ValueError("No Page-2 column rectangles found")
    ordered = sorted(candidates, key=lambda rect: (float(rect["x0"]), float(rect["x1"]) - float(rect["x0"])))
    unique = [ordered[0]]
    for rect in ordered[1:]:
        if abs(float(rect["x0"]) - float(unique[-1]["x0"])) > x_tolerance:
            unique.append(rect)
    unique.sort(key=lambda rect: float(rect["x0"]))
    if len(unique) != 26:
        raise ValueError(f"Expected exactly 26 physical Page-2 columns, found {len(unique)}")
    bands = [ColumnBand(index, float(rect["x0"]), float(rect["x1"])) for index, rect in enumerate(unique)]
    if any(left.x1 > right.x0 + 1.0 for left, right in zip(bands, bands[1:])):
        raise ValueError("Overlapping Page-2 column bands")
    return bands


def assign_physical_column(word: dict, bands: list[ColumnBand]) -> int | None:
    midpoint = (float(word["x0"]) + float(word["x1"])) / 2.0
    for band in bands:
        if band.x0 <= midpoint <= band.x1:
            return band.physical_column
    if midpoint < bands[0].x0 - 5.0 or midpoint > bands[-1].x1 + 5.0:
        return None
    return min(bands, key=lambda band: abs(band.midpoint - midpoint)).physical_column


def bucket_row_words(row_words: list[dict], bands: list[ColumnBand]) -> dict[int, list[dict]]:
    buckets: dict[int, list[dict]] = {index: [] for index in range(26)}
    seen: set[tuple[float, float, str]] = set()
    for word in sorted(row_words, key=lambda item: (float(item["x0"]), float(item["top"]), str(item["text"]))):
        key = (round(float(word["x0"]), 2), round(float(word["top"]), 2), str(word["text"]))
        if key in seen:
            continue
        seen.add(key)
        column = assign_physical_column(word, bands)
        if column is not None:
            buckets[column].append(word)
    return buckets


def join_cell_tokens(words: list[dict], *, label_cell: bool = False) -> str:
    tokens = [str(word.get("text", "")).strip() for word in sorted(words, key=lambda item: float(item["x0"]))]
    tokens = [token for token in tokens if token]
    if label_cell:
        return " ".join(tokens)
    return "".join(tokens)


def bbox_string(x0: float, top: float, x1: float, bottom: float) -> str:
    return f"{x0:.3f},{top:.3f},{x1:.3f},{bottom:.3f}"

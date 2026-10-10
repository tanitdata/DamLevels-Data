"""Coordinate normalization and the fragment cell grid.

Two measured facts drive this module (see the session probe findings):

1. On ``/Rotate 90`` pages PyMuPDF words are in the **unrotated content frame**
   while pdfplumber geometry is in the **rotated display frame**. Applying
   ``page.derotation_matrix`` to pdfplumber's boxes brings both into one frame
   and reproduces the portrait fragment signature exactly, so the whole
   downstream pipeline stays orientation-free.
2. pdfplumber emits per-row cells from *detected* intersections, so a missing
   ruling merges cells and swallows a neighbouring value. Column identity
   therefore comes from a **fragment-global edge grid**, not from the individual
   cell rectangles. The rectangles are kept only as bbox evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

BBox = tuple[float, float, float, float]

#: Tolerance for collapsing near-identical ruling coordinates into one edge.
EDGE_TOLERANCE = 2.5

ROTATION_IDENTITY = "identity"
ROTATION_DEROTATED_90 = "derotated_90"
ROTATION_DEROTATED_180 = "derotated_180"
ROTATION_DEROTATED_270 = "derotated_270"


@dataclass(frozen=True)
class Transform:
    """Affine map from the geometry engine's frame to the canonical frame."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float
    name: str

    def point(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def bbox(self, box: Sequence[float]) -> BBox:
        x0, y0, x1, y1 = (float(v) for v in box)
        p0 = self.point(x0, y0)
        p1 = self.point(x1, y1)
        return (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))

    @classmethod
    def identity(cls) -> "Transform":
        return cls(1.0, 0.0, 0.0, 1.0, 0.0, 0.0, ROTATION_IDENTITY)

    @classmethod
    def from_pymupdf_matrix(cls, m, name: str) -> "Transform":
        return cls(float(m.a), float(m.b), float(m.c), float(m.d),
                   float(m.e), float(m.f), name)


def rotation_name(rotation: int) -> str:
    return {
        0: ROTATION_IDENTITY,
        90: ROTATION_DEROTATED_90,
        180: ROTATION_DEROTATED_180,
        270: ROTATION_DEROTATED_270,
    }.get(int(rotation) % 360, ROTATION_IDENTITY)


# ---------------------------------------------------------------------- #
# Edge clustering
# ---------------------------------------------------------------------- #

def cluster_edges(values: Iterable[float], tol: float = EDGE_TOLERANCE) -> list[float]:
    """Collapse coordinates within ``tol`` into single representative edges."""
    groups: list[list[float]] = []
    for v in sorted(float(x) for x in values):
        if groups and abs(v - groups[-1][-1]) <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def nearest_edge(edges: Sequence[float], value: float) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - value))


def band_index(edges: Sequence[float], value: float) -> Optional[int]:
    """Index of the band ``[edges[i], edges[i+1])`` containing ``value``."""
    if len(edges) < 2:
        return None
    if value < edges[0] - EDGE_TOLERANCE or value > edges[-1] + EDGE_TOLERANCE:
        return None
    for i in range(len(edges) - 1):
        if edges[i] - EDGE_TOLERANCE <= value <= edges[i + 1] + EDGE_TOLERANCE:
            return i
    return len(edges) - 2


# ---------------------------------------------------------------------- #
# Words and cells
# ---------------------------------------------------------------------- #

@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def bbox(self) -> BBox:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class GridCell:
    """One (row, column) slot of a fragment's global grid."""

    row_index: int
    column_index: int
    bbox: BBox
    words: list[Word] = field(default_factory=list)
    ruled: bool = False
    ruled_bbox: Optional[BBox] = None
    row_span: int = 1
    column_span: int = 1

    @property
    def is_empty(self) -> bool:
        return not self.words


@dataclass
class Fragment:
    """A ruled table region with a global row/column grid, canonical frame."""

    index: int
    bbox: BBox
    x_edges: list[float]
    y_edges: list[float]
    cells: dict[tuple[int, int], GridCell]
    ruled_cell_count: int
    #: Words that *overlap* this fragment's rectangle but whose own centre falls
    #: outside it, so cell assignment (which is by centre, and stays that way)
    #: dropped them. On presentation-form pages PyMuPDF welds a value onto the
    #: adjacent Arabic word and the welded token's centre can land between two
    #: fragments, taking a printed number out of the grid entirely. Recording
    #: them costs nothing — the same word list is already in hand — and lets the
    #: bounded recovery in :mod:`fused_recovery` see a donor it would otherwise
    #: have no way to reach. Nothing reads this list except that recovery, and
    #: no word here is ever assigned to a cell.
    overflow_words: list[Word] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return max(0, len(self.y_edges) - 1)

    @property
    def n_cols(self) -> int:
        return max(0, len(self.x_edges) - 1)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.n_rows, self.n_cols)

    def cell(self, row: int, col: int) -> Optional[GridCell]:
        return self.cells.get((row, col))

    def row_cells(self, row: int) -> list[GridCell]:
        return [self.cells[(row, c)] for c in range(self.n_cols) if (row, c) in self.cells]

    def non_empty_columns(self, row: int) -> list[int]:
        return [c for c in range(self.n_cols)
                if (row, c) in self.cells and not self.cells[(row, c)].is_empty]


def build_fragment(index: int,
                   table_bbox: Sequence[float],
                   ruled_cells: Sequence[Sequence[float]],
                   words: Sequence[Word],
                   transform: Transform) -> Fragment:
    """Build one fragment's grid in the canonical frame.

    ``table_bbox`` and ``ruled_cells`` come from the geometry engine and are
    transformed here; ``words`` are already canonical.
    """
    nb = transform.bbox(table_bbox)
    ncells = [transform.bbox(c) for c in ruled_cells if c is not None]

    if ncells:
        x_edges = cluster_edges([c[0] for c in ncells] + [c[2] for c in ncells])
        y_edges = cluster_edges([c[1] for c in ncells] + [c[3] for c in ncells])
    else:
        x_edges = [nb[0], nb[2]]
        y_edges = [nb[1], nb[3]]

    cells: dict[tuple[int, int], GridCell] = {}
    for r in range(max(0, len(y_edges) - 1)):
        for c in range(max(0, len(x_edges) - 1)):
            cells[(r, c)] = GridCell(
                row_index=r,
                column_index=c,
                bbox=(x_edges[c], y_edges[r], x_edges[c + 1], y_edges[r + 1]),
            )

    for cb in ncells:
        r0, r1 = nearest_edge(y_edges, cb[1]), nearest_edge(y_edges, cb[3])
        c0, c1 = nearest_edge(x_edges, cb[0]), nearest_edge(x_edges, cb[2])
        if r1 <= r0 or c1 <= c0:
            continue
        slot = cells.get((r0, c0))
        if slot is not None:
            slot.ruled = True
            slot.ruled_bbox = cb
            slot.row_span = r1 - r0
            slot.column_span = c1 - c0

    # Words are assigned by their own centre against the global grid, never by
    # "which ruled rectangle happens to contain them".
    overflow: list[Word] = []
    for w in words:
        assigned = False
        if (nb[0] - EDGE_TOLERANCE <= w.cx <= nb[2] + EDGE_TOLERANCE
                and nb[1] - EDGE_TOLERANCE <= w.cy <= nb[3] + EDGE_TOLERANCE):
            r = band_index(y_edges, w.cy)
            c = band_index(x_edges, w.cx)
            slot = cells.get((r, c)) if r is not None and c is not None else None
            if slot is not None:
                slot.words.append(w)
                assigned = True
        if assigned:
            continue
        # Unassigned, but physically overlapping the table: kept aside as
        # evidence, never as a cell's content.
        if (min(nb[2], w.x1) - max(nb[0], w.x0) > 0
                and min(nb[3], w.y1) - max(nb[1], w.y0) > 0):
            overflow.append(w)

    return Fragment(
        index=index,
        bbox=nb,
        x_edges=x_edges,
        y_edges=y_edges,
        cells=cells,
        ruled_cell_count=len(ncells),
        overflow_words=overflow,
    )


def reading_order(fragments: Sequence[Fragment]) -> list[Fragment]:
    """Sort fragments the way the page reads: top to bottom, then left to right.

    Rounding the top coordinate keeps side-by-side fragments (the two ``[2,1]``
    daily-total mini-boxes and their regional neighbours) in a stable pair.
    """
    ordered = sorted(fragments, key=lambda f: (round(f.bbox[1]), f.bbox[0]))
    return [
        Fragment(i + 1, f.bbox, f.x_edges, f.y_edges, f.cells, f.ruled_cell_count,
                 f.overflow_words)
        for i, f in enumerate(ordered)
    ]


def bbox_center(b: Sequence[float]) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def vertical_gap(above: Sequence[float], below: Sequence[float]) -> float:
    """Distance from the bottom of ``above`` to the top of ``below``."""
    return float(below[1]) - float(above[3])


def horizontal_overlap(a: Sequence[float], b: Sequence[float]) -> float:
    lo = max(float(a[0]), float(b[0]))
    hi = min(float(a[2]), float(b[2]))
    return max(0.0, hi - lo)


def contains(outer: Sequence[float], inner: Sequence[float], pad: float = 1.0) -> bool:
    return (float(outer[0]) - pad <= float(inner[0])
            and float(outer[1]) - pad <= float(inner[1])
            and float(outer[2]) + pad >= float(inner[2])
            and float(outer[3]) + pad >= float(inner[3]))

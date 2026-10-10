"""Run instrumentation: stage counters, timings and the required report.

The counter set is the one the accepted architecture decision demands, plus the
per-file percentiles. Counters are *measured*, never asserted: the performance
tests read them back from the run directory, which is what makes the fast-path
claim falsifiable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from statistics import quantiles
from typing import Any, Optional, Sequence

from .page_context import StageCounters


@dataclass
class FileTiming:
    source_sha256: str
    source_relpath: str
    context_build_seconds: float
    extract_seconds: float
    validate_seconds: float
    total_seconds: float
    counters: StageCounters
    output_rows: int = 0


@dataclass
class RunPerformance:
    files: list[FileTiming] = field(default_factory=list)
    wall_start: float = field(default_factory=time.perf_counter)
    cpu_start: float = field(default_factory=time.process_time)
    wall_seconds: float = 0.0
    cpu_seconds: float = 0.0
    peak_memory_mb: float = 0.0
    output_bytes: int = 0

    def add(self, t: FileTiming) -> None:
        self.files.append(t)

    def stop(self) -> None:
        self.wall_seconds = time.perf_counter() - self.wall_start
        self.cpu_seconds = time.process_time() - self.cpu_start
        self.peak_memory_mb = _peak_memory_mb()

    # ------------------------------------------------------------------ #
    def totals(self) -> StageCounters:
        agg = StageCounters()
        for f in self.files:
            agg.add(f.counters)
        return agg

    def report(self) -> dict[str, Any]:
        durations = sorted(f.total_seconds for f in self.files)
        n = len(durations)
        agg = self.totals()
        return {
            "files_processed": n,
            "wall_seconds": round(self.wall_seconds, 3),
            "cpu_seconds": round(self.cpu_seconds, 3),
            "peak_memory_mb": round(self.peak_memory_mb, 1),
            "files_per_second": round(n / self.wall_seconds, 3) if self.wall_seconds else 0.0,
            "p50_file_seconds": _pct(durations, 50),
            "p95_file_seconds": _pct(durations, 95),
            "p99_file_seconds": _pct(durations, 99),
            "mean_file_seconds": round(sum(durations) / n, 4) if n else 0.0,
            "max_file_seconds": round(durations[-1], 4) if n else 0.0,
            "source_filesystem_reads": agg.source_filesystem_reads,
            "source_bytes_read": agg.source_bytes_read,
            "pymupdf_document_opens": agg.pymupdf_document_opens,
            "pdfplumber_document_opens": agg.pdfplumber_document_opens,
            "textpage_builds": agg.textpage_builds,
            "word_extractions": agg.word_extractions,
            # Reads of the *existing* TextPage's span layer. At most one per
            # page, and zero on a page whose word-level fast path succeeded, so
            # this is the number that makes "conditional fallback" falsifiable.
            "rawdict_extractions": agg.rawdict_extractions,
            # Glyph-trace reads of the content stream. At most one per page, and
            # zero on every page that holds no R1 T2 overprint candidate, so
            # this is what makes "conditional second representation" falsifiable.
            "glyph_trace_extractions": agg.glyph_trace_extractions,
            "drawing_scans": agg.drawing_scans,
            "page_renders": agg.page_renders,
            "ocr_invocations": agg.ocr_invocations,
            "camelot_invocations": agg.camelot_invocations,
            "opencv_invocations": agg.opencv_invocations,
            "fallback_counts": agg.fallback_count,
            "cache_hits": agg.cache_hits,
            "cache_misses": agg.cache_misses,
            "output_bytes": self.output_bytes,
        }


def _pct(sorted_values: Sequence[float], p: int) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(sorted_values[0], 4)
    k = (len(sorted_values) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    frac = k - lo
    return round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac, 4)


def _peak_memory_mb() -> float:
    try:  # pragma: no cover - platform dependent
        import resource  # type: ignore

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except ImportError:
        pass
    try:  # pragma: no cover - Windows
        import ctypes
        import ctypes.wintypes as wt

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PMC()
        counters.cb = ctypes.sizeof(PMC)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001
        pass
    return 0.0


# ---------------------------------------------------------------------- #
# Fast-path assertions
# ---------------------------------------------------------------------- #
#: The counters an ordinary uncached vector file must show, per the accepted
#: contract. ``pdfplumber_document_opens`` is capped, not fixed, because the D1
#: upgrade gate may legitimately reach zero one day.
FAST_PATH_EXPECTATIONS = {
    "source_filesystem_reads": ("==", 1),
    "pymupdf_document_opens": ("==", 1),
    "textpage_builds": ("==", 1),
    "drawing_scans": ("==", 1),
    "pdfplumber_document_opens": ("<=", 1),
    # The conditional native-span fallback reads the TextPage the context
    # already holds. Reading it twice would mean the memoization broke; reading
    # it on every page would mean the fallback stopped being conditional. Only
    # the first is an architecture violation, so this is capped, not fixed.
    "rawdict_extractions": ("<=", 1),
    # PATCH-P5D-001. The conditional glyph trace walks the content stream the
    # open page already holds. Reading it twice would mean the memoization
    # broke; reading it on every page would mean it stopped being conditional.
    # Only the first is an architecture violation, so this is capped, not fixed.
    "glyph_trace_extractions": ("<=", 1),
    "page_renders": ("==", 0),
    "ocr_invocations": ("==", 0),
}


def check_fast_path(counters: StageCounters) -> list[str]:
    """Return the list of violated counter expectations (empty means clean)."""
    out = []
    d = counters.as_dict()
    for name, (op, want) in FAST_PATH_EXPECTATIONS.items():
        got = d.get(name, 0)
        if op == "==" and got != want:
            out.append(f"{name}: expected == {want}, got {got}")
        elif op == "<=" and got > want:
            out.append(f"{name}: expected <= {want}, got {got}")
    return out


# ---------------------------------------------------------------------- #
# Inefficient baseline, for the speedup comparison
# ---------------------------------------------------------------------- #

def repeated_open_baseline(paths: Sequence[Any], sections: int = 6) -> dict[str, Any]:
    """Deliberately inefficient baseline: rebuild everything once per section.

    This is the "one PDF open per table" design the architecture forbids. For
    the comparison to mean anything it must do the *same* per-section work the
    shared context does once — read the bytes, open the document, build a
    TextPage, extract words, scan drawings, and open pdfplumber for geometry —
    and simply repeat all of it for each of the six T-families. A baseline that
    skipped the geometry stage would be measuring a different program and would
    flatter or damn the real design at random.
    """
    import io

    import fitz
    import pdfplumber

    t0 = time.perf_counter()
    reads = opens = textpages = drawings = plumber = 0
    for p in paths:
        for _ in range(sections):
            with open(p, "rb") as fh:
                data = fh.read()
            reads += 1
            doc = fitz.open(stream=data, filetype="pdf")
            opens += 1
            page = doc[0]
            tp = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
            textpages += 1
            page.get_text("words", textpage=tp)
            page.get_text("text", textpage=tp)
            page.get_drawings()
            drawings += 1
            doc.close()
            with pdfplumber.open(io.BytesIO(data)) as pl:
                for t in pl.pages[0].find_tables():
                    for row in t.rows:
                        _ = row.cells
            plumber += 1
    wall = time.perf_counter() - t0
    n = len(paths)
    return {
        "design": "D3_naive_repeated_open",
        "sections_per_file": sections,
        "files_processed": n,
        "wall_seconds": round(wall, 3),
        "per_file_seconds": round(wall / n, 4) if n else 0.0,
        "source_filesystem_reads": reads,
        "pymupdf_document_opens": opens,
        "textpage_builds": textpages,
        "drawing_scans": drawings,
        "pdfplumber_document_opens": plumber,
    }

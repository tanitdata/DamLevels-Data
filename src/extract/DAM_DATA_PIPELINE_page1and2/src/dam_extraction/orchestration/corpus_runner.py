from __future__ import annotations

import os
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Iterable, Iterator

from dam_extraction.common.contracts import ExecutionScope, Page1ExtractionResult
from dam_extraction.page1.engine import extract_page1_pdf


@dataclass(frozen=True)
class CorpusOutcome:
    """One source result or a captured worker failure, tagged with source order."""

    source_index: int
    source_path: str
    result: Page1ExtractionResult | None
    failure_class: str | None = None
    failure_message: str | None = None
    failure_traceback: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.result is not None and self.failure_class is None


def deterministic_pdf_inventory(pdf_paths: Iterable[str | Path]) -> list[Path]:
    """Return a stable, duplicate-free absolute inventory.

    The full path is the tie-breaker so case-insensitive filename collisions
    cannot make ordering depend on filesystem enumeration order.
    """
    unique = {str(Path(value).resolve()).casefold(): Path(value).resolve() for value in pdf_paths}
    return sorted(unique.values(), key=lambda path: (path.name.casefold(), str(path).casefold()))


def resolve_worker_count(requested: int | str | None = "auto") -> int:
    """Choose a conservative CPU/memory-bounded worker count.

    Auto mode reserves 1.25 GiB for the controller/desktop and budgets 400 MiB
    per PDF worker. An explicit integer remains an operator override.
    """
    if requested not in (None, "auto", "AUTO", 0, "0"):
        workers = int(requested)
        if workers < 1:
            raise ValueError("workers must be >= 1 or 'auto'")
        return workers

    logical = max(1, os.cpu_count() or 1)
    physical = max(1, logical // 2)
    memory_bound = physical
    try:
        import psutil

        available = int(psutil.virtual_memory().available)
        reserve = int(1.25 * 1024**3)
        per_worker = 400 * 1024**2
        memory_bound = max(1, (available - reserve) // per_worker)
    except Exception:
        pass
    return max(1, min(physical, int(memory_bound), 8))


def _worker_extract(task: tuple[int, str, str, list[dict[str, str]] | None, str | None]) -> CorpusOutcome:
    """Top-level Windows-spawn worker; every call independently opens its PDF."""
    index, path, scope, targets, alias_registry_path = task
    try:
        result = extract_page1_pdf(
            path,
            scope=scope,
            target_keys=targets,
            alias_registry_path=alias_registry_path,
        )
        return CorpusOutcome(index, path, result)
    except Exception as exc:  # worker failures are data, never silently dropped
        return CorpusOutcome(
            index,
            path,
            None,
            type(exc).__name__,
            str(exc),
            traceback.format_exc(),
        )


def run_page1_corpus_outcomes(
    pdf_paths: Iterable[str | Path],
    *,
    scope: ExecutionScope | str = ExecutionScope.FULL,
    targets_by_file: dict[str, list[dict[str, str]]] | None = None,
    workers: int | str | None = "auto",
    alias_registry_path: str | Path | None = None,
    max_pending_factor: int = 2,
) -> Iterator[CorpusOutcome]:
    """Extract with bounded process parallelism and yield in source order.

    Worker completion order cannot affect consumer order. The controller keeps
    at most ``workers * max_pending_factor`` outcomes in flight or buffered.
    No PDF or SQLite object crosses a process boundary.
    """
    inventory = deterministic_pdf_inventory(pdf_paths)
    scope_value = scope if isinstance(scope, ExecutionScope) else ExecutionScope(str(scope).upper())
    worker_count = resolve_worker_count(workers)
    alias = None if alias_registry_path is None else str(Path(alias_registry_path).resolve())
    tasks = [
        (
            index,
            str(path),
            scope_value.value,
            None if targets_by_file is None else targets_by_file.get(path.name),
            alias,
        )
        for index, path in enumerate(inventory)
    ]
    if worker_count == 1:
        for task in tasks:
            yield _worker_extract(task)
        return

    window = max(worker_count, worker_count * max(1, int(max_pending_factor)))
    context = get_context("spawn")
    with ProcessPoolExecutor(max_workers=worker_count, mp_context=context) as executor:
        pending: dict[object, int] = {}
        ready: dict[int, CorpusOutcome] = {}
        next_submit = 0
        next_yield = 0

        def submit_until_full() -> None:
            nonlocal next_submit
            while next_submit < len(tasks) and len(pending) + len(ready) < window:
                future = executor.submit(_worker_extract, tasks[next_submit])
                pending[future] = next_submit
                next_submit += 1

        submit_until_full()
        while next_yield < len(tasks):
            if next_yield in ready:
                outcome = ready.pop(next_yield)
                next_yield += 1
                submit_until_full()
                yield outcome
                continue

            completed, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in completed:
                index = pending.pop(future)
                try:
                    ready[index] = future.result()
                except BaseException as exc:
                    ready[index] = CorpusOutcome(
                        index,
                        tasks[index][1],
                        None,
                        type(exc).__name__,
                        str(exc),
                        traceback.format_exc(),
                    )


def run_page1_corpus(
    pdf_paths: Iterable[str | Path],
    *,
    scope: ExecutionScope | str = ExecutionScope.FULL,
    targets_by_file: dict[str, list[dict[str, str]]] | None = None,
    workers: int | str | None = 1,
) -> Iterator[Page1ExtractionResult]:
    """Compatibility API returning successful results and surfacing failures."""
    for outcome in run_page1_corpus_outcomes(
        pdf_paths,
        scope=scope,
        targets_by_file=targets_by_file,
        workers=workers,
    ):
        if not outcome.succeeded:
            raise RuntimeError(
                f"Page-1 extraction failed for {outcome.source_path}: "
                f"{outcome.failure_class}: {outcome.failure_message}"
            )
        assert outcome.result is not None
        yield outcome.result

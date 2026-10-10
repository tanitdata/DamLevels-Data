"""Pure helpers for professor QA checks A, B, and H.

The helpers in this module operate on passed values only. They do not invoke
the production extractor, mutate accepted observations, or fill missing data.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Callable, Iterable, Mapping, Sequence, TypeVar


T = TypeVar("T")


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Return the two-sided Wilson score interval for a binomial proportion."""
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("successes/trials are inconsistent")
    if trials == 0:
        return (0.0, 1.0)
    p = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (p + z * z / (2.0 * trials)) / denominator
    half = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * trials)) / trials) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def accuracy_target_decision(
    *,
    accuracy: float | None,
    wilson_lower: float | None,
    target: float,
    design_supports_population_inference: bool,
) -> str:
    """Classify a population target without overstating a descriptive interval.

    A pooled simple-binomial interval can support ``YES`` only when the audit
    design supports the corresponding population inference. Unequal stratum
    allocation or clustered observations require an appropriate design-based
    estimator before that claim can be made.
    """
    if accuracy is None or wilson_lower is None:
        return "INCONCLUSIVE"
    if not design_supports_population_inference:
        return "INCONCLUSIVE"
    if wilson_lower >= target:
        return "YES"
    if accuracy < target:
        return "NO"
    return "INCONCLUSIVE"


def minimum_zero_error_sample_size(
    target: float = 0.995,
    confidence: float = 0.95,
) -> int:
    """Return the first zero-error sample size whose Wilson lower bound meets target."""
    if not 0.0 < target < 1.0:
        raise ValueError("target must be between zero and one")
    if confidence != 0.95:
        raise ValueError("only the tested two-sided 95% Wilson contract is supported")
    trials = 1
    while wilson_interval(trials, trials)[0] < target:
        trials += 1
    return trials


def proportional_allocation(populations: Mapping[str, int], sample_size: int) -> dict[str, int]:
    """Allocate a fixed sample by largest remainder, bounded by stratum size."""
    if sample_size < 0 or any(value < 0 for value in populations.values()):
        raise ValueError("sample and population sizes must be nonnegative")
    total = sum(populations.values())
    if sample_size > total:
        raise ValueError("sample exceeds population")
    if total == 0:
        return {key: 0 for key in populations}
    exact = {key: sample_size * value / total for key, value in populations.items()}
    allocated = {key: min(populations[key], int(exact[key])) for key in populations}
    remaining = sample_size - sum(allocated.values())
    order = sorted(
        populations,
        key=lambda key: (exact[key] - int(exact[key]), populations[key], key),
        reverse=True,
    )
    for key in order:
        if remaining == 0:
            break
        if allocated[key] < populations[key]:
            allocated[key] += 1
            remaining -= 1
    if remaining:
        raise ValueError("allocation could not satisfy bounded strata")
    return allocated


def proportional_stratified_sample(
    records_by_stratum: Mapping[str, Sequence[T]],
    sample_size: int,
    *,
    seed: int,
    stable_key: Callable[[T], str],
) -> tuple[list[T], dict[str, int]]:
    """Select a fixed-seed proportional sample without replacement."""
    import random

    populations = {key: len(value) for key, value in records_by_stratum.items()}
    allocation = proportional_allocation(populations, sample_size)
    rng = random.Random(seed)
    selected: list[T] = []
    for stratum in sorted(records_by_stratum):
        records = sorted(records_by_stratum[stratum], key=stable_key)
        selected.extend(rng.sample(records, allocation[stratum]))
    return sorted(selected, key=stable_key), allocation


def assert_one_primary_cell_per_pdf(rows: Iterable[Mapping[str, object]]) -> None:
    """Reject a primary sample containing more than one target cell per PDF."""
    seen: set[str] = set()
    for row in rows:
        source_file = str(row["source_file"])
        if source_file in seen:
            raise ValueError(f"primary sample contains duplicate PDF {source_file}")
        seen.add(source_file)


def multipage_target_decision(
    *,
    matches: int,
    eligible: int,
    required_zero_error_sample_size: int,
    target: float,
    independent_pdf_design: bool,
) -> tuple[str, float | None, float | None]:
    """Evaluate one page family; challenge and semantic rows belong elsewhere."""
    if eligible == 0:
        return "INCONCLUSIVE", None, None
    lower, upper = wilson_interval(matches, eligible)
    accuracy = matches / eligible
    design_valid = independent_pdf_design and eligible >= required_zero_error_sample_size
    return (
        accuracy_target_decision(
            accuracy=accuracy,
            wilson_lower=lower,
            target=target,
            design_supports_population_inference=design_valid,
        ),
        lower,
        upper,
    )


def parse_pdf_number(text: str) -> Decimal | None:
    """Parse one complete printed numeric token using French decimal commas.

    Any extra, ambiguous text makes the cell unverifiable. Missing is never
    converted to zero.
    """
    compact = text.replace("\u00a0", "").replace("\u202f", "")
    compact = re.sub(r"\s+", "", compact)
    if not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", compact):
        return None
    try:
        return Decimal(compact.replace(",", "."))
    except InvalidOperation:
        return None


def classify_extraction(repository_value: Decimal, source_value: Decimal | None) -> tuple[str, bool | None]:
    if source_value is None:
        return "UNVERIFIABLE", None
    if source_value == repository_value:
        return "MATCH", True
    return "EXTRACTION_DISCREPANCY_CANDIDATE", False


@dataclass(frozen=True)
class GapSummary:
    missing_count: int
    longest_run: int
    longest_start: str
    longest_end: str
    leading_run: int
    trailing_run: int


def missing_run_summary(expected_dates: list[str], observed_dates: set[str]) -> GapSummary:
    """Summarize consecutive missing opportunities in an ordered expected calendar."""
    missing = [day not in observed_dates for day in expected_dates]
    best_length = current_length = 0
    best_start = best_end = current_start = -1
    for index, is_missing in enumerate(missing):
        if is_missing:
            if current_length == 0:
                current_start = index
            current_length += 1
            if current_length > best_length:
                best_length = current_length
                best_start = current_start
                best_end = index
        else:
            current_length = 0
    leading = 0
    for is_missing in missing:
        if not is_missing:
            break
        leading += 1
    trailing = 0
    for is_missing in reversed(missing):
        if not is_missing:
            break
        trailing += 1
    return GapSummary(
        missing_count=sum(missing),
        longest_run=best_length,
        longest_start=expected_dates[best_start] if best_start >= 0 else "",
        longest_end=expected_dates[best_end] if best_end >= 0 else "",
        leading_run=leading,
        trailing_run=trailing,
    )


def classify_date_completeness(*, bulletin_present: bool, page1_present: bool, observed: int, expected: int) -> str:
    if not bulletin_present:
        return "NO_BULLETIN"
    if not page1_present:
        return "PARTIAL_BULLETIN"
    return "COMPLETE" if observed == expected else "DAM_NOT_REPORTED"


def median_mad(values: Iterable[Decimal]) -> tuple[Decimal | None, Decimal | None]:
    items = list(values)
    if not items:
        return None, None
    centre = median(items)
    deviations = [abs(item - centre) for item in items]
    return centre, median(deviations)


def robust_z(value: Decimal, centre: Decimal, mad: Decimal) -> Decimal | None:
    if mad == 0:
        return Decimal(0) if value == centre else None
    return Decimal("0.6745") * (value - centre) / mad


def classify_temporal(
    *,
    elapsed_days: int | None,
    delta: Decimal | None,
    centre: Decimal | None,
    mad: Decimal | None,
    threshold: Decimal = Decimal("6"),
) -> tuple[str, Decimal | None]:
    if elapsed_days is None or delta is None or elapsed_days != 1:
        return "GAP_NOT_COMPARABLE", None
    if centre is None or mad is None:
        return "UNRESOLVED", None
    score = robust_z(delta, centre, mad)
    if score is None:
        return "SOURCE_REVIEW_REQUIRED", None
    if abs(score) >= threshold:
        return "ROBUST_OUTLIER", score
    return "NORMAL", score


def date_span_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days

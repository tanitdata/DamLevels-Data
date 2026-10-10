"""Validation rules, evaluated from stored evidence only.

Nothing here reopens a source file. Every rule states its eligibility before its
result, so "did not apply" is never reported as "passed", and a rule that
cannot run on a page produces a ``NOT_ELIGIBLE`` row rather than silence.

No rule repairs a value. A failed check is a recorded disagreement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .evidence import Fact
from .numbers import STATE_NUMBER
from .semantic_mapping import T1, T2, T3, T4, T5, T6

# --- statuses ------------------------------------------------------------ #
PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
NOT_ELIGIBLE = "NOT_ELIGIBLE"

ELIGIBLE = "ELIGIBLE"
INELIGIBLE_MISSING_INPUT = "INELIGIBLE_MISSING_INPUT"
INELIGIBLE_NON_NUMERIC_STATE = "INELIGIBLE_NON_NUMERIC_STATE"
INELIGIBLE_SCHEMA_ERA = "INELIGIBLE_SCHEMA_ERA"

#: The bulletins print three decimals in Mm3, so a printed value carries at most
#: half an increment of rounding error.
DISPLAY_INCREMENT = 0.001
HALF_INCREMENT = DISPLAY_INCREMENT / 2
_EPS = 1e-9

#: Kept for callers that compare a value against an external source of unknown
#: precision. The rules below deliberately do **not** use a relative tolerance:
#: every quantity they compare is printed at the same fixed precision, so the
#: honest bound is rounding-derived. A 0.5% relative band would let a 5 Mm3
#: error pass on a 1000 Mm3 national total and hide exactly the column-mapping
#: mistakes these rules exist to catch.
ABSOLUTE_TOLERANCE = 0.0015
RELATIVE_TOLERANCE = 0.005


def rounding_tolerance(printed_value_count: int) -> float:
    """Worst-case disagreement from display rounding alone.

    Each printed value contributes at most half a display increment, so an
    identity over ``n`` printed values tolerates ``n/2`` increments.
    """
    return printed_value_count * HALF_INCREMENT + _EPS


#: Number of per-dam components the bulletin sums, unprinted, into each printed
#: regional figure and into the printed national total. Measured from the corpus:
#: the T2 grid publishes 10 dam rows per page, and the regional aggregates cover
#: the full ~30-dam network, not only the selected rows.
UNPRINTED_COMPONENT_COUNT = 36


def unprinted_component_tolerance(printed_value_count: int) -> float:
    """Bound for an identity whose terms are each rounded *sums of rounded parts*.

    ``VR-T3-01`` / ``VR-T4-01`` compare a printed national total against three
    printed regional figures. Those four numbers are not four independent
    roundings of one exact quantity: each is itself an aggregate of per-dam
    values the page never prints, and each of those is rounded before being
    summed. The honest bound is therefore the printed-rounding term *plus* one
    half-increment per unprinted component.

    Measured on the frozen reference run, over the 3,619 T3 and 3,620 T4 pages
    where all four terms are printed numbers: 99.78% and 99.61% of residuals
    fall below 0.006, and exactly 11 pages in total exceed 0.02. Treating the
    0.002-0.006 band as a failure — which the 1.0.0 rule did — turned 3,264 of
    3,382 FAIL verdicts into an artefact of the tolerance model (AUD-F-004 /
    PATCH-P4-003) rather than a statement about the source.
    """
    return (printed_value_count + UNPRINTED_COMPONENT_COUNT) * HALF_INCREMENT + _EPS


#: Alias used by the recovery gates, so the tolerance a recovered value must
#: satisfy is the same number the validation rule publishes.
regional_sum_tolerance = unprinted_component_tolerance


@dataclass
class ValidationResult:
    section_id: str
    entity_type: str
    entity_id: str
    rule_id: str
    eligibility_status: str
    observed_value: Optional[float]
    comparison_value: Optional[float]
    difference: Optional[float]
    tolerance: Optional[float]
    status: str
    severity: str
    evidence: dict
    #: Evidence ids of the facts this rule actually consumed, set only by rules
    #: that test an identity the *source* printed. This is what lets
    #: ``source_consistency_status`` be a per-fact statement instead of a family
    #: verdict smeared over every value on the page.
    arithmetic_scope: tuple[str, ...] = ()


def _severity(status: str) -> str:
    return {PASS: "info", WARN: "warning", FAIL: "error"}.get(status, "info")


def _by_field(facts: Sequence[Fact], family: str, field_id: str,
              record_id: Optional[str] = None) -> Optional[Fact]:
    for f in facts:
        if f.family_id != family or f.canonical_field_id != field_id:
            continue
        if record_id is not None and not f.record_id.endswith(record_id):
            continue
        return f
    return None


def _num(fact: Optional[Fact]) -> Optional[float]:
    if fact is None or fact.semantic_state != STATE_NUMBER:
        return None
    return fact.parsed_value


def _identity_check(printed: float, derived: float, printed_value_count: int,
                    *, unprinted_components: bool = False
                    ) -> tuple[str, float, float]:
    """Compare a printed value against the identity it should satisfy.

    Returns ``(status, difference, tolerance)``. Exact agreement passes;
    agreement only after rounding warns, because at corpus scale the distinction
    between "the arithmetic holds" and "the arithmetic holds once you allow for
    rounding" is worth seeing; anything wider fails.

    ``unprinted_components`` selects the wider bound for an identity whose terms
    are rounded sums of values the page never prints — see
    :func:`unprinted_component_tolerance`. Without it the rule reports a
    property of its own tolerance model rather than of the bulletin.
    """
    diff = printed - derived
    tol = (unprinted_component_tolerance(printed_value_count) if unprinted_components
           else rounding_tolerance(printed_value_count))
    if abs(diff) <= _EPS:
        return PASS, diff, tol
    if abs(diff) <= tol:
        return WARN, diff, tol
    return FAIL, diff, tol


def _scope(*facts: Optional[Fact]) -> tuple[str, ...]:
    return tuple(f.evidence_id for f in facts if f is not None and f.evidence_id)


def run_validations(facts: Sequence[Fact],
                    *,
                    family_status: dict[str, str],
                    t2_row_count: int,
                    filename_date: Optional[str],
                    printed_date: Optional[str]) -> list[ValidationResult]:
    out: list[ValidationResult] = []
    out.append(_rule_t1_difference(facts))
    out.append(_rule_t3_regional_sum(facts))
    out.append(_rule_t4_regional_sum(facts))
    out.append(_rule_t3_comparator_difference(facts))
    out.extend(_rule_t2_fill_pct_range(facts))
    out.append(_rule_t2_row_count(t2_row_count))
    out.append(_rule_date_agreement(filename_date, printed_date))
    out.extend(_rule_family_presence(family_status))
    out.append(_rule_no_silent_zero(facts))
    return [r for r in out if r is not None]


def _rule_t1_difference(facts: Sequence[Fact]) -> ValidationResult:
    """T1 prints today, the 3-year average, and their difference."""
    f_today = _by_field(facts, T1, "p3_t1_stock_current_season_today_mm3")
    f_avg = _by_field(facts, T1, "p3_t1_stock_3yr_same_day_avg_mm3")
    f_printed = _by_field(facts, T1, "p3_t1_stock_difference_mm3")
    today, avg, printed = _num(f_today), _num(f_avg), _num(f_printed)
    scope = _scope(f_today, f_avg, f_printed)
    if today is None or avg is None or printed is None:
        return ValidationResult(T1, "page", "T1-GENERAL", "VR-T1-01",
                                INELIGIBLE_MISSING_INPUT, printed, None, None, None,
                                NOT_ELIGIBLE, "info",
                                {"reason": "one or more T1 values is not a number"})
    status, diff, tol = _identity_check(printed, today - avg, 3)
    return ValidationResult(T1, "page", "T1-GENERAL", "VR-T1-01", ELIGIBLE,
                            printed, today - avg, diff, tol,
                            status, _severity(status),
                            {"today": today, "three_year_average": avg},
                            arithmetic_scope=scope)


def _regional_sum_rule(facts: Sequence[Fact], family: str, region_field: str,
                       total_field: str, rule_id: str) -> ValidationResult:
    parts = [f for f in facts
             if f.family_id == family and f.canonical_field_id == region_field]
    total_fact = _by_field(facts, family, total_field)
    total = _num(total_fact)
    values = [_num(p) for p in parts]
    scope = _scope(total_fact, *parts)
    if total is None or not values or any(v is None for v in values):
        return ValidationResult(family, "page", f"{family}-REGIONAL-SUM", rule_id,
                                INELIGIBLE_MISSING_INPUT, total, None, None, None,
                                NOT_ELIGIBLE, "info",
                                {"reason": "regional parts or the printed total is "
                                           "not a number", "parts": len(parts)})
    s = sum(v for v in values if v is not None)
    # Each printed figure is itself a rounded sum of per-dam values the page does
    # not print, so the bound is the printed-rounding term plus one half
    # increment per unprinted component (PATCH-P4-003 / AUD-F-004).
    status, diff, tol = _identity_check(total, s, len(values) + 1,
                                        unprinted_components=True)
    return ValidationResult(family, "page", f"{family}-REGIONAL-SUM", rule_id, ELIGIBLE,
                            total, s, diff, tol, status, _severity(status),
                            {"parts": [v for v in values], "part_count": len(values),
                             "tolerance_model": "printed_rounding+unprinted_components"},
                            arithmetic_scope=scope)


def _rule_t3_regional_sum(facts: Sequence[Fact]) -> ValidationResult:
    return _regional_sum_rule(facts, T3, "p3_t3_inflow_region_today_mm3",
                              "p3_t3_inflow_total_today_mm3", "VR-T3-01")


def _rule_t4_regional_sum(facts: Sequence[Fact]) -> ValidationResult:
    return _regional_sum_rule(facts, T4, "p3_t4_withdrawal_region_today_mm3",
                              "p3_t4_withdrawal_total_today_mm3", "VR-T4-01")


def _rule_t3_comparator_difference(facts: Sequence[Fact]) -> ValidationResult:
    f_cur = _by_field(facts, T3, "p3_t3_inflow_current_season_cum_mm3")
    f_avg = _by_field(facts, T3, "p3_t3_inflow_period_average_mm3")
    f_printed = _by_field(facts, T3, "p3_t3_inflow_difference_vs_period_mm3")
    cur, avg, printed = _num(f_cur), _num(f_avg), _num(f_printed)
    if cur is None or avg is None or printed is None:
        return ValidationResult(T3, "page", "T3-COMPARATOR", "VR-T3-02",
                                INELIGIBLE_MISSING_INPUT, printed, None, None, None,
                                NOT_ELIGIBLE, "info",
                                {"reason": "comparator values incomplete"})
    status, diff, tol = _identity_check(printed, cur - avg, 3)
    return ValidationResult(T3, "page", "T3-COMPARATOR", "VR-T3-02", ELIGIBLE,
                            printed, cur - avg, diff, tol,
                            status, _severity(status),
                            {"current_season": cur, "period_average": avg},
                            arithmetic_scope=_scope(f_cur, f_avg, f_printed))


def _rule_t2_fill_pct_range(facts: Sequence[Fact]) -> list[ValidationResult]:
    out = []
    for f in facts:
        if f.family_id != T2 or f.canonical_field_id != "p3_t2_dam_fill_pct":
            continue
        if f.semantic_state != STATE_NUMBER or f.parsed_value is None:
            out.append(ValidationResult(T2, "dam", f.record_id, "VR-T2-01",
                                        INELIGIBLE_NON_NUMERIC_STATE, None, None, None,
                                        None, NOT_ELIGIBLE, "info",
                                        {"semantic_state": f.semantic_state}))
            continue
        v = f.parsed_value
        # Over-100 fills are physically meaningful (a dam above its normal
        # level), so they warn rather than fail.
        status = PASS if 0 <= v <= 100 else WARN
        out.append(ValidationResult(T2, "dam", f.record_id, "VR-T2-01", ELIGIBLE,
                                    v, None, None, None, status,
                                    "info" if status == PASS else "warning",
                                    {"evidence_id": f.evidence_id,
                                     "dam_id": f.dam_id}))
    return out


def _rule_t2_row_count(t2_row_count: int) -> ValidationResult:
    """The roster size is measured, not assumed. Out-of-band counts get a look."""
    expected_band = (8, 14)
    ok = expected_band[0] <= t2_row_count <= expected_band[1]
    return ValidationResult(T2, "page", "T2-ROW-COUNT", "VR-T2-02", ELIGIBLE,
                            float(t2_row_count), None, None, None,
                            PASS if ok else WARN, "info" if ok else "warning",
                            {"observed_band": list(expected_band)})


def _rule_date_agreement(filename_date: Optional[str],
                         printed_date: Optional[str]) -> ValidationResult:
    if not filename_date or not printed_date:
        return ValidationResult("PAGE", "page", "DATE", "VR-DATE-01",
                                INELIGIBLE_MISSING_INPUT, None, None, None, None,
                                NOT_ELIGIBLE, "info",
                                {"filename_date": filename_date or "",
                                 "printed_date": printed_date or ""})
    ok = filename_date == printed_date
    return ValidationResult("PAGE", "page", "DATE", "VR-DATE-01", ELIGIBLE,
                            None, None, None, None,
                            PASS if ok else FAIL, "info" if ok else "error",
                            {"filename_date": filename_date, "printed_date": printed_date})


def _rule_family_presence(family_status: dict[str, str]) -> list[ValidationResult]:
    out = []
    for fam in (T1, T2, T3, T4, T5, T6):
        st = family_status.get(fam, "MISSING")
        ok = st in ("OK", "PARTIAL")
        out.append(ValidationResult(fam, "page", f"{fam}-PRESENCE", "VR-PRESENCE-01",
                                    ELIGIBLE, None, None, None, None,
                                    PASS if st == "OK" else (WARN if ok else FAIL),
                                    "info" if st == "OK" else ("warning" if ok else "error"),
                                    {"family_status": st}))
    return out


def _rule_no_silent_zero(facts: Sequence[Fact]) -> ValidationResult:
    """Guard the project's hardest rule: nothing non-numeric may become zero."""
    offenders = [
        f.evidence_id for f in facts
        if f.semantic_state != STATE_NUMBER and f.parsed_value is not None
    ]
    return ValidationResult("PAGE", "page", "NO-SILENT-ZERO", "VR-GUARD-01", ELIGIBLE,
                            float(len(offenders)), 0.0, float(len(offenders)), 0.0,
                            PASS if not offenders else FAIL,
                            "info" if not offenders else "error",
                            {"offending_evidence_ids": offenders[:20]})


def has_blocking_failure(results: Iterable[ValidationResult]) -> bool:
    """Only the structural guard blocks a page; arithmetic disagreements do not.

    A printed difference that does not reconcile is evidence about the source,
    not proof that extraction failed, so it is published with its status rather
    than suppressed.
    """
    return any(r.rule_id == "VR-GUARD-01" and r.status == FAIL for r in results)

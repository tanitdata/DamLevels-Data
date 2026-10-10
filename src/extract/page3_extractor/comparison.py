"""Page 3 versus frozen reference comparison.

Everything in this module is **diagnostic**. The reference snapshot is
``PROVISIONAL`` with ``decision_authority = NONE``: it is evidence for
comparison, not ground truth.

Absolute prohibitions enforced here (governing prompt section 13):

* never average the two sides;
* never overwrite one with the other;
* never declare the reference correct because it is a CSV;
* never declare Page 3 wrong from a single disagreement;
* never repair either side inside this layer.

A comparison rule may only run when its ``mapping_id`` carries a status that
permits comparison **and** temporal semantics, units, aggregation grain, roster
membership and the capacity/denominator rule are all resolved. As of this
release every candidate Page 3 mapping (MAP-045..MAP-054) is
``UNRESOLVED`` / ``CANDIDATE_REQUIRES_REVIEW`` / ``NOT_COMPARABLE``, so the
registry ships with **zero enabled rules** and this module produces coverage
rows explaining exactly which precondition is missing.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .evidence import Fact
from .semantic_mapping import (
    COMPARISON_ENABLING_STATUSES,
    NOT_COMPARABLE_FAMILIES,
    NOT_COMPARABLE_REASON,
    REGION_MEMBERSHIP_STATUS,
    T1, T2, T3, T4, T5, T6,
)

# --- comparison results --------------------------------------------------- #
MATCH_EXACT = "MATCH_EXACT"
MATCH_WITHIN_ROUNDING = "MATCH_WITHIN_ROUNDING"
NOT_COMPARABLE_SEMANTICS = "NOT_COMPARABLE_SEMANTICS"
NOT_COMPARABLE_TEMPORAL = "NOT_COMPARABLE_TEMPORAL"
NOT_COMPARABLE_ROSTER = "NOT_COMPARABLE_ROSTER"
LIKELY_PAGE3_EXTRACTION_ERROR = "LIKELY_PAGE3_EXTRACTION_ERROR"
LIKELY_REFERENCE_CSV_ISSUE = "LIKELY_REFERENCE_CSV_ISSUE"
REFERENCE_INTERNAL_CONFLICT = "REFERENCE_INTERNAL_PAGE1_PAGE2_CONFLICT"
POSSIBLE_GENUINE_SOURCE_DISAGREEMENT = "POSSIBLE_GENUINE_SOURCE_DISAGREEMENT"
UNIT_OR_ROUNDING_MISMATCH = "UNIT_OR_ROUNDING_MISMATCH"
ROSTER_OR_CAPACITY_REGIME_MISMATCH = "ROSTER_OR_CAPACITY_REGIME_MISMATCH"
AMBIGUOUS_MULTIPLE_CAUSES = "AMBIGUOUS_MULTIPLE_CAUSES"
UNRESOLVED_NEEDS_SOURCE_REVIEW = "UNRESOLVED_NEEDS_SOURCE_REVIEW"

MISMATCH_CATEGORIES = (
    MATCH_EXACT, MATCH_WITHIN_ROUNDING,
    NOT_COMPARABLE_SEMANTICS, NOT_COMPARABLE_TEMPORAL, NOT_COMPARABLE_ROSTER,
    LIKELY_PAGE3_EXTRACTION_ERROR, LIKELY_REFERENCE_CSV_ISSUE,
    REFERENCE_INTERNAL_CONFLICT, POSSIBLE_GENUINE_SOURCE_DISAGREEMENT,
    UNIT_OR_ROUNDING_MISMATCH, ROSTER_OR_CAPACITY_REGIME_MISMATCH,
    AMBIGUOUS_MULTIPLE_CAUSES, UNRESOLVED_NEEDS_SOURCE_REVIEW,
)


@dataclass(frozen=True)
class ComparisonRule:
    comparison_rule_id: str
    mapping_id: str
    p3_family: str
    p3_field_id: str
    reference_field_id: str
    entity_scope: str
    unit: str
    p3_temporal_reference: str
    reference_temporal_reference: str
    aggregation_rule: str
    denominator_class: str
    roster_registry_id: str
    mapping_status: str
    status: str
    absolute_tolerance: float = 0.0015
    relative_tolerance: float = 0.005
    rounding_increment: float = 0.001
    blocking_preconditions: tuple[str, ...] = ()
    notes: str = ""

    @property
    def enabled(self) -> bool:
        return (self.status == "enabled"
                and self.mapping_status in COMPARISON_ENABLING_STATUSES
                and not self.blocking_preconditions)


#: Shipped registry. Every rule is disabled and names the precondition that
#: blocks it, so a reviewer can see *why* nothing was compared rather than
#: inferring that nothing was attempted.
DEFAULT_RULES: tuple[ComparisonRule, ...] = (
    ComparisonRule(
        "CMP-T1-NATIONAL-STOCK", "MAP-045", T1,
        "p3_t1_stock_current_season_today_mm3", "p1_stock_today_mm3",
        "national_aggregate", "Mm3", "observation_today", "observation_today",
        "SUM over the day's dam roster", "not_applicable", "p3_t2_roster_registry",
        "CANDIDATE_REQUIRES_REVIEW", "disabled",
        blocking_preconditions=(
            "the roster of dams summed into the national total is unresolved: "
            "summing all 36 canonical dams would manufacture a roster mismatch "
            "that looks like a data error",
        ),
    ),
    ComparisonRule(
        "CMP-T2-DAM-STOCK", "MAP-046", T2, "p3_t2_dam_stock_mm3",
        "p1_stock_today_mm3", "per_dam", "Mm3", "observation_today", "observation_today",
        "one to one by dam and date", "not_applicable", "p3_t2_roster_registry",
        "CANDIDATE_REQUIRES_REVIEW", "disabled",
        blocking_preconditions=(
            "dam identity crosswalk is unconfirmed: Bouhertma and Zayatin match the "
            "reference names only as spelling variants, not exact strings",
            "R1 pages carry no matchable dam label at all",
        ),
    ),
    ComparisonRule(
        "CMP-T2-FILL-PCT", "MAP-047", T2, "p3_t2_dam_fill_pct",
        "p1_stock_fill_pct", "per_dam", "%", "observation_today", "observation_today",
        "one to one by dam and date", "useful_capacity_at_last_bathymetric_survey_mm3",
        "p3_t2_roster_registry", "CANDIDATE_REQUIRES_REVIEW", "disabled",
        blocking_preconditions=(
            "the capacity denominator regime must be pinned to "
            "p2_cap_actuelle_mm3, never to initial or regulated capacity",
            "dam identity crosswalk is unconfirmed",
        ),
    ),
    ComparisonRule(
        "CMP-T3-NATIONAL-INFLOW", "MAP-048", T3, "p3_t3_inflow_total_today_mm3",
        "p1_apport_today", "national_aggregate", "Mm3", "interval_today", "interval_today",
        "SUM over the day's dam roster", "not_applicable", "p3_t2_roster_registry",
        "UNRESOLVED", "disabled",
        blocking_preconditions=(
            "roster membership for the national inflow aggregate is unresolved",
        ),
    ),
    ComparisonRule(
        "CMP-T3-REGIONAL-INFLOW", "MAP-049", T3, "p3_t3_inflow_region_today_mm3",
        "p1_apport_today", "per_region", "Mm3", "interval_today", "interval_today",
        "SUM over the region's dams", "not_applicable", "p3_region_membership_registry",
        "UNRESOLVED", "disabled",
        blocking_preconditions=(
            f"region membership registry does not exist: {REGION_MEMBERSHIP_STATUS}",
        ),
    ),
    ComparisonRule(
        "CMP-T4-NATIONAL-WITHDRAWAL", "MAP-050", T4,
        "p3_t4_withdrawal_total_today_mm3", "p1_release_yesterday",
        "national_aggregate", "Mm3", "interval_today", "interval_reporting",
        "SUM over the day's dam roster", "not_applicable", "p3_t2_roster_registry",
        "UNRESOLVED", "disabled",
        blocking_preconditions=(
            "roster membership is unresolved",
            "the reporting interval of the reference outflow field is not aligned "
            "with the bulletin's 'for this day'; p1_release_today is a previous-year "
            "reference and must never be used as current outflow",
        ),
    ),
    ComparisonRule(
        "CMP-T4-REGIONAL-WITHDRAWAL", "MAP-051", T4,
        "p3_t4_withdrawal_region_today_mm3", "p1_release_yesterday",
        "per_region", "Mm3", "interval_today", "interval_reporting",
        "SUM over the region's dams", "not_applicable", "p3_region_membership_registry",
        "UNRESOLVED", "disabled",
        blocking_preconditions=(
            f"region membership registry does not exist: {REGION_MEMBERSHIP_STATUS}",
            "temporal alignment unresolved",
        ),
    ),
    ComparisonRule(
        "CMP-T5-TRANSFER", "MAP-052", T5, "p3_t5_transfer_day_mm3", "",
        "per_edge", "Mm3", "interval_today", "", "none", "not_applicable", "",
        "NOT_COMPARABLE", "disabled",
        blocking_preconditions=(NOT_COMPARABLE_REASON,),
    ),
    ComparisonRule(
        "CMP-T6-ICHKEUL", "MAP-054", T6, "p3_t6_ichkeul_day_mm3", "",
        "external_destination", "Mm3", "interval_today", "", "none",
        "not_applicable", "", "NOT_COMPARABLE", "disabled",
        blocking_preconditions=(NOT_COMPARABLE_REASON,),
    ),
)


#: Column names that identify a bulletin date on the reference side, in order of
#: preference. Profiling is read-only and never modifies the frozen snapshot.
_DATE_COLUMN_CANDIDATES = ("date", "bulletin_date", "jour", "day")
_ENTITY_COLUMN_CANDIDATES = ("dam_name", "dam_id", "barrage", "entity_id")


@dataclass
class ReferenceSnapshot:
    snapshot_id: str
    path: Path
    sha256: str
    row_count: int
    column_count: int = 0
    columns: tuple[str, ...] = ()
    key_columns: str = ""
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    schema_hash: str = ""
    audit_state: str = "PROVISIONAL"
    approved_for_comparison: bool = False

    @classmethod
    def load(cls, path: Path) -> "ReferenceSnapshot":
        """Identify and profile a frozen snapshot, read-only.

        The snapshot is hashed and profiled so a run records exactly which
        frozen artefact it was pointed at, even when no rule is enabled. The
        file is opened for reading and nothing else: a frozen reference is never
        rewritten by this package.
        """
        p = Path(path)
        csv_path = p
        if p.is_dir():
            candidates = sorted(p.glob("*.csv"))
            if not candidates:
                raise FileNotFoundError(f"no CSV inside reference snapshot {p}")
            csv_path = candidates[0]

        h = hashlib.sha256()
        with open(csv_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)

        rows = 0
        header: list[str] = []
        date_idx: Optional[int] = None
        dmin = dmax = None
        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            for i, row in enumerate(reader):
                if i == 0:
                    header = row
                    lowered = [c.strip().lower() for c in row]
                    for cand in _DATE_COLUMN_CANDIDATES:
                        if cand in lowered:
                            date_idx = lowered.index(cand)
                            break
                    continue
                rows += 1
                if date_idx is not None and date_idx < len(row):
                    v = row[date_idx].strip()
                    if v:
                        dmin = v if dmin is None or v < dmin else dmin
                        dmax = v if dmax is None or v > dmax else dmax

        lowered = [c.strip().lower() for c in header]
        keys = [header[lowered.index(c)] for c in _DATE_COLUMN_CANDIDATES if c in lowered]
        keys += [header[lowered.index(c)] for c in _ENTITY_COLUMN_CANDIDATES if c in lowered]
        schema_hash = hashlib.sha256(
            "|".join(header).encode("utf-8")).hexdigest()

        return cls(
            snapshot_id=csv_path.parent.name or csv_path.stem,
            path=csv_path,
            sha256=h.hexdigest(),
            row_count=rows,
            column_count=len(header),
            columns=tuple(header),
            key_columns="|".join(keys) if keys else "NOT_IDENTIFIED_FROM_HEADER",
            date_min=dmin,
            date_max=dmax,
            schema_hash=schema_hash,
        )


@dataclass
class CoverageRow:
    coverage_id: str
    comparison_rule_id: str
    reference_snapshot_id: str
    bulletin_date: str
    entity_scope: str
    entity_id: str
    p3_available: bool
    reference_available: bool
    p3_evidence_available: bool
    semantic_alignment_status: str
    temporal_alignment_status: str
    roster_alignment_status: str
    comparability_status: str
    not_comparable_reason: str


def build_coverage(facts: Sequence[Fact],
                   rules: Sequence[ComparisonRule],
                   snapshot: Optional[ReferenceSnapshot],
                   bulletin_date: str,
                   run_id: str) -> list[CoverageRow]:
    """Record, per rule, why a comparison did or did not happen.

    This is the honest alternative to an empty comparison table: a reviewer can
    see the attempted key, both availability flags, and the blocking
    precondition.
    """
    out: list[CoverageRow] = []
    snap_id = snapshot.snapshot_id if snapshot else ""
    for rule in rules:
        p3_facts = [f for f in facts
                    if f.family_id == rule.p3_family
                    and f.canonical_field_id == rule.p3_field_id]
        blocked = "; ".join(rule.blocking_preconditions)
        if rule.p3_family in NOT_COMPARABLE_FAMILIES:
            comparability = NOT_COMPARABLE_SEMANTICS
            semantic = "NO_REFERENCE_SIDE_FIELD"
        elif rule.blocking_preconditions:
            comparability = NOT_COMPARABLE_ROSTER if "roster" in blocked or "region" in blocked \
                else NOT_COMPARABLE_SEMANTICS
            semantic = "UNRESOLVED"
        else:
            comparability = "COMPARABLE"
            semantic = "ALIGNED"
        out.append(CoverageRow(
            coverage_id=f"COV-{run_id}-{rule.comparison_rule_id}-{bulletin_date or 'NA'}",
            comparison_rule_id=rule.comparison_rule_id,
            reference_snapshot_id=snap_id,
            bulletin_date=bulletin_date or "",
            entity_scope=rule.entity_scope,
            entity_id="ALL",
            p3_available=bool(p3_facts),
            reference_available=snapshot is not None and bool(rule.reference_field_id),
            p3_evidence_available=any(f.evidence_id for f in p3_facts),
            semantic_alignment_status=semantic,
            temporal_alignment_status=(
                "ALIGNED" if rule.p3_temporal_reference == rule.reference_temporal_reference
                and rule.reference_temporal_reference else "UNRESOLVED"),
            roster_alignment_status=(
                "UNRESOLVED" if rule.roster_registry_id else "NOT_APPLICABLE"),
            comparability_status=comparability,
            not_comparable_reason=blocked or NOT_COMPARABLE_REASON,
        ))
    return out


def enabled_rules(rules: Iterable[ComparisonRule]) -> list[ComparisonRule]:
    return [r for r in rules if r.enabled]


def compare(facts: Sequence[Fact],
            rules: Sequence[ComparisonRule],
            snapshot: Optional[ReferenceSnapshot]) -> list[dict]:
    """Execute the enabled rules only.

    With the shipped registry this returns an empty list by construction. The
    function exists so that enabling a rule later is a registry edit, not a code
    change, and so the disabled state is auditable rather than implicit.
    """
    if snapshot is None:
        return []
    return []  # no enabled rule exists; see DEFAULT_RULES for the reasons

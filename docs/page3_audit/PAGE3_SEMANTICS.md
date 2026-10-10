# Page 3 semantic guide

Documented 2026-09-09 for the selected Phase6c canonical facts. This describes the
actual stored release and distinguishes it from intended contract semantics.
It is not a new extraction, corrected master or feature-admission decision.

## One row and the two dictionaries

One canonical fact is one measure for one entity on one bulletin, with source,
identity, value-state and quality evidence. There are **274,183 rows and 39
columns**, covering **22 canonical field IDs, 23 analysis measure IDs and 29
field/measure/grain combinations**. A measure ID alone does not determine grain.

- [Field dictionary](PAGE3_FIELD_DICTIONARY.csv): every actual column, Arrow type,
  meaning, observed missingness/vocabulary and interpretation cautions.
- [Measure dictionary](PAGE3_MEASURE_DICTIONARY.csv): every actual combination,
  units, temporal interpretation, coverage and qualifications.
- [Coverage verification](DICTIONARY_VERIFICATION.json): source hashes, observed
  status codes and reconciled row counts. Coverage is not proof of physical truth.

## Seven observation grains

| Grain | Meaning | Main restriction |
| --- | --- | --- |
| NATIONAL_DAY | National summary/comparator | Not an individual dam value |
| REGION_DAY | Printed North, Centre or Cap Bon summary | No inferred P3 dam membership |
| DAM_DAY | Confirmed selected-dam value | Only confirmed non-provisional IDs join P1/2 |
| ROW_SLOT_DAY | T2 row with unresolved or provisional identity | Never identify by row position |
| TRANSFER_EDGE_DAY | Physical pumped route | Do not add accounting observations |
| TRANSFER_ACCOUNTING_DAY | Sejnane inflow including transfers | Already includes transfers; not another route |
| EXTERNAL_DELIVERY_DAY | Lake Ichkeul delivery | Leaves the dam system |

Families are T1 national stock, T2 selected-dam status, T3 inflow, T4 uses and
withdrawals, T5 transfers/accounting, and T6 Ichkeul. Stock, fill, headroom, daily
flows, cumulative counters and historical comparators are distinct quantities.

## Units and temporal support

The stored token **mm3 means Mm3, million cubic metres**, in this hydrological
release. It must not be interpreted as cubic millimetres. `pct` contains reported
percentages such as 31, not 0.31; a subtraction is in percentage points.

The documented contract assigns current states to the bulletin day, daily flows
to the preceding calendar day, and multi-year comparisons to non-observation
support. Cumulative measures summarize a season through a reporting endpoint;
they are not one-day flows. Previous-season totals are historical comparators.

**Actual metadata conflict:** every fact currently has SAME_DAY and an effective
date equal to its bulletin date. Therefore the stored date fields do not implement
all those intended distinctions. Use bulletin date for same-publication equality,
and require an explicit validated adapter before temporal feature integration.
Do not infer a precise cumulative/reference endpoint merely by shifting all rows.

## Value states and quality

`PRESENT_ZERO` is an observed zero. `SOURCE_BLANK` is a blank source value.
`PRESENT_TEXT` retains a nonnumeric source state. `WITHHELD_UNRESOLVED` means no
accepted numeric value. `STRUCTURAL_NOT_EXPECTED` denotes a measure not expected
under that source structure. These cannot be merged into zero or a single
undifferentiated missing-value category.

`source_consistency_status` describes imported within-source checks, not the new
P3-versus-P1/P2 equality result. `SOURCE_CONSISTENT`, `quality_flag=OK`, or
`usability_status=OK` do not establish physical truth, forecast availability or
training suitability. A PARTIAL record can contain a valid numeric value while
some required interpretation remains unresolved.

Identity flags are stored as strings. Read TRUE/FALSE explicitly. Non-dam facts
can correctly have IDENTITY_NOT_APPLICABLE and unconfirmed P1/2 dam identity.
Numerical recovery does not recover an unknown dam name.

Both `schema_era` and `gap_episode_id` are entirely blank in this fact release.
That is missing annotation, not evidence of no schema changes or no gaps. The
fact table is not the entire continuity calendar; consult the separate continuity
products and series IDs before analyzing missing dates.

## Comparability and remaining uncertainty

Current stock maps to P1 stock and P2 current corresponding total storage. P1
current release is `p1_release_yesterday`, not the previous-year field. Printed
regional totals can be compared without inventing regional dam membership. P2
sums require every contributor in the explicitly documented P1 roster.

The fill denominator, headroom/capacity regime, historical reference window and
some printed difference signs need their own evidence. Do not infer them solely
from numerical agreement. In particular, retain the source sign of T3 comparator
differences instead of imposing current-minus-reference on every row.

The withdrawal source checks confirm sampled printed discrepancies. The transfer
recipe explains many post-2024-01-09 differences, but is exploratory and incomplete.
It must not become an automatic source correction or a fabricated split of a
mixed-purpose withdrawal. The same-day `__LEAK` columns in the convenience join
surface are diagnostic restatements, not automatically allowed predictors.

This guide and its field dictionary cover the long canonical facts. The separate
34-column join surface still needs its own exhaustive column dictionary before
being treated as a modeling interface.

## Evidence and use

The dictionaries name their source contracts and code using project-relative
paths. Their observed frequencies come from the current Parquet input. Read
[the methodology](AUDIT_METHOD_AND_DECISIONS.md) for implementation rationale
and [the thesis draft](THESIS_AUDIT_SECTION_DRAFT.md) for report prose.

Meaning and schema coverage are now documented; complete dataset cleanliness,
time alignment and model admission are separate scientific claims still requiring
their own validation.

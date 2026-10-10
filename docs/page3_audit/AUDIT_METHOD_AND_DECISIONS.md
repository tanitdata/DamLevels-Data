# Page 3 audit: methodology and implementation decisions

Prepared 2026-09-09. This document explains the implemented method, its design
choices, the supporting evidence and the limits of the results. It is intended
for the thesis methodology and data-preparation chapters.

## Objective and meaning of audited data

The objective was to determine whether corresponding Page 3 and Page 1/2 values
describe compatible quantities and, where they do, whether they are numerically
equal. Important discrepancies were then investigated in the source bulletins.

An audited dataset is traceable and explicit about uncertainty. A value can be
extracted correctly while its published definition differs from another page.
The audit therefore preserves source values and records comparison outcomes. It
does not create a reconciled master by averaging or replacing disagreeing values.

## 1. Identify the exact input versions

The audit selects the Aug31 Page 1/2 exports and Phase6c Page 3 canonical facts
through `configs/inputs.json`. Earlier P3 comparisons used an older 44-column
`dams.csv`; the selected merged P1/2 export has 66 columns. Their names and
completeness cannot be assumed interchangeable.

The selected inputs contain 129,391 P1 observations, 129,472 P2 observations and
274,183 P3 facts. Input hashes are recorded before analysis and checked again
before saving results. Each finding therefore refers to an identified release.

Evidence: both current run manifests, the imported P1/2 receipt and P3 contracts.
Code: `interpage.run`, `sha256`.

## 2. Define meaning before matching column names

Every pair needs compatible physical meaning, unit, entity, geographical scope
and temporal reference. Similar names alone are insufficient.

| Quantity | Accepted counterpart | Reason |
| --- | --- | --- |
| P3 selected-dam stock | P1 `p1_stock_today_mm3`; P2 `storage_current_total_corresponding_p2_mm3` | Current total storage; other similarly named P2 columns can refer to prior-year-end or exploitable storage |
| P3 fill percentage | P1 `p1_stock_fill_pct` | Compare printed percentages while retaining precision differences and unverified capacity-denominator equivalence |
| P3 current withdrawal | P1 `p1_release_yesterday` | The header identifies the current reporting interval; `p1_release_today` is a previous-year reference |
| P3 national/regional daily values | P1 printed TOTAL/subtotals | Compare reported aggregate scopes without inventing a P3 dam roster |
| P3 transfers | Physical transfer records | The Sejnane accounting observation already includes transfers and is not another physical movement |

P3's stored `mm3` token means **million cubic metres**, displayed as Mm3 here,
not cubic millimetres. Stored `pct` values are reported percentages; their
differences are percentage points. The [semantic guide](PAGE3_SEMANTICS.md) and
CSV dictionaries cover the actual schema and measure/grain combinations, with
unresolved definitions explicitly marked.

## 3. Preserve grain and identity

P3 contains national, regional, confirmed selected-dam, anonymous row-slot,
physical-route, accounting and external-delivery records. It is not one complete
dam-day panel. Repeating a national total on each dam row would not make it an
individual dam measurement.

Dam comparisons require `grain=DAM_DAY`, a confirmed P1/2 identifier and a
non-provisional identity. Anonymous rows and provisional El Hma are excluded.
Row position is not an identity, and an unselected dam is not a measured zero.

Unique input, natural-fact, lineage and comparison keys are checked. Duplicates
stop execution instead of multiplying rows or silently overwriting records.
Each comparison rule must have candidates and the expected grain and unit.

Code: `unique_index`, `RULES`, and identity/grain/unit guards. Outputs:
`pair_registry.csv`, `excluded_p3_fields.csv`.

## 4. Match dates for the question being asked

The audit compares **pages from the same bulletin**, joining on `bulletin_date`
on both sides, with a confirmed dam key where appropriate. It does not shift one
source independently to improve agreement, use nearest dates, or bridge gaps.

Printed equality and hydrological time alignment are different questions. The
P3 contracts distinguish current stock, preceding-day flows and historical
comparators, but all 274,183 imported facts currently store SAME_DAY metadata.
This contradiction is documented rather than silently repaired. A later adapter
must establish the applicable time policy while preserving original metadata.

## 5. Distinguish printed totals from calculated sums

The current P1 export includes a separate reader for printed TOTAL and regional
subtotal rows. `checksum_source.csv.gz` retains their numbers, raw tokens,
physical contributor indexes and source hashes. Dates come through the source
manifest rather than ad hoc parsing of inconsistent filenames.

Printed aggregates are compared directly with P3. Their internal residuals
against P1 dam-row sums remain contextual evidence; they do not authorize
altering the printed total.

P2 sums are a separate diagnostic. Their roster comes from the physical P1
subtotal/TOTAL rows for each bulletin. Every expected identity and P2 value must
exist, otherwise the sum is not evaluated. This establishes completeness against
that P1 roster, not proof of an identical P3 roster or accounting definition.

Code: `sum_reference` and the printed-scope/P2-sum branches. Evidence:
`p2_aggregate_lineage.csv.gz`, including contributor and missing-dam lists.

## 6. Separate equality, precision and missingness

The equality run stores `delta = P3 - reference` using decimal arithmetic.
Representations such as 1.230 and 1.23 are equal. A nonzero difference is not
called exact merely because it is small relative to the observation.

Printed resolution is accepted only when its raw token reproduces the stored
number. For displayed steps `qa` and `qb`, the potential rounding bound is
`(qa + qb) / 2`. For a sum, contributor steps are added before taking their
half-bound. This tests a stated rounding model, not the publisher's unknown
internal calculation process.

| Status | Meaning |
| --- | --- |
| `EXACT` | Zero decimal difference |
| `DIFFERENT_ROUNDING_COMPATIBLE` | Nonzero difference within the displayed-step bound |
| `DIFFERENT_BEYOND_ROUNDING` | Difference beyond that bound; not automatically an error |
| `DIFFERENT_PRECISION_UNKNOWN` | Both values exist, but at least one source resolution is not established |
| `NOT_EVALUATED` | Required value, scope or complete sum is unavailable |

Blank, non-finite and withheld values never become zero. Unevaluated rows retain
reasons. Exact percentages use evaluated comparisons as their denominators,
while unavailable cases are separately counted. The actual run had no evaluated
differences of unknown precision, but that status is implemented for future data.

Code: `decimal_value`, `precision`, `equality`, `summarize`. Tests cover numeric
equality, zero versus missing, precision boundaries and denominator handling.

## 7. Inspect patterns before assigning a cause

The run produced 117,108 comparison rows across 15 pairs, with summaries by year,
entity and the previously documented 2024-01-09 withdrawal boundary. An overall
match rate would conceal important temporal differences.

Selected-dam stock agrees exactly on 12,598 of 12,616 cases against each page.
The 18 differences involve nine dams on 2-3 July 2022. National storage and
regional inflow also show high exact agreement. National daily totals contain
many small printed differences. A separate 0.01 Mm3 diagnostic describes small
deviations without redefining them as exact equality or proven rounding.

From 2024-01-09, national P3 withdrawal averages 0.85373 Mm3 below the printed P1
TOTAL. Regional checks locate the change in the North. That finding is a
discrepancy to investigate, not yet a parser-error classification.

Evidence: the first run's row-level output, summaries, storage exception table,
withdrawal figure and separately labeled small-difference diagnostic.

## 8. Check the original publication

Six withdrawal bulletin pairs were selected deliberately: the day before the
change, the first changed day, two typical differences in different seasons, a
later agreement control and the largest difference. Original PDFs were rendered
and inspected with their dates, units, regional labels and footnotes.

All 36 recorded aggregate transcriptions matched extraction. For example, the
19 May 2025 publication prints 2.129 Mm3 on P3 and 9.460 Mm3 on P1. The sampled
aggregate disagreements are therefore already present in the publication. This
does not prove every corpus cell is correctly extracted or either total is
physically correct.

The earlier storage review separately checked six dam-day examples on 2-3 July
2022. These two samples must not be described as a complete manual corpus audit.

Evidence: `visual_source_checks.csv`, the reviewed PDF hashes and the source
investigation report. `review_withdrawal_sources.py` checks saved transcriptions;
its assertions do not substitute for the documented visual inspection.

## 9. Test a semantic hypothesis without imposing a correction

P3 explicitly reports some physical transfers, and P1 identifies transfer actions
with `tr`. Several North residuals equal combinations of those recorded
quantities. This supports a possible change in treatment of internal transfers.

The exploratory recipe adds two P3 transfer routes and withdrawals at Moula,
Gamgoum, Kebir and Zarga only when the action code is exactly `tr`. It does not
reclassify all mixed-purpose withdrawals as transfers. All required source
records and numeric values exist on the 1,010 diagnostic dates; none is imputed.

Across 638 post-change dates, the candidate reproduces 328 residuals exactly and
489 within 0.001 Mm3. Across 372 pre-change controls, the original P1/P3 North
values agree on every date, while the candidate reconciles only one. The ungated
candidate is a separate auxiliary diagnostic and must not be confused with the
action-gated recipe.

The remaining 149 post-change differences above 0.001 Mm3 and mixed-purpose
withdrawals show that the candidate is incomplete. Operational components or
the publisher's calculation details are needed before adopting a full rule.
This exploratory result is not an approved source correction.

## 10. Preserve evidence and define the next release

Frozen engines and source products remain unchanged. Scientific comparison code
lives under `src/pfe_dams/quality`; private report, review and packaging helpers
remain under ignored `local_build`. Each run retains its outputs, manifests and
limitations. The implementation passed 22 targeted tests, and an independent
calculation reproduced the storage scorecards. Output hashes and source links
were also verified.

The package is a snapshot of an executed audit, not a new corrected-data release.
Before P3 enters features, the project still needs a date adapter, variable-level
admission rules, treatment of unresolved identities and mixed-purpose withdrawals,
and checks of availability at forecast issue time. This audit supplies evidence
for those decisions without prematurely claiming they are complete.

## Implementation map

| Component | Role | Evidence |
| --- | --- | --- |
| `src/pfe_dams/quality/interpage.py` | Validate compatible pairs, joins, decimals and missingness | `interpage_20260908_v1` |
| `tests/unit/test_interpage.py` | Test numeric, identity and completeness boundaries | 22 tests; not proof of physical truth |
| `local_build/render_interpage_audit.py` | Generate report, discrepancy view and chart | Report receipt and figure |
| `local_build/review_withdrawal_sources.py` | Check transcriptions and reproduce the transfer diagnostic | `withdrawal_source_review_20260908_v1` |
| `packages/page3` | Preserved extractor and semantic contracts | Historical 1.2.0rc2 engine, not rerun here |
| `docs/page3_audit` | Methods, semantic dictionaries and thesis prose | Documentation of the selected release |

Paths are project-relative. The archive retains that layout and an inventory of
copied files, source locations and SHA-256 hashes.

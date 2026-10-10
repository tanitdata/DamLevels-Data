# Draft thesis section: Semantic validation and interpage auditing

Suggested placement: methodological framework and the Page 3 data-preparation
section. This new source prose is ready for review and integration; it has not
been inserted into the synchronized main Markdown/LaTeX thesis.

## Semantic harmonization

Preparing the reservoir dataset required validation of each measurement's
meaning before numerical reconciliation. Although the bulletin pages describe
the same system, they contain different observation grains, reporting periods
and accounting quantities. Page 3 combines national and regional summaries,
selected-dam storage, physical transfers, accounting observations and an external
lake delivery. Its records therefore cannot be merged indiscriminately into a
complete dam-day panel.

A release-specific mapping was established between the selected Page 3 canonical
facts and the 31 August 2026 Page 1/2 extraction. Printed labels and existing
contracts identified compatible quantities, units, temporal references and
entities. For example, current Page 1 outflow is stored in
`p1_release_yesterday`, while `p1_release_today` is a previous-year reference.
The accepted Page 2 counterpart for current total storage is
`storage_current_total_corresponding_p2_mm3`. These examples demonstrate why
column names alone are insufficient for scientific integration. [E1, E2]

Dam-level comparisons required confirmed identities and excluded anonymous row
slots and provisional matches. National and regional P3 values were compared
with independently extracted printed P1 totals and subtotals. A separate
diagnostic used P2 sums over each bulletin's physically documented P1 contributor
roster. Such sums required every expected identity and numeric value. Missing
observations remained unavailable rather than becoming zero. [E1]

## Comparison and traceability

Corresponding pages were aligned by bulletin date. This evaluates agreement
between publications and does not independently resolve hydrological effective
dates. Decimal arithmetic distinguished exact equality from a small nonzero
difference. Potential rounding compatibility used the precision retained in raw
source tokens. Its bound represents a stated numerical model, not proof of the
publisher's internal calculation method. [E1]

The audit produced 117,108 comparison rows across 15 registered pairs. Each row
retained both source values, the signed difference, comparison status, source
identifiers and any reason for exclusion. Summary denominators contained only
evaluated pairs, with unavailable cases reported separately. Unique-key, grain,
unit, lineage and completeness checks accompanied the analysis. Input hashes
verified source preservation, and 22 targeted tests covered decimal equality,
precision, duplicate keys, missing values and complete sums. [E1, E3]

## Findings and source investigation

Confirmed selected-dam storage agreed exactly between P3 and each of P1 and P2
on 12,598 of 12,616 comparisons, or 99.86%. The 18 discrepancies involved nine
dams on 2 and 3 July 2022. Inspection of six dam-day examples confirmed that
different values were already printed in the original documents. Correct
extraction therefore does not necessarily produce interpage agreement. [E1]

A persistent withdrawal difference appeared from 9 January 2024. Across 638
post-change comparisons, P3's national total averaged 0.85373 Mm3 below the P1
printed total. Regional checks located the change in the North. Six bulletin
pairs were selected for visual review, including pre-change and agreement
controls, typical differences and the largest discrepancy. All 36 recorded
aggregate transcriptions matched extraction. The sampled discrepancies thus
originated in the publication rather than misreading those aggregate cells. [E4]

An exploratory explanation considered internal transfers. A candidate combining
two explicitly reported P3 transfer routes with selected P1 withdrawals marked
exclusively as transfers explained the North residual exactly on 328 of the 638
post-change dates and within 0.001 Mm3 on 489 dates. Mixed-purpose withdrawals
and remaining residuals prevented confirmation of a complete accounting formula.
The hypothesis was retained as evidence and did not overwrite either source. [E4]

## Conditions for model integration

The audit identified a discrepancy between the P3 time contract and delivered
metadata. All 274,183 canonical facts currently carry SAME_DAY metadata,
including quantities whose documented interpretation has another temporal
support. An explicit adapter must resolve this before temporal integration and
feature engineering. Unresolved identities, accounting definitions and forecast
availability also require variable-level admission rules. [E2]

The result is a traceable auditing stage rather than a claim that all data has
been corrected or is ready for modeling. Original values, discrepancies and
uncertainty are preserved with evidence for subsequent decisions. This supports
clean data preparation by making transformations reviewable and preventing
unsupported harmonization.

## Evidence for bibliography integration

These are unpublished project artifacts. Replace temporary labels with thesis
citation keys when integrating the section. They are not external publications.

| Label | Project-relative evidence |
| --- | --- |
| E1 | `artifacts/runs/interpage_20260908_v1/report.md`, `comparison_summary.csv`, `pair_registry.csv`, `run_manifest.json` |
| E2 | `docs/DATA_CONTRACT.md`, `docs/page3_audit/PAGE3_SEMANTICS.md`, `data/reference/page3_canonical/PAGE3_TO_FINAL_P12_JOIN_CONTRACT.md` |
| E3 | `tests/unit/test_interpage.py` and the audit implementation |
| E4 | `artifacts/runs/withdrawal_source_review_20260908_v1/report.md`, `visual_source_checks.csv`, `transfer_hypothesis_summary.csv`, `manifest.json` |

Review this draft against the saved evidence and the report's terminology. It
must not be presented as a manual audit of every PDF or a confirmed reconstruction
of the publisher's calculation formula.

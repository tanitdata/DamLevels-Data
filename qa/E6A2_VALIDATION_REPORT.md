# E6A.2 validation report

## Decision

**VALIDATED WITH EXPLICIT LIMITATIONS.** E6A.2 adds three separate independent-PDF numeric audits and one categorical Page 3 semantic audit. It does not report a pooled Page 1+Page 2+Page 3 accuracy.

## Accepted baseline

- Repository baseline: `977ed9ca1e59640daaa4ceb6263d703a57e0436b` (accepted E6A.1).
- Frozen authority: `<FROZEN_BASELINES>/V010_20260924_1620`.
- Fixed sampling seed: `20260926`.
- Target: `99.5%`; interval: two-sided 95% Wilson score.
- Computed minimum zero-error independent sample: 765 PDFs; 764 does not meet the lower-bound target.

## Primary numeric audit results

| Family | Sampled PDFs | Eligible | Matches | Errors | Unverifiable | Wilson 95% CI | Decision |
|---|---:|---:|---:|---:|---:|---|---|
| A1 Page 1 extraction | 800 | 800 | 800 | 0 | 0 | 99.522112%–100.000000% | YES |
| A2 Page 2 extraction | 800 | 800 | 800 | 0 | 0 | 99.522112%–100.000000% | YES |
| A3 Page 3 transcription | 800 | 792 | 792 | 0 | 8 | 99.517309%–100.000000% | YES |

The PDF/bulletin is the primary sampling unit. Each family uses at most one primary target cell per selected PDF. Layout/text-regime samples are allocated proportionally. Inclusion probabilities, sampling weights, within-PDF candidate counts, and cell-selection probabilities are preserved in the audit CSVs.

These are computer-assisted source rereads using preserved production lineage to locate source cells. They do not call the production extractor or its parsing functions. No E6A.2 row is claimed as `HUMAN_VISUAL_VERIFIED`.

## Page 3 semantic audit

The separate A3B categorical sample contains 160 rows:

- `PRINTED_LABEL_MATCH_STABLE_ID_UNRESOLVED`: 76
- `ACCOUNTING_NOT_HYDRAULIC_EDGE`: 39
- `DATE_SEMANTICS_UNRESOLVED`: 45

The semantic audit is not combined with A3 transcription accuracy. Page 3 authority remains `PROBABLE`.

## Challenge and correction records

- Noninferential challenge-set rows: 28
- Challenge rows included in primary denominators: 0
- Correction candidates: 0

## Preservation checks

- The original E6A `qa/audit_sample.csv` remains byte-identical at SHA-256 `c07c18df8479039f5390b7e4193728733fa7927d894154c8c972adcbcac375f1`.
- All artifacts marked `MUST_REMAIN_BYTE_IDENTICAL` in `qa/e6a2/E6A2_PROTECTED_BASELINE_HASHES.csv` matched their baseline hashes after generation.
- The frozen V010 ZIP remained byte-identical at SHA-256 `303673e8b342572dff807797355e15cdea9a39325e6083931b31d5f6c783c9d0`.
- B and H underlying outputs, C-G outputs, accepted scientific tables, and E5 GIS artifacts remained byte-identical.
- The shared `qa/qa_summary.json` and `qa/report.md` changed only to present A1/A2/A3/A3B and clarify the B denominator.
- The 144 opportunities from four partial bulletins without Page 1 are labeled `OUTSIDE_DENOMINATOR_PARTIAL_BULLETIN_OPPORTUNITIES`; they are not added to the 143,316 Page 1 denominator.

## Execution boundaries

- Production extractors run: **NO**
- Accepted scientific values changed: **NO**
- Watershed/GIS science rerun: **NO**
- Model or satellite pipeline run: **NO**
- Public remote configured: **NO**

## Limitations

- Source localization inherits production lineage bounding boxes, so this is not a fully independent manual/human extraction audit.
- Eight sampled Page 3 cells were unverifiable and were excluded rather than passed.
- Page 3 semantic authority, stable-ID crosswalks, and effective-date interpretation retain their prior qualifications.
- E6B satellite validation has not started.

## Final status

E6A.2 is reproducible and reviewable within its stated design. The three numeric decisions are separate. No overall multipage accuracy claim is made.

Validation completed with **42 tests passed**. All repository Python files parsed, all three primary sample files satisfied the one-PDF/one-cell constraint, and the generated CSV/JSON contracts reconciled with the counts above.

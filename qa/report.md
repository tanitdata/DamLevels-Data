# Automatic QA report — professor checks A1/A2/A3/A3B and B through H

This report is generated from the same result objects as `qa_summary.json`. It does not invoke production extraction or change accepted values. Satellite KPI I remains excluded.

| KPI | Eligible | Pass | Fail | Excluded/Unknown | Status |
|---|---:|---:|---:|---:|---|
| A1. Page 1 extraction | 800 | 800 | 0 | 0 | YES |
| A2. Page 2 extraction | 800 | 800 | 0 | 0 | YES |
| A3. Page 3 numeric transcription | 792 | 792 | 0 | 8 | YES |
| A3B. Page 3 semantic mapping | 160 | 0 | 0 | 160 | CATEGORICAL_REVIEW_WITH_EXPLICIT_GAPS |
| B. completeness | 143,316 | 129,390 | 13,926 | 0 | YES_WITH_EXPLICIT_GAPS |
| C. uniqueness | 129,390 | 129,390 | 0 | 0 | PASS |
| D. physical validity | 129,241 | 127,753 | 1,488 | 149 | REVIEW_REQUIRED |
| E. fill consistency | 84,471 | 80,814 | 3,657 | 44,919 | REVIEW_REQUIRED |
| F. national total reconciliation | 3,967 | 3,965 | 2 | 18 | REVIEW_REQUIRED |
| G. transfer balance | 0 | 0 | 0 | 15,852 | NOT_NUMERICALLY_ELIGIBLE_WITH_EXPLICIT_EXCLUSIONS |
| H. temporal plausibility | 119,548 | 114,235 | 5,313 | 9,842 | YES_WITH_EXPLICIT_GAPS |

## Multipage extraction/transcription QA

A1, A2 and A3 are separate independent-PDF audits. No pooled Page 1+Page 2+Page 3 accuracy is reported. A3B is categorical. Page 3 remains `PROBABLE`.

See `qa/extraction/multipage_accuracy_report.md` and `qa/extraction/sampling_design.md` for methods, per-regime allocations, field-family breakdowns and limitations.

The source-cell reread is computer assisted and uses inherited lineage localization. It is not described as a human manual audit.

## B. Completeness

Page 1 completeness remains 90.283011% over 143,316 Page 1 dam/date opportunities. The 144 dam opportunities associated with four partial bulletins without Page 1 are `OUTSIDE_DENOMINATOR_PARTIAL_BULLETIN_OPPORTUNITIES`; they do not belong to the 143,316 denominator.

## C–G and H preservation

Accepted C–G scientific counts and H temporal results are unchanged. Page 3 transfer exclusions remain exclusions, not failures. See the unchanged component CSVs and the structured `qa_summary.json` entries.

## Known limitations affecting interpretation

- source localization uses preserved production bounding boxes;
- E6A.2 performed computer-assisted source rereads, not a fully independent human audit;
- Page 3 authority remains PROBABLE;
- candidate Page 3 dam crosswalks and effective-date semantics remain unresolved;
- challenge-set results are noninferential;
- capacity gaps, partial bulletin inventories and existing scientific limitations remain visible.

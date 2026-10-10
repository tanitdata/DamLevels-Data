# E6A.1 validation report

Date: 2026-09-25  
Accepted E6A baseline: Git commit `65694b918a6ba69f209d9d95e6011d517f5a6305`
Frozen scientific authority: `<FROZEN_BASELINES>/V010_20260924_1620`

## Baseline protection

- Git started at the accepted E6A commit `65694b918a6ba69f209d9d95e6011d517f5a6305`, and no remote is configured.
- The frozen V010 ZIP still has SHA-256 `303673e8b342572dff807797355e15cdea9a39325e6083931b31d5f6c783c9d0`.
- `qa/e6a/E6A_PROTECTED_BASELINE_HASHES.csv` records 32 accepted scientific/public data and E5 GIS artifacts. Every before/after hash is identical.
- The production extractor, watershed/GIS science, climate, integration, feature, model, and satellite pipelines were not run.
- Accepted storage, capacity, fill, Page 3, source-manifest, and GIS values were not modified.

## A. Extraction accuracy

The audit uses fixed seed `20260925`. It contains 1,500 unique storage observations across all 36 governed dams, 160 bulletin dates/files, and five strata spanning 2014-07-15 through 2025-09-24. The four evidence-backed 2015-10-03 through 2015-10-06 roster/scope dates are a 96-row census; the other four strata each contain 351 seeded observations selected as 39 dates by 9 dam rows.

Each comparison reads printed glyphs directly from the original PDF cell region with `pdfplumber`, verifies the source PDF SHA-256, and compares the parsed source decimal with the accepted repository decimal. It does not invoke the production extractor and does not reuse an earlier audit disposition. Preserved cell bounding boxes identify the source cell. Fifteen representative cell crops across all five strata were also visually inspected; their printed values agree with the audit rows. This is an independent source-cell consistency audit rather than a fully independent human/manual extraction audit.

- Sampled cells: **1,500**
- Verifiable denominator: **1,500**
- Matches: **1,500**
- Errors: **0**
- Unverifiable: **0**
- Accuracy: **100.000000%**
- Error rate: **0.000000%**
- Descriptive pooled Wilson 95% interval: **99.744557% to 100.000000%**
- Interval type: **DESCRIPTIVE_SIMPLE_BINOMIAL_INTERVAL**
- Correction candidates: **0**

The Wilson interval is computed as `(p̂ + z²/(2n) ± z*sqrt((p̂(1-p̂)+z²/(4n))/n)) / (1+z²/n)` with two-sided 95% `z=1.959963984540054`. It is retained as a descriptive pooled interval conditional on independent equally sampled Bernoulli trials.

**A. DOES THE CURRENT AUDIT DEMONSTRATE THE PROFESSOR'S POPULATION-WIDE >=99.5% EXTRACTION-ACCURACY TARGET? INCONCLUSIVE.**

All 1,500 selected cells matched. The four ordinary strata receive equal sample counts despite unequal populations, 96 observations form a separate census of four known roster/scope dates, and nine cells are clustered within each selected bulletin/PDF. The pooled simple-binomial interval therefore does not provide a design-valid population-wide confidence bound. A design-valid independent audit is still required for that claim.

## B. Completeness

The primary denominator is 3,981 canonical bulletin dates with an accepted Page 1 source multiplied by 36 governed dams: **143,316 dam-date opportunities**. The repository contains **129,390 observations**, leaving **13,926 explicit missing opportunities** and overall bulletin-date completeness of **90.283011%**.

- `VALUE_BLANK_IN_SOURCE`: **1**
- `DAM_NOT_REPORTED` from accepted Page 1 row-census evidence: **13,925**
- `EXTRACTION_MISSING` established by direct evidence: **0**
- Partial bulletins without Page 1: **4 dates / 144 dam opportunities outside the primary denominator**
- Calendar days without a canonical bulletin in the corpus span: **134**
- Complete 36-dam bulletin dates: **1,631**
- Bulletin dates with a smaller reported roster: **2,350**

The longest missing bulletin-opportunity run is for `sarrat`: **2,350 Page 1 bulletin dates**, from 2014-07-02 through 2021-04-07. This is a leading historical roster gap before Sarrat first appears, not an inferred extractor failure. The longest continuous-calendar gap between observed values is **7 days** (2014-09-11 through 2014-09-17 for dams with otherwise complete Page 1 coverage).

No value is interpolated or silently filled. Most absent dam/date states are classified from the accepted Page 1 row census, so the reason remains source-aware but is not a fresh cell-level PDF audit.

**B. IS COMPLETENESS NOW QUANTIFIED WITH LONGEST GAPS AND SOURCE-AWARE MISSINGNESS? YES_WITH_EXPLICIT_GAPS.**

## H. Temporal plausibility

All **129,390** storage observations were placed in dam/date order. The primary daily comparison uses only observations separated by exactly one calendar day. Per dam, the build calculates the median and MAD of those contiguous-day changes and applies `z_robust = 0.6745 * (delta - median) / MAD`.

The threshold `|z_robust| >= 6.0` is an analyst screening rule, not a physical law.

- Contiguous-day pairs: **127,192**
- Eligible numeric robust-z comparisons: **119,548**
- Normal numeric comparisons: **114,235**
- Robust review outliers: **5,313**
- MAD-zero nonmedian changes requiring source review: **7,644**
- First observations or long-gap pairs excluded from daily comparison: **2,198**
- Unresolved statistic rows: **0**
- Representative strongest outliers: **40** (20 positive and 20 negative)
- Representative exception source traces confirmed: **40/40**

MAD-zero nonmedian changes receive no fabricated numeric z score. Long-gap pairs are not treated as one-day changes. Capacity-regime changes are attached as context where present, but context does not erase an anomaly. The flags do not change accepted observations and do not by themselves establish hydrological, operational, reporting, or extraction error.

**H. IS TEMPORAL PLAUSIBILITY NOW SCREENED AND REVIEWABLE WITHOUT SILENT CORRECTION? YES_WITH_EXPLICIT_GAPS.**

## Accepted C-G reproduction

The E6A build regenerated C-G from accepted repository evidence and reproduced the E3.1 counts exactly:

| KPI | Eligible | Pass | Fail | Excluded/Unknown |
|---|---:|---:|---:|---:|
| C | 129,390 | 129,390 | 0 | 0 |
| D | 129,241 | 127,753 | 1,488 | 149 |
| E | 84,471 | 80,814 | 3,657 | 44,919 |
| F | 3,967 | 3,965 | 2 | 18 |
| G | 0 | 0 | 0 | 15,852 |

Page 3 authority remains `PROBABLE`, and G exclusions remain exclusions rather than failures.

## Validation

- `python src/build.py`: **not rerun in E6A.1**, because this bounded patch preserves the accepted 1,500 audit rows and changes only decision logic and reporting. The underlying E6A build previously passed.
- Full test suite: **32 passed**.
- Fixed sample reproduction: **PASS**; 1,500 observation IDs reproduce in the same order.
- Generated CSV and JSON parsing: **PASS**.
- Pydantic tested: `2.12.5`.
- pdfplumber tested: `0.11.9`.
- Protected data/GIS hashes: **32/32 unchanged**.
- V010 hash: **unchanged**.
- Public remote: **none**.
- Secrets detected: **none**.
- Satellite validation KPI I: **not run; outside E6A**.

The main provenance registry was externally locked during E6A. The four append-only E6A rows are preserved without loss in `provenance/ENGINEERING_CHANGES_E6A_PATCH.csv` for later merge; no existing provenance row was overwritten.

## Validation status

**PASS_WITH_EXPLICIT_GAPS**

The remaining gaps are interpretive: row-census-based missingness attribution, MAD-zero temporal groups, incomplete operational context for outliers, qualified Page 3 authority, and the deferred provenance-registry merge. They do not hide or mutate accepted scientific values.

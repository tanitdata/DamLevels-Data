# Extraction accuracy — E6A.1

This is a reproducible **independent source-cell consistency audit**. It reads printed glyphs directly from original bulletin PDF cell regions with `pdfplumber` and preserved cell bounding boxes. Fifteen representative crops were visually spot-checked. It does **not** invoke the production extractor or reuse historical audit labels.

- Fixed random seed: `20260925`
- Sampled cells: **1,500**
- Verifiable cells: **1,500**
- Matches: **1,500**
- Errors: **0**
- Unverifiable: **0**
- Accuracy: **100.000000%**
- Error rate: **0.000000%**
- Descriptive pooled Wilson 95% interval: **[99.744557%, 100.000000%]**
- Interval type: **DESCRIPTIVE_SIMPLE_BINOMIAL_INTERVAL**
- Professor population-wide target (>= 99.5%): **INCONCLUSIVE**

Wilson formula: `(p̂ + z²/(2n) ± z*sqrt((p̂(1-p̂)+z²/(4n))/n)) / (1+z²/n)`, with two-sided 95% `z=1.959963984540054`. This descriptive interval is conditional on independent equally sampled Bernoulli trials. The assumption does not support population-wide inference here because the audit uses unequal stratum allocation and nine-cell bulletin/PDF clusters.

## Strata

- `EARLY_LAYOUT15`: 351
- `KNOWN_ROSTER_SCOPE`: 96
- `MIDDLE_LAYOUT16`: 351
- `RECENT_LAYOUT16`: 351
- `TRANSITION_LAYOUT16`: 351

Unverifiable rows are excluded from the accuracy denominator and never counted as passes. Any discrepancy is retained as a correction candidate; production data remain unchanged.

All 1,500 selected cells matched. The descriptive pooled Wilson interval does not establish the population-wide >=99.5% target; KPI A remains **INCONCLUSIVE** pending a design-valid independent audit.

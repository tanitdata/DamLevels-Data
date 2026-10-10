# Review of the apparent cross-page mismatches

The suspicion is partly confirmed. The large October 2015 stock discrepancy comes from the contributor roster used by the comparison. July 2022 contains a separate repeated-storage pattern. The persistent withdrawal discrepancy from January 2024 is a different issue and is visible in at least one original bulletin PDF. A single global date shift would not repair these problems.

No source measurements, master tables, features or model results were modified.

## 1. October 2015: the sum excludes two available Page-2 values

On 3–6 October 2015, `merged_daily_candidate.csv` has Page-2 records for **Ben Metir and Sidi Aïch**, but `p1_row_present = 0` for both. Restricting the Page-2 sum to the extracted Page-1 roster therefore counts only 24 dams instead of the 26 represented on Page 2. Calling that sum “complete” is misleading for a national-stock comparison.

All quantities below are Mm³. The difference is Page 3 minus the Page-2 sum.

| Date | Page-3 stock | Restricted P2 sum | Ben Metir, excluded | Sidi Aïch, excluded | P2 sum including both | Remaining difference |
|---|---:|---:|---:|---:|---:|---:|
| 2015-10-03 | 1153.455 | 1112.834 | 40.419 | 0.201 | 1153.454 | +0.001 |
| 2015-10-04 | 1151.335 | 1110.794 | 40.340 | 0.201 | 1151.335 | 0.000 |
| 2015-10-05 | 1149.573 | 1109.111 | 40.262 | 0.201 | 1149.574 | −0.001 |
| 2015-10-06 | 1147.253 | 1106.868 | 40.184 | 0.201 | 1147.253 | 0.000 |

This identifies the source of the *comparison* spike without interpolating, shifting dates or changing any observation. It does not establish why the two Page-1 rows are absent from the extraction; inspect the original Page-1 PDFs to settle that.

The same mechanism appears on **11 August 2016**: Lebna is absent from the Page-1 roster but has **5.598 Mm³** on Page 2. Including it reduces a **5.599 Mm³** discrepancy to **0.001 Mm³**.

Five of the 17 large stock discrepancies in this reconstruction are explained by these roster omissions. Twelve other stock dates remain above the stated rounding bound; two are the July 2022 cases below. See `evidence/stock_exception_dates.csv` for every date.

**Required change to the audit:** derive expected membership independently of the extraction being checked. At minimum, compare the union of Page-1 and Page-2 date/dam keys and report missing members explicitly. The union is a useful cross-check, not a final official roster: it cannot detect a dam omitted from both pages. Do not fill an absent Page-1 observation with zero or overwrite it with Page 2 merely to force agreement.

## 2. July 2022: the “flat, then jump” pattern exists in the CSVs

On **2 and 3 July 2022**, all **36 dams** repeat the previous day's storage in both Page 1 and Page 2. Page 3 continues changing. The Page-1/2 sum then changes from **1018.588** to **1007.860 Mm³** on 4 July, a one-step decline of **10.728 Mm³** after the two flat days.

For example, Sidi Salem:

| Bulletin date | P1 storage | P2 storage | P3 storage |
|---|---:|---:|---:|
| 2022-07-01 | 183.695 | 183.695 | 183.695 |
| 2022-07-02 | 183.695 | 183.695 | 183.203 |
| 2022-07-03 | 183.695 | 183.695 | 181.479 |
| 2022-07-04 | 180.515 | 180.515 | 180.515 |

This independently reproduces the pattern recorded in vault finding F-016, now in the supplied canonical merged export and on both pages. The July source PDFs are not available here, so **stale publication versus extraction/copying error remains unresolved**. Page 3 is corroborating evidence, not an automatic replacement source for all 36 dams.

For modelling, flag the questionable observations and any target or difference that directly uses them until source review resolves them. In particular, daily storage differences on 2–4 July are unsuitable as unquestioned physical-balance evidence. Do not remove an entire season or fabricate smooth values.

## 3. National inflow: low exact equality mostly reflects precision

I reproduced **52 exact / 537 evaluated** against the Page-2 dam sum. The other **485** differences are within the explicitly assumed aggregation-rounding bound; the maximum absolute difference is **0.008 Mm³**.

The national Page-3 inflow lies on a **0.01 Mm³ grid on 3961 of 3962 numeric dates**, even though its raw text usually displays three decimal places. Regional values retain finer precision. In the original **16 July 2025 PDF**, regional inflows are 0.088 + 0.013 + 0.007 = **0.108**, while the national Page-3 figure is **0.110**. Page 1 prints **0.108**. Literal equality is therefore the wrong sole quality score for this example.

Coverage matters: of the 537 evaluable national Page-2 inflow dates, **10 precede 9 January 2024**, one is 1 March 2024, and **526 run from 30 April 2024 onward**. This is not an evenly sampled eleven-year comparison.

The supplied canonical schema also changes one physical Page-2 column from **month-to-date inflow through 26 April 2024** to **reporting-interval evaporation from 27 April 2024**. That column must remain separate from the dedicated daily-inflow field. Do not use cumulative values to fill missing daily observations.

## 4. Withdrawal: a persistent discrepancy begins on 9 January 2024

The atlas's two Page-2 withdrawal comparisons reproduce exactly:

| Scope | Evaluated | Exact | Additional rounding-compatible | Above bound |
|---|---:|---:|---:|---:|
| National | 526 | 13 | 12 | 501 |
| Three regions combined | 1730 | 1023 | 206 | 501 |

All **501** large regional differences are Northern, and their dates are identical to the 501 large national differences. The national Page-2 comparison begins only on 30 April 2024, so the earlier break must be studied using Page 1 or the Page-3 series themselves.

Against the complete extracted Page-1 Northern dam sum, the median absolute discrepancy changes from **0.001 Mm³ before 9 January 2024** to **0.7325 Mm³ afterward**. A descriptive scan of the frequency of large discrepancies identifies **9 January 2024** as its strongest single boundary. This locates a numerical change; it does not prove a change in hydrological processes or official definitions.

There is also a precision change: before the boundary, every numeric national withdrawal is on a hundredth grid; afterward, 570 of 638 dates use a nonzero third decimal. That precision change cannot explain discrepancies of several tenths or several Mm³.

**Direct visual PDF check, 16 July 2025:**

| Printed quantity | Page 1 | Page 3 | P3 minus P1 |
|---|---:|---:|---:|
| Northern withdrawal | 2.905 | 2.027 | −0.878 |
| National withdrawal | 2.995 | 2.117 | −0.878 |
| National storage | 849.240 | 849.240 | 0.000 |

The withdrawal discrepancy is present in this original bulletin, not introduced by our numerical join. Whether it reflects a changed accounting scope, a source spreadsheet formula, or another reporting issue still needs documentary/source review.

Subtracting the three physical T5 transfers is **not an established correction**. Over the same 638 post-boundary Northern dates, it reduces mean absolute discrepancy from **0.861** to **0.335 Mm³**, but only **61/638** residuals satisfy the aggregation bound. The accounting row describing Sejnane inflow was excluded from this physical transfer sum.

The statement “Page 3 stays internally consistent throughout” also needs qualification. The uploaded cells contain **10 withdrawal dates** where the national figure differs from the three-region sum by more than 0.007 Mm³, up to **0.900**. One inflow date, **3 June 2019**, has a 1.278 Mm³ internal discrepancy. These are recorded separately; the source PDFs for those dates were not checked here.

## 5. A calendar-day shift does not solve these problems

I compared **P3(t)** to the named reference at **t−1, t, t+1**, using actual calendar dates. Each row below uses exactly the same eligible dates for all three offsets; previous/next available bulletin rows were not substituted across gaps.

| National P2 reference | Matched dates | MAE at t−1 | MAE at t | MAE at t+1 |
|---|---:|---:|---:|---:|
| Inflow sum | 518 | 1.3271 | **0.0026** | 1.3209 |
| Stock sum, original restricted roster | 3454 | 3.2303 | **0.0552** | 3.2114 |
| Withdrawal sum | 518 | 0.9902 | **0.8930** | 0.9813 |

Same-date alignment is best on these matched comparisons. Withdrawal still fails substantially; moving the date merely changes the discrepancy. These are tests of repeated bulletin quantities, **not estimates of rainfall-to-inflow travel time**.

## 6. Which files were available, and what is still missing?

| Actual input | Role |
|---|---|
| `merged_daily_candidate.csv` | 129508 rows; separate Page-1 and Page-2 measurements, row-presence indicators and source lineage |
| `p3_cell_observation.csv` | 274183 cells over 3963 bulletin dates; national/regional/transfer values and raw text |
| `CANONICAL_DATABASE_SCHEMA.md` and field registry | Interpret source fields and date-dependent semantics |
| `AUDIT_ATLAS(1).pdf` and `audit_map.zip` | Atlas definitions and displayed counts; the ZIP has diagrams and PDF, not the underlying comparison CSVs |
| `BARRAGES-16-7-2025.pdf` | Original Page-1 and Page-3 visual verification |

The four principal columns used were `source_p1_stock_today_mm3`, `p2_source_storage_current_total_corresponding_p2_mm3`, `p2_source_inflow_reporting_interval_p2_mm3` and `p2_source_outflow_reporting_interval_p2_mm3`. Current Page-1 withdrawal is `source_p1_release_yesterday`; `source_p1_release_today` is the previous-year reference and was not used as current withdrawal.

**Reproduction limit:** the atlas reports 3597 evaluated stock comparisons, but the supplied export and reconstructed roster produce **3604**, including 17 rather than 16 above-bound cases. Three of the four queried comparison rows reproduce their full exact/rounding/large-difference counts. I cannot identify the reason for those seven stock eligibility differences without the actual run files. Also, a sum of Page-1 dam rows is not the same artifact as a Page-1 printed total. Full historical printed-total CSVs were unavailable here.

To close that gap, upload the folder:
`<PFE_FINAL>/artifacts/runs/interpage_20260908_v1`

The most useful files are `comparisons.csv.gz`, `pair_registry.csv`, `comparison_summary.csv`, `comparison_by_regime.csv`, `comparison_by_year.csv`, plus the comparator script/configuration or run manifest identifying its input versions.

Prioritize original PDFs for **2–3 July 2022**, **3–6 October 2015**, **8–10 January 2024**, then **11 August 2016**. Neighboring days help distinguish a layout change from a repeated value. The evidence folder includes the source filenames and individual records to inspect.

## How the quality score should be presented

Report each relationship's unit, date/interval meaning, scope, expected contributors, observed contributors, evaluated date range, exact count, rounding-compatible count and larger-difference count. Separate roster failure, reporting-period limitations, repeated values and unresolved source disagreement. Numerical compatibility alone does not establish semantic identity.

The rounding sensitivity used here is `q_total/2 + n*q_dam/2`, with dam precision 0.001 Mm³; national inflow precision 0.01; national withdrawal 0.01 before the January boundary and 0.001 afterward; regional flows and stock totals 0.001. It assumes separate rounding of the same additive quantity and is labelled **compatible**, not proven. Exact means absolute numeric difference no larger than 1e-8 Mm³.

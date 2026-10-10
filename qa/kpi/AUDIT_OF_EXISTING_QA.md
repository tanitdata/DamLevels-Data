# Audit of the existing QA and KPIs

Date: 30 September 2026. Scope: `qa+powerbi/DAM_QA_SUBMISSION_CLEAN`, `qa+powerbi/qa`, the formula README `DAM_QA_FORMULAS_WITH_VARIABLES_README.md`, the open package (`data/`, `provenance/`, `sources/`, `datapackage.json`) and the DLO 0.3 ontology (copy in `ontology_ref/`).

Nothing outside this `kpi` folder was changed or deleted.

---

## 1. How the audit was done

1. I read every registry, report and producer script of the QA package.
2. I re-ran the QA logic in Python on the same staged inputs. The counts came out identical:
   - Q04–Q07 (daily vs cumulative): 118,419 / 119,415 / 122,072 / 124,610 passes, exactly as in `QA_MASTER_SUMMARY.csv`.
   - Q14 (Page 3): 13,129 / 14,229, recomputed from the published `data/transfers.csv`.
   - Q01–Q03, Q09, Q18: same counts.
3. Then I checked each formula against the meaning of the columns. The meanings come from the ontology: DLO 0.3 rules and 46 corpus tests.
4. When a result looked wrong, I opened the source PDF to check it.

So the QA code does what it says. The problems are in some of the **rules** it uses, not in the arithmetic.

---

## 2. Findings

### F-1. Cumulative counters were reset on the wrong day (Q04–Q07, Q14). **Wrong.**

- **What the QA does:** it resets the month-to-date counter when the *bulletin date* changes month, and the season counter when the bulletin date passes 1 September.
- **What the source means:** bulletin D reports the day D−1 ("du D−1 observée le D", test H01, 3,981/3,981). So the month-to-date total on bulletin D runs from the first day of the month of **D−1** to D−1. It resets on the bulletin of the **2nd** of the month, not the 1st. Season totals reset on the bulletin of **2 September**. These are DLO rules `MONTH_TO_DATE` and `SEASON_TO_DATE`.
- **Effect:**
  - Every real reset (the bulletin of the 2nd) was checked as a normal day. It showed a big negative step: 4,158 "negative steps" for inflow MTD, against 4,166 resets.
  - Every valid day (the bulletin of the 1st) was excluded as a "reset".
- **Evidence:** `results/K10_counter_reset_rule_comparison.csv`. With the DLO rule, the eligible counts equal the ontology tests exactly: 122,957 = H06, 122,959 = H08, 126,191 = H07, 126,155 = H09.
- **Corrected KPI:**

| Series | QA (old reset) | DLO reset |
|---|---:|---:|
| inflow month-to-date | 96.26 % | **99.48 %** |
| outflow month-to-date | 97.06 % | **99.56 %** |
| inflow season-to-date | 96.74 % | **97.03 %** |
| outflow season-to-date | 98.78 % | **99.05 %** |
| Page 3 daily vs season | 92.27 % | **92.54 %** |

### F-2. Ziatine and Gamgoum season-to-date inflow is swapped in the source (2017–2021). **Real source error.**

- The remaining inflow season-to-date failures are concentrated in two dams: Ziatine (1,475) and Gamgoum (1,251).
- From 31 January 2017, when Gamgoum enters the table, the Gamgoum counter grows by exactly the **Ziatine** daily inflow, and the other way round. The last swapped day found is 7 February 2021; from September 2021 the counters are correct again.
- **PDF check:** `13-1-2018_1.pdf` (SHA-256 `7154afcd…a505`, same hash as the manifest) prints:
  - Ziatine season total 0,618;
  - Gamgoum season total 12,832.

  The extraction is faithful. The publisher printed the two values in each other's rows.
- Without these two dams, the inflow season-to-date KPI is 99.15 %.
- **Evidence:** `results/K10_ziatine_gamgoum_swap_test.csv`, which gives the pass rate per year for the own column and for the swapped column.
- **Action:** record it as a source issue in `docs/known_issues.md`. Do not swap the published values.

### F-3. Fill consistency ignored two of the three roundings (Q10 / E). **Wrong tolerance.**

- **The QA rule:** `|100·V/C − F| ≤ half the printed unit of F`.
- **The problem:** V is printed to 0.001 Mm³ and C to 0.01 Mm³, so both are rounded too. For a small dam (C ≈ 10 Mm³), the rounding of C alone moves the computed fill by about 0.05 points. That is as much as the whole tolerance.
- **Corrected rule (interval arithmetic):** compatible when `[100(V−0.0005)/(C+0.005), 100(V+0.0005)/(C−0.005)]` overlaps `[F−h, F+h]`.
- **Result:** 84,470 / 84,471 compatible, against 80,814 before. The only real mismatch is Masri, 9 February 2022: printed 44.9 %, computed 43.87 %.
- The national-total check (F) already used this principle (`n × 0.0005`). The fill check did not.
- **Evidence:** `results/K11_fill_changed_or_failing_rows.csv`.

### F-4. "Above capacity" was counted as a validity failure (Q11 / D). **Misleading KPI.**

- The capacity used is the printed *useful capacity at the last survey*. Storage above it is physically possible, for example in flood surcharge or after sedimentation surveys.
- Of the 1,488 rows above capacity:
  - 836 have a printed fill, and **all 836 print fill ≥ 100 %** in the bulletin itself;
  - the median excess is 0.42 %.
- **Corrected:** the validity KPI checks only what is impossible: finite and ≥ 0. That gives 129,390 / 129,390. The above-capacity share, 1.15 %, becomes diagnostic D1.

### F-5. Completeness mixed two different things (Q16/B and Q17). **Misleading KPI.**

- **Naive B, 90.28 %:** its denominator counts all 36 dams on every bulletin date, even before a dam appears in the bulletin. For example, Sarrat is only printed from 8 April 2021. So this measures the **publisher's roster**, not our capture. It becomes K07a, reported as source coverage.
- **Q17, 97.14 %:** it divides the P1-or-P2 union (129,508 rows) by a calendar-day denominator (133,322) that includes days with no bulletin. Numerator and denominator have different grains.
- **Corrected split:**
  - **K06 value capture:** printed dam rows that have a numeric value = 129,390 / 129,391. The one exception is a printed blank.
  - **K07b coverage inside each dam's reporting era:** 129,390 / 129,400.

### F-6. Robust z and 3σ flag rates are not quality KPIs (Q12/H, Q13). **Reframed.**

- A flag rate from a statistical screen depends on the shape of the data, not on its correctness. They stay as **diagnostics** (D2, D3).
- **Q12 (robust z):** 7,644 daily changes got no score at all, because the per-dam MAD is 0. So the 4.44 % rate is computed on a reduced population. A scaled MAD floor or an IQR rule would fix this later.
- **Q13 (water balance):** the balance cannot close, because evaporation, seepage and spill are not printed. The new diagnostic D2 reports closure within the printed rounding (`|R| ≤ 4 × 0.0005`): 31.15 %.

### F-7. Published transfer dates do not match the verified time (transfers.csv). **Schema issue.**

- `transfers.csv` stores `date = bulletin_date` with `effective_date_rule = SAME_DAY` for all 47,556 rows.
- DLO 0.3 verified:
  - `today` is the amount for day D−1 (`DAY_BEFORE_BULLETIN`);
  - `current_season_to_date` is an interval (`SEASON_TO_DATE`).

  The QA transfer check (G) still lists this as "DATE_SEMANTICS_UNRESOLVED".
- K08 counts rows whose published date equals the DLO time. Storage matches (129,390/129,390). Transfers do not (0/31,704).
- **Fix proposed, not applied:** keep `date` for provenance and add `dlo_temporal_rule`, `phenomenon_time_start` and `phenomenon_time_end_exclusive`. See `schema/transfers_contract_v2_proposal.json`.

### F-8. Checks that are correct (confirmed)

| QA | What | Recomputed |
|---|---|---|
| Q01 | P1 = P2 storage | 128,995 / 128,996 |
| Q02 | P1 = P2 inflow | 92,330 exact / 92,338 (+1 within one unit) |
| Q03 | P1 = P2 outflow | 83,584 exact / 83,642 (+2 within one unit) |
| Q09 / F | national total | 3,965 / 3,967 |
| Q18 / C | uniqueness (dam_id, date) | 129,390 / 129,390 |
| A1–A3 | sampled extraction | 800/800, 800/800, 792/792 (carried; needs the PDFs) |

These checks also follow the DLO time rules: storage is a state at D, and flows cover D−1 on both pages. Q03 uses `p1_release_yesterday`, as the ontology confirms (H12, 99.93 %; negative control H13, 14.3 %).

---

## 3. Schema findings

| # | Where | Problem | Fix |
|---|---|---|---|
| S-1 | `datapackage.json` | Resources `printed-fill-reference` and its Parquet point to `qa/…`, but the files are now in `qa+powerbi/qa/`. 13 of 15 paths resolve. | Update the two paths, or move the files back. |
| S-2 | `datapackage.json` | Name and version still say `e5-private` / `0.5.0`, while the content is E6A.2. | Bump the version. |
| S-3 | storage schema | `unit` says "Mm3 or percent", but only Mm3 is allowed now. No `minimum: 0` on `value`. No unique key on `(dam_id, date)`. | `schema/storage_contract_v2.json` (all rows already pass it). |
| S-4 | transfers schema | The date semantics conflict with DLO (F-7). | `schema/transfers_contract_v2_proposal.json`. |
| S-5 | `registries/VARIABLE_REGISTRY.csv` | The Page 2 physical names are wrong: `p2_volume_exploitable_mm3` is given for the storage *total* column, and `p2_apport_pluv_mm3` and `p2_soutirage_30dec_mm3` do not exist. The real columns are `storage_current_total_corresponding_p2_mm3` (col 19), `inflow_reporting_interval_p2_mm3` (col 22) and `outflow_reporting_interval_p2_mm3` (col 21). | Label fix only; the data used was right. |
| S-6 | `registries/VARIABLE_REGISTRY.csv` | The time basis of the MTD and HYTD counters says "calendar month" and "Sep 1–Aug 31". It must say "month of D−1 up to D−1" and "1 September of the season of D−1 up to D−1". This is the root cause of F-1. | Use the DLO rule codes. |
| S-7 | formula README F02 | `r = S_printed − Σx`, but the Page 1 extractor stores `Σx − S_printed`. | State one sign convention. |

---

## 4. Ontology cross-check (DLO 0.3)

| QA check | Columns | DLO rule | Consistent? |
|---|---|---|---|
| Q01 | P1 / P2 storage | `STATE_AT_BULLETIN_DATE` on both | yes |
| Q02, Q03 | P1 / P2 inflow and outflow | `DAY_BEFORE_BULLETIN` on both | yes |
| Q04, Q05 | month-to-date counters | `MONTH_TO_DATE` = first of month of D−1 … D−1 | **no**: reset on the wrong day (F-1) |
| Q06, Q07 | season counters | `SEASON_TO_DATE` = 1 Sep of hy(D−1) … D−1 | **no**: reset on the wrong day (F-1) |
| Q09 | national total vs dams | state at D; Page 1 total = national feature | yes |
| Q10 | fill vs storage / capacity | `StorageFillRatio` (D) vs `UsefulCapacity` (`REGIME_VALUE_AS_PRINTED`) | yes; tolerance fixed (F-3) |
| Q13 | water balance | V(D) − V(D−1) against flows of D−1 | yes |
| Q14 | Page 3 today vs season | `DAY_BEFORE_BULLETIN` / `SEASON_TO_DATE` | **no**: reset on the wrong day (F-1) |
| G / Q20 | transfers | T5 `today` = `DAY_BEFORE_BULLETIN` (HIGH) | the published date conflicts (F-7) |

The KPIs are also exported as W3C DQV measurements (`results/KPI_DQV.ttl`), the quality vocabulary DLO already uses.

---

## 5. Verdict on the 18 formulas of `DAM_QA_FORMULAS_WITH_VARIABLES_README.md`

| Formula | Verdict |
|---|---|
| F01 cross-page difference | correct |
| F02 checksum residual | correct, but fix the sign convention (S-7) |
| F03 daily vs cumulative | the formula is right, but the eligibility (reset day) is wrong (F-1) |
| F04 0.0015 bound | correct: three printed numbers × 0.0005 |
| F05 expectedness completeness | mixes grains; replaced by K06 / K07b (F-5) |
| F06 uniqueness | correct |
| F07 0 ≤ V ≤ C | only V ≥ 0 is a hard rule; V > C is a diagnostic (F-4) |
| F08 derived fill | correct |
| F09 fill residual | the formula is right, but the tolerance is incomplete (F-3) |
| F10 national residual | correct |
| F11 storage change | correct |
| F12 robust z | correct as a screen, not as a KPI; the MAD = 0 gap remains (F-6) |
| F13 water balance | correct as a diagnostic |
| F14 Page 3 daily vs cumulative | reset day wrong (F-1) |
| F15, F16 multi-day | correct; descriptive only |
| F17 transfer lag | correctly marked not executed |
| F18 latency | correctly marked not implemented |

---

## 6. Power BI (not changed)

- `Check Pass Rate = DIVIDE(SUM(pass), SUM(eligible))`: with no check selected, this becomes the pooled global score that the package itself forbids.
- `Average Dam Completeness %` averages the per-dam ratios, so Sarrat's 41 % weighs as much as a complete dam. A pooled ratio is the right measure.
- The dashboard reads the old Q04–Q07, Q10, Q11 and Q14 numbers. Its figures will change if it is rebuilt from `results/KPI_RESULTS.csv`.

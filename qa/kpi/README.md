# Open-data quality KPIs for DamLevels-Data

This folder recomputes the quality indicators of the open package in plain Python (pandas). It then compares every indicator with the automated QA (`DAM_QA_SUBMISSION_CLEAN`, `qa/qa_summary.json`).

**These results supersede the D, E and B values in `qa/qa_summary.json` / `qa/report.md` and every number in the earlier QA/Power BI package.** See `AUDIT_OF_EXISTING_QA.md`.

It only reads. Every output goes to `results/` inside this folder. No input is changed or deleted.

`inputs/` holds byte-identical copies of the five staged files the comparison needs from the earlier automated-QA package (`DAM_QA_SUBMISSION_CLEAN`), so that package does not have to be kept in the repository. Their SHA-256 values are recorded in `results/RUN_RECEIPT.json`.

## Run it

From the repository root:

```powershell
python qa/kpi/run_kpis.py
python qa/kpi/make_kpi_figures.py
```

- **Needs:** Python 3.10+, `pandas`, `pyarrow`.
- **Optional:** `frictionless` (for K01 and the schema part of K03).
- **Runtime:** about 15 seconds.

## Files

| File | What it is |
|---|---|
| `run_kpis.py` | the whole KPI pipeline |
| `make_kpi_figures.py` | the five KPI figures of report Section 9.8 (run after `run_kpis.py`; needs matplotlib) |
| `AUDIT_OF_EXISTING_QA.md` | what was traced, what was wrong, and why |
| `schema/storage_contract_v2.json` | stricter storage schema (all rows pass it) |
| `schema/transfers_contract_v2_proposal.json` | adds the DLO time columns to transfers |
| `ontology_ref/` | copy of the DLO 0.3 catalogue, temporal rules and hypothesis tests used by the checks |
| `results/KPI_RESULTS.csv` | every KPI: formula, numerator, denominator, value |
| `results/KPI_VS_AUTOMATED_QA.csv` | new value next to the automated QA value, with a verdict |
| `results/KPI_DQV.ttl` | the same results as W3C DQV quality measurements |
| `results/K*_*.csv`, `results/D1_*.csv` | the rows behind each KPI (exceptions only) |
| `results/RUN_RECEIPT.json` | input SHA-256 hashes and versions |
| `results/figures/` | `fig_kpi_overview`, `fig_kpi_counter_reset`, `fig_kpi_fill_residual`, `fig_kpi_completeness`, `fig_kpi_swap` (PDF and PNG) |

## Results (30 September 2026)

### A. Published package

| KPI | Result | Automated QA |
|---|---:|---:|
| K01 rows valid against the declared schema | 177,042 / 177,042 = 100 % | 100 % |
| K02 resource paths that resolve | 13 / 15 | not checked |
| K03 stricter storage contract | 129,390 / 129,390 = 100 % | not checked |
| K04 unique (dam_id, date) | 100 % | 100 % |
| K05 storage rows traceable to the manifest hash | 100 % | not checked |
| K06 printed dam rows with a value | 129,390 / 129,391 = 99.9992 % | new |
| K07a publisher roster coverage (source side) | 90.28 % | 90.28 % (B) |
| K07b coverage inside each dam's reporting era | 99.9923 % | 97.14 % (Q17) |
| K08 dates that match the DLO time | 80.32 % (storage 100 %, transfers 0 %) | not checked |
| K16 fields with a description | 100 % | not checked |
| K17 licences cleared | 0 / 2 | not checked |

### B. Extraction consistency behind the package

| KPI | Result | Automated QA |
|---|---:|---:|
| K09a P1 = P2 storage | 99.9992 % | 99.9992 % |
| K09b P1 = P2 inflow (exact) | 99.9913 % | 99.9957 % (exact + compatible) |
| K09c P1 = P2 outflow (exact) | 99.9307 % | 99.9330 % |
| K10a inflow month-to-date | **99.48 %** | 96.26 % |
| K10b outflow month-to-date | **99.56 %** | 97.06 % |
| K10c inflow season-to-date | **97.03 %** (99.15 % without the Ziatine/Gamgoum source swap) | 96.74 % |
| K10d outflow season-to-date | **99.05 %** | 98.78 % |
| K11 printed fill vs storage / capacity | **84,470 / 84,471** | 95.67 % |
| K12 national total | 3,965 / 3,967 = 99.95 % | 99.95 % |
| K13 physically possible storage (finite, ≥ 0) | 100 % | 98.85 % (counted V > C as a failure) |
| K14 Page 3 today vs season total | **92.54 %** | 92.27 % |
| K15a–c sampled extraction (P1, P2, P3) | 800/800, 800/800, 792/792 | same (carried) |

### C. Diagnostics (not quality scores)

- **D1** storage above useful capacity: 1.15 %. All such rows with a printed fill show fill ≥ 100 % in the bulletin itself.
- **D2** water balance closes within printed rounding: 31.15 %. Non-closure is expected, because evaporation is not printed.
- **D3** robust storage-change review flags: 4.44 %. 7,644 changes had MAD = 0 and got no score.

## What changed and why (short)

1. **Counters reset one day later.** Bulletin D reports day D−1 (DLO rules MTD and STD), so the reset comes on the bulletin of the 2nd of the month and of 2 September.
2. **Fill tolerance.** The rounding of storage and capacity is now included, not only the rounding of the fill.
3. **Completeness split.** Our value capture (K06, K07b) is now separate from what the publisher printed (K07a).
4. **Above capacity** is a diagnostic, not a failure.
5. **Flag rates** (robust z, 3σ) are diagnostics, not KPIs.
6. **Found in the source:** the Ziatine and Gamgoum season-to-date inflows are printed swapped from 2017 to 2021 (checked in `13-1-2018_1.pdf`).

Details and evidence are in `AUDIT_OF_EXISTING_QA.md`.

## Limits

- K15a–c are carried from the sampled PDF audit. Recomputing them needs the PDFs.
- The printed checksums (Q08) and the Page 3 multi-day checks (Q15) are not recomputed here.
- The checks read the staged Run 6 Page 1 / Page 2 view in `DAM_QA_SUBMISSION_CLEAN/staged_data/`.

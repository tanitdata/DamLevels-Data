# INTERPAGE_MISMATCH_REVIEW

Start with `MISMATCH_REVIEW.md` and `evidence/mismatch_timeline.png`.
Every output already contains results. This is a source-comparison investigation; no model was trained and no master data was repaired.

The two scripts use pandas, NumPy and Matplotlib. They read your existing CSVs and write a separate results folder. The complete raw exports are not duplicated in this download.

Run in VS Code's terminal, replacing the two input paths with your real files:

```powershell
python -m pip install -r requirements.txt
python inspect_mismatches.py --merged "C:\path\merged_daily_candidate.csv" --p3 "C:\path\p3_cell_observation.csv" --output results
python temporal_checks.py --output results
```

`inspect_mismatches.py` reconstructs the comparisons, preserves missing values, records source hashes and produces small intermediate caches.
`temporal_checks.py` investigates roster omissions, calendar shifts, coverage, Page-3 arithmetic, transfers and the July 2022 pattern.
The report includes manual observations from the original 16 July 2025 PDF; scripts alone do not redo that visual reading.

Useful CSVs:
- `october_2015_explanation.csv`: four disputed days plus neighboring dates and both omitted dams.
- `july_2022_flat_then_jump.csv` / `july_2022_dam_examples.csv`: repeated observations and Page-3 differences.
- `comparison_summary.csv`, `comparison_by_year.csv`, `comparison_by_regime.csv`: independent counts, not a copy of the missing original run.
- `calendar_shift_comparison.csv`: matched-date t−1/t/t+1 tests.
- `stock_exception_dates.csv`: all large stock discrepancies before/after the union-roster check.
- `p3_internal_arithmetic.csv`: national versus regional sum on Page 3.
- `transfer_hypothesis_summary.csv`: tests of specific reported transfer explanations.
- `ATLAS_COUNT_RECONCILIATION.csv`: exactly which atlas counts reproduced and which did not.

Do not apply a blanket one-day shift, delete whole years, replace blanks with zero, or rewrite raw values to satisfy an equality.

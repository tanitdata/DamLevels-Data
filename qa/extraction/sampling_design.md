# E6A.2 multipage sampling design

Fixed seed: `20260926`. Target: `99.500%`. Confidence: two-sided `95%` Wilson score interval.

The minimum zero-error sample size is computed by iterating `n` until `wilson_interval(n, n).lower >= 0.995`. The first qualifying value is **765**; 764 does not qualify. Each numeric family targets 800 PDFs so modest unverifiability can remain explicit without silently replacing sampled units.

The bulletin PDF is the primary independent sampling unit. Each family selects at most one numeric target cell per sampled PDF. PDFs are stratified by their governed layout/text regime and allocated proportionally by the largest-remainder method. The CSVs retain stratum populations, allocations, PDF inclusion probabilities, PDF weights, within-PDF candidate counts and cell-selection probabilities.

Within each selected PDF, one eligible candidate is selected by a fixed-seed SHA-256 ordering. Wilson inference is made separately for Page 1, Page 2 and Page 3 transcription. No combined A1/A2/A3 accuracy is calculated. The Page 3 semantic review is categorical and never enters a numeric Wilson denominator.

Source localization uses preserved production lineage bounding boxes. Values are reread from the original PDF region with `pdfplumber`, independent of production parser functions. This is `COMPUTER_ASSISTED_SOURCE_REREAD`, not a human manual audit. No row is marked `HUMAN_VISUAL_VERIFIED` in E6A.2.

Known difficult cases are placed in a separate challenge set. Challenge rows are excluded from all primary inferential denominators.

## Family allocations

### A1_PAGE1_EXTRACTION

Population by regime: `{"P1_LAYOUT_15_NO_FILL": 1576, "P1_LAYOUT_16_WITH_FILL": 2405}`

Sample by regime: `{"P1_LAYOUT_15_NO_FILL": 317, "P1_LAYOUT_16_WITH_FILL": 483}`

### A2_PAGE2_EXTRACTION

Population by regime: `{"POST_CUTOFF_INTERVAL_EVAPORATION": 530, "PRE_CUTOFF_MONTH_TO_DATE_INFLOW": 3453}`

Sample by regime: `{"POST_CUTOFF_INTERVAL_EVAPORATION": 106, "PRE_CUTOFF_MONTH_TO_DATE_INFLOW": 694}`

### A3_PAGE3_TRANSCRIPTION

Population by regime: `{"R1_c0_control_substitution|P3_PORTRAIT_STANDARD": 2619, "R1_c0_control_substitution|P3_ROTATED": 12, "R2_presentation_forms|P3_PORTRAIT_STANDARD": 343, "R3_standard_letters_lamalef_reversed|P3_PORTRAIT_STANDARD": 989}`

Sample by regime: `{"R1_c0_control_substitution|P3_PORTRAIT_STANDARD": 529, "R1_c0_control_substitution|P3_ROTATED": 2, "R2_presentation_forms|P3_PORTRAIT_STANDARD": 69, "R3_standard_letters_lamalef_reversed|P3_PORTRAIT_STANDARD": 200}`


# Data dictionary

This dictionary defines the E6A.2 public-facing and QA contract. Empty means missing or unavailable. It never means zero.

## Value and status vocabulary

- **Observed value:** a numeric value emitted by an accepted/selected extraction product and linked to its source file. `storage` and `printed_fill_pct` are independently observed Page 1 values.
- **Derived value:** a QA calculation from observed values, such as computed fill percentage or a reconciliation residual. Derived QA values never replace source observations.
- **Audit flag:** a row annotation about provenance, review, missingness, or authority. It does not change the value.
- **Probable/qualified Page 3 evidence:** selected Page 3 facts whose scientific authority remains `PROBABLE`. Physical edges and accounting observations remain separate.
- **Missing:** the source field had no emitted numeric value. No observation row is fabricated; the source occurrence is recorded in `provenance/storage_missingness.csv` or a Page 3 `value_status`.
- **Unavailable:** evidence does not support a unique value for the requested use, such as capacity during a documented regime gap.
- **Zero:** a source-observed numeric zero. It is different from blank, structural absence, or unavailable.

## `data/dams.csv`

One row per governed canonical dam. `dam_id` is immutable. Coordinates are accepted control points transformed from EPSG:32632 to EPSG:4326. Arabic names and basin labels carry their own evidence statuses and paths. Evidence paths outside the repository (`*_source` columns) start with a logical root token such as `<FULL_RECONSTRUCTION>` or `<V010_REVIEW_PACKAGE>`; `config/paths.example.toml` lists what each token stands for. The six populated basin values are supported Medjerda-context statements; blank basins are not inferred from geography.

`reference_capacity_mm3` is the latest durable printed Page 2 regime. It is not a timeless engineering capacity.

## `data/capacity_history.csv`

One row per admitted durable Page 2 capacity regime. Bounds are inclusive. Blank `valid_to` means the current observed regime. Dates are observation support, not independent commissioning evidence. `capacity_for_date()` returns:

- `KNOWN` for exactly one applicable regime;
- `AMBIGUOUS` for multiple applicable regimes;
- `UNAVAILABLE` for no supported regime.

No result is forward-filled across `provenance/CAPACITY_UNKNOWN_PERIODS.csv`.

## `sources/manifest.csv`

One row per logical accepted bulletin date. Page filenames and hashes come independently from accepted Page 1, Page 2, and selected Page 3 inventories. `pages_available` lists supported pages. `PARTIAL_PAGE_INVENTORY` does not imply a missing physical file; it means the accepted source inventories do not supply all three pages for that logical date. `original_url` is the bulletin's link on ONAGRI (`https://www.onagri.nat.tn/uploads/barrages/…`). It points to the combined three-page bulletin, while the page hashes refer to the project's split pages. It is blank for six dates that have no matching entry in the ONAGRI listing.

`sources/original_url_evidence.csv` records how each link was established (listing checked 2026-10-10):

- `PAGE_HASH_CHAIN|LISTING_TITLE_DATE` (2,361): a split page's SHA-256 matches a page split from the file of that name on ONAGRI, and the listing title gives the same date.
- `PAGE_HASH_CHAIN|LISTING_TITLE_DATE_DIFFERS` (9): hash chain as above, but ONAGRI's listing title shows another date; the hash chain is taken as authoritative.
- `LISTING_TITLE_DATE|SERVER_FILE_IN_ORIGINAL_BACKUP` (1,609): the only listing entry with that date, and a file of the same server name is in the downloaded originals; the split copy had been renamed, so no page-hash chain exists.
- `NOT_FOUND_IN_LISTING` (6): no URL assigned.

## `sources/file_manifest.csv`

The byte-preserved E1 path-level inventory: 31,843 physical path records, including backup duplicates and split copies. A row is a physical-file claim, not a unique logical bulletin.

`sources/uncanonicalized_files.csv` lists physical records that cannot be assigned to the logical manifest from established date evidence.

## `data/storage.csv`

Long/tidy Page 1 primary storage observations. One row is one storage value for one governed dam and bulletin date. The intended QA key is `(dam_id, date)`.

| Field | Meaning |
|---|---|
| `observation_id` | Stable hash-derived identifier over source hash, dam, date, and source field. |
| `dam_id` | Governed stable dam ID. |
| `date` | Bulletin reporting date. |
| `variable` | Constant `storage`. |
| `value` | Observed numeric value; never interpolated. |
| `unit` | Constant `Mm3`. |
| `source_file`, `source_sha256`, `page` | Physical source identity. |
| `source_field` | Constant accepted extractor field `p1_stock_today_mm3`. |
| `authority_release`, `engine_version` | Use-specific extraction authority/version. |
| `source_row_key`, `lineage_id` | Accepted row and source-cell lineage identifiers. |
| `flag` | Pipe-separated authority and lineage/QC states. |

`provenance/storage_lineage.csv` preserves cell IDs and parse/review states. `provenance/storage_missingness.csv` records source rows for which no numeric observation was emitted.

## `data/bulletin_page1.csv`

Every column printed on Page 1, in wide form: one row per governed dam and bulletin date, 129,391 rows from 3,981 bulletins (2014-07-02 to 2025-10-10). It comes from the same accepted extraction (engine `page1-authoritative-0.2.3`) as `data/storage.csv`; values are as printed, with dot decimals. A blank cell means the bulletin printed nothing usable there. It is never zero and never filled. Dates are not shifted: `bulletin_date` is the bulletin day D, and the table below gives the day each column describes.

| Field | Meaning | Day described |
|---|---|---|
| `source_row_key` | `PAGE_1\|bulletin_date\|dam_id`; the same key as `source_row_key` in `data/storage.csv`. | |
| `dam_id` | Governed stable dam ID. | |
| `bulletin_date` | Bulletin date D. | |
| `source_file`, `source_sha256`, `page` | Page 1 PDF; equal to the Page 1 entry of `sources/manifest.csv`. | |
| `layout` | `P1_LAYOUT_16_WITH_FILL` (fill column printed, from 2019-02-05) or `P1_LAYOUT_15_NO_FILL`. | |
| `engine_version`, `authority_release` | Extraction engine and authority, as in `data/storage.csv`. | |
| `p1_apport_today` | Inflow, Mm³. Six negative printed values are kept. | D−1 |
| `p1_apport_cumul_this_month` | Inflow month to date, Mm³; restarts on the bulletin of the 2nd. | 1st of the month to D−1 |
| `p1_apport_average_month` | Long-term mean inflow of the month, Mm³ (a reference). | the month |
| `p1_apport_cumul_since_sep` | Inflow season to date, Mm³; restarts on the bulletin of 2 September. | 1 September to D−1 |
| `p1_apport_cumul_prev_year` | Inflow over the same period one year earlier, Mm³. | previous season, to the same day |
| `p1_apport_average_period` | Long-term mean inflow of the season-to-date period, Mm³ (a reference). | 1 September to D−1 |
| `p1_release_action_code` | Operation codes printed beside the releases, comma-separated as printed (`E`, `p`, `tr`, `T`, `d`, …). No printed legend was found; meanings are provisional. | D−1 |
| `p1_release_yesterday` | Release, Mm³. **This is the current release.** | D−1 |
| `p1_release_today` | Release on the same day one year earlier, Mm³ (second value under *Lâchers du jour*). **Never the current release.** | D−1, one year earlier |
| `p1_release_cumul_this_month` | Release month to date, Mm³; restarts on the bulletin of the 2nd. | 1st of the month to D−1 |
| `p1_release_cumul_year` | Release season to date, Mm³; restarts on the bulletin of 2 September. | 1 September to D−1 |
| `p1_release_cumul_last_year` | Release over the same period one year earlier, Mm³. | previous season, to the same day |
| `p1_stock_fill_pct` | Printed fill, % of useful capacity. Printed from 2019-02-05 only; equal to `qa/printed_fill_reference.csv`. | D |
| `p1_stock_today_mm3` | Storage, Mm³; equal to `value` in `data/storage.csv`. | D |
| `p1_stock_last_year_mm3` | Storage on the same date one year earlier, Mm³. | D, one year earlier |

The DLO 0.3 ontology (`ontology/`, source table `P1_observations`) defines each column and its time rule. The table holds the same values as `qa/kpi/inputs/page1.parquet`, so the current indicators K09 (Page 1 = Page 2), K10 (daily values against month and season counters) and K11 (printed fill against storage and capacity) apply to it; `tests/test_bulletin_page1.py` checks all of these equalities. `src/build_page1_table.py` builds it.

## `qa/printed_fill_reference.csv`

The 84,620 non-primary percentages printed independently in Page 1 bulletins. It retains the same provenance columns and observation IDs used in E2. `variable` is `printed_fill_pct`, `unit` is `percent`, and `source_field` is `p1_stock_fill_pct`. This table is a comparison reference; it is not a replacement for storage.

## `data/transfers.csv`

Long/tidy selected Page 3 T5 facts. These rows remain `PAGE3_SELECTED_RELEASE_PROBABLE`.

`TRANSFER_EDGE_DAY` represents a reported physical route. `TRANSFER_ACCOUNTING_DAY` represents Sejnane accounting and is never a hydraulic edge. `from_node_id` and `to_node_id` preserve Page 3 identities. `from_dam_id` and `to_dam_id` are populated only for confirmed stable-ID crosswalks; candidate Bouhertma and Zayatin crosswalks remain blank.

`variable` is the published measure ID (`today`, `current_season_to_date`, or `previous_season_to_date`). Blank and structurally absent values remain blank with `value_status`. `date` and `effective_date_rule` reproduce the selected product fields without reinterpretation. Note: `date` is the bulletin date; under DLO 0.3, `today` describes day D−1 and the season measures describe an interval ending on D−1 (see `docs/known_issues.md`).

## Parquet representations

`data/parquet/storage.parquet`, `data/parquet/transfers.parquet`, `data/parquet/bulletin_page1.parquet`, and `qa/printed_fill_reference.parquet` contain the same logical rows, order, identifiers, variables, and numeric values as their CSV counterparts.

## Quality indicators (current)

`qa/kpi/` holds the 2026-09-30 recompute of the quality indicators (`run_kpis.py`). Its results supersede the D, E and B values of the engineering QA below.

- `qa/kpi/results/KPI_RESULTS.csv`: every KPI with formula, numerator, denominator and value.
- `qa/kpi/results/KPI_VS_AUTOMATED_QA.csv`: each recomputed KPI next to the earlier automated value, with a verdict.
- `qa/kpi/results/KPI_DQV.ttl`: the same results as W3C DQV quality measurements.
- `qa/kpi/results/K*_*.csv`, `D1_*.csv`: the exception rows behind each KPI or diagnostic.
- `qa/kpi/results/RUN_RECEIPT.json`: input SHA-256 values and library versions.
- `qa/kpi/AUDIT_OF_EXISTING_QA.md`: what changed and why (counter reset on D−1, rounding-aware fill tolerance, above-capacity as diagnostic, split completeness).
- `qa/kpi/inputs/`: byte-identical copies of the staged inputs taken from the earlier automated-QA package.

## Engineering QA tables

- `qa/uniqueness.csv`: summary and any duplicate `(dam_id, date)` records; duplicates are never silently removed.
- `qa/physical_validity.csv`: every storage row classified as `PASS`, `NEGATIVE_STORAGE`, `ABOVE_CAPACITY`, `CAPACITY_UNAVAILABLE`, or `CAPACITY_AMBIGUOUS` using date-aware capacity. Superseded rule: `ABOVE_CAPACITY` is a diagnostic (KPI D1), not a failure.
- `qa/fill_consistency.csv`: computed fill versus printed fill under the displayed printed rounding interval, with missing/capacity exclusions explicit. Superseded rule: the tolerance must include the rounding of storage and capacity (KPI K11).
- `qa/national_reconciliation.csv`: one row per canonical bulletin date, using the accepted independently printed Page 1 grand-total evidence in `provenance/page1_national_totals.csv`.
- `qa/transfer_balance.csv`: every daily Page 3 candidate classified for direct-comparison eligibility. Ineligible facts are not failures.
- `qa/qa_summary.json` and `qa/report.md`: one shared A-H result object (satellite KPI I excluded) rendered for machines and people; accepted C-G counts remain unchanged.
- `qa/audit_sample.csv`: fixed-seed, source-to-data extraction audit rows read directly from original PDF cell regions; `UNVERIFIABLE` rows never count as passes.
- `qa/completeness_by_dam.csv`, `qa/completeness_by_date.csv`: bulletin-opportunity and continuous-calendar coverage without interpolation. The denominator counts all 36 dams on every date, so it measures the publisher's roster; capture completeness is KPI K06/K07b.
- `qa/INTERPAGE_MISMATCH_REVIEW/`: the 2026-09-11 Page 1/2/3 inter-page mismatch review (October 2015 roster scope, July 2022 evidence).
- `qa/temporal_plausibility.csv`: per-dam contiguous-day robust median/MAD screening; flags are review findings, not corrections.
- `qa/extraction/page1_audit_sample.csv`: one direct printed Page 1 storage cell per sampled PDF in the primary A1 design.
- `qa/extraction/page2_audit_sample.csv`: one direct printed Page 2 numeric cell per sampled PDF, with field-family labels retained.
- `qa/extraction/page3_transcription_audit_sample.csv`: direct Page 3 `today` or `current_season_to_date` transcription checks; unverifiable cells are excluded rather than passed.
- `qa/extraction/page3_semantic_audit_sample.csv`: categorical Page 3 label, accounting/physical-role, crosswalk, and effective-date dispositions. It is not an accuracy denominator.
- `qa/extraction/challenge_set.csv`: known difficult cases kept outside all primary inferential denominators.
- `qa/extraction/multipage_accuracy_summary.json` and `multipage_accuracy_report.md`: separate A1/A2/A3 results; no pooled multipage accuracy is defined.

Pydantic models in `src/validate/models.py` validate representation. They do not impute missing values or elevate scientific authority.

## Units

- Storage, capacity, and Page 3 reported quantities: `Mm3` (million cubic metres).
- Printed fill: `percent`.
- Latitude/longitude: decimal degrees, WGS 84 (EPSG:4326).

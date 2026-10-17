# Changelog

## 1.2.1 — documentation corrections — 2026-10-17

No published value changed. Found by checking every bulletin PDF against the published tables.

- **Operation-code legend.** Every Page 1 bulletin (3,981 of 3,981) prints a legend for the letters beside the releases: "D : Déversement, E : Exploitation, tr : Transfert, a : déstockage pour abaissement du plan d'eau, d : dévasement, T : Turbinage, P : fuite de drainage". Earlier versions said no legend had been found. The ontology (`ontology/*.ttl`, `*.owl`), `datapackage.json` and the data dictionary now give the printed meanings. Codes `p` and `f` are printed but are not in the legend. The ontology label of `P` was wrong ("drainage or source variant", now "drainage leakage"), and `p` no longer carries a guessed meaning. New concept `dlc:OpDrawdown` for legend code `a`, which is never printed. No IRI changed.
- **Two bulletins dated one day early** (`docs/known_issues.md`, README section 11). The files filed as 28 and 29 September 2019 print 29-09-19 and 30-09-19 on Pages 1 and 2. The rows keep their published dates.
- **July 2022.** The stale bulletins of 2 and 3 July 2022 repeat the previous day's **releases** as well as storage, for all 36 dams.
- **January 2021.** The previous-year anomaly affects 33 dams, not 32 (Sficifa differs in the previous-year inflow only).
- Version 1.2.1 in `CITATION.cff`, `datapackage.json`, `pyproject.toml` and `mcp_server`. KPIs rerun: values identical. The cell-lineage release assets stay attached to v1.2.0 (`provenance/RELEASE_ASSETS.csv`).

## 1.2.0 — full Page 1 and Page 2 tables — 2026-10-13

- Version 1.2.0 in `CITATION.cff`, `datapackage.json`, `pyproject.toml` and `mcp_server`. The cell-lineage files listed in `provenance/RELEASE_ASSETS.csv` are attached to the GitHub release v1.2.0; Zenodo's GitHub archive holds the repository snapshot only.
- **Cell lineage of the full page tables.** New `provenance/RELEASE_ASSETS.csv` lists two files attached to the GitHub release because they exceed the 50 MB file limit: `page1_cell_lineage.csv.gz` (1,896,094 cells) and `page2_cell_lineage.csv.gz` (3,366,272 cells), byte-identical to the extraction output, with SHA-256, size and join keys. Every non-blank numeric cell of the two tables has a lineage record with the same value. README sections 2 and 3 now say where the cell-level record of each value is.
- **MCP server.** `dataset_info` lists the published tables with their row counts; `describe_variable` accepts every column name of the full page tables, answering a renamed Page 2 column (e.g. `previous_hydraulic_year_end_water_level_m`) with its DLO column. Two new tests; `mcp_server/README.md` and README section 8 updated (the server does not yet serve inflows, releases or water levels).
- **Contract validation** (`src/validate/contracts.py`) also checks the two full page tables: row counts, unique keys, dam IDs, manifest file and SHA-256, Parquet columns and row order, and the Page 1 stock column against `data/storage.csv`.
- `CITATION.cff` abstract and keywords, the `datapackage.json` description, `docs/engineering_notes.md` and `ontology/README.md` (where each mapped column is published) mention the full page tables. KPIs rerun: values identical.
- **Full Page 2 table.** New `data/bulletin_page2.csv` (and `data/parquet/bulletin_page2.parquet`): all 26 columns printed on Page 2 — current water level, storage and usable storage, inflow and withdrawal of the day before, month-to-date inflow (to 2024-04-26) or evaporation (from 2024-04-27), rainfall, capacities, siltation, erosion, spillway discharge and the previous hydraulic year's level, volume, inflow and withdrawal — one row per dam and bulletin, 129,472 rows from 3,983 bulletins. Columns carry the project's canonical names because the extractor names `p2_cote_plan_eau_m` and `p2_volume_actuel_mm3` are previous-year values, not current ones; the current level is `water_level_current_m`. Same accepted extraction as `sources/manifest.csv` (input SHA-256 checked); no value changed, filled or shifted. Built by `src/build_page2_table.py`; `tests/test_bulletin_page2.py` checks it against the KPI input `qa/kpi/inputs/page2.parquet`, KPI K09, `data/capacity_history.csv`, the manifest, and the previous-year semantics (377 of 383 previous-year volumes equal the Page 1 storage of 1 September).
- Page 2 in `datapackage.json`, the data dictionary and the README (summary, quick start with the current water level, repository map, limitations). `docs/known_issues.md`: the January 2021 previous-year values, the July 2022 repeated storage, the unresolved *R.S. (g/l)* column, Mellègue's unextracted *Cote PHE* line and the level/volume behaviour of four small dams. KPIs rerun: K02 19/19, K16 290/290; all other values identical.
- **Full Page 1 table.** New `data/bulletin_page1.csv` (and `data/parquet/bulletin_page1.parquet`): all 15 columns printed on Page 1 — inflow of the day, month and season to date, long-term means, previous-year inflow, release codes, releases (day before, same day one year earlier, month and season to date, previous year), fill %, stock and last year's stock — one row per dam and bulletin, 129,391 rows from 3,981 bulletins. Same accepted extraction as `data/storage.csv` (input SHA-256 checked); no value changed, filled or shifted. Built by `src/build_page1_table.py`; `tests/test_bulletin_page1.py` checks that the stock and fill columns equal `data/storage.csv` and `qa/printed_fill_reference.csv`, that every row points to the Page 1 file of `sources/manifest.csv`, and that every column equals the KPI input `qa/kpi/inputs/page1.parquet`.
- `datapackage.json` registers both files with a description and day rule for every field; data dictionary, README (summary, quick start with the D−1 rule, repository map, limitations) updated. README section 11 now says which Page 2 and Page 3 columns are not yet published.
- KPIs rerun: K02 17/17 resources and K16 216/216 described fields (were 15/15 and 168/168); all other values identical.
- Author name corrected to **Soura Boulaares** in `CITATION.cff`, `LICENSE`, the README and the MCP server package metadata (it was spelled "Boulares").
- README citation section: removed the note about the GitHub "Cite this repository" button.
- Zenodo concept DOI 10.5281/zenodo.23304326 (all versions; 1.1.2 is 10.5281/zenodo.23304327) added to the README (badge and citation section) and to `CITATION.cff`.

## 1.1.2 — documentation and citation — 2026-10-11

- Version 1.1.2 in `CITATION.cff`, `datapackage.json`, `pyproject.toml` and `mcp_server`; KPIs rerun (values identical, receipt updated). First release archived on Zenodo.
- `CITATION.cff`: author affiliations added (Mohamed Hamza Nasfi and Soura Boulares: MUST University, TanitData; Tarek Gasmi: DataDoIt, TanitData). Zenodo copies them into the archive record.
- README: new section 8 "Ask the data with an AI assistant (MCP server)" with example questions, a worked answer (Sidi Salem, 2025-10-10), the 10 October national series, the built-in rules, the tool list and setup for Claude Code and Claude Desktop; the summary table links to it. Later sections renumbered 9–13.
- Internal maintainer notes are no longer published: `CLAUDE.md` was removed from the repository and is ignored by git.

## 1.1.1 — review fixes — 2026-10-11

Fixes for the findings of an independent review of 1.1.0 (F01–F18). No published value changed.

- **MCP server, wrong or misleading answers.** `describe_variable` no longer picks one meaning when a label belongs to several concepts: the two shared Arabic labels (الفارق and المعدل لنفس اليوم للثلاث السنوات الفارطة) return every candidate with its printed columns, in a fixed order, so restarts cannot change the answer (F01). `get_storage` counts days without a bulletin against every bulletin in the manifest and lists bulletins that exist without a Page 1 separately, e.g. Sidi Salem on 2022-05-03 (F03).
- **MCP server, transfers.** `get_transfers` returns both endpoint mapping statuses, the fact id and the Page 3 source file, SHA-256, evidence id and printed text of each row (F11); when filtering by dam, facts that reach the dam only through a candidate crosswalk (Bouhertma→Bou Heurtma, Zayatin→Ziatine) are listed separately and not promoted (F05); every answer states the time rule of the measure asked for (D−1 for `today`, 1 September..D−1 for season totals) and that the stored date is the bulletin date (F06); `limit` must be 1–1000 (`BAD_LIMIT`), with `returned`/`matched`/`truncated` (F08).
- **MCP server, inputs and details.** Dates must be strict `YYYY-MM-DD`; `compare_years` refuses impossible days such as `02-30`; reversed transfer ranges give `BAD_RANGE` (F07). `national_storage` gives the fill numerator, capacity sum and excluded dams, the rounding bound of the printed total, and the known disagreements of 2017-12-30 and 2022-02-09 (KPI K12) and the 2015-10-03..06 roster-scope dates (F13). Dam names: Arabic tatweel is ignored; a longer text that merely contains a dam name is no longer accepted, and `find_dam` reports `match_type` (F14). A missing rdflib now gives `ONTOLOGY_UNAVAILABLE` (F15). Monthly means are exact decimal means rounded half-to-even.
- **Privacy (F02).** Removed a workstation user name and local paths from the executed audit notebook outputs, the QGIS project metadata, the inter-page mismatch receipt and `docs/page3_audit/README.md`; `src/paths.py` no longer contains any machine path (local roots for the logical tokens now come from the `[roots]` table of the untracked config). The git history of `main` was rewritten with the same replacements and force-pushed; authorship is unchanged.
- **Licences (F04, F12).** `LICENSE-DATA` and the README map credit carry the Copernicus WorldDEM-30 / Airbus statements required by the FABDEM v1-2 readme. `CITATION.cff` states the licence of each part and links `LICENSE-DATA`.
- **Descriptor and records (F06, F17).** Both transfer schemas in `datapackage.json` now state that `date` = bulletin date with `SAME_DAY` and how DLO 0.3 dates each measure. `provenance/ENGINEERING_CHANGES.csv` records the descriptor transition from E7 to 1.0.0 and every 1.1.1 file change with SHA-256 before and after. KPIs rerun: all values identical, receipt updated.
- **Tests and documentation (F09, F10, F16, F18).** Ontology tests compare TTL and OWL including blank nodes (graph isomorphism) and read owlrl error messages, each with a self-test that must fail on a broken graph; the two research-QA tests that compared local constants now exercise the production audit functions and the published audit files. New MCP tests cover each fix and run real stdio sessions, including the ambiguous labels under three hash seeds. README describes the five checks as complementary, with their own denominators; the MCP README states exactly what the tests cover; private-project links in `docs/page3_audit/README.md` are marked as such.
- **Versions.** Dataset, code and MCP server share one version: 1.1.1 (`CITATION.cff`, `datapackage.json`, `pyproject.toml`, `mcp_server`).

## 1.1.0 — MCP server — 2026-10-11

- Added `mcp_server/` (`damlevels-mcp` 0.1.0): a read-only Model Context Protocol server over the published tables with ten tools (`dataset_info`, `list_dams`, `find_dam`, `get_storage`, `get_fill`, `national_storage`, `compare_years`, `get_source`, `get_transfers`, `describe_variable`) and three document resources.
- Built-in rules: coverage 2014-07-02..2025-10-10 with `OUTSIDE_RECORD` outside it; missing values reported, never filled or substituted; fill from the capacity regime in force; Page 3 facts flagged `PROBABLE`; flows dated to the day before the bulletin; every answer carries coverage, attribution and caveats.
- `describe_variable` reads the DLO 0.3 ontology to explain French/Arabic/English terms and printed columns with their time rules.
- Added `tests/test_mcp_server.py` (23 tests: tool outputs against the published tables, no-fill and out-of-record rules, ontology lookups, MCP tool listing and error handling); `mcp` added to `requirements-lock.txt`; README updated.

## 1.0.3 — maintainer notes — 2026-10-11

- Added internal maintainer notes (since removed from the published repository).

## 1.0.2 — overview map — 2026-10-11

- Added an overview map to the top of the README (`docs/img/map_dams.png`): the 36 dams coloured by fill on 2025-10-10 (computed with the capacity regime in force that day), sized by reference capacity, with catchments, the 8 river links, mapped transfer routes, background rivers derived from HydroSHEDS and an inset locating the area in Tunisia.
- Added the script that draws it (`src/figures/make_readme_map.py`) and Natural Earth country outlines (`gis/context/naturalearth_countries.geojson`, public domain).
- `LICENSE-DATA`: the map is CC BY-NC-SA 4.0 (it shows the FABDEM/MERIT-derived catchments); HydroSHEDS and Natural Earth credited.

## 1.0.1 — public README and ontology — 2026-10-11

- Rewrote `README.md` for readers outside the project: what the data is, the three bulletin pages with images, how a printed cell becomes a row (with its provenance), how the dataset was built, how to read the time rules, the five checks, source errors, a tested quick start, repository map, limitations, licences and citation.
- Moved the engineering-run sections of the old README to `docs/engineering_notes.md`.
- Added the DamLevels Ontology (DLO 0.3) view in `ontology/` (Turtle and OWL) with a README and three tested SPARQL queries.
- Added bulletin page images to `docs/img/` (1 February 2020 pages 1–3, one Page 1 row, and Page 1 of 2 July 2014).
- `LICENSE-DATA`: `ontology/` is CC BY 4.0; bulletin images fall under the source licence.
- Added `tests/test_ontology.py` (11 tests): TTL/OWL equivalence, documented counts, completeness of observations, mappings, concepts and time rules, no undefined project terms, sample values against `data/storage.csv`, example queries, time dating, and OWL RL consistency. rdflib and owlrl added to `requirements-lock.txt`.

## 1.0.0 — licences settled, publication release — 2026-10-10

- Source values: Licence Nationale de Données Publiques Ouvertes with the DGBGTH/ONAGRI attribution in `LICENSE-DATA`.
- Project tables, QA, provenance, documentation, dam points, transfer network, styles and QGIS project: CC BY 4.0.
- Catchments, incremental catchments and natural network: CC BY-NC-SA 4.0, following FABDEM (CC BY-NC-SA 4.0) and MERIT Hydro (CC BY-NC 4.0 option); declared per resource in `datapackage.json`.
- Code: MIT (`LICENSE`). README notes the PyMuPDF (AGPL-3.0) dependency of the Page 3 extractor.
- README rewritten for public readers; `CITATION.cff` gives author, version 1.0.0 and the source-data reference; package and project version 1.0.0.
- KPI K17 now reports all declared licences settled.

## E7.2 — full rebuild check — 2026-10-10

- Ran `src/build.py` end to end with the portable configuration (bulletin PDFs and lineage inputs on the local drive; V010 ZIP check skipped as not configured). All regenerated QA tables C–G, the four E6A.2 audit samples, the challenge set and correction candidates are identical in content to the accepted files; A1/A2/A3 = YES. Only `generated_utc` differed, so the accepted files were kept.
- Fixed two reproducibility gaps the check exposed: `build.py` now carries the accepted run-scope flags (`production_extractor_rerun`, `satellite_validation_run`, `protected_baseline`) into the regenerated summary, and `build_e6a2.py` orders KPIs A1–A3B before B–H, so `qa/report.md` rows keep their accepted order.
- Reran `qa/kpi/run_kpis.py` (with frictionless 5.19.1) and `make_kpi_figures.py`. All KPI and diagnostic values and exception rows are unchanged except K02 (13/15 → 15/15 resources resolve after restoring `qa/`) and K17 (0/2 → 1/3 licences cleared after the source-data licence was identified). Results, receipt and figures updated.
- `requirements-lock.txt` now records the verified environment, including frictionless.

## E7.1 — bulletin URLs, sample bulletins, source licence — 2026-10-10

- Filled `original_url` in `sources/manifest.csv` for 3,979 of 3,985 bulletins from the ONAGRI listing (https://www.onagri.nat.tn/Situation-des-barrages/fr/19, retrieved 2026-10-10). No other column changed. Matching evidence per date is in the new `sources/original_url_evidence.csv` (2,361 page-hash chain + listing date; 9 hash chain with a differing listing date; 1,609 listing date + server filename; 6 not listed). A sample of 30 links across all classes returned HTTP 200.
- Added two complete bulletins as samples (`sources/samples/2-7-2014.pdf`, `01-02-2020.pdf`), re-downloaded from ONAGRI and byte-identical to the extracted originals, with `sources/samples/README.md`.
- Rewrote `LICENSE-DATA`: source data are reused under the Licence Nationale de Données Publiques Ouvertes with the required DGBGTH/ONAGRI attribution; the project-material licence (proposed CC BY 4.0) and the GIS-layer licence remain open. Updated `datapackage.json`, README, data dictionary and known issues accordingly.

## E7 — repository consistency, current KPIs, portable paths — 2026-10-10

- Restored the engineering QA to `qa/` (all 49 tracked files byte-identical to E6A.2) after an uncommitted move to `qa+powerbi/qa/`; `src/build.py` and `datapackage.json` resolve again (15/15 resources).
- Added the 2026-09-30 KPI recompute as `qa/kpi/` with byte-identical copies of its five staged inputs in `qa/kpi/inputs/`. It supersedes the D, E and B values of the engineering QA and the earlier QA/Power BI package (counter reset on D−1, rounding-aware fill tolerance, above-capacity as diagnostic).
- Updated `docs/known_issues.md`, `docs/data_dictionary.md` and `README.md` to the recompute; added the Ziatine/Gamgoum source swap, the single Masri fill mismatch, the transfer date-semantics note and the geometry limitations.
- Added `src/paths.py` and `config/paths.example.toml`: builders read external inputs from an untracked `config/paths.local.toml` or `DAMLEVELS_*` variables instead of hard-coded `D:\` / `C:\Users\…` paths. The frozen V010 ZIP check runs only where configured.
- Replaced machine-specific roots with logical tokens (`<FULL_RECONSTRUCTION>`, `<V010_REVIEW_PACKAGE>`, `<BULLETIN_CORPUS>`, …) in provenance/path columns of `data/dams.csv`, `provenance/*.csv`, `gis/*.csv`, `datapackage.json`, `sources/samples/SAMPLE_SELECTION.csv`, the Page 1+2 hash registers and the QA reports. No observation value, identifier or SHA-256 changed. Before/after hashes are in `provenance/ENGINEERING_CHANGES.csv` (E7-CHG-*).
- Added the Page 1+2 frozen engines and the Page 3 extractor source to version control (code, config, fixtures register, notebooks; run outputs, databases and fixture PDFs stay ignored), plus `docs/page3_audit/` and `qa/INTERPAGE_MISMATCH_REVIEW/`.
- Added `requirements-lock.txt` for the repository tooling.
- Fixed `validate_repository()` to expect the E6A.2 KPI set (A1, A2, A3, A3B, B–H); it still expected the pooled KPI A and therefore failed on the accepted E6A.2 summary.
- No extractor, scientific pipeline or model was run.

## E6A.2 — design-valid multipage extraction/transcription audit — 2026-09-26

- Added independent-PDF, proportionally stratified primary audits for Page 1 extraction, Page 2 extraction, and Page 3 numeric transcription, with one target cell per sampled PDF.
- Reported Page 1, Page 2, and Page 3 results separately and prohibited a pooled multipage accuracy claim.
- Added a separate categorical Page 3 semantic-mapping review and retained Page 3 `PROBABLE` authority.
- Preserved the original E6A/E6A.1 sample and all B/H, C-G, GIS, and scientific data artifacts byte-for-byte except the intended shared report/summary presentation.
- Clarified that 144 partial-bulletin opportunities without Page 1 sit outside the 143,316 Page 1 completeness denominator.

## E6A.1 — KPI A statistical interpretation correction — 2026-09-25

- Preserved all 1,500 source-cell comparisons, their values, match dispositions, and the descriptive pooled Wilson interval.
- Changed the population-wide >=99.5% decision from `YES` to `INCONCLUSIVE` because unequal stratum allocation and bulletin-level clustering invalidate the simple-binomial inference for that purpose.
- Labeled the work an independent source-cell consistency audit and added a regression guard against automatically promoting a naive pooled interval to a population claim.

## E6A — extraction accuracy, completeness, and temporal plausibility — 2026-09-25

- Added a fixed-seed 1,500-cell source-to-data audit that reads original PDF cell regions directly without invoking the production extractor.
- Quantified governed dam-by-bulletin completeness and continuous-calendar availability without filling missing values.
- Added per-dam contiguous-day median/MAD screening and source-traced representative outliers without correcting accepted observations.
- Extended the shared QA report/JSON with KPIs A, B, and H while preserving C-G counts and all E5 GIS artifacts.

## E5 — GIS/QGIS publication conversion and CRS audit — 2026-09-25

- Exported five lightweight EPSG:4326 GeoJSON layers from the hash-verified R11A final GeoPackage without rerunning watershed delineation.
- Preserved the accepted 35-total / 32-ordinary-incremental-ready scientific state and the explicit Mellègue exclusion.
- Calculated and checked polygon areas in EPSG:32632; all 69 exported polygon records pass the packaging-integrity comparison.
- Logged three topology-preserving, six-decimal precision actions required after coordinate transformation; source geometries and scientific selections remain unchanged.
- Added presentation-only QML styles, an uncompressed relative-path QGIS project, raster/source registries, and GIS integrity tests.

## E4 — professor-style visual acceptance review — 2026-09-25

- Reviewed the repository as a first-version human handoff without rerunning scientific pipelines or changing source values.
- Added deterministic dam, bulletin, storage-lineage, Page 3, and QA-exception review samples under `qa/e4/`.
- Confirmed 12/12 sampled storage rows against local external PDF hashes and unique lineage links.
- Corrected stale E3/E3.1 documentation labels and the post-E3.1 national-disagreement count.
- Preserved all Page 3 qualifications, capacity gaps, draft licenses, source redistribution gates, and E5/E6 scope boundaries.

## E3.1 — national-reconciliation disposition correction — 2026-09-25

- Reclassified 2015-10-03 through 2015-10-06 as evidence-backed `SOURCE_ROSTER_SCOPE_DIFFERENCE` exclusions.
- Preserved component sums, printed totals, residuals, tolerances, and all scientific source values.
- Retained 2017-12-30 and 2022-02-09 as `SOURCE_PRINTED_DISAGREEMENT` cases.
- Updated KPI F to 3,967 eligible, 3,965 pass, 2 fail, and 18 excluded.

## E3 — Pydantic contracts and professor QA C-G — 2026-09-24

- Repackaged `data/storage.csv` as 129,390 primary storage observations only.
- Preserved 84,620 printed percentages with full source provenance in `qa/printed_fill_reference.csv` and a matching Parquet mirror.
- Added Pydantic contracts for dams, capacity regimes, logical bulletins, storage observations, and qualified Page 3 observations.
- Projected 3,981 accepted Page 1 grand-total checksum records into local provenance without rerunning extraction.
- Added reproducible uniqueness, physical-validity, fill-consistency, national-total, and conservative transfer-eligibility checks.
- Generated one JSON result object and its Markdown report from the same QA results.
- Preserved Page 3 as `PROBABLE`, all capacity gaps, unresolved endpoint mappings, and the transfer date-semantics conflict.
- Ran no extractor, watershed, climate, feature, integration, model, GIS, sampling, or satellite-validation pipeline.

## E2 — core data contract — 2026-09-24

- Preserved the E1 physical/path bulletin inventory byte-for-byte as `sources/file_manifest.csv`.
- Built a logical bulletin manifest from accepted Page 1, Page 2, and qualified Page 3 inventories.
- Built tidy storage and non-primary printed-fill observations from the accepted Page 1 delivery with source-cell lineage.
- Built qualified Page 3 physical-edge and accounting observations without promoting Page 3 beyond `PROBABLE`.
- Added matching private CSV/Parquet representations and explicit missingness/capacity-gap records.
- Added the non-filling `capacity_for_date()` helper and expanded the Frictionless data contract.
- Ran no production extractor, scientific pipeline, E3 KPI, or model.

## E1 — repository foundation — 2026-09-24

- Created the private `DamLevels-Data` repository foundation.
- Derived authoritative dam identities, accepted control coordinates, and Page 2 observed capacity regimes from frozen/reconstructed evidence.
- Registered the full external bulletin corpus without copying PDFs.
- Added draft licensing gates, metadata contracts, and QA validation.
- Recorded the V010 `PROJECT_INDEX.csv` bulletin-manifest pointer correction in append-only engineering provenance instead of changing V010.
- Ran no scientific extraction, audit, climate, watershed, feature, or model pipeline.

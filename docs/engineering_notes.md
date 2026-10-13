# Engineering notes

Internal record of how the package was assembled and validated, moved here from the README. Run labels (E1 to E7, R10 to R11A) refer to `CHANGELOG.md` and `provenance/ENGINEERING_CHANGES.csv`.

## E5 GIS publication status

Engineering run E5 packages the accepted composite Task21 spatial state into five lightweight GeoJSON layers and one repository-relative QGIS project. The source is the frozen R11A GeoPackage assembled from R10, the R10A Siliana/incremental correction, the R10B Mellègue decision, and R11/R11A packaging. It contains 36 dam controls, 35 accepted total catchments, 34 incremental geometries (32 ordinary-ready and two special), eight natural controlled-dam edges, and ten artificial-transfer relationships.

Published geometry uses EPSG:4326 with six-decimal coordinates. Area is calculated and checked only in EPSG:32632. Mellègue remains excluded from canonical total and incremental layers; its sensitivity candidates are not promoted. The conversion reruns no watershed delineation and changes no scientific selection.

## E6A.2 status

Engineering run E6A.2 adds separate design-valid audits for Page 1 extraction, Page 2 extraction, Page 3 numeric transcription, and Page 3 semantic mapping while preserving E6A completeness (B), temporal plausibility (H), and accepted checks C through G. The numeric audits use a fixed seed, proportional layout/regime strata, and at most one primary target cell per PDF. They report no pooled Page 1+Page 2+Page 3 accuracy. `data/storage.csv` contains 129,390 primary storage observations for 36 governed dams; all 84,620 independently printed fill percentages remain byte-value-preserved in `qa/printed_fill_reference.csv`.

No production extractor or scientific pipeline was rerun. No model was run. E6A.2 rereads selected original PDF cell regions without calling production parser functions; it does not generate extraction output. This is a computer-assisted source reread using inherited lineage localization, not a human manual audit. Page 3 remains `PROBABLE`, and its transcription result is separate from categorical semantic mapping.

## Source and licence

The data come from the daily bulletins "Situation des barrages" produced by DGBGTH (Ministère de l'Agriculture, des Ressources Hydrauliques et de la Pêche) and published by ONAGRI at <https://www.onagri.nat.tn/Situation-des-barrages/fr/19>. They are reused under the Licence Nationale de Données Publiques Ouvertes, which requires citing the data producer and the date of the data; see `LICENSE-DATA` for the attribution text. `sources/manifest.csv` gives the `original_url` of 3,979 of the 3,985 bulletins used, and `sources/original_url_evidence.csv` records how each link was matched. The bulletins themselves are not redistributed except for two samples in `sources/samples/`.

## Quality indicators (E7)

The current quality indicators are the 2026-09-30 recompute in `qa/kpi/` (`run_kpis.py`, results in `qa/kpi/results/`). It corrects three rules of the earlier automated QA: month- and season-to-date counters reset on the bulletin of D−1's period (bulletin D reports day D−1), the printed-fill tolerance includes the rounding of storage and capacity, and storage above useful capacity is a diagnostic rather than a failure. Headline results: printed fill agrees with storage/capacity for 84,470 of 84,471 eligible rows; all 129,390 storage values are physically possible (finite, ≥ 0); 1.15 % of rows exceed the printed useful capacity (diagnostic D1). The D, E and B values in `qa/qa_summary.json` and `qa/report.md` are kept as the historical engineering record. `qa/kpi/AUDIT_OF_EXISTING_QA.md` explains each change.

## Data conventions

- `dam_id` is a stable governed identifier and never derives from the current spelling.
- `name_fr` preserves the selected governed French/canonical label.
- Arabic labels are included only where the selected Page 3 roster supplies evidence; candidate mappings retain their status.
- Storage and capacity units are million cubic metres (`Mm3`).
- `storage` is the only variable in `data/storage.csv`. `printed_fill_pct` remains a separate non-primary source observation in `qa/printed_fill_reference.csv`.
- Missing values remain absent from the observation table and are recorded in `provenance/storage_missingness.csv`; nothing is interpolated or forward-filled.
- Capacity lookup returns `KNOWN`, `AMBIGUOUS`, or `UNAVAILABLE` and never fills an unresolved interval.
- Basin names are populated only for six dams with explicit official Medjerda-context support. Other basin fields remain blank.
- Page 3 rows remain `PROBABLE`; accounting observations are not represented as physical transfer edges.

## Provenance philosophy

Every published value should point to a source, producer, audit, and version. Corrections append history instead of overwriting it. E1 through E5 derive from frozen reconstruction baseline `<FROZEN_BASELINES>/V010_20260924_1620`; that baseline remains unchanged. Paths to anything outside the repository are recorded with logical root tokens (`<FULL_RECONSTRUCTION>`, `<BULLETIN_CORPUS>`, …) next to SHA-256 values; `config/paths.example.toml` lists the tokens. Accepted E2 remains recoverable as local Git commit `79cbdac`, accepted E3.1 as `81d45d5`, and accepted E4 as `146f1ca`.

## Repository structure

- `sources/manifest.csv` — one logical record per accepted bulletin date.
- `sources/file_manifest.csv` — complete path-level corpus evidence, including duplicates and backups.
- `data/storage.csv` and `data/parquet/storage.parquet` — accepted Page 1 primary storage observations only.
- `data/bulletin_page1.csv` and `data/parquet/bulletin_page1.parquet` — every printed Page 1 column, wide, one row per dam and bulletin (`src/build_page1_table.py`).
- `data/bulletin_page2.csv` and `data/parquet/bulletin_page2.parquet` — every printed Page 2 column, wide, canonical column names (`src/build_page2_table.py`).
- `provenance/RELEASE_ASSETS.csv` — cell-lineage files of the two wide tables, attached to the GitHub release because they exceed the 50 MB file limit; SHA-256, size and join keys.
- `data/transfers.csv` and `data/parquet/transfers.parquet` — qualified Page 3 edge/accounting facts.
- `data/dams.csv` and `data/capacity_history.csv` — stable identities, selected metadata, and dated capacity evidence.
- `gis/vector/` — five lightweight EPSG:4326 publication layers derived from the accepted R11A GeoPackage.
- `gis/styles/` and `gis/project/DamLevels-Data.qgs` — presentation-only styles and an uncompressed relative-path QGIS project.
- `gis/GIS_SOURCE_AUTHORITY.csv` and `gis/RASTER_MANIFEST.csv` — spatial authority and external raster metadata; no provider raster is committed.
- `src/validate/` — Pydantic row models, date-aware capacity lookup, and QA C-G implementations.
- `qa/printed_fill_reference.csv` — separately packaged printed percentages with full E2 provenance.
- `qa/kpi/` — current quality indicators (2026-09-30 recompute), their inputs, exception rows, DQV export and run receipt.
- `qa/` — generated A-H engineering tables, shared JSON/Markdown summary, and validation receipts.
- `qa/INTERPAGE_MISMATCH_REVIEW/` — inter-page mismatch review with evidence.
- `src/extract/DAM_DATA_PIPELINE_page1and2/` — frozen Page 1 (`page1-authoritative-0.2.3`) and Page 2 (`page2-authoritative-1.0.0`) engines with orchestration, build/audit notebooks, fixtures and dependency lock. Run outputs stay outside git.
- `src/extract/page3_extractor/` — Page 3 extractor `1.2.0rc2`.
- `src/paths.py`, `config/paths.example.toml` — locations of external inputs (copy to `config/paths.local.toml`, which is not tracked).
- `docs/page3_audit/` — Page 3 field and measure dictionaries and semantics.
- `qa/extraction/` — E6A.2 Page 1, Page 2, and Page 3 samples, separate accuracy results, semantic dispositions, sampling design, and noninferential challenge set.
- `qa/e4/` — deterministic human-review samples, acceptance checklist, repository tree, and E4 report.
- `qa/gis/` — E5 CRS, stable-ID, geometry, area, QGIS, and raster-disposition checks.
- `docs/` — data dictionary and known limitations.
- `provenance/` — append-only engineering changes.

## Current authority limitations

Page 3 remains qualified/probable in the frozen baseline. E3.1 retains capacity-bound, fill-consistency, and printed-national-total review cases without changing source values; the E7 recompute reclassifies the capacity and fill cases (see Quality indicators). Direct Page 3 transfer balance is not numerically eligible because endpoint, counterpart, source-consistency, and effective-date requirements are not all established. Bulletin redistribution and the earlier reconstruction gaps remain unresolved.

## Validate the current contract

```powershell
Copy-Item config/paths.example.toml config/paths.local.toml   # then edit the local paths
pip install -r requirements-lock.txt
$env:PYTHONPATH = "src"
python src/build.py
python qa/kpi/run_kpis.py
```

`build.py` validates Pydantic/table contracts, preserves the historical E6A/E6A.1 audit and accepted B/H results, regenerates C-G from accepted repository tables, and regenerates the separate E6A.2 multipage audits (satellite KPI I remains excluded). It does not invoke the production extractors or rebuild scientific outputs. It needs the bulletin PDFs and the E6A.2 lineage inputs listed in `config/paths.example.toml`. The frozen V010 ZIP hash check runs only when `v010_review_zip` is configured; otherwise `build.py` reports it as skipped. `run_kpis.py` recomputes the current quality indicators from repository files only.

Open `gis/project/DamLevels-Data.qgs` in QGIS 3.44 or later to inspect the accepted spatial package. See `docs/gis.md` before interpreting incremental or network layers.

## Current review boundary

The current repository is ready for human review with explicit gaps. E6A.2 supplies separate Page 1, Page 2, and Page 3 transcription results and a categorical Page 3 semantic audit. No E6A.2 row is claimed as human-visual verification. Satellite validation and any governed scientific-value correction remain future work.

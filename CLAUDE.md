# CLAUDE.md

Guidance for working in this repository. Read it before changing any file.

## What this project is

DamLevels-Data reconstructs the daily state of Tunisia's 36 large dams (2 July 2014 – 10 October 2025) from the DGBGTH bulletins *Situation des barrages* published as PDFs by ONAGRI. It is a **published dataset first and a codebase second**: the tables in `data/`, their provenance and their QA results are the product. Code exists to produce, validate and explain them.

- Public repository: https://github.com/tanitdata/DamLevels-Data (public, default branch `main`).
- Audience of `README.md`: internet users (researchers, journalists, citizens), not developers. Keep it plain, concrete and illustrated. Engineering detail goes in `docs/engineering_notes.md`.
- Values are read from the PDF text layer and drawn table lines by deterministic engines. **There is no OCR anywhere in this project**; if any text claims otherwise, it is a documentation error.

## Repository map

| Path | Contents |
|---|---|
| `data/storage.csv` (+ `data/parquet/`) | 129,390 daily storage observations (Mm³), long format, one row per `dam_id` × `date`, with `source_file`, `source_sha256`, `page`, `lineage_id`, `flag` |
| `data/dams.csv`, `data/capacity_history.csv` | 36 dams (stable `dam_id`, FR/AR names, coordinates) and dated capacity regimes |
| `data/transfers.csv` | 47,556 Page 3 transfer facts, authority `PROBABLE` |
| `sources/` | `manifest.csv` (every bulletin: ONAGRI URL, per-page SHA-256), `original_url_evidence.csv`, `file_manifest.csv`, two sample PDFs in `samples/` |
| `provenance/` | cell-level lineage, missingness, append-only `ENGINEERING_CHANGES.csv` |
| `qa/` | engineering QA (C–G, E6A.2 audits) and the current indicators in `qa/kpi/` |
| `gis/` | `vector/` (5 GeoJSON layers, EPSG:4326), `styles/`, `project/` (QGIS), `context/` (Natural Earth outlines) |
| `ontology/` | DamLevels Ontology DLO 0.3 view (TTL/OWL) and example SPARQL queries |
| `docs/` | `data_dictionary.md`, `known_issues.md`, `gis.md`, `engineering_notes.md`, `img/` |
| `src/extract/` | frozen extraction engines: `DAM_DATA_PIPELINE_page1and2/` (Page 1 `page1-authoritative-0.2.3`, Page 2 `page2-authoritative-1.0.0`) and `page3_extractor/` (`1.2.0rc2`) |
| `src/` | `build.py` (QA regeneration + contract validation), historical builders `build_e2.py`, `build_e3.py`, `build_e6a*.py`, `validate/` (Pydantic contracts, capacity lookup, QA), `gis/`, `figures/`, `paths.py` |
| `tests/` | pytest suite (76 tests, including `test_ontology.py` and `test_mcp_server.py`) |
| `mcp_server/` | read-only MCP server (`damlevels_mcp`): `core.py` holds all query logic and the data rules, `ontology.py` the DLO lookups, `server.py` only registers tools/resources |
| `datapackage.json` | Frictionless descriptor of every resource and field, with per-resource licences |

## Commands

Run from the repository root. Python 3.11+ (verified on 3.14.3); pinned versions in `requirements-lock.txt`.

```bash
pip install -r requirements-lock.txt

python -m pytest -q                                   # full test suite (53 tests); needs nothing outside the repo

PYTHONPATH=src python -c "from pathlib import Path; from validate.contracts import validate_repository; print(validate_repository(Path('.')) or 'OK')"
                                                      # contract validation only; needs nothing outside the repo

python qa/kpi/run_kpis.py                             # recompute current quality indicators (~15 s); writes qa/kpi/results/
python qa/kpi/make_kpi_figures.py                     # KPI figures, after run_kpis.py

PYTHONPATH=src python src/build.py                    # regenerate QA C-G + E6A.2 audits, then validate (~4 min)
                                                      # needs config/paths.local.toml (bulletin PDFs, lineage inputs)

python src/figures/make_readme_map.py [--rivers PATH] # redraw docs/img/map_dams.png

pip install -e "mcp_server[ontology]"                 # MCP server; then `python -m damlevels_mcp` (stdio)
```

MCP server rules: keep new logic in `mcp_server/damlevels_mcp/core.py` (testable without MCP) and register it in `server.py`. Every tool must stay read-only, return `_envelope(...)` (coverage + attribution + notes), refuse dates outside 2014-07-02..2025-10-10 with `OUTSIDE_RECORD`, never fill or substitute missing values, and get a test in `tests/test_mcp_server.py` that compares its output with the published tables. There is no data after 2025-10-10.

On Windows PowerShell use `$env:PYTHONPATH = "src"` instead of the `PYTHONPATH=src` prefix.

External inputs (bulletin PDFs, run outputs, rasters) are never hard-coded. Builders resolve them through `src/paths.py` from an **untracked** `config/paths.local.toml` (copy `config/paths.example.toml`) or `DAMLEVELS_<KEY>` environment variables. Paths written into published files use logical root tokens (`<FULL_RECONSTRUCTION>`, `<BULLETIN_CORPUS>`, `<TASK21>`, …), never drive letters.

## Rules that protect the data

These are the project's invariants. Breaking one silently corrupts the published record.

1. **Never change a published value.** Observation values, identifiers and SHA-256 columns in `data/`, `sources/`, `provenance/` and `qa/printed_fill_reference.*` are frozen. Source errors are documented in `docs/known_issues.md`, never repaired in the data (e.g. the Ziatine/Gamgoum season-to-date swap, 2017–2021, stays as printed).
2. **Bytes are part of the contract.** `.gitattributes` is `* -text`: files are stored byte-for-byte because SHA-256 values in provenance, receipts and validators refer to exact bytes (e.g. `sources/file_manifest.csv` must hash to `2debc06e…`). Never normalise line endings or re-save CSVs with a different writer. After touching data files, run the tests and contract validation.
3. **Join on `dam_id`, never on names.** Names vary between bulletins and between French and Arabic.
4. **Join by key, never by row position.** An earlier integrated table attached rainfall by position and put 131,729 of 131,736 values on the wrong row.
5. **Unknown stays unknown.** Missing values are absent rows (recorded in `provenance/storage_missingness.csv`), never zero, never interpolated or forward-filled. Capacity lookup returns `KNOWN`, `AMBIGUOUS` or `UNAVAILABLE` and never fills a gap.
6. **Respect the time rules** (`ontology/`, `docs/data_dictionary.md`):
   - stock, level, fill on bulletin D → state on day D;
   - inflow, release, transfer, evaporation on bulletin D → amount over day D−1;
   - month-to-date counters restart on the bulletin of the 2nd; season counters run from 1 September and restart on the bulletin of 2 September;
   - `p1_release_today` is the release on the same day **one year earlier**; the current release is `p1_release_yesterday`;
   - storage above the printed useful capacity is a diagnostic (flood surcharge), not an error.
7. **Page 3 stays `PROBABLE`.** Do not promote transfer facts or resolve the candidate crosswalks (Bouhertma→Bou Heurtma, Zayatin→Ziatine) without new evidence.
8. **The current quality indicators are `qa/kpi/`.** The D, E and B values in `qa/qa_summary.json` / `qa/report.md` use superseded rules and are kept only as history. Quote numbers from `qa/kpi/results/KPI_RESULTS.csv`.
9. **Every number in prose must be checkable.** Before writing a figure into the README or docs, compute it from the repository files.

## Recording changes

- Add an entry at the top of `CHANGELOG.md` for every change (version heading, date, what changed and why).
- Any change to a data, provenance, GIS-registry or descriptor file gets a row in `provenance/ENGINEERING_CHANGES.csv` with SHA-256 before and after. Corrections append history; they do not overwrite it.
- Keep `README.md`, `docs/data_dictionary.md`, `docs/known_issues.md` and `datapackage.json` consistent with each other.

## Licences

Do not change licence terms without the project owners' decision.

| Material | Licence |
|---|---|
| Source values (DGBGTH via ONAGRI), sample bulletins, bulletin images | Licence Nationale de Données Publiques Ouvertes — attribution to DGBGTH/ONAGRI required (text in `LICENSE-DATA`) |
| Tables, QA, provenance, docs, ontology, dam points, transfer network, styles, QGIS project | CC BY 4.0 |
| `gis/vector/catchments*.geojson`, `natural_network.geojson`, `docs/img/map_dams.png` | CC BY-NC-SA 4.0 (derived from FABDEM and MERIT Hydro) |
| `gis/context/` | Natural Earth, public domain |
| Code (including `mcp_server/`) | MIT (`LICENSE`); the Page 3 extractor imports PyMuPDF (AGPL-3.0) |

Never commit: the bulletin corpus (only the two documented samples), provider rasters (MERIT Hydro, FABDEM, JRC), HydroSHEDS-derived river data, SQLite run databases, `config/paths.local.toml`, or any absolute local path, personal email or credential.

## Git conventions

- Branch: `main`. The repository is public; history is shown to everyone.
- Commit as **tarekddoit** (`272937070+tarekddoit@users.noreply.github.com`). Do **not** add a `Co-Authored-By: Claude` trailer or any AI attribution to commits or pull requests in this repository.
- Authors of the work (in `CITATION.cff` and `LICENSE`): Mohamed Hamza Nasfi, Soura Boulares, Tarek Gasmi. Do not change them.
- No file over 50 MB in git; large outputs belong in release assets.
- Run `python -m pytest -q` before every commit; do not force-push `main` without the owners' explicit agreement.

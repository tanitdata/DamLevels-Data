# GIS publication contract

## Authority

The spatial authority is composite and use-specific. The immutable E5 source is:

`<FULL_RECONSTRUCTION>/geospatial/final/TASK21_FINAL_WATERSHEDS.gpkg` (see `config/paths.example.toml` for root tokens)

SHA-256: `006b0c93dc8c8afb0b6ef6661a67bcc8061e628f17f6cc2afe17c76aa8a2850e`

R10 produced the controls, most accepted totals, reservoir evidence, and network layers. R10A replaced the Siliana geometry with its accepted producing set and produced the incremental layer. R10B retained Mellègue as an external-evidence exclusion. R11 assembled the scientific package, and R11A transplanted the incremental layer and froze the final package without changing accepted-total science.

E5 converts this package for publication. It does not rerun delineation, select a different geometry, or repair the scientific source.

## Publication layers

| File | Meaning | Features | Qualification |
|---|---|---:|---|
| `gis/vector/dams.geojson` | Accepted physical control points | 36 | Control-status warnings remain attributes. |
| `gis/vector/catchments.geojson` | Accepted topographic total catchments | 35 | Mellègue has no canonical accepted total and is absent. |
| `gis/vector/catchments_incremental.geojson` | Accepted incremental/local geometries | 34 | 32 are ordinary-ready. Sidi Saad and Sidi Aïch are present as special cases. Mellègue and Sidi Salem are absent. |
| `gis/vector/natural_network.geojson` | Controlled-dam natural receiver topology | 8 | This is not a complete river network. Mellègue/Sidi Salem network use remains blocked. |
| `gis/vector/transfer_network.geojson` | Typed artificial or engineered relationships | 10 | Four conceptual records deliberately have null geometry. Lines do not establish operational timing or discharge. |

Each dam-associated feature uses the governed `dam_id` from `data/dams.csv`. Names are labels, never join keys. Non-dam transfer sources retain their named system/entity and a blank `from_dam_id`; they are classified `NOT_APPLICABLE`, not forced into the dam registry. Candidate Page 3 crosswalks are not promoted.

## CRS and coordinate precision

The accepted source GeoPackage uses **EPSG:32632 (UTM zone 32N)**. Publication geometry uses **EPSG:4326** and coordinates rounded to six decimal places.

Area is never calculated in EPSG:4326. E5 calculates source and output-integrity areas in EPSG:32632 and records the comparison in `qa/gis/area_integrity.csv`. Area agreement is an integrity check only; it did not select or accept a watershed.

Naive six-decimal rounding made three transformed incremental polygons invalid. E5 therefore applied Shapely `set_precision(..., mode="valid_output")` on a 0.000001-degree grid to those three publication copies. The operation is packaging-only and is fully recorded with source, intermediate, and final WKB hashes in `qa/gis/geometry_packaging_actions.csv`. The EPSG:32632 source geometries remain unchanged and valid. No `buffer(0)` or unrecorded repair was used.

`qa/gis/crs_inventory.csv` records source/output CRS, geometry type, counts, bounds, missing geometry, and validity. All selected layers pass a coarse Tunisia-region coordinate envelope check. Exact national-boundary containment remains `NOT_EVALUATED_NO_AUTHORITATIVE_BOUNDARY_GEOMETRY`; the coarse check must not be cited as a geopolitical containment test.

## Total and incremental meaning

There are 35 accepted total climate domains. Mellègue remains `EXCLUDED_EXTERNAL_EVIDENCE`; neither its MERIT nor FABDEM sensitivity candidate is published as a canonical catchment.

There are 34 incremental geometries. Thirty-two are ordinary incremental-ready. The Sidi Saad and Sidi Aïch geometries retain special/upstream-blocker status and must not be treated as ordinary model-ready domains. Sidi Salem has an accepted total but no final incremental geometry because its ordinary incremental/network status depends on the unresolved Mellègue system.

## Natural and artificial connectivity

`natural_network.geojson` contains eight explicit immediate-downstream controlled-dam edges. It is a governed dam graph, not the HydroRIVERS network.

`transfer_network.geojson` contains ten typed artificial or engineered relationships. Six have schematic geometry. Four are documented conceptual relationships with null geometry; E5 preserves the missing geometry instead of inventing a line. The layer does not establish hydraulic travel time, effective date, operating state, or measured flow.

## Styles and QGIS project

No authoritative QGIS style or project was present in the accepted production package. E5 therefore created five minimal styles under `gis/styles/`, each explicitly marked `PRESENTATION_ONLY`. Colors and line patterns encode no new scientific classification.

Open the uncompressed project:

`gis/project/DamLevels-Data.qgs`

The project CRS is EPSG:4326. All five layer data sources are repository-relative (`../vector/...`). The project contains no absolute drive paths, user-profile paths, credentials, or connection strings. QGIS 3.44.12 loaded the project and resolved the `Dam controls` layer during E5 validation.

## Raster policy

No provider raster is committed. `gis/RASTER_MANIFEST.csv` records the targeted MERIT Hydro DIR/UPA, FABDEM v1.2, and JRC Global Surface Water occurrence families that support the accepted lineage. E5 inspected their local metadata and produced aggregate manifest hashes from sorted filename, size, and per-file SHA-256 entries.

These sources are technically convertible to Cloud-Optimized GeoTIFF using GDAL, but no COG was created because they are upstream provider sources rather than a DamLevels publication raster and redistribution remains under license review. Their bytes remain external.

## Rebuild the publication package

The conversion script requires the accepted GeoPackage and final Task21 registry as external inputs:

```powershell
python src/gis/build_publication_gis.py `
  --repo-root . `
  --source-gpkg <path-to-TASK21_FINAL_WATERSHEDS.gpkg> `
  --task21-registry <path-to-TASK21_FINAL_REGISTRY_36.csv>
```

Create the QGIS project with the installed QGIS Processing executable:

```powershell
qgis_process run src/gis/create_qgis_project.py --
```

The conversion script refuses a source GeoPackage whose SHA-256 differs from the frozen R11A artifact. It reads and exports accepted geometry only; it contains no watershed delineation algorithm.

## Validation records

- `gis/GIS_SOURCE_AUTHORITY.csv`
- `gis/RASTER_MANIFEST.csv`
- `qa/gis/crs_inventory.csv`
- `qa/gis/dam_id_crosswalk_audit.csv`
- `qa/gis/area_integrity.csv`
- `qa/gis/geometry_packaging_actions.csv`
- `qa/gis/gis_summary.json`
- `qa/gis/E5_GIS_VALIDATION_REPORT.md`


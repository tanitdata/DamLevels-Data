# E5 GIS / QGIS validation report

**Decision:** `YES_WITH_EXPLICIT_GAPS`

E5 packages the previously accepted Task21 spatial state for repository review. It does not rerun delineation, select new watersheds, alter dam identities, or change accepted scientific tables. The accepted E4 commit is `146f1ca54c68b6340dceb487cb8b27fd472a9c41`; the frozen V010 ZIP still hashes to `303673e8b342572dff807797355e15cdea9a39325e6083931b31d5f6c783c9d0`.

## Selected source authority

The selected source is `<FULL_RECONSTRUCTION>/geospatial/final/TASK21_FINAL_WATERSHEDS.gpkg`, SHA-256 `006b0c93dc8c8afb0b6ef6661a67bcc8061e628f17f6cc2afe17c76aa8a2850e`. Authority is use-specific and composite:

- R10 supplies controls, most total catchments, natural connectivity, artificial-transfer relationships, reservoir evidence, and special-hydrology zones.
- R10A supplies the accepted Siliana correction and the incremental-catchment layer.
- R10B preserves the Mellègue audit and exclusion decision. Neither Mellègue candidate is canonical.
- R11 assembles and freezes the accepted package.
- R11A performs the final package/incremental transplant without changing the scientific decision.

The detailed disposition of all nine source layers is in `gis/GIS_SOURCE_AUTHORITY.csv`. Superseded R05/R06/R08 geometries were not promoted.

## CRS and output inventory

All nine inspected source layers declare `EPSG:32632`. No layer has a missing or mixed CRS, and no CRS was assigned by inference. Source and output details, bounds, geometry types, and validity are in `qa/gis/crs_inventory.csv`.

| Publication layer | Features | Geometry | Publication CRS | Missing geometry | Invalid geometry |
|---|---:|---|---|---:|---:|
| `dams.geojson` | 36 | Point | EPSG:4326 | 0 | 0 |
| `catchments.geojson` | 35 | MultiPolygon | EPSG:4326 | 0 | 0 |
| `catchments_incremental.geojson` | 34 | MultiPolygon | EPSG:4326 | 0 | 0 |
| `transfer_network.geojson` | 10 | LineString / null | EPSG:4326 | 4 | 0 |
| `natural_network.geojson` | 8 | LineString | EPSG:4326 | 0 | 0 |

The four null transfer geometries are preserved source states for typed relationships with no accepted line geometry. They are not conversion failures. All published coordinates are rounded to six decimal places. A coarse Tunisia-region envelope check passes. Exact national-boundary containment is recorded as `NOT_EVALUATED_NO_AUTHORITATIVE_BOUNDARY_GEOMETRY`; no boundary was invented for this check.

## Stable dam identifiers

All dam-associated public features use the stable `dam_id` values from `data/dams.csv`. The crosswalk audit contains 141 associations: 135 `MATCHED`, six `NOT_APPLICABLE` external/non-dam source entities, zero `UNRESOLVED`, and zero `CANDIDATE_ONLY`. No Page 3 candidate crosswalk was promoted. See `qa/gis/dam_id_crosswalk_audit.csv`.

## Geometry validity and publication precision

All source geometries selected for publication are valid. Direct coordinate rounding to six decimals made three transformed incremental geometries invalid. E5 therefore applied Shapely `set_precision` with a `0.000001` degree grid and `valid_output` mode to the publication copies of Bou Heurtma, Siliana, and Sidi Saad. No source geometry was altered, no `buffer(0)` operation was used, and scientific selection did not change. Before/after WKB hashes and validity states are recorded in `qa/gis/geometry_packaging_actions.csv`.

## Area integrity

Areas are calculated only after transformation to `EPSG:32632`; published geometry remains in `EPSG:4326`. All 69 total/incremental comparisons pass the six-decimal packaging-rounding integrity rule. The largest absolute difference between source and publication-roundtrip area is `0.000846120129 km²`. Area agreement was used only as an integrity check, never to select a watershed. See `qa/gis/area_integrity.csv`.

## Preserved scientific state

- 35 total domains remain accepted for the supported use.
- 34 incremental geometries are published: 32 ordinary incremental-ready domains plus the qualified Sidi Saad and Sidi Aïch special cases.
- Mellègue has no accepted canonical total or incremental catchment and is absent from both public catchment layers.
- Sidi Salem has no accepted incremental catchment.
- The natural layer contains eight controlled-dam relationships and is not a complete river network.
- The artificial layer contains ten typed relationships; operational timing and discharge are not established by this geometry layer.

## QGIS project and styles

`gis/project/DamLevels-Data.qgs` is an uncompressed QGIS 3.44.12 project in `EPSG:4326`. It loads the five publication layers using relative paths under `../vector/`. A QGIS Processing load check completed successfully. XML inspection found no `C:\`, `D:\`, user-profile paths, passwords, database connection strings, or tokens; every non-empty datasource resolves within the repository.

No accepted authoritative QML or QGIS project was found in the targeted source material. The five QML files created in E5 are explicitly marked `PRESENTATION_ONLY` and do not encode scientific classes.

## Raster disposition

`gis/RASTER_MANIFEST.csv` describes four accepted input families covering 33 external files: MERIT Hydro direction, MERIT Hydro upstream area, FABDEM v1.2, and JRC Global Surface Water occurrence. Their source CRS, resolution, size, aggregate manifest hash, and external path are recorded. No raster bytes or provider archives were copied into Git. No COG was created because redistribution remains `LICENSE_REVIEW_REQUIRED`; the inspected TIFF families are technically convertible without changing values.

## Verification

- Protected E4 data tables, source manifests, and C–G QA outputs are unchanged from the accepted E4 commit.
- Source GeoPackage and V010 ZIP hashes match the recorded values.
- Five public GeoJSONs parse, use `EPSG:4326`, preserve expected counts, and pass validity checks.
- The project has five resolvable relative datasources and passes a QGIS load check.
- No public Git remote is configured.
- No scientific pipeline, extractor, watershed delineation, climate process, integration, feature process, or model ran.
- No secrets or bulky source rasters were added.
- Test result: **23 passed**. The single pytest warning concerns inability to create its local cache directory and does not affect test execution.

## Explicit gaps

**Packaging gaps:** styles are presentation-only; four artificial relationships lack line geometry by design; external rasters have not been converted to COGs while publication rights are gated.

**Unavailable metadata:** exact Tunisia-boundary containment was not evaluated because the accepted source contract contains no authoritative boundary; raster redistribution status remains under review.

**Scientific watershed issues:** Mellègue remains excluded; Sidi Saad and Sidi Aïch remain qualified special incremental cases; Sidi Salem has no accepted incremental domain and its network use remains blocked. E5 preserves these states and does not attempt to resolve them.

## Acceptance answer

**DO THE REPOSITORY GIS PRODUCTS NOW SATISFY THE PROFESSOR'S QGIS/GIS PUBLICATION REQUIREMENTS?**

`YES_WITH_EXPLICIT_GAPS`

The vector package, stable identifiers, CRS handling, area calculations, relative-path QGIS project, styles, raster manifest, and provenance are suitable for review. The stated gaps remain visible and do not represent hidden conversion failures.

# E1 validation report

**Status: PASS WITH EXPLICIT METADATA GAPS**

## Scope and preservation

- Repository: `<REPO>`
- Frozen authority: `<FROZEN_BASELINES>/V010_20260924_1620`
- V010 files hash-compared before/after: **9**
- V010 unchanged: **YES**
- V010 review ZIP SHA-256: **303673e8b342572dff807797355e15cdea9a39325e6083931b31d5f6c783c9d0**
- Scientific pipelines run: **NO**
- Models run: **NO**
- Production database/Parquet/raster copied: **NO**
- Source PDF bytes copied: **NO**
- Public remote configured during E1: **NO**
- Local Git repository initialized on branch `main`: **YES**

## Counts

- Governed dams: **36**
- Unique `dam_id`: **36**
- Dams with accepted control coordinates: **36**
- Dams with Arabic label evidence: **15**
- Capacity-history records: **60**
- Dams with current capacity regime: **36**
- Bulletin manifest path records: **31843**
- Local manifest paths present at E1 validation: **31843**
- Representative sample candidates: **5**

## Contract checks

- Required directories/files: generated; final repository check follows this report creation.
- CSVs: standard-library parse completed during build; all six E1 CSVs also parsed successfully with `@oai/artifact-tool` after generation.
- `datapackage.json`: parsed successfully and lists only `dams`, `capacity-history`, and `bulletin-manifest`.
- SHA-256 strings: all 31843 bulletin rows match lowercase 64-hex syntax.
- Dam IDs: unique and governed; no IDs were derived from current spelling.
- Coordinates: numeric and in valid WGS84 ranges.
- Capacity: dated durable observed regimes; transient/alternating conflicts are not silently promoted.
- License: draft/pending language is explicit.

## Selected-source integrity

Current source hashes match the frozen review-clone registries where recorded:

- Governed alias register: `aff3b38b3bf42b3b3d059dccd33857affe4ddc173ccff3b5aa00f851c33324dc`
- Task21 final registry: `7205196aee553209282ef209c732487a1fa505aaf3054e1f5ae9909855b8eabc`
- Page 3 Arabic roster: `3fd90cbc676a83607a3f7eda67f729d89263ea812fdfa76ac67247ba794f6ce6`
- Accepted Task21 GeoPackage: `006b0c93dc8c8afb0b6ef6661a67bcc8061e628f17f6cc2afe17c76aa8a2850e`
- Page 2 observations: `ec1c1002ecf5d3c6a9e3ad29a52273870fb4d5e774669c6e6ab0284a9b6d22b5`
- Frozen bulletin manifest: `2a71bc834a930adc75dd3be7890e84dda0ae924034bd37d440bab6588058138e`

All were read in place. No selected source file was written or replaced.

## Unresolved metadata

- Hydrographic basin names: unresolved for all 36 dams in selected E1 sources.
- Current Page 2 capacity absent for: none.
- Arabic names: evidence available for 15/36; remaining labels are blank.
- Bulletin original URLs and unsplit page counts: unresolved.
- Redistribution/publication approval: unresolved.
- Brek/Lakhmess transition intervals and Kebir/Moula/Rmel contradictory printed episodes: retained as explicit capacity-history limitations.

# E2 validation report

**Status: PASS WITH EXPLICIT GAPS**

## Scope and preservation

- Repository: `<REPO>`
- Frozen authority: `<FROZEN_BASELINES>/V010_20260924_1620`
- V010 unchanged: **YES**
- V010 review ZIP SHA-256: **303673e8b342572dff807797355e15cdea9a39325e6083931b31d5f6c783c9d0**
- Scientific extraction or audit pipelines run: **NO**
- Models run: **NO**
- E3 KPI or derived-quality calculation run: **NO**
- Source PDF bytes copied: **NO**
- Production database, raster, GeoPackage, NetCDF, or HDF copied: **NO**
- Public remote configured: **NO**
- Secret-pattern scan: **NO MATCHES**

E2 is an engineering projection of accepted source products into the public-data contract. It does not change their scientific algorithms or authority.

## Bulletin identity and manifests

- Logical bulletin dates: **3,985**
- Complete Page 1 + Page 2 + Page 3 dates: **3,962**
- Partial logical bulletin dates: **23**
- Page 1 dates: **3,981**
- Page 2 dates: **3,983**
- Page 3 dates: **3,963**
- Multiple accepted sources for one page/date: **0**
- Accepted source/hash pairs unmatched to the physical inventory: **0**
- Physical file-manifest rows: **31,843**
- Uncanonicalized physical-file rows: **3,270**

`sources/file_manifest.csv` is byte-identical to the E1 manifest. Its SHA-256 is **2debc06e3532edaca2b2d78bb30f8933d0b41a4e85fe835817b226aced9ebb14**. `sources/manifest.csv` is the new logical bulletin-date manifest; the two registries have distinct contracts.

Two Page 3 source filenames disagree with the accepted canonical date and remain explicitly annotated: `28-9-2019_3.pdf` maps to 2019-09-29 and `29-9-2019_3.pdf` maps to 2019-09-30.

## Storage contract

- Total tidy rows: **214,010**
- Primary storage observations: **129,390**
- Printed-fill observations: **84,620**
- Governed dams: **36**
- Date range: **2014-07-02 through 2025-10-10**
- Emitted observations with unique lineage links: **214,010 / 214,010**
- Additional retained nonnumeric source state: **1** (`#N/A`, Barbara, 2017-01-27)
- Explicit missing source occurrences: **44,772**

Storage and printed fill remain separate observations. No value was interpolated. The one nonnumeric storage state was not emitted as a numeric observation; its raw state and source-cell lineage remain in the provenance tables.

## Transfer and accounting contract

- Selected Page 3 facts: **47,556**
- Date range: **2014-07-02 through 2025-10-10**
- Authority on every row: **PROBABLE**

Semantic categories:

- Probable physical edge with unresolved dam crosswalk: **23,778**
- Probable physical transfer edge: **11,889**
- Probable accounting observation, not a hydraulic edge: **11,889**

Value states:

- Present numeric: **38,105**
- Present zero: **5,370**
- Structurally not expected: **4,026**
- Source blank: **55**

Only confirmed stable-ID crosswalks are populated for Barbara, Sidi El Barrak, and Sejnane. Bouhertma→Bou Heurtma and Zayatin→Ziatine remain candidate mappings, so E2 preserves the Page 3 node identifier and leaves the corresponding stable dam endpoint blank. Accounting observations remain distinct from physical transfer edges.

## Dam and capacity metadata

- Dam IDs: **36 unique / 36 rows**
- Arabic labels missing: **21**
- Basin values missing: **30**
- Basin values added with explicit Medjerda evidence: **6**
- Explicit capacity-unavailable intervals: **3**

Capacity-unavailable intervals:

| Dam | From | Through | Storage observations affected |
|---|---:|---:|---:|
| Brek | 2020-09-24 | 2020-12-06 | 74 |
| Lakhmess | 2020-06-10 | 2020-08-30 | 75 |
| Mellègue | 2015-06-18 | 2015-06-18 | 0 |

`capacity_for_date` reports `KNOWN`, `AMBIGUOUS`, or `UNAVAILABLE`; it does not forward-fill evidence gaps. The direct known/gap/unknown-dam tests pass.

## Representation and format validation

- All **13** repository CSV files parse with the Python standard library.
- Compact CSVs parse fully with the spreadsheet artifact validator.
- Deterministic 10,000-row samples of both large data CSVs parse with the spreadsheet artifact validator.
- Full storage and transfer CSVs were streamed end to end during contract validation.
- Storage CSV/Parquet row counts and ordered observation IDs agree: **PASS**.
- Transfer CSV/Parquet row counts and ordered fact IDs agree: **PASS**.
- All selected Python source files parse: **7 / 7**.
- JSON, TOML, and YAML metadata parse: **PASS**.
- `datapackage.json` lists the E2 CSV and Parquet resources and parses: **PASS**.

## Source evidence and output hashes

Selected accepted-source hashes:

- Page 1 observations: `91e8373f36ff68b2080f54762ea9d15c041d3f9b45b21768d9b694168939ac85`
- Page 2 observations: `ec1c1002ecf5d3c6a9e3ad29a52273870fb4d5e774669c6e6ab0284a9b6d22b5`
- Page 1 value lineage: `8a423c44945f6e1113641a143370c7d6740f9197c0c944fb968cc98904231724`
- Page 3 canonical facts: `79c278780991b18e039db3bf4414dbaba34760c9dbc819572654a5a30d140062`
- Page 3 transfer facts: `d6f82b94529f19057642c745f4cc3b711e1efd469bbbd24dcb1f96f77e6d4863`

Primary E2 outputs:

- `data/storage.csv`: `bcded2d533ca70e90f7df40862b5eb6af8727a328b6147bb65e39f77f266ff22`
- `data/transfers.csv`: `41ef5f2b05f6c2881c2bac87803f1652152542f91846d4108ba67eb7242a18cc`
- `data/parquet/storage.parquet`: `aa9ccd7c263e357bf7ffea3e34e14f241bc36e56b4c0e5d9fe225a0359680675`
- `data/parquet/transfers.parquet`: `e1b0f2cc36240cfe0583222eba19d1216f82ea6d86c8122c78ca2f8a96307d30`

The complete generated hash receipt is `provenance/E2_BUILD_SUMMARY.json`.

## Explicit gaps

- Source-document redistribution/publication approval remains unresolved.
- Original bulletin URLs and unsplit page counts remain unresolved.
- Twenty-three logical dates have incomplete page sets; 3,270 physical paths lack a supported canonical date.
- Arabic labels remain absent for 21 dams and basin labels for 30 dams.
- Some capacity transitions remain unavailable or ambiguous; E2 does not infer through them.
- Page 3 authority remains PROBABLE.
- Two Page 3 node-to-dam crosswalks remain candidate-only.
- The selected Page 3 transfer product says `SAME_DAY`, while its canonical-base contract describes minus-one-calendar-day transfer semantics. E2 preserves and discloses this conflict.
- Page 3 source-consistency status for the selected transfer facts is `NOT_CHECKED`; Sejnane source-label limitations remain flagged.


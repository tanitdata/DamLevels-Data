# E3.1 validation report

**Status: PASS WITH SCIENTIFIC REVIEW FINDINGS AND EXPLICIT GAPS**

E3.1 preserves the E3 engineering contracts and corrects only four evidence-backed national-reconciliation dispositions. `REVIEW_REQUIRED` KPI results below are preserved scientific/data findings; they do not mean the engineering build failed.

## Baseline and scope

- Repository: `<REPO>`
- Accepted E3 commit verified before changes: `79e1ef8f937ab6a0b77e911032fba8c7fce27318`
- Accepted E2 commit verified before changes: `79cbdac5e3155aecf9b953ed24327df624705108`
- Frozen authority: `<FROZEN_BASELINES>/V010_20260924_1620`
- V010 review ZIP SHA-256: `303673e8b342572dff807797355e15cdea9a39325e6083931b31d5f6c783c9d0`
- V010 unchanged: **YES**
- Production extraction rerun: **NO**
- Watershed, climate, feature, integration, GIS, sampling, or satellite pipeline run: **NO**
- Model run: **NO**
- Public remote configured: **NO**

## Contract migration

- Primary `data/storage.csv`: **129,390 storage rows only**
- Separate `qa/printed_fill_reference.csv`: **84,620 printed-fill rows**
- Combined observation identity/value set compared with E2: **EXACT MATCH**
- Governed dams: **36**
- Qualified Page 3 facts retained: **47,556**
- Page 3 authority: **PROBABLE**
- Accepted Page 1 national-total evidence projected locally: **3,981 rows**

The split is `PACKAGING_ONLY`. No accepted observation ID, numeric value, source file, hash, lineage ID, authority, or flag was changed.

## Pydantic contracts

- Tested version: **Pydantic 2.12.5**
- Active models: `Dam`, `CapacityRegime`, `BulletinManifestRecord`, `StorageObservation`, and `TransferObservation`
- Empty transfer values remain `None`; missing is never coerced to zero.
- All current governed rows validate through `python src/build.py`.

## Professor QA C-G

| KPI | Population | Eligible | Pass | Fail | Excluded/unknown | Status |
|---|---:|---:|---:|---:|---:|---|
| C. Uniqueness | 129,390 | 129,390 | 129,390 | 0 | 0 | PASS |
| D. Physical validity | 129,390 | 129,241 | 127,753 | 1,488 | 149 | REVIEW_REQUIRED |
| E. Fill consistency | 129,390 | 84,471 | 80,814 | 3,657 | 44,919 | REVIEW_REQUIRED |
| F. National total reconciliation | 3,985 | 3,967 | 3,965 | 2 | 18 | REVIEW_REQUIRED |
| G. Transfer balance | 15,852 daily candidates | 0 | 0 | 0 | 15,852 | NOT_NUMERICALLY_ELIGIBLE_WITH_EXPLICIT_EXCLUSIONS |

### C. Uniqueness

- Unique `(dam_id, date)` keys: **129,390**
- Duplicate keys: **0**
- Duplicate records: **0**

### D. Physical validity

- `PASS`: **127,753**
- `NEGATIVE_STORAGE`: **0**
- `ABOVE_CAPACITY`: **1,488**
- `CAPACITY_UNAVAILABLE`: **149**
- `CAPACITY_AMBIGUOUS`: **0**

The 149 unavailable rows are the preserved Brek and Lakhmess capacity-gap observations. They are excluded from the upper-capacity denominator and are not failures.

### E. Fill consistency

- `MATCH_WITHIN_ROUNDING`: **80,814**
- `MISMATCH`: **3,657**
- `NO_PRINTED_FILL`: **44,770**
- `CAPACITY_UNAVAILABLE`: **149**
- `CAPACITY_AMBIGUOUS`: **0**

Printed precision is read from the source-cell lineage. The comparison interval is half of the displayed unit on either side of the printed percentage. Storage or capacity is never changed to manufacture agreement.

### F. National total reconciliation

- `MATCH_EXACT`: **1,022**
- `MATCH_WITHIN_ROUNDING`: **2,943**
- `SOURCE_PRINTED_DISAGREEMENT`: **2**
- `MISSING_COMPONENT`: **14**
- `SOURCE_ROSTER_SCOPE_DIFFERENCE`: **4**
- `EXTRACTION_SUSPECT`: **0**
- `UNRESOLVED`: **0**

The source-precision bound is `component_count × 0.0005 Mm3 + printed_total_increment / 2`. It is derived from the printed 0.001 Mm3 precision and is not an arbitrary global tolerance. Ten excluded Page 1 rows have incomplete accepted checksum evidence; four additional canonical dates have no Page 1 grand-total evidence.

The preserved audit classifies **2015-10-03 through 2015-10-06** as a Page 1 roster omission that changes aggregate scope. Those four rows are now qualified/excluded `SOURCE_ROSTER_SCOPE_DIFFERENCE` cases. Their component sums, printed totals, residuals and rounding bounds are byte-for-byte numerically unchanged. The repository-local disposition registry links the preserved evidence at `<PFE_SUBMITTABLE>/03_EVIDENCE/objects/31/31e5456902fffdb938a59fb19f4099dc317beb99a983244f0358e50a45805097__remaining_source_issues.csv` and corroborating residual rows in `<V010_REVIEW_PACKAGE>/data/metadata/audits/interpage_v4/largest_differences.csv`.

The two remaining source-printed disagreements were checked individually and retain their E3 disposition because no preserved direct evidence supports a different classification:

- **2017-12-30:** component sum `631.217` Mm3, printed total `631.607` Mm3, residual `-0.390` Mm3, rounding bound `0.0155` Mm3.
- **2022-02-09:** component sum `1145.464` Mm3, printed total `1145.517` Mm3, residual `-0.053` Mm3, rounding bound `0.0185` Mm3.

### G. Transfer balance

- Daily physical-edge facts: **11,889**
- Daily accounting observations: **3,963**
- Eligible direct comparisons: **0**
- Numerical matches: **0**
- Numerical discrepancies: **0**

Primary exclusions:

- `UNRESOLVED_DAM_CROSSWALK`: **7,926**
- `DATE_SEMANTICS_UNRESOLVED`: **3,963**
- `ACCOUNTING_NOT_HYDRAULIC_EDGE`: **3,963**

All 15,852 candidates also lack a compatible independently reported receiving-side counterpart and have source consistency `NOT_CHECKED`; all retain the unresolved effective-date conflict. Excluded rows are not reported as failed transfers.

## Engineering validation

- Synthetic unit tests: **17 passed**
- Evidence-backed national-disposition guard: **PASS**
- E3.1 roster-scope dates excluded from KPI F failure denominator: **PASS**
- 2017-12-30 and 2022-02-09 retained as `SOURCE_PRINTED_DISAGREEMENT`: **PASS**
- Python source AST parsing: **12 files passed**
- Storage CSV/Parquet order, identifiers, variables, and numeric values: **PASS**
- Printed-fill CSV/Parquet order, identifiers, variables, and numeric values: **PASS**
- Transfer CSV/Parquet order, identifiers, variables, and numeric values: **PASS**
- Complete E2 numeric storage/fill observation identity set preserved: **PASS**
- `datapackage.json` parses and all listed resources resolve: **PASS**
- `python src/build.py` regenerates C-G outputs and validates contracts: **PASS**

## Primary output hashes

- `data/storage.csv`: `6efead63d54cef53ab2f09adb6c22bca2cbc0c55a14b8a39a00d46707cfa7de3`
- `data/parquet/storage.parquet`: `8e0a3fab2c3d49822c7b112b166dfe3e12a499b39c831ede94b7655f5079d376`
- `qa/printed_fill_reference.csv`: `b3de43355d398049bd6495736e3b40b438398b22cff95fd8610ef111a0d34577`
- `qa/printed_fill_reference.parquet`: `4f051066913969a16b88ea73a46d31056c2060662f50ff8f685fa36710f2aa53`
- `provenance/page1_national_totals.csv`: `ddec791242c5689fc2429e257b2086c7684dd44e57641d50d2ea3460f1d394f1`

## Remaining interpretation limits

- The admitted capacity history is printed Page 2 evidence, not independent physical engineering certification.
- Capacity gaps remain unavailable and unfilled.
- Page 3 remains `PROBABLE`; endpoint mappings and effective-date semantics remain unresolved where recorded.
- No compatible independent receiving-side Page 3 measure is established for direct transfer balance.
- Partial bulletin inventories and redistribution status remain unresolved.

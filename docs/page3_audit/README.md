# Page 3 auditing: reading and working guide

Start with [the methodology and implementation decisions](AUDIT_METHOD_AND_DECISIONS.md).
It explains the scientific choices in a form suitable for the report and for
another developer continuing the project.

| Need | File |
| --- | --- |
| Meaning of Page 3 tables, dates, units and flags | [PAGE3_SEMANTICS.md](PAGE3_SEMANTICS.md) |
| Every column in the current canonical fact table | [PAGE3_FIELD_DICTIONARY.csv](PAGE3_FIELD_DICTIONARY.csv) |
| Actual measure, field and grain combinations | [PAGE3_MEASURE_DICTIONARY.csv](PAGE3_MEASURE_DICTIONARY.csv) |
| Prose for the thesis methodology/data chapter | [THESIS_AUDIT_SECTION_DRAFT.md](THESIS_AUDIT_SECTION_DRAFT.md) |
| Executed equality results and exact column pairs | Interpage report: `<PFE_FINAL>/artifacts/runs/interpage_20260908_v1/report.md` (private project, not in this repository) |
| Original-PDF checks and transfer hypothesis | Withdrawal source investigation: `<PFE_FINAL>/artifacts/runs/withdrawal_source_review_20260908_v1/report.md` (private project, not in this repository) |

## Entering data

This guide comes from the private PFE Final project; paths below are relative to its root. The authoritative
machine-local root is `<PFE_FINAL>`; `configs/inputs.json` defines the inputs.

- `data/reference/page12_run_20260831/page1/observations.csv.gz` and its
  `value_lineage.csv.gz`, `source_manifest.csv`, `checksum_source.csv.gz` and
  `checksum_validation.csv.gz` sidecars.
- `data/reference/page12_run_20260831/page2/observations.csv.gz` and
  `value_lineage.csv.gz`.
- `data/reference/page3_canonical/PAGE3_CANONICAL_FACTS_LONG.parquet` with its
  semantic and join contracts.
- Selected original PDFs under `data/raw/bulletins/page1`, `page2`, and `page3`.

## Implementation and preservation

The active comparison implementation is `<PFE_FINAL>/src/pfe_dams/quality/interpage.py`,
with 22 boundary tests in `<PFE_FINAL>/tests/unit/test_interpage.py`. Both are in the
private PFE Final project and are not included in this repository; the published
inter-page check is `qa/INTERPAGE_MISMATCH_REVIEW/`. Private report generation,
source-review and archive-building scripts remain in `local_build/`.

The reviewed dated copy is under `artifacts/audit_packages/page3_audit_20260909_v2/`, with a
ZIP alongside it. It contains a single `PAGE3_AUDIT_DOSSIER.md` for reading and
the separate original files for working. `COPY_MANIFEST.csv` records where each
copy came from and its SHA-256. Treat this archive as a snapshot; continue editing
the authoritative project files and create a new dated snapshot after changes.

The package includes numerical audit inputs and selected source-review PDFs. It
does not duplicate the complete bulletin corpus or all project/environmental
datasets. It supports reproduction of the numerical interpage audit; it is not
a full offline PDF-extraction or model-training project.

## Current scientific status

The comparisons and source investigation are executed and documented. The
withdrawal-transfer recipe remains exploratory, date metadata still conflicts
with parts of the P3 contract, and the join surface is not a training table.
These documents do not mark full QC adaptation, a corrected master, features
or models as complete.

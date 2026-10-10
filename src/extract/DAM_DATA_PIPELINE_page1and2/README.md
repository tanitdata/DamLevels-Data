# Page-1/Page-2 Dam Data Pipeline

This capstone project freezes the accepted Page-1 (`page1-authoritative-0.2.3`) and Page-2 (`page2-authoritative-1.0.0`) extractors byte-for-byte and adds a separate orchestration, outer-merge, SQLite, export, investigation, and read-only audit layer.

The production flow is: source PDFs → accepted page extractors → observations and cell lineage → page tables → one-to-one outer merge → fresh SQLite → plain/compressed CSV. Page measurements remain separately prefixed; nulls, failures, unresolved states, checksum evidence, and `both`/`left_only`/`right_only` coverage are preserved.

Use the existing Python 3.12.13 `pfe` environment and install nothing globally. Open `notebooks/01_BUILD_MERGED_DAM_DATASET.ipynb` first and edit only its configuration cell. It inventories the full direct-child corpora before extraction. Then run `notebooks/02_AUDIT_MERGED_DAM_DATASET.ipynb` against the completed run directory; the audit never imports the extraction runner and opens SQLite read-only.

Fixture runs are regression smoke tests only. The capstone CSV is valid only when the receipt records 3,981 Page-1 PDFs and 3,983 Page-2 PDFs and the independent audit has no failures. Large PDFs, databases, CSV/GZIP products, output runs, caches, and task-local kernel files are ignored by Git. Source, configuration, notebooks, tests, schemas, dependency and hash registers are intended for GitHub; this task does not commit or push.

Page 3 is explicitly out of scope. Future notebooks are reserved as `03_BUILD_PAGE3_DATASET.ipynb` and `04_AUDIT_PAGE3_WITH_PAGE1_PAGE2.ipynb`; Page 3 will remain long-format and will be audited for coverage, identity, transfer, and plausibility without forcing it into this wide table.

from __future__ import annotations

import json, sqlite3
from pathlib import Path
import pandas as pd

PAGE_FILES = {
 "observations": "observations.csv.gz", "value_lineage": "value_lineage.csv.gz",
 "checksum_source": "checksum_source.csv.gz", "checksum_validation": "checksum_validation.csv.gz",
 "failures": "extraction_failures.csv", "unresolved": "unresolved_values.csv", "validation": "validation_checks.csv",
}


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False) if path.exists() else pd.DataFrame()


def create_database(path: str | Path, page1_root: str | Path, page2_root: str | Path,
                    source_manifest: pd.DataFrame, page1: pd.DataFrame, page2: pd.DataFrame,
                    merged: pd.DataFrame, metadata: dict) -> dict:
    path = Path(path)
    if path.exists(): raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        pd.DataFrame([{"key": k, "value": json.dumps(v, sort_keys=True) if isinstance(v, (dict,list)) else str(v)} for k,v in metadata.items()]).to_sql("pipeline_metadata", conn, index=False)
        source_manifest.to_sql("source_manifest", conn, index=False)
        page1.to_sql("page1_observations", conn, index=False)
        page2.rename(columns={"dam_id":"canonical_dam_id"}).to_sql("page2_observations", conn, index=False)
        merged.to_sql("merged_daily", conn, index=False)
        for page, root in (("page1", Path(page1_root)), ("page2", Path(page2_root))):
            for role, filename in PAGE_FILES.items():
                if role == "observations": continue
                frame = _read(root / filename)
                if frame.shape[1]:
                    frame.to_sql(f"{page}_{role}", conn, index=False)
                else:
                    conn.execute(f'CREATE TABLE "{page}_{role}" (_empty TEXT)')
        for table in ("page1_observations", "page2_observations", "merged_daily"):
            conn.execute(f'CREATE UNIQUE INDEX ux_{table}_key ON "{table}"(canonical_dam_id, bulletin_date)')
            conn.execute(f'CREATE INDEX ix_{table}_date ON "{table}"(bulletin_date)')
        conn.executescript('''
CREATE VIEW v_merged_daily AS SELECT * FROM merged_daily;
CREATE VIEW v_page_coverage AS SELECT page_presence, COUNT(*) AS rows FROM merged_daily GROUP BY page_presence;
CREATE VIEW v_missingness_by_dam AS SELECT canonical_dam_id, COUNT(*) AS rows FROM merged_daily GROUP BY canonical_dam_id;
CREATE VIEW v_lineage_summary AS SELECT 'page1' page, COUNT(*) rows FROM page1_value_lineage UNION ALL SELECT 'page2', COUNT(*) FROM page2_value_lineage;
CREATE VIEW v_cross_page_comparison AS SELECT * FROM merged_daily WHERE page_presence='both';
CREATE VIEW v_extraction_quality AS SELECT 'page1_failures' metric, COUNT(*) value FROM page1_failures UNION ALL SELECT 'page2_failures', COUNT(*) FROM page2_failures UNION ALL SELECT 'page1_unresolved', COUNT(*) FROM page1_unresolved UNION ALL SELECT 'page2_unresolved', COUNT(*) FROM page2_unresolved;
''')
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.commit()
    finally: conn.close()
    return {"path": str(path.resolve()), "integrity_check": integrity, "foreign_key_violations": len(fk)}

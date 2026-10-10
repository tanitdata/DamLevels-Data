from __future__ import annotations

import argparse, json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from dam_extraction.orchestration.page1_production import execute_page1_run
from dam_extraction.page2.production import execute_page2_run
from dam_extraction.page1.engine import ENGINE_VERSION as PAGE1_ENGINE
from dam_extraction.page2 import ENGINE_VERSION as PAGE2_ENGINE
from . import PIPELINE_VERSION
from .corpus import inventory, compare_accepted, sha256_file
from .database import create_database
from .export import export_products
from .investigation import build_investigation
from .merge import merge_pages


def utcnow(): return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")


def run_pipeline(page1_root: str|Path, page2_root: str|Path, output_root: str|Path, *, run_id: str,
                 project_root: str|Path, page1_workers: int=8, page2_workers: int=12,
                 expected_page1_count: int|None=3981, expected_page2_count: int|None=3983,
                 write_sqlite: bool=True, write_csv: bool=True, generate_figures: bool=True) -> dict:
    project=Path(project_root).resolve(); run=Path(output_root).resolve()
    if run.exists() and any(run.iterdir()): raise FileExistsError(f"fresh run required: {run}")
    for sub in ("page1","page2","database","exports","figures","reports","investigation"): (run/sub).mkdir(parents=True,exist_ok=True)
    started=utcnow()
    m1=inventory(page1_root,1,expected_page1_count); m2=inventory(page2_root,2,expected_page2_count); manifest=pd.concat([m1,m2],ignore_index=True)
    manifest.to_csv(run/"reports"/"source_manifest_sha256.csv",index=False)
    accepted=project/"references"/"COMBINED_SOURCE_INVENTORY.csv"
    inventory_check=compare_accepted(manifest,accepted); inventory_check.to_csv(run/"reports"/"accepted_inventory_comparison.csv",index=False)
    if (inventory_check.status!="PASS").any(): raise RuntimeError("accepted source inventory mismatch")
    alias=project/"config"/"page1"/"PAGE1_GOVERNED_ALIAS_REGISTER.csv"
    s1=execute_page1_run(m1.source_path,run/"page1",run_id=f"{run_id}-page1",run_mode="FULL",workers=page1_workers,alias_registry_path=alias,write_sqlite=True,write_csv_exports=True)
    s2=execute_page2_run(m2.source_path,run/"page2",run_id=f"{run_id}-page2",run_mode="FULL",workers=page2_workers,write_sqlite=True,write_csv=True)
    p1=pd.read_csv(run/"page1"/"observations.csv.gz",low_memory=False); p2=pd.read_csv(run/"page2"/"observations.csv.gz",low_memory=False)
    merged=merge_pages(p1,p2)
    products=export_products(p1,p2,merged,run/"exports") if write_csv else {}
    metadata={"pipeline_version":PIPELINE_VERSION,"run_id":run_id,"page1_engine":PAGE1_ENGINE,"page2_engine":PAGE2_ENGINE,"started_at":started,"source_counts":{"page1":len(m1),"page2":len(m2)}}
    db=create_database(run/"database"/"dam_data.db",run/"page1",run/"page2",manifest,p1,p2,merged,metadata) if write_sqlite else {}
    investigation=build_investigation(manifest,p1,p2,merged,run/"page1",run/"page2",run/"investigation",run/"figures") if generate_figures else {}
    presence=merged.page_presence.value_counts().to_dict()
    receipt={**metadata,"completed_at":utcnow(),"status":"COMPLETE","page1_summary":s1,"page2_summary":s2,
      "page1_observation_count":len(p1),"page2_observation_count":len(p2),"merged_row_count":len(merged),"merged_column_count":len(merged.columns),
      "merged_dam_count":int(merged.canonical_dam_id.nunique()),"merged_date_min":str(merged.bulletin_date.min()),"merged_date_max":str(merged.bulletin_date.max()),
      "page_presence":presence,"database":db,"products":products,"investigation":investigation,"accepted_inventory_match":True}
    (run/"pipeline_receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    return receipt


def main():
    p=argparse.ArgumentParser(); p.add_argument("--page1-root",required=True); p.add_argument("--page2-root",required=True); p.add_argument("--output-root",required=True); p.add_argument("--project-root",required=True); p.add_argument("--run-id",required=True); p.add_argument("--page1-workers",type=int,default=8); p.add_argument("--page2-workers",type=int,default=12)
    a=p.parse_args(); print(json.dumps(run_pipeline(a.page1_root,a.page2_root,a.output_root,run_id=a.run_id,project_root=a.project_root,page1_workers=a.page1_workers,page2_workers=a.page2_workers),indent=2,default=str))


if __name__=="__main__": main()

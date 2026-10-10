from pathlib import Path
import pandas as pd
from dam_pipeline.investigation import build_investigation
from dam_pipeline.corpus import sha256_file

project=Path(__file__).resolve().parents[1]
run=project/"outputs/runs/RUN_20260831_FULL_01"
protected=sorted([p for folder in ("page1","page2","database","exports","reports") for p in (run/folder).rglob("*") if p.is_file()]+[run/"pipeline_receipt.json"])
before={str(p.relative_to(run)):sha256_file(p) for p in protected}
(run/"investigation"/"UNRESOLVED_SUMMARY.csv").unlink(missing_ok=True)
(run/"figures"/"08_failures_and_unresolved.png").unlink(missing_ok=True)
source=pd.read_csv(run/"reports/source_manifest_sha256.csv",low_memory=False)
p1=pd.read_csv(run/"page1/observations.csv.gz",low_memory=False)
p2=pd.read_csv(run/"page2/observations.csv.gz",low_memory=False)
merged=pd.read_csv(run/"exports/merged_dam_daily.csv",low_memory=False)
result=build_investigation(source,p1,p2,merged,run/"page1",run/"page2",run/"investigation",run/"figures")
after={str(p.relative_to(run)):sha256_file(p) for p in protected}
assert before==after, [name for name in before if before[name]!=after.get(name)]
(run/"audit").mkdir(exist_ok=True)
pd.DataFrame([{"artifact":name,"sha256_before":before[name],"sha256_after":after[name],"status":"PASS"} for name in before]).to_csv(run/"audit"/"presentation_refresh_scientific_hash_check.csv",index=False)
print(result)
print("PROTECTED_SCIENTIFIC_OUTPUTS_UNCHANGED",len(before))
for name in ("SOURCE_COVERAGE_BY_YEAR","LINEAGE_STATUS_SUMMARY","LINEAGE_BY_FIELD","QUALITY_STATUS_SUMMARY"):
    frame=pd.read_csv(run/"investigation"/f"{name}.csv")
    print(name,len(frame))

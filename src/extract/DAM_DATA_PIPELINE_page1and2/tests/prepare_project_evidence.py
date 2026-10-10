from __future__ import annotations
import ast, csv, hashlib
from pathlib import Path
import pandas as pd

import os
PROJECT=Path(__file__).resolve().parents[1]
# Original production_v2 workspace this evidence was copied from (<PFE_WORK>/extraction/production_v2)
SOURCE=Path(os.environ["DAMLEVELS_PRODUCTION_V2"])

def sha(p):
 d=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""): d.update(b)
 return d.hexdigest()

# Accepted full-run observations provide independent fixture expectations.
names1={p.name for p in (PROJECT/"fixtures/page1").glob("*.pdf")}; names2={p.name for p in (PROJECT/"fixtures/page2").glob("*.pdf")}
for page,names in (("page1",names1),("page2",names2)):
 src=SOURCE/"output"/"combined_run5_20260813"/page/"observations.csv.gz"
 df=pd.read_csv(src,low_memory=False)
 source_col=next(c for c in ("source_filename","source_file","source_pdf") if c in df)
 expected=df[df[source_col].isin(names)].sort_values([source_col,"bulletin_date", "canonical_dam_id" if "canonical_dam_id" in df else "dam_id"],kind="stable")
 expected.to_csv(PROJECT/"fixtures"/f"expected_{page}.csv",index=False,lineterminator="\n")
 pd.DataFrame({"column":df.columns,"ordinal":range(len(df.columns)),"dtype_accepted":df.dtypes.astype(str).values}).to_csv(PROJECT/"references"/f"accepted_{page}_output_schema.csv",index=False)

entrypoints=[PROJECT/"src/dam_extraction/orchestration/page1_production.py",PROJECT/"src/dam_extraction/page2/production.py",PROJECT/"src/dam_extraction/orchestration/combined_run.py"]
copied=sorted([p for p in (PROJECT/"src/dam_extraction").rglob("*") if p.is_file() and p.suffix in {".py",".json"}] + list((PROJECT/"config/page1").glob("*")) + list((PROJECT/"config/page2").glob("*")))
with (PROJECT/"investigation/ACCEPTED_SOURCE_HASHES.csv").open("w",encoding="utf-8",newline="") as f:
 w=csv.DictWriter(f,fieldnames=["destination_path","source_path","sha256","status"]); w.writeheader()
 for dest in copied:
  rel=dest.relative_to(PROJECT)
  if str(rel).startswith("src\\dam_extraction"):
   src=SOURCE/rel
  elif dest.name=="PAGE1_GOVERNED_ALIAS_REGISTER.csv": src=SOURCE/"page1/fixtures"/dest.name
  else: src=SOURCE/"page2/config"/dest.name
  w.writerow({"destination_path":str(rel),"source_path":str(src),"sha256":sha(dest),"status":"MATCH" if src.exists() and sha(src)==sha(dest) else "MISMATCH"})

rows=[]
for ep in entrypoints:
 tree=ast.parse(ep.read_text(encoding="utf-8"))
 imports=[]
 for n in ast.walk(tree):
  if isinstance(n,ast.Import): imports += [a.name for a in n.names]
  elif isinstance(n,ast.ImportFrom) and n.module: imports.append(n.module)
 for module in sorted(set(imports)):
  if module.startswith("dam_extraction"):
   candidate=PROJECT/"src"/(module.replace(".","/")+".py")
   if not candidate.exists(): candidate=PROJECT/"src"/module.replace(".","/")/"__init__.py"
   rows.append([str(ep.relative_to(PROJECT)),"local_python_import",str((SOURCE/candidate.relative_to(PROJECT)).resolve()),str(candidate.relative_to(PROJECT)),True,sha(candidate) if candidate.exists() else "","COPIED" if candidate.exists() else "UNRESOLVED",module])
resources=[(SOURCE/"page1/fixtures/PAGE1_GOVERNED_ALIAS_REGISTER.csv",PROJECT/"config/page1/PAGE1_GOVERNED_ALIAS_REGISTER.csv","Page-1 governed alias roster"),(SOURCE/"page2/config/PAGE2_GOVERNED_ALIAS_REGISTRY.csv",PROJECT/"config/page2/PAGE2_GOVERNED_ALIAS_REGISTRY.csv","Page-2 governed alias registry"),(SOURCE/"src/dam_extraction/page2/data/roster.json",PROJECT/"src/dam_extraction/page2/data/roster.json","Page-2 package roster"),(SOURCE/"page2/config/schema.json",PROJECT/"config/page2/schema.json","Page-2 schema")]
for src,dest,reason in resources: rows.append(["page1/page2 runtime","configuration_resource",str(src),str(dest.relative_to(PROJECT)),True,sha(dest),"COPIED_MATCH" if sha(src)==sha(dest) else "MISMATCH",reason])
with (PROJECT/"investigation/RUNTIME_DEPENDENCY_CLOSURE.csv").open("w",encoding="utf-8",newline="") as f:
 w=csv.writer(f); w.writerow(["entry_point","dependency_type","source_path","destination_path","required_at_runtime","sha256","status","reason"]); w.writerows(rows)
print("EXPECTED_PAGE1_ROWS",len(pd.read_csv(PROJECT/"fixtures/expected_page1.csv")))
print("EXPECTED_PAGE2_ROWS",len(pd.read_csv(PROJECT/"fixtures/expected_page2.csv")))
print("FROZEN_SOURCE_HASHES","PASS" if all(r[6] not in {"MISMATCH","UNRESOLVED"} for r in rows) else "FAIL")

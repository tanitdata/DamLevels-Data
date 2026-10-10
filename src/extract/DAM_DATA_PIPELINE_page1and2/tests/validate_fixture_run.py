from pathlib import Path
import sqlite3
import pandas as pd
from pandas.testing import assert_frame_equal

project=Path(__file__).resolve().parents[1]
run=project/"outputs/fixture_gate_run_02"
def normalized(df):
    keys=[c for c in ("source_filename","source_file","bulletin_date","canonical_dam_id","dam_id") if c in df]
    return df.sort_values(keys,kind="stable").reset_index(drop=True)
for page in ("page1","page2"):
    actual=pd.read_csv(run/page/"observations.csv.gz",low_memory=False)
    expected=pd.read_csv(project/"fixtures"/f"expected_{page}.csv",low_memory=False)
    assert_frame_equal(normalized(actual),normalized(expected),check_dtype=False,check_like=False)
    print(f"{page.upper()}_EXPECTED_COMPARISON = PASS")
merged=pd.read_csv(run/"exports/merged_dam_daily.csv",low_memory=False)
compressed=pd.read_csv(run/"exports/merged_dam_daily.csv.gz",low_memory=False)
assert_frame_equal(merged,compressed,check_dtype=False)
with sqlite3.connect(f"file:{(run/'database/dam_data.db').as_posix()}?mode=ro",uri=True) as c:
    assert c.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    assert not c.execute("PRAGMA foreign_key_check").fetchall()
    db=pd.read_sql_query("select * from merged_daily order by bulletin_date, canonical_dam_id",c)
left=normalized(merged).fillna("<NULL>").astype(str)
right=normalized(db).fillna("<NULL>").astype(str)
assert_frame_equal(left,right,check_dtype=False)
register=pd.read_csv(project/"investigation/ACCEPTED_SOURCE_HASHES.csv")
assert (register.status=="MATCH").all()
print("FIXTURE_MERGE = PASS\nFIXTURE_DATABASE = PASS\nFIXTURE_CSV = PASS\nFROZEN_SOURCE_HASHES = PASS")

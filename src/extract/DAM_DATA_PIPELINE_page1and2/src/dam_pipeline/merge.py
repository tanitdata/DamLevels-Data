from __future__ import annotations

import pandas as pd

MERGE_KEYS = ["canonical_dam_id", "bulletin_date"]


def merge_pages(page1: pd.DataFrame, page2: pd.DataFrame) -> pd.DataFrame:
    p1 = page1.copy()
    p2 = page2.rename(columns={"dam_id": "canonical_dam_id"}).copy()
    for label, frame in (("Page-1", p1), ("Page-2", p2)):
        missing = set(MERGE_KEYS) - set(frame.columns)
        if missing:
            raise KeyError(f"{label} missing keys: {sorted(missing)}")
        if frame.duplicated(MERGE_KEYS).any():
            raise ValueError(f"{label} observation keys are not unique")
    p1 = p1.rename(columns={c: f"page1__{c}" for c in p1.columns if c not in MERGE_KEYS})
    p2 = p2.rename(columns={c: f"page2__{c}" for c in p2.columns if c not in MERGE_KEYS})
    merged = p1.merge(p2, on=MERGE_KEYS, how="outer", validate="one_to_one", indicator="page_presence")
    merged["page_presence"] = merged["page_presence"].astype(str)
    return merged.sort_values(["bulletin_date", "canonical_dam_id"], kind="stable").reset_index(drop=True)

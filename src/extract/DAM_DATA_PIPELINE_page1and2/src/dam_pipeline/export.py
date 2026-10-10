from __future__ import annotations

from pathlib import Path
import pandas as pd
from .corpus import sha256_file


def export_products(page1: pd.DataFrame, page2: pd.DataFrame, merged: pd.DataFrame, root: str | Path) -> dict:
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    products = {
        "page1": root / "page1_observations.csv.gz",
        "page2": root / "page2_observations.csv.gz",
        "merged_csv": root / "merged_dam_daily.csv",
        "merged_gzip": root / "merged_dam_daily.csv.gz",
    }
    page1.to_csv(products["page1"], index=False, compression={"method": "gzip", "mtime": 0})
    page2.to_csv(products["page2"], index=False, compression={"method": "gzip", "mtime": 0})
    merged.to_csv(products["merged_csv"], index=False, lineterminator="\n")
    merged.to_csv(products["merged_gzip"], index=False, compression={"method": "gzip", "mtime": 0}, lineterminator="\n")
    return {k: {"path": str(v.resolve()), "bytes": v.stat().st_size, "sha256": sha256_file(v)} for k, v in products.items()}

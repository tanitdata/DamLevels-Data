from __future__ import annotations

import hashlib
from pathlib import Path
import pandas as pd


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: str | Path, page: int, expected_count: int | None = None) -> pd.DataFrame:
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    files = sorted(root.glob("*.pdf"), key=lambda p: (p.name.casefold(), p.name))
    suffix = f"_{page}.pdf"
    foreign = [p.name for p in files if not p.name.lower().endswith(suffix)]
    if foreign:
        raise ValueError(f"page{page} filename contamination: {foreign[:10]}")
    if expected_count is not None and len(files) != expected_count:
        raise ValueError(f"page{page} count {len(files)} != {expected_count}")
    return pd.DataFrame([{"page": f"page{page}", "source_file": p.name, "source_path": str(p),
                          "source_bytes": p.stat().st_size, "source_sha256": sha256_file(p)} for p in files])


def compare_accepted(actual: pd.DataFrame, accepted_path: str | Path) -> pd.DataFrame:
    accepted = pd.read_csv(accepted_path, dtype=str)
    keys = actual[["page", "source_file"]]
    expected = accepted.merge(keys, on=["page", "source_file"], how="inner")[["page", "source_file", "source_sha256"]]
    check = actual.merge(expected, on=["page", "source_file"], how="outer", suffixes=("_actual", "_accepted"), indicator=True)
    check["status"] = check.apply(lambda r: "PASS" if r["_merge"] == "both" and r["source_sha256_actual"] == r["source_sha256_accepted"] else "FAIL", axis=1)
    return check

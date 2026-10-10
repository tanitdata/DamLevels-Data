import csv
import hashlib
import json
import os
import warnings
from pathlib import Path

import pytest

from dam_extraction.page1.engine import extract_cell_strategy_evidence, extract_page1_pdf

if not os.environ.get("DAMLEVELS_BULLETIN_PAGE1_DIR"):
    pytest.skip("set DAMLEVELS_BULLETIN_PAGE1_DIR to the Page 1 bulletin folder", allow_module_level=True)
PDF_ROOT = Path(os.environ["DAMLEVELS_BULLETIN_PAGE1_DIR"])
# Original development workspace (historical archaeology checks only).
PROJECT = Path(os.environ["DAMLEVELS_PFE_WORK"]) if os.environ.get("DAMLEVELS_PFE_WORK") else None


def test_schema_authority_reports_true_physical_leaf_counts():
    cases = [
        ("3-10-2015_1.pdf", "mellegue", "stock_last_year_mm3", "P1_LAYOUT_15_NO_FILL", 15),
        ("14-4-2020_1.pdf", "gamgoum", "apport_cumul_prev_year", "P1_LAYOUT_16_WITH_FILL", 16),
    ]
    for filename, dam, field, layout, count in cases:
        result = extract_page1_pdf(PDF_ROOT / filename, scope="TARGETED", target_keys=[(dam, field)])
        evidence = next(row for row in result.validation_results if row["validation_name"] == "SCHEMA_AUTHORITY")
        details = json.loads(evidence["details_json"])
        assert result.schema_layout_class == layout
        assert details["data_column_count"] == count


def test_hvc_runtime_helper_is_truthfully_deprecated():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        evidence = extract_cell_strategy_evidence(PDF_ROOT / "13-2-2017_1.pdf", "bezirk", "release_cumul_year")
    assert caught and issubclass(caught[0].category, DeprecationWarning)
    assert evidence["status"] == "DEPRECATED_ARCHAEOLOGY_DEVELOPMENT_BENCHMARK_ONLY"
    assert evidence["runtime_strategy_comparison"] is False
    assert evidence["runtime_fallback_invoked"] is False
    assert evidence["diagnostic_values_returned"] is False
    assert not any(name in evidence for name in ("horizontal", "vertical", "exact_crop"))


@pytest.mark.skipif(PROJECT is None, reason="set DAMLEVELS_PFE_WORK to the original development workspace")
def test_authorized_cache_removed_and_legacy_baseline_unchanged():
    cache = PROJECT / "extraction/page1/dam_pipeline/__pycache__/extract_row.cpython-312.pyc"
    assert not cache.exists()
    baseline = PROJECT / "extraction_engineering_work/run_01_archaeology_design_20260810/PROTECTED_SCOPE_SNAPSHOT_BASELINE.csv"
    with baseline.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["scope"] == "PAGE1_LIVE_EXTRACTOR"]
    assert rows
    for row in rows:
        path = Path(row["absolute_path"])
        assert path.is_file()
        assert path.stat().st_size == int(row["bytes"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]

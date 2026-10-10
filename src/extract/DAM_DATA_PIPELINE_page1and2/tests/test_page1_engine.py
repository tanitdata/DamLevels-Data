import os
from pathlib import Path

import pytest

from dam_extraction.page1.engine import extract_page1_pdf

if not os.environ.get("DAMLEVELS_BULLETIN_PAGE1_DIR"):
    pytest.skip("set DAMLEVELS_BULLETIN_PAGE1_DIR to the Page 1 bulletin folder", allow_module_level=True)
PDF_ROOT = Path(os.environ["DAMLEVELS_BULLETIN_PAGE1_DIR"])


def get(pdf, dam, field):
    result = extract_page1_pdf(PDF_ROOT / pdf, scope="TARGETED", target_keys=[(dam, field)])
    assert len(result.value_lineage) == 1
    return result, result.value_lineage[0]


def test_doubled_overlay_is_coordinate_deduped():
    _, cell = get("13-2-2017_1.pdf", "bezirk", "release_cumul_year")
    assert cell.raw_glyph_sequence == "00,,336611"
    assert cell.normalized_parse_input == "0,361"
    assert cell.parsed_numeric_value == 0.361


def test_borderless_stock_is_physical_source_value():
    result, cell = get("3-10-2015_1.pdf", "mellegue", "stock_last_year_mm3")
    assert cell.parsed_numeric_value == 27.972
    assert result.validation_results[0]["status"] == "BORDERLESS_COLUMN_PROVEN"


def test_action_adjacency_does_not_shift_release():
    _, cell = get("1-5-2021_1.pdf", "tine", "release_yesterday")
    assert cell.parsed_numeric_value == 0.046
    assert cell.time_basis == "current reporting-interval release"


def test_full_targeted_same_semantic_cell():
    pdf = PDF_ROOT / "13-2-2017_1.pdf"
    targeted = extract_page1_pdf(pdf, scope="TARGETED", target_keys=[("bezirk", "release_cumul_year")])
    full = extract_page1_pdf(pdf, scope="FULL")
    a = targeted.value_lineage[0]
    b = next(cell for cell in full.value_lineage if cell.canonical_dam_id == "bezirk" and cell.canonical_semantic_field == "p1_release_cumul_year")
    assert (a.parsed_numeric_value, a.parser_state, a.raw_glyph_sequence) == (b.parsed_numeric_value, b.parser_state, b.raw_glyph_sequence)


def test_merged_ben_metir_kasseb_band_is_split_by_printed_baseline():
    result, cell = get("01-02-2020_1.pdf", "benmetir", "apport_today")
    assert cell.raw_dam_label == "BEN METIR"
    assert cell.row_detection_method == "MERGED_TABLE_BAND_VERTICAL_BASELINE_PLUS_GOVERNED_EXACT_ALIAS"
    assert cell.parser_state == "NUMERIC_PARSED"
    assert len(result.observations) == 1


def test_duplicate_label_band_keeps_numeric_source_glyphs():
    result = extract_page1_pdf(
        PDF_ROOT / "11-8-2016_1.pdf",
        scope="TARGETED",
        target_keys=[("chiba", "apport_today"), ("chiba", "stock_last_year_mm3")],
    )
    cells = {cell.canonical_semantic_field: cell for cell in result.value_lineage}
    assert cells["p1_apport_today"].parsed_numeric_value == 0.001
    assert cells["p1_stock_last_year_mm3"].parsed_numeric_value == 0.951
    assert all(cell.parser_state == "NUMERIC_PARSED" for cell in cells.values())

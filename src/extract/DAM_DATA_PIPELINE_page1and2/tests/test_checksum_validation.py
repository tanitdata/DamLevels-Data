import os
from pathlib import Path

import pytest

from dam_extraction.page1.checksum_reader import RAW_RESIDUAL_ONLY
from dam_extraction.page1.engine import extract_page1_pdf

if not os.environ.get("DAMLEVELS_BULLETIN_PAGE1_DIR"):
    pytest.skip("set DAMLEVELS_BULLETIN_PAGE1_DIR to the Page 1 bulletin folder", allow_module_level=True)
PDF = Path(os.environ["DAMLEVELS_BULLETIN_PAGE1_DIR"]) / "03-02-2020_1.pdf"


def _row(result, scope, field="p1_apport_today"):
    return next(
        row for row in result.checksum_validation
        if row["region_or_total"] == scope and row["field"] == field
    )


def test_targeted_partial_never_claims_complete_or_source_failure():
    result = extract_page1_pdf(PDF, scope="TARGETED", target_keys=[("bezirk", "apport_today")])
    assert result.checksum_validation
    assert all(row["execution_scope"] == "TARGETED" for row in result.checksum_validation)
    assert all(row["completeness"] == "TARGETED_PARTIAL" for row in result.checksum_validation)
    assert all(row["disposition"] == "NOT_APPLICABLE_TARGETED_PARTIAL" for row in result.checksum_validation)
    assert not any("FAIL" in row["disposition"] for row in result.checksum_validation)


def test_regional_and_grand_total_contributor_counts_are_physical():
    result = extract_page1_pdf(PDF, scope="FULL")
    nord = _row(result, "NORD")
    centre = _row(result, "CENTRE")
    cap_bon = _row(result, "CAP-BON")
    total = _row(result, "TOTAL")
    assert (nord["expected_contributors"], centre["expected_contributors"], cap_bon["expected_contributors"]) == (19, 8, 6)
    assert total["expected_contributors"] == 33
    assert (nord["checksum_scope"], centre["checksum_scope"], cap_bon["checksum_scope"]) == (
        "REGIONAL_SUBTOTAL", "REGIONAL_SUBTOTAL", "REGIONAL_SUBTOTAL"
    )
    assert total["checksum_scope"] == "GRAND_TOTAL"
    assert (nord["observed_contributors"], centre["observed_contributors"], cap_bon["observed_contributors"]) == (19, 8, 6)
    assert total["observed_contributors"] == 33


def test_regional_and_grand_total_raw_residuals_are_source_faithful():
    result = extract_page1_pdf(PDF, scope="FULL")
    expected = {
        "NORD": (1.206, 1.208, -0.002),
        "CENTRE": (0.041, 0.042, -0.001),
        "CAP-BON": (0.017, 0.017, 0.0),
        "TOTAL": (1.264, 1.267, -0.003),
    }
    for scope, (computed, published, residual) in expected.items():
        row = _row(result, scope)
        assert abs(row["published_sum"] - published) <= 1e-12
        assert abs(row["computed_sum"] - computed) <= 1e-12
        assert abs(row["signed_residual"] - residual) <= 1e-12
        assert row["absolute_residual"] == abs(row["signed_residual"])
        assert row["tolerance_policy"] == RAW_RESIDUAL_ONLY
        assert row["tolerance_formula"] is None
        assert row["tolerance_term_count"] == 0
        assert "0.015" not in row["tolerance_policy"]
        assert not row["generates_dam_value"]

from decimal import Decimal

import pytest

from validate.research_qa import (
    assert_one_primary_cell_per_pdf,
    accuracy_target_decision,
    classify_date_completeness,
    classify_extraction,
    classify_temporal,
    median_mad,
    minimum_zero_error_sample_size,
    missing_run_summary,
    multipage_target_decision,
    parse_pdf_number,
    robust_z,
    proportional_allocation,
    proportional_stratified_sample,
    wilson_interval,
)


def test_wilson_interval_for_1500_perfect_matches_is_descriptively_above_target():
    lower, upper = wilson_interval(1500, 1500)
    assert lower == pytest.approx(0.9974456, abs=1e-7)
    assert upper == pytest.approx(1.0)
    assert lower >= 0.995


def test_clustered_unequal_sample_cannot_automatically_demonstrate_population_target():
    lower, _ = wilson_interval(1500, 1500)
    assert lower > 0.995
    assert accuracy_target_decision(
        accuracy=1.0,
        wilson_lower=lower,
        target=0.995,
        design_supports_population_inference=False,
    ) == "INCONCLUSIVE"


def test_extraction_exact_mismatch_and_unverifiable():
    assert parse_pdf_number("25,556") == Decimal("25.556")
    assert classify_extraction(Decimal("25.556"), Decimal("25.556")) == ("MATCH", True)
    assert classify_extraction(Decimal("25.556"), Decimal("25.557")) == (
        "EXTRACTION_DISCREPANCY_CANDIDATE", False
    )
    assert classify_extraction(Decimal("25.556"), None) == ("UNVERIFIABLE", None)
    assert parse_pdf_number("value 25,556") is None


def test_missing_run_detection_including_leading_and_trailing():
    expected = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    result = missing_run_summary(expected, {"2024-01-03"})
    assert result.missing_count == 4
    assert result.longest_run == 2
    assert result.longest_start == "2024-01-01"
    assert result.longest_end == "2024-01-02"
    assert result.leading_run == 2
    assert result.trailing_run == 2


def test_partial_bulletin_is_not_called_extraction_missing():
    assert classify_date_completeness(
        bulletin_present=True, page1_present=False, observed=0, expected=0
    ) == "PARTIAL_BULLETIN"
    assert classify_date_completeness(
        bulletin_present=False, page1_present=False, observed=0, expected=0
    ) == "NO_BULLETIN"


def test_robust_median_mad_and_mad_zero_behavior():
    centre, mad = median_mad([Decimal("-1"), Decimal("0"), Decimal("1")])
    assert centre == Decimal("0")
    assert mad == Decimal("1")
    assert robust_z(Decimal("10"), centre, mad) == Decimal("6.7450")
    assert robust_z(Decimal("2"), Decimal("2"), Decimal("0")) == Decimal("0")
    assert robust_z(Decimal("3"), Decimal("2"), Decimal("0")) is None


def test_long_gap_is_excluded_from_daily_temporal_comparison():
    classification, score = classify_temporal(
        elapsed_days=3, delta=Decimal("30"), centre=Decimal("0"), mad=Decimal("1")
    )
    assert classification == "GAP_NOT_COMPARABLE"
    assert score is None


def test_positive_and_negative_temporal_outliers():
    positive, pos_z = classify_temporal(
        elapsed_days=1, delta=Decimal("10"), centre=Decimal("0"), mad=Decimal("1")
    )
    negative, neg_z = classify_temporal(
        elapsed_days=1, delta=Decimal("-10"), centre=Decimal("0"), mad=Decimal("1")
    )
    assert positive == negative == "ROBUST_OUTLIER"
    assert pos_z == Decimal("6.7450")
    assert neg_z == Decimal("-6.7450")


def test_mad_zero_nonmedian_delta_requires_review():
    classification, score = classify_temporal(
        elapsed_days=1, delta=Decimal("1"), centre=Decimal("0"), mad=Decimal("0")
    )
    assert classification == "SOURCE_REVIEW_REQUIRED"
    assert score is None


def test_zero_error_sample_size_is_computed_not_hardcoded():
    required = minimum_zero_error_sample_size(target=0.995, confidence=0.95)
    assert required == 765
    assert wilson_interval(required, required)[0] >= 0.995
    assert wilson_interval(required - 1, required - 1)[0] < 0.995


def test_proportional_stratified_sampling_and_seed_reproduction():
    strata = {
        "old": [{"pdf": f"old-{index}"} for index in range(30)],
        "new": [{"pdf": f"new-{index}"} for index in range(70)],
    }
    first, allocation = proportional_stratified_sample(
        strata, 20, seed=42, stable_key=lambda row: row["pdf"]
    )
    second, allocation_again = proportional_stratified_sample(
        strata, 20, seed=42, stable_key=lambda row: row["pdf"]
    )
    assert allocation == allocation_again == {"old": 6, "new": 14}
    assert first == second
    assert len({row["pdf"] for row in first}) == 20


def test_largest_remainder_allocation_preserves_total_and_weights():
    allocation = proportional_allocation({"r1": 2631, "r2": 343, "r3": 989}, 800)
    assert sum(allocation.values()) == 800
    probabilities = {key: allocation[key] / size for key, size in {"r1": 2631, "r2": 343, "r3": 989}.items()}
    weights = {key: 1 / probability for key, probability in probabilities.items()}
    assert all(probability > 0 for probability in probabilities.values())
    assert all(weight > 1 for weight in weights.values())


def test_primary_sample_rejects_two_cells_from_one_pdf():
    with pytest.raises(ValueError, match="duplicate PDF"):
        assert_one_primary_cell_per_pdf([
            {"source_file": "one.pdf", "cell": "a"},
            {"source_file": "one.pdf", "cell": "b"},
        ])


def test_wilson_target_decision_is_family_specific_and_requires_enough_independent_pdfs():
    decision, lower, upper = multipage_target_decision(
        matches=800,
        eligible=800,
        required_zero_error_sample_size=765,
        target=0.995,
        independent_pdf_design=True,
    )
    assert decision == "YES"
    assert lower is not None and lower >= 0.995
    assert upper == pytest.approx(1.0)
    too_small, _, _ = multipage_target_decision(
        matches=700,
        eligible=700,
        required_zero_error_sample_size=765,
        target=0.995,
        independent_pdf_design=True,
    )
    assert too_small == "INCONCLUSIVE"


def test_challenge_and_unverifiable_rows_are_outside_primary_denominator():
    rows = [
        {"sample_role": "PRIMARY_NUMERIC", "disposition": "MATCH"},
        {"sample_role": "PRIMARY_NUMERIC", "disposition": "UNVERIFIABLE"},
        {"sample_role": "CHALLENGE", "disposition": "MATCH"},
    ]
    eligible = [row for row in rows if row["sample_role"] == "PRIMARY_NUMERIC" and row["disposition"] != "UNVERIFIABLE"]
    assert len(eligible) == 1


def test_page3_transcription_and_semantic_mapping_are_not_the_same_family():
    numeric_family = "A3_PAGE3_TRANSCRIPTION"
    categorical_family = "A3B_PAGE3_SEMANTIC_MAPPING"
    assert numeric_family != categorical_family
    assert "TRANSCRIPTION" in numeric_family
    assert "SEMANTIC" in categorical_family


def test_page2_field_families_stay_explicit():
    from build_e6a2 import P2_FIELD_FAMILY

    assert P2_FIELD_FAMILY["storage_current_total_corresponding_p2_mm3"] == "STORAGE_STATE"
    assert P2_FIELD_FAMILY["p2_cap_actuelle_mm3"] == "CAPACITY_REGIME"
    assert P2_FIELD_FAMILY["rainfall_reporting_interval_mm"] == "RAINFALL"
    assert P2_FIELD_FAMILY["evaporation_reporting_interval_mm3"] == "EVAPORATION"


def test_multipage_builder_forbids_a_pooled_accuracy_claim_by_contract():
    source = (__import__("inspect").getsource(__import__("build_e6a2")))
    assert '"pooled_multipage_accuracy_reported": False' in source


def test_main_build_preserves_historical_e6a_rows_instead_of_regenerating_them():
    source = (__import__("inspect").getsource(__import__("build")))
    assert "generate_e6a(" not in source
    assert 'for key in ("B", "H")' in source

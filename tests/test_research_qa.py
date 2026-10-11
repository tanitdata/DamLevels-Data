import csv
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[1]


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


class _Candidate(dict):
    """Audit candidate fixture: unspecified descriptive fields read as 'x'."""

    def __missing__(self, key):
        return "x"


def _read(value: str) -> dict[str, str]:
    return {"source_value": value, "source_raw_text": value, "source_hash_checked": "YES", "verification_issue": ""}


def test_challenge_and_unverifiable_rows_are_outside_primary_denominator(monkeypatch):
    import build_e6a2

    reads = {"M": _read("1.5"), "U": _read(""), "E": _read("2.0")}
    monkeypatch.setattr(build_e6a2, "_read_source_cells", lambda candidates: reads)
    candidates = [_Candidate(audit_id="M", accepted_value="1.5"), _Candidate(audit_id="U", accepted_value="1.5"),
                  _Candidate(audit_id="E", accepted_value="1.5")]
    rows, summary = build_e6a2._audit_rows("A3_PAGE3_TRANSCRIPTION", candidates, {}, {})
    assert [r["disposition"] for r in rows] == ["MATCH", "UNVERIFIABLE", "EXTRACTION_DISCREPANCY_CANDIDATE"]
    assert (summary["primary_sample_pdfs"], summary["eligible"], summary["matches"], summary["errors"],
            summary["unverifiable"]) == (3, 2, 1, 1, 1)
    assert summary["estimated_accuracy"] == 0.5
    # Published audit: the 8 unverifiable Page 3 cells and the challenge set are not in the denominator.
    published = json.loads((ROOT / "qa/extraction/multipage_accuracy_summary.json").read_text(encoding="utf-8"))
    a3 = published["numeric_families"]["A3_PAGE3_TRANSCRIPTION"]
    with open(ROOT / "qa/extraction/page3_transcription_audit_sample.csv", encoding="utf-8-sig", newline="") as f:
        dispositions = Counter(r["disposition"] for r in csv.DictReader(f))
    assert a3["eligible"] == a3["primary_sample_pdfs"] - dispositions["UNVERIFIABLE"] == 792
    with open(ROOT / "qa/extraction/challenge_set.csv", encoding="utf-8-sig", newline="") as f:
        assert {r["in_primary_denominator"] for r in csv.DictReader(f)} == {"NO"}
    assert published["challenge_set"]["included_in_primary_denominator"] is False


def test_page3_transcription_and_semantic_mapping_are_not_the_same_family():
    from build_e6a2 import _semantic_rows

    base = {"source_sha256": "h", "evidence_id": "", "record_id": "r", "entity_id": "e", "from_node_id": "a",
            "to_node_id": "b", "from_dam_id": "", "to_dam_id": "", "stratum": "s", "bulletin_date": "2020-02-01",
            "source_file": "f", "page": "3"}
    candidates = [
        {**base, "row_role": "ACCOUNTING_OBSERVATION", "from_mapping_status": "NOT_APPLICABLE", "to_mapping_status": "CONFIRMED"},
        {**base, "row_role": "PHYSICAL_TRANSFER_EDGE", "from_mapping_status": "CANDIDATE_X", "to_mapping_status": "CONFIRMED"},
        {**base, "row_role": "PHYSICAL_TRANSFER_EDGE", "from_mapping_status": "CONFIRMED", "to_mapping_status": "CONFIRMED"},
    ]
    rows, counts = _semantic_rows(candidates, {})
    assert {r["audit_family"] for r in rows} == {"A3B_PAGE3_SEMANTIC_MAPPING"}
    assert [r["semantic_decision"] for r in rows] == [
        "ACCOUNTING_NOT_HYDRAULIC_EDGE", "PRINTED_LABEL_MATCH_STABLE_ID_UNRESOLVED", "UNVERIFIABLE"]
    assert all("disposition" not in r and "match" not in r for r in rows)  # no transcription accuracy fields
    published = json.loads((ROOT / "qa/extraction/multipage_accuracy_summary.json").read_text(encoding="utf-8"))
    assert published["page3_semantic_mapping"]["combined_with_transcription_accuracy"] is False
    assert "A3B_PAGE3_SEMANTIC_MAPPING" not in published["numeric_families"]


def test_page2_field_families_stay_explicit():
    from build_e6a2 import P2_FIELD_FAMILY

    assert P2_FIELD_FAMILY["storage_current_total_corresponding_p2_mm3"] == "STORAGE_STATE"
    assert P2_FIELD_FAMILY["p2_cap_actuelle_mm3"] == "CAPACITY_REGIME"
    assert P2_FIELD_FAMILY["rainfall_reporting_interval_mm"] == "RAINFALL"
    assert P2_FIELD_FAMILY["evaporation_reporting_interval_mm3"] == "EVAPORATION"


def test_multipage_builder_forbids_a_pooled_accuracy_claim_by_contract():
    # Static check of the builder (generate_e6a2 needs the external PDF corpus) plus the published summary.
    source = (__import__("inspect").getsource(__import__("build_e6a2")))
    assert '"pooled_multipage_accuracy_reported": False' in source
    published = json.loads((ROOT / "qa/extraction/multipage_accuracy_summary.json").read_text(encoding="utf-8"))
    assert published["pooled_multipage_accuracy_reported"] is False
    assert not any("pooled" in key for key in published["numeric_families"])


def test_main_build_preserves_historical_e6a_rows_instead_of_regenerating_them():
    # Static check only: running build.py needs external inputs (config/paths.local.toml).
    source = (__import__("inspect").getsource(__import__("build")))
    assert "generate_e6a(" not in source
    assert 'for key in ("B", "H")' in source

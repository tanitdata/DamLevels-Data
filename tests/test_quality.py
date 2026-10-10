from decimal import Decimal

from validate.quality import (
    apply_national_disposition,
    classify_fill_rounding,
    classify_national_total,
    classify_physical_validity,
    classify_transfer_candidate,
    duplicate_storage_keys,
)


def cap(status="KNOWN", value="10"):
    return {"status": status, "capacity_mm3": None if status != "KNOWN" else float(value), "matches": []}


def transfer(**overrides):
    row = {
        "row_role": "PHYSICAL_TRANSFER_EDGE",
        "from_dam_id": "a",
        "to_dam_id": "b",
        "value": "1.000",
        "source_consistency_status": "CHECKED",
    }
    row.update(overrides)
    return row


def test_uniqueness_detection_preserves_duplicate_records():
    rows = [
        {"observation_id": "one", "dam_id": "a", "date": "2024-01-01"},
        {"observation_id": "two", "dam_id": "a", "date": "2024-01-01"},
        {"observation_id": "three", "dam_id": "b", "date": "2024-01-01"},
    ]
    assert duplicate_storage_keys(rows) == {("a", "2024-01-01"): ["one", "two"]}


def test_physical_negative_and_above_capacity_and_unavailable():
    assert classify_physical_validity(Decimal("-0.001"), cap()) == "NEGATIVE_STORAGE"
    assert classify_physical_validity(Decimal("10.001"), cap()) == "ABOVE_CAPACITY"
    assert classify_physical_validity(Decimal("5"), cap("UNAVAILABLE")) == "CAPACITY_UNAVAILABLE"


def test_printed_fill_rounding_interval():
    match = classify_fill_rounding(Decimal("5.004"), cap(), Decimal("50.0"), 1)
    mismatch = classify_fill_rounding(Decimal("5.006"), cap(), Decimal("50.0"), 1)
    assert match[0] == "MATCH_WITHIN_ROUNDING"
    assert mismatch[0] == "MISMATCH"


def test_national_total_exact_rounding_and_mismatch():
    exact = classify_national_total(Decimal("10.000"), Decimal("10.000"), 2, Decimal("0.001"))
    rounded = classify_national_total(Decimal("10.001"), Decimal("10.000"), 2, Decimal("0.001"))
    mismatch = classify_national_total(Decimal("10.100"), Decimal("10.000"), 2, Decimal("0.001"))
    assert exact[0] == "MATCH_EXACT"
    assert rounded[0] == "MATCH_WITHIN_ROUNDING"
    assert mismatch[0] == "SOURCE_PRINTED_DISAGREEMENT"


def test_known_roster_scope_disposition_qualifies_only_supported_disagreement():
    evidence = {
        "2015-10-03": {
            "bulletin_date": "2015-10-03",
            "classification": "SOURCE_ROSTER_SCOPE_DIFFERENCE",
            "status": "SUPPORTED_BY_PRESERVED_AUDIT_EVIDENCE",
        }
    }
    classification, disposition = apply_national_disposition(
        "2015-10-03", "SOURCE_PRINTED_DISAGREEMENT", evidence
    )
    untouched, no_disposition = apply_national_disposition(
        "2017-12-30", "SOURCE_PRINTED_DISAGREEMENT", evidence
    )
    assert classification == "SOURCE_ROSTER_SCOPE_DIFFERENCE"
    assert disposition is evidence["2015-10-03"]
    assert untouched == "SOURCE_PRINTED_DISAGREEMENT"
    assert no_disposition is None


def test_transfer_eligible_direct_exact_comparison():
    classification, reasons = classify_transfer_candidate(
        transfer(), date_semantics_resolved=True, counterpart_value=Decimal("1.000")
    )
    assert classification == "MATCH_EXACT"
    assert reasons == []


def test_transfer_accounting_row_is_excluded():
    classification, _ = classify_transfer_candidate(
        transfer(row_role="ACCOUNTING_OBSERVATION"),
        date_semantics_resolved=True,
        counterpart_value=Decimal("1.000"),
    )
    assert classification == "ACCOUNTING_NOT_HYDRAULIC_EDGE"


def test_transfer_unresolved_endpoint_is_excluded():
    classification, _ = classify_transfer_candidate(
        transfer(to_dam_id=""), date_semantics_resolved=True, counterpart_value=Decimal("1.000")
    )
    assert classification == "UNRESOLVED_DAM_CROSSWALK"


def test_transfer_date_semantics_are_not_assumed():
    classification, _ = classify_transfer_candidate(
        transfer(), date_semantics_resolved=False, counterpart_value=Decimal("1.000")
    )
    assert classification == "DATE_SEMANTICS_UNRESOLVED"

from pydantic import ValidationError
import pytest

from validate.models import StorageObservation, TransferObservation


def storage_row(**overrides):
    row = {
        "observation_id": "STO-test",
        "dam_id": "dam-a",
        "date": "2024-01-01",
        "variable": "storage",
        "value": "12.345",
        "unit": "Mm3",
        "source_file": "1-1-2024_1.pdf",
        "source_sha256": "a" * 64,
        "page": "1",
        "source_field": "p1_stock_today_mm3",
        "authority_release": "TEST_ACCEPTED",
        "engine_version": "test",
        "source_row_key": "PAGE_1|2024-01-01|dam-a",
        "lineage_id": "LIN-test",
        "flag": "TEST_ONLY",
    }
    row.update(overrides)
    return row


def transfer_row(**overrides):
    row = {
        "transfer_observation_id": "P3-test",
        "date": "2024-01-01",
        "bulletin_date": "2024-01-01",
        "effective_date_rule": "SAME_DAY",
        "from_dam_id": "dam-a",
        "to_dam_id": "dam-b",
        "from_node_id": "NODE-A",
        "to_node_id": "NODE-B",
        "from_mapping_status": "CONFIRMED",
        "to_mapping_status": "CONFIRMED",
        "entity_id": "ROUTE-A-B",
        "row_role": "PHYSICAL_TRANSFER_EDGE",
        "variable": "today",
        "value": "1.000",
        "unit": "Mm3",
        "source_file": "1-1-2024_3.pdf",
        "source_sha256": "b" * 64,
        "page": "3",
        "source_field": "p3_t5_transfer_day_mm3",
        "authority_release": "PAGE3_TEST_PROBABLE",
        "flag": "PAGE3_PROBABLE|TEST_ONLY",
        "semantic_status": "PROBABLE_PHYSICAL_TRANSFER_EDGE",
        "value_status": "PRESENT_NUMERIC",
        "continuity_status": "PRESENT_NUMERIC",
        "source_consistency_status": "CHECKED",
        "evidence_id": "EV-test",
        "record_id": "T5-test",
        "series_id": "SERIES-test",
        "raw_text": "1,000",
    }
    row.update(overrides)
    return row


def test_storage_model_accepts_valid_row():
    model = StorageObservation.model_validate(storage_row())
    assert str(model.value) == "12.345"


def test_storage_model_rejects_fill_row():
    with pytest.raises(ValidationError):
        StorageObservation.model_validate(storage_row(variable="printed_fill_pct", unit="percent"))


def test_storage_model_rejects_missing_as_zero_substitution():
    with pytest.raises(ValidationError):
        StorageObservation.model_validate(storage_row(value=""))


def test_transfer_model_requires_probable_authority():
    with pytest.raises(ValidationError):
        TransferObservation.model_validate(transfer_row(authority_release="PAGE3_ACCEPTED", flag="TEST_ONLY"))


def test_transfer_model_accepts_qualified_blank_value_state():
    model = TransferObservation.model_validate(
        transfer_row(value="", value_status="SOURCE_BLANK", continuity_status="SOURCE_BLANK")
    )
    assert model.value is None

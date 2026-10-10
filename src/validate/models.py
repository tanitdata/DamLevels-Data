"""Pydantic contracts for the public engineering tables.

These models validate representation and uncertainty states. They do not
repair, impute, or reinterpret scientific values.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _none_if_blank(value):
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _require_text(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _validate_sha(value: str, field_name: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


class CsvContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Dam(CsvContract):
    dam_id: str
    name_fr: str
    name_ar: str = ""
    name_ar_status: str
    name_ar_source: str = ""
    aliases: str = ""
    basin: str = ""
    basin_status: str
    basin_source: str = ""
    reference_capacity_mm3: Decimal | None = None
    capacity_valid_from: date | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    status: str
    geometry_status: str
    control_status: str
    identity_source: str
    coordinate_source: str
    capacity_source: str
    notes: str = ""

    _optional_values = field_validator(
        "reference_capacity_mm3", "capacity_valid_from", "latitude", "longitude",
        mode="before",
    )(_none_if_blank)

    @field_validator("dam_id", "name_fr", "status", "identity_source")
    @classmethod
    def required_text(cls, value: str, info):
        return _require_text(value, info.field_name)


class CapacityRegime(CsvContract):
    dam_id: str
    valid_from: date
    valid_to: date | None = None
    capacity_mm3: Decimal
    source: str
    source_file: str
    page: Literal["2"]
    status: str
    notes: str = ""

    _optional_end = field_validator("valid_to", mode="before")(_none_if_blank)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.capacity_mm3 <= 0:
            raise ValueError("capacity_mm3 must be positive")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to precedes valid_from")
        return self


class BulletinManifestRecord(CsvContract):
    bulletin_id: str
    bulletin_date: date
    original_url: str = ""
    page1_source_file: str = ""
    page1_sha256: str = ""
    page2_source_file: str = ""
    page2_sha256: str = ""
    page3_source_file: str = ""
    page3_sha256: str = ""
    pages_available: str
    status: str
    provenance_status: str
    notes: str = ""

    @model_validator(mode="after")
    def source_hash_pairs(self):
        for page in ("1", "2", "3"):
            source = getattr(self, f"page{page}_source_file")
            digests = getattr(self, f"page{page}_sha256")
            if bool(source) != bool(digests):
                raise ValueError(f"Page {page} source/hash presence differs")
            if digests:
                for digest in digests.split("|"):
                    _validate_sha(digest, f"page{page}_sha256")
        return self


class StorageObservation(CsvContract):
    observation_id: str
    dam_id: str
    date: date
    variable: Literal["storage"]
    value: Decimal
    unit: Literal["Mm3"]
    source_file: str
    source_sha256: str
    page: Literal["1"]
    source_field: Literal["p1_stock_today_mm3"]
    authority_release: str
    engine_version: str
    source_row_key: str
    lineage_id: str
    flag: str

    @field_validator("source_sha256")
    @classmethod
    def sha256_contract(cls, value: str):
        return _validate_sha(value, "source_sha256")

    @field_validator(
        "observation_id", "dam_id", "source_file", "authority_release",
        "source_row_key", "lineage_id", "flag",
    )
    @classmethod
    def required_text(cls, value: str, info):
        return _require_text(value, info.field_name)


class TransferObservation(CsvContract):
    transfer_observation_id: str
    date: date
    bulletin_date: date
    effective_date_rule: str
    from_dam_id: str = ""
    to_dam_id: str = ""
    from_node_id: str = ""
    to_node_id: str = ""
    from_mapping_status: str
    to_mapping_status: str
    entity_id: str
    row_role: Literal["PHYSICAL_TRANSFER_EDGE", "ACCOUNTING_OBSERVATION"]
    variable: Literal["today", "current_season_to_date", "previous_season_to_date"]
    value: Decimal | None = None
    unit: Literal["Mm3"]
    source_file: str
    source_sha256: str
    page: Literal["3"]
    source_field: str
    authority_release: str
    flag: str
    semantic_status: str
    value_status: str
    continuity_status: str
    source_consistency_status: str
    evidence_id: str
    record_id: str
    series_id: str
    raw_text: str = ""

    _optional_value = field_validator("value", mode="before")(_none_if_blank)

    @field_validator("source_sha256")
    @classmethod
    def sha256_contract(cls, value: str):
        return _validate_sha(value, "source_sha256")

    @model_validator(mode="after")
    def qualified_page3(self):
        if "PROBABLE" not in self.authority_release or "PAGE3_PROBABLE" not in self.flag:
            raise ValueError("Page 3 authority qualification is required")
        if self.value_status in {"PRESENT_NUMERIC", "PRESENT_ZERO"} and self.value is None:
            raise ValueError("present Page 3 value state requires a value")
        return self

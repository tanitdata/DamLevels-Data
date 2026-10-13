"""data/bulletin_page1.csv: the full Page 1 table against the other published files.

Needs nothing outside the repository. The stock and fill columns must equal the
already published storage and printed-fill tables, every value column must equal
the Page 1 input of the current quality indicators (qa/kpi/inputs/page1.parquet),
so the KPI checks K09-K11 cover this table too.
"""
from __future__ import annotations

import csv
import json
import math
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from build_page1_table import FIELDS, TEXT_VALUE_FIELDS, VALUE_FIELDS

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "data/bulletin_page1.csv"
PARQUET = ROOT / "data/parquet/bulletin_page1.parquet"
NUMERIC_FIELDS = [field for field in VALUE_FIELDS if field not in TEXT_VALUE_FIELDS]

# Column names of the KPI input for the same Page 1 extraction.
KPI_COLUMNS = {
    "p1_apport_today": "inflow_reporting_interval_mm3",
    "p1_apport_cumul_this_month": "inflow_month_to_date_mm3",
    "p1_apport_average_month": "inflow_reference_month_total_mm3",
    "p1_apport_cumul_since_sep": "inflow_hydraulic_year_to_date_mm3",
    "p1_apport_cumul_prev_year": "inflow_previous_year_comparable_period_mm3",
    "p1_apport_average_period": "inflow_reference_cumulative_through_observation_date_mm3",
    "p1_release_action_code": "operation_codes_raw",
    "p1_release_yesterday": "outflow_reporting_interval_mm3",
    "p1_release_today": "outflow_previous_year_reference_interval_mm3",
    "p1_release_cumul_this_month": "outflow_month_to_date_mm3",
    "p1_release_cumul_year": "outflow_hydraulic_year_to_date_mm3",
    "p1_release_cumul_last_year": "outflow_previous_year_comparable_period_mm3",
    "p1_stock_fill_pct": "storage_fill_pct_of_last_survey_useful_capacity",
    "p1_stock_today_mm3": "storage_current_total_mm3",
    "p1_stock_last_year_mm3": "storage_previous_year_reference_mm3",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def table() -> list[dict[str, str]]:
    return _rows(TABLE)


@lru_cache(maxsize=1)
def by_key() -> dict[str, dict[str, str]]:
    return {row["source_row_key"]: row for row in table()}


def test_shape_header_and_keys():
    with TABLE.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == FIELDS
    rows = table()
    assert len(rows) == 129391
    assert len(by_key()) == len(rows)
    assert len({(row["dam_id"], row["bulletin_date"]) for row in rows}) == len(rows)
    for row in rows:
        assert row["source_row_key"] == f"PAGE_1|{row['bulletin_date']}|{row['dam_id']}"
    dam_ids = {row["dam_id"] for row in _rows(ROOT / "data/dams.csv")}
    assert {row["dam_id"] for row in rows} == dam_ids
    dates = {row["bulletin_date"] for row in rows}
    assert len(dates) == 3981
    assert min(dates) == "2014-07-02" and max(dates) == "2025-10-10"


def test_bytes_are_lf_utf8_without_bom():
    head = TABLE.read_bytes()[:4096]
    assert not head.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in head


def test_values_are_numbers_or_blank_never_filled():
    blanks = {field: 0 for field in VALUE_FIELDS}
    for row in table():
        for field in NUMERIC_FIELDS:
            value = row[field]
            if value == "":
                blanks[field] += 1
                continue
            number = float(value)
            assert math.isfinite(number)
            assert value == format(number, ".15g"), (row["source_row_key"], field, value)
        code = row["p1_release_action_code"]
        if code:
            assert re.fullmatch(r"[A-Za-z]+(,[A-Za-z]+)*", code), (row["source_row_key"], code)
        else:
            blanks["p1_release_action_code"] += 1
    # Blank cells are the cells the bulletin left empty or unreadable; none is replaced by zero.
    assert blanks["p1_stock_today_mm3"] == 1
    assert blanks["p1_stock_fill_pct"] == 44771
    assert blanks["p1_release_cumul_this_month"] == 0


def test_fill_printed_only_in_the_16_column_layout():
    for row in table():
        assert row["layout"] in {"P1_LAYOUT_16_WITH_FILL", "P1_LAYOUT_15_NO_FILL"}
        assert (row["p1_stock_fill_pct"] != "") == (row["layout"] == "P1_LAYOUT_16_WITH_FILL")


def test_stock_column_equals_published_storage():
    storage = _rows(ROOT / "data/storage.csv")
    assert sum(1 for row in table() if row["p1_stock_today_mm3"]) == len(storage)
    for obs in storage:
        row = by_key()[obs["source_row_key"]]
        assert row["p1_stock_today_mm3"] == obs["value"]
        assert (row["dam_id"], row["bulletin_date"]) == (obs["dam_id"], obs["date"])
        assert (row["source_file"], row["source_sha256"], row["page"]) == (
            obs["source_file"], obs["source_sha256"], obs["page"]
        )
        assert (row["engine_version"], row["authority_release"]) == (
            obs["engine_version"], obs["authority_release"]
        )


def test_fill_column_equals_published_printed_fill():
    fill = _rows(ROOT / "qa/printed_fill_reference.csv")
    assert sum(1 for row in table() if row["p1_stock_fill_pct"]) == len(fill)
    for obs in fill:
        row = by_key()[obs["source_row_key"]]
        assert row["p1_stock_fill_pct"] == obs["value"]
        assert row["source_sha256"] == obs["source_sha256"]


def test_every_row_points_to_the_manifest_page1_file():
    manifest = {row["bulletin_date"]: row for row in _rows(ROOT / "sources/manifest.csv")}
    for row in table():
        entry = manifest[row["bulletin_date"]]
        assert (row["source_file"], row["source_sha256"]) == (entry["page1_source_file"], entry["page1_sha256"])
        assert row["page"] == "1"


def test_values_equal_the_kpi_page1_input():
    kpi = pq.read_table(ROOT / "qa/kpi/inputs/page1.parquet").to_pylist()
    assert len(kpi) == len(table())
    index = {(row["dam_id"], row["bulletin_date"]): row for row in table()}
    for source in kpi:
        row = index[(source["dam_id_canonical"], str(source["bulletin_observation_date"])[:10])]
        for field, kpi_field in KPI_COLUMNS.items():
            expected = source[kpi_field]
            if field in TEXT_VALUE_FIELDS:
                assert row[field] == (expected or ""), (row["source_row_key"], field)
            elif expected is None or (isinstance(expected, float) and math.isnan(expected)):
                assert row[field] == "", (row["source_row_key"], field)
            else:
                assert row[field] != "" and float(row[field]) == pytest.approx(float(expected), abs=5e-7), (
                    row["source_row_key"], field
                )


def test_parquet_mirrors_csv():
    parquet = pq.read_table(PARQUET)
    assert parquet.schema.names == FIELDS
    rows = parquet.to_pylist()
    assert len(rows) == len(table())
    for csv_row, pq_row in zip(table(), rows, strict=True):
        for field in FIELDS:
            value = pq_row[field]
            if field in NUMERIC_FIELDS:
                if csv_row[field] == "":
                    assert value is None
                else:
                    assert Decimal(csv_row[field]) == Decimal(str(value))
            else:
                assert csv_row[field] == (value if value is not None else "")


def test_value_columns_are_the_dlo_page1_columns():
    ttl = (ROOT / "ontology/DLO_0.3_VIEW_20260929-2345.ttl").read_text(encoding="utf-8")
    mapped = set(re.findall(r"mapping/P1_observations/(p1_[a-z0-9_]+)>", ttl))
    assert set(VALUE_FIELDS) == mapped


def test_descriptor_matches_the_table():
    descriptor = json.loads((ROOT / "datapackage.json").read_text(encoding="utf-8"))
    resources = {resource["name"]: resource for resource in descriptor["resources"]}
    for name, path in (("bulletin-page1", "data/bulletin_page1.csv"),
                       ("bulletin-page1-parquet", "data/parquet/bulletin_page1.parquet")):
        resource = resources[name]
        assert resource["path"] == path
        fields = resource["schema"]["fields"]
        assert [field["name"] for field in fields] == FIELDS
        assert all(field.get("description") for field in fields)

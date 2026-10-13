"""data/bulletin_page2.csv: the full Page 2 table against the other published files.

Needs nothing outside the repository. Every value column must equal the Page 2
input of the current quality indicators (qa/kpi/inputs/page2.parquet), the
Page 1/Page 2 agreement must reproduce KPI K09, every capacity regime must be the
printed useful capacity, and the previous-hydraulic-year columns must behave as
their names say.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pyarrow.parquet as pq

from build_page2_table import FIELDS, SOURCE_COLUMNS, VALUE_FIELDS

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "data/bulletin_page2.csv"
PARQUET = ROOT / "data/parquet/bulletin_page2.parquet"
CUTOFF = "2024-04-27"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def table() -> list[dict[str, str]]:
    return _rows(TABLE)


@lru_cache(maxsize=1)
def by_dam_date() -> dict[tuple[str, str], dict[str, str]]:
    return {(row["dam_id"], row["bulletin_date"]): row for row in table()}


def test_shape_header_and_keys():
    with TABLE.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == FIELDS
    rows = table()
    assert len(rows) == 129472
    assert len(by_dam_date()) == len(rows)
    for row in rows:
        assert row["source_row_key"] == f"PAGE_2|{row['bulletin_date']}|{row['dam_id']}"
        assert row["page"] == "2"
        assert row["region"] in {"nord", "centre", "cap_bon"}
        assert row["row_detection"] in {"TEXT_LABEL_EXACT_NORMALIZED", "RECOVERED_ROSTER_IDENTIFIED_ROW"}
    dam_ids = {row["dam_id"] for row in _rows(ROOT / "data/dams.csv")}
    assert {row["dam_id"] for row in rows} == dam_ids
    dates = {row["bulletin_date"] for row in rows}
    assert len(dates) == 3983
    assert min(dates) == "2014-07-02" and max(dates) == "2025-10-10"
    assert sum(row["row_detection"] != "TEXT_LABEL_EXACT_NORMALIZED" for row in rows) == 2


def test_bytes_are_lf_utf8_without_bom_and_under_50_mb():
    data = TABLE.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in data[:4096]
    assert len(data) < 50 * 1024 * 1024


def test_values_are_numbers_or_blank_never_filled():
    for row in table():
        for field in VALUE_FIELDS:
            value = row[field]
            if value:
                number = float(value)
                assert math.isfinite(number)
                assert value == format(number, ".15g"), (row["source_row_key"], field, value)
    # One storage cell per printed row may be blank on Page 2; no blank is replaced by zero.
    blanks = sum(1 for row in table() if not row["storage_current_total_corresponding_p2_mm3"])
    assert blanks == 359


def test_column_23_changes_meaning_on_2024_04_27():
    for row in table():
        before = row["bulletin_date"] < CUTOFF
        assert row["layout"] == ("PRE_CUTOFF_MONTH_TO_DATE_INFLOW" if before else "POST_CUTOFF_INTERVAL_EVAPORATION")
        if before:
            assert row["evaporation_reporting_interval_mm3"] == ""
        else:
            assert row["inflow_month_to_date_p2_mm3"] == ""


def test_every_row_points_to_the_manifest_page2_file():
    manifest = {row["bulletin_date"]: row for row in _rows(ROOT / "sources/manifest.csv")}
    for row in table():
        entry = manifest[row["bulletin_date"]]
        assert (row["source_file"], row["source_sha256"]) == (entry["page2_source_file"], entry["page2_sha256"])


def test_values_equal_the_kpi_page2_input():
    kpi = pq.read_table(ROOT / "qa/kpi/inputs/page2.parquet").to_pylist()
    assert len(kpi) == len(table())
    for source in kpi:
        row = by_dam_date()[(source["dam_id_canonical"], str(source["bulletin_observation_date"])[:10])]
        for field in VALUE_FIELDS:
            expected = source[field]
            if expected is None or (isinstance(expected, float) and math.isnan(expected)):
                assert row[field] == "", (row["source_row_key"], field)
            else:
                assert row[field] != "" and Decimal(row[field]) == Decimal(str(expected)).normalize() or \
                    float(row[field]) == float(expected), (row["source_row_key"], field)


def test_page1_page2_agreement_reproduces_kpi_k09():
    kpi = {row["kpi_id"]: row for row in _rows(ROOT / "qa/kpi/results/KPI_RESULTS.csv")}
    page1 = {(row["dam_id"], row["bulletin_date"]): row for row in _rows(ROOT / "data/bulletin_page1.csv")}
    pairs = {
        "K09a": ("p1_stock_today_mm3", "storage_current_total_corresponding_p2_mm3"),
        "K09b": ("p1_apport_today", "inflow_reporting_interval_p2_mm3"),
        "K09c": ("p1_release_yesterday", "outflow_reporting_interval_p2_mm3"),
    }
    for kpi_id, (p1_field, p2_field) in pairs.items():
        both = exact = 0
        for key, row in by_dam_date().items():
            other = page1.get(key)
            if other is None or not other[p1_field] or not row[p2_field]:
                continue
            both += 1
            exact += Decimal(other[p1_field]) == Decimal(row[p2_field])
        assert (exact, both) == (int(kpi[kpi_id]["numerator"]), int(kpi[kpi_id]["denominator"])), kpi_id


def test_capacity_regimes_are_printed_useful_capacity():
    for regime in _rows(ROOT / "data/capacity_history.csv"):
        row = by_dam_date()[(regime["dam_id"], regime["valid_from"])]
        assert row["source_file"] == regime["source_file"]
        assert Decimal(row["useful_capacity_at_last_bathymetric_survey_mm3"]) == Decimal(regime["capacity_mm3"])


def _season(day: str) -> int:
    d = date.fromisoformat(day)
    # The bulletin of 2 September opens the new hydraulic year (it reports on 1 September).
    return d.year if (d.month, d.day) >= (9, 2) else d.year - 1


def test_previous_year_columns_are_constant_within_a_hydraulic_year():
    values: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in table():
        if row["previous_hydraulic_year_end_water_level_m"]:
            values[(row["dam_id"], _season(row["bulletin_date"]))].add(row["previous_hydraulic_year_end_water_level_m"])
    constant = sum(len(v) == 1 for v in values.values())
    # The rest change mid-year, e.g. a few January 2021 bulletins; they are kept as printed.
    assert (constant, len(values)) == (378, 410)


def test_previous_year_storage_is_the_storage_printed_on_1_september():
    storage = {(row["dam_id"], row["date"]): Decimal(row["value"]) for row in _rows(ROOT / "data/storage.csv")}
    per_season: dict[tuple[str, int], list[str]] = defaultdict(list)
    for row in table():
        if row["previous_hydraulic_year_end_storage_mm3"]:
            per_season[(row["dam_id"], _season(row["bulletin_date"]))].append(row["previous_hydraulic_year_end_storage_mm3"])
    compared = equal = 0
    for (dam_id, year), printed in per_season.items():
        reference = storage.get((dam_id, f"{year}-09-01"))
        if reference is None:
            continue
        value = Decimal(max(set(printed), key=printed.count))
        compared += 1
        # Printed with 2 decimals here and 3 decimals on Page 1.
        equal += abs(value - reference) <= Decimal("0.0055")
    assert (equal, compared) == (377, 383)


def test_parquet_mirrors_csv():
    parquet = pq.read_table(PARQUET)
    assert parquet.schema.names == FIELDS
    rows = parquet.to_pylist()
    assert len(rows) == len(table())
    for csv_row, pq_row in zip(table(), rows, strict=True):
        for field in FIELDS:
            value = pq_row[field]
            if field in VALUE_FIELDS:
                if csv_row[field] == "":
                    assert value is None
                else:
                    assert Decimal(csv_row[field]) == Decimal(str(value))
            else:
                assert csv_row[field] == value


def test_value_columns_are_the_dlo_page2_columns():
    ttl = (ROOT / "ontology/DLO_0.3_VIEW_20260929-2345.ttl").read_text(encoding="utf-8")
    mapped = set(re.findall(r"mapping/P2_observations/([a-z0-9_]+)>", ttl))
    assert set(SOURCE_COLUMNS.values()) == mapped


def test_descriptor_matches_the_table():
    descriptor = json.loads((ROOT / "datapackage.json").read_text(encoding="utf-8"))
    resources = {resource["name"]: resource for resource in descriptor["resources"]}
    for name, path in (("bulletin-page2", "data/bulletin_page2.csv"),
                       ("bulletin-page2-parquet", "data/parquet/bulletin_page2.parquet")):
        resource = resources[name]
        assert resource["path"] == path
        fields = resource["schema"]["fields"]
        assert [field["name"] for field in fields] == FIELDS
        assert all(field.get("description") for field in fields)

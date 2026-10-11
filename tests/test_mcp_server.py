"""Tests for the DamLevels MCP server (mcp_server/damlevels_mcp).

The query logic is checked against the published tables; the MCP layer is
checked in-process. Skipped when the mcp package is not installed.
"""
import asyncio
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))

from damlevels_mcp.core import ATTRIBUTION, DamData, QueryError  # noqa: E402


@pytest.fixture(scope="module")
def data():
    return DamData(ROOT)


@pytest.fixture(scope="module")
def storage_csv():
    with open(ROOT / "data" / "storage.csv", encoding="utf-8-sig", newline="") as f:
        return {(r["dam_id"], r["date"]): r for r in csv.DictReader(f)}


def test_every_answer_carries_coverage_and_attribution(data):
    out = data.dataset_info()
    assert out["coverage"]["first_date"] == "2014-07-02"
    assert out["coverage"]["last_date"] == "2025-10-10"
    assert out["attribution"] == ATTRIBUTION and "ONAGRI" in ATTRIBUTION
    assert out["result"]["storage_observations"] == 129390


def test_list_dams(data):
    dams = data.list_dams()["result"]
    assert len(dams) == 36
    sarrat = next(d for d in dams if d["dam_id"] == "sarrat")
    assert sarrat["first_date"] == "2021-04-08"


@pytest.mark.parametrize("query, dam_id", [
    ("Sidi Salem", "sidisalem"), ("سيدي سالم", "sidisalem"), ("S. EL BARRAK", "sidielbarrak"),
    ("sidielbarrak", "sidielbarrak"), ("Bir M'Cherga", "birmcherga"), ("EL BREK", "brek"),
])
def test_find_dam(data, query, dam_id):
    assert data.resolve_dam(query) == dam_id


def test_find_dam_ambiguous_returns_candidates(data):
    out = data.find_dam("Sidi")["result"]
    assert out["match"] is None
    assert {"sidisalem", "sidielbarrak", "sidisaad", "sidiaich"} <= {c["dam_id"] for c in out["candidates"]}


def test_storage_values_equal_published_table(data, storage_csv):
    out = data.get_storage("sidielbarrak", "2020-01-01", "2020-03-31")["result"]
    expected = sorted(d for (dam, d) in storage_csv if dam == "sidielbarrak" and "2020-01-01" <= d <= "2020-03-31")
    assert [p["date"] for p in out["series"]] == expected
    for point in out["series"]:
        assert point["storage_mm3"] == float(storage_csv[("sidielbarrak", point["date"])]["value"])
    # Bulletin dates without a value are reported, not filled.
    bulletins = [d for d in data.page1_dates if "2020-01-01" <= d <= "2020-03-31"]
    assert out["missing_dates"] == sorted(set(bulletins) - set(expected))
    assert out["values_found"] + out["missing_count"] == len(bulletins)
    assert out["calendar_days_without_bulletin"] == 91 - len(bulletins)  # Q1 2020 has 91 calendar days


def test_missing_days_are_listed_not_filled(data, storage_csv):
    # Pick a dam/date pair where a Page 1 bulletin exists but the dam has no value.
    out = data.get_storage("melah", "2019-01-01", "2025-10-10", resolution="monthly")["result"]
    assert out["missing_count"] == len({d for d in data.page1_dates if "2019-01-26" <= d <= "2025-10-10"}) - out["values_found"]
    for d in out["missing_dates"]:
        assert ("melah", d) not in storage_csv


def test_monthly_resolution_and_row_limit(data):
    with pytest.raises(QueryError) as err:
        data.get_storage("sidisalem", "2015-01-01", "2020-01-01")
    assert err.value.code == "TOO_MANY_ROWS"
    months = data.get_storage("sidisalem", "2024-01-01", "2024-03-31", resolution="monthly")["result"]["series"]
    assert [m["month"] for m in months] == ["2024-01", "2024-02", "2024-03"]


@pytest.mark.parametrize("call", [
    lambda d: d.get_fill("sidisalem", "2026-01-01"),
    lambda d: d.get_storage("sidisalem", "2014-01-01", "2014-12-31"),
    lambda d: d.national_storage("2025-10-11"),
])
def test_dates_outside_the_record_are_refused(data, call):
    with pytest.raises(QueryError) as err:
        call(data)
    assert err.value.code == "OUTSIDE_RECORD"


def test_fill_uses_capacity_in_force_and_matches_printed_fill(data):
    out = data.get_fill("sidielbarrak", "2020-02-01")["result"]
    assert out["storage_mm3"] == 283.496
    assert out["capacity"] == {"status": "KNOWN", "capacity_mm3": 286.51}
    assert out["fill_pct"] == out["printed_fill_pct"] == 98.9


def test_fill_on_a_day_without_value_is_not_substituted(data):
    out = data.get_fill("sarrat", "2020-02-01")["result"]
    assert out["status"] == "NO_VALUE" and out["storage_mm3"] is None and out["fill_pct"] is None
    assert out["next_value_date"] == "2021-04-08"


def test_national_storage_equals_sum_and_printed_total(data, storage_csv):
    out = data.national_storage("2020-02-01")["result"]
    expected = round(sum(float(r["value"]) for (d, day), r in storage_csv.items() if day == "2020-02-01"), 3)
    assert out["total_mm3"] == expected == 1471.419
    assert out["dams_with_value"] == 33
    assert out["printed_national_total_mm3"] == 1471.421
    assert out["fill_pct_of_known_capacity"] == 65.3  # the bulletin prints 65,3 % for TOTAL


def test_compare_years_uses_exact_dates_only(data, storage_csv):
    series = data.compare_years("Sidi Salem", "10-10")["result"]["series"]
    assert [p["date"][:4] for p in series] == [str(y) for y in range(2014, 2026)]
    for p in series:
        row = storage_csv.get(("sidisalem", p["date"]))
        assert p["storage_mm3"] == (float(row["value"]) if row else None)


def test_get_source_matches_lineage(data):
    out = data.get_source("sidielbarrak", "2020-02-01")["result"]
    assert out["source_file"] == "01-02-2020_1.pdf"
    assert out["source_sha256"].startswith("0bb40123")
    assert out["bulletin_url"] == "https://www.onagri.nat.tn/uploads/barrages/01-02-2020.pdf"
    assert out["cell"]["physical_column"] == "14"
    assert out["cell"]["printed_text"] == "283,496"


def test_transfers_are_flagged_probable(data):
    out = data.get_transfers("2020-02-01", "2020-02-01")
    rows = out["result"]["rows"]
    assert rows and all("PROBABLE" in r["authority"] for r in rows)
    assert any("day before the bulletin" in n for n in out["notes"])


def test_describe_variable_from_ontology():
    pytest.importorskip("rdflib")
    from damlevels_mcp.ontology import Ontology

    onto = Ontology(ROOT)
    assert onto.describe("الإيرادات")["concept"] == "inflow volume"
    release = onto.describe("p1_release_today")
    rules = {c["column"]: c["time_rule"] for c in release["printed_columns"]}
    assert rules["p1_release_today"] == "amount over the same day one year earlier"
    assert rules["p1_release_yesterday"] == "amount over the day before the bulletin"
    assert onto.describe("p2_rs_unresolved_prohibited")["concept"] is None


def test_mcp_server_lists_read_only_tools_and_answers():
    pytest.importorskip("mcp")
    from damlevels_mcp.server import build_server

    server = build_server(ROOT)

    async def run():
        tools = await server.list_tools()
        resources = await server.list_resources()
        error = await server.call_tool("get_fill", {"dam": "Sidi Salem", "date": "2026-03-01"})
        return tools, resources, error

    tools, resources, error = asyncio.run(run())
    names = {t.name for t in tools}
    assert names == {"dataset_info", "list_dams", "find_dam", "get_storage", "get_fill", "national_storage",
                     "compare_years", "get_source", "get_transfers", "describe_variable"}
    assert all(t.annotations.readOnlyHint for t in tools)
    assert {str(r.uri) for r in resources} == {"damlevels://docs/data-dictionary", "damlevels://docs/known-issues",
                                              "damlevels://docs/licence"}
    content = error[0] if isinstance(error, tuple) else error
    payload = json.loads(content[0].text)
    assert payload["error"] == "OUTSIDE_RECORD"

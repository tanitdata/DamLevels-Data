"""Tests for the DamLevels MCP server (mcp_server/damlevels_mcp).

The query logic is checked against the published tables; the MCP layer is
checked in-process and over real stdio (the server started as a subprocess
with `python -m damlevels_mcp`). MCP tests are skipped when the mcp package
is not installed.
"""
import asyncio
import csv
import json
import os
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
    assert "day before bulletin date" in out["result"]["time_rule"]
    assert any("SAME_DAY" in n and "bulletin date" in n for n in out["notes"])
    season = data.get_transfers("2020-02-01", "2020-02-01", measure="current_season_to_date")["result"]
    assert "1 September" in season["time_rule"] and "not a daily amount" in season["time_rule"]


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


# --------------------------------------------------------------- review fixes
@pytest.fixture(scope="module")
def transfers_csv():
    with open(ROOT / "data" / "transfers.csv", encoding="utf-8-sig", newline="") as f:
        return {r["transfer_observation_id"]: r for r in csv.DictReader(f)}


def test_partial_bulletin_is_not_reported_as_no_bulletin(data):
    # 2022-05-03 has Page 2 in the manifest but no Page 1.
    out = data.get_storage("sidisalem", "2022-05-03", "2022-05-03")["result"]
    assert out["values_found"] == 0 and out["missing_count"] == 0
    assert out["bulletins_without_page1"] == ["2022-05-03"] and out["bulletins_without_page1_count"] == 1
    assert out["calendar_days_without_bulletin"] == 0
    q1 = data.get_storage("sidielbarrak", "2020-01-01", "2020-03-31")["result"]
    in_q1 = [d for d in data.bulletin_dates if "2020-01-01" <= d <= "2020-03-31"]
    assert q1["bulletins_in_dam_period"] == len(in_q1)
    assert q1["calendar_days_without_bulletin"] == 91 - len(in_q1)


def test_monthly_mean_is_exact_decimal_half_even(data, storage_csv):
    from decimal import ROUND_HALF_EVEN, Decimal

    for dam, month, expected in [("melah", "2020-09", 13.92), ("barbara", "2016-06", 63.446)]:
        vals = [Decimal(r["value"]) for (d, day), r in storage_csv.items() if d == dam and day.startswith(month)]
        exact = sum(vals) / len(vals)
        assert exact.quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN) == Decimal(str(expected))
        series = data.get_storage(dam, f"{month}-01", f"{month}-30", resolution="monthly")["result"]["series"]
        assert series[0]["mean_mm3"] == expected and series[0]["days_with_value"] == len(vals)


@pytest.mark.parametrize("call, code", [
    (lambda d: d.national_storage("20200201"), "BAD_DATE"),
    (lambda d: d.national_storage("2020-W05-6"), "BAD_DATE"),
    (lambda d: d.national_storage(""), "BAD_DATE"),
    (lambda d: d.get_fill("sidisalem", "2020-02-30"), "BAD_DATE"),
    (lambda d: d.compare_years("all", "02-30"), "BAD_DATE"),
    (lambda d: d.compare_years("all", "13-01"), "BAD_DATE"),
    (lambda d: d.compare_years("sidisalem", "00-00"), "BAD_DATE"),
    (lambda d: d.get_transfers("2020-02-02", "2020-02-01"), "BAD_RANGE"),
    (lambda d: d.get_storage("sidisalem", "2020-02-02", "2020-02-01"), "BAD_RANGE"),
    (lambda d: d.get_transfers("2020-02-01", "2020-02-01", limit=-1), "BAD_LIMIT"),
    (lambda d: d.get_transfers("2020-02-01", "2020-02-01", limit=0), "BAD_LIMIT"),
    (lambda d: d.get_transfers("2020-02-01", "2020-02-01", limit=1001), "BAD_LIMIT"),
    (lambda d: d.get_transfers("2020-02-01", "2020-02-01", limit=True), "BAD_LIMIT"),
])
def test_invalid_inputs_are_refused(data, call, code):
    with pytest.raises(QueryError) as err:
        call(data)
    assert err.value.code == code


def test_leap_day_comparison_lists_leap_years_only(data, storage_csv):
    out = data.compare_years("all", "02-29")
    assert [p["date"] for p in out["result"]["series"]] == ["2016-02-29", "2020-02-29", "2024-02-29"]
    for p in out["result"]["series"]:
        assert p["total_mm3"] == round(sum(float(r["value"]) for (d, day), r in storage_csv.items() if day == p["date"]), 3)


def test_transfer_limit_and_truncation(data):
    full = data.get_transfers("2020-02-01", "2020-02-01")["result"]
    assert full["matched"] == full["returned"] == 4 and full["truncated"] is False
    cut = data.get_transfers("2020-02-01", "2020-02-01", limit=3)["result"]
    assert cut["matched"] == 4 and cut["returned"] == 3 and cut["truncated"] is True


def test_transfer_rows_equal_published_table_with_source(data, transfers_csv):
    out = data.get_transfers("2020-02-01", "2020-02-03", measure="current_season_to_date")["result"]
    expected = [r for r in transfers_csv.values()
                if "2020-02-01" <= r["bulletin_date"] <= "2020-02-03" and r["variable"] == "current_season_to_date"]
    assert out["matched"] == len(expected) == len(out["rows"])
    for row in out["rows"]:
        src = transfers_csv[row["transfer_observation_id"]]
        assert row["value_mm3"] == (float(src["value"]) if src["value"] else None)
        assert row["from_mapping_status"] == src["from_mapping_status"]
        assert row["to_mapping_status"] == src["to_mapping_status"]
        assert row["source"]["source_file"] == src["source_file"] and row["source"]["page"] == "3"
        assert row["source"]["source_sha256"] == src["source_sha256"]
        assert row["source"]["evidence_id"] == (src["evidence_id"] or None)
        assert row["source"]["printed_text"] == (src["raw_text"] or None)


def test_candidate_endpoints_are_reported_separately_never_promoted(data):
    for dam, node, side in [("bouheurtma", "NODE-DAM-BOUHERTMA", "to"), ("ziatine", "NODE-DAM-ZAYATIN", "from")]:
        out = data.get_transfers("2020-02-01", "2020-02-01", dam=dam)
        res = out["result"]
        assert res["matched"] == 0 and res["rows"] == []
        assert res["candidate_endpoint_matched"] == 1
        cand = res["candidate_endpoint_rows"][0]
        assert cand[side] == node and cand[f"{side}_mapping_status"].startswith("CANDIDATE_")
        assert any("not promoted" in n for n in out["notes"])
    sejnane = data.get_transfers("2020-02-01", "2020-02-01", dam="sejnane")["result"]["rows"]
    zayatin = next(r for r in sejnane if r["from"] == "NODE-DAM-ZAYATIN")
    assert zayatin["from_mapping_status"] == "CANDIDATE_ZAYATIN_TO_ZIATINE_NOT_PROMOTED"
    assert zayatin["value_mm3"] == 0.004


def test_national_fill_subset_is_explained(data):
    out = data.national_storage("2020-10-01")
    res = out["result"]
    assert res["dams_without_known_capacity"] == ["brek"] and res["dams_in_fill"] == res["dams_with_value"] - 1
    assert res["fill_pct_of_known_capacity"] == round(100 * res["fill_numerator_mm3"] / res["known_capacity_sum_mm3"], 1)
    assert res["total_mm3"] > res["fill_numerator_mm3"]
    assert any("brek" in n and "denominator" in n for n in out["notes"])


@pytest.mark.parametrize("day, printed, disposition", [
    ("2017-12-30", 631.607, "SOURCE_PRINTED_DISAGREEMENT"),
    ("2022-02-09", 1145.517, "SOURCE_PRINTED_DISAGREEMENT"),
    ("2015-10-03", None, "SOURCE_ROSTER_SCOPE_DIFFERENCE"),
    ("2020-02-01", 1471.421, "WITHIN_ROUNDING"),
])
def test_known_national_disagreements_are_disclosed(data, day, printed, disposition):
    out = data.national_storage(day)
    cmp = out["result"]["printed_total_comparison"]
    assert cmp["disposition"] == disposition
    if printed is not None:
        assert out["result"]["printed_national_total_mm3"] == printed
    if disposition != "WITHIN_ROUNDING":
        assert any(disposition in n for n in out["notes"])


@pytest.mark.parametrize("query, dam_id, match_type", [
    ("سـيـدي سـالم", "sidisalem", "exact"),  # with tatweel
    ("sidisal", "sidisalem", "partial"),
])
def test_dam_name_variants(data, query, dam_id, match_type):
    assert data.match_dam(query) == (dam_id, match_type)


def test_longer_text_containing_a_dam_name_is_not_accepted(data):
    with pytest.raises(QueryError) as err:
        data.resolve_dam("not Sidi Salem")
    assert err.value.details["candidates"] == ["sidisalem"]
    assert err.value.details["match_type"] == "label_inside_query"
    assert data.find_dam("not Sidi Salem")["result"]["match"] is None


@pytest.mark.parametrize("label, iris", [
    ("الفارق", {"InflowVolumeDifference", "StoredWaterVolumeAnomaly"}),
    ("المعدل لنفس اليوم للثلاث السنوات الفارطة", {"InflowVolumeMultiYearMean", "StoredWaterVolumeMultiYearMean"}),
])
def test_shared_arabic_labels_are_ambiguous_not_guessed(label, iris):
    pytest.importorskip("rdflib")
    from damlevels_mcp.ontology import Ontology

    onto = Ontology(ROOT)
    out = onto.describe(label)
    assert out["concept"] is None and out["ambiguous"] is True
    assert {c["iri"].rsplit("/", 1)[1] for c in out["candidates"]} == iris
    for cand in out["candidates"]:
        for col in cand["printed_columns"]:  # each candidate can be selected by its printed column
            assert onto.describe(col["column"])["iri"] == cand["iri"]


def test_missing_rdflib_gives_ontology_unavailable(monkeypatch):
    from damlevels_mcp.ontology import Ontology

    monkeypatch.setitem(sys.modules, "rdflib", None)  # makes `import rdflib` fail
    with pytest.raises(QueryError) as err:
        Ontology(ROOT).describe("Apports")
    assert err.value.code == "ONTOLOGY_UNAVAILABLE"


# ------------------------------------------------------- real stdio transport
def _stdio_calls(calls: list[tuple[str, dict]], hash_seed: str = "0") -> list[dict]:
    """Start `python -m damlevels_mcp` as a subprocess and call tools over MCP stdio."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "DAMLEVELS_DATA_ROOT": str(ROOT),
           "PYTHONPATH": os.pathsep.join([str(ROOT / "mcp_server"), os.environ.get("PYTHONPATH", "")])}
    params = StdioServerParameters(command=sys.executable, args=["-m", "damlevels_mcp"], env=env, cwd=str(ROOT))

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out = []
                for name, args in calls:
                    res = await session.call_tool(name, args)
                    assert not res.isError, res.content
                    out.append(json.loads(res.content[0].text))
                return out

    return asyncio.run(run())


def test_stdio_server_answers_and_reports_errors():
    pytest.importorskip("mcp")
    info, storage, error, transfers = _stdio_calls([
        ("dataset_info", {}),
        ("get_storage", {"dam": "sidielbarrak", "start": "2020-02-01", "end": "2020-02-03"}),
        ("get_fill", {"dam": "Sidi Salem", "date": "2026-03-01"}),
        ("get_transfers", {"start": "2020-02-01", "end": "2020-02-01", "limit": -1}),
    ])
    assert info["result"]["storage_observations"] == 129390 and info["attribution"] == ATTRIBUTION
    assert [p["storage_mm3"] for p in storage["result"]["series"]] == [283.496, 283.496, 283.798]
    assert error["error"] == "OUTSIDE_RECORD"
    assert transfers["error"] == "BAD_LIMIT"


def test_stdio_ambiguous_labels_are_stable_across_hash_seeds():
    pytest.importorskip("mcp")
    pytest.importorskip("rdflib")
    calls = [("describe_variable", {"term": "الفارق"}),
             ("describe_variable", {"term": "المعدل لنفس اليوم للثلاث السنوات الفارطة"})]
    answers = [[r["result"] for r in _stdio_calls(calls, seed)] for seed in ("1", "2", "3")]
    assert answers[0] == answers[1] == answers[2]
    assert all(r["concept"] is None and len(r["candidates"]) == 2 for r in answers[0])

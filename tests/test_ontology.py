"""Checks on the published DLO 0.3 ontology view (ontology/).

Needs rdflib; the reasoning test also needs owlrl. Both tests are skipped when
the library is missing.
"""
import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib.compare import isomorphic  # noqa: E402
from rdflib.namespace import OWL, RDF, SKOS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TTL = ROOT / "ontology" / "DLO_0.3_VIEW_20260929-2345.ttl"
OWL_FILE = ROOT / "ontology" / "DLO_0.3_VIEW_20260929-2345.owl"
QUERIES = ROOT / "ontology" / "queries"
DLO = rdflib.Namespace("https://w3id.org/damlevels/ontology/")
DLC = rdflib.Namespace("https://w3id.org/damlevels/code/")
SOSA = rdflib.Namespace("http://www.w3.org/ns/sosa/")
QUDT = rdflib.Namespace("http://qudt.org/schema/qudt/")
PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")
NO_RESULT_STATUSES = {DLC.NoValueInExtract, DLC.StructuralNotExpected, DLC.SourceBlank}


@pytest.fixture(scope="module")
def graph():
    return rdflib.Graph().parse(TTL, format="turtle")


def _normalised(g):
    """Copy of g with decimal literals in canonical form (0.0 and 0 are the same decimal).

    Blank nodes are kept, so the result must be compared with graph isomorphism.
    """
    out = rdflib.Graph()
    for s, p, o in g:
        if isinstance(o, rdflib.Literal) and o.datatype is not None and str(o.datatype).endswith("#decimal"):
            o = rdflib.Literal(str(Decimal(str(o)).normalize()), datatype=o.datatype)
        out.add((s, p, o))
    return out


def _same_statements(a, b) -> bool:
    return len(a) == len(b) and isomorphic(_normalised(a), _normalised(b))


def test_turtle_and_owl_files_carry_the_same_statements(graph):
    owl_graph = rdflib.Graph().parse(OWL_FILE, format="xml")
    assert len(owl_graph) == len(graph)
    assert _same_statements(owl_graph, graph)


def test_statement_comparison_detects_a_changed_blank_node_triple(graph):
    changed = rdflib.Graph()
    for triple in graph:
        changed.add(triple)
    s, p, o = next(t for t in graph if isinstance(t[0], rdflib.BNode))
    changed.remove((s, p, o))
    changed.add((s, p, rdflib.Literal("MUTATED")))
    assert len(changed) == len(graph) and not _same_statements(changed, graph)


def test_documented_counts(graph):
    assert len(set(graph.subjects(RDF.type, DLO.ColumnMapping))) == 84
    assert len(set(graph.objects(None, DLO.mapsToVariable))) == 33
    assert len(set(graph.subjects(SKOS.inScheme, DLC.TemporalSupportScheme))) == 16
    assert len(set(graph.subjects(RDF.type, DLO.SemanticTest))) == 46
    assert len(set(graph.subjects(RDF.type, DLO.BulletinObservation))) == 200
    for cls in (DLO.Dam, DLO.ManagedReservoir, DLO.Catchment):
        assert len(set(graph.subjects(RDF.type, cls))) == 36


def test_observations_are_complete(graph):
    required = [SOSA.hasFeatureOfInterest, SOSA.observedProperty, SOSA.phenomenonTime, SOSA.usedProcedure, PROV.used]
    for obs in graph.subjects(RDF.type, DLO.BulletinObservation):
        for prop in required:
            assert (obs, prop, None) in graph, (obs, prop)
        assert (next(graph.objects(obs, SOSA.usedProcedure)), RDF.type, DLO.ColumnMapping) in graph
        results = list(graph.objects(obs, SOSA.hasResult))
        if results:
            assert all((r, QUDT.numericValue, None) in graph for r in results), obs
        else:
            assert set(graph.objects(obs, DLO.valueStatus)) & NO_RESULT_STATUSES, obs


def test_mappings_concepts_and_time_rules_are_defined(graph):
    incomplete = [str(m).rsplit("/", 1)[1] for m in graph.subjects(RDF.type, DLO.ColumnMapping)
                  if (m, DLO.mapsToVariable, None) not in graph or (m, DLO.temporalSupport, None) not in graph]
    assert incomplete == ["p2_rs_unresolved_prohibited"]  # R.S.: meaning not documented by the publisher
    for term in set(graph.objects(None, DLO.mapsToVariable)) | set(graph.subjects(SKOS.inScheme, DLC.TemporalSupportScheme)):
        assert (term, SKOS.prefLabel, None) in graph and (term, SKOS.definition, None) in graph, term


def test_no_undefined_project_terms(graph):
    described = set(graph.subjects())
    bookkeeping = {rdflib.RDFS.isDefinedBy, OWL.versionIRI, OWL.priorVersion,
                   rdflib.URIRef("http://purl.org/dc/terms/source")}
    dangling = Counter(
        str(o) for _, p, o in graph
        if isinstance(o, rdflib.URIRef) and str(o).startswith("https://w3id.org/damlevels/")
        and o not in described and p != RDF.type and p not in bookkeeping
    )
    assert not dangling, dangling


def test_sample_storage_values_match_published_table(graph):
    storage = {}
    with open(ROOT / "data" / "storage.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            storage[(row["source_sha256"], row["dam_id"])] = Decimal(row["value"])
    compared = 0
    for obs in graph.subjects(RDF.type, DLO.BulletinObservation):
        if not str(next(graph.objects(obs, SOSA.usedProcedure))).endswith("/p1_stock_today_mm3"):
            continue
        sha = str(next(graph.objects(obs, PROV.used))).rsplit("/", 1)[1]
        dam = str(next(graph.objects(obs, SOSA.hasFeatureOfInterest))).rsplit("/", 1)[1]
        for result in graph.objects(obs, SOSA.hasResult):
            value = Decimal(str(next(graph.objects(result, QUDT.numericValue))))
            assert storage[(sha, dam)] == value, (dam, sha)
            compared += 1
    assert compared == 20


@pytest.mark.parametrize("name, rows", [("observations_for_one_dam.rq", 5), ("column_meanings.rq", 83), ("time_rules.rq", 16)])
def test_example_queries(graph, name, rows):
    result = list(graph.query((QUERIES / name).read_text(encoding="utf-8")))
    assert len(result) == rows


def test_flows_are_dated_the_day_before_the_bulletin(graph):
    rows = {(str(r.variable), str(r.describes)): float(r.value)
            for r in graph.query((QUERIES / "observations_for_one_dam.rq").read_text(encoding="utf-8"))}
    assert rows[("inflow volume", "2020-01-31/P1D")] == 0.016
    assert rows[("stored water volume", "2020-02-01")] == 283.496
    assert rows[("stored water volume", "2019-02-01")] == 280.478


OWLRL_ERROR = rdflib.URIRef("http://www.daml.org/2002/03/agents/agent-ont#error")


def _owl_rl_problems(g):
    """OWL RL closure of g: owlrl error messages and instances of owl:Nothing."""
    owlrl = pytest.importorskip("owlrl")
    closure = rdflib.Graph()
    for triple in g:
        closure.add(triple)
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False).expand(closure)
    errors = sorted(str(o) for o in closure.objects(None, OWLRL_ERROR))
    return closure, errors, set(closure.subjects(RDF.type, OWL.Nothing))


def test_owl_rl_reasoning_finds_no_contradiction(graph):
    closure, errors, nothing = _owl_rl_problems(graph)
    assert len(closure) > len(graph)
    assert errors == [] and not nothing


def test_owl_rl_check_detects_an_inconsistency():
    bad = rdflib.Graph()
    a, b, x = (rdflib.URIRef(f"urn:test:{n}") for n in "abx")
    bad.add((a, OWL.disjointWith, b))
    bad.add((x, RDF.type, a))
    bad.add((x, RDF.type, b))
    _, errors, _ = _owl_rl_problems(bad)
    assert errors and "Disjoint classes" in errors[0]

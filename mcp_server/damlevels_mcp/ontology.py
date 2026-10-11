"""Meaning of terms and printed columns, from the DLO 0.3 ontology view."""
from __future__ import annotations

from functools import cached_property
from pathlib import Path

from .core import QueryError, _fold

DLO = "https://w3id.org/damlevels/ontology/"
SKOS = "http://www.w3.org/2004/02/skos/core#"


class Ontology:
    def __init__(self, root: Path):
        self.path = Path(root) / "ontology" / "DLO_0.3_VIEW_20260929-2345.ttl"

    @cached_property
    def graph(self):
        try:
            import rdflib
        except ImportError as exc:  # optional dependency
            raise QueryError("ONTOLOGY_UNAVAILABLE", "Install rdflib to query the ontology: "
                             "pip install -e \"mcp_server[ontology]\".") from exc
        return rdflib.Graph().parse(self.path, format="turtle")

    def _labels(self, node, prop: str) -> dict[str, list[str]]:
        import rdflib

        out: dict[str, list[str]] = {}
        for lit in self.graph.objects(node, rdflib.URIRef(SKOS + prop)):
            out.setdefault(lit.language or "", []).append(str(lit))
        return {lang: sorted(vals) for lang, vals in sorted(out.items())}

    def _first(self, node, prop: str, lang: str = "en") -> str | None:
        labels = self._labels(node, prop)
        for key in (lang, "", *labels):
            if labels.get(key):
                return labels[key][0]
        return None

    @cached_property
    def _concepts(self) -> list[tuple[object, set[str]]]:
        """Concepts used by column mappings, with every label folded for matching."""
        import rdflib

        g = self.graph
        maps_to = rdflib.URIRef(DLO + "mapsToVariable")
        out = []
        for concept in sorted(set(g.objects(None, maps_to)), key=str):
            keys = {_fold(str(concept).rsplit("/", 1)[1])}
            for prop in ("prefLabel", "altLabel"):
                for values in self._labels(concept, prop).values():
                    keys.update(_fold(v) for v in values)
            out.append((concept, keys))
        return out

    def _columns_for(self, concept) -> list[dict]:
        import rdflib

        g = self.graph
        rows = []
        for mapping in g.subjects(rdflib.URIRef(DLO + "mapsToVariable"), concept):
            rule = next(g.objects(mapping, rdflib.URIRef(DLO + "temporalSupport")), None)
            table = next(g.objects(mapping, rdflib.URIRef(DLO + "sourceTable")), None)
            rows.append({
                "column": str(next(g.objects(mapping, rdflib.URIRef(DLO + "sourceColumn")), "")),
                "table": str(table).rsplit("/", 1)[-1] if table else None,
                "time_rule": self._first(rule, "prefLabel") if rule else None,
            })
        return sorted(rows, key=lambda r: (r["table"] or "", r["column"]))

    def describe(self, term: str) -> dict:
        g = self.graph  # raises ONTOLOGY_UNAVAILABLE before any other rdflib import
        import rdflib

        key = _fold(term) if isinstance(term, str) else ""
        if not key:
            raise QueryError("UNKNOWN_TERM", "Empty term.")
        # A printed column name maps directly to one concept.
        for mapping in g.subjects(rdflib.URIRef(DLO + "sourceColumn"), rdflib.Literal(term.strip())):
            concept = next(g.objects(mapping, rdflib.URIRef(DLO + "mapsToVariable")), None)
            if concept is None:
                return {"term": term, "concept": None, "match_type": "printed_column",
                        "note": "This column is mapped but has no concept: its meaning is not documented by the publisher."}
            return {**self._concept_dict(term, concept), "match_type": "printed_column"}
        exact = [c for c, keys in self._concepts if key in keys]
        partial = [c for c, keys in self._concepts if any(key in k for k in keys)]
        found, match_type = (exact, "exact_label") if exact else (partial, "partial_label")
        if not found:
            raise QueryError("UNKNOWN_TERM", f"No concept matches {term!r}.",
                             known_concepts=sorted(self._first(c, "prefLabel") for c, _ in self._concepts))
        if len(found) > 1:
            return {"term": term, "concept": None, "match_type": match_type, "ambiguous": True,
                    "note": "This term is a label of several concepts with different meanings and time rules. "
                            "Do not pick one: call describe_variable again with the printed column name "
                            "(see printed_columns) that the value comes from.",
                    "candidates": sorted(({"concept": self._first(c, "prefLabel"), "iri": str(c),
                                           "printed_columns": self._columns_for(c)} for c in found),
                                         key=lambda d: d["iri"])}
        return {**self._concept_dict(term, found[0]), "match_type": match_type}

    def _concept_dict(self, term: str, concept) -> dict:
        import rdflib

        unit = next(self.graph.objects(concept, rdflib.URIRef(DLO + "canonicalUnit")), None)
        return {
            "term": term,
            "concept": self._first(concept, "prefLabel"),
            "iri": str(concept),
            "definition": self._first(concept, "definition"),
            "labels": {lang or "und": vals for lang, vals in self._labels(concept, "altLabel").items()},
            "unit": str(unit).rsplit("/", 1)[-1] if unit else None,
            "printed_columns": self._columns_for(concept),
        }

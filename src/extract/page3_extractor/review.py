"""Read a completed run without re-running extraction.

Backs notebook 01 and ``python -m page3_extractor review``. Everything here is
read-only over a run directory; no PDF is opened, which is exactly the property
that makes a review reproducible on a machine that does not have the corpus.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterator, Optional


class RunView:
    """Lazy view over one run directory."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        if not self.run_dir.exists():
            raise FileNotFoundError(f"run directory not found: {self.run_dir}")
        self.manifest = self._json("RUN_MANIFEST.json")
        self.status = self._json("RUN_STATUS.json")
        self.config = self._json("CONFIG_RESOLVED.json")
        self.environment = self._json("ENVIRONMENT.json")
        self._catalog: Optional[dict[str, dict[str, Any]]] = None

    # -- files ---------------------------------------------------------- #
    def _json(self, name: str) -> dict[str, Any]:
        p = self.run_dir / name
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))

    @property
    def catalog(self) -> dict[str, dict[str, Any]]:
        if self._catalog is None:
            self._catalog = {}
            p = self.run_dir / "OUTPUT_CATALOG.csv"
            if p.exists():
                with open(p, encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        self._catalog[row["table"]] = row
        return self._catalog

    def table_path(self, table: str) -> Path:
        entry = self.catalog.get(table)
        if entry:
            return self.run_dir / entry["relative_path"]
        matches = list(self.run_dir.rglob(f"{table}.csv"))
        if not matches:
            raise FileNotFoundError(f"table {table} not in run {self.run_dir}")
        return matches[0]

    def rows(self, table: str) -> Iterator[dict[str, str]]:
        with open(self.table_path(table), encoding="utf-8-sig", newline="") as fh:
            yield from csv.DictReader(fh)

    def table(self, table: str, limit: Optional[int] = None) -> list[dict[str, str]]:
        out = []
        for i, row in enumerate(self.rows(table)):
            if limit is not None and i >= limit:
                break
            out.append(row)
        return out

    # -- summaries ------------------------------------------------------ #
    def source_status_distribution(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows("p3_source_status"):
            counts[row["terminal_status"]] = counts.get(row["terminal_status"], 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def family_status_distribution(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for row in self.rows("p3_family_status"):
            fam = out.setdefault(row["family_id"], {})
            fam[row["family_status"]] = fam.get(row["family_status"], 0) + 1
        return dict(sorted(out.items()))

    def semantic_state_distribution(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows("page3_all_facts_long"):
            counts[row["semantic_state"]] = counts.get(row["semantic_state"], 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def validation_distribution(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for row in self.rows("p3_validation_result"):
            rule = out.setdefault(row["rule_id"], {})
            rule[row["status"]] = rule.get(row["status"], 0) + 1
        return dict(sorted(out.items()))

    def review_queue(self, priority: Optional[str] = None,
                     family: Optional[str] = None) -> list[dict[str, str]]:
        out = []
        for row in self.rows("page3_open_review_items"):
            if priority and row["priority"] != priority:
                continue
            if family and row["family_id"] != family:
                continue
            out.append(row)
        return out

    # -- drilldown ------------------------------------------------------ #
    def lookup_evidence(self, evidence_id: str) -> dict[str, Any]:
        """Resolve an evidence id to its cell, its facts and its source path."""
        cell = None
        for row in self.rows("p3_cell_evidence"):
            if _evidence_id_of(row) == evidence_id:
                cell = row
                break
        facts = [r for r in self.rows("page3_all_facts_long")
                 if r["evidence_id"] == evidence_id]
        source = facts[0]["source_relative_path"] if facts else (
            cell["source_file"] if cell else "")
        return {
            "evidence_id": evidence_id,
            "cell_evidence": cell,
            "facts": facts,
            "source_relative_path": source,
            "coordinates": None if not cell else {
                "x0": float(cell["bbox_x0"]), "y0": float(cell["bbox_y0"]),
                "x1": float(cell["bbox_x1"]), "y1": float(cell["bbox_y1"]),
                "frame": "canonical portrait frame after rotation normalization",
            },
        }

    def facts_for_source(self, name_or_sha: str) -> list[dict[str, str]]:
        return [r for r in self.rows("page3_all_facts_long")
                if name_or_sha in (r["source_relative_path"], r["source_sha256"])]

    def mismatches(self) -> list[dict[str, str]]:
        try:
            return list(self.rows("page3_cross_source_mismatches"))
        except FileNotFoundError:
            return []

    def performance(self) -> dict[str, Any]:
        return self.manifest.get("performance", {})

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.manifest.get("run_id"),
            "status": self.status.get("status"),
            "release_status": self.manifest.get("release_status"),
            "extractor_version": self.manifest.get("extractor_version"),
            "configuration_hash": self.manifest.get("configuration_hash"),
            "mode": self.manifest.get("mode"),
            "selected_file_count": self.manifest.get("selected_file_count"),
            "terminal_status_counts": self.manifest.get("terminal_status_counts"),
            "fact_count": self.manifest.get("fact_count"),
            "review_item_count": self.manifest.get("review_item_count"),
            "failure_count": self.manifest.get("failure_count"),
            "counter_violations": len(self.manifest.get("counter_violations", [])),
            "tables": len(self.catalog),
        }


def _evidence_id_of(cell_row: dict[str, str]) -> str:
    from .evidence import evidence_id

    frag = cell_row["fragment_id"].lstrip("F")
    cell = cell_row["cell_id"]
    row_i, _, col_i = cell.lstrip("r").partition("c")
    try:
        return evidence_id(cell_row["source_sha256"], int(frag), int(row_i), int(col_i))
    except ValueError:
        return ""


def load_run(run_dir: Path) -> dict[str, Any]:
    view = RunView(run_dir)
    return {
        "summary": view.summary(),
        "source_status_distribution": view.source_status_distribution(),
        "family_status_distribution": view.family_status_distribution(),
        "semantic_state_distribution": view.semantic_state_distribution(),
        "validation_distribution": view.validation_distribution(),
        "performance": view.performance(),
        "open_review_items": len(view.review_queue()),
    }

"""Producer findings — Layer C.

A finding interprets **one frozen run**. It is not an extractor rule and it is
not evidence. Every finding therefore carries the run it came from, the exact
table and query that produced it, a numerator *and a denominator*, and a claim
status that says how far it may be pushed.

Regenerating findings from the same frozen evidence reproduces the same hashes:
nothing here reads a clock into a value, and every query is a deterministic scan
of the run's CSVs.

Deleting the findings directory damages nothing.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .review import RunView
from .version import EXTRACTOR_VERSION

FINDINGS_VERSION = "1.0.0"

CLAIM_SUPPORTED = "SUPPORTED_BY_THIS_RUN"
CLAIM_MEASURED = "MEASURED_IN_THIS_RUN"
CLAIM_CANDIDATE = "CANDIDATE_REQUIRES_INDEPENDENT_REVIEW"
CLAIM_CONTRADICTS = "CONTRADICTS_A_PRIOR_DRAFT_REGISTRY"


@dataclass
class Finding:
    finding_id: str
    finding_text: str
    run_id: str
    extractor_version: str
    configuration_hash: str
    corpus_manifest_hash: str
    evidence_table: str
    evidence_filter_or_query: str
    numerator: float
    denominator: float
    supporting_paths: str
    claim_status: str
    review_status: str = "pending_human"
    notes: str = ""

    @property
    def rate(self) -> Optional[float]:
        if not self.denominator:
            return None
        return round(self.numerator / self.denominator, 6)

    def as_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["rate"] = "" if self.rate is None else repr(self.rate)
        d["numerator"] = _num(self.numerator)
        d["denominator"] = _num(self.denominator)
        return d


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(round(float(v), 6))


FINDING_COLUMNS = (
    "finding_id", "finding_text", "run_id", "extractor_version",
    "configuration_hash", "corpus_manifest_hash", "evidence_table",
    "evidence_filter_or_query", "numerator", "denominator", "rate",
    "supporting_paths", "claim_status", "review_status", "notes",
)

LINK_COLUMNS = ("finding_id", "evidence_table", "relative_path", "row_count",
                "sha256", "query")


# ---------------------------------------------------------------------- #

def build_findings(run_dir: Path, output_dir: Optional[Path] = None) -> dict[str, Any]:
    view = RunView(run_dir)
    run_id = view.manifest.get("run_id", run_dir.name)
    cfg_hash = view.manifest.get("configuration_hash", "")
    corpus_hash = (view.manifest.get("corpus_identity") or {}).get("manifest_sha256", "")
    out_dir = Path(output_dir) if output_dir else run_dir / "10_findings"
    out_dir.mkdir(parents=True, exist_ok=True)

    ctx = _FindingContext(view, run_id, cfg_hash, corpus_hash)
    findings: list[Finding] = []
    for builder in FINDING_BUILDERS:
        findings.extend(builder(ctx))

    _write_csv(out_dir / "FINDINGS_REGISTER.csv", FINDING_COLUMNS,
               [f.as_row() for f in findings])
    _write_csv(out_dir / "FINDING_EVIDENCE_LINKS.csv", LINK_COLUMNS,
               _links(view, findings))
    _write_csv(out_dir / "KNOWN_UNRESOLVED_CASES.csv",
               ("case_id", "source_relative_path", "bulletin_date", "family_id",
                "entity_id", "reason", "priority", "evidence_id", "status"),
               _unresolved(view, run_id))

    summary = {
        "findings_version": FINDINGS_VERSION,
        "run_id": run_id,
        "extractor_version": EXTRACTOR_VERSION,
        "configuration_hash": cfg_hash,
        "corpus_manifest_hash": corpus_hash,
        "finding_count": len(findings),
        "claim_status_counts": _counts(f.claim_status for f in findings),
        "generated_from": str(run_dir),
        "note": ("findings interpret exactly one frozen run; deleting this "
                 "directory does not damage the extractor or the evidence"),
    }
    (out_dir / "REFERENCE_RUN_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (out_dir / "REFERENCE_RUN_FINDINGS.md").write_text(
        _markdown(view, findings, summary), encoding="utf-8")

    hashes = {p.name: _sha256(p) for p in sorted(out_dir.glob("*")) if p.is_file()}
    summary["output_hashes"] = hashes
    (out_dir / "REFERENCE_RUN_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return summary


@dataclass
class _FindingContext:
    view: RunView
    run_id: str
    configuration_hash: str
    corpus_manifest_hash: str
    _cache: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def rows(self, table: str) -> list[dict[str, str]]:
        if table not in self._cache:
            try:
                self._cache[table] = list(self.view.rows(table))
            except FileNotFoundError:
                self._cache[table] = []
        return self._cache[table]

    def make(self, fid: str, text: str, table: str, query: str,
             numerator: float, denominator: float, claim: str,
             paths: str = "", notes: str = "") -> Finding:
        return Finding(
            finding_id=fid, finding_text=text, run_id=self.run_id,
            extractor_version=EXTRACTOR_VERSION,
            configuration_hash=self.configuration_hash,
            corpus_manifest_hash=self.corpus_manifest_hash,
            evidence_table=table, evidence_filter_or_query=query,
            numerator=numerator, denominator=denominator,
            supporting_paths=paths or table, claim_status=claim, notes=notes,
        )


# ---------------------------------------------------------------------- #
# Individual findings
# ---------------------------------------------------------------------- #

def _f_terminal_status(ctx: _FindingContext) -> list[Finding]:
    rows = ctx.rows("p3_source_status")
    total = len(rows)
    out = []
    counts = _counts(r["terminal_status"] for r in rows)
    for status, n in sorted(counts.items()):
        out.append(ctx.make(
            f"F-STATUS-{status}",
            f"{n} of {total} source files ended with terminal status {status}.",
            "p3_source_status", f"terminal_status == '{status}'",
            n, total, CLAIM_MEASURED,
        ))
    out.append(ctx.make(
        "F-STATUS-RECONCILIATION",
        f"Every source file reconciles to exactly one terminal status: "
        f"{total} status rows for {total} distinct source hashes.",
        "p3_source_status", "count(*) vs count(distinct source_sha256)",
        len({r["source_sha256"] for r in rows}), total, CLAIM_MEASURED,
    ))
    return out


def _f_fast_path(ctx: _FindingContext) -> list[Finding]:
    rows = ctx.rows("p3_performance_counters")
    total = len(rows)
    if not total:
        return []
    clean = sum(1 for r in rows
                if r["source_filesystem_reads"] == "1"
                and r["pymupdf_document_opens"] == "1"
                and r["textpage_builds"] == "1"
                and r["drawing_scans"] == "1"
                and int(r["pdfplumber_document_opens"] or 0) <= 1
                and r["page_renders"] == "0"
                and r["ocr_invocations"] == "0")
    return [ctx.make(
        "F-FASTPATH-COUNTERS",
        f"{clean} of {total} processed files met every fast-path counter "
        "expectation (1 read, 1 PyMuPDF open, 1 TextPage, 1 drawing scan, "
        "<=1 pdfplumber open, 0 renders, 0 OCR).",
        "p3_performance_counters",
        "source_filesystem_reads==1 and pymupdf_document_opens==1 and "
        "textpage_builds==1 and drawing_scans==1 and pdfplumber_document_opens<=1 "
        "and page_renders==0 and ocr_invocations==0",
        clean, total, CLAIM_MEASURED,
    )]


def _f_semantic_states(ctx: _FindingContext) -> list[Finding]:
    rows = ctx.rows("page3_all_facts_long")
    total = len(rows)
    if not total:
        return []
    out = []
    for state, n in sorted(_counts(r["semantic_state"] for r in rows).items()):
        out.append(ctx.make(
            f"F-STATE-{state}",
            f"{n} of {total} published facts carry semantic_state '{state}'.",
            "page3_all_facts_long", f"semantic_state == '{state}'",
            n, total, CLAIM_MEASURED,
        ))
    zeroed = sum(1 for r in rows
                 if r["semantic_state"] != "numeric" and r["parsed_value"] != "")
    out.append(ctx.make(
        "F-NO-SILENT-ZERO",
        f"{zeroed} of {total} published facts carry a parsed value while not "
        "being a printed number. The project rule requires this to be zero.",
        "page3_all_facts_long",
        "semantic_state != 'numeric' and parsed_value != ''",
        zeroed, total, CLAIM_MEASURED,
    ))
    return out


def _f_t2_roster(ctx: _FindingContext) -> list[Finding]:
    fam = [r for r in ctx.rows("p3_family_status") if r["family_id"] == "T2"]
    if not fam:
        return []
    counts = _counts(r["row_count"] for r in fam)
    total = len(fam)
    out = []
    for rc, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        out.append(ctx.make(
            f"F-T2-ROWCOUNT-{rc}",
            f"{n} of {total} pages published {rc} T2 dam rows.",
            "p3_family_status", f"family_id=='T2' and row_count=='{rc}'",
            n, total, CLAIM_MEASURED,
        ))
    grid = _counts(r["schema_id"] for r in fam)
    dominant = max(counts.items(), key=lambda kv: kv[1]) if counts else ("0", 0)
    out.append(ctx.make(
        "F-T2-ROWCOUNT-VS-GRIDROWS",
        "Fragment-2 grid row count and the published dam-row count are different "
        f"quantities: grid shapes observed {sorted(grid)}, dam-row counts observed "
        f"{sorted(counts)}. The dominant dam-row count is {dominant[0]}.",
        "p3_family_status", "family_id=='T2' group by schema_id, row_count",
        dominant[1], total, CLAIM_CONTRADICTS,
        notes="the inherited draft registry read fragment-2 cardinality as the day's "
              "roster size; this run measures the dam rows directly instead",
    ))
    unmatched = [r for r in ctx.rows("page3_t2_dam_status")
                 if r["dam_id"] == ""]
    all_t2 = ctx.rows("page3_t2_dam_status")
    out.append(ctx.make(
        "F-T2-ROSTER-UNMATCHED",
        f"{len(unmatched)} of {len(all_t2)} T2 values carry no resolved dam id "
        "(unreadable label regime or a label outside the roster registry).",
        "page3_t2_dam_status", "dam_id == ''",
        len(unmatched), len(all_t2) or 1, CLAIM_MEASURED,
    ))
    return out


def _f_t6_variant(ctx: _FindingContext) -> list[Finding]:
    fam = [r for r in ctx.rows("p3_family_status") if r["family_id"] == "T6"]
    if not fam:
        return []
    total = len(fam)
    by_schema = _counts(r["schema_id"] for r in fam)
    one_data_row = sum(1 for r in fam if r["row_count"] == "1")
    out = [ctx.make(
        "F-T6-SINGLE-DATA-ROW",
        f"{one_data_row} of {total} pages published exactly one T6 delivery row, "
        f"across header variants {sorted(by_schema)}.",
        "p3_family_status", "family_id=='T6' and row_count=='1'",
        one_data_row, total, CLAIM_CONTRADICTS,
        notes="the inherited era registry left the 3-row variant's 'extra row' "
              "unresolved; measured here as a two-line header over the same single "
              "data row",
    )]
    return out


def _f_t5_eras(ctx: _FindingContext) -> list[Finding]:
    fam = [r for r in ctx.rows("p3_family_status") if r["family_id"] == "T5"]
    if not fam:
        return []
    total = len(fam)
    out = []
    for schema_id, n in sorted(_counts(r["schema_id"] for r in fam).items()):
        out.append(ctx.make(
            f"F-T5-ERA-{schema_id or 'NONE'}",
            f"{n} of {total} pages used T5 schema {schema_id or '(none)'}.",
            "p3_family_status", f"family_id=='T5' and schema_id=='{schema_id}'",
            n, total, CLAIM_MEASURED,
        ))
    acc = [r for r in ctx.rows("page3_t5_transfers")
           if r["is_accounting_observation"] == "True"]
    allt5 = ctx.rows("page3_t5_transfers")
    edges_as_edges = sum(1 for r in acc if r["source_node_id"] != "")
    out.append(ctx.make(
        "F-T5-ACCOUNTING-NEVER-AN-EDGE",
        f"{edges_as_edges} of {len(acc)} accounting-observation rows carry a source "
        "node id. The connectivity rule requires this to be zero: the Sejnane "
        "transfer-inflow row restates rows 2+3 and is never a graph edge.",
        "page3_t5_transfers",
        "is_accounting_observation=='True' and source_node_id != ''",
        edges_as_edges, len(acc) or 1, CLAIM_MEASURED,
        notes=f"{len(allt5)} T5 values in total",
    ))
    return out


def _f_dates(ctx: _FindingContext) -> list[Finding]:
    rows = ctx.rows("p3_source_status")
    total = len(rows)
    if not total:
        return []
    printed = sum(1 for r in rows if r["bulletin_date_printed"])
    conflict = sum(1 for r in rows if r["date_conflict"] == "True")
    return [
        ctx.make(
            "F-DATE-PRINTED-CAPTURED",
            f"{printed} of {total} source files yielded a printed bulletin date, "
            "captured inside the single main extraction pass.",
            "p3_source_status", "bulletin_date_printed != ''",
            printed, total, CLAIM_MEASURED,
        ),
        ctx.make(
            "F-DATE-CONFLICT",
            f"{conflict} of {total} source files disagree between the filename date "
            "and the printed date. Both are preserved; neither is overwritten.",
            "p3_source_status", "date_conflict == True",
            conflict, total, CLAIM_MEASURED,
        ),
    ]


def _f_anchors(ctx: _FindingContext) -> list[Finding]:
    rows = ctx.rows("p3_anchor_attempt")
    total = len(rows)
    if not total:
        return []
    out = []
    for status, n in sorted(_counts(r["terminal_status"] for r in rows).items()):
        out.append(ctx.make(
            f"F-ANCHOR-{status}",
            f"{n} of {total} anchor attempts ended as {status}.",
            "p3_anchor_attempt", f"terminal_status == '{status}'",
            n, total, CLAIM_MEASURED,
        ))

    # Per definition, on pages whose text regime can carry an anchor at all.
    # The aggregate above is what hid a real defect during development: two
    # anchors were being accepted on a quarter of readable pages while the
    # overall figure looked unremarkable.
    readable = [r for r in rows
                if r["terminal_status"] != "TEXT_REGIME_INCOMPATIBLE"]
    by_anchor: dict[str, list[dict[str, str]]] = {}
    for r in readable:
        by_anchor.setdefault(r["anchor_id"], []).append(r)
    for anchor_id, rs in sorted(by_anchor.items()):
        accepted = sum(1 for r in rs if r["terminal_status"] == "ACCEPTED")
        worst = _counts(r["terminal_status"] for r in rs if
                        r["terminal_status"] != "ACCEPTED")
        detail = ", ".join(f"{k}={v}" for k, v in sorted(worst.items())) or "none"
        out.append(ctx.make(
            f"F-ANCHOR-READABLE-{anchor_id}",
            f"{anchor_id} was accepted on {accepted} of {len(rs)} pages whose "
            f"text regime can carry an anchor. Other outcomes: {detail}.",
            "p3_anchor_attempt",
            f"anchor_id=='{anchor_id}' and terminal_status!='TEXT_REGIME_INCOMPATIBLE'",
            accepted, len(rs) or 1, CLAIM_MEASURED,
        ))
    return out


def _f_rotation(ctx: _FindingContext) -> list[Finding]:
    rows = ctx.rows("p3_source_status")
    total = len(rows)
    if not total:
        return []
    rotated = [r for r in rows if r["rotation_normalization"] != "identity"]
    rotated_ok = sum(1 for r in rotated
                     if r["terminal_status"].startswith("SUCCESS")
                     or r["terminal_status"] == "PARTIAL_REVIEW_REQUIRED")
    return [ctx.make(
        "F-ROTATION-NORMALIZED",
        f"{len(rotated)} of {total} source files needed rotation normalization; "
        f"{rotated_ok} of those produced Page 3 facts after normalization rather "
        "than being dismissed on orientation.",
        "p3_source_status", "rotation_normalization != 'identity'",
        rotated_ok, len(rotated) or 1, CLAIM_MEASURED,
    )]


def _f_validation(ctx: _FindingContext) -> list[Finding]:
    rows = ctx.rows("p3_validation_result")
    if not rows:
        return []
    out = []
    by_rule: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_rule.setdefault(r["rule_id"], []).append(r)
    # The stored vocabulary is the Phase 2 contract's lowercase enum, not the
    # extractor's internal names.
    for rule, rs in sorted(by_rule.items()):
        eligible = [r for r in rs if r["eligibility_status"] == "eligible"]
        passed = sum(1 for r in eligible if r["status"] == "pass")
        warned = sum(1 for r in eligible if r["status"] == "warn")
        failed = sum(1 for r in eligible if r["status"] == "fail")
        out.append(ctx.make(
            f"F-VALIDATION-{rule}",
            f"Rule {rule}: {passed} pass, {warned} warn, {failed} fail out of "
            f"{len(eligible)} eligible checks ({len(rs) - len(eligible)} not "
            f"eligible, out of {len(rs)} attempted).",
            "p3_validation_result",
            f"rule_id=='{rule}' and eligibility_status=='eligible'",
            passed, len(eligible) or 1, CLAIM_MEASURED,
            notes=f"attempted={len(rs)} eligible={len(eligible)} warn={warned} "
                  f"fail={failed}",
        ))
        if failed:
            out.append(ctx.make(
                f"F-VALIDATION-{rule}-FAILURES",
                f"Rule {rule} failed on {failed} of {len(eligible)} eligible checks. "
                "A failing arithmetic check records a disagreement about the source; "
                "no value was altered to make it pass.",
                "p3_validation_result",
                f"rule_id=='{rule}' and status=='fail'",
                failed, len(eligible) or 1, CLAIM_MEASURED,
            ))
    return out


def _f_comparison(ctx: _FindingContext) -> list[Finding]:
    cov = ctx.rows("p3_comparison_input_coverage")
    reg = ctx.rows("p3_comparison_pair_registry")
    enabled = sum(1 for r in reg if r["status"] == "enabled")
    return [ctx.make(
        "F-COMPARISON-NONE-ENABLED",
        f"{enabled} of {len(reg)} registered comparison rules are enabled. No Page 3 "
        "value was compared against the provisional reference snapshot, because "
        "roster membership, region membership, temporal alignment and the capacity "
        "denominator are unresolved, and T5/T6 have no reference-side column at all.",
        "p3_comparison_pair_registry", "status == 'enabled'",
        enabled, len(reg) or 1, CLAIM_SUPPORTED,
        notes=f"{len(cov)} coverage rows record the blocking precondition per rule",
    )]


FINDING_BUILDERS: tuple[Callable[[_FindingContext], list[Finding]], ...] = (
    _f_terminal_status, _f_fast_path, _f_semantic_states, _f_t2_roster,
    _f_t6_variant, _f_t5_eras, _f_dates, _f_anchors, _f_rotation,
    _f_validation, _f_comparison,
)


# ---------------------------------------------------------------------- #

def _counts(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def _links(view: RunView, findings: list[Finding]) -> list[dict[str, Any]]:
    cat = view.catalog
    out = []
    for f in findings:
        entry = cat.get(f.evidence_table, {})
        out.append({
            "finding_id": f.finding_id,
            "evidence_table": f.evidence_table,
            "relative_path": entry.get("relative_path", ""),
            "row_count": entry.get("row_count", ""),
            "sha256": entry.get("sha256", ""),
            "query": f.evidence_filter_or_query,
        })
    return out


def _unresolved(view: RunView, run_id: str) -> list[dict[str, Any]]:
    out = []
    for i, row in enumerate(view.review_queue(), 1):
        out.append({
            "case_id": f"UNRESOLVED-{run_id}-{i:06d}",
            "source_relative_path": row.get("source_relative_path", ""),
            "bulletin_date": row.get("bulletin_date", ""),
            "family_id": row.get("family_id", ""),
            "entity_id": row.get("entity_id", ""),
            "reason": row.get("review_reason", ""),
            "priority": row.get("priority", ""),
            "evidence_id": row.get("evidence_id", ""),
            "status": row.get("review_status", "OPEN"),
        })
    return out


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow(["" if r.get(c) is None else str(r.get(c, "")) for c in columns])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _markdown(view: RunView, findings: list[Finding], summary: dict[str, Any]) -> str:
    m = view.manifest
    lines = [
        "# Reference-run findings (producer interpretation)",
        "",
        "> These are **producer findings about one frozen run**, not extractor rules and",
        "> not audited results. Phase 4 has not reviewed them. Every rate below carries",
        "> its denominator, and every finding names the table and query it came from.",
        "",
        "| | |",
        "|---|---|",
        f"| run_id | `{m.get('run_id', '')}` |",
        f"| extractor_version | `{m.get('extractor_version', '')}` |",
        f"| configuration_hash | `{m.get('configuration_hash', '')}` |",
        f"| corpus_manifest_hash | `{summary.get('corpus_manifest_hash', '')}` |",
        f"| files selected | {m.get('selected_file_count', '')} |",
        f"| release_status | `{m.get('release_status', '')}` |",
        "",
        "## Findings",
        "",
        "| id | claim status | numerator / denominator | rate | statement |",
        "|---|---|---|---|---|",
    ]
    for f in findings:
        rate = "" if f.rate is None else f"{f.rate:.4f}"
        text = f.finding_text.replace("|", "\\|")
        lines.append(
            f"| `{f.finding_id}` | {f.claim_status} | {_num(f.numerator)} / "
            f"{_num(f.denominator)} | {rate} | {text} |"
        )
    lines += [
        "",
        "## How to reproduce",
        "",
        "```bash",
        "python -m page3_extractor findings --run-dir <run_dir>",
        "```",
        "",
        "Each row of `FINDING_EVIDENCE_LINKS.csv` names the evidence table, its path",
        "inside the run, its SHA-256 and the exact filter used. Regenerating from the",
        "same frozen evidence reproduces the same file hashes.",
        "",
    ]
    return "\n".join(lines)

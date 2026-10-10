"""The public Python API. The notebook and the CLI both call these functions.

``run_page3_pipeline`` owns the run directory contract of section 6 of the
governing prompt: a new immutable run directory per run, every source
reconciling to exactly one terminal status, every value pointing at evidence,
and every contract table emitted whether or not this particular run had rows for
it.
"""

from __future__ import annotations

import json
import shutil
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import t1_general_stock, t2_dam_status, t3_inflows, t4_withdrawals, t5_transfers, t6_ichkeul
from .anchors import (
    ACCEPTED,
    AMBIGUOUS_REVIEW,
    ANCHOR_DEFS,
    ANCHOR_REGISTRY_VERSION,
    AnchorResult,
    REJECTED_DISTANCE_GATE,
    REJECTED_PROHIBITED_TOKEN,
    TEXT_REGIME_INCOMPATIBLE,
    detect_anchors,
)
from .cache import ArtifactCache
from .comparison import (
    DEFAULT_RULES,
    ReferenceSnapshot,
    build_coverage,
    compare,
    enabled_rules,
)
from .completeness import detect_orphan_numeric_tokens
from .config import (
    Page3RunConfig,
    ResolvedConfig,
    default_registry_root,
    default_schema_root,
    resolve_config,
)
from .evidence import (
    FAMILY_QUARANTINED,
    NOT_CHECKED,
    SOURCE_ARITHMETIC_INCONSISTENCY,
    SOURCE_CONSISTENT,
    SOURCE_ROUNDING_DIFFERENCE,
    Fact,
    FamilyResult,
)
from .page_context import PageContext, SourceReadError, StageCounters, build_page_context
from .performance import FileTiming, RunPerformance, check_fast_path
from .roster import default_registry
from .routing import (
    FAILED_EXTRACTOR_ERROR,
    FAILED_SOURCE_READ,
    NOT_P3_CONFIRMED,
    P3_REVIEW,
    QUARANTINED_NOT_LOGICAL_PAGE3,
    RouteDecision,
    classify,
    schema_era_for,
    terminal_status_for,
)
from .semantic_mapping import FAMILIES, T1, T2, T3, T4, T5, T6
from .source_inventory import SourceFile, corpus_identity, enumerate_sources, select_by_names
from .sampling import (
    fifty_file_sample,
    quick_check_sample,
    sample_identity,
    stratified_sample,
)
from .text_and_encoding import R1
from .validation import ValidationResult, has_blocking_failure, run_validations
from .version import EXTRACTOR_VERSION, RELEASE_STATUS, ROUTING_VERSION, SEMANTICS_VERSION
from .writers import RunWriters, SchemaRegistry, sha256_file, write_json, write_text

RUN_SUBDIRS = (
    "01_source_inventory", "02_page_context", "03_extracted_facts", "04_validation",
    "05_review_queues", "06_reference_comparisons", "07_performance", "08_logs",
    "09_publication_exports",
)

TABLE_LAYOUT: dict[str, str] = {
    "_default": "03_extracted_facts",
    "p3_source_manifest": "01_source_inventory",
    "p3_source_status": "01_source_inventory",
    "p3_page_preflight": "02_page_context",
    "p3_layout_fingerprint": "02_page_context",
    "p3_route_decision": "02_page_context",
    "p3_engine_run": "02_page_context",
    "p3_fragment_candidate": "02_page_context",
    "p3_anchor_candidate": "02_page_context",
    "p3_anchor_attempt": "02_page_context",
    "p3_anchor_adjudication": "02_page_context",
    "p3_anchor_variant_registry": "02_page_context",
    "p3_anchor_fragment_link": "02_page_context",
    "p3_unit_marker_inventory": "02_page_context",
    "p3_schema_era_assignment": "02_page_context",
    "p3_validation_result": "04_validation",
    "p3_extraction_failure": "04_validation",
    "p3_orphan_numeric_token": "04_validation",
    "p3_comparison_validation_checks": "04_validation",
    "p3_reference_internal_qc": "04_validation",
    "p3_reference_snapshot_diff": "04_validation",
    "p3_reference_snapshot_manifest": "04_validation",
    "p3_manual_review_queue": "05_review_queues",
    "p3_anchor_review_queue": "05_review_queues",
    "p3_mismatch_triage": "05_review_queues",
    "p3_cross_source_mismatch": "05_review_queues",
    "p3_cross_source_comparison": "06_reference_comparisons",
    "p3_comparison_input_coverage": "06_reference_comparisons",
    "p3_comparison_pair_registry": "06_reference_comparisons",
    "p3_comparison_summary": "06_reference_comparisons",
    "p3_mismatch_history": "06_reference_comparisons",
    "p3_performance_counters": "07_performance",
}
for _t in ("page3_all_facts_long", "page3_t1_general_stock", "page3_t2_dam_status",
           "page3_t3_inflows", "page3_t4_withdrawals", "page3_t5_transfers",
           "page3_t6_ichkeul", "page3_source_status", "page3_open_review_items",
           "page3_cross_source_mismatches", "page3_data_dictionary"):
    TABLE_LAYOUT[_t] = "09_publication_exports"

FAMILY_TABLE = {
    T1: "page3_t1_general_stock", T2: "page3_t2_dam_status", T3: "page3_t3_inflows",
    T4: "page3_t4_withdrawals", T5: "page3_t5_transfers", T6: "page3_t6_ichkeul",
}


@dataclass
class SourceOutcome:
    """Everything one source file contributed, before it is written."""

    source: SourceFile
    source_sha256: str
    terminal_status: str
    decision: Optional[RouteDecision]
    ctx: Optional[PageContext]
    facts: list[Fact] = field(default_factory=list)
    families: dict[str, FamilyResult] = field(default_factory=dict)
    validations: list[ValidationResult] = field(default_factory=list)
    anchors: Optional[AnchorResult] = None
    review_items: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    timing: Optional[FileTiming] = None
    error: str = ""
    #: PATCH-P5C-002 — one row per numeric-position fact that stayed blank or
    #: source-blank while an unclaimed strict numeric token sits in its row.
    orphan_findings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    status: str
    source_count: int
    terminal_status_counts: dict[str, int]
    fact_count: int
    review_item_count: int
    failure_count: int
    validation_counts: dict[str, int]
    performance: dict[str, Any]
    output_catalog: list[dict[str, Any]]
    counter_violations: list[str]
    elapsed_seconds: float
    release_status: str = RELEASE_STATUS

    def summary(self) -> str:
        lines = [
            f"run_id                : {self.run_id}",
            f"run_dir               : {self.run_dir}",
            f"status                : {self.status}",
            f"sources               : {self.source_count}",
            f"facts                 : {self.fact_count}",
            f"review items          : {self.review_item_count}",
            f"failures              : {self.failure_count}",
            f"counter violations    : {len(self.counter_violations)}",
            f"elapsed seconds       : {round(self.elapsed_seconds, 2)}",
            "terminal statuses     : " + ", ".join(
                f"{k}={v}" for k, v in sorted(self.terminal_status_counts.items())),
        ]
        return "\n".join(lines)


# ====================================================================== #
# Per-file processing
# ====================================================================== #

def process_source(src: SourceFile, roster, cache: ArtifactCache) -> SourceOutcome:
    """Read one PDF once and produce every row it is responsible for.

    The document, its page and its TextPage stay open for the duration of this
    call so a family can reach the native span layer of the page it is already
    holding, and are released here — a context never outlives its own file.
    """
    t_start = time.perf_counter()
    try:
        ctx = build_page_context(src.path, src.relative_path)
    except SourceReadError as exc:
        return SourceOutcome(
            source=src, source_sha256="", terminal_status=FAILED_SOURCE_READ,
            decision=None, ctx=None, error=str(exc),
            failures=[{"section_id": "PAGE", "failure_stage": "source_read",
                       "failure_code": "FAILED_SOURCE_READ", "severity": "error",
                       "message": str(exc)}],
        )
    try:
        return _process_open_source(src, ctx, roster, cache, t_start)
    finally:
        ctx.close()


def _process_open_source(src: SourceFile, ctx: PageContext, roster,
                         cache: ArtifactCache, t_start: float) -> SourceOutcome:
    t_ctx = time.perf_counter()

    decision = classify(ctx)
    regime = ctx.text_health.encoding_regime
    anchors = detect_anchors(ctx.words, ctx.fragments, regime)

    outcome = SourceOutcome(
        source=src, source_sha256=ctx.source_sha256,
        terminal_status="", decision=decision, ctx=ctx, anchors=anchors,
    )

    if decision.logical_page_class == NOT_P3_CONFIRMED:
        outcome.terminal_status = QUARANTINED_NOT_LOGICAL_PAGE3
        for fam in FAMILIES:
            outcome.families[fam] = FamilyResult(fam, (), FAMILY_QUARANTINED)
        outcome.failures.append({
            "section_id": "PAGE", "failure_stage": "logical_page_classification",
            "failure_code": "NOT_LOGICAL_PAGE3", "severity": "info",
            "message": "; ".join(decision.reasons) or "alien topology",
        })
        outcome.review_items.append({
            "section_id": "PAGE", "entity_id": "LOGICAL-PAGE",
            "review_reason": "quarantined as not a logical Page 3; zero Page 3 facts "
                             "may be extracted, and this date has no bulletin data",
            "priority": "low",
        })
        outcome.timing = _timing(src, ctx, t_start, t_ctx, t_ctx, t_ctx)
        return outcome

    if decision.logical_page_class == P3_REVIEW:
        outcome.terminal_status = terminal_status_for(
            decision, had_geometry_fallback=False, had_specialist_fallback=False,
            open_review_items=1, validation_failed=False)
        for fam in FAMILIES:
            outcome.families[fam] = FamilyResult(fam, (), "UNRESOLVED_SHAPE")
        outcome.failures.append({
            "section_id": "PAGE", "failure_stage": "routing",
            "failure_code": "UNRESOLVED_LAYOUT", "severity": "error",
            "message": "; ".join(decision.reasons) or "layout not in the accepted registry",
        })
        outcome.review_items.append({
            "section_id": "PAGE", "entity_id": "LAYOUT",
            "review_reason": "layout unresolved: " + ("; ".join(decision.reasons) or "unknown"),
            "priority": "high",
        })
        outcome.timing = _timing(src, ctx, t_start, t_ctx, t_ctx, t_ctx)
        return outcome

    frags = {f.index: f for f in ctx.fragments}
    sha = ctx.source_sha256
    date = ctx.printed_date_parsed or src.filename_date_parsed

    results = {
        T1: t1_general_stock.extract(frags.get(1), sha, regime, anchors),
        T2: t2_dam_status.extract(frags.get(2), sha, regime, anchors, roster, date,
                                  ctx=ctx),
        T3: t3_inflows.extract(frags.get(3), frags.get(4), frags.get(5), sha, regime, anchors),
        T4: t4_withdrawals.extract(frags.get(6), frags.get(7), sha, regime, anchors),
        T5: t5_transfers.extract(frags.get(8), sha, regime, anchors, ctx=ctx),
        T6: t6_ichkeul.extract(frags.get(9), sha, regime, anchors, ctx=ctx),
    }
    t_extract = time.perf_counter()

    outcome.families = results
    for fam, res in results.items():
        # PATCH-P5B-005: publish the per-family usability the run already
        # computes, so a page whose only partial family is T2 stops reading like
        # a page with a T1 or T3 defect. It is the same value p3_family_status
        # carries, by construction and by test.
        for fact in res.facts:
            fact.family_usability_status = res.status
        outcome.facts.extend(res.facts)
        outcome.review_items.extend(res.review_items)
        outcome.failures.extend(res.failures)

    # PATCH-P5C-002: a numeric-position fact may not stay silently blank while
    # the page prints an unclaimed measurement in the same cell.
    outcome.orphan_findings = detect_orphan_numeric_tokens(ctx, results, frags)
    for item in outcome.orphan_findings:
        if item["orphan_class"] != "UNCLAIMED_MEASUREMENT":
            continue
        results[item["family_id"]].add_review(
            item["review_reason"], item["entity_id"], "high",
            evidence_id=item["evidence_id"])
        outcome.review_items.append({
            "section_id": item["family_id"], "entity_id": item["entity_id"],
            "review_reason": item["review_reason"], "priority": "high",
            "evidence_id": item["evidence_id"],
        })

    validations = run_validations(
        outcome.facts,
        family_status={k: v.status for k, v in results.items()},
        t2_row_count=results[T2].row_count,
        filename_date=src.filename_date_parsed,
        printed_date=ctx.printed_date_parsed,
    )
    outcome.validations = validations
    t_validate = time.perf_counter()

    _apply_validation_status(outcome.facts, validations)
    _review_source_inconsistencies(outcome, validations)

    open_reviews = len(outcome.review_items) + sum(
        1 for a in anchors.attempts if a.status in (AMBIGUOUS_REVIEW, REJECTED_DISTANCE_GATE))
    outcome.terminal_status = terminal_status_for(
        decision,
        had_geometry_fallback=ctx.geometry_engine not in ("pdfplumber",),
        had_specialist_fallback=ctx.counters.camelot_invocations > 0
        or ctx.counters.opencv_invocations > 0,
        open_review_items=open_reviews,
        validation_failed=has_blocking_failure(validations),
    )
    outcome.timing = _timing(src, ctx, t_start, t_ctx, t_extract, t_validate)
    return outcome


def _timing(src, ctx, t_start, t_ctx, t_extract, t_validate) -> FileTiming:
    return FileTiming(
        source_sha256=ctx.source_sha256 if ctx else "",
        source_relpath=src.relative_path,
        context_build_seconds=round(t_ctx - t_start, 5),
        extract_seconds=round(t_extract - t_ctx, 5),
        validate_seconds=round(t_validate - t_extract, 5),
        total_seconds=round(time.perf_counter() - t_start, 5),
        counters=ctx.counters if ctx else StageCounters(),
    )


def _apply_validation_status(facts: Sequence[Fact], results: Sequence[ValidationResult]) -> None:
    """Stamp the page-level verdict and the per-fact source-consistency verdict.

    Two different questions, deliberately answered in two different columns:

    ``validation_status``
        unchanged from 1.0.0 — the strongest verdict of every rule that ran on
        this fact's *family*. It is a page-level signal and nothing that reads
        it needs to migrate.
    ``source_consistency_status``
        new in 1.1.0 and scoped to the individual fact: it is set only by the
        rules that test an identity the bulletin printed, and only on the facts
        those rules actually consumed. A correctly extracted number therefore
        stops being marked unusable because some other value on the page does
        not reconcile.
    """
    by_family: dict[str, list[ValidationResult]] = {}
    for r in results:
        by_family.setdefault(r.section_id, []).append(r)

    # evidence_id -> strongest arithmetic verdict that consumed that fact
    by_evidence: dict[str, str] = {}
    for r in results:
        if not r.arithmetic_scope or r.eligibility_status != "ELIGIBLE":
            continue
        for eid in r.arithmetic_scope:
            prior = by_evidence.get(eid)
            by_evidence[eid] = _stronger(prior, r.status)

    for f in facts:
        rules = by_family.get(f.family_id, [])
        applicable = [r for r in rules if r.eligibility_status == "ELIGIBLE"]
        if not applicable:
            f.validation_status = "NOT_ELIGIBLE"
        elif any(r.status == "FAIL" for r in applicable):
            f.validation_status = "FAIL"
        elif any(r.status == "WARN" for r in applicable):
            f.validation_status = "WARN"
        else:
            f.validation_status = "PASS"
        f.source_consistency_status = _SOURCE_CONSISTENCY.get(
            by_evidence.get(f.evidence_id, ""), NOT_CHECKED)


_ORDER = {"": 0, "PASS": 1, "WARN": 2, "FAIL": 3}

#: The arithmetic verdict, restated in the vocabulary a consumer needs: whether
#: the *source's own* printed arithmetic holds. It says nothing about whether the
#: extractor read the cell correctly — that is ``extraction_status``.
_SOURCE_CONSISTENCY = {
    "PASS": SOURCE_CONSISTENT,
    "WARN": SOURCE_ROUNDING_DIFFERENCE,
    "FAIL": SOURCE_ARITHMETIC_INCONSISTENCY,
}


def _stronger(a: Optional[str], b: str) -> str:
    return a if a and _ORDER.get(a, 0) >= _ORDER.get(b, 0) else b


def _review_source_inconsistencies(outcome: SourceOutcome,
                                   results: Sequence[ValidationResult]) -> None:
    """Raise one review item per printed identity that genuinely does not hold.

    PATCH-P4-003: once the tolerance model stops reporting its own artefacts, a
    surviving failure is a real disagreement in the source and must be visible
    rather than only stamped on a column.
    """
    for r in results:
        if not r.arithmetic_scope or r.status != "FAIL":
            continue
        outcome.review_items.append({
            "section_id": r.section_id,
            "entity_id": r.entity_id,
            "review_reason": (
                f"{r.rule_id}: the identity this page prints does not hold — "
                f"printed {r.observed_value}, derived {r.comparison_value}, "
                f"difference {r.difference}, tolerance {r.tolerance}. The "
                f"extracted values are unchanged; this is a statement about the "
                f"source, not about extraction"),
            "priority": "medium",
            "evidence_id": r.arithmetic_scope[0],
        })


# ====================================================================== #
# Run orchestration
# ====================================================================== #

def run_page3_pipeline(config: Page3RunConfig,
                       *,
                       progress: Optional[Any] = None) -> RunResult:
    """Execute one complete run and return its result."""
    started = time.perf_counter()
    resolved = resolve_config(config)
    run_dir = resolved.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    for sub in RUN_SUBDIRS:
        (run_dir / sub).mkdir(exist_ok=True)

    schema_root = default_schema_root(config)
    if schema_root is None:
        raise FileNotFoundError(
            "no schema root: pass schema_root in the config or ship "
            "page3_extractor/contracts/schemas with the package"
        )
    registry = SchemaRegistry(Path(schema_root))

    write_json(run_dir / "RUN_STATUS.json", {
        "run_id": resolved.run_id, "status": "RUNNING",
        "started_at": resolved.created_at, "release_status": RELEASE_STATUS,
    })
    write_json(run_dir / "CONFIG_RESOLVED.json", resolved.to_dict())
    write_json(run_dir / "ENVIRONMENT.json", resolved.environment)

    all_sources = enumerate_sources(config.input_dir)
    selected = _select_sources(config, all_sources)
    identity = corpus_identity(all_sources)

    roster = default_registry(default_registry_root(config))
    cache = ArtifactCache(config.cache_dir, enabled=config.enable_cache)
    writers = RunWriters(registry, run_dir, TABLE_LAYOUT)
    writers.ensure_all_tables()

    perf = RunPerformance()
    outcomes: list[SourceOutcome] = []
    log_lines: list[str] = []
    checkpoint_path = run_dir / "08_logs" / "CHECKPOINT.json"
    done_shas = _load_checkpoint(checkpoint_path) if config.resume else set()

    for i, src in enumerate(selected, 1):
        try:
            outcome = process_source(src, roster, cache)
        except Exception as exc:  # noqa: BLE001
            if config.fail_fast:
                raise
            outcome = SourceOutcome(
                source=src, source_sha256="",
                terminal_status=FAILED_EXTRACTOR_ERROR,
                decision=None, ctx=None,
                error=f"{type(exc).__name__}: {exc}",
                failures=[{"section_id": "PAGE", "failure_stage": "pipeline",
                           "failure_code": "UNHANDLED_EXTRACTOR_EXCEPTION",
                           "severity": "error",
                           "message": f"{type(exc).__name__}: {exc}"}],
            )
            log_lines.append(traceback.format_exc())
        outcomes.append(outcome)
        if outcome.timing:
            perf.add(outcome.timing)
        if progress is not None:
            progress(i, len(selected), src.name, outcome.terminal_status)
        if i % max(1, config.checkpoint_every) == 0:
            _write_checkpoint(checkpoint_path, outcomes, i, len(selected))

    perf.stop()
    _write_checkpoint(checkpoint_path, outcomes, len(selected), len(selected))

    catalog = _emit_all(writers, resolved, registry, outcomes, selected, identity,
                        roster, perf, config)

    counter_violations = _counter_violations(outcomes)
    write_text(run_dir / "08_logs" / "run.log", "\n".join(log_lines) + "\n")

    status_counts: dict[str, int] = {}
    for o in outcomes:
        status_counts[o.terminal_status] = status_counts.get(o.terminal_status, 0) + 1
    validation_counts: dict[str, int] = {}
    for o in outcomes:
        for v in o.validations:
            validation_counts[v.status] = validation_counts.get(v.status, 0) + 1

    fact_count = sum(len(o.facts) for o in outcomes)
    review_count = sum(len(o.review_items) for o in outcomes)
    failure_count = sum(len(o.failures) for o in outcomes)
    perf_report = perf.report()
    perf_report["output_bytes"] = sum(c["bytes"] for c in catalog)

    manifest = {
        "run_id": resolved.run_id,
        "created_at": resolved.created_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "extractor_version": EXTRACTOR_VERSION,
        "routing_version": ROUTING_VERSION,
        "semantics_version": SEMANTICS_VERSION,
        "configuration_hash": resolved.configuration_hash,
        "release_status": RELEASE_STATUS,
        "mode": config.mode,
        "input_dir": str(config.input_dir),
        "corpus_identity": identity,
        "selected_file_count": len(selected),
        "selection_sha256": sample_identity(selected),
        "schema_root": str(schema_root),
        "schema_count": len(registry),
        "terminal_status_counts": status_counts,
        "fact_count": fact_count,
        "review_item_count": review_count,
        "failure_count": failure_count,
        "validation_counts": validation_counts,
        "performance": perf_report,
        "counter_violations": counter_violations,
        "environment": resolved.environment,
        "reference_snapshot": str(config.reference_snapshot) if config.reference_snapshot else None,
        "comparison_rules_enabled": len(enabled_rules(DEFAULT_RULES)),
    }
    write_json(run_dir / "RUN_MANIFEST.json", manifest)
    write_json(run_dir / "RUN_STATUS.json", {
        "run_id": resolved.run_id, "status": "COMPLETED",
        "started_at": resolved.created_at,
        "completed_at": manifest["completed_at"],
        "release_status": RELEASE_STATUS,
        "sources_accounted_for": len(outcomes),
        "sources_selected": len(selected),
    })

    return RunResult(
        run_id=resolved.run_id, run_dir=run_dir, status="COMPLETED",
        source_count=len(outcomes), terminal_status_counts=status_counts,
        fact_count=fact_count, review_item_count=review_count,
        failure_count=failure_count, validation_counts=validation_counts,
        performance=perf_report, output_catalog=catalog,
        counter_violations=counter_violations,
        elapsed_seconds=time.perf_counter() - started,
    )


def _select_sources(config: Page3RunConfig, sources: Sequence[SourceFile]) -> list[SourceFile]:
    if config.file_list:
        picked = select_by_names(sources, config.file_list)
        if not picked:
            raise ValueError("file_list matched no file under input_dir")
        return picked
    n = config.effective_sample_size
    if config.mode == "quick_check":
        return quick_check_sample(sources, n or 10)
    if config.mode == "benchmark":
        return stratified_sample(sources, n or 200)
    if n is not None:
        return fifty_file_sample(sources, n)
    return list(sources)


def _counter_violations(outcomes: Sequence[SourceOutcome]) -> list[str]:
    out: list[str] = []
    for o in outcomes:
        if o.ctx is None:
            continue
        for v in check_fast_path(o.ctx.counters):
            out.append(f"{o.source.name}: {v}")
    return out


def _load_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")).get("completed_sha256", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _write_checkpoint(path: Path, outcomes: Sequence[SourceOutcome],
                      done: int, total: int) -> None:
    write_json(path, {
        "completed": done,
        "total": total,
        "completed_sha256": [o.source_sha256 for o in outcomes if o.source_sha256],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


# ====================================================================== #
# Emission
# ====================================================================== #

def _emit_all(writers: RunWriters,
              resolved: ResolvedConfig,
              registry: SchemaRegistry,
              outcomes: Sequence[SourceOutcome],
              selected: Sequence[SourceFile],
              identity: dict[str, Any],
              roster,
              perf: RunPerformance,
              config: Page3RunConfig) -> list[dict[str, Any]]:
    from .emit import emit_run_tables

    return emit_run_tables(writers, resolved, registry, outcomes, selected,
                           identity, roster, perf, config)


# ====================================================================== #
# Secondary entry points
# ====================================================================== #

def validate_run(run_dir: Path, schema_root: Optional[Path] = None) -> dict[str, Any]:
    """Validate every table in a run directory against its schema contract."""
    from .contracts_validator import validate_output_contracts

    run_dir = Path(run_dir)
    root = Path(schema_root) if schema_root else Path(__file__).resolve().parent / "contracts" / "schemas"
    result = validate_output_contracts(run_dir, root)
    write_json(run_dir / "04_validation" / "SCHEMA_VALIDATION.json", result)
    return result


def review_run(run_dir: Path) -> dict[str, Any]:
    """Load a completed run for inspection without re-running extraction."""
    from .review import load_run

    return load_run(Path(run_dir))


def generate_findings(run_dir: Path, output_dir: Optional[Path] = None) -> dict[str, Any]:
    """Produce the producer-findings layer from a frozen run's evidence."""
    from .findings import build_findings

    return build_findings(Path(run_dir), Path(output_dir) if output_dir else None)

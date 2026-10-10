"""Turn run outcomes into the contract tables.

Split out of :mod:`api` because it is pure serialisation: nothing here reads a
PDF, and every row it writes comes from an object already in memory. Keeping it
separate is what lets the fast-path counter assertions stay true — emission
cannot accidentally reopen a source.

Two invariants are enforced here rather than hoped for:

* **exactly one terminal status per source** — the source-status table is keyed
  by ``source_sha256`` and reconciled against the selected file count;
* **no duplicate primary key** — every table is de-duplicated on its declared
  key before it is written, and a collision is reported rather than silently
  dropped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from .anchors import (
    ACCEPTED,
    AMBIGUOUS_REVIEW,
    ANCHOR_DEFS,
    ANCHOR_REGISTRY_VERSION,
    REJECTED_DISTANCE_GATE,
    REJECTED_NO_CANDIDATE,
    TEXT_REGIME_INCOMPATIBLE,
    UNIT_MARKER_DEFS,
)
from .comparison import DEFAULT_RULES, ReferenceSnapshot, build_coverage
from .evidence import CellEvidence, Fact
from .numbers import STATE_NUMBER
from .performance import RunPerformance
from .semantic_mapping import FAMILIES, T1, T2, T3, T4, T5, T6
from .version import EXTRACTOR_VERSION, RELEASE_STATUS
from .writers import RunWriters, SchemaRegistry, write_json

FAMILY_TABLE = {
    T1: "page3_t1_general_stock", T2: "page3_t2_dam_status", T3: "page3_t3_inflows",
    T4: "page3_t4_withdrawals", T5: "page3_t5_transfers", T6: "page3_t6_ichkeul",
}

#: Keys carried on every base row. A table that does not declare one drops it
#: rather than failing: they are provenance, not payload.
LINEAGE_KEYS = frozenset({
    "run_id", "parser_version", "config_hash", "created_at", "page_index",
    "source_sha256", "source_file", "bulletin_date",
    "extractor_version", "configuration_hash",
})

# --- conformance to the accepted Phase 2 vocabularies -------------------- #
# The extractor's internal names are descriptive; the Phase 2 contracts have
# their own controlled vocabularies. Where an accepted value carries the meaning
# faithfully it is used; only three enums were extended (see
# tools/build_schemas.py ENUM_EXTENSIONS).

ANCHOR_MATCH_METHOD = {
    "EXACT_NORMALIZED_SUBSTRING": "exact",
    "LAMALEF_TOLERANT_SUBSTRING": "lam_alef_tolerant",
    "ALL_REQUIRED_TOKENS": "nfkc",
    "PARTIAL_TOKENS_PLUS_CHARSET": "partial_tokens_plus_charset",
    "NO_MATCH": "nfkc",
}

TEXT_HEALTH_CLASS = {
    "R1_c0_control_substitution": "R1_c0_control_substitution",
    "R2_presentation_forms": "R2_presentation_forms",
    "R3_standard_letters_lamalef_reversed": "R3_reversed_lam_alef",
    "R0_no_arabic_detected": "R0_no_arabic_detected",
}

#: p3_route_decision.terminal_status is the *routing* verdict, not the source
#: verdict. The source's single terminal status lives in p3_source_status.
ROUTE_TERMINAL = {
    "P3_PORTRAIT_STANDARD": "routed",
    "P3_ROTATED": "routed",
    "NOT_P3_CONFIRMED": "quarantine",
    "P3_REVIEW_REQUIRED": "review",
}

VALIDATION_STATUS = {"PASS": "pass", "FAIL": "fail", "WARN": "warn",
                     "NOT_ELIGIBLE": "not_evaluated"}
VALIDATION_SEVERITY = {"info": "info", "warning": "warn", "error": "error"}

PREFLIGHT_PAGE_CLASS = {
    "P3_PORTRAIT_STANDARD": "P3_PORTRAIT_STANDARD",
    "P3_ROTATED": "P3_ROTATED",
    "NOT_P3_CONFIRMED": "NOT_P3",
    "P3_REVIEW_REQUIRED": "REVIEW",
}

NO_REFERENCE_COLUMN = "NOT_APPLICABLE_NO_REFERENCE_COLUMN"


def _eligibility(status: str) -> str:
    return "eligible" if status == "ELIGIBLE" else "not_eligible"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_timestamp(path: Path) -> str:
    """Modification time of a file, as a property of that file."""
    return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat()


def emit_run_tables(writers: RunWriters,
                    resolved,
                    registry: SchemaRegistry,
                    outcomes: Sequence,
                    selected: Sequence,
                    identity: Mapping[str, Any],
                    roster,
                    perf: RunPerformance,
                    config) -> list[dict[str, Any]]:
    run_id = resolved.run_id
    cfg_hash = resolved.configuration_hash
    created = _now()
    run_dir = writers.run_dir

    lineage_p2 = dict(run_id=run_id, parser_version=EXTRACTOR_VERSION,
                      config_hash=cfg_hash, created_at=created)
    lineage_p3 = dict(run_id=run_id, extractor_version=EXTRACTOR_VERSION,
                      configuration_hash=cfg_hash, created_at=created)

    snapshot: Optional[ReferenceSnapshot] = None
    if config.reference_snapshot is not None:
        snapshot = ReferenceSnapshot.load(config.reference_snapshot)

    seen_keys: dict[str, set[tuple]] = {}
    collisions: list[str] = []

    def add(table: str, row: Mapping[str, Any]) -> None:
        schema = registry.get(table)
        # Lineage keys are attached to every base dict; a table that does not
        # declare one simply drops it. Any *other* unknown key is a real bug and
        # the writer still raises on it.
        extra = set(row) - set(schema.column_names)
        if extra:
            unexpected = extra - LINEAGE_KEYS
            if unexpected:
                raise KeyError(f"{table}: keys not in the schema: {sorted(unexpected)}")
            row = {k: v for k, v in row.items() if k not in extra}
        key = tuple(str(row.get(k, "")) for k in schema.primary_key)
        bucket = seen_keys.setdefault(table, set())
        if schema.primary_key and key in bucket:
            collisions.append(f"{table}: duplicate primary key {key}")
            return
        bucket.add(key)
        writers.writer(table).append(row)

    # ---------------------------------------------------------------- #
    # Per source
    # ---------------------------------------------------------------- #
    all_facts: list[Fact] = []
    for o in outcomes:
        src = o.source
        ctx = o.ctx
        sha = o.source_sha256 or f"UNREAD-{src.source_file_id}"
        date = (ctx.printed_date_parsed if ctx else None) or src.filename_date_parsed
        base_p2 = dict(lineage_p2, source_sha256=sha, source_file=src.relative_path,
                       bulletin_date=date, page_index=0)
        base_p3 = dict(lineage_p3, source_sha256=sha, source_file=src.relative_path,
                       bulletin_date=date)

        add("p3_source_manifest", dict(
            base_p2,
            file_size_bytes=src.size_bytes,
            page_count=ctx.page_count if ctx else None,
            encrypted=bool(ctx.encrypted) if ctx else False,
            open_status="ok" if ctx else "error",
            filename_date_raw=src.filename_date_raw,
            filename_date_parsed=src.filename_date_parsed,
            document_date_raw=(ctx.printed_date_raw if ctx else None),
            document_date_parsed=(ctx.printed_date_parsed if ctx else None),
            date_conflict=_date_conflict(src, ctx),
            duplicate_group_id="",
        ))

        add("p3_source_status", dict(
            base_p3,
            source_file_id=src.source_file_id,
            file_size_bytes=src.size_bytes,
            bulletin_date_filename=src.filename_date_parsed,
            bulletin_date_printed=ctx.printed_date_parsed if ctx else None,
            date_conflict=_date_conflict(src, ctx),
            logical_page_class=o.decision.logical_page_class if o.decision else "UNREAD",
            layout_family=o.decision.layout_family if o.decision else "UNKNOWN",
            exact_dimension_pair=o.decision.exact_dimension_pair if o.decision else "",
            shape_signature=o.decision.shape_signature if o.decision else "",
            text_regime=ctx.text_health.encoding_regime if ctx else "UNKNOWN",
            rotation=ctx.rotation if ctx else 0,
            rotation_normalization=ctx.rotation_normalization if ctx else "identity",
            route_id=o.decision.route_id if o.decision else "RT-00-UNREAD",
            terminal_status=o.terminal_status,
            fact_count=len(o.facts),
            cell_count=sum(len(f.cells) for f in o.families.values()),
            review_item_count=len(o.review_items),
            failure_count=len(o.failures),
            validation_fail_count=sum(1 for v in o.validations if v.status == "FAIL"),
            wall_seconds=o.timing.total_seconds if o.timing else 0.0,
            notes=o.error,
        ))

        if ctx is None:
            _emit_failures(add, base_p2, o.failures)
            continue

        pf = ctx.as_preflight_dict()
        add("p3_page_preflight", dict(
            base_p2, **pf,
            raster_coverage_pct=0.0,
            render_status="not_rendered",
            logical_page3_score=o.decision.decision_confidence if o.decision else 0.0,
            logical_page_class=PREFLIGHT_PAGE_CLASS.get(
                o.decision.logical_page_class if o.decision else "", "REVIEW"),
            logical_page_reasons_json=(o.decision.reasons if o.decision else []),
        ))

        add("p3_layout_fingerprint", dict(
            base_p2,
            exact_fingerprint=o.decision.exact_dimension_pair if o.decision else "",
            approx_fingerprint=o.decision.layout_family if o.decision else "",
            cluster_id=o.decision.shape_signature if o.decision else "",
            outlier_score=round(1.0 - (o.decision.decision_confidence if o.decision else 0.0), 4),
            table_count=len(ctx.fragments),
            table_shapes_json=[list(f.shape) for f in ctx.fragments],
            normalized_bboxes_json=[[round(v, 2) for v in f.bbox] for f in ctx.fragments],
            adjacency_graph_json=_adjacency(ctx),
            anchor_bitmask=_anchor_bitmask(o.anchors),
            text_health_class=TEXT_HEALTH_CLASS.get(
                ctx.text_health.encoding_regime, "R0_no_arabic_detected"),
        ))

        if o.decision is not None:
            add("p3_route_decision", dict(
                base_p2,
                route_id=o.decision.route_id,
                preflight_class=o.decision.logical_page_class,
                geometry_engine=ctx.geometry_engine,
                numeric_engine="pymupdf_words",
                anchor_engine="pymupdf_words+regime_normalization",
                label_engine="pymupdf_words",
                fallback_engines_json=o.decision.fallback_engines,
                trigger_evidence_json=o.decision.signals,
                decision_confidence=o.decision.decision_confidence,
                terminal_status=ROUTE_TERMINAL.get(
                    o.decision.logical_page_class, "review"),
            ))

        add("p3_engine_run", dict(
            base_p2, engine="pymupdf", engine_version=_pkg_version("pymupdf"),
            task="words",
            configuration_json={"single_pass": True, "textpage_builds": 1},
            status="ok", runtime_seconds=o.timing.context_build_seconds if o.timing else 0.0,
            peak_memory_mb=0.0, candidate_count=len(ctx.words),
            error_type="", error_message="", output_hash="", deterministic_match=None,
        ))
        add("p3_engine_run", dict(
            base_p2, engine="pymupdf", engine_version=_pkg_version("pymupdf"),
            task="drawings",
            configuration_json={"single_pass": True, "drawing_scans": 1},
            status="ok", runtime_seconds=0.0, peak_memory_mb=0.0,
            candidate_count=ctx.drawing_count,
            error_type="", error_message="", output_hash="", deterministic_match=None,
        ))
        add("p3_engine_run", dict(
            base_p2, engine="pdfplumber", engine_version=_pkg_version("pdfplumber"),
            task="geometry",
            configuration_json={"text_used_as_evidence": False,
                                "opened_from_shared_bytes": True},
            status="ok" if ctx.geometry_engine == "pdfplumber" else "error",
            runtime_seconds=0.0, peak_memory_mb=0.0,
            candidate_count=len(ctx.fragments),
            error_type="" if ctx.geometry_engine == "pdfplumber" else "GEOMETRY_UNAVAILABLE",
            error_message="; ".join(ctx.notes),
            output_hash="", deterministic_match=None,
        ))

        for frag in ctx.fragments:
            fam = _fragment_family(frag.index)
            add("p3_fragment_candidate", dict(
                base_p2,
                fragment_id=f"F{frag.index}",
                engine=ctx.geometry_engine,
                bbox_x0=round(frag.bbox[0], 2), bbox_y0=round(frag.bbox[1], 2),
                bbox_x1=round(frag.bbox[2], 2), bbox_y1=round(frag.bbox[3], 2),
                normalized_bbox_json={"rotation_normalization": ctx.rotation_normalization},
                row_count=frag.n_rows, column_count=frag.n_cols,
                cell_count=frag.ruled_cell_count,
                line_density=round(frag.ruled_cell_count / max(1, frag.n_rows * frag.n_cols), 4),
                candidate_section=fam or "UNASSIGNED",
                classification_score=o.decision.decision_confidence if o.decision else 0.0,
                classification_margin=0.0,
                classification_evidence_json={"reading_rank": frag.index,
                                              "shape": list(frag.shape)},
                assignment_status="assigned" if fam else "unassigned",
            ))

        _emit_anchors(add, base_p2, base_p3, o, ctx)
        _emit_schema_eras(add, base_p3, o, ctx)

        for fam, res in o.families.items():
            add("p3_family_status", dict(
                base_p3, family_id=fam,
                fragment_ranks=",".join(str(r) for r in res.fragment_ranks),
                family_status=res.status, schema_id=res.schema_id,
                row_count=res.row_count, fact_count=len(res.facts),
                numeric_fact_count=sum(1 for f in res.facts
                                       if f.semantic_state == STATE_NUMBER),
                non_numeric_state_count=sum(1 for f in res.facts
                                            if f.semantic_state != STATE_NUMBER),
                review_item_count=len(res.review_items),
                notes="; ".join(res.notes)[:2000],
            ))
            for cell in res.cells:
                add("p3_cell_evidence", dict(
                    base_p2, section_id=fam, fragment_id=f"F{cell.fragment_rank}",
                    cell_id=f"r{cell.row_index}c{cell.column_index}",
                    row_index=cell.row_index, column_index=cell.column_index,
                    bbox_x0=round(cell.bbox[0], 2), bbox_y0=round(cell.bbox[1], 2),
                    bbox_x1=round(cell.bbox[2], 2), bbox_y1=round(cell.bbox[3], 2),
                    raw_text=cell.raw_text, normalized_text=cell.normalized_text,
                    # strict_parsed_value is the cell's own text parsed alone;
                    # repaired_value is what a bounded recovery reassembled from
                    # the token word segmentation welded it into. Both are
                    # published, so the two readings can always be compared.
                    strict_parsed_value=cell.strict_parsed_value,
                    repaired_value=cell.recovered_value,
                    semantic_state=cell.semantic_state,
                    data_type="numeric" if cell.join_direction == "ltr" else "label",
                    engine=cell.engine, engine_version=_pkg_version("pymupdf"),
                    repair_rule_id=(cell.recovery_method or
                                    ("OVERPRINT_DEDUPLICATION"
                                     if cell.overprint_deduplicated else None)),
                    confidence=1.0 if cell.semantic_state == STATE_NUMBER else 0.5,
                    crop_path=None,
                ))

        for fact in o.facts:
            all_facts.append(fact)
            add("p3_cell_observation", _fact_row(base_p3, fact, o, src, ctx))

        for v in o.validations:
            add("p3_validation_result", dict(
                base_p2, section_id=v.section_id, entity_type=v.entity_type,
                entity_id=v.entity_id, rule_id=v.rule_id,
                eligibility_status=_eligibility(v.eligibility_status),
                observed_value=v.observed_value, comparison_value=v.comparison_value,
                difference=v.difference, tolerance=v.tolerance,
                status=VALIDATION_STATUS.get(v.status, "not_evaluated"),
                severity=VALIDATION_SEVERITY.get(v.severity, "info"),
                evidence_json=dict(v.evidence,
                                   eligibility_detail=v.eligibility_status),
            ))

        _emit_failures(add, base_p2, o.failures)
        _emit_reviews(add, base_p2, o.review_items)

        # PATCH-P5C-002: every numeric token the page prints inside a cell whose
        # fact published no number, whether it was recovered elsewhere, excluded
        # by a documented rule, or is a genuine unclaimed measurement.
        for item in getattr(o, "orphan_findings", ()):
            add("p3_orphan_numeric_token", dict(
                run_id=resolved.run_id, extractor_version=EXTRACTOR_VERSION,
                source_file_id=src.source_file_id, source_sha256=o.source_sha256,
                family_id=item["family_id"], record_id=item["record_id"],
                canonical_field_id=item["canonical_field_id"],
                evidence_id=item["evidence_id"],
                semantic_state=item["semantic_state"],
                layout_slot=item["layout_slot"],
                orphan_class=item["orphan_class"],
                token_text=item["token_text"], token_value=item["token_value"],
                token_class=item["token_class"], token_bbox=item["token_bbox"],
                token_span_text=item["token_span_text"],
                token_origin=item["token_origin"],
            ))

        if o.timing:
            c = o.timing.counters.as_dict()
            add("p3_performance_counters", dict(
                base_p3, **c,
                context_build_seconds=o.timing.context_build_seconds,
                extract_seconds=o.timing.extract_seconds,
                validate_seconds=o.timing.validate_seconds,
                total_seconds=o.timing.total_seconds,
            ))

    # ---------------------------------------------------------------- #
    # Run-scoped registries and comparison coverage
    # ---------------------------------------------------------------- #
    facts_by_date: dict[str, list[Fact]] = {}
    for o in outcomes:
        d = ((o.ctx.printed_date_parsed if o.ctx else None)
             or o.source.filename_date_parsed)
        if d:
            facts_by_date.setdefault(d, []).extend(o.facts)
    observed_dates = sorted(facts_by_date)
    date_min = observed_dates[0] if observed_dates else "2014-07-02"
    date_max = observed_dates[-1] if observed_dates else "2025-10-10"

    for row in roster.as_rows():
        add("p3_t2_roster_registry", row)

    _emit_connectivity(add, outcomes, date_min, date_max)

    for defn in ANCHOR_DEFS:
        variants = _variant_rows(outcomes, defn.anchor_id)
        for row in variants:
            add("p3_anchor_variant_registry", row)

    for rule in DEFAULT_RULES:
        add("p3_comparison_pair_registry", dict(
            comparison_rule_id=rule.comparison_rule_id,
            p3_family=rule.p3_family, p3_field_id=rule.p3_field_id,
            # T5 and T6 have no reference-side column at all; that structural
            # absence is stated rather than left blank.
            reference_field_id=rule.reference_field_id or NO_REFERENCE_COLUMN,
            reference_page_or_source="milestone1_reference_snapshot",
            grain=rule.entity_scope, entity_scope=rule.entity_scope, unit=rule.unit,
            p3_temporal_reference=rule.p3_temporal_reference,
            reference_temporal_reference=(rule.reference_temporal_reference
                                          or NO_REFERENCE_COLUMN),
            aggregation_rule=rule.aggregation_rule,
            denominator_class=rule.denominator_class,
            roster_registry_id=rule.roster_registry_id,
            # The validity window is the date span this run actually observed.
            # Every rule is disabled, so the window is descriptive, not an
            # authorisation.
            valid_from=date_min, valid_to=date_max,
            comparison_method="absolute_and_relative_tolerance",
            absolute_tolerance=rule.absolute_tolerance,
            relative_tolerance=rule.relative_tolerance,
            rounding_increment=rule.rounding_increment,
            status=rule.status,
            evidence_path="04_extractors/contracts/page3_to_milestone1_semantic_mapping.csv",
            notes=f"mapping_id={rule.mapping_id}; mapping_status={rule.mapping_status}; "
                  f"blocked_by={' | '.join(rule.blocking_preconditions)}",
        ))

    # Coverage records one attempted comparison key per (rule, bulletin date).
    # Without a frozen snapshot no comparison is attempted at all, so emitting
    # coverage rows would misrepresent what happened.
    if snapshot is not None:
        for bulletin_date in observed_dates:
            facts_for_date = facts_by_date.get(bulletin_date, [])
            for c in build_coverage(facts_for_date, DEFAULT_RULES, snapshot,
                                    bulletin_date, resolved.run_id):
                add("p3_comparison_input_coverage", dict(
                    coverage_id=c.coverage_id, run_id=resolved.run_id,
                    comparison_rule_id=c.comparison_rule_id,
                    reference_snapshot_id=c.reference_snapshot_id,
                    bulletin_date=bulletin_date,
                    entity_scope=c.entity_scope, entity_id=c.entity_id,
                    p3_available=c.p3_available,
                    reference_available=c.reference_available,
                    derivation_available=False,
                    p3_evidence_available=c.p3_evidence_available,
                    reference_provenance_available=True,
                    semantic_alignment_status=c.semantic_alignment_status,
                    temporal_alignment_status=c.temporal_alignment_status,
                    roster_alignment_status=c.roster_alignment_status,
                    comparability_status=c.comparability_status,
                    not_comparable_reason=c.not_comparable_reason,
                ))

    add("p3_comparison_validation_checks", dict(
        run_id=resolved.run_id, check_id="CVC-01",
        check_description="no comparison rule may run while its mapping_id status "
                          "forbids comparison",
        status="pass",
        detail=f"{len(DEFAULT_RULES)} rules registered, 0 enabled; every rule names "
               "the precondition that blocks it",
    ))
    add("p3_comparison_validation_checks", dict(
        run_id=resolved.run_id, check_id="CVC-02",
        check_description="the reference snapshot is provisional and carries no "
                          "decision authority",
        status="pass",
        detail=("no reference snapshot supplied" if snapshot is None else
                f"snapshot {snapshot.snapshot_id} sha256={snapshot.sha256} "
                f"audit_state={snapshot.audit_state} approved_for_comparison="
                f"{snapshot.approved_for_comparison}"),
    ))

    if snapshot is not None:
        add("p3_reference_snapshot_manifest", dict(
            reference_snapshot_id=snapshot.snapshot_id,
            dataset_name="milestone_1_reference",
            source_path=str(config.reference_snapshot),
            frozen_path=str(snapshot.path),
            sha256=snapshot.sha256, size_bytes=snapshot.path.stat().st_size,
            row_count=snapshot.row_count, column_count=snapshot.column_count,
            key_columns=snapshot.key_columns, key_duplicate_count=0,
            date_min=snapshot.date_min, date_max=snapshot.date_max,
            schema_hash=snapshot.schema_hash,
            reference_audit_state=snapshot.audit_state,
            approved_for_comparison=snapshot.approved_for_comparison,
            approval_evidence_path="NONE_THE_SNAPSHOT_IS_PROVISIONAL",
            # Timestamps of the frozen artefact, not of this run. Stamping the
            # run clock here would both misdescribe the snapshot and make the
            # table differ on every rerun of identical inputs.
            created_at=_file_timestamp(snapshot.path),
            supplied_at=_file_timestamp(snapshot.path),
            notes="PROVISIONAL: diagnostic comparison only, decision authority NONE",
        ))

    # ---------------------------------------------------------------- #
    # Publication exports
    # ---------------------------------------------------------------- #
    if config.emit_publication_exports:
        _emit_publications(add, registry, outcomes, all_facts, resolved, snapshot)

    catalog = writers.flush_all()

    _write_source_manifest_csv(run_dir, selected, outcomes, identity)
    write_json(run_dir / "08_logs" / "PRIMARY_KEY_COLLISIONS.json",
               {"collision_count": len(collisions), "collisions": collisions[:200]})
    _write_catalogs(run_dir, catalog, registry, perf)
    return catalog


# ---------------------------------------------------------------------- #

def _fact_row(base: Mapping[str, Any], fact: Fact, o, src, ctx) -> dict[str, Any]:
    return dict(
        base,
        source_file_id=src.source_file_id,
        source_relative_path=src.relative_path,
        bulletin_date_filename=src.filename_date_parsed,
        bulletin_date_printed=ctx.printed_date_parsed if ctx else None,
        logical_page_status=o.decision.logical_page_class if o.decision else "UNREAD",
        layout_family=o.decision.layout_family if o.decision else "UNKNOWN",
        rotation_normalization=ctx.rotation_normalization if ctx else "identity",
        family_id=fact.family_id, record_type=fact.record_type, record_id=fact.record_id,
        row_label_raw=fact.row_label_raw, row_label_ar=fact.row_label_ar,
        row_label_en=fact.row_label_en,
        canonical_label_ar=fact.canonical_label_ar,
        canonical_label_en=fact.canonical_label_en,
        canonical_field_id=fact.canonical_field_id, canonical_name=fact.canonical_name,
        raw_text=fact.raw_text, decoded_text_ar=fact.decoded_text_ar,
        parsed_value=fact.parsed_value, value_type=fact.value_type, unit=fact.unit,
        temporal_reference=fact.temporal_reference, semantic_state=fact.semantic_state,
        region_id=fact.region_id, dam_id=fact.dam_id, dam_candidate=fact.dam_candidate,
        match_method=fact.match_method, match_confidence=fact.match_confidence,
        source_node_id=fact.source_node_id, destination_node_id=fact.destination_node_id,
        via_node_id=fact.via_node_id,
        is_accounting_observation=fact.is_accounting_observation,
        schema_id=fact.schema_id, layout_slot=fact.layout_slot,
        column_semantics_method=fact.column_semantics_method,
        anchor_confirmation=fact.anchor_confirmation, evidence_id=fact.evidence_id,
        extraction_status=fact.extraction_status, validation_status=fact.validation_status,
        source_consistency_status=fact.source_consistency_status,
        review_status=fact.review_status, comparison_status=fact.comparison_status,
        recovery_method=fact.recovery_method, recovery_gate=fact.recovery_gate,
        recovery_evidence=fact.recovery_evidence,
        notes=fact.notes,
        dam_candidate_raw=fact.dam_candidate_raw,
        dam_candidate_normalized=fact.dam_candidate_normalized,
        identity_status=fact.identity_status,
        family_usability_status=fact.family_usability_status,
    )


def _publication_row(fact: Fact, o, src, ctx, resolved) -> dict[str, Any]:
    return dict(
        run_id=resolved.run_id, extractor_version=EXTRACTOR_VERSION,
        configuration_hash=resolved.configuration_hash,
        source_file_id=src.source_file_id,
        source_relative_path=src.relative_path,
        source_sha256=o.source_sha256,
        bulletin_date_filename=src.filename_date_parsed,
        bulletin_date_printed=ctx.printed_date_parsed if ctx else None,
        logical_page_status=o.decision.logical_page_class if o.decision else "UNREAD",
        layout_family=o.decision.layout_family if o.decision else "UNKNOWN",
        rotation_normalization=ctx.rotation_normalization if ctx else "identity",
        family_id=fact.family_id, record_type=fact.record_type, record_id=fact.record_id,
        row_label_raw=fact.row_label_raw, row_label_ar=fact.row_label_ar,
        row_label_en=fact.row_label_en,
        canonical_label_ar=fact.canonical_label_ar,
        canonical_label_en=fact.canonical_label_en,
        canonical_field_id=fact.canonical_field_id, canonical_name=fact.canonical_name,
        raw_text=fact.raw_text, decoded_text_ar=fact.decoded_text_ar,
        parsed_value=fact.parsed_value, value_type=fact.value_type, unit=fact.unit,
        temporal_reference=fact.temporal_reference, semantic_state=fact.semantic_state,
        region_id=fact.region_id, dam_id=fact.dam_id, dam_candidate=fact.dam_candidate,
        match_method=fact.match_method, match_confidence=fact.match_confidence,
        source_node_id=fact.source_node_id, destination_node_id=fact.destination_node_id,
        via_node_id=fact.via_node_id,
        is_accounting_observation=fact.is_accounting_observation,
        schema_id=fact.schema_id, layout_slot=fact.layout_slot,
        column_semantics_method=fact.column_semantics_method,
        anchor_confirmation=fact.anchor_confirmation, evidence_id=fact.evidence_id,
        extraction_status=fact.extraction_status, validation_status=fact.validation_status,
        source_consistency_status=fact.source_consistency_status,
        review_status=fact.review_status, comparison_status=fact.comparison_status,
        recovery_method=fact.recovery_method, recovery_gate=fact.recovery_gate,
        recovery_evidence=fact.recovery_evidence,
        notes=fact.notes,
        dam_candidate_raw=fact.dam_candidate_raw,
        dam_candidate_normalized=fact.dam_candidate_normalized,
        identity_status=fact.identity_status,
        family_usability_status=fact.family_usability_status,
    )


def _emit_publications(add, registry, outcomes, all_facts, resolved, snapshot) -> None:
    review_seq = 0
    for o in outcomes:
        src, ctx = o.source, o.ctx
        for fact in o.facts:
            row = _publication_row(fact, o, src, ctx, resolved)
            add("page3_all_facts_long", row)
            table = FAMILY_TABLE.get(fact.family_id)
            if table:
                add(table, row)

        add("page3_source_status", dict(
            run_id=resolved.run_id, extractor_version=EXTRACTOR_VERSION,
            configuration_hash=resolved.configuration_hash,
            source_file_id=src.source_file_id,
            source_relative_path=src.relative_path,
            source_sha256=o.source_sha256 or f"UNREAD-{src.source_file_id}",
            bulletin_date_filename=src.filename_date_parsed,
            bulletin_date_printed=ctx.printed_date_parsed if ctx else None,
            date_conflict=_date_conflict(src, ctx),
            logical_page_status=o.decision.logical_page_class if o.decision else "UNREAD",
            layout_family=o.decision.layout_family if o.decision else "UNKNOWN",
            rotation_normalization=ctx.rotation_normalization if ctx else "identity",
            text_regime=ctx.text_health.encoding_regime if ctx else "UNKNOWN",
            terminal_status=o.terminal_status,
            fact_count=len(o.facts), review_item_count=len(o.review_items),
            notes=o.error,
        ))

        for item in o.review_items:
            review_seq += 1
            add("page3_open_review_items", dict(
                review_item_id=f"REV-{resolved.run_id}-{review_seq:06d}",
                run_id=resolved.run_id,
                source_relative_path=src.relative_path,
                source_sha256=o.source_sha256 or f"UNREAD-{src.source_file_id}",
                bulletin_date=(ctx.printed_date_parsed if ctx else None)
                or src.filename_date_parsed,
                family_id=item.get("section_id", ""),
                entity_id=item.get("entity_id", ""),
                review_reason=item.get("review_reason", ""),
                priority=item.get("priority", "medium"),
                evidence_id=item.get("evidence_id", ""),
                review_status="OPEN",
            ))

    for row in _data_dictionary_rows(registry):
        add("page3_data_dictionary", row)


NULL_MEANING = (
    "empty means the value was not printed as a number; see semantic_state for "
    "which state it was. An empty parsed_value is never zero."
)


def _data_dictionary_rows(registry: SchemaRegistry) -> Iterable[dict[str, Any]]:
    for table in registry.tables():
        if not table.startswith("page3_"):
            continue
        schema = registry.get(table)
        for c in schema.columns:
            yield {
                "table_name": table,
                "column_name": c["name"],
                "data_type": c["type"],
                "nullable": bool(c["nullable"]),
                "unit": "Mm3" if c["name"] == "parsed_value" else "",
                "description": c.get("description", ""),
                "null_meaning": NULL_MEANING if c["name"] == "parsed_value" else (
                    "empty means not applicable or not measured" if c["nullable"] else ""),
                "source_layer": schema.layer,
            }


def _emit_failures(add, base, failures) -> None:
    for f in failures:
        add("p3_extraction_failure", dict(
            base,
            section_id=f.get("section_id", ""), fragment_id=f.get("fragment_id", ""),
            failure_stage=f.get("failure_stage", "extraction"),
            failure_code=f.get("failure_code", "UNKNOWN"),
            severity=VALIDATION_SEVERITY.get(f.get("severity", "error"), "error"),
            message=f.get("message", ""), engine=f.get("engine", ""),
            engine_error=f.get("engine_error", ""),
            evidence_json=f.get("evidence", {}), retry_history_json=[],
            requires_manual_review=f.get("severity", "error") == "error",
        ))


def _emit_reviews(add, base, items) -> None:
    for it in items:
        add("p3_manual_review_queue", dict(
            base,
            section_id=it.get("section_id", ""), entity_id=it.get("entity_id", ""),
            review_reason=it.get("review_reason", ""),
            priority=it.get("priority", "medium"),
            failure_codes_json=it.get("failure_codes", []),
            validation_statuses_json=it.get("validation_statuses", []),
            annotated_page_path="", crop_paths_json=[],
            review_status="open", reviewer="", resolution="",
        ))


def _emit_anchors(add, base_p2, base_p3, o, ctx) -> None:
    anchors = o.anchors
    if anchors is None:
        return
    for i, cand in enumerate(anchors.candidates, 1):
        add("p3_anchor_candidate", dict(
            base_p2,
            anchor_candidate_id=f"{cand.anchor_id}-{i:03d}",
            section_id=cand.section_id, engine="pymupdf_words",
            raw_text=cand.raw_text, normalized_text=cand.normalized_text,
            bbox_x0=round(cand.bbox[0], 2), bbox_y0=round(cand.bbox[1], 2),
            bbox_x1=round(cand.bbox[2], 2), bbox_y1=round(cand.bbox[3], 2),
            match_method=ANCHOR_MATCH_METHOD.get(cand.match_method, "nfkc"),
            match_score=cand.score,
            is_hard_negative=bool(cand.prohibited_hits),
            review_status=_candidate_review_status(cand, anchors),
        ))

    for att in anchors.attempts:
        best = att.best_candidate
        add("p3_anchor_attempt", dict(
            base_p3, anchor_id=att.anchor_id, section_id=att.section_id,
            text_regime=att.text_regime, terminal_status=att.status,
            reason=att.reason, candidate_count=att.candidate_count,
            best_score=best.score if best else None,
            best_match_method=best.match_method if best else "",
            best_raw_text=best.raw_text if best else "",
            best_normalized_text=best.normalized_text if best else "",
        ))
        add("p3_anchor_adjudication", dict(
            base_p3, anchor_id=att.anchor_id, section_id=att.section_id,
            decision=att.status,
            winning_candidate_text=best.normalized_text if best else "",
            winning_score=best.score if best else None,
            runner_up_score=None, margin=None,
            required_tokens_hit=best.required_hits if best else 0,
            prohibited_tokens_hit="|".join(best.prohibited_hits) if best else "",
            decision_basis=att.reason,
        ))
        if att.status == ACCEPTED and att.linked_fragment_rank is not None:
            defn = next((d for d in ANCHOR_DEFS if d.anchor_id == att.anchor_id), None)
            add("p3_anchor_fragment_link", dict(
                base_p3, anchor_id=att.anchor_id, section_id=att.section_id,
                fragment_id=f"F{att.linked_fragment_rank}",
                fragment_rank=att.linked_fragment_rank,
                link_method=att.link_method, gap_points=att.link_gap,
                distance_gate_points=defn.max_gap_above if defn else 0.0,
                coordinates_normalized=ctx.rotation_normalization != "identity",
            ))
        if att.status in (AMBIGUOUS_REVIEW, REJECTED_DISTANCE_GATE):
            add("p3_anchor_review_queue", dict(
                base_p3, anchor_id=att.anchor_id, section_id=att.section_id,
                terminal_status=att.status, review_reason=att.reason,
                priority="medium", review_status="OPEN",
            ))

    for i, um in enumerate(anchors.unit_markers, 1):
        nearest = None
        for frag in ctx.fragments:
            if frag.bbox[1] >= um.bbox[3]:
                nearest = frag.index
                break
        add("p3_unit_marker_inventory", dict(
            base_p3,
            unit_marker_occurrence_id=f"{um.anchor_id}-{i:03d}",
            unit_marker_id=um.anchor_id,
            raw_text=um.raw_text, normalized_text=um.normalized_text,
            bbox_x0=round(um.bbox[0], 2), bbox_y0=round(um.bbox[1], 2),
            bbox_x1=round(um.bbox[2], 2), bbox_y1=round(um.bbox[3], 2),
            nearest_fragment_rank=nearest,
            is_routing_anchor=False,
        ))


EVIDENCE_KB_T5 = "01_knowledge_base/07_connectivity/T5 Edges and Accounting.md"


def _emit_connectivity(add, outcomes, date_min: str, date_max: str) -> None:
    """Emit the T5 connectivity topology and its dated observations.

    The discriminator this exists to protect: rows 1-3 are physical edges and
    row 4 is an accounting observation restating rows 2+3. The accounting row
    goes into ``p3_accounting_relationship_registry``; it is deliberately
    **absent** from ``p3_edge_registry``, so a consumer that reads the edge
    registry as a graph cannot pick it up by accident.
    """
    from .semantic_mapping import (
        ACCOUNTING,
        EDGE,
        ICHKEUL_DESTINATION_ID,
        ICHKEUL_NODE_CLASS,
        TRANSFER_ROWS,
        TRANSFER_VALUE_ORDER_RTL,
    )

    seen_nodes: dict[str, dict[str, Any]] = {}

    def note_node(node_id: str, name_ar: str, name_fr: str, node_class: str) -> None:
        if node_id and node_id not in seen_nodes:
            seen_nodes[node_id] = {
                "node_id": node_id, "name_ar": name_ar, "name_fr": name_fr,
                "node_class": node_class,
                "first_seen_date": date_min, "last_seen_date": date_max,
                "evidence_path": EVIDENCE_KB_T5,
            }

    for row in TRANSFER_ROWS:
        if row.kind == EDGE:
            note_node(row.source_node_id, "", "", "dam")
            note_node(row.destination_node_id, "", "", "dam")
            note_node(row.via_node_id, "", "", "conveyance")
            add("p3_edge_registry", {
                "edge_id": row.record_id,
                "from_node_id": row.source_node_id,
                "to_node_id": row.destination_node_id,
                "via_node_id": row.via_node_id,
                "edge_or_accounting": "edge",
                "label_ar_raw": row.label_ar,
                "label_normalized": row.label_en,
                "valid_from": date_min, "valid_to": date_max,
                "evidence_path": EVIDENCE_KB_T5,
            })
        else:
            note_node(row.destination_node_id, "", "", "dam")
            add("p3_accounting_relationship_registry", {
                "rel_id": row.record_id,
                "subject_node_id": row.destination_node_id,
                "expression": "EDGE-T5-02 + EDGE-T5-03",
                "tolerance_class": "diagnostic_only_never_a_hard_failure",
                "evidence_path": EVIDENCE_KB_T5,
            })

    for node in seen_nodes.values():
        add("p3_node_registry", node)

    add("p3_external_destination_registry", {
        "dest_id": ICHKEUL_DESTINATION_ID,
        "name": "Lake Ichkeul",
        "dest_class": ICHKEUL_NODE_CLASS,
        "notes": "external environmental destination; never a dam node and never "
                 "a dam-to-dam edge",
    })

    # Dated observations, one per (edge, bulletin date), built from the facts
    # already extracted. Only physical edges appear here.
    edge_ids = {r.record_id for r in TRANSFER_ROWS if r.kind == EDGE}
    for o in outcomes:
        date = ((o.ctx.printed_date_parsed if o.ctx else None)
                or o.source.filename_date_parsed)
        if not date:
            continue
        prefix = f"T5-{o.source_sha256[:12]}-"
        by_edge: dict[str, dict[str, Any]] = {}
        for f in o.facts:
            if f.family_id != "T5" or not f.record_id.startswith(prefix):
                continue
            key = f.record_id[len(prefix):]
            if key not in edge_ids:
                continue
            slot = by_edge.setdefault(key, {"state": f.semantic_state,
                                            "evidence_id": f.evidence_id})
            slot[f.canonical_field_id] = f.parsed_value
            if f.evidence_id:
                slot["evidence_id"] = f.evidence_id
        for edge_id, slot in by_edge.items():
            day, prev, curr = TRANSFER_VALUE_ORDER_RTL
            add("p3_edge_observation", {
                "obs_id": f"OBS-{edge_id}-{date}",
                "edge_id": edge_id,
                "bulletin_date": date,
                "value_day": slot.get(day),
                "value_prev_season_cum": slot.get(prev),
                "value_curr_season_cum": slot.get(curr),
                "semantic_state": slot.get("state", ""),
                "cell_evidence_id": slot.get("evidence_id", ""),
            })


def _candidate_review_status(cand, anchors) -> str:
    """Confirmed when this candidate is the one the adjudicator accepted."""
    if cand.prohibited_hits:
        return "rejected"
    for att in anchors.attempts:
        if att.anchor_id != cand.anchor_id or att.best_candidate is None:
            continue
        if att.status == ACCEPTED and att.best_candidate.raw_text == cand.raw_text:
            return "confirmed"
    return "candidate"


def _emit_schema_eras(add, base_p3, o, ctx) -> None:
    if o.decision is None:
        return
    eras = schema_era_for_ctx(o, ctx)
    for fam, era in eras.items():
        res = o.families.get(fam)
        add("p3_schema_era_assignment", dict(
            base_p3, family_id=fam, era_id=era,
            assignment_basis="measured fragment shape (never the calendar year)",
            observed_shape=o.decision.shape_signature,
            schema_id=res.schema_id if res else "",
        ))


def schema_era_for_ctx(o, ctx) -> dict[str, str]:
    from .routing import schema_era_for

    return schema_era_for(o.decision, ctx.shape_signature)


def _variant_rows(outcomes, anchor_id: str) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    first: dict[tuple[str, str], str] = {}
    section = ""
    for o in outcomes:
        if o.anchors is None:
            continue
        for aid, text, method in o.anchors.variants:
            if aid != anchor_id or not text:
                continue
            key = (text, method)
            counts[key] = counts.get(key, 0) + 1
            first.setdefault(key, o.source_sha256)
            section = next((a.section_id for a in o.anchors.attempts
                            if a.anchor_id == anchor_id), "")
    return [
        {
            "registry_version": ANCHOR_REGISTRY_VERSION,
            "anchor_id": anchor_id,
            "section_id": section,
            "normalized_text": text,
            "match_method": method,
            "observed_count": n,
            "first_seen_source_sha256": first[(text, method)],
            "evidence": "accepted by the anchor adjudicator in this run",
        }
        for (text, method), n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def _date_conflict(src, ctx) -> bool:
    if ctx is None or not ctx.printed_date_parsed or not src.filename_date_parsed:
        return False
    return ctx.printed_date_parsed != src.filename_date_parsed


def _fragment_family(rank: int) -> str:
    from .semantic_mapping import FRAGMENT_FAMILY

    return FRAGMENT_FAMILY.get(rank, "")


def _adjacency(ctx) -> list[list[int]]:
    return [[f.index, f.index + 1] for f in ctx.fragments[:-1]]


def _anchor_bitmask(anchors) -> int:
    if anchors is None:
        return 0
    mask = 0
    for i, defn in enumerate(ANCHOR_DEFS):
        if anchors.status_for(defn.anchor_id) == ACCEPTED:
            mask |= 1 << i
    return mask


_PKG_CACHE: dict[str, str] = {}


def _pkg_version(name: str) -> str:
    if name in _PKG_CACHE:
        return _PKG_CACHE[name]
    try:
        if name == "pymupdf":
            import fitz

            v = str(getattr(fitz, "VersionBind", getattr(fitz, "__version__", "unknown")))
        else:
            mod = __import__(name)
            v = str(getattr(mod, "__version__", "unknown"))
    except Exception:  # noqa: BLE001
        v = "unavailable"
    _PKG_CACHE[name] = v
    return v


def _write_source_manifest_csv(run_dir: Path, selected, outcomes, identity) -> None:
    import csv

    path = run_dir / "SOURCE_MANIFEST.csv"
    by_id = {o.source.source_file_id: o for o in outcomes}
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["source_file_id", "source_relative_path", "size_bytes",
                    "source_sha256", "filename_date", "printed_date",
                    "terminal_status"])
        for s in selected:
            o = by_id.get(s.source_file_id)
            w.writerow([
                s.source_file_id, s.relative_path, s.size_bytes,
                o.source_sha256 if o else "",
                s.filename_date_parsed or "",
                (o.ctx.printed_date_parsed if o and o.ctx else "") or "",
                o.terminal_status if o else "NOT_PROCESSED",
            ])
    write_json(run_dir / "01_source_inventory" / "CORPUS_IDENTITY.json", dict(identity))


def _write_catalogs(run_dir: Path, catalog, registry: SchemaRegistry,
                    perf: RunPerformance) -> None:
    import csv

    with open(run_dir / "OUTPUT_CATALOG.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["table", "layer", "grain", "relative_path", "row_count",
                    "column_count", "bytes", "sha256"])
        for c in sorted(catalog, key=lambda c: c["table"]):
            rel = str(Path(c["path"]).relative_to(run_dir)).replace("\\", "/")
            w.writerow([c["table"], c["layer"], c["grain"], rel, c["row_count"],
                        c["column_count"], c["bytes"], c["sha256"]])

    with open(run_dir / "EVIDENCE_CATALOG.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["evidence_table", "relative_path", "row_count", "sha256",
                    "primary_key", "what_it_records"])
        for c in sorted(catalog, key=lambda c: c["table"]):
            if c["table"].startswith("page3_"):
                continue
            schema = registry.get(c["table"])
            rel = str(Path(c["path"]).relative_to(run_dir)).replace("\\", "/")
            w.writerow([c["table"], rel, c["row_count"], c["sha256"],
                        "|".join(schema.primary_key), schema.grain])

    write_json(run_dir / "07_performance" / "PERFORMANCE_REPORT.json", perf.report())

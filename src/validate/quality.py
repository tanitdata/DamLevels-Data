"""Professor QA checks C through G over accepted engineering products.

This module reads repository tables only. It does not invoke extraction or any
scientific pipeline and never edits accepted numeric observations.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import pydantic

from validate.capacity import CapacityIndex


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def printed_decimal_places(raw_value: str) -> int:
    """Return displayed decimal places; integers imply whole-unit precision."""
    compact = raw_value.strip().replace(" ", "")
    match = re.search(r"[,.](\d+)$", compact)
    return len(match.group(1)) if match else 0


def rounding_increment(decimal_places: int) -> Decimal:
    return Decimal(1).scaleb(-decimal_places)


def duplicate_storage_keys(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        grouped[(row["dam_id"], row["date"])].append(row["observation_id"])
    return {key: ids for key, ids in grouped.items() if len(ids) > 1}


def classify_physical_validity(value: Decimal, capacity: dict) -> str:
    if value < 0:
        return "NEGATIVE_STORAGE"
    if capacity["status"] == "UNAVAILABLE":
        return "CAPACITY_UNAVAILABLE"
    if capacity["status"] == "AMBIGUOUS":
        return "CAPACITY_AMBIGUOUS"
    if value > Decimal(str(capacity["capacity_mm3"])):
        return "ABOVE_CAPACITY"
    return "PASS"


def classify_fill_rounding(
    storage_mm3: Decimal,
    capacity: dict,
    printed_fill_pct: Decimal | None,
    printed_places: int | None,
) -> tuple[str, Decimal | None, Decimal | None, Decimal | None]:
    if printed_fill_pct is None:
        return "NO_PRINTED_FILL", None, None, None
    if capacity["status"] == "UNAVAILABLE":
        return "CAPACITY_UNAVAILABLE", None, None, None
    if capacity["status"] == "AMBIGUOUS":
        return "CAPACITY_AMBIGUOUS", None, None, None
    capacity_value = Decimal(str(capacity["capacity_mm3"]))
    computed = Decimal(100) * storage_mm3 / capacity_value
    places = 0 if printed_places is None else printed_places
    half_increment = rounding_increment(places) / Decimal(2)
    lower = printed_fill_pct - half_increment
    upper = printed_fill_pct + half_increment
    classification = "MATCH_WITHIN_ROUNDING" if lower <= computed <= upper else "MISMATCH"
    return classification, computed, lower, upper


def classify_national_total(
    component_sum: Decimal,
    printed_total: Decimal,
    component_count: int,
    printed_increment: Decimal,
    accepted_component_sum: Decimal | None = None,
) -> tuple[str, Decimal, Decimal]:
    """Classify using the maximum error implied by printed source precision.

    Page 1 component storage values are printed to 0.001 Mm3. The independently
    printed grand total contributes half of its own displayed increment.
    """
    residual = component_sum - printed_total
    tolerance = Decimal(component_count) * Decimal("0.0005") + printed_increment / Decimal(2)
    # The accepted checksum artifact serialized some binary-float sums with
    # tails such as 1465.6870000000001. Compare at the established 0.001 Mm3
    # source precision so representation noise is not mislabeled as an
    # extraction difference.
    if accepted_component_sum is not None and (
        component_sum.quantize(Decimal("0.001"))
        != accepted_component_sum.quantize(Decimal("0.001"))
    ):
        return "EXTRACTION_SUSPECT", residual, tolerance
    if residual == 0:
        return "MATCH_EXACT", residual, tolerance
    if abs(residual) <= tolerance:
        return "MATCH_WITHIN_ROUNDING", residual, tolerance
    return "SOURCE_PRINTED_DISAGREEMENT", residual, tolerance


def apply_national_disposition(
    bulletin_date: str,
    computed_classification: str,
    dispositions_by_date: dict[str, dict[str, str]],
) -> tuple[str, dict[str, str] | None]:
    """Apply a preserved, evidence-backed QA disposition without changing values.

    E3.1 only permits a roster/scope disposition to qualify a numerical source
    disagreement. This guard prevents the registry from overriding matches,
    missing evidence, or extraction-suspect results.
    """
    disposition = dispositions_by_date.get(bulletin_date)
    if disposition is None:
        return computed_classification, None
    requested = disposition["classification"]
    if requested != "SOURCE_ROSTER_SCOPE_DIFFERENCE":
        raise ValueError(f"unsupported national disposition for {bulletin_date}: {requested}")
    if computed_classification != "SOURCE_PRINTED_DISAGREEMENT":
        raise ValueError(
            f"national disposition for {bulletin_date} requires SOURCE_PRINTED_DISAGREEMENT; "
            f"computed {computed_classification}"
        )
    if disposition.get("status") != "SUPPORTED_BY_PRESERVED_AUDIT_EVIDENCE":
        raise ValueError(f"national disposition for {bulletin_date} lacks supported status")
    return requested, disposition


def classify_transfer_candidate(
    row: dict[str, str],
    *,
    date_semantics_resolved: bool,
    counterpart_value: Decimal | None = None,
    counterpart_increment: Decimal = Decimal("0.001"),
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if row["row_role"] != "PHYSICAL_TRANSFER_EDGE":
        reasons.append("ACCOUNTING_NOT_HYDRAULIC_EDGE")
    if row["row_role"] == "PHYSICAL_TRANSFER_EDGE" and (
        not row.get("from_dam_id") or not row.get("to_dam_id")
    ):
        reasons.append("UNRESOLVED_DAM_CROSSWALK")
    if not date_semantics_resolved:
        reasons.append("DATE_SEMANTICS_UNRESOLVED")
    if row.get("source_consistency_status") != "CHECKED":
        reasons.append("SOURCE_CONSISTENCY_NOT_CHECKED")
    if counterpart_value is None:
        reasons.append("NO_DIRECT_COUNTERPART")

    precedence = (
        "ACCOUNTING_NOT_HYDRAULIC_EDGE",
        "UNRESOLVED_DAM_CROSSWALK",
        "DATE_SEMANTICS_UNRESOLVED",
        "SOURCE_CONSISTENCY_NOT_CHECKED",
        "NO_DIRECT_COUNTERPART",
    )
    for reason in precedence:
        if reason in reasons:
            return reason, reasons

    source_value = Decimal(row["value"])
    residual = source_value - counterpart_value
    if residual == 0:
        return "MATCH_EXACT", []
    tolerance = counterpart_increment / Decimal(2) + Decimal("0.0005")
    if abs(residual) <= tolerance:
        return "MATCH_WITHIN_ROUNDING", []
    return "DISCREPANCY_DOCUMENTED", []


def _status(pass_count: int, fail_count: int, eligible: int, no_eligible: str = "NO_ELIGIBLE_RECORDS") -> str:
    if eligible == 0:
        return no_eligible
    return "PASS" if fail_count == 0 else "REVIEW_REQUIRED"


def _render_report(summary: dict) -> str:
    kpis = summary["kpis"]
    lines = [
        "# Automatic QA report — professor checks C through G",
        "",
        "This report is generated from the same result object as `qa_summary.json`. The build validates accepted E2 engineering tables; it does not rerun extraction or change scientific values.",
        "",
        "| KPI | Eligible | Pass | Fail | Excluded/Unknown | Status |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for key in ("C", "D", "E", "F", "G"):
        item = kpis[key]
        lines.append(
            f"| {key}. {item['name']} | {item['eligible']:,} | {item['pass']:,} | "
            f"{item['fail']:,} | {item['excluded_unknown']:,} | {item['status']} |"
        )
    lines.extend([
        "",
        "## Denominators and findings",
        "",
        f"### C. Uniqueness",
        "",
        f"Population: **{kpis['C']['population']:,} primary storage rows**. Unique `(dam_id, date)` keys: **{kpis['C']['details']['unique_keys']:,}**; duplicated keys: **{kpis['C']['details']['duplicate_keys']:,}**. No row is silently deduplicated.",
        "",
        "### D. Physical validity",
        "",
        f"Population: **{kpis['D']['population']:,} storage observations**. The eligible denominator includes rows for which negative storage and date-specific capacity bounds can be evaluated. Capacity-unavailable and ambiguous rows are excluded, not counted as physical failures.",
        "",
        f"Classifications: `{json.dumps(kpis['D']['details']['classifications'], sort_keys=True)}`.",
        "",
        "### E. Fill consistency",
        "",
        f"Population: **{kpis['E']['population']:,} storage observations**. Eligible comparisons require both a printed fill value and a known date-specific capacity. Rounding intervals come from the displayed printed precision, rather than a universal tolerance.",
        "",
        f"Classifications: `{json.dumps(kpis['E']['details']['classifications'], sort_keys=True)}`.",
        "",
        "### F. National total reconciliation",
        "",
        f"Population: **{kpis['F']['population']:,} canonical bulletin dates**. Eligible dates require a complete accepted Page 1 grand-total checksum row. The rounding bound is the sum of half-unit bounds for the printed 0.001 Mm3 dam components and the independently printed total.",
        "",
        f"Classifications: `{json.dumps(kpis['F']['details']['classifications'], sort_keys=True)}`.",
        "",
        f"Evidence-backed roster/scope exclusions: `{json.dumps(kpis['F']['details']['roster_scope_dates'])}`. Remaining source-printed disagreements: `{json.dumps(kpis['F']['details']['remaining_disagreement_dates'])}`.",
        "",
        "### G. Transfer balance",
        "",
        f"Daily Page 3 candidates: **{kpis['G']['population']:,}**, comprising **{kpis['G']['details']['daily_physical_facts']:,} physical-edge facts** and **{kpis['G']['details']['accounting_rows']:,} accounting observations**. Eligible direct comparisons: **{kpis['G']['eligible']:,}**. Excluded rows are not failed transfers.",
        "",
        f"Primary classifications: `{json.dumps(kpis['G']['details']['primary_classifications'], sort_keys=True)}`.",
        "",
        f"All recorded ineligibility reasons: `{json.dumps(kpis['G']['details']['reason_counts'], sort_keys=True)}`.",
        "",
        "## Known limitations affecting interpretation",
        "",
        "- Capacity evidence has explicit unavailable intervals; no lookup crosses those gaps.",
        "- Page 3 authority remains **PROBABLE**.",
        "- Bouhertma/Bou Heurtma and Zayatin/Ziatine endpoint mappings remain unresolved and are not promoted.",
        "- The selected Page 3 product says `SAME_DAY`, while the canonical-base contract describes minus-one-calendar-day transfer semantics. E3.1 performs no assumed alignment.",
        "- Page 3 source consistency is `NOT_CHECKED`, and no independently reported compatible receiving-side counterpart is established.",
        "- The canonical bulletin inventory contains partial page sets; missing evidence remains excluded or unresolved.",
        "",
        "## Build metadata",
        "",
        f"- Generated UTC: `{summary['generated_utc']}`",
        f"- Pydantic tested: `{summary['pydantic_version']}`",
        f"- Storage authority: `{summary['authority']['storage']}`",
        f"- Page 3 authority: `{summary['authority']['page3']}`",
        "- Scientific pipelines rerun: **NO**",
        "- Models run: **NO**",
        "",
        "Earlier validation receipts remain in `E1_VALIDATION_REPORT.md` and `E2_VALIDATION_REPORT.md`.",
        "",
    ])
    return "\n".join(lines)


def generate_qa(root: Path) -> dict:
    qa_root = root / "qa"
    storage = read_csv(root / "data/storage.csv")
    printed_fill = read_csv(qa_root / "printed_fill_reference.csv")
    transfers = read_csv(root / "data/transfers.csv")
    manifest = read_csv(root / "sources/manifest.csv")
    national_evidence = read_csv(root / "provenance/page1_national_totals.csv")
    national_dispositions = read_csv(root / "provenance/national_reconciliation_dispositions.csv")
    lineage = read_csv(root / "provenance/storage_lineage.csv")
    capacity_index = CapacityIndex.from_csv(root / "data/capacity_history.csv")

    dispositions_by_date: dict[str, dict[str, str]] = {}
    for row in national_dispositions:
        day = row["bulletin_date"]
        if day in dispositions_by_date:
            raise ValueError(f"duplicate national reconciliation disposition: {day}")
        dispositions_by_date[day] = row

    lineage_by_id = {row["lineage_id"]: row for row in lineage}

    # C: storage-key uniqueness.
    duplicates = duplicate_storage_keys(storage)
    unique_rows = [{
        "row_type": "SUMMARY",
        "dam_id": "",
        "date": "",
        "key_count": len(storage) - sum(len(ids) - 1 for ids in duplicates.values()),
        "observation_ids": "",
        "classification": "PASS" if not duplicates else "DUPLICATES_PRESENT",
        "notes": f"storage_rows={len(storage)}; duplicate_keys={len(duplicates)}",
    }]
    for (dam_id, day), observation_ids in sorted(duplicates.items()):
        unique_rows.append({
            "row_type": "DUPLICATE_KEY",
            "dam_id": dam_id,
            "date": day,
            "key_count": len(observation_ids),
            "observation_ids": "|".join(observation_ids),
            "classification": "DUPLICATE",
            "notes": "Records retained; no automatic deduplication.",
        })
    write_csv(
        qa_root / "uniqueness.csv",
        ["row_type", "dam_id", "date", "key_count", "observation_ids", "classification", "notes"],
        unique_rows,
    )

    # D: physical validity under date-specific capacity evidence.
    physical_rows: list[dict] = []
    physical_counts = Counter()
    capacity_cache: dict[tuple[str, str], dict] = {}
    for row in storage:
        key = (row["dam_id"], row["date"])
        capacity = capacity_cache.setdefault(key, capacity_index.for_date(*key))
        value = Decimal(row["value"])
        classification = classify_physical_validity(value, capacity)
        physical_counts[classification] += 1
        match_sources = "|".join(
            str(item.get("source_file", "")) for item in capacity["matches"]
        )
        physical_rows.append({
            "observation_id": row["observation_id"],
            "dam_id": row["dam_id"],
            "date": row["date"],
            "storage_mm3": row["value"],
            "capacity_status": capacity["status"],
            "capacity_mm3": "" if capacity["capacity_mm3"] is None else capacity["capacity_mm3"],
            "classification": classification,
            "eligible": "NO" if classification in {"CAPACITY_UNAVAILABLE", "CAPACITY_AMBIGUOUS"} else "YES",
            "capacity_evidence": match_sources,
            "source_file": row["source_file"],
            "flag": row["flag"],
        })
    write_csv(
        qa_root / "physical_validity.csv",
        ["observation_id", "dam_id", "date", "storage_mm3", "capacity_status", "capacity_mm3",
         "classification", "eligible", "capacity_evidence", "source_file", "flag"],
        physical_rows,
    )

    # E: storage/capacity versus independently printed fill percentage.
    fill_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in printed_fill:
        fill_by_key[(row["dam_id"], row["date"])].append(row)
    fill_rows: list[dict] = []
    fill_counts = Counter()
    for row in storage:
        key = (row["dam_id"], row["date"])
        matches = fill_by_key.get(key, [])
        fill = matches[0] if len(matches) == 1 else None
        capacity = capacity_cache[key]
        raw_printed = ""
        places = None
        printed_value = None
        if fill is not None:
            printed_value = Decimal(fill["value"])
            raw_printed = lineage_by_id.get(fill["lineage_id"], {}).get("raw_glyph_sequence", fill["value"])
            places = printed_decimal_places(raw_printed)
        classification, computed, lower, upper = classify_fill_rounding(
            Decimal(row["value"]), capacity, printed_value, places
        )
        if len(matches) > 1:
            classification = "MISMATCH"
        fill_counts[classification] += 1
        fill_rows.append({
            "storage_observation_id": row["observation_id"],
            "printed_fill_observation_id": "" if fill is None else fill["observation_id"],
            "dam_id": row["dam_id"],
            "date": row["date"],
            "storage_mm3": row["value"],
            "capacity_status": capacity["status"],
            "capacity_mm3": "" if capacity["capacity_mm3"] is None else capacity["capacity_mm3"],
            "printed_fill_pct": "" if printed_value is None else decimal_text(printed_value),
            "raw_printed_fill": raw_printed,
            "printed_decimal_places": "" if places is None else places,
            "computed_fill_pct": decimal_text(computed),
            "rounding_lower_pct": decimal_text(lower),
            "rounding_upper_pct": decimal_text(upper),
            "classification": classification,
            "eligible": "YES" if classification in {"MATCH_WITHIN_ROUNDING", "MISMATCH"} else "NO",
            "source_file": row["source_file"],
            "flag": row["flag"],
        })
    write_csv(
        qa_root / "fill_consistency.csv",
        ["storage_observation_id", "printed_fill_observation_id", "dam_id", "date", "storage_mm3",
         "capacity_status", "capacity_mm3", "printed_fill_pct", "raw_printed_fill",
         "printed_decimal_places", "computed_fill_pct", "rounding_lower_pct", "rounding_upper_pct",
         "classification", "eligible", "source_file", "flag"],
        fill_rows,
    )

    # F: accepted Page 1 independently printed grand total.
    evidence_by_date = {row["bulletin_date"]: row for row in national_evidence}
    storage_by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in storage:
        storage_by_date[row["date"]].append(row)
    national_rows: list[dict] = []
    national_counts = Counter()
    for bulletin in manifest:
        day = bulletin["bulletin_date"]
        evidence = evidence_by_date.get(day)
        components = storage_by_date.get(day, [])
        component_sum = sum((Decimal(row["value"]) for row in components), Decimal(0))
        classification = "MISSING_COMPONENT"
        residual = None
        tolerance = None
        printed = None
        accepted_sum = None
        disposition = None
        if evidence is not None and evidence["printed_total_mm3"]:
            printed = Decimal(evidence["printed_total_mm3"])
            accepted_sum = Decimal(evidence["accepted_component_sum_mm3"])
            expected = int(evidence["expected_contributors"])
            numeric = int(evidence["numeric_contributors"])
            if evidence["completeness"] == "COMPLETE" and expected == numeric:
                if len(components) != numeric:
                    classification = "SOURCE_ROSTER_SCOPE_DIFFERENCE"
                    residual = component_sum - printed
                else:
                    classification, residual, tolerance = classify_national_total(
                        component_sum,
                        printed,
                        len(components),
                        Decimal(evidence["printed_increment_mm3"]),
                        accepted_sum,
                    )
                    classification, disposition = apply_national_disposition(
                        day, classification, dispositions_by_date
                    )
        national_counts[classification] += 1
        national_rows.append({
            "bulletin_id": bulletin["bulletin_id"],
            "bulletin_date": day,
            "component_count": len(components),
            "component_observation_ids": "|".join(row["observation_id"] for row in components),
            "component_sum_mm3": decimal_text(component_sum),
            "accepted_component_sum_mm3": decimal_text(accepted_sum),
            "printed_total_mm3": decimal_text(printed),
            "signed_residual_mm3": decimal_text(residual),
            "rounding_tolerance_mm3": decimal_text(tolerance),
            "classification": classification,
            "eligible": "YES" if classification in {
                "MATCH_EXACT", "MATCH_WITHIN_ROUNDING", "SOURCE_PRINTED_DISAGREEMENT", "EXTRACTION_SUSPECT"
            } else "NO",
            "source_file": "" if evidence is None else evidence["source_file"],
            "source_sha256": "" if evidence is None else evidence["source_sha256"],
            "source_page": "" if evidence is None else evidence["source_page"],
            "completeness": "" if evidence is None else evidence["completeness"],
            "source_disposition": "" if evidence is None else evidence["source_disposition"],
            "notes": (
                disposition["evidence_summary"]
                + " See provenance/national_reconciliation_dispositions.csv."
            ) if disposition is not None else (
                "Accepted Page 1 printed grand total; no value generation or repair."
                if evidence is not None else "No accepted Page 1 grand-total evidence for this canonical date."
            ),
        })
    write_csv(
        qa_root / "national_reconciliation.csv",
        ["bulletin_id", "bulletin_date", "component_count", "component_observation_ids",
         "component_sum_mm3", "accepted_component_sum_mm3", "printed_total_mm3",
         "signed_residual_mm3", "rounding_tolerance_mm3", "classification", "eligible",
         "source_file", "source_sha256", "source_page", "completeness", "source_disposition", "notes"],
        national_rows,
    )

    # G: conservative Page 3 transfer eligibility. The known date-rule conflict
    # remains unresolved, and no compatible independent receiving-side measure
    # is established in the accepted E2 products.
    transfer_rows: list[dict] = []
    transfer_primary_counts = Counter()
    transfer_reason_counts = Counter()
    daily_candidates = [row for row in transfers if row["variable"] == "today"]
    for row in daily_candidates:
        classification, reasons = classify_transfer_candidate(
            row,
            date_semantics_resolved=False,
            counterpart_value=None,
        )
        transfer_primary_counts[classification] += 1
        transfer_reason_counts.update(reasons)
        transfer_rows.append({
            "transfer_observation_id": row["transfer_observation_id"],
            "date": row["date"],
            "entity_id": row["entity_id"],
            "row_role": row["row_role"],
            "from_dam_id": row["from_dam_id"],
            "to_dam_id": row["to_dam_id"],
            "value_mm3": row["value"],
            "counterpart_observation_id": "",
            "counterpart_value_mm3": "",
            "classification": classification,
            "ineligibility_reasons": "|".join(reasons),
            "eligible": "NO",
            "effective_date_rule": row["effective_date_rule"],
            "source_consistency_status": row["source_consistency_status"],
            "authority_release": row["authority_release"],
            "source_file": row["source_file"],
            "flag": row["flag"],
        })
    write_csv(
        qa_root / "transfer_balance.csv",
        ["transfer_observation_id", "date", "entity_id", "row_role", "from_dam_id", "to_dam_id",
         "value_mm3", "counterpart_observation_id", "counterpart_value_mm3", "classification",
         "ineligibility_reasons", "eligible", "effective_date_rule", "source_consistency_status",
         "authority_release", "source_file", "flag"],
        transfer_rows,
    )

    physical_fail = physical_counts["NEGATIVE_STORAGE"] + physical_counts["ABOVE_CAPACITY"]
    physical_excluded = physical_counts["CAPACITY_UNAVAILABLE"] + physical_counts["CAPACITY_AMBIGUOUS"]
    physical_eligible = len(storage) - physical_excluded
    fill_eligible = fill_counts["MATCH_WITHIN_ROUNDING"] + fill_counts["MISMATCH"]
    fill_excluded = len(storage) - fill_eligible
    national_pass = national_counts["MATCH_EXACT"] + national_counts["MATCH_WITHIN_ROUNDING"]
    national_fail = national_counts["SOURCE_PRINTED_DISAGREEMENT"] + national_counts["EXTRACTION_SUSPECT"]
    national_eligible = national_pass + national_fail
    transfer_pass = transfer_primary_counts["MATCH_EXACT"] + transfer_primary_counts["MATCH_WITHIN_ROUNDING"]
    transfer_fail = transfer_primary_counts["DISCREPANCY_DOCUMENTED"]
    transfer_eligible = transfer_pass + transfer_fail

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "engineering_run": "E3.1",
        "baseline_git_commit": "79e1ef8f937ab6a0b77e911032fba8c7fce27318",
        "pydantic_version": pydantic.__version__,
        "authority": {
            "storage": "PAGE1_0.2.3_CURRENT_EXTRACTION_DELIVERY",
            "page3": "PAGE3_SELECTED_RELEASE_PROBABLE",
        },
        "scientific_pipelines_rerun": False,
        "models_run": False,
        "kpis": {
            "C": {
                "name": "uniqueness",
                "population": len(storage),
                "eligible": len(storage),
                "pass": len(storage) - sum(len(ids) for ids in duplicates.values()),
                "fail": sum(len(ids) for ids in duplicates.values()),
                "excluded_unknown": 0,
                "status": "PASS" if not duplicates else "FAIL",
                "details": {
                    "unique_keys": len(storage) - sum(len(ids) - 1 for ids in duplicates.values()),
                    "duplicate_keys": len(duplicates),
                    "duplicate_records": sum(len(ids) for ids in duplicates.values()),
                },
            },
            "D": {
                "name": "physical validity",
                "population": len(storage),
                "eligible": physical_eligible,
                "pass": physical_counts["PASS"],
                "fail": physical_fail,
                "excluded_unknown": physical_excluded,
                "status": _status(physical_counts["PASS"], physical_fail, physical_eligible),
                "details": {"classifications": {
                    key: physical_counts[key] for key in (
                        "PASS", "NEGATIVE_STORAGE", "ABOVE_CAPACITY",
                        "CAPACITY_UNAVAILABLE", "CAPACITY_AMBIGUOUS",
                    )
                }},
            },
            "E": {
                "name": "fill consistency",
                "population": len(storage),
                "eligible": fill_eligible,
                "pass": fill_counts["MATCH_WITHIN_ROUNDING"],
                "fail": fill_counts["MISMATCH"],
                "excluded_unknown": fill_excluded,
                "status": _status(fill_counts["MATCH_WITHIN_ROUNDING"], fill_counts["MISMATCH"], fill_eligible),
                "details": {"classifications": {
                    key: fill_counts[key] for key in (
                        "MATCH_WITHIN_ROUNDING", "MISMATCH", "NO_PRINTED_FILL",
                        "CAPACITY_UNAVAILABLE", "CAPACITY_AMBIGUOUS",
                    )
                }},
            },
            "F": {
                "name": "national total reconciliation",
                "population": len(manifest),
                "eligible": national_eligible,
                "pass": national_pass,
                "fail": national_fail,
                "excluded_unknown": len(manifest) - national_eligible,
                "status": _status(national_pass, national_fail, national_eligible),
                "details": {
                    "classifications": {
                        key: national_counts[key] for key in (
                            "MATCH_EXACT", "MATCH_WITHIN_ROUNDING", "SOURCE_ROSTER_SCOPE_DIFFERENCE",
                            "SOURCE_PRINTED_DISAGREEMENT", "MISSING_COMPONENT", "EXTRACTION_SUSPECT", "UNRESOLVED",
                        )
                    },
                    "roster_scope_dates": [
                        row["bulletin_date"] for row in national_rows
                        if row["classification"] == "SOURCE_ROSTER_SCOPE_DIFFERENCE"
                    ],
                    "remaining_disagreement_dates": [
                        row["bulletin_date"] for row in national_rows
                        if row["classification"] == "SOURCE_PRINTED_DISAGREEMENT"
                    ],
                },
            },
            "G": {
                "name": "transfer balance",
                "population": len(daily_candidates),
                "eligible": transfer_eligible,
                "pass": transfer_pass,
                "fail": transfer_fail,
                "excluded_unknown": len(daily_candidates) - transfer_eligible,
                "status": _status(
                    transfer_pass, transfer_fail, transfer_eligible,
                    no_eligible="NOT_NUMERICALLY_ELIGIBLE_WITH_EXPLICIT_EXCLUSIONS",
                ),
                "details": {
                    "daily_physical_facts": sum(row["row_role"] == "PHYSICAL_TRANSFER_EDGE" for row in daily_candidates),
                    "accounting_rows": sum(row["row_role"] == "ACCOUNTING_OBSERVATION" for row in daily_candidates),
                    "primary_classifications": {
                        key: transfer_primary_counts[key] for key in (
                            "MATCH_EXACT", "MATCH_WITHIN_ROUNDING", "DISCREPANCY_DOCUMENTED",
                            "NO_DIRECT_COUNTERPART", "UNRESOLVED_DAM_CROSSWALK",
                            "ACCOUNTING_NOT_HYDRAULIC_EDGE", "DATE_SEMANTICS_UNRESOLVED",
                            "SOURCE_CONSISTENCY_NOT_CHECKED",
                        )
                    },
                    "reason_counts": {
                        key: transfer_reason_counts[key] for key in (
                            "NO_DIRECT_COUNTERPART", "UNRESOLVED_DAM_CROSSWALK",
                            "ACCOUNTING_NOT_HYDRAULIC_EDGE", "DATE_SEMANTICS_UNRESOLVED",
                            "SOURCE_CONSISTENCY_NOT_CHECKED",
                        )
                    },
                },
            },
        },
    }
    (qa_root / "qa_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (qa_root / "report.md").write_text(_render_report(summary), encoding="utf-8")
    return summary

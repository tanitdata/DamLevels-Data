"""Regenerate engineering QA A1/A2/A3/A3B and C-G, then validate contracts.

This command reads accepted repository tables. It does not run extraction or
any upstream scientific pipeline. Historical E6A/E6A.1 audit rows and the
accepted B/H result objects are preserved rather than regenerated.
"""
import json
from pathlib import Path
from build_e6a2 import generate_e6a2
from validate.contracts import v010_zip_configured, validate_repository
from validate.quality import generate_qa


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    summary_path = root / "qa/qa_summary.json"
    accepted = json.loads(summary_path.read_text(encoding="utf-8"))
    preserved = {key: accepted["kpis"][key] for key in ("B", "H")}
    historical_a = accepted.get("historical_e6a1_kpi_a")
    generate_qa(root)
    regenerated = json.loads(summary_path.read_text(encoding="utf-8"))
    regenerated["kpis"].update(preserved)
    regenerated["historical_e6a1_kpi_a"] = historical_a
    # Keep accepted run-scope flags that generate_qa does not produce, in their accepted position.
    carried = ("production_extractor_rerun", "satellite_validation_run", "protected_baseline")
    merged = {}
    for key in accepted:
        if key in regenerated:
            merged[key] = regenerated[key]
        elif key in carried:
            merged[key] = accepted[key]
    for key, value in regenerated.items():
        merged.setdefault(key, value)
    summary_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    regenerated = merged
    summary = generate_e6a2(root, regenerated)
    errors = validate_repository(root)
    if errors:
        raise SystemExit("\n".join(errors))
    if not v010_zip_configured():
        print("Note: frozen V010 review ZIP not configured (v010_review_zip); its hash check was skipped.")
    decisions = ", ".join(
        f"{key}={value['target_decision']}" for key, value in summary["numeric_families"].items()
    )
    print(f"Current DamLevels-Data E6A.2 contracts validated; {decisions}.")

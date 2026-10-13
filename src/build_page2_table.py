"""Build the full Page 2 table: every printed Page 2 column, one row per dam and bulletin.

Packaging only: no extraction is run and no value is changed, filled or shifted.
The input is the accepted Page 2 extraction (engine page2-authoritative-1.0.0),
the same file sources/manifest.csv was built from; its SHA-256 is checked.

Columns use the project's canonical names (as in qa/kpi/inputs/page2.parquet),
not the extractor's p2_* names: p2_cote_plan_eau_m and p2_volume_actuel_mm3, for
example, are the level and volume at the end of the previous hydraulic year,
not current values. SOURCE_COLUMNS gives the DLO 0.3 source column of each.

    python src/build_page2_table.py   (needs page2_observations in config/paths.local.toml)
"""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from build_page1_table import clean_float_text, sha256
from paths import REPO, external

PAGE2_OBSERVATIONS_SHA256 = "ec1c1002ecf5d3c6a9e3ad29a52273870fb4d5e774669c6e6ab0284a9b6d22b5"
AUTHORITY_RELEASE = "PAGE2_1.0.0_CURRENT_EXTRACTION_DELIVERY"
CSV_PATH = REPO / "data/bulletin_page2.csv"
PARQUET_PATH = REPO / "data/parquet/bulletin_page2.parquet"

ID_FIELDS = [
    "source_row_key", "dam_id", "bulletin_date", "region", "source_file", "source_sha256", "page",
    "layout", "engine_version", "authority_release", "row_detection",
]
# Published name -> DLO 0.3 source column (table P2_observations), in bulletin order.
SOURCE_COLUMNS = {
    "catchment_area_km2": "p2_bassin_versant_km2",
    "mean_annual_inflow_mm3_per_year": "p2_apport_annuel_moyen_mm3",
    "minimum_annual_inflow_since_impoundment_mm3": "p2_min_depuis_mise_en_eau_mm3",
    "normal_pool_elevation_m": "p2_cote_retenue_normale_m",
    "initial_total_capacity_mm3": "p2_cap_totale_initiale_mm3",
    "useful_capacity_at_last_bathymetric_survey_mm3": "p2_cap_actuelle_mm3",
    "calculated_regulated_volume_mm3": "p2_cap_reguliere_mm3",
    "maximum_evacuation_discharge_m3s": "p2_debit_max_evacuateur_m3s",
    "measured_sediment_volume_mm3": "p2_envasement_volume_mm3",
    "mean_annual_sedimentation_mm3_per_year": "p2_envasement_annuel_mm3",
    "sedimentation_pct_of_initial_capacity": "p2_envasement_pct",
    "catchment_equivalent_erosion_mm_per_year": "p2_erosion_mm_an",
    "estimated_useful_capacity_after_post_survey_sedimentation_mm3": "p2_cap_utile_calculee_mm3",
    "previous_hydraulic_year_end_water_level_m": "p2_cote_plan_eau_m",
    "previous_hydraulic_year_end_storage_mm3": "p2_volume_actuel_mm3",
    "previous_full_hydraulic_year_inflow_mm3": "p2_apport_annee_prec_mm3",
    "previous_full_hydraulic_year_outflow_mm3": "p2_soutirage_annee_prec_mm3",
    "water_level_current_m": "water_level_current_m",
    "storage_current_total_corresponding_p2_mm3": "storage_current_total_corresponding_p2_mm3",
    "storage_current_exploitable_mm3": "storage_current_exploitable_mm3",
    "outflow_reporting_interval_p2_mm3": "outflow_reporting_interval_p2_mm3",
    "inflow_reporting_interval_p2_mm3": "inflow_reporting_interval_p2_mm3",
    "inflow_month_to_date_p2_mm3": "inflow_month_to_date_p2_mm3",
    "evaporation_reporting_interval_mm3": "evaporation_reporting_interval_mm3",
    "rainfall_reporting_interval_mm": "rainfall_reporting_interval_mm",
    "p2_rs_unresolved_prohibited": "p2_rs_unresolved_prohibited",
}
VALUE_FIELDS = list(SOURCE_COLUMNS)
FIELDS = ID_FIELDS + VALUE_FIELDS


def build_rows(p2_obs: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with gzip.open(p2_obs, "rt", encoding="utf-8-sig", newline="") as f:
        for source in csv.DictReader(f):
            row = {
                "source_row_key": f"PAGE_2|{source['bulletin_date']}|{source['dam_id']}",
                "dam_id": source["dam_id"],
                "bulletin_date": source["bulletin_date"],
                "region": source["region"],
                "source_file": source["source_file"],
                "source_sha256": source["source_sha256"],
                # Logical bulletin page; the split PDF holds this page as its page 1.
                "page": "2",
                "layout": source["schema_class"],
                "engine_version": source["extractor_version"],
                "authority_release": AUTHORITY_RELEASE,
                "row_detection": source["row_detection_method"],
            }
            for field, source_field in SOURCE_COLUMNS.items():
                value = source[source_field].strip()
                row[field] = clean_float_text(value) if value else ""
            rows.append(row)
    keys = [(row["dam_id"], row["bulletin_date"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate dam_id/bulletin_date rows in the Page 2 extraction")
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_parquet(path: Path, rows: list[dict[str, str]]) -> None:
    columns: dict[str, list] = {field: [row[field] for row in rows] for field in ID_FIELDS}
    for field in VALUE_FIELDS:
        columns[field] = [None if row[field] == "" else float(row[field]) for row in rows]
    pq.write_table(pa.table(columns), path, compression="zstd")


def main() -> None:
    p2_obs = external("page2_observations")
    digest = sha256(p2_obs)
    if digest != PAGE2_OBSERVATIONS_SHA256:
        raise SystemExit(f"Page 2 observations SHA-256 {digest} differs from the accepted input")
    rows = build_rows(p2_obs)
    write_csv(CSV_PATH, rows)
    write_parquet(PARQUET_PATH, rows)
    print(json.dumps({
        "rows": len(rows),
        "dams": len({row["dam_id"] for row in rows}),
        "bulletin_dates": len({row["bulletin_date"] for row in rows}),
        "non_blank": {field: sum(1 for row in rows if row[field]) for field in VALUE_FIELDS},
        "csv_sha256": sha256(CSV_PATH),
        "parquet_sha256": sha256(PARQUET_PATH),
    }, indent=2))


if __name__ == "__main__":
    main()

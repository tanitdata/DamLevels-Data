from __future__ import annotations

from datetime import date

from .schema import COLUMN23_CUTOFF

PHYSICAL_COLUMN_NAMES = {
    0: "dam_label_source",
    1: "p2_bassin_versant_km2",
    2: "p2_apport_annuel_moyen_mm3",
    3: "p2_min_depuis_mise_en_eau_mm3",
    4: "p2_cote_retenue_normale_m",
    5: "p2_cap_totale_initiale_mm3",
    6: "p2_cap_actuelle_mm3",
    7: "p2_cap_reguliere_mm3",
    8: "p2_debit_max_evacuateur_m3s",
    9: "p2_envasement_volume_mm3",
    10: "p2_envasement_annuel_mm3",
    11: "p2_envasement_pct",
    12: "p2_erosion_mm_an",
    13: "p2_cap_utile_calculee_mm3",
    14: "p2_cote_plan_eau_m",
    15: "p2_volume_actuel_mm3",
    16: "p2_apport_annee_prec_mm3",
    17: "p2_soutirage_annee_prec_mm3",
    18: "water_level_current_m",
    19: "storage_current_total_corresponding_p2_mm3",
    20: "storage_current_exploitable_mm3",
    21: "outflow_reporting_interval_p2_mm3",
    22: "inflow_reporting_interval_p2_mm3",
    24: "rainfall_reporting_interval_mm",
    25: "p2_rs_unresolved_prohibited",
}

OBSERVATION_VALUE_FIELDS = [PHYSICAL_COLUMN_NAMES[column] for column in range(1, 23)] + [
    "inflow_month_to_date_p2_mm3",
    "evaporation_reporting_interval_mm3",
    PHYSICAL_COLUMN_NAMES[24],
    PHYSICAL_COLUMN_NAMES[25],
]


def semantic_for_physical_column(column: int, bulletin_date: date) -> str:
    if column == 23:
        if bulletin_date < COLUMN23_CUTOFF:
            return "inflow_month_to_date_p2_mm3"
        return "evaporation_reporting_interval_mm3"
    try:
        return PHYSICAL_COLUMN_NAMES[column]
    except KeyError as exc:
        raise ValueError(f"Unsupported Page-2 physical column {column}") from exc


def validate_registry() -> None:
    expected = set(range(26))
    actual = set(PHYSICAL_COLUMN_NAMES) | {23}
    if actual != expected:
        raise AssertionError(f"Physical registry mismatch: {sorted(expected ^ actual)}")

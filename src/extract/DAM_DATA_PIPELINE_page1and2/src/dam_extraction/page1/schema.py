from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

LAYOUT_15 = [
    "dam_name", "apport_today", "apport_cumul_this_month", "apport_average_month",
    "apport_cumul_since_sep", "apport_cumul_prev_year", "apport_average_period",
    "release_action_code", "release_yesterday", "release_today",
    "release_cumul_this_month", "release_cumul_year", "release_cumul_last_year",
    "stock_today_mm3", "stock_last_year_mm3",
]
LAYOUT_16 = LAYOUT_15[:-2] + ["stock_fill_pct", "stock_today_mm3", "stock_last_year_mm3"]

SEMANTICS = {
    "apport_today": ("Mm3", "current reporting interval inflow"),
    "apport_cumul_this_month": ("Mm3", "month-to-date inflow"),
    "apport_average_month": ("Mm3", "printed monthly-average reference"),
    "apport_cumul_since_sep": ("Mm3", "hydraulic-year inflow since September"),
    "apport_cumul_prev_year": ("Mm3", "previous-year/reference inflow"),
    "apport_average_period": ("Mm3", "printed historical-period inflow reference"),
    "release_action_code": ("source_code", "current reporting interval action"),
    "release_yesterday": ("Mm3", "current reporting-interval release"),
    "release_today": ("Mm3", "previous-year/reference release"),
    "release_cumul_this_month": ("Mm3", "month-to-date release"),
    "release_cumul_year": ("Mm3", "hydraulic-year cumulative release"),
    "release_cumul_last_year": ("Mm3", "previous-year cumulative release reference"),
    "stock_fill_pct": ("percent", "reporting date"),
    "stock_today_mm3": ("Mm3", "reporting date storage"),
    "stock_last_year_mm3": ("Mm3", "previous-year/reference storage"),
}


@dataclass(frozen=True)
class SchemaDecision:
    layout_class: str
    fields: list[str]
    authority_method: str
    incident_status: str
    header_fill_evidence: bool
    date_heuristic: str


def decide_schema(data_column_count: int, header_text: str, bulletin_date: str | None) -> SchemaDecision:
    header = header_text.casefold()
    header_fill = "%" in header or "remplissage" in header or "امتالء" in header
    heuristic = "UNKNOWN"
    if bulletin_date:
        heuristic = "EXPECT_FILL" if date.fromisoformat(bulletin_date) >= date(2020, 1, 1) else "EXPECT_NO_FILL"
    if data_column_count == 16:
        layout, fields = "P1_LAYOUT_16_WITH_FILL", LAYOUT_16
        incident = "NONE" if header_fill else "SCHEMA_HEADER_GEOMETRY_DISAGREEMENT"
    elif data_column_count == 15:
        layout, fields = "P1_LAYOUT_15_NO_FILL", LAYOUT_15
        incident = "SCHEMA_DATE_HEURISTIC_DISAGREEMENT" if heuristic == "EXPECT_FILL" else "NONE"
        if header_fill:
            incident = "SCHEMA_HEADER_GEOMETRY_DISAGREEMENT"
    else:
        layout, fields = "P1_LAYOUT_UNRESOLVED", []
        incident = "SCHEMA_GEOMETRY_UNRESOLVED"
    return SchemaDecision(layout, list(fields), "PRINTED_HEADER_THEN_PHYSICAL_GEOMETRY", incident, header_fill, heuristic)


def semantic(field: str) -> tuple[str, str]:
    return SEMANTICS.get(field, ("", "source-defined"))


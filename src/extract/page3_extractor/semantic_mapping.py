"""Canonical field identities, registries and semantic guardrails.

Names here come from the accepted contracts, never from position alone:

* ``01_knowledge_base/08_semantics/Page 3 to Milestone 1 Semantic Mapping.md``
* ``04_extractors/contracts/page3_to_milestone1_semantic_mapping.csv``
* ``03_exploration/routing/p3_fragment_semantic_map.csv`` (FSM-01..FSM-11)

Every Page 3 field keeps **both** its raw identity (fragment rank, row, column,
printed label) and its canonical id. The raw identity is never discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SEMANTIC_MAP_VERSION = "1.0.0"

MM3 = "Mm3"
PCT = "%"

# ---------------------------------------------------------------------- #
# Families
# ---------------------------------------------------------------------- #
T1 = "T1"
T2 = "T2"
T3 = "T3"
T4 = "T4"
T5 = "T5"
T6 = "T6"
FAMILIES = (T1, T2, T3, T4, T5, T6)

#: FSM rank -> family, for the nine-fragment portrait signature.
FRAGMENT_FAMILY: dict[int, str] = {
    1: T1, 2: T2, 3: T3, 4: T3, 5: T3, 6: T4, 7: T4, 8: T5, 9: T6,
}

FRAGMENT_ROLE: dict[int, str] = {
    1: "general_stock",
    2: "dam_status_grid",
    3: "inflow_regional",
    4: "inflow_total",
    5: "inflow_comparator",
    6: "withdrawal_regional",
    7: "withdrawal_total",
    8: "transfers",
    9: "ichkeul_feed",
}

FSM_ID: dict[int, str] = {i: f"FSM-{i:02d}" for i in range(1, 10)}


# ---------------------------------------------------------------------- #
# Canonical field definitions
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class FieldDef:
    field_id: str
    canonical_name: str
    unit: str
    temporal_reference: str
    value_type: str = "measure"
    label_ar: str = ""
    label_en: str = ""
    notes: str = ""


FIELDS: dict[str, FieldDef] = {
    # --- T1 -------------------------------------------------------------
    "p3_t1_stock_current_season_today_mm3": FieldDef(
        "p3_t1_stock_current_season_today_mm3",
        "general_dam_stock_today_mm3", MM3, "observation_today",
        label_ar="لهذا اليوم من الموسم الحالي", label_en="this day of the current season"),
    "p3_t1_stock_3yr_same_day_avg_mm3": FieldDef(
        "p3_t1_stock_3yr_same_day_avg_mm3",
        "general_dam_stock_3yr_same_day_average_mm3", MM3, "reference_3yr_same_day",
        label_ar="المعدل لنفس اليوم للثلاث السنوات الفارطة",
        label_en="average for the same day over the last three years"),
    "p3_t1_stock_difference_mm3": FieldDef(
        "p3_t1_stock_difference_mm3",
        "general_dam_stock_difference_vs_3yr_avg_mm3", MM3, "derived_difference",
        value_type="printed_difference", label_ar="الفارق", label_en="difference"),

    # --- T2 -------------------------------------------------------------
    "p3_t2_dam_stock_mm3": FieldDef(
        "p3_t2_dam_stock_mm3", "dam_stock_today_mm3", MM3, "observation_today",
        label_ar="المخزون", label_en="stock"),
    "p3_t2_dam_fill_pct": FieldDef(
        "p3_t2_dam_fill_pct", "dam_fill_percentage", PCT, "observation_today",
        label_ar="الامتلاء (%)", label_en="fill (%)"),
    "p3_t2_headroom_to_normal_level_mm3": FieldDef(
        "p3_t2_headroom_to_normal_level_mm3",
        "remaining_capacity_to_normal_level_mm3", MM3, "observation_today",
        label_ar="الرصيد المتبقي من طاقة الإستيعاب الى حدود المستوى العادي للسد",
        label_en="remaining absorption capacity up to the dam's normal level"),
    "p3_t2_headroom_to_max_level_mm3": FieldDef(
        "p3_t2_headroom_to_max_level_mm3",
        "remaining_capacity_to_maximum_water_level_mm3", MM3, "observation_today",
        label_ar="الرصيد المتبقي من طاقة الإستيعاب الى حدود المستوى الاقصى للمياه",
        label_en="remaining absorption capacity up to the maximum water level"),

    # --- T3 -------------------------------------------------------------
    "p3_t3_inflow_region_today_mm3": FieldDef(
        "p3_t3_inflow_region_today_mm3", "regional_inflow_today_mm3", MM3,
        "interval_today", label_ar="الإيرادات الجملية للسدود - لهذا اليوم",
        label_en="total dam inflow for this day, by region"),
    "p3_t3_inflow_total_today_mm3": FieldDef(
        "p3_t3_inflow_total_today_mm3", "national_inflow_today_mm3", MM3,
        "interval_today", label_ar="لهذا اليوم", label_en="for this day"),
    "p3_t3_inflow_current_season_cum_mm3": FieldDef(
        "p3_t3_inflow_current_season_cum_mm3",
        "national_inflow_current_season_cumulative_mm3", MM3, "cumulative_current_season",
        label_ar="للموسم الحالي", label_en="for the current season"),
    "p3_t3_inflow_period_average_mm3": FieldDef(
        "p3_t3_inflow_period_average_mm3", "national_inflow_period_average_mm3",
        MM3, "reference_period_average", label_ar="معدل الفترة", label_en="period average"),
    "p3_t3_inflow_difference_vs_period_mm3": FieldDef(
        "p3_t3_inflow_difference_vs_period_mm3",
        "national_inflow_difference_vs_period_average_mm3", MM3, "derived_difference",
        value_type="printed_difference", label_ar="الفارق", label_en="difference"),
    "p3_t3_inflow_3yr_same_day_avg_mm3": FieldDef(
        "p3_t3_inflow_3yr_same_day_avg_mm3",
        "national_inflow_3yr_same_day_average_mm3", MM3, "reference_3yr_same_day",
        label_ar="المعدل لنفس اليوم للثلاث السنوات الفارطة",
        label_en="average for the same day over the last three years",
        notes="present only in the five-value comparator schema"),
    "p3_t3_inflow_difference_vs_3yr_mm3": FieldDef(
        "p3_t3_inflow_difference_vs_3yr_mm3",
        "national_inflow_difference_vs_3yr_average_mm3", MM3, "derived_difference",
        value_type="printed_difference", label_ar="الفارق", label_en="difference",
        notes="present only in the five-value comparator schema"),

    # --- T4 -------------------------------------------------------------
    "p3_t4_withdrawal_region_today_mm3": FieldDef(
        "p3_t4_withdrawal_region_today_mm3", "regional_withdrawal_today_mm3", MM3,
        "interval_today", label_ar="مجموع الاستعمالات والسحب - لهذا اليوم",
        label_en="total uses and withdrawals for this day, by region"),
    "p3_t4_withdrawal_total_today_mm3": FieldDef(
        "p3_t4_withdrawal_total_today_mm3", "national_withdrawal_today_mm3", MM3,
        "interval_today", label_ar="لهذا اليوم", label_en="for this day"),

    # --- T5 -------------------------------------------------------------
    "p3_t5_transfer_day_mm3": FieldDef(
        "p3_t5_transfer_day_mm3", "pumped_transfer_today_mm3", MM3, "interval_today",
        label_ar="لليوم", label_en="for the day"),
    "p3_t5_transfer_prev_season_cum_mm3": FieldDef(
        "p3_t5_transfer_prev_season_cum_mm3",
        "pumped_transfer_previous_season_cumulative_mm3", MM3,
        "cumulative_previous_season", label_ar="مجموع الموسم السابق إلى غاية هذا اليوم",
        label_en="previous season total to this day"),
    "p3_t5_transfer_curr_season_cum_mm3": FieldDef(
        "p3_t5_transfer_curr_season_cum_mm3",
        "pumped_transfer_current_season_cumulative_mm3", MM3,
        "cumulative_current_season", label_ar="مجموع الموسم الحالي إلى غاية هذا اليوم",
        label_en="current season total to this day"),

    # --- T6 -------------------------------------------------------------
    "p3_t6_ichkeul_day_mm3": FieldDef(
        "p3_t6_ichkeul_day_mm3", "ichkeul_feed_today_mm3", MM3, "interval_today",
        label_ar="لليوم", label_en="for the day"),
    "p3_t6_ichkeul_prev_season_cum_mm3": FieldDef(
        "p3_t6_ichkeul_prev_season_cum_mm3",
        "ichkeul_feed_previous_season_cumulative_mm3", MM3,
        "cumulative_previous_season", label_ar="مجموع الموسم السابق إلى غاية هذا اليوم",
        label_en="previous season total to this day"),
    "p3_t6_ichkeul_curr_season_cum_mm3": FieldDef(
        "p3_t6_ichkeul_curr_season_cum_mm3",
        "ichkeul_feed_current_season_cumulative_mm3", MM3,
        "cumulative_current_season", label_ar="مجموع الموسم الحالي إلى غاية هذا اليوم",
        label_en="current season total to this day"),
}


# ---------------------------------------------------------------------- #
# Column orders, right to left
# ---------------------------------------------------------------------- #
#: T1 data row, reading right to left after the label column.
T1_VALUE_ORDER_RTL = (
    "p3_t1_stock_current_season_today_mm3",
    "p3_t1_stock_3yr_same_day_avg_mm3",
    "p3_t1_stock_difference_mm3",
)

#: T2 grid, reading right to left after the dam-name column.
T2_VALUE_ORDER_RTL = (
    "p3_t2_dam_stock_mm3",
    "p3_t2_dam_fill_pct",
    "p3_t2_headroom_to_normal_level_mm3",
    "p3_t2_headroom_to_max_level_mm3",
)

#: Comparator schemas. Column *indices* move between eras (measured: 2016 uses
#: c2/c3/c4, 2024 uses c1/c3/c4), so the populated value cells are ordered
#: right to left instead.
T3_COMPARATOR_3VALUE = "T3_COMPARATOR_3VALUE"
T3_COMPARATOR_5VALUE = "T3_COMPARATOR_5VALUE"

T3_COMPARATOR_ORDER_RTL: dict[str, tuple[str, ...]] = {
    T3_COMPARATOR_3VALUE: (
        "p3_t3_inflow_current_season_cum_mm3",
        "p3_t3_inflow_period_average_mm3",
        "p3_t3_inflow_difference_vs_period_mm3",
    ),
    T3_COMPARATOR_5VALUE: (
        "p3_t3_inflow_current_season_cum_mm3",
        "p3_t3_inflow_3yr_same_day_avg_mm3",
        "p3_t3_inflow_difference_vs_3yr_mm3",
        "p3_t3_inflow_period_average_mm3",
        "p3_t3_inflow_difference_vs_period_mm3",
    ),
}

#: T5 and T6 share one value order, reading right to left after the label.
TRANSFER_VALUE_ORDER_RTL = (
    "p3_t5_transfer_day_mm3",
    "p3_t5_transfer_prev_season_cum_mm3",
    "p3_t5_transfer_curr_season_cum_mm3",
)
ICHKEUL_VALUE_ORDER_RTL = (
    "p3_t6_ichkeul_day_mm3",
    "p3_t6_ichkeul_prev_season_cum_mm3",
    "p3_t6_ichkeul_curr_season_cum_mm3",
)


# ---------------------------------------------------------------------- #
# Region registry (T3 / T4)
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class RegionDef:
    region_id: str
    name_ar: str
    name_en: str
    row_rank: int


REGIONS: tuple[RegionDef, ...] = (
    RegionDef("REG-NORTH", "سدود الشمال", "northern dams", 1),
    RegionDef("REG-CENTRE", "سدود الوسط", "central dams", 2),
    RegionDef("REG-CAP-BON", "سدود الوطن القبلي", "Cap Bon dams", 3),
)
REGION_BY_RANK = {r.row_rank: r for r in REGIONS}

#: Region *membership* (which dam belongs to which region) is deliberately
#: absent. Section 10 of the semantic mapping guide forbids enabling a regional
#: aggregate comparison until a membership registry exists with evidence.
REGION_MEMBERSHIP_STATUS = "UNRESOLVED_NO_MEMBERSHIP_REGISTRY"


# ---------------------------------------------------------------------- #
# T5 connectivity
# ---------------------------------------------------------------------- #
EDGE = "physical_edge"
ACCOUNTING = "accounting_observation"

@dataclass(frozen=True)
class TransferRowDef:
    row_rank: int
    record_id: str
    label_ar: str
    label_en: str
    kind: str
    source_node_id: str = ""
    destination_node_id: str = ""
    via_node_id: str = ""


#: KB-CONN-T5 / CLM-022. Row 4 restates rows 2+3 from the receiving node's point
#: of view. It is an accounting observation and is **never** a graph edge.
TRANSFER_ROWS: tuple[TransferRowDef, ...] = (
    TransferRowDef(1, "EDGE-T5-01", "من سد بربرة الى سد بوهرتمة (وادي غريب)",
                   "from Barbara dam to Bouhertma dam (Oued Ghrib)", EDGE,
                   "NODE-DAM-BARBARA", "NODE-DAM-BOUHERTMA", "NODE-CONV-OUED-GHRIB"),
    TransferRowDef(2, "EDGE-T5-02", "من سد سيدي البراق الى سد سجنان",
                   "from Sidi El Barrak dam to Sejnane dam", EDGE,
                   "NODE-DAM-SIDI-EL-BARRAK", "NODE-DAM-SEJNANE"),
    TransferRowDef(3, "EDGE-T5-03", "من سد الزياتين إلى سد سجنان",
                   "from Zayatin dam to Sejnane dam", EDGE,
                   "NODE-DAM-ZAYATIN", "NODE-DAM-SEJNANE"),
    TransferRowDef(4, "EDGE-T5-04-ACCOUNTING", "إيرادات سد سجنان باعتماد التحويل",
                   "Sejnane dam inflow accounted through transfer", ACCOUNTING,
                   "", "NODE-DAM-SEJNANE"),
)
TRANSFER_ROW_BY_RANK = {r.row_rank: r for r in TRANSFER_ROWS}

#: In the two-row era only edges 1 and 2 are printed. A row that is not printed
#: is ``row_absent`` — never a zero.
TWO_ROW_ERA_RANKS = (1, 2)

ICHKEUL_DESTINATION_ID = "DEST-EXT-LAKE-ICHKEUL"
ICHKEUL_RECORD_ID = "T6-ICHKEUL-FEED"

#: Lake Ichkeul is an external environmental destination, not a dam node.
ICHKEUL_NODE_CLASS = "external_environmental"


# ---------------------------------------------------------------------- #
# Reference comparison gate
# ---------------------------------------------------------------------- #
#: MAP-045..MAP-054 are all ``UNRESOLVED`` / ``CANDIDATE_REQUIRES_REVIEW`` /
#: ``NOT_COMPARABLE`` in the accepted mapping contract. None of them authorizes
#: an enabled comparison rule, so this extractor ships with zero enabled rules
#: and refuses to invent one.
COMPARISON_ENABLING_STATUSES = (
    "CONFIRMED_FROM_VAULT",
    "CONFIRMED_FROM_SOURCE_HEADER",
    "SCHEMA_DEPENDENT_CONFIRMED",
)

NOT_COMPARABLE_FAMILIES = (T5, T6)
NOT_COMPARABLE_REASON = (
    "the reference dataset has no transfer-volume or environmental-delivery "
    "physical column; this is a structural absence, not a data gap"
)


def field_def(field_id: str) -> Optional[FieldDef]:
    return FIELDS.get(field_id)


def canonical_name(field_id: str) -> str:
    fd = FIELDS.get(field_id)
    return fd.canonical_name if fd else ""


def unit_for(field_id: str) -> str:
    fd = FIELDS.get(field_id)
    return fd.unit if fd else ""


def temporal_for(field_id: str) -> str:
    fd = FIELDS.get(field_id)
    return fd.temporal_reference if fd else ""

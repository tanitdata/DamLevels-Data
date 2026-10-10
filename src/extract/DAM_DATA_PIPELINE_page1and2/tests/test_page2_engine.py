from __future__ import annotations

import ast
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dam_extraction.page2.checksum_validation import validate_without_value_generation
from dam_extraction.page2.header_geometry import semantic_for_physical_column, validate_registry
from dam_extraction.page2.roster import REGISTRY_PATH, expected_single_between, identify_text_label
from dam_extraction.page2.value_parser import parse_source_value


class Page2EngineTests(unittest.TestCase):
    def test_registry_covers_all_physical_columns(self) -> None:
        validate_registry()

    def test_bezirk_unique_roster_slot(self) -> None:
        self.assertEqual(expected_single_between("brek", "chiba"), "bezirk")

    def test_sidi_saad_unique_roster_slot(self) -> None:
        self.assertEqual(expected_single_between("nebhana", "elhouareb"), "sidisaad")

    def test_ambiguous_roster_gap_not_guessed(self) -> None:
        self.assertIsNone(expected_single_between("ghezala", "sejnane"))

    def test_doubled_label_normalizes(self) -> None:
        self.assertEqual(identify_text_label("LLEEBBNNAA ((8866))"), "lebna")

    def test_source_supported_karka_alias(self) -> None:
        self.assertEqual(identify_text_label("Karka (16)"), "harka")

    def test_raw_harka_label(self) -> None:
        self.assertEqual(identify_text_label("Harka (16)"), "harka")

    def test_karka_is_governed_data_not_local_special_case(self) -> None:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        harka = next(row for row in payload["entries"] if row["dam_id"] == "harka")
        self.assertEqual(harka["aliases"], ["HARKA", "KARKA"])

    def test_numeric_parser(self) -> None:
        parsed = parse_source_value("0,022", physical_column=23)
        self.assertEqual(parsed.status, "NUMERIC_PARSED")
        self.assertEqual(parsed.numeric_value, 0.022)

    def test_raw_expression_not_guessed(self) -> None:
        parsed = parse_source_value("75+11", physical_column=1)
        self.assertEqual(parsed.status, "NONNUMERIC_SOURCE_EXPRESSION")
        self.assertIsNone(parsed.numeric_value)

    def test_source_blank_remains_null(self) -> None:
        parsed = parse_source_value("", physical_column=22)
        self.assertEqual(parsed.status, "SOURCE_BLANK")
        self.assertIsNone(parsed.numeric_value)

    def test_rs_remains_unresolved(self) -> None:
        parsed = parse_source_value("1,70", physical_column=25)
        self.assertEqual(parsed.status, "NUMERIC_PARSED_RS_UNRESOLVED_PROHIBITED")
        self.assertEqual(parsed.numeric_value, 1.70)

    def test_column23_cutoff(self) -> None:
        self.assertEqual(semantic_for_physical_column(23, date(2024, 4, 26)), "inflow_month_to_date_p2_mm3")
        self.assertEqual(semantic_for_physical_column(23, date(2024, 4, 27)), "evaporation_reporting_interval_mm3")

    def test_storage_fields_distinct(self) -> None:
        self.assertNotEqual(
            semantic_for_physical_column(19, date(2024, 4, 27)),
            semantic_for_physical_column(20, date(2024, 4, 27)),
        )

    def test_inflow_outflow_fields_distinct(self) -> None:
        self.assertNotEqual(
            semantic_for_physical_column(21, date(2024, 4, 27)),
            semantic_for_physical_column(22, date(2024, 4, 27)),
        )

    def test_checksum_validator_does_not_generate_value(self) -> None:
        result = validate_without_value_generation(3.0, 5.0)
        self.assertEqual(result["signed_delta"], -2.0)
        self.assertEqual(set(result), {"computed_sum", "published_total", "signed_delta"})

    def test_no_runtime_measurement_corrections_or_cross_page_average(self) -> None:
        source_root = ROOT / "src" / "dam_extraction" / "page2"
        prohibited_names = {"average_page1_page2", "checksum_fill_value", "measurement_correction_dictionary"}
        runtime_text = ""
        for path in source_root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            runtime_text += source.casefold()
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id.casefold(), prohibited_names)
        self.assertNotIn("11-8-2016", runtime_text)
        self.assertNotIn("26-12-2022", runtime_text)


if __name__ == "__main__":
    unittest.main()

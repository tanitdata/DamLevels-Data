from __future__ import annotations

import csv
import gzip
import os
import unittest
from pathlib import Path


def validate_constant_csv_widths(root: Path) -> list[str]:
    failures: list[str] = []
    for path in sorted([*root.rglob("*.csv"), *root.rglob("*.csv.gz")]):
        opener = gzip.open if path.name.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                header = next(reader, [])
                for row_number, row in enumerate(reader, start=2):
                    if len(row) != len(header):
                        failures.append(f"{path}:{row_number}: expected {len(header)} fields, found {len(row)}")
                        break
        except Exception as exc:
            failures.append(f"{path}: {type(exc).__name__}: {exc}")
    return failures


class CSVPackageWidthTests(unittest.TestCase):
    def test_static_page2_csvs_have_constant_width(self) -> None:
        root = Path(__file__).resolve().parents[1] / "page2"
        self.assertEqual(validate_constant_csv_widths(root), [])

    def test_external_package_when_requested(self) -> None:
        value = os.environ.get("PAGE2_PACKAGE_ROOT")
        if not value:
            self.skipTest("PAGE2_PACKAGE_ROOT not set")
        self.assertEqual(validate_constant_csv_widths(Path(value)), [])


if __name__ == "__main__":
    unittest.main()

"""Date-aware capacity lookup with explicit uncertainty states."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


DEFAULT_CAPACITY_HISTORY = Path(__file__).resolve().parents[2] / "data" / "capacity_history.csv"


@dataclass(frozen=True)
class CapacityRegimeRecord:
    dam_id: str
    valid_from: date
    valid_to: date
    capacity_mm3: float
    source: str
    source_file: str
    status: str


class CapacityIndex:
    """In-memory lookup that never fills a date not covered by evidence."""

    def __init__(self, regimes: dict[str, list[CapacityRegimeRecord]]):
        self.regimes = regimes

    @classmethod
    def from_csv(cls, path: str | Path = DEFAULT_CAPACITY_HISTORY) -> "CapacityIndex":
        regimes: dict[str, list[CapacityRegimeRecord]] = {}
        with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                record = CapacityRegimeRecord(
                    dam_id=row["dam_id"],
                    valid_from=date.fromisoformat(row["valid_from"]),
                    valid_to=date.fromisoformat(row["valid_to"]) if row["valid_to"] else date.max,
                    capacity_mm3=float(row["capacity_mm3"]),
                    source=row["source"],
                    source_file=row["source_file"],
                    status=row["status"],
                )
                regimes.setdefault(record.dam_id, []).append(record)
        return cls(regimes)

    def for_date(self, dam_id: str, when: str | date) -> dict:
        target = date.fromisoformat(when) if isinstance(when, str) else when
        matches = [
            row for row in self.regimes.get(dam_id, [])
            if row.valid_from <= target <= row.valid_to
        ]
        if not matches:
            return {
                "dam_id": dam_id,
                "date": target.isoformat(),
                "status": "UNAVAILABLE",
                "capacity_mm3": None,
                "matches": [],
            }
        values = {row.capacity_mm3 for row in matches}
        if len(matches) > 1 or len(values) > 1:
            return {
                "dam_id": dam_id,
                "date": target.isoformat(),
                "status": "AMBIGUOUS",
                "capacity_mm3": None,
                "matches": [row.__dict__ for row in matches],
            }
        return {
            "dam_id": dam_id,
            "date": target.isoformat(),
            "status": "KNOWN",
            "capacity_mm3": matches[0].capacity_mm3,
            "matches": [matches[0].__dict__],
        }


def capacity_for_date(
    dam_id: str,
    when: str | date,
    capacity_history_path: str | Path = DEFAULT_CAPACITY_HISTORY,
) -> dict:
    """Return KNOWN, AMBIGUOUS, or UNAVAILABLE without filling gaps.

    The bounds in ``capacity_history.csv`` are inclusive. A blank ``valid_to``
    means the observed regime is open-ended. Multiple applicable evidence rows
    are reported as AMBIGUOUS; no winner is selected.
    """
    return CapacityIndex.from_csv(capacity_history_path).for_date(dam_id, when)

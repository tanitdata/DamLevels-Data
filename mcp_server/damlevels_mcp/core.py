"""Query logic over the DamLevels-Data tables, independent of MCP.

Every public method returns a JSON-serialisable dict built by ``_envelope`` so
that each answer carries the record's coverage, the source attribution and any
caveats. Rules enforced here (see docs/data_dictionary.md):

- values are never interpolated, forward-filled or replaced by zero; a date
  without a value is reported as missing, never as the nearest value;
- dates outside 2014-07-02..2025-10-10 are answered with OUTSIDE_RECORD;
- dams are identified by dam_id; names are only used to find the dam_id;
- fill uses the capacity regime in force on that date and is not computed when
  that capacity is unknown or ambiguous;
- Page 3 transfer facts are always returned with their PROBABLE authority,
  both endpoint mapping statuses and the time rule of the requested measure;
  candidate node crosswalks are reported separately and never promoted.
"""
from __future__ import annotations

import difflib
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd

ATTRIBUTION = (
    "Source: DGBGTH, Ministère de l'Agriculture, des Ressources Hydrauliques et de la Pêche (Tunisie), "
    "bulletins \"Situation des barrages\" published by ONAGRI. Licence Nationale de Données Publiques Ouvertes. "
    "Extracted and restructured by DamLevels-Data (CC BY 4.0)."
)
MAX_DAILY_ROWS = 400
MAX_TRANSFER_ROWS = 1000
HALF_UNIT = 0.0005  # storage is printed to 0.001 Mm3
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Page 3 nodes whose crosswalk to a stable dam_id is a candidate only (docs/known_issues.md).
CANDIDATE_NODES = {"NODE-DAM-BOUHERTMA": "bouheurtma", "NODE-DAM-ZAYATIN": "ziatine"}
TRANSFER_TIME_RULES = {
    "today": "amount over day D-1, the day before bulletin date D (DLO DAY_BEFORE_BULLETIN).",
    "current_season_to_date": "cumulative amount from 1 September of the current season up to day D-1 "
                              "(DLO SEASON_TO_DATE); not a daily amount.",
    "previous_season_to_date": "cumulative amount over the same interval one season earlier; not a daily amount.",
}


class QueryError(ValueError):
    """A request that cannot be answered as asked (unknown dam, bad date, ...)."""

    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.details = details

    def as_dict(self) -> dict:
        return {"error": self.code, "message": str(self), **self.details}


def default_root() -> Path:
    env = os.environ.get("DAMLEVELS_DATA_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def _fold(text: str) -> str:
    """Lower-case, strip accents, tatweel and non-alphanumerics: 'Bir M'Cherga' -> 'birmcherga'."""
    text = unicodedata.normalize("NFKD", str(text)).replace("ـ", "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z؀-ۿ]", "", text.lower())


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), digits)


def _mean(values) -> float:
    """Exact decimal mean of 0.001-unit values, rounded half-to-even to 0.001."""
    vals = [Decimal(repr(float(v))) for v in values]
    return float((sum(vals) / len(vals)).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True)
class Coverage:
    first: str
    last: str

    def as_dict(self) -> dict:
        return {"first_date": self.first, "last_date": self.last,
                "note": "Historical archive; no bulletin after the last date is included."}


class DamData:
    """Lazy, read-only access to the repository tables."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_root()
        if not (self.root / "data" / "dams.csv").is_file():
            raise FileNotFoundError(f"DamLevels-Data tables not found under {self.root}")

    # ------------------------------------------------------------------ tables
    @cached_property
    def dams(self) -> pd.DataFrame:
        return pd.read_csv(self.root / "data/dams.csv", dtype=str).fillna("")

    @cached_property
    def storage(self) -> pd.DataFrame:
        frame = pd.read_parquet(self.root / "data/parquet/storage.parquet")
        return frame.sort_values(["dam_id", "date"]).reset_index(drop=True)

    @cached_property
    def printed_fill(self) -> pd.DataFrame:
        path = self.root / "qa/printed_fill_reference.parquet"
        frame = pd.read_parquet(path, columns=["dam_id", "date", "value"])
        return frame.set_index(["dam_id", "date"])["value"]

    @cached_property
    def manifest(self) -> pd.DataFrame:
        return pd.read_csv(self.root / "sources/manifest.csv", dtype=str).fillna("")

    @cached_property
    def page1_dates(self) -> list[str]:
        m = self.manifest
        return sorted(m.loc[m["page1_source_file"] != "", "bulletin_date"])

    @cached_property
    def bulletin_dates(self) -> list[str]:
        """Every logical bulletin date in the manifest, with or without Page 1."""
        return sorted(self.manifest["bulletin_date"])

    @cached_property
    def national_totals(self) -> pd.DataFrame:
        frame = pd.read_csv(self.root / "provenance/page1_national_totals.csv", dtype=str)
        return frame[frame["field"] == "p1_stock_today_mm3"].set_index("bulletin_date")

    @cached_property
    def national_dispositions(self) -> dict[str, dict]:
        """Known national-total exceptions: evidence-backed dispositions and the KPI K12 disagreements."""
        out = {}
        disp = pd.read_csv(self.root / "provenance/national_reconciliation_dispositions.csv", dtype=str)
        for r in disp.itertuples():
            out[r.bulletin_date] = {"classification": r.classification, "evidence": r.evidence_summary,
                                    "reference": "provenance/national_reconciliation_dispositions.csv"}
        k12 = pd.read_csv(self.root / "qa/kpi/results/K12_national_disagreements.csv", dtype=str)
        for r in k12.itertuples():
            out.setdefault(r.bulletin_date, {
                "classification": "SOURCE_PRINTED_DISAGREEMENT",
                "evidence": "The printed national TOTAL differs from the sum of the printed dam values beyond "
                            "the rounding bound. Both are kept as printed; neither is corrected.",
                "reference": "qa/kpi/results/K12_national_disagreements.csv"})
        return out

    @cached_property
    def lineage(self) -> pd.DataFrame:
        cols = ["observation_id", "physical_column", "cell_bbox", "raw_glyph_sequence", "parser_state",
                "checksum_validation_reference", "link_status"]
        return pd.read_csv(self.root / "provenance/storage_lineage.csv", dtype=str, usecols=cols).set_index("observation_id")

    @cached_property
    def transfers(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "data/parquet/transfers.parquet")

    @cached_property
    def tables(self) -> dict[str, dict]:
        """Published tables with their row counts (read from the Parquet metadata only)."""
        import pyarrow.parquet as pq

        described = {
            "data/storage.csv": "daily storage, long format, one row per dam and date",
            "data/bulletin_page1.csv": "every printed Page 1 column (inflows, releases, fill, stock), one row per dam "
                                       "and bulletin; flows describe the day before the bulletin",
            "data/bulletin_page2.csv": "every printed Page 2 column (water level, capacities, siltation, rain, "
                                       "evaporation, previous hydraulic year), one row per dam and bulletin",
            "data/transfers.csv": "Page 3 inter-dam transfer facts, authority PROBABLE",
        }
        out = {}
        for path, what in described.items():
            parquet = self.root / "data/parquet" / Path(path).with_suffix(".parquet").name
            out[path] = {"content": what, "rows": pq.ParquetFile(parquet).metadata.num_rows}
        return out

    @cached_property
    def capacity(self):
        src = str(self.root / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        from validate.capacity import CapacityIndex  # repository helper; never fills gaps

        return CapacityIndex.from_csv(self.root / "data/capacity_history.csv")

    @cached_property
    def coverage(self) -> Coverage:
        return Coverage(self.storage["date"].min(), self.storage["date"].max())

    @cached_property
    def dam_spans(self) -> pd.DataFrame:
        g = self.storage.groupby("dam_id")["date"]
        return pd.DataFrame({"first_date": g.min(), "last_date": g.max(), "observations": g.size()})

    # ----------------------------------------------------------------- helpers
    def _envelope(self, result: Any, notes: list[str] | None = None) -> dict:
        return {"result": result, "coverage": self.coverage.as_dict(), "attribution": ATTRIBUTION,
                "notes": notes or []}

    def _date(self, value: str, field: str = "date") -> str:
        text = value.strip() if isinstance(value, str) else ""
        try:
            if not ISO_DATE.fullmatch(text):
                raise ValueError(text)
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise QueryError("BAD_DATE", f"{field} must be an ISO date YYYY-MM-DD, got {value!r}") from exc
        iso = parsed.isoformat()
        cov = self.coverage
        if not cov.first <= iso <= cov.last:
            raise QueryError("OUTSIDE_RECORD", f"{iso} is outside the record ({cov.first} to {cov.last}). "
                             "No value is estimated outside the archive.", coverage=cov.as_dict())
        return iso

    def _range(self, start: str, end: str) -> tuple[str, str]:
        start_iso, end_iso = self._date(start, "start"), self._date(end, "end")
        if start_iso > end_iso:
            raise QueryError("BAD_RANGE", "start must not be after end.", start=start_iso, end=end_iso)
        return start_iso, end_iso

    @cached_property
    def _label_table(self) -> dict[str, set[str]]:
        table: dict[str, set[str]] = {}
        for row in self.dams.itertuples():
            for label in [row.dam_id, row.name_fr, row.name_ar, *str(row.aliases).split("|")]:
                if label:
                    table.setdefault(_fold(label), set()).add(row.dam_id)
        return table

    def match_dam(self, query: str) -> tuple[str, str]:
        """Map a dam_id, French name, alias or Arabic name to (dam_id, match_type).

        match_type is 'exact' (the whole name equals a known label) or 'partial' (the
        name is part of the labels of exactly one dam). A query that only contains a
        known label inside a longer text is not accepted; its dam is returned as a
        candidate instead.
        """
        key = _fold(query) if isinstance(query, str) else ""
        if not key:
            raise QueryError("UNKNOWN_DAM", "Empty dam name.")
        table = self._label_table
        if key in table and len(table[key]) == 1:
            return next(iter(table[key])), "exact"
        partial = sorted({d for k, ids in table.items() if key in k for d in ids})
        if len(partial) == 1:
            return partial[0], "partial"
        if partial:
            raise QueryError("AMBIGUOUS_DAM", f"No unique dam matches {query!r}.", candidates=partial,
                             match_type="partial")
        contained = sorted({d for k, ids in table.items() if len(k) > 3 and k in key for d in ids})
        if contained:
            raise QueryError("UNKNOWN_DAM", f"No dam is named {query!r}; the text contains the name of a dam. "
                             "Use the dam_id of the intended candidate.", candidates=contained,
                             match_type="label_inside_query")
        suggestions = sorted({d for k in difflib.get_close_matches(key, list(table), n=5, cutoff=0.6) for d in table[k]})
        raise QueryError("UNKNOWN_DAM", f"No unique dam matches {query!r}.", candidates=suggestions,
                         match_type="similar_spelling")

    def resolve_dam(self, query: str) -> str:
        return self.match_dam(query)[0]

    def _dam_row(self, dam_id: str) -> pd.Series:
        return self.dams.set_index("dam_id").loc[dam_id]

    def _dam_label(self, dam_id: str) -> dict:
        row = self._dam_row(dam_id)
        return {"dam_id": dam_id, "name_fr": row["name_fr"], "name_ar": row["name_ar"] or None}

    def _value(self, dam_id: str, iso: str) -> pd.Series | None:
        s = self.storage
        hit = s[(s["dam_id"] == dam_id) & (s["date"] == iso)]
        return None if hit.empty else hit.iloc[0]

    def _capacity(self, dam_id: str, iso: str) -> dict:
        res = self.capacity.for_date(dam_id, iso)
        cap = res.get("capacity_mm3")
        return {"status": res["status"], "capacity_mm3": _round(float(cap), 2) if cap is not None else None}

    def _nearest(self, dam_id: str, iso: str) -> dict:
        dates = self.storage.loc[self.storage["dam_id"] == dam_id, "date"]
        before = dates[dates < iso]
        after = dates[dates > iso]
        return {"previous_value_date": before.max() if not before.empty else None,
                "next_value_date": after.min() if not after.empty else None}

    # ------------------------------------------------------------------- tools
    def dataset_info(self) -> dict:
        s = self.storage
        result = {
            "name": "DamLevels-Data",
            "description": "Daily storage of Tunisia's large dams reconstructed from the DGBGTH bulletins "
                           "'Situation des barrages' (ONAGRI), with every printed Page 1 and Page 2 column. "
                           "Values are read from the PDF text layer; no OCR.",
            "dams": int(self.dams.shape[0]),
            "storage_observations": int(len(s)),
            "bulletin_dates": int(self.manifest.shape[0]),
            "tables": self.tables,
            "unit": "Mm3 (million cubic metres)",
            "time_rules": {
                "storage, level, fill": "state on the bulletin date",
                "inflow, release, transfer, evaporation": "amount over the day before the bulletin",
            },
            "source_page": "https://www.onagri.nat.tn/Situation-des-barrages/fr/19",
            "repository": "https://github.com/tanitdata/DamLevels-Data",
        }
        return self._envelope(result, ["Missing days are gaps, never zeros.",
                                       "Page 3 transfer facts have authority PROBABLE.",
                                       "Inflows, releases, water levels and the other Page 1/Page 2 columns are in the "
                                       "full page tables; no tool serves them yet. describe_variable explains any "
                                       "of their column names."])

    def list_dams(self) -> dict:
        spans = self.dam_spans
        rows = []
        for r in self.dams.itertuples():
            span = spans.loc[r.dam_id] if r.dam_id in spans.index else None
            rows.append({
                "dam_id": r.dam_id, "name_fr": r.name_fr, "name_ar": r.name_ar or None,
                "basin": r.basin or None,
                "latitude": float(r.latitude) if r.latitude else None,
                "longitude": float(r.longitude) if r.longitude else None,
                "reference_capacity_mm3": float(r.reference_capacity_mm3) if r.reference_capacity_mm3 else None,
                "first_date": span["first_date"] if span is not None else None,
                "last_date": span["last_date"] if span is not None else None,
                "observations": int(span["observations"]) if span is not None else 0,
            })
        return self._envelope(rows, ["reference_capacity_mm3 is the latest printed capacity regime; "
                                     "use get_fill for the capacity in force on a given date.",
                                     "Basin is given only where officially supported (6 dams)."])

    def find_dam(self, query: str) -> dict:
        try:
            dam_id, match_type = self.match_dam(query)
            return self._envelope({"match": self._dam_label(dam_id), "match_type": match_type})
        except QueryError as err:
            cands = [self._dam_label(d) for d in err.details.get("candidates", [])]
            return self._envelope({"match": None, "match_type": err.details.get("match_type"), "candidates": cands},
                                  [str(err)])

    def get_storage(self, dam: str, start: str, end: str, resolution: str = "daily") -> dict:
        dam_id = self.resolve_dam(dam)
        start_iso, end_iso = self._range(start, end)
        s = self.storage
        sel = s[(s["dam_id"] == dam_id) & (s["date"] >= start_iso) & (s["date"] <= end_iso)]
        span = self.dam_spans.loc[dam_id]
        active_from, active_to = max(start_iso, span["first_date"]), min(end_iso, span["last_date"])
        all_bulletins = [d for d in self.bulletin_dates if active_from <= d <= active_to]
        page1 = [d for d in self.page1_dates if active_from <= d <= active_to]
        without_page1 = sorted(set(all_bulletins) - set(page1))
        missing = sorted(set(page1) - set(sel["date"]))
        notes = ["Stock values describe the morning of each bulletin date.",
                 "Dates without a value are listed as missing; nothing is interpolated."]
        if start_iso < span["first_date"]:
            notes.append(f"{dam_id} first appears in the bulletins on {span['first_date']}.")
        calendar_days = (date.fromisoformat(active_to) - date.fromisoformat(active_from)).days + 1 if active_from <= active_to else 0
        result: dict[str, Any] = {
            "dam": self._dam_label(dam_id), "unit": "Mm3", "start": start_iso, "end": end_iso,
            "dam_period": {"start": active_from, "end": active_to} if active_from <= active_to else None,
            "values_found": int(len(sel)),
            "bulletins_in_dam_period": len(all_bulletins),
            "bulletins_with_page1_in_dam_period": len(page1),
            "bulletins_without_page1": without_page1[:50], "bulletins_without_page1_count": len(without_page1),
            "calendar_days_without_bulletin": calendar_days - len(all_bulletins),
            "missing_dates": missing[:50], "missing_count": len(missing),
        }
        notes.append("Counts are limited to dam_period, the part of the request in which this dam appears in the "
                     "bulletins. missing_dates are bulletin dates with a Page 1 on which this dam has no value; "
                     "bulletins_without_page1 are bulletins that exist without a Page 1 (storage is printed only on "
                     "Page 1 and is not taken from another page); calendar_days_without_bulletin counts days for "
                     "which the archive holds no bulletin at all. Lists are cut at 50 dates; counts are complete.")
        if resolution == "daily":
            if len(sel) > MAX_DAILY_ROWS:
                raise QueryError("TOO_MANY_ROWS", f"{len(sel)} daily values; narrow the range or use "
                                 f"resolution='monthly' (max {MAX_DAILY_ROWS} daily rows).", values=int(len(sel)))
            result["series"] = [{"date": d, "storage_mm3": _round(v)} for d, v in zip(sel["date"], sel["value"])]
        elif resolution == "monthly":
            m = sel.assign(month=sel["date"].str[:7]).groupby("month")["value"]
            result["series"] = [
                {"month": k, "days_with_value": int(g.size), "first_mm3": _round(g.iloc[0]), "last_mm3": _round(g.iloc[-1]),
                 "min_mm3": _round(g.min()), "max_mm3": _round(g.max()), "mean_mm3": _mean(g)}
                for k, g in m
            ]
            notes.append("Monthly figures are computed only from the days with a value; mean_mm3 is the exact "
                         "decimal mean rounded half-to-even to 0.001 Mm3.")
        else:
            raise QueryError("BAD_RESOLUTION", "resolution must be 'daily' or 'monthly'.")
        return self._envelope(result, notes)

    def get_fill(self, dam: str, on: str) -> dict:
        dam_id = self.resolve_dam(dam)
        iso = self._date(on)
        row = self._value(dam_id, iso)
        cap = self._capacity(dam_id, iso)
        notes = ["fill = storage / capacity in force on that date (printed Page 2 capacity regime)."]
        result: dict[str, Any] = {"dam": self._dam_label(dam_id), "date": iso, "capacity": cap}
        if row is None:
            result.update({"status": "NO_VALUE", "storage_mm3": None, "fill_pct": None, **self._nearest(dam_id, iso)})
            notes.append("No storage value on this date; the nearest dates are given but not substituted.")
            return self._envelope(result, notes)
        storage = float(row["value"])
        result.update({"status": "OK", "storage_mm3": _round(storage)})
        if cap["status"] == "KNOWN" and cap["capacity_mm3"]:
            result["fill_pct"] = _round(100 * storage / cap["capacity_mm3"], 1)
            if result["fill_pct"] > 100:
                notes.append("Storage above the printed useful capacity is possible (flood surcharge); not an error.")
        else:
            result["fill_pct"] = None
            notes.append(f"Capacity is {cap['status']} on this date; fill is not computed.")
        printed = self.printed_fill.get((dam_id, iso))
        result["printed_fill_pct"] = _round(printed, 1) if printed is not None and not pd.isna(printed) else None
        return self._envelope(result, notes)

    def national_storage(self, on: str) -> dict:
        iso = self._date(on)
        day = self.storage[self.storage["date"] == iso]
        notes = ["The total is the sum of the dams printed with a value on that date."]
        if day.empty:
            return self._envelope({"date": iso, "status": "NO_BULLETIN_VALUES", "total_mm3": None}, notes)
        caps = [self._capacity(d, iso) for d in day["dam_id"]]
        known = [(v, c["capacity_mm3"]) for v, c in zip(day["value"], caps) if c["status"] == "KNOWN" and c["capacity_mm3"]]
        excluded = [d for d, c in zip(day["dam_id"], caps) if not (c["status"] == "KNOWN" and c["capacity_mm3"])]
        total = float(day["value"].sum())
        numerator, denominator = sum(v for v, _ in known), sum(c for _, c in known)
        printed = self.national_totals.loc[iso] if iso in self.national_totals.index else None
        result: dict[str, Any] = {
            "date": iso, "status": "OK", "dams_with_value": int(len(day)), "total_mm3": _round(total),
            "fill_pct_of_known_capacity": _round(100 * numerator / denominator, 1) if known else None,
            "fill_numerator_mm3": _round(numerator) if known else None,
            "known_capacity_sum_mm3": _round(denominator, 2) if known else None,
            "dams_in_fill": len(known),
            "dams_without_known_capacity": excluded,
            "printed_national_total_mm3": None,
        }
        if excluded:
            notes.append(f"{', '.join(excluded)}: capacity not known on this date. These dams are included in "
                         "total_mm3 but excluded from both the numerator and the denominator of "
                         "fill_pct_of_known_capacity, which therefore covers dams_in_fill dams only.")
        if printed is not None and printed["printed_total_mm3"]:
            printed_total = float(printed["printed_total_mm3"])
            places = int(printed["printed_decimal_places"] or 3)
            bound = len(day) * HALF_UNIT + 0.5 * 10.0 ** (-places)
            disposition = self.national_dispositions.get(iso)
            result["printed_national_total_mm3"] = _round(printed_total)
            result["printed_total_comparison"] = {
                "difference_mm3": _round(total - printed_total),
                "rounding_bound_mm3": _round(bound, 4),
                "disposition": disposition["classification"] if disposition else
                ("WITHIN_ROUNDING" if abs(total - printed_total) <= bound + 1e-9 else "OUTSIDE_ROUNDING"),
            }
            notes.append("printed_national_total_mm3 is the TOTAL printed on Page 1; rounding_bound_mm3 is the largest "
                         "difference that printing each value to 0.001 Mm3 can explain.")
            if disposition:
                notes.append(f"Known exception ({disposition['classification']}, {disposition['reference']}): "
                             f"{disposition['evidence']}")
        return self._envelope(result, notes)

    def compare_years(self, dam: str, month_day: str) -> dict:
        if not isinstance(month_day, str) or not re.fullmatch(r"\d{2}-\d{2}", month_day):
            raise QueryError("BAD_DATE", "month_day must be MM-DD, e.g. '02-01'.")
        try:
            date.fromisoformat(f"2000-{month_day}")  # leap year: accepts 02-29, rejects 02-30, 13-01, 00-00
        except ValueError as exc:
            raise QueryError("BAD_DATE", f"month_day {month_day!r} is not a calendar day.") from exc
        everyone = isinstance(dam, str) and dam.strip().lower() in {"all", "national", "*"}
        dam_id = None if everyone else self.resolve_dam(dam)
        first, last = int(self.coverage.first[:4]), int(self.coverage.last[:4])
        series = []
        for year in range(first, last + 1):
            iso = f"{year}-{month_day}"
            try:
                date.fromisoformat(iso)
            except ValueError:
                continue
            if not self.coverage.first <= iso <= self.coverage.last:
                continue
            if everyone:
                day = self.storage[self.storage["date"] == iso]
                series.append({"date": iso, "total_mm3": _round(day["value"].sum()) if not day.empty else None,
                               "dams_with_value": int(len(day))})
            else:
                row = self._value(dam_id, iso)
                series.append({"date": iso, "storage_mm3": _round(row["value"]) if row is not None else None})
        target = "all dams with a value (count varies by year)" if everyone else self._dam_label(dam_id)
        notes = ["Exact dates only; a year without a bulletin value on that date shows null.",
                 "National totals include only the dams printed that day; the roster grew over time."]
        if month_day == "02-29":
            notes.append("02-29 exists only in leap years; other years are not listed.")
        return self._envelope({"target": target, "unit": "Mm3", "series": series}, notes)

    def get_source(self, dam: str, on: str) -> dict:
        dam_id = self.resolve_dam(dam)
        iso = self._date(on)
        row = self._value(dam_id, iso)
        if row is None:
            raise QueryError("NO_VALUE", f"No storage value for {dam_id} on {iso}.", **self._nearest(dam_id, iso))
        bulletin = self.manifest.set_index("bulletin_date").loc[iso]
        lin = self.lineage.loc[row["observation_id"]] if row["observation_id"] in self.lineage.index else None
        result = {
            "dam": self._dam_label(dam_id), "date": iso, "storage_mm3": _round(row["value"]),
            "observation_id": row["observation_id"], "source_file": row["source_file"],
            "source_sha256": row["source_sha256"], "page": row["page"], "source_field": row["source_field"],
            "engine_version": row["engine_version"], "flag": row["flag"],
            "bulletin_url": bulletin["original_url"] or None,
            "cell": None if lin is None else {
                "physical_column": lin["physical_column"], "bbox_pdf_points": lin["cell_bbox"],
                "printed_text": lin["raw_glyph_sequence"], "parser_state": lin["parser_state"],
                "checksum_reference": lin["checksum_validation_reference"],
            },
        }
        return self._envelope(result, ["bulletin_url is the combined three-page PDF on ONAGRI; source_sha256 "
                                       "identifies the split Page 1 file the value was read from.",
                                       "get_source covers Page 1 storage values only; each get_transfers row "
                                       "carries its own Page 3 source file, hash and evidence identifier."])

    def _transfer_row(self, r, bulletin_urls: dict[str, str]) -> dict:
        return {
            "transfer_observation_id": r.transfer_observation_id, "bulletin_date": r.bulletin_date,
            "from": r.from_dam_id or r.from_node_id or None, "to": r.to_dam_id or r.to_node_id or None,
            "from_node_id": r.from_node_id or None, "to_node_id": r.to_node_id or None,
            "from_mapping_status": r.from_mapping_status, "to_mapping_status": r.to_mapping_status,
            "role": r.row_role, "measure": r.variable, "value_mm3": _round(r.value), "value_status": r.value_status,
            "authority": r.authority_release,
            "source": {"source_file": r.source_file, "source_sha256": r.source_sha256, "page": r.page,
                       "source_field": r.source_field, "evidence_id": r.evidence_id or None,
                       "printed_text": r.raw_text if r.raw_text else None,
                       "bulletin_url": bulletin_urls.get(r.bulletin_date) or None},
        }

    def get_transfers(self, start: str, end: str, dam: str | None = None, measure: str = "today", limit: int = 200) -> dict:
        start_iso, end_iso = self._range(start, end)
        if measure not in TRANSFER_TIME_RULES:
            raise QueryError("BAD_MEASURE", "measure must be today, current_season_to_date or previous_season_to_date.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_TRANSFER_ROWS:
            raise QueryError("BAD_LIMIT", f"limit must be an integer from 1 to {MAX_TRANSFER_ROWS}, got {limit!r}.")
        t = self.transfers
        sel = t[(t["bulletin_date"] >= start_iso) & (t["bulletin_date"] <= end_iso) & (t["variable"] == measure)]
        candidates = sel.iloc[0:0]
        dam_id = None
        if dam:
            dam_id = self.resolve_dam(dam)
            nodes = [n for n, d in CANDIDATE_NODES.items() if d == dam_id]
            candidates = sel[sel["from_node_id"].isin(nodes) | sel["to_node_id"].isin(nodes)]
            sel = sel[(sel["from_dam_id"] == dam_id) | (sel["to_dam_id"] == dam_id)]
        urls = dict(zip(self.manifest["bulletin_date"], self.manifest["original_url"]))
        rows = [self._transfer_row(r, urls) for r in sel.head(limit).itertuples()]
        result: dict[str, Any] = {"start": start_iso, "end": end_iso, "measure": measure,
                                  "time_rule": TRANSFER_TIME_RULES[measure], "rows": rows,
                                  "matched": int(len(sel)), "returned": len(rows), "truncated": len(sel) > limit}
        notes = ["Page 3 facts have authority PROBABLE.",
                 "bulletin_date is the date of the bulletin (D), used for start/end. The published table stores "
                 "date = bulletin date with effective_date_rule SAME_DAY; under DLO 0.3 the amount refers to "
                 f"another period: {measure} is the {TRANSFER_TIME_RULES[measure]}",
                 "ACCOUNTING_OBSERVATION rows (Sejnane accounting) are not physical transfers."]
        if dam_id is not None:
            notes.append(f"rows are the facts whose stable from/to dam_id is {dam_id}.")
            if len(candidates):
                result["candidate_endpoint_rows"] = [self._transfer_row(r, urls) for r in candidates.head(limit).itertuples()]
                result["candidate_endpoint_matched"] = int(len(candidates))
                result["candidate_endpoint_truncated"] = len(candidates) > limit
                notes.append(f"candidate_endpoint_rows: {len(candidates)} facts name a Page 3 node whose crosswalk to "
                             f"{dam_id} is only a candidate (see *_mapping_status). They are not counted in rows and "
                             "the node is not promoted to this dam.")
        if len(sel) > limit:
            notes.append(f"{len(sel)} rows matched; only the first {limit} are returned (truncated).")
        return self._envelope(result, notes)

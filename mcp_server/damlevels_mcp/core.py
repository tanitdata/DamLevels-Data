"""Query logic over the DamLevels-Data tables, independent of MCP.

Every public method returns a JSON-serialisable dict built by ``_envelope`` so
that each answer carries the record's coverage, the source attribution and any
caveats. Rules enforced here (see CLAUDE.md and docs/data_dictionary.md):

- values are never interpolated, forward-filled or replaced by zero; a date
  without a value is reported as missing, never as the nearest value;
- dates outside 2014-07-02..2025-10-10 are answered with OUTSIDE_RECORD;
- dams are identified by dam_id; names are only used to find the dam_id;
- fill uses the capacity regime in force on that date and is not computed when
  that capacity is unknown or ambiguous;
- Page 3 transfer facts are always returned with their PROBABLE authority and
  the note that `today` amounts describe the day before the bulletin.
"""
from __future__ import annotations

import difflib
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
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
    """Lower-case, strip accents and non-alphanumerics: 'Bir M'Cherga' -> 'birmcherga'."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z؀-ۿ]", "", text.lower())


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), digits)


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
    def national_totals(self) -> pd.DataFrame:
        frame = pd.read_csv(self.root / "provenance/page1_national_totals.csv", dtype=str)
        return frame.set_index("bulletin_date")

    @cached_property
    def lineage(self) -> pd.DataFrame:
        cols = ["observation_id", "physical_column", "cell_bbox", "raw_glyph_sequence", "parser_state",
                "checksum_validation_reference", "link_status"]
        return pd.read_csv(self.root / "provenance/storage_lineage.csv", dtype=str, usecols=cols).set_index("observation_id")

    @cached_property
    def transfers(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "data/parquet/transfers.parquet")

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
        try:
            parsed = date.fromisoformat(str(value).strip())
        except ValueError as exc:
            raise QueryError("BAD_DATE", f"{field} must be an ISO date YYYY-MM-DD, got {value!r}") from exc
        iso = parsed.isoformat()
        cov = self.coverage
        if not cov.first <= iso <= cov.last:
            raise QueryError("OUTSIDE_RECORD", f"{iso} is outside the record ({cov.first} to {cov.last}). "
                             "No value is estimated outside the archive.", coverage=cov.as_dict())
        return iso

    def resolve_dam(self, query: str) -> str:
        """Map a dam_id, French name, alias or Arabic name to a dam_id."""
        key = _fold(query)
        if not key:
            raise QueryError("UNKNOWN_DAM", "Empty dam name.")
        table = {}
        for row in self.dams.itertuples():
            for label in [row.dam_id, row.name_fr, row.name_ar, *str(row.aliases).split("|")]:
                if label:
                    table.setdefault(_fold(label), set()).add(row.dam_id)
        if key in table and len(table[key]) == 1:
            return next(iter(table[key]))
        partial = sorted({d for k, ids in table.items() if key in k or (len(k) > 3 and k in key) for d in ids})
        if len(partial) == 1:
            return partial[0]
        suggestions = partial or sorted({d for k in difflib.get_close_matches(key, list(table), n=5, cutoff=0.6) for d in table[k]})
        raise QueryError("UNKNOWN_DAM" if not partial else "AMBIGUOUS_DAM",
                         f"No unique dam matches {query!r}.", candidates=suggestions)

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
                           "'Situation des barrages' (ONAGRI). Values are read from the PDF text layer; no OCR.",
            "dams": int(self.dams.shape[0]),
            "storage_observations": int(len(s)),
            "bulletin_dates": int(self.manifest.shape[0]),
            "unit": "Mm3 (million cubic metres)",
            "time_rules": {
                "storage, level, fill": "state on the bulletin date",
                "inflow, release, transfer, evaporation": "amount over the day before the bulletin",
            },
            "source_page": "https://www.onagri.nat.tn/Situation-des-barrages/fr/19",
            "repository": "https://github.com/tanitdata/DamLevels-Data",
        }
        return self._envelope(result, ["Missing days are gaps, never zeros.",
                                       "Page 3 transfer facts have authority PROBABLE."])

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
            return self._envelope({"match": self._dam_label(self.resolve_dam(query))})
        except QueryError as err:
            cands = [self._dam_label(d) for d in err.details.get("candidates", [])]
            return self._envelope({"match": None, "candidates": cands}, [str(err)])

    def get_storage(self, dam: str, start: str, end: str, resolution: str = "daily") -> dict:
        dam_id = self.resolve_dam(dam)
        start_iso, end_iso = self._date(start, "start"), self._date(end, "end")
        if start_iso > end_iso:
            raise QueryError("BAD_RANGE", "start must not be after end.")
        s = self.storage
        sel = s[(s["dam_id"] == dam_id) & (s["date"] >= start_iso) & (s["date"] <= end_iso)]
        span = self.dam_spans.loc[dam_id]
        active_from, active_to = max(start_iso, span["first_date"]), min(end_iso, span["last_date"])
        bulletin_dates = [d for d in self.page1_dates if active_from <= d <= active_to]
        missing = sorted(set(bulletin_dates) - set(sel["date"]))
        notes = ["Stock values describe the morning of each bulletin date.",
                 "Dates without a value are listed as missing; nothing is interpolated."]
        if start_iso < span["first_date"]:
            notes.append(f"{dam_id} first appears in the bulletins on {span['first_date']}.")
        calendar_days = (date.fromisoformat(active_to) - date.fromisoformat(active_from)).days + 1 if active_from <= active_to else 0
        result: dict[str, Any] = {
            "dam": self._dam_label(dam_id), "unit": "Mm3", "start": start_iso, "end": end_iso,
            "values_found": int(len(sel)),
            "bulletins_with_page1_in_dam_period": len(bulletin_dates),
            "calendar_days_without_bulletin": calendar_days - len(bulletin_dates),
            "missing_dates": missing[:50], "missing_count": len(missing),
        }
        notes.append("missing_dates are bulletin dates on which this dam has no value; "
                     "calendar_days_without_bulletin counts days on which no bulletin was published.")
        if resolution == "daily":
            if len(sel) > MAX_DAILY_ROWS:
                raise QueryError("TOO_MANY_ROWS", f"{len(sel)} daily values; narrow the range or use "
                                 f"resolution='monthly' (max {MAX_DAILY_ROWS} daily rows).", values=int(len(sel)))
            result["series"] = [{"date": d, "storage_mm3": _round(v)} for d, v in zip(sel["date"], sel["value"])]
        elif resolution == "monthly":
            m = sel.assign(month=sel["date"].str[:7]).groupby("month")["value"]
            result["series"] = [
                {"month": k, "days_with_value": int(g.size), "first_mm3": _round(g.iloc[0]), "last_mm3": _round(g.iloc[-1]),
                 "min_mm3": _round(g.min()), "max_mm3": _round(g.max()), "mean_mm3": _round(g.mean())}
                for k, g in m
            ]
            notes.append("Monthly figures are computed only from the days with a value.")
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
        total = float(day["value"].sum())
        printed = self.national_totals.loc[iso] if iso in self.national_totals.index else None
        result = {
            "date": iso, "status": "OK", "dams_with_value": int(len(day)), "total_mm3": _round(total),
            "fill_pct_of_known_capacity": _round(100 * sum(v for v, _ in known) / sum(c for _, c in known), 1) if known else None,
            "dams_without_known_capacity": [d for d, c in zip(day["dam_id"], caps) if c["status"] != "KNOWN"],
            "printed_national_total_mm3": _round(float(printed["printed_total_mm3"])) if printed is not None else None,
        }
        if printed is not None:
            notes.append("printed_national_total_mm3 is the TOTAL printed on Page 1; small differences are rounding.")
        return self._envelope(result, notes)

    def compare_years(self, dam: str, month_day: str) -> dict:
        if not re.fullmatch(r"\d{2}-\d{2}", month_day or ""):
            raise QueryError("BAD_DATE", "month_day must be MM-DD, e.g. '02-01'.")
        everyone = dam.strip().lower() in {"all", "national", "*"}
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
        return self._envelope({"target": target, "unit": "Mm3", "series": series},
                              ["Exact dates only; a year without a bulletin value on that date shows null.",
                               "National totals include only the dams printed that day; the roster grew over time."])

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
                                       "identifies the split Page 1 file the value was read from."])

    def get_transfers(self, start: str, end: str, dam: str | None = None, measure: str = "today", limit: int = 200) -> dict:
        start_iso, end_iso = self._date(start, "start"), self._date(end, "end")
        if measure not in {"today", "current_season_to_date", "previous_season_to_date"}:
            raise QueryError("BAD_MEASURE", "measure must be today, current_season_to_date or previous_season_to_date.")
        t = self.transfers
        sel = t[(t["bulletin_date"] >= start_iso) & (t["bulletin_date"] <= end_iso) & (t["variable"] == measure)]
        if dam:
            dam_id = self.resolve_dam(dam)
            sel = sel[(sel["from_dam_id"] == dam_id) | (sel["to_dam_id"] == dam_id)]
        rows = [{
            "bulletin_date": r.bulletin_date, "from": r.from_dam_id or r.from_node_id, "to": r.to_dam_id or r.to_node_id,
            "role": r.row_role, "measure": r.variable, "value_mm3": _round(r.value), "value_status": r.value_status,
            "authority": r.authority_release, "to_mapping_status": r.to_mapping_status,
        } for r in sel.head(limit).itertuples()]
        notes = ["Page 3 facts have authority PROBABLE.",
                 "date is the bulletin date; under DLO 0.3 the 'today' amount describes the day before the bulletin.",
                 "ACCOUNTING_OBSERVATION rows (Sejnane accounting) are not physical transfers."]
        if len(sel) > limit:
            notes.append(f"{len(sel)} rows matched; only the first {limit} are returned.")
        return self._envelope({"start": start_iso, "end": end_iso, "rows": rows, "matched": int(len(sel))}, notes)

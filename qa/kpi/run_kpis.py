"""DamLevels-Data open-data quality KPIs (independent Python recomputation).

Run from anywhere:
    python run_kpis.py

What it does
- Reads the published package (data/, provenance/, sources/, datapackage.json),
  the Page 1 / Page 2 staged views of the QA package and the DLO 0.3 catalogue copy.
- Recomputes every KPI with pandas. Frictionless is used for the declared-schema
  check when it is installed; otherwise that one KPI is marked SKIPPED.
- Compares each KPI with the automated QA (QA_MASTER_SUMMARY.csv, qa_summary.json).
- Writes only inside ./results (this folder). It never changes or deletes an input.

Requirements: Python 3.10+, pandas, pyarrow (for Parquet). Optional: frictionless.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import platform
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent            # .../DamLevels-Data/qa/kpi
ROOT = HERE.parents[1]                            # .../DamLevels-Data
INPUTS_DIR = HERE / "inputs"                      # copies of the staged automated-QA inputs
QA_DIR = ROOT / "qa"
ONT = HERE / "ontology_ref"
OUT = HERE / "results"

HALF_UNIT = 0.0005          # half of the 0.001 Mm3 printed precision of Page 1/2 volumes
CAPACITY_HALF_UNIT = 0.005  # capacity values carry at most two decimals (0.01 Mm3)
COUNTER_BOUND = 3 * HALF_UNIT   # C_t, C_(t-1) and D_t are three rounded printed numbers
BALANCE_BOUND = 4 * HALF_UNIT   # V_t, V_(t-1), Q_in and Q_out are four rounded printed numbers
Z95 = 1.959963984540054


# ----------------------------------------------------------------------------- helpers
def first_existing(*paths: Path) -> Path:
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError(" or ".join(str(p) for p in paths))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def rate(num: float, den: float) -> float | None:
    return None if not den else num / den


def wilson_lower(k: int, n: int, z: float = Z95) -> float | None:
    if n == 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def hydro_year(d: pd.Series) -> pd.Series:
    return d.dt.year.where(d.dt.month >= 9, d.dt.year - 1)


RESULTS: list[dict] = []
INPUTS: dict[str, Path] = {}


def kpi(kid, layer, name, dimension, formula, numerator, denominator, *, unit="ratio",
        qa_ref="", qa_value=None, verdict="", note=""):
    RESULTS.append({
        "kpi_id": kid, "layer": layer, "name": name, "iso25012_dimension": dimension,
        "formula": formula, "numerator": numerator, "denominator": denominator,
        "value": rate(numerator, denominator) if unit == "ratio" else numerator,
        "unit": unit, "automated_qa_ref": qa_ref, "automated_qa_value": qa_value,
        "verdict": verdict, "note": note,
    })


# ----------------------------------------------------------------------------- load
def load():
    p = {
        "storage": first_existing(ROOT / "data/parquet/storage.parquet", ROOT / "data/storage.csv"),
        "transfers": first_existing(ROOT / "data/parquet/transfers.parquet", ROOT / "data/transfers.csv"),
        "dams": ROOT / "data/dams.csv",
        "capacity": ROOT / "data/capacity_history.csv",
        "manifest": ROOT / "sources/manifest.csv",
        "national": ROOT / "provenance/page1_national_totals.csv",
        "dispositions": ROOT / "provenance/national_reconciliation_dispositions.csv",
        "missingness": ROOT / "provenance/storage_missingness.csv",
        "lineage": ROOT / "provenance/storage_lineage.csv",
        "printed_fill": first_existing(QA_DIR / "printed_fill_reference.parquet",
                                       QA_DIR / "printed_fill_reference.csv"),
        "datapackage": ROOT / "datapackage.json",
        "page1": INPUTS_DIR / "page1.parquet",
        "page2": INPUTS_DIR / "page2.parquet",
        "p3_accounting": INPUTS_DIR / "P3_DAILY_CUMULATIVE.csv",
        "qa_master": INPUTS_DIR / "QA_MASTER_SUMMARY.csv",
        "qa_summary": QA_DIR / "qa_summary.json",
        "temporal_summary": INPUTS_DIR / "TEMPORAL_PLAUSIBILITY_SUMMARY__temporal_plausibility_summary.json",
        "catalogue": ONT / "VARIABLE_CATALOGUE.csv",
    }
    INPUTS.update(p)

    def read(key, **kw):
        path = p[key]
        return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, **kw)

    d = {
        "storage": read("storage", dtype={"page": str}),
        "transfers": read("transfers", dtype=str),
        "dams": pd.read_csv(p["dams"], dtype=str),
        "capacity": pd.read_csv(p["capacity"], dtype={"capacity_mm3": float}),
        "manifest": pd.read_csv(p["manifest"], dtype=str),
        "national": pd.read_csv(p["national"], dtype={"printed_total_mm3": float}),
        "dispositions": pd.read_csv(p["dispositions"], dtype=str),
        "missingness": pd.read_csv(p["missingness"], dtype=str),
        "lineage": pd.read_csv(p["lineage"], dtype=str, usecols=["observation_id", "source_field", "raw_glyph_sequence"]),
        "printed_fill": read("printed_fill"),
        "datapackage": json.loads(p["datapackage"].read_text(encoding="utf-8")),
        "page1": pd.read_parquet(p["page1"]),
        "page2": pd.read_parquet(p["page2"]),
        "p3": pd.read_csv(p["p3_accounting"]),
        "qa_master": pd.read_csv(p["qa_master"], dtype=str).set_index("check_id"),
        "qa_summary": json.loads(p["qa_summary"].read_text(encoding="utf-8")),
        "temporal_summary": json.loads(p["temporal_summary"].read_text(encoding="utf-8")),
        "catalogue": pd.read_csv(p["catalogue"], dtype=str).fillna(""),
    }
    for name in ("page1", "page2"):
        d[name] = d[name].rename(columns={"dam_id_canonical": "dam_id", "bulletin_observation_date": "date"})
    return d


def qa_pass_rate(d, check_id):
    row = d["qa_master"].loc[check_id]
    try:
        return float(row["pass_rate"])
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- A. published package
def package_kpis(d):
    storage, dams, cap, manifest = d["storage"], d["dams"], d["capacity"], d["manifest"]
    pkg = d["datapackage"]

    # K01 declared-schema conformance (Frictionless, optional)
    tables = ["dams", "capacity-history", "storage", "transfers"]
    try:
        import frictionless
        sub = {k: v for k, v in pkg.items() if k != "resources"}
        sub["resources"] = [r for r in pkg["resources"] if r["name"] in tables]
        report = frictionless.Package(sub, basepath=str(ROOT)).validate(limit_errors=1_000_000)
        rows = sum(int(t.stats.get("rows") or 0) for t in report.tasks)
        bad = sum(len({e.row_number for e in t.errors if getattr(e, "row_number", None)}) for t in report.tasks)
        kpi("K01", "A. published package", "Declared-schema conformance (4 tables)", "Compliance",
            "rows without Table Schema error / rows", rows - bad, rows,
            qa_ref="E3 Pydantic contracts", qa_value=1.0, verdict="CONFIRMED",
            note=f"frictionless {frictionless.__version__}; tables: {', '.join(tables)}")
    except ImportError:
        kpi("K01", "A. published package", "Declared-schema conformance (4 tables)", "Compliance",
            "rows without Table Schema error / rows", 0, 0, verdict="SKIPPED",
            note="frictionless not installed; run `pip install frictionless`")

    # K02 resource paths that resolve
    paths = [(r["name"], r.get("path")) for r in pkg["resources"]]
    resolved = [(n, pth, (ROOT / pth).exists()) for n, pth in paths if isinstance(pth, str)]
    missing = [f"{n} -> {pth}" for n, pth, ok in resolved if not ok]
    kpi("K02", "A. published package", "Resource paths that resolve", "Accessibility",
        "resources whose path exists / resources", sum(ok for *_, ok in resolved), len(resolved),
        verdict="NEW", note="missing: " + "; ".join(missing) if missing else "all resolve")

    # K03 strengthened storage contract
    date = pd.to_datetime(storage["date"], errors="coerce")
    p1_dates = set(manifest.loc[manifest["page1_sha256"].notna(), "bulletin_date"])
    checks = {
        "value_finite_nonnegative": np.isfinite(storage["value"]) & (storage["value"] >= 0),
        "unit_is_Mm3": storage["unit"].eq("Mm3"),
        "variable_is_storage": storage["variable"].eq("storage"),
        "date_is_page1_bulletin_date": date.notna() & storage["date"].isin(p1_dates),
        "dam_id_in_dams": storage["dam_id"].isin(dams["dam_id"]),
        "sha256_pattern": storage["source_sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}"),
        "lineage_id_present": storage["lineage_id"].astype(str).str.len().gt(0),
        "dam_date_key_unique": ~storage.duplicated(["dam_id", "date"], keep=False),
    }
    ok = pd.concat(checks, axis=1).all(axis=1)
    pd.DataFrame({k: [int(v.sum()), int((~v).sum())] for k, v in checks.items()},
                 index=["pass", "fail"]).T.to_csv(OUT / "K03_storage_contract_checks.csv")
    fl_note = "frictionless not installed: pandas rules only"
    try:
        import frictionless
        spec = json.loads((HERE / "schema" / "storage_contract_v2.json").read_text(encoding="utf-8"))
        sch = {k: v for k, v in spec["schema"].items() if k not in ("uniqueKeys", "foreignKeys")}
        res = frictionless.Resource(path=str(INPUTS["storage"].relative_to(ROOT)), basepath=str(ROOT),
                                    schema=frictionless.Schema.from_descriptor(sch))
        rep = res.validate(limit_errors=1_000_000)
        fl_note = f"frictionless check of the v2 field constraints: valid={rep.valid}, errors={rep.tasks[0].stats.get('errors')}"
    except ImportError:
        pass
    kpi("K03", "A. published package", "Strengthened storage contract", "Compliance",
        "storage rows passing 8 stricter rules / rows", int(ok.sum()), len(storage),
        verdict="NEW", note="rules in schema/storage_contract_v2.json; per-rule counts in K03_storage_contract_checks.csv; " + fl_note)

    # K04 key uniqueness
    dup = int(storage.duplicated(["dam_id", "date"]).sum())
    kpi("K04", "A. published package", "Key uniqueness (dam_id, date)", "Consistency",
        "1 - duplicate keys / rows", len(storage) - dup, len(storage),
        qa_ref="Q18 / C", qa_value=qa_pass_rate(d, "Q18"), verdict="CONFIRMED")

    # K05 source traceability: row hash and file equal the manifest's Page 1 entry for that date
    m = storage.merge(manifest[["bulletin_date", "page1_source_file", "page1_sha256"]],
                      left_on="date", right_on="bulletin_date", how="left")
    traced = m["source_sha256"].eq(m["page1_sha256"]) & m["source_file"].eq(m["page1_source_file"]) \
        & m["lineage_id"].astype(str).str.len().gt(0)
    kpi("K05", "A. published package", "Source traceability of storage rows", "Traceability",
        "rows whose SHA-256 and file equal the manifest Page 1 entry and that carry a lineage id / rows",
        int(traced.sum()), len(storage), verdict="NEW")

    # K06 / K07 completeness split into value capture and source roster coverage
    page1 = d["page1"]
    printed_rows = len(page1)
    blank = int((d["missingness"]["variable"] == "storage").sum())
    kpi("K06", "A. published package", "Value completeness of printed dam rows", "Completeness",
        "numeric storage rows / Page 1 dam rows printed", len(storage), len(storage) + blank,
        verdict="NEW (split from B)",
        note=f"{blank} printed row(s) carry a source blank; Page 1 rows in the staged view: {printed_rows}")
    n_dates = len(p1_dates)
    n_dams = dams["dam_id"].nunique()
    kpi("K07a", "A. published package", "Source roster coverage (publisher side)", "Completeness",
        "dam rows printed / (governed dams x Page 1 bulletin dates)", len(storage) + blank, n_dams * n_dates,
        qa_ref="Q16 / B", qa_value=qa_pass_rate(d, "Q16"), verdict="REFRAMED",
        note="measures what DGBGTH printed (roster growth, dams not yet reported), not an extraction defect")
    sd = storage.assign(date=pd.to_datetime(storage["date"]))
    span = sd.groupby("dam_id")["date"].agg(["min", "max"])
    all_dates = pd.to_datetime(sorted(p1_dates))
    expected_in_era = sum(int(((all_dates >= r["min"]) & (all_dates <= r["max"])).sum()) for _, r in span.iterrows())
    kpi("K07b", "A. published package", "Coverage inside each dam's reporting era", "Completeness",
        "storage rows / Page 1 bulletin dates between the dam's first and last printed row", len(storage), expected_in_era,
        qa_ref="Q17", qa_value=qa_pass_rate(d, "Q17"), verdict="CORRECTED",
        note="Q17 mixed the P1-or-P2 union (129,508) with a calendar-day denominator")

    # K08 temporal-semantic conformance of published date columns with DLO 0.3
    cat = d["catalogue"]
    rule = {(r.source_column, r.p3_grain): r.temporal_rule for r in cat.itertuples()}
    stor_rule = rule[("p1_stock_today_mm3", "")]
    stor_ok = int(len(storage)) if stor_rule == "STATE_AT_BULLETIN_DATE" else 0
    t = d["transfers"]
    grain = np.where(t["row_role"].eq("ACCOUNTING_OBSERVATION"), "TRANSFER_ACCOUNTING_DAY", "TRANSFER_EDGE_DAY")
    t_rule = [rule.get((sf, g), "") for sf, g in zip(t["source_field"], grain)]
    t = t.assign(dlo_rule=t_rule)
    bd = pd.to_datetime(t["bulletin_date"])
    pub = pd.to_datetime(t["date"])
    # the DLO phenomenon time of an amount "for the day before" is the day D-1; a season total is an interval.
    conform = np.select(
        [t["dlo_rule"].eq("DAY_BEFORE_BULLETIN"), t["dlo_rule"].eq("SEASON_TO_DATE"),
         t["dlo_rule"].eq("PREVIOUS_SEASON_TO_DATE_UNRESOLVED")],
        [pub.eq(bd - pd.Timedelta(days=1)), False, np.nan], default=np.nan)
    t = t.assign(date_conforms=conform)
    asserted = t["date_conforms"].notna()
    t_ok = int((t.loc[asserted, "date_conforms"] == 1).sum())
    t.groupby(["variable", "row_role", "dlo_rule", "effective_date_rule"]).agg(
        rows=("date", "size"), conforming=("date_conforms", lambda s: int((s == 1).sum()))
    ).reset_index().to_csv(OUT / "K08_transfer_date_semantics.csv", index=False)
    kpi("K08", "A. published package", "Date columns that match the DLO phenomenon time", "Credibility (semantic)",
        "rows whose published date equals the DLO 0.3 phenomenon time / rows with an asserted rule",
        stor_ok + t_ok, len(storage) + int(asserted.sum()), verdict="NEW",
        note=f"storage {stor_ok}/{len(storage)}; transfers {t_ok}/{int(asserted.sum())} "
             "(published date = bulletin date with rule SAME_DAY; DLO: day D-1 for daily, interval for season totals)")
    return p1_dates


# ----------------------------------------------------------------------------- B. extraction-product consistency
def crosspage_kpis(d):
    p1, p2 = d["page1"], d["page2"]
    pairs = {
        "K09a": ("storage", "storage_current_total_mm3", "storage_current_total_corresponding_p2_mm3", "Q01"),
        "K09b": ("inflow", "inflow_reporting_interval_mm3", "inflow_reporting_interval_p2_mm3", "Q02"),
        "K09c": ("outflow", "outflow_reporting_interval_mm3", "outflow_reporting_interval_p2_mm3", "Q03"),
    }
    m = p1.merge(p2, on=["dam_id", "date"], how="outer", suffixes=("", "_p2dup"))
    rows = []
    for kid, (label, a, b, q) in pairs.items():
        both = m[a].notna() & m[b].notna()
        diff = (m.loc[both, a] - m.loc[both, b]).abs().round(6)
        exact = int((diff == 0).sum())
        close = int(((diff > 0) & (diff <= 0.001 + 1e-9)).sum())
        rows.append({"pair": label, "both_numeric": int(both.sum()), "exact": exact, "within_0.001": close,
                     "different": int(both.sum()) - exact - close,
                     "p1_only_numeric": int((m[a].notna() & m[b].isna()).sum()),
                     "p2_only_numeric": int((m[a].isna() & m[b].notna()).sum())})
        kpi(kid, "B. extraction consistency", f"Page 1 = Page 2 {label} (same dam, same day)", "Consistency",
            "pairs equal at 0.001 Mm3 / pairs where both pages print a number", exact, int(both.sum()),
            qa_ref=q, qa_value=qa_pass_rate(d, q), verdict="CONFIRMED",
            note=f"{close} more pairs within one printed unit; different: {rows[-1]['different']}")
    pd.DataFrame(rows).to_csv(OUT / "K09_cross_page_pairs.csv", index=False)


def counter_kpis(d):
    p1 = d["page1"].copy()
    p1["d"] = pd.to_datetime(p1["date"])
    p1 = p1.sort_values(["dam_id", "d"], kind="mergesort").reset_index(drop=True)
    g = p1.groupby("dam_id", sort=False)
    prev_d = g["d"].shift(1)
    consecutive = (p1["d"] - prev_d).dt.days.eq(1)
    specs = {
        "K10a": ("inflow month-to-date", "inflow_month_to_date_mm3", "inflow_reporting_interval_mm3", "M", "Q04"),
        "K10b": ("outflow month-to-date", "outflow_month_to_date_mm3", "outflow_reporting_interval_mm3", "M", "Q05"),
        "K10c": ("inflow season-to-date", "inflow_hydraulic_year_to_date_mm3", "inflow_reporting_interval_mm3", "S", "Q06"),
        "K10d": ("outflow season-to-date", "outflow_hydraulic_year_to_date_mm3", "outflow_reporting_interval_mm3", "S", "Q07"),
    }
    trace, detail = [], []
    for kid, (label, cum, daily, period, q) in specs.items():
        prev = g[cum].shift(1)
        e = p1[cum] - prev - p1[daily]
        present = p1[cum].notna() & prev.notna() & p1[daily].notna()
        for mode, shift in (("QA_BULLETIN_DATE", 0), ("DLO_DAY_BEFORE", 1)):
            ref = p1["d"] - pd.Timedelta(days=shift)
            ref_prev = prev_d - pd.Timedelta(days=shift)
            if period == "M":
                reset = (ref.dt.year != ref_prev.dt.year) | (ref.dt.month != ref_prev.dt.month)
            else:
                reset = hydro_year(ref) != hydro_year(ref_prev)
            eligible = consecutive & ~reset & present
            ok = eligible & e.abs().le(COUNTER_BOUND + 1e-12) & (p1[cum] - prev).ge(0)
            trace.append({"kpi_id": kid, "series": label, "reset_rule": mode, "eligible": int(eligible.sum()),
                          "pass": int(ok.sum()), "rate": rate(int(ok.sum()), int(eligible.sum())),
                          "negative_steps": int((eligible & (p1[cum] - prev).lt(0)).sum()),
                          "reset_rows_excluded": int((consecutive & reset).sum())})
            if mode == "DLO_DAY_BEFORE":
                bad = eligible & ~ok
                detail.append(p1.loc[bad, ["dam_id", "date", cum, daily]].rename(
                    columns={cum: "cumulative_mm3", daily: "daily_mm3"}).assign(series=label, residual_mm3=e[bad]))
                qa_rate = qa_pass_rate(d, q)
                pair = p1["dam_id"].isin(["ziatine", "gamgoum"])
                extra = ""
                if kid == "K10c":
                    extra = (f"; without the Ziatine/Gamgoum rows (column swap, see K10_ziatine_gamgoum_swap_test.csv): "
                             f"{int((ok & ~pair).sum())}/{int((eligible & ~pair).sum())} = "
                             f"{100 * rate(int((ok & ~pair).sum()), int((eligible & ~pair).sum())):.2f} %")
                kpi(kid, "B. extraction consistency", f"Daily vs {label} counter", "Consistency",
                    "|C_t - C_(t-1) - D_t| <= 0.0015 Mm3 on consecutive days, reset where the day D-1 starts a new period",
                    int(ok.sum()), int(eligible.sum()), qa_ref=q, qa_value=qa_rate, verdict="CORRECTED",
                    note="QA reset the counter on the bulletin date; DLO 0.3 (rules MTD/STD) resets it on the day D-1" + extra)
    pd.DataFrame(trace).to_csv(OUT / "K10_counter_reset_rule_comparison.csv", index=False)
    pd.concat(detail, ignore_index=True).to_csv(OUT / "K10_counter_exceptions.csv", index=False)

    # swapped season-to-date inflow columns between two adjacent Page 1 rows
    c, dl = "inflow_hydraulic_year_to_date_mm3", "inflow_reporting_interval_mm3"
    w = p1[p1["dam_id"].isin(["ziatine", "gamgoum"])].pivot(index="d", columns="dam_id", values=[c, dl]).asfreq("D")
    ref = w.index - pd.Timedelta(days=1)
    season = pd.Series(np.where(ref.month >= 9, ref.year, ref.year - 1), index=w.index)
    same = season.eq(season.shift(1))
    rows = []
    for own, other in (("ziatine", "gamgoum"), ("gamgoum", "ziatine")):
        for col_owner in (own, other):
            r = w[(c, col_owner)] - w[(c, col_owner)].shift(1) - w[(dl, own)]
            ok = (r.abs() <= COUNTER_BOUND) & same & r.notna()
            n = (same & r.notna())
            by_year = (ok.groupby(w.index.year).sum() / n.groupby(w.index.year).sum()).round(3)
            rows.append({"daily_of": own, "season_counter_of": col_owner,
                         **{str(y): v for y, v in by_year.items()}})
    pd.DataFrame(rows).to_csv(OUT / "K10_ziatine_gamgoum_swap_test.csv", index=False)


def fill_kpis(d):
    s = d["storage"][["observation_id", "dam_id", "date", "value"]].rename(columns={"value": "storage_mm3"})
    f = d["printed_fill"][["dam_id", "date", "value", "observation_id"]].rename(
        columns={"value": "printed_fill_pct", "observation_id": "fill_observation_id"})
    lin = d["lineage"]
    raw = lin[lin["source_field"].eq("p1_stock_fill_pct")][["observation_id", "raw_glyph_sequence"]]
    f = f.merge(raw.rename(columns={"observation_id": "fill_observation_id"}), on="fill_observation_id", how="left")
    places = f["raw_glyph_sequence"].astype(str).str.extract(r"[,.](\d+)\s*$")[0].str.len().fillna(0)
    f["fill_half_unit"] = 0.5 * 10.0 ** (-places)

    cap = d["capacity"].copy()
    cap["valid_from"] = pd.to_datetime(cap["valid_from"])
    cap["valid_to"] = pd.to_datetime(cap["valid_to"]).fillna(pd.Timestamp.max)
    x = s.merge(f, on=["dam_id", "date"], how="inner")
    x["d"] = pd.to_datetime(x["date"])
    j = x.merge(cap[["dam_id", "valid_from", "valid_to", "capacity_mm3"]], on="dam_id", how="left")
    j = j[(j["d"] >= j["valid_from"]) & (j["d"] <= j["valid_to"])]
    n_match = j.groupby("observation_id").size()
    known = n_match[n_match == 1].index
    x = x.merge(j[j["observation_id"].isin(known)][["observation_id", "capacity_mm3"]], on="observation_id", how="left")
    el = x[x["capacity_mm3"].notna()].copy()
    v, c, F, h = el["storage_mm3"], el["capacity_mm3"], el["printed_fill_pct"], el["fill_half_unit"]
    el["computed_fill_pct"] = 100 * v / c
    old_ok = (el["computed_fill_pct"] - F).abs() <= h + 1e-12
    lo = 100 * (v - HALF_UNIT) / (c + CAPACITY_HALF_UNIT)
    hi = 100 * (v + HALF_UNIT) / (c - CAPACITY_HALF_UNIT)
    new_ok = (hi >= F - h - 1e-12) & (lo <= F + h + 1e-12)
    el["qa_rule_match"] = old_ok
    el["interval_rule_match"] = new_ok
    el.loc[~new_ok | ~old_ok].to_csv(OUT / "K11_fill_changed_or_failing_rows.csv", index=False)
    kpi("K11", "B. extraction consistency", "Printed fill = storage / useful capacity", "Consistency",
        "printed fill interval intersects [100(V-dV)/(C+dC), 100(V+dV)/(C-dC)] / comparable rows",
        int(new_ok.sum()), len(el), qa_ref="Q10 / E", qa_value=qa_pass_rate(d, "Q10"), verdict="CORRECTED",
        note=f"QA rounding rule (fill only) passes {int(old_ok.sum())}; it ignored the rounding of V (0.0005) and C (0.005)")
    return el


def national_kpi(d, p1_dates):
    s = d["storage"]
    comp = s.groupby("date")["value"].agg(["sum", "count"])
    nat = d["national"][d["national"]["field"].eq("p1_stock_today_mm3")].set_index("bulletin_date")
    j = nat.join(comp, how="left")
    dec = j["printed_decimal_places"].fillna(3).astype(int)
    tol = j["count"].fillna(0) * HALF_UNIT + 0.5 * 10.0 ** (-dec)
    resid = (j["sum"] - j["printed_total_mm3"]).round(6)
    complete = j["completeness"].eq("COMPLETE") & j["printed_total_mm3"].notna() & j["sum"].notna() \
        & j["count"].eq(j["expected_contributors"].astype(float))
    scope = set(d["dispositions"].loc[d["dispositions"]["classification"].eq("SOURCE_ROSTER_SCOPE_DIFFERENCE"), "bulletin_date"])
    eligible = complete & ~j.index.isin(scope)
    ok = eligible & (resid.abs() <= tol + 1e-9)
    j.assign(component_sum=j["sum"], residual_mm3=resid, tolerance_mm3=tol, eligible=eligible, ok=ok) \
        .loc[eligible & ~ok].to_csv(OUT / "K12_national_disagreements.csv")
    kpi("K12", "B. extraction consistency", "National total = sum of dam storage", "Consistency",
        "|sum V_i - T_printed| <= n x 0.0005 + half printed unit / complete bulletins", int(ok.sum()), int(eligible.sum()),
        qa_ref="Q09 / F", qa_value=qa_pass_rate(d, "Q09"), verdict="CONFIRMED",
        note=f"{len(scope)} roster-scope dates excluded as in F")


def physical_kpis(d, fill_rows):
    s = d["storage"]
    valid = np.isfinite(s["value"]) & (s["value"] >= 0)
    kpi("K13", "B. extraction consistency", "Physically possible storage value", "Accuracy (semantic)",
        "finite and non-negative storage / rows", int(valid.sum()), len(s),
        qa_ref="Q11 / D", qa_value=qa_pass_rate(d, "Q11"), verdict="REFRAMED",
        note="storage above useful capacity is possible (flood surcharge, capacity after sedimentation) and is kept as diagnostic D1")
    cap = d["capacity"].copy()
    cap["valid_from"] = pd.to_datetime(cap["valid_from"])
    cap["valid_to"] = pd.to_datetime(cap["valid_to"]).fillna(pd.Timestamp.max)
    x = s.assign(dd=pd.to_datetime(s["date"])).merge(cap, on="dam_id", how="left")
    x = x[(x["dd"] >= x["valid_from"]) & (x["dd"] <= x["valid_to"])]
    x = x[x.groupby("observation_id")["observation_id"].transform("size").eq(1)]
    above = x[x["value"] > x["capacity_mm3"]]
    pf = d["printed_fill"].set_index(["dam_id", "date"])["value"]
    ap = above.join(pf.rename("printed_fill_pct"), on=["dam_id", "date"])
    with_fill = ap["printed_fill_pct"].notna()
    confirmed = int((ap["printed_fill_pct"] >= 100).sum())
    ap.to_csv(OUT / "D1_above_useful_capacity.csv", index=False)
    kpi("D1", "C. diagnostics (not quality scores)", "Storage above useful capacity", "Diagnostic",
        "rows with V > C / rows with a known capacity", len(above), len(x), verdict="DIAGNOSTIC",
        note=f"{confirmed} of {int(with_fill.sum())} such rows with a printed fill show fill >= 100 % in the bulletin itself; "
             f"median excess {100 * (above['value'] / above['capacity_mm3'] - 1).median():.2f} %")


def page3_kpi(d):
    """Recomputed from the published data/transfers table (today vs current_season_to_date)."""
    t = d["transfers"]
    t = t[t["variable"].isin(["today", "current_season_to_date"])].copy()
    t["v"] = pd.to_numeric(t["value"], errors="coerce")
    w = t.pivot_table(index=["entity_id", "bulletin_date"], columns="variable", values="v", aggfunc="first").reset_index()
    w["bd"] = pd.to_datetime(w["bulletin_date"])
    w = w.sort_values(["entity_id", "bd"], kind="mergesort")
    g = w.groupby("entity_id", sort=False)
    w["prev_c"] = g["current_season_to_date"].shift(1)
    w["prev_bd"] = g["bd"].shift(1)
    cons = (w["bd"] - w["prev_bd"]).dt.days.eq(1)
    reset = hydro_year(w["bd"] - pd.Timedelta(days=1)) != hydro_year(w["prev_bd"] - pd.Timedelta(days=1))
    e = w["current_season_to_date"] - w["prev_c"] - w["today"]
    base = cons & e.notna()
    eligible = base & ~reset
    ok = eligible & (e.abs() <= COUNTER_BOUND + 1e-9)
    old_ok = base & (e.abs() <= COUNTER_BOUND + 1e-9)
    w.assign(residual_mm3=e).loc[eligible & ~ok].to_csv(OUT / "K14_page3_exceptions.csv", index=False)
    kpi("K14", "B. extraction consistency", "Page 3 daily vs season total (qualified)", "Consistency",
        "|C_t - C_(t-1) - D_t| <= 0.0015 Mm3, season reset on the day D-1", int(ok.sum()), int(eligible.sum()),
        qa_ref="Q14", qa_value=qa_pass_rate(d, "Q14"), verdict="CORRECTED",
        note=f"without a reset rule this reproduces Q14 exactly ({int(old_ok.sum())}/{int(base.sum())}); "
             f"{int((base & reset).sum())} season-reset rows (bulletin of 2 September) are no longer counted as mismatches")


def diagnostic_kpis(d):
    p1 = d["page1"].copy()
    p1["d"] = pd.to_datetime(p1["date"])
    p1 = p1.sort_values(["dam_id", "d"], kind="mergesort")
    g = p1.groupby("dam_id", sort=False)
    prev_v = g["storage_current_total_mm3"].shift(1)
    cons = (p1["d"] - g["d"].shift(1)).dt.days.eq(1)
    R = p1["storage_current_total_mm3"] - prev_v - p1["inflow_reporting_interval_mm3"] + p1["outflow_reporting_interval_mm3"]
    el = cons & R.notna()
    closed = el & (R.abs() <= BALANCE_BOUND + 1e-9)
    kpi("D2", "C. diagnostics (not quality scores)", "Water balance closes within printed rounding", "Diagnostic",
        "|V_t - V_(t-1) - Q_in + Q_out| <= 0.002 Mm3 / consecutive days", int(closed.sum()), int(el.sum()),
        qa_ref="Q13", qa_value=None, verdict="DIAGNOSTIC",
        note="evaporation, seepage, spill and timing are not printed, so non-closure is expected and is not an error rate")
    ts = d["temporal_summary"]
    kpi("D3", "C. diagnostics (not quality scores)", "Robust storage-change review flags", "Diagnostic",
        "|0.6745 (dV - median) / MAD| >= 6 / comparable daily changes", int(ts["robust_outliers"]),
        int(ts["robust_outliers"]) + int(ts["normal"]), qa_ref="Q12 / H", qa_value=None, verdict="DIAGNOSTIC",
        note=f"carried from the automated QA; {ts['source_review_required_mad_zero']} changes had MAD = 0 and got no score")


def carried_kpis(d):
    k = d["qa_summary"]["kpis"]
    for key, name in (("A1", "Page 1 extraction accuracy (sample)"), ("A2", "Page 2 extraction accuracy (sample)"),
                      ("A3", "Page 3 transcription accuracy (sample)")):
        e = k[key]
        kpi("K15" + "abc"[int(key[-1]) - 1], "B. extraction consistency", name, "Accuracy (syntactic)",
            "matching source cells / verifiable sampled cells (95 % Wilson lower bound in note)",
            int(e["pass"]), int(e["eligible"]), qa_ref=key, qa_value=rate(int(e["pass"]), int(e["eligible"])),
            verdict="CONFIRMED (carried)", note=f"Wilson lower bound {wilson_lower(int(e['pass']), int(e['eligible'])):.4f}; needs the PDFs to recompute")


def metadata_kpis(d):
    pkg = d["datapackage"]
    fields = [f for r in pkg["resources"] if isinstance(r.get("schema"), dict) for f in r["schema"]["fields"]]
    described = sum(bool(str(f.get("description", "")).strip()) for f in fields)
    kpi("K16", "A. published package", "Fields with a description", "Understandability",
        "schema fields with a non-empty description / schema fields", described, len(fields), verdict="NEW")
    lic = [l.get("name", "") for l in pkg.get("licenses", [])]
    cleared = [l for l in lic if not l.upper().startswith("PENDING")]
    kpi("K17", "A. published package", "Licences cleared for publication", "Compliance",
        "licences not marked PENDING / licences", len(cleared), len(lic), verdict="NEW",
        note="publication gate: " + ", ".join(lic))


# ----------------------------------------------------------------------------- DQV export
def write_dqv(results: pd.DataFrame):
    lines = [
        "@prefix dqv: <http://www.w3.org/ns/dqv#> .",
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix kpi: <https://w3id.org/damlevels/kpi/> .",
        "@prefix dld: <https://w3id.org/damlevels/id/> .",
        "",
        "dld:dataset-damlevels-data a dcat:Dataset .",
        "",
    ]
    dims = sorted(set(results["iso25012_dimension"]))
    for dim in dims:
        slug = re.sub(r"[^A-Za-z0-9]+", "", dim.title())
        lines.append(f'kpi:dim-{slug} a dqv:Dimension ; skos:prefLabel "{dim}"@en .')
    lines.append("")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in results.itertuples():
        slug = re.sub(r"[^A-Za-z0-9]+", "", r.iso25012_dimension.title())
        name = r.name.replace('"', "'")
        formula = r.formula.replace('"', "'").replace("\\", "/")
        lines.append(f'kpi:{r.kpi_id} a dqv:Metric ; skos:prefLabel "{name}"@en ; '
                     f'skos:definition "{formula}"@en ; dqv:inDimension kpi:dim-{slug} ; '
                     f'dqv:expectedDataType xsd:decimal .')
        if r.value is not None and not (isinstance(r.value, float) and math.isnan(r.value)):
            lines.append(f'kpi:measurement-{r.kpi_id} a dqv:QualityMeasurement ; dqv:isMeasurementOf kpi:{r.kpi_id} ; '
                         f'dqv:computedOn dld:dataset-damlevels-data ; dqv:value "{float(r.value):.8f}"^^xsd:decimal ; '
                         f'prov:generatedAtTime "{now}"^^xsd:dateTime .')
    (OUT / "KPI_DQV.ttl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- main
def main() -> int:
    OUT.mkdir(exist_ok=True)
    d = load()
    p1_dates = package_kpis(d)
    crosspage_kpis(d)
    counter_kpis(d)
    fill_rows = fill_kpis(d)
    national_kpi(d, p1_dates)
    physical_kpis(d, fill_rows)
    page3_kpi(d)
    carried_kpis(d)
    metadata_kpis(d)
    diagnostic_kpis(d)

    res = pd.DataFrame(RESULTS)
    res["value_pct"] = (100 * res["value"].astype(float)).round(4)
    res["automated_qa_pct"] = (100 * pd.to_numeric(res["automated_qa_value"], errors="coerce")).round(4)
    res["change_pct_points"] = (res["value_pct"] - res["automated_qa_pct"]).round(4)
    res.to_csv(OUT / "KPI_RESULTS.csv", index=False, encoding="utf-8")
    cmp_cols = ["kpi_id", "name", "automated_qa_ref", "automated_qa_pct", "value_pct", "change_pct_points", "verdict", "note"]
    res[res["automated_qa_ref"].ne("")][cmp_cols].to_csv(OUT / "KPI_VS_AUTOMATED_QA.csv", index=False, encoding="utf-8")
    write_dqv(res)

    receipt = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        "inputs": {k: {"path": str(v.relative_to(ROOT)) if ROOT in v.parents else str(v), "sha256": sha256(v)}
                   for k, v in INPUTS.items()},
        "inputs_modified": False, "writes_only_to": str(OUT.relative_to(ROOT)),
        "kpis": len(res),
    }
    (OUT / "RUN_RECEIPT.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(res[["kpi_id", "name", "numerator", "denominator", "value_pct", "automated_qa_pct", "verdict"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

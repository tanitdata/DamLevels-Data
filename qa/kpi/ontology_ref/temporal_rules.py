"""Temporal support rules: from the bulletin date D (printed 'observée le D') to a phenomenon time.

Single source of truth used by both the ontology builder (documentation, alignments) and the
converter (computation). Every rule cites the corpus tests that fix it (analysis/SEMANTIC_HYPOTHESIS_TESTS.csv).

Conventions
- Dates are local calendar dates (Africa/Tunis). No clock time is asserted.
- An instant is known only to its day (the daily reading of that day).
- An interval runs from the instant of its first day to the instant of the day after its last day, so that
  consecutive intervals meet and the day-before amount of bulletin D ends at the state instant of D:
  ('P', first_day, end_day_exclusive).
- hy(x) = the hydrological year (season) containing day x, identified by the year of its 1 September.
- R(D) = the reference date one year earlier used by the previous-year columns of bulletin D. It is the same
  calendar date, except in dated periods around leap years where the publisher used the same day of the year
  (+-1 day). R(D) is read from analysis/PREVIOUS_YEAR_REFERENCE_CALENDAR.csv (test H02c).
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

ODM2 = "http://vocabulary.odm2.org/aggregationstatistic/"
WML = "http://www.opengis.net/def/waterml/2.0/interpolationType/"


def hy(x: dt.date) -> int:
    return x.year if x.month >= 9 else x.year - 1


def minus_years(d: dt.date, n: int = 1) -> dt.date:
    try:
        return d.replace(year=d.year - n)
    except ValueError:                      # 29 February -> 28 February (same as pandas DateOffset)
        return d.replace(year=d.year - n, day=28)


def next_month_start(d: dt.date) -> dt.date:
    nxt = d.replace(day=28) + dt.timedelta(days=4)
    return nxt.replace(day=1)


ONE = dt.timedelta(days=1)
CALENDAR = Path(__file__).resolve().parents[1] / "analysis/PREVIOUS_YEAR_REFERENCE_CALENDAR.csv"
_REF: dict | None = None


def reference_date(D: dt.date) -> dt.date:
    """R(D): the tested per-bulletin reference date, or the same calendar date one year earlier when untested."""
    global _REF
    if _REF is None:
        _REF = {}
        if CALENDAR.exists():
            with open(CALENDAR, newline="") as f:
                for r in csv.DictReader(f):
                    _REF[dt.date.fromisoformat(r["bulletin_date"])] = dt.date.fromisoformat(r["reference_date"])
    return _REF.get(D, minus_years(D))

# notation: (label, definition, time pattern, ODM2 aggregation statistic, WaterML 2.0 interpolation type, CF cell_methods, tests)
RULES = {
    "STATE_AT_BULLETIN_DATE": (
        "state at the bulletin date",
        "A state (volume, level, fill, remaining volume) that holds on the bulletin date D.",
        "instant(D)", "continuous", "Continuous", "time: point", "H01;H23;H23b"),
    "DAY_BEFORE_BULLETIN": (
        "amount over the day before the bulletin",
        "An amount (inflow, release, withdrawal, transfer, evaporation, rain) accumulated over the reporting day D-1, which ends at the reading of day D. The Page 1 header 'du D-1 observée le D' prints this day.",
        "interval(D-1 .. D)", "incremental", "TotalPrec", "time: sum", "H01;H06;H07;H08;H09;H23;H23b"),
    "MONTH_TO_DATE": (
        "running total since the start of the month",
        "An amount accumulated from the first day of the month of D-1 to D-1 inclusive.",
        "interval(first-of-month(D-1) .. D)", "cumulative", "InstantTotal", "time: sum", "H06;H08"),
    "SEASON_TO_DATE": (
        "running total since 1 September",
        "An amount accumulated from 1 September of the hydrological year of D-1 to D-1 inclusive.",
        "interval(01-09-hy(D-1) .. D)", "cumulative", "InstantTotal", "time: sum", "H07;H09"),
    "PREVIOUS_YEAR_SAME_DATE_STATE": (
        "state on the same date one year earlier",
        "The same state variable at the reference date R(D) one year before D: the same calendar date, or the same day of the year (+-1 day) in dated periods around leap years (per-bulletin calendar, test H02c).",
        "instant(R(D))", "continuous", "Continuous", "time: point", "H02;H02c"),
    "PREVIOUS_YEAR_SAME_DAY": (
        "amount over the same day one year earlier",
        "The same daily amount for the day before R(D), i.e. the daily amount printed on the reference bulletin one year earlier.",
        "interval(R(D)-1 .. R(D))", "incremental", "TotalPrec", "time: sum", "H03;H03c;H13;H23b"),
    "PREVIOUS_YEAR_SEASON_TO_DATE": (
        "running season total one year earlier",
        "The season-to-date total as it stood on the reference bulletin one year earlier: from 1 September of hy(R(D)-1) to R(D)-1.",
        "interval(01-09-hy(R(D)-1) .. R(D))", "cumulative", "InstantTotal", "time: sum", "H04;H04c;H05;H05c"),
    "END_OF_PREVIOUS_HYDROLOGICAL_YEAR_STATE": (
        "state at the close of the previous hydrological year",
        "A state read on the 1 September bulletin that opened the current season, i.e. at 1 September of hy(D-1). Reprinted unchanged all season.",
        "instant(01-09-hy(D-1))", "continuous", "Continuous", "time: point", "H18;H19"),
    "PREVIOUS_FULL_HYDROLOGICAL_YEAR": (
        "total over the previous hydrological year",
        "An amount over the whole previous season, 1 September of hy(D-1)-1 to 31 August of hy(D-1), as printed on the 1 September bulletin.",
        "interval(01-09-(hy(D-1)-1) .. 01-09-hy(D-1))", "incremental", "TotalPrec", "time: sum", "H20;H21"),
    "LONG_TERM_MONTH_REFERENCE": (
        "long-term mean for the calendar month",
        "A climatological mean of the monthly total for the month of D-1. The phenomenon time is the representative month; the averaging years are unknown and carried by the statistical modifier.",
        "interval(first-of-month(D-1) .. first-of-next-month)", "average", "TotalPrec", "time: sum within years time: mean over years", "H17"),
    "LONG_TERM_SEASON_TO_DATE_REFERENCE": (
        "long-term mean of the season-to-date total",
        "A climatological mean of the season-to-date total for the same span 1 September to D-1. The phenomenon time is the representative span; averaging years unknown.",
        "interval(01-09-hy(D-1) .. D)", "average", "InstantTotal", "time: sum within years time: mean over years", "H16;H16b"),
    "MULTI_YEAR_SAME_DAY_REFERENCE": (
        "mean of the same date over the three previous years",
        "The mean of a state at the same calendar date in the three previous years (Page 3). The phenomenon time is the representative date D.",
        "instant(D)", "average", "Continuous", "time: point within years time: mean over years", "H27d"),
    "MULTI_YEAR_SEASON_TO_DATE_REFERENCE": (
        "mean season-to-date total over the three previous years",
        "The mean of the season-to-date total for the same span in the three previous years (Page 3 T3, printed until 2015-10-01). The phenomenon time is the representative span.",
        "interval(01-09-hy(D-1) .. D)", "average", "InstantTotal", "time: sum within years time: mean over years", "H27c"),
    "LONG_TERM_STATIC": (
        "static attribute reprinted unchanged",
        "A design or long-term attribute reprinted on every bulletin. One observation per run of identical values; the phenomenon time is the span of bulletins that printed it.",
        "interval(first D of run .. day after last D of run)", "constantOverInterval", "ConstPrec", "", "PATCH_01"),
    "REGIME_VALUE_AS_PRINTED": (
        "value in force for a regime",
        "A value that holds until the operator reprints a new one (capacities, sedimentation from surveys). One observation per run of identical values; the phenomenon time is the span of bulletins that printed it.",
        "interval(first D of run .. day after last D of run)", "constantOverInterval", "ConstPrec", "", "ADR-011"),
    "PREVIOUS_SEASON_TO_DATE_UNRESOLVED": (
        "previous-season running total (time unresolved)",
        "A running total for the previous season whose exact span is not established (Page 1 and Page 3 print different values). No phenomenon time is asserted.",
        "none", "cumulative", "InstantTotal", "time: sum", ""),
}

RUN_LENGTH_RULES = {"LONG_TERM_STATIC", "REGIME_VALUE_AS_PRINTED", "END_OF_PREVIOUS_HYDROLOGICAL_YEAR_STATE",
                    "PREVIOUS_FULL_HYDROLOGICAL_YEAR"}


def camel(notation: str) -> str:
    return "".join(w.capitalize() for w in notation.split("_"))


def phenomenon_time(rule: str, D: dt.date, run_last: dt.date | None = None):
    """Return ('I', day) for an instant, ('P', first_day, end_day_exclusive) for an interval, or None."""
    Dm1 = D - ONE
    if rule in ("STATE_AT_BULLETIN_DATE", "MULTI_YEAR_SAME_DAY_REFERENCE"):
        return ("I", D)
    if rule == "DAY_BEFORE_BULLETIN":
        return ("P", Dm1, D)
    if rule == "MONTH_TO_DATE":
        return ("P", Dm1.replace(day=1), D)
    if rule in ("SEASON_TO_DATE", "LONG_TERM_SEASON_TO_DATE_REFERENCE", "MULTI_YEAR_SEASON_TO_DATE_REFERENCE"):
        return ("P", dt.date(hy(Dm1), 9, 1), D)
    if rule == "PREVIOUS_YEAR_SAME_DATE_STATE":
        return ("I", reference_date(D))
    if rule == "PREVIOUS_YEAR_SAME_DAY":
        R = reference_date(D)
        return ("P", R - ONE, R)
    if rule == "PREVIOUS_YEAR_SEASON_TO_DATE":
        R = reference_date(D)
        return ("P", dt.date(hy(R - ONE), 9, 1), R)
    if rule == "END_OF_PREVIOUS_HYDROLOGICAL_YEAR_STATE":
        return ("I", dt.date(hy(Dm1), 9, 1))
    if rule == "PREVIOUS_FULL_HYDROLOGICAL_YEAR":
        h = hy(Dm1)
        return ("P", dt.date(h - 1, 9, 1), dt.date(h, 9, 1))
    if rule == "LONG_TERM_MONTH_REFERENCE":
        return ("P", Dm1.replace(day=1), next_month_start(Dm1))
    if rule in ("LONG_TERM_STATIC", "REGIME_VALUE_AS_PRINTED"):
        return ("P", D, (run_last or D) + ONE)
    if rule == "PREVIOUS_SEASON_TO_DATE_UNRESOLVED":
        return None
    raise KeyError(f"unknown temporal rule {rule!r}")


def run_key(rule: str, D: dt.date):
    """Values under these rules are constant within this key; a run never crosses a key change."""
    if rule in ("END_OF_PREVIOUS_HYDROLOGICAL_YEAR_STATE", "PREVIOUS_FULL_HYDROLOGICAL_YEAR"):
        return hy(D - ONE)
    return 0


if __name__ == "__main__":                 # self-test on hand-checked dates
    d = dt.date
    assert phenomenon_time("DAY_BEFORE_BULLETIN", d(2020, 3, 1)) == ("P", d(2020, 2, 29), d(2020, 3, 1))
    assert phenomenon_time("MONTH_TO_DATE", d(2020, 3, 1)) == ("P", d(2020, 2, 1), d(2020, 3, 1))
    assert phenomenon_time("SEASON_TO_DATE", d(2020, 9, 1)) == ("P", d(2019, 9, 1), d(2020, 9, 1))
    assert phenomenon_time("SEASON_TO_DATE", d(2020, 9, 2)) == ("P", d(2020, 9, 1), d(2020, 9, 2))
    assert phenomenon_time("END_OF_PREVIOUS_HYDROLOGICAL_YEAR_STATE", d(2020, 9, 1)) == ("I", d(2019, 9, 1))
    assert phenomenon_time("END_OF_PREVIOUS_HYDROLOGICAL_YEAR_STATE", d(2020, 9, 2)) == ("I", d(2020, 9, 1))
    assert phenomenon_time("PREVIOUS_FULL_HYDROLOGICAL_YEAR", d(2021, 1, 5)) == ("P", d(2019, 9, 1), d(2020, 9, 1))
    assert phenomenon_time("LONG_TERM_MONTH_REFERENCE", d(2021, 3, 1)) == ("P", d(2021, 2, 1), d(2021, 3, 1))
    assert phenomenon_time("LONG_TERM_STATIC", d(2021, 3, 1), run_last=d(2021, 3, 1)) == ("P", d(2021, 3, 1), d(2021, 3, 2))
    # the publisher's reference date (test H02c): same day of the year around leap years
    assert reference_date(d(2019, 5, 10)) == d(2018, 5, 10)
    assert reference_date(d(2020, 2, 29)) == d(2019, 3, 1), reference_date(d(2020, 2, 29))
    assert reference_date(d(2017, 5, 1)) == d(2016, 4, 30), reference_date(d(2017, 5, 1))
    assert phenomenon_time("PREVIOUS_YEAR_SAME_DAY", d(2019, 5, 10)) == ("P", d(2018, 5, 9), d(2018, 5, 10))
    assert phenomenon_time("PREVIOUS_YEAR_SEASON_TO_DATE", d(2021, 9, 2)) == ("P", d(2020, 9, 1), d(2020, 9, 2))
    for rule in RULES:
        spec = phenomenon_time(rule, d(2024, 2, 29), run_last=d(2024, 3, 5))
        assert spec is None or spec[0] == "I" or spec[1] < spec[2], (rule, spec)   # proper intervals only
    print(len(RULES), "rules; self-test passed")

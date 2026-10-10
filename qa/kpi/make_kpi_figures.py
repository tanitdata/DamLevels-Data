"""Figures for the open-data KPIs (report Section 9.8).

Run after run_kpis.py:
    python make_kpi_figures.py

Reads results/KPI_RESULTS.csv and the same inputs as run_kpis.py.
Writes PDF (for LaTeX) and PNG copies to results/figures/. Nothing else is written.
Requires matplotlib in addition to the run_kpis.py requirements.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, PercentFormatter

import run_kpis as rk

FIG = rk.OUT / "figures"

# palette: categorical slots 1-2 of the validated reference palette (light), plus neutral inks
BLUE = "#2a78d6"      # recomputed with the DLO rules
ORANGE = "#eb6834"    # highlighted cases
OLD = "#a8a6a0"       # earlier automated QA (de-emphasised)
LIGHT = "#dcdad4"     # neutral fill
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e6e5e1"
SURFACE = "#ffffff"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": GRID, "axes.linewidth": 0.8,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.grid": False, "savefig.dpi": 300, "pdf.fonttype": 42, "legend.frameon": False,
})


def style_axes(ax, grid_axis="x"):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(FIG / f"{name}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def pct_label(v: float) -> str:
    """Two decimals, but never print 100.00 for a value below 100."""
    if v >= 100:
        return "100"
    txt = f"{v:.2f}"
    return txt if txt != "100.00" else f"{np.floor(v * 1000) / 1000:.3f}"


# ----------------------------------------------------------------------------- 1. overview
def fig_overview(res: pd.DataFrame):
    rows = [
        ("K04", "Unique (dam_id, date) key"),
        ("K07b", "Coverage in each dam's reporting era"),
        ("K09a", "Page 1 = Page 2 storage"),
        ("K09b", "Page 1 = Page 2 inflow"),
        ("K09c", "Page 1 = Page 2 outflow"),
        ("K10a", "Daily vs month-to-date inflow"),
        ("K10b", "Daily vs month-to-date outflow"),
        ("K10c", "Daily vs season-to-date inflow"),
        ("K10d", "Daily vs season-to-date outflow"),
        ("K11", "Printed fill vs storage / capacity"),
        ("K12", "National total vs sum of dams"),
        ("K13", "Physically possible storage"),
        ("K14", "Page 3 daily vs season total"),
    ]
    r = res.set_index("kpi_id")
    fig, ax = plt.subplots(figsize=(6.3, 4.1))
    y = np.arange(len(rows))[::-1]
    for yi, (kid, label) in zip(y, rows):
        new, old = r.loc[kid, "value_pct"], r.loc[kid, "automated_qa_pct"]
        ax.plot([old, new], [yi, yi], color=LIGHT, linewidth=2, solid_capstyle="round", zorder=1)
        ax.scatter(old, yi, s=42, color=OLD, edgecolor=SURFACE, linewidth=1.5, zorder=2)
        ax.scatter(new, yi, s=42, color=BLUE, edgecolor=SURFACE, linewidth=1.5, zorder=3)
        ax.text(100.25, yi, pct_label(new), va="center", ha="left", fontsize=7.6, color=INK)
        if abs(new - old) >= 0.2:
            ax.text(old - 0.12, yi, pct_label(old), va="center", ha="right", fontsize=7.2, color=INK2)
    ax.set_yticks(y, [f"{k}  {lab}" for k, lab in rows])
    ax.set_xlim(91.5, 100.9)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f} %"))
    ax.set_xlabel("share of eligible records that pass the check")
    style_axes(ax, "x")
    ax.scatter([], [], s=42, color=OLD, label="earlier automated QA")
    ax.scatter([], [], s=42, color=BLUE, label="recomputed with the DLO 0.3 rules")
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2, fontsize=7.8, handletextpad=0.3)
    save(fig, "fig_kpi_overview")


# ----------------------------------------------------------------------------- 2. reset day
def fig_reset_day(d):
    p1 = d["page1"].copy()
    p1["d"] = pd.to_datetime(p1["date"])
    p1 = p1.sort_values(["dam_id", "d"], kind="mergesort").reset_index(drop=True)
    g = p1.groupby("dam_id", sort=False)
    prev_d = g["d"].shift(1)
    cum, daily = "inflow_month_to_date_mm3", "inflow_reporting_interval_mm3"
    prev = g[cum].shift(1)
    e = p1[cum] - prev - p1[daily]
    present = p1[cum].notna() & prev.notna() & p1[daily].notna()
    cons = (p1["d"] - prev_d).dt.days.eq(1)
    day = p1["d"].dt.day
    out = {}
    for mode, shift in (("qa", 0), ("dlo", 1)):
        ref, refp = p1["d"] - pd.Timedelta(days=shift), prev_d - pd.Timedelta(days=shift)
        reset = (ref.dt.year != refp.dt.year) | (ref.dt.month != refp.dt.month)
        el = cons & ~reset & present
        fail = el & ~(e.abs().le(rk.COUNTER_BOUND + 1e-12) & (p1[cum] - prev).ge(0))
        out[mode] = fail.groupby(day).sum().reindex(range(1, 32), fill_value=0)
        out[mode + "_excluded"] = (cons & reset).groupby(day).sum().reindex(range(1, 32), fill_value=0)
    fig, axes = plt.subplots(2, 1, figsize=(6.3, 3.5), sharex=True, sharey=True)
    for ax, mode, title in ((axes[0], "qa", "earlier QA: counter reset on the bulletin date"),
                            (axes[1], "dlo", "DLO 0.3: counter reset on the day D−1")):
        vals = out[mode]
        colors = [ORANGE if v > 1000 else (OLD if mode == "qa" else BLUE) for v in vals]
        ax.bar(vals.index, vals.values, width=0.72, color=colors, zorder=2)
        excl = out[mode + "_excluded"]
        xd = int(excl.idxmax())
        ax.text(0.99, 0.92, title, transform=ax.transAxes, ha="right", va="top", fontsize=8, color=INK)
        ax.text(0.99, 0.72, f"excluded as a reset: bulletins of day {xd} ({int(excl.max()):,})",
                transform=ax.transAxes, ha="right", va="top", fontsize=7.2, color=INK2)
        big = vals[vals > 1000]
        for dd, v in big.items():
            ax.text(dd + 0.6, v * 0.92, f"{int(v):,} failures on the bulletin of the 2nd:\nthe real month reset",
                    fontsize=7.2, color=INK, va="top")
        ax.text(0.99, 0.52, f"failing checks: {int(vals.sum()):,}", transform=ax.transAxes, ha="right",
                va="top", fontsize=7.2, color=INK2)
        style_axes(ax, "y")
        ax.set_ylabel("failing checks")
    axes[1].set_xlabel("day of the month of the bulletin date D")
    axes[1].set_xticks([1, 2, 5, 10, 15, 20, 25, 31])
    axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    fig.tight_layout(h_pad=0.8)
    save(fig, "fig_kpi_counter_reset")


# ----------------------------------------------------------------------------- 3. fill residual
def fig_fill(d):
    el = rk.fill_kpis(d)  # same computation as K11 (rewrites the identical K11 exception file)
    resid = el["computed_fill_pct"] - el["printed_fill_pct"]
    h = el["fill_half_unit"]
    bins = np.arange(-0.16, 0.1601, 0.005)
    fig, ax = plt.subplots(figsize=(6.3, 2.9))
    inside = resid.abs() <= h + 1e-12
    rescued = int((~inside & el["interval_rule_match"]).sum())
    ax.hist([resid[inside].clip(-0.1599, 0.1599), resid[~inside].clip(-0.1599, 0.1599)], bins=bins, stacked=True,
            color=[BLUE, ORANGE], rwidth=0.9, zorder=2,
            label=[f"inside the earlier tolerance \u00b1h ({int(inside.sum()):,})",
                   f"outside it ({int((~inside).sum()):,}); {rescued:,} of them fit once V and C rounding is included"])
    ax.set_yscale("log")
    ax.axvline(-0.05, color=INK2, linewidth=0.8)
    ax.axvline(0.05, color=INK2, linewidth=0.8)
    ax.set_xlabel("computed minus printed fill, 100 V/C − F (percentage points)")
    ax.set_ylabel("comparable rows (log scale)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    style_axes(ax, "y")
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=7.6)
    save(fig, "fig_kpi_fill_residual")


# ----------------------------------------------------------------------------- 4. source swap
def fig_swap():
    s = pd.read_csv(rk.OUT / "K10_ziatine_gamgoum_swap_test.csv")
    zi = s[s["daily_of"].eq("ziatine")].set_index("season_counter_of").drop(columns="daily_of")
    years = [int(c) for c in zi.columns]
    fig, ax = plt.subplots(figsize=(6.3, 2.8))
    for owner, color, label in (("ziatine", BLUE, "Ziatine daily inflow vs Ziatine's printed season total"),
                                ("gamgoum", ORANGE, "Ziatine daily inflow vs Gamgoum's printed season total")):
        vals = 100 * zi.loc[owner].astype(float).values
        ax.plot(years, vals, color=color, linewidth=2, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=label, zorder=3)
    ax.axvspan(2016.6, 2021.4, color=GRID, zorder=0)
    ax.text(2019, 50, "values printed in each\nother's row (2017 to 2021)", ha="center", va="center",
            fontsize=7.6, color=INK2)
    ax.set_ylim(-5, 105)
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_xticks(years)
    ax.set_ylabel("daily checks that pass")
    style_axes(ax, "y")
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=7.6)
    save(fig, "fig_kpi_swap")


# ----------------------------------------------------------------------------- 5. completeness
def fig_completeness(d):
    s = d["storage"]
    dates = pd.to_datetime(sorted(set(d["manifest"].loc[d["manifest"]["page1_sha256"].notna(), "bulletin_date"])))
    names = d["dams"].set_index("dam_id")["name_fr"]
    rows = []
    for dam, grp in s.groupby("dam_id"):
        ds = pd.to_datetime(grp["date"])
        first, last = ds.min(), ds.max()
        in_era = int(((dates >= first) & (dates <= last)).sum())
        rows.append({"dam": names.get(dam, dam), "printed": len(grp), "gap_in_era": in_era - len(grp),
                     "outside_era": len(dates) - in_era})
    t = pd.DataFrame(rows).sort_values(["outside_era", "dam"], ascending=[True, True]).reset_index(drop=True)
    n = len(dates)
    fig, ax = plt.subplots(figsize=(6.3, 5.2))
    y = np.arange(len(t))[::-1]
    left = np.zeros(len(t))
    gaps = int(t["gap_in_era"].sum())
    for col, color, label in (("printed", BLUE, "storage value published"),
                              ("gap_in_era", ORANGE, f"missing inside the dam's reporting era ({gaps} dates in total)"),
                              ("outside_era", LIGHT, "dam not yet (or no longer) in the bulletin")):
        w = 100 * t[col].values / n
        ax.barh(y, w, left=left, height=0.62, color=color, label=label, edgecolor=SURFACE, linewidth=0.6, zorder=2)
        left += w
    for yi, row in zip(y, t.itertuples()):
        if row.outside_era:
            ax.text(100 * row.printed / n + 1, yi, f"{100 * row.printed / n:.0f} %", va="center", ha="left",
                    fontsize=6.8, color=INK)
    ax.set_yticks(y, t["dam"])
    ax.tick_params(axis="y", labelsize=7)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_xlabel(f"share of the {n:,} Page 1 bulletin dates")
    style_axes(ax, "x")
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=1, fontsize=7.6)
    save(fig, "fig_kpi_completeness")


def main():
    res = pd.read_csv(rk.OUT / "KPI_RESULTS.csv")
    d = rk.load()
    fig_overview(res)
    fig_reset_day(d)
    fig_fill(d)
    fig_swap()
    fig_completeness(d)
    print("figures written to", FIG)


if __name__ == "__main__":
    main()

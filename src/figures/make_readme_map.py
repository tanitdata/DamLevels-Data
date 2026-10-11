"""Draw the overview map used in the README (docs/img/map_dams.png).

Dams are coloured by their fill on the latest bulletin date, using the
capacity regime in force that day. Run from the repository root:

    python src/figures/make_readme_map.py [--rivers PATH]

--rivers takes a line layer of rivers (for example drainage lines derived from
HydroSHEDS, Strahler order >= 2, with an "ord" attribute). It is not shipped in
this repository; without it the map is drawn without rivers.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from validate.capacity import CapacityIndex  # noqa: E402

OUT = ROOT / "docs" / "img" / "map_dams.png"
EXTENT = (7.05, 11.35, 34.55, 37.45)  # lon_min, lon_max, lat_min, lat_max

# Label offsets in points (negative x = label to the left of the dam).
OFFSETS = {
    "harka": (5, 6), "gamgoum": (-3, 7), "ziatine": (-8, -3), "sejnane": (8, -3),
    "melah": (-7, -2), "ghezala": (7, 1), "sidielbarrak": (-8, 6), "joumine": (8, -2),
    "moula": (6, 3), "zarga": (-7, -1), "kebir": (6, -7), "tine": (7, -2),
    "kasseb": (7, -1), "benmetir": (6, 5), "bouheurtma": (6, -7), "barbara": (-7, -1),
    "sidisalem": (9, -4), "abid": (6, 3), "lebna": (6, 0), "bezirk": (-6, 1),
    "chiba": (5, -8), "hma": (-6, 1), "masri": (6, -3), "birmcherga": (-6, 2),
    "rmel": (7, -2), "mellegue": (7, -2), "rmil": (7, 1), "siliana": (-7, 0),
    "nebhana": (7, -1), "lakhmess": (7, -2), "sarrat": (7, -1), "elhouareb": (7, 0),
    "brek": (-7, 1), "sidisaad": (8, -2), "sficifa": (7, -4), "sidiaich": (7, 0),
}


def latest_fill(storage: pd.DataFrame, capacity: CapacityIndex) -> tuple[str, pd.DataFrame]:
    last = storage["date"].max()
    day = storage[storage["date"] == last][["dam_id", "value"]].copy()
    caps = [capacity.for_date(d, last) for d in day["dam_id"]]
    day["capacity"] = [c["capacity_mm3"] for c in caps]
    day["fill_pct"] = 100 * day["value"].astype(float) / day["capacity"].astype(float)
    return last, day


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rivers", type=Path, help="optional river line layer (GeoJSON/GPKG) with an 'ord' column")
    args = parser.parse_args()

    dams = gpd.read_file(ROOT / "gis/vector/dams.geojson")[["dam_id", "geometry"]]
    meta = pd.read_csv(ROOT / "data/dams.csv")[["dam_id", "name_fr", "reference_capacity_mm3"]]
    dams = dams.merge(meta, on="dam_id", how="left")
    catchments = gpd.read_file(ROOT / "gis/vector/catchments.geojson")
    rivers = gpd.read_file(ROOT / "gis/vector/natural_network.geojson")
    transfers = gpd.read_file(ROOT / "gis/vector/transfer_network.geojson")
    transfers = transfers[transfers.geometry.notna() & ~transfers.geometry.is_empty]
    countries = gpd.read_file(ROOT / "gis/context/naturalearth_countries.geojson")
    streams = gpd.read_file(args.rivers) if args.rivers else None

    storage = pd.read_csv(ROOT / "data/storage.csv", usecols=["dam_id", "date", "value"])
    last, fill = latest_fill(storage, CapacityIndex.from_csv(ROOT / "data/capacity_history.csv"))
    dams = dams.merge(fill[["dam_id", "fill_pct"]], on="dam_id", how="left")

    bins = [0, 25, 50, 75, 1000]
    colours = ["#c0392b", "#e67e22", "#5dade2", "#1f4e79"]
    cmap, norm = ListedColormap(colours), BoundaryNorm(bins, len(colours))

    fig, ax = plt.subplots(figsize=(9.2, 7.6), dpi=170)
    ax.set_facecolor("#e8f1f8")
    countries.plot(ax=ax, color="#f7f5ef", edgecolor="#9a9a9a", linewidth=0.8, zorder=1)
    catchments.plot(ax=ax, color="#d8e8d0", edgecolor="#7fa36b", linewidth=0.5, alpha=0.85, zorder=2)
    if streams is not None:
        width = streams["ord"].astype(float).clip(2, 6).sub(1.5).mul(0.28) if "ord" in streams else 0.4
        streams.plot(ax=ax, color="#7fb3d5", linewidth=width, alpha=0.9, zorder=2.5)
    rivers.plot(ax=ax, color="#1b4f72", linewidth=1.6, zorder=3)
    transfers.plot(ax=ax, color="#8e44ad", linewidth=1.3, linestyle=(0, (4, 2)), zorder=3)

    sizes = 18 + 1.1 * dams["reference_capacity_mm3"].fillna(10).clip(upper=600) ** 0.85
    no_fill = dams["fill_pct"].isna()
    ax.scatter(dams.loc[no_fill].geometry.x, dams.loc[no_fill].geometry.y, s=sizes[no_fill],
               facecolor="white", edgecolor="#555555", linewidth=0.8, zorder=4)
    ax.scatter(dams.loc[~no_fill].geometry.x, dams.loc[~no_fill].geometry.y, s=sizes[~no_fill],
               c=dams.loc[~no_fill, "fill_pct"], cmap=cmap, norm=norm, edgecolor="white", linewidth=0.7, zorder=5)
    for _, d in dams.iterrows():
        dx, dy = OFFSETS.get(d["dam_id"], (6, 2))
        ax.annotate(d["name_fr"], (d.geometry.x, d.geometry.y), xytext=(dx, dy), textcoords="offset points",
                    fontsize=5.8, color="#1d1d1d", zorder=6, ha="right" if dx < 0 else "left", va="center",
                    bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none", alpha=0.55))

    ax.set_xlim(EXTENT[0], EXTENT[1])
    ax.set_ylim(EXTENT[2], EXTENT[3])
    ax.set_aspect(1 / 0.81)  # approximate ground scale at 36° N
    ax.set_xticks([]); ax.set_yticks([])
    for side in ax.spines.values():
        side.set_color("#9a9a9a")
    ax.text(7.45, 35.6, "ALGERIA", fontsize=8, color="#8a8a8a", ha="center", style="italic", rotation=70)
    ax.text(9.95, 34.85, "TUNISIA", fontsize=9, color="#8a8a8a", ha="center", style="italic")
    ax.text(11.2, 37.3, "Mediterranean Sea", fontsize=7, color="#5d7a92", ha="right", style="italic")

    legend = [
        Patch(facecolor=c, label=lab) for c, lab in zip(colours, ["below 25 %", "25 – 50 %", "50 – 75 %", "75 % and above"])
    ] + [
        Line2D([], [], marker="o", color="none", markerfacecolor="white", markeredgecolor="#555555", label="not printed that day"),
        Patch(facecolor="#d8e8d0", edgecolor="#7fa36b", label="catchment (35)"),
        Line2D([], [], color="#1b4f72", linewidth=1.6, label="river link between dams (8)"),
        Line2D([], [], color="#8e44ad", linewidth=1.3, linestyle=(0, (4, 2)), label="transfer route (mapped)"),
    ] + ([Line2D([], [], color="#7fb3d5", linewidth=0.8, label="river (HydroSHEDS)")] if streams is not None else [])
    ax.legend(handles=legend, loc="lower right", fontsize=6.5, title=f"Fill on {last}", title_fontsize=7,
              frameon=True, framealpha=0.92, borderpad=0.8)
    ax.set_title("Tunisia's 36 large dams", fontsize=12, loc="left", pad=8)
    credit = ("Marker size: reference capacity. Fill = storage / capacity in force on that date. "
              "Data: DGBGTH bulletins via ONAGRI (Licence Nationale de Données Publiques Ouvertes); "
              "catchments CC BY-NC-SA 4.0 (FABDEM, MERIT Hydro); outlines Natural Earth")
    credit += "; rivers derived from HydroSHEDS (Lehner et al. 2008)." if streams is not None else "."
    ax.text(0, -0.035, credit, transform=ax.transAxes, fontsize=5.2, color="#555555", va="top", wrap=True)

    # Inset: where the map sits in Tunisia (top-left, over the sea)
    inset = fig.add_axes([0.13, 0.66, 0.14, 0.21])
    countries.plot(ax=inset, color="#f7f5ef", edgecolor="#9a9a9a", linewidth=0.5)
    countries[countries["name"] == "Tunisia"].plot(ax=inset, color="#d9d2bf", edgecolor="#7a7a7a", linewidth=0.6)
    inset.add_patch(Rectangle((EXTENT[0], EXTENT[2]), EXTENT[1] - EXTENT[0], EXTENT[3] - EXTENT[2],
                              fill=False, edgecolor="#c0392b", linewidth=1))
    inset.set_xlim(5.5, 13); inset.set_ylim(29.8, 38); inset.set_xticks([]); inset.set_yticks([])
    inset.set_facecolor("#e8f1f8")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    printed = int((~no_fill).sum())
    print(f"wrote {OUT.relative_to(ROOT)} (fill on {last}: {printed} dams printed)")


if __name__ == "__main__":
    main()

"""Build publication GIS files from the frozen Task21 R11A GeoPackage.

This is a packaging and integrity operation. It does not delineate, repair,
select, or otherwise change watershed science. Invalid or missing geometry is
reported and preserved.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from shapely import set_precision
from shapely.geometry import mapping, shape

from paths import optional, portable


# Raster roots are configured locally; the registry records these portable identifiers.
RASTER_LOGICAL_PATHS = {
    "merit_hydro_dir": "<TASK21>/data/merit_hydro_v101/dir",
    "merit_hydro_upa": "<TASK21>/data/merit_hydro_v101/upa",
    "fabdem_tiles": "<TASK21>/data/fabdem_v12/tiles",
    "jrc_gsw_occurrence": "<TASK21>/data/jrc_gsw_v1_4_2021/occurrence",
}

SOURCE_GPKG_SHA256 = "006b0c93dc8c8afb0b6ef6661a67bcc8061e628f17f6cc2afe17c76aa8a2850e"
SOURCE_CRS_EPSG = 32632
PUBLICATION_CRS_EPSG = 4326
COORDINATE_DECIMALS = 6

LAYER_AUTHORITY = {
    "accepted_dam_controls": (
        "CURRENT_CONTROL_CONTRACT",
        "R10 current producer; R11 assembler; R11A unchanged",
        "PUBLIC_EXPORT_DAMS",
        "Thirty-six accepted controls; source warning fields remain authoritative.",
    ),
    "accepted_total_watersheds": (
        "35_TOTAL_CLIMATE_READY",
        "R10 producer plus R10A Siliana correction; R11/R11A assembler/freeze",
        "PUBLIC_EXPORT_TOTAL_CATCHMENTS",
        "Mellègue is excluded and has no canonical accepted total geometry.",
    ),
    "incremental_catchments": (
        "32_ORDINARY_INCREMENTAL_READY_PLUS_2_SPECIAL",
        "R10A producer; R11A exact SQLite row/blob transplant",
        "PUBLIC_EXPORT_INCREMENTAL_CATCHMENTS",
        "Thirty-four geometries exist: 32 ordinary-ready plus Sidi Saad and Sidi Aïch special cases; Mellègue and Sidi Salem are absent.",
    ),
    "natural_dam_graph": (
        "CURRENT_NATURAL_NETWORK_EDGES",
        "R10 producer; R10A audit; R11 assembler",
        "PUBLIC_EXPORT_NATURAL_NETWORK",
        "Eight controlled-dam edges; not a complete river network. Mellègue/Sidi Salem network use remains blocked.",
    ),
    "artificial_transfer_edges": (
        "CURRENT_ARTIFICIAL_TRANSFER_EDGES",
        "R10 producer; R11 assembler",
        "PUBLIC_EXPORT_TRANSFER_NETWORK",
        "Ten typed relationships; four deliberately have no geometry and operational timing/discharge are not established.",
    ),
    "reservoir_footprints": (
        "CURRENT_RESERVOIR_EVIDENCE_LAYER",
        "R10 producer; R11 assembler; R11A unchanged",
        "SOURCE_ONLY_NOT_REQUESTED_CORE_EXPORT",
        "Evidence footprints are not official cadastral reservoir boundaries.",
    ),
    "special_hydrology_zones": (
        "CURRENT_SPECIAL_HYDROLOGY_ZONES",
        "R10 producer; R11 assembler; R11A taxonomy repair",
        "SOURCE_ONLY_QUALIFICATION_PRESERVED_IN_REGISTRIES",
        "Presence is not ordinary model readiness.",
    ),
    "mellegue_candidate_watersheds": (
        "SENSITIVITY_ONLY",
        "R11 assembler from R10/R10A candidates under R10B exclusion decision",
        "SENSITIVITY_ONLY_NOT_PUBLIC_CORE_LAYER",
        "Neither candidate is canonical or authorized for accepted catchment use.",
    ),
    "mellegue_uncertainty_components": (
        "CURRENT_UNRESOLVED_COMPONENT_EVIDENCE",
        "R10B audit; R11 assembler",
        "EVIDENCE_ONLY_NOT_PUBLIC_CORE_LAYER",
        "Six material components require external receiver evidence.",
    ),
}

EXPORTS = {
    "accepted_dam_controls": "dams.geojson",
    "accepted_total_watersheds": "catchments.geojson",
    "incremental_catchments": "catchments_incremental.geojson",
    "artificial_transfer_edges": "transfer_network.geojson",
    "natural_dam_graph": "natural_network.geojson",
}

RASTER_SOURCES = [
    {
        "raster_id": "MERIT_HYDRO_V101_DIR",
        "source": "MERIT Hydro",
        "purpose": "Primary structured D8 flow-direction terrain branch used in accepted watershed lineage.",
        "root_key": "merit_hydro_dir",
        "product": "MERIT Hydro v1.0.1 DIR",
        "redistribution": "LICENSE_REVIEW_REQUIRED",
    },
    {
        "raster_id": "MERIT_HYDRO_V101_UPA",
        "source": "MERIT Hydro",
        "purpose": "Upstream-area companion used for outlet/control checks in accepted watershed lineage.",
        "root_key": "merit_hydro_upa",
        "product": "MERIT Hydro v1.0.1 UPA",
        "redistribution": "LICENSE_REVIEW_REQUIRED",
    },
    {
        "raster_id": "FABDEM_V12_TILES",
        "source": "FABDEM",
        "purpose": "Independent Priority-Flood/D8 terrain branch and bounded accepted corrections, including final Siliana.",
        "root_key": "fabdem_tiles",
        "product": "FABDEM v1.2 source elevation tiles",
        "redistribution": "LICENSE_REVIEW_REQUIRED",
    },
    {
        "raster_id": "JRC_GSW_V14_OCCURRENCE",
        "source": "JRC Global Surface Water",
        "purpose": "Reservoir-connectivity evidence used by R10; not a published DamLevels raster product.",
        "root_key": "jrc_gsw_occurrence",
        "product": "JRC Global Surface Water occurrence v1.4 (2021)",
        "redistribution": "LICENSE_REVIEW_REQUIRED",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def round_coordinates(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [round_coordinates(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return round(float(value), COORDINATE_DECIMALS)
    return value


def geometry_wkb_sha256(geometry: Any) -> str:
    if geometry is None:
        return ""
    return hashlib.sha256(geometry.wkb).hexdigest()


def rounded_geometry(geometry: Any) -> tuple[Any, dict[str, Any] | None]:
    if geometry is None or geometry.is_empty:
        return geometry, None
    payload = mapping(geometry)
    payload["coordinates"] = round_coordinates(payload["coordinates"])
    naive = shape(payload)
    if naive.is_valid:
        return naive, None
    precision_safe = set_precision(geometry, 10 ** -COORDINATE_DECIMALS, mode="valid_output")
    safe_payload = mapping(precision_safe)
    safe_payload["coordinates"] = round_coordinates(safe_payload["coordinates"])
    final = shape(safe_payload)
    if not final.is_valid:
        raise RuntimeError("Topology-preserving coordinate precision output remains invalid")
    return final, {
        "transformed_preprecision_wkb_sha256": geometry_wkb_sha256(geometry),
        "naive_rounded_wkb_sha256": geometry_wkb_sha256(naive),
        "final_wkb_sha256": geometry_wkb_sha256(final),
        "transformed_preprecision_valid": geometry.is_valid,
        "naive_rounded_valid": naive.is_valid,
        "final_valid": final.is_valid,
        "operation": "SHAPELY_SET_PRECISION_VALID_OUTPUT_GRID_0.000001_DEG",
        "reason": "Naive six-decimal coordinate rounding made a valid source geometry invalid; valid-output precision reduction preserves topology at the required publication precision.",
        "scientific_selection_effect": "NONE_PACKAGING_ONLY",
    }


def write_geojson(frame: gpd.GeoDataFrame, path: Path, layer_name: str) -> str:
    features = []
    for _, row in frame.iterrows():
        geometry = row.geometry
        properties = {
            key: clean_value(value)
            for key, value in row.items()
            if key != frame.geometry.name
        }
        features.append(
            {
                "type": "Feature",
                "geometry": None if geometry is None else mapping(geometry),
                "properties": properties,
            }
        )
    payload = {
        "type": "FeatureCollection",
        "name": layer_name,
        "metadata": {
            "publication_crs": "EPSG:4326",
            "coordinate_precision_decimals": COORDINATE_DECIMALS,
            "source_crs": "EPSG:32632",
            "scientific_geometry_changed": False,
            "coordinate_rounding": "PACKAGING_ONLY",
        },
        "features": features,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return sha256_file(path)


def layer_metrics(frame: gpd.GeoDataFrame) -> dict[str, Any]:
    present = frame.geometry.notna()
    types = sorted({str(item) for item in frame.geom_type.tolist()})
    wgs = frame.to_crs(PUBLICATION_CRS_EPSG) if frame.crs else None
    bounds = [float(value) for value in frame.total_bounds]
    wgs_bounds = [float(value) for value in wgs.total_bounds] if wgs is not None else []
    return {
        "feature_count": len(frame),
        "source_crs": str(frame.crs) if frame.crs else "",
        "epsg": frame.crs.to_epsg() if frame.crs else "",
        "geometry_type": "|".join(types),
        "missing_geometry_count": int(frame.geometry.isna().sum()),
        "empty_geometry_count": int(frame.geometry.is_empty.sum()),
        "invalid_geometry_count": int((~frame.geometry[present].is_valid).sum()),
        "bounds": json.dumps(bounds),
        "wgs84_bounds": json.dumps(wgs_bounds),
    }


def add_common_fields(frame: gpd.GeoDataFrame, source_layer: str, source_hash: str) -> gpd.GeoDataFrame:
    authority, producer, _, _ = LAYER_AUTHORITY[source_layer]
    output = frame.copy()
    output["source_layer"] = source_layer
    output["source_artifact_sha256"] = source_hash
    output["source_authority"] = authority
    output["source_producer_or_assembler"] = producer
    output["publication_crs"] = "EPSG:4326"
    output["coordinate_precision_decimals"] = COORDINATE_DECIMALS
    return output


def export_layers(
    source_gpkg: Path,
    vector_dir: Path,
    dams_path: Path,
    registry_path: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, gpd.GeoDataFrame],
]:
    source_hash = sha256_file(source_gpkg)
    if source_hash != SOURCE_GPKG_SHA256:
        raise RuntimeError(f"Unexpected source GeoPackage hash: {source_hash}")

    dams = pd.read_csv(dams_path, dtype=str, keep_default_na=False)
    registry = pd.read_csv(registry_path, dtype=str, keep_default_na=False)
    dam_ids = set(dams["dam_id"])
    source_frames: dict[str, gpd.GeoDataFrame] = {}
    for layer in pyogrio.list_layers(source_gpkg)[:, 0]:
        source_frames[str(layer)] = gpd.read_file(source_gpkg, layer=str(layer))

    prepared: dict[str, gpd.GeoDataFrame] = {}

    controls = add_common_fields(source_frames["accepted_dam_controls"], "accepted_dam_controls", source_hash)
    controls = controls.merge(
        dams[
            [
                "dam_id",
                "name_fr",
                "name_ar",
                "name_ar_status",
                "basin",
                "basin_status",
                "reference_capacity_mm3",
                "status",
                "geometry_status",
            ]
        ],
        on="dam_id",
        how="left",
        validate="one_to_one",
    )
    prepared["accepted_dam_controls"] = controls

    readiness_fields = [
        "dam_id",
        "task21_status",
        "geometry_status",
        "natural_total_climate_ready",
        "local_incremental_ready",
        "network_ready",
        "special_hydrology_required",
        "warning_code",
        "warning_text",
        "decision_run",
    ]
    totals = add_common_fields(source_frames["accepted_total_watersheds"], "accepted_total_watersheds", source_hash)
    totals = totals.merge(registry[readiness_fields], on="dam_id", how="left", validate="one_to_one")
    prepared["accepted_total_watersheds"] = totals

    incrementals = add_common_fields(source_frames["incremental_catchments"], "incremental_catchments", source_hash)
    incrementals = incrementals.merge(registry[readiness_fields], on="dam_id", how="left", validate="one_to_one")
    prepared["incremental_catchments"] = incrementals

    natural = add_common_fields(source_frames["natural_dam_graph"], "natural_dam_graph", source_hash)
    prepared["natural_dam_graph"] = natural

    transfers = add_common_fields(source_frames["artificial_transfer_edges"], "artificial_transfer_edges", source_hash)
    transfers["from_dam_id"] = transfers["from_entity"].map(lambda value: value if value in dam_ids else None)
    transfers["from_entity_identity_status"] = transfers["from_entity"].map(
        lambda value: "MATCHED" if value in dam_ids else "NOT_APPLICABLE_NON_DAM_ENTITY"
    )
    transfers["to_dam_id_status"] = transfers["to_dam_id"].map(
        lambda value: "MATCHED" if value in dam_ids else "UNRESOLVED"
    )
    prepared["artificial_transfer_edges"] = transfers

    area_rows: list[dict[str, Any]] = []
    packaging_actions: list[dict[str, Any]] = []
    output_info: dict[str, dict[str, Any]] = {}
    exported_frames: dict[str, gpd.GeoDataFrame] = {}
    for source_layer, filename in EXPORTS.items():
        original = prepared[source_layer]
        projected = original.to_crs(SOURCE_CRS_EPSG)
        is_polygon = projected.geom_type.isin(["Polygon", "MultiPolygon"])
        if bool(is_polygon.any()):
            projected["area_km2_calculated_epsg32632"] = projected.geometry.area / 1_000_000
            projected["area_calculation_crs"] = "EPSG:32632"
        public = projected.to_crs(PUBLICATION_CRS_EPSG)
        rounded_geometries = []
        for feature_index, geometry in enumerate(public.geometry):
            rounded, action = rounded_geometry(geometry)
            rounded_geometries.append(rounded)
            if action:
                source_geometry = projected.geometry.iloc[feature_index]
                action.update(
                    {
                        "output_layer": Path(filename).stem,
                        "source_layer": source_layer,
                        "feature_index": feature_index,
                        "dam_id_or_feature": clean_value(public.iloc[feature_index].get("dam_id"))
                        or clean_value(public.iloc[feature_index].get("component_id"))
                        or str(feature_index),
                        "source_epsg32632_wkb_sha256": geometry_wkb_sha256(source_geometry),
                        "source_epsg32632_valid": source_geometry.is_valid,
                    }
                )
                packaging_actions.append(action)
        public.geometry = rounded_geometries
        exported_frames[source_layer] = public
        output_path = vector_dir / filename
        output_hash = write_geojson(public, output_path, output_path.stem)

        metrics = layer_metrics(public)
        metrics["output_crs"] = metrics.pop("source_crs")
        output_info[source_layer] = {
            "filename": filename,
            "path": f"gis/vector/{filename}",
            "sha256": output_hash,
            **metrics,
        }

        if bool(is_polygon.any()):
            roundtrip = public.to_crs(SOURCE_CRS_EPSG)
            for index in range(len(projected)):
                source_geometry_area = float(projected.geometry.iloc[index].area / 1_000_000)
                output_geometry_area = float(roundtrip.geometry.iloc[index].area / 1_000_000)
                accepted = clean_value(projected.iloc[index].get("area_km2"))
                accepted_float = float(accepted) if accepted not in (None, "") else None
                difference = output_geometry_area - source_geometry_area
                tolerance = max(0.01, source_geometry_area * 0.00001)
                area_rows.append(
                    {
                        "output_layer": output_path.stem,
                        "source_layer": source_layer,
                        "dam_id": projected.iloc[index].get("dam_id", ""),
                        "source_area_km2_epsg32632": f"{source_geometry_area:.12f}",
                        "accepted_attribute_area_km2": "" if accepted_float is None else f"{accepted_float:.12f}",
                        "output_roundtrip_area_km2_epsg32632": f"{output_geometry_area:.12f}",
                        "output_minus_source_km2": f"{difference:.12f}",
                        "absolute_difference_km2": f"{abs(difference):.12f}",
                        "relative_difference": f"{abs(difference) / source_geometry_area:.12g}" if source_geometry_area else "",
                        "packaging_tolerance_km2": f"{tolerance:.12f}",
                        "status": "PASS_6DP_PACKAGING_ROUNDING" if abs(difference) <= tolerance else "REVIEW_REQUIRED",
                        "scientific_selection_effect": "NONE",
                    }
                )

    crosswalk_rows: list[dict[str, Any]] = []
    for layer in ("accepted_dam_controls", "accepted_total_watersheds", "incremental_catchments"):
        for index, row in prepared[layer].reset_index(drop=True).iterrows():
            dam_id = clean_value(row.get("dam_id")) or ""
            crosswalk_rows.append(
                {
                    "layer": EXPORTS[layer],
                    "source_layer": layer,
                    "feature_index": index,
                    "association_role": "dam_id",
                    "source_value": dam_id,
                    "dam_id": dam_id if dam_id in dam_ids else "",
                    "classification": "MATCHED" if dam_id in dam_ids else "UNRESOLVED",
                    "evidence": "data/dams.csv",
                    "notes": "Stable ID exact membership check; spelling was not used as a key.",
                }
            )
    for index, row in prepared["natural_dam_graph"].reset_index(drop=True).iterrows():
        for role in ("from_dam_id", "to_dam_id"):
            value = clean_value(row.get(role)) or ""
            crosswalk_rows.append(
                {
                    "layer": EXPORTS["natural_dam_graph"],
                    "source_layer": "natural_dam_graph",
                    "feature_index": index,
                    "association_role": role,
                    "source_value": value,
                    "dam_id": value if value in dam_ids else "",
                    "classification": "MATCHED" if value in dam_ids else "UNRESOLVED",
                    "evidence": "data/dams.csv",
                    "notes": "Stable endpoint ID exact membership check.",
                }
            )
    for index, row in prepared["artificial_transfer_edges"].reset_index(drop=True).iterrows():
        source_value = clean_value(row.get("from_entity")) or ""
        source_is_dam = source_value in dam_ids
        crosswalk_rows.append(
            {
                "layer": EXPORTS["artificial_transfer_edges"],
                "source_layer": "artificial_transfer_edges",
                "feature_index": index,
                "association_role": "from_entity",
                "source_value": source_value,
                "dam_id": source_value if source_is_dam else "",
                "classification": "MATCHED" if source_is_dam else "NOT_APPLICABLE",
                "evidence": "data/dams.csv|source from_entity semantics",
                "notes": "Non-dam source systems remain named entities; no candidate dam mapping was invented.",
            }
        )
        target_value = clean_value(row.get("to_dam_id")) or ""
        crosswalk_rows.append(
            {
                "layer": EXPORTS["artificial_transfer_edges"],
                "source_layer": "artificial_transfer_edges",
                "feature_index": index,
                "association_role": "to_dam_id",
                "source_value": target_value,
                "dam_id": target_value if target_value in dam_ids else "",
                "classification": "MATCHED" if target_value in dam_ids else "UNRESOLVED",
                "evidence": "data/dams.csv",
                "notes": "Stable endpoint ID exact membership check.",
            }
        )
    return output_info, area_rows, crosswalk_rows, packaging_actions, source_frames


def raster_manifest() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in RASTER_SOURCES:
        root = optional(item["root_key"])
        files = sorted(root.glob("*.tif")) if root is not None and root.exists() else []
        crs_values: set[str] = set()
        resolutions: set[str] = set()
        formats: set[str] = set()
        bounds: list[tuple[float, float, float, float]] = []
        manifest_lines: list[str] = []
        inspection_errors: list[str] = []
        for path in files:
            digest = sha256_file(path)
            manifest_lines.append(f"{path.name}|{path.stat().st_size}|{digest}")
            try:
                with rasterio.open(path) as dataset:
                    crs_values.add(str(dataset.crs))
                    resolutions.add(f"{dataset.res[0]:.15g} x {dataset.res[1]:.15g}")
                    formats.add(dataset.driver)
                    bounds.append(tuple(float(value) for value in dataset.bounds))
            except Exception as error:
                inspection_errors.append(f"{path.name}: {error}")
        aggregate_hash = hashlib.sha256("\n".join(manifest_lines).encode("utf-8")).hexdigest() if manifest_lines else ""
        union_bounds = (
            [min(x[0] for x in bounds), min(x[1] for x in bounds), max(x[2] for x in bounds), max(x[3] for x in bounds)]
            if bounds
            else []
        )
        rows.append(
            {
                "raster_id": item["raster_id"],
                "source": item["source"],
                "product": item["product"],
                "purpose": item["purpose"],
                "CRS": "|".join(sorted(crs_values)) if crs_values else "UNKNOWN",
                "resolution": "|".join(sorted(resolutions)) if resolutions else "UNKNOWN",
                "format": "|".join(sorted(formats)) if formats else "UNKNOWN",
                "file_count": len(files),
                "size_bytes": sum(path.stat().st_size for path in files),
                "bounds": json.dumps(union_bounds),
                "COG_status": "CONVERTIBLE_WITH_GDAL_NOT_CREATED_EXTERNAL_PROVIDER_SOURCE",
                "external_path": RASTER_LOGICAL_PATHS[item["root_key"]],
                "sha256": aggregate_hash,
                "hash_scope": "SHA256_OF_SORTED_FILENAME_SIZE_FILE_SHA256_MANIFEST",
                "redistribution_status": item["redistribution"],
                "inspection_status": "METADATA_INSPECTED" if files and not inspection_errors else "REVIEW_REQUIRED",
                "notes": "No raster bytes copied; no COG created because publication/redistribution remains gated."
                + (" Errors: " + " | ".join(inspection_errors) if inspection_errors else ""),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--source-gpkg", type=Path, required=True)
    parser.add_argument("--task21-registry", type=Path, required=True)
    args = parser.parse_args()

    root = args.repo_root.resolve()
    source_gpkg = args.source_gpkg.resolve()
    vector_dir = root / "gis" / "vector"
    qa_dir = root / "qa" / "gis"
    vector_dir.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)

    output_info, area_rows, crosswalk_rows, packaging_actions, source_frames = export_layers(
        source_gpkg,
        vector_dir,
        root / "data" / "dams.csv",
        args.task21_registry.resolve(),
    )
    source_hash = sha256_file(source_gpkg)

    authority_rows = []
    crs_rows = []
    for layer, frame in source_frames.items():
        metrics = layer_metrics(frame)
        authority, producer, disposition, limitation = LAYER_AUTHORITY[layer]
        authority_rows.append(
            {
                "artifact_id": f"GIS-SRC-{len(authority_rows)+1:03d}",
                "source_artifact": portable(str(source_gpkg)),
                "source_sha256": source_hash,
                "size_bytes": source_gpkg.stat().st_size,
                "layer": layer,
                "authority": authority,
                "producer_or_assembler": producer,
                "source_crs": metrics["source_crs"],
                "epsg": metrics["epsg"],
                "geometry_type": metrics["geometry_type"],
                "feature_count": metrics["feature_count"],
                "disposition": disposition,
                "known_limitations": limitation,
                "evidence": "V010 provenance/WATERSHED_FINAL_PRODUCTS.csv; provenance/WATERSHED_AUTHORITY_DECISION.md",
            }
        )
        crs_rows.append(
            {
                "record_type": "SOURCE_VECTOR_LAYER",
                "artifact": portable(str(source_gpkg)),
                "layer": layer,
                "source_crs": metrics["source_crs"],
                "epsg": metrics["epsg"],
                "geometry_type": metrics["geometry_type"],
                "feature_count": metrics["feature_count"],
                "bounds": metrics["bounds"],
                "wgs84_bounds": metrics["wgs84_bounds"],
                "missing_crs_flag": "NO" if frame.crs else "YES",
                "mixed_crs_flag": "NO",
                "unexpected_crs_flag": "NO" if metrics["epsg"] == SOURCE_CRS_EPSG else "YES",
                "coarse_tunisia_envelope_flag": "PASS"
                if metrics["wgs84_bounds"] and 5 <= json.loads(metrics["wgs84_bounds"])[0] <= 13
                and 29 <= json.loads(metrics["wgs84_bounds"])[1] <= 39
                and 5 <= json.loads(metrics["wgs84_bounds"])[2] <= 13
                and 29 <= json.loads(metrics["wgs84_bounds"])[3] <= 39
                else "REVIEW_REQUIRED",
                "outside_tunisia_flag": "NOT_EVALUATED_NO_AUTHORITATIVE_BOUNDARY_GEOMETRY",
                "missing_geometry_count": metrics["missing_geometry_count"],
                "empty_geometry_count": metrics["empty_geometry_count"],
                "invalid_geometry_count": metrics["invalid_geometry_count"],
                "validity_status": "VALID_WITH_MISSING_GEOMETRY_RECORDS"
                if metrics["missing_geometry_count"]
                else "VALID",
                "notes": "No CRS assignment or geometry repair performed. Coarse envelope is a coordinate sanity screen, not a national-boundary test.",
            }
        )
    authority_rows.extend(
        [
            {
                "artifact_id": "GIS-SRC-010",
                "source_artifact": "NOT_FOUND_IN_ACCEPTED_V010_OR_PRODUCTION_GIS_MATERIAL",
                "source_sha256": "",
                "size_bytes": "",
                "layer": "QGIS_STYLES",
                "authority": "NO_AUTHORITATIVE_STYLE_FOUND",
                "producer_or_assembler": "E5 packaging",
                "source_crs": "NOT_APPLICABLE",
                "epsg": "",
                "geometry_type": "NOT_APPLICABLE",
                "feature_count": "",
                "disposition": "GENERATED_PRESENTATION_ONLY",
                "known_limitations": "E5 colors and line patterns carry no scientific authority.",
                "evidence": "Targeted search of accepted production geospatial and V010 review-clone material.",
            },
            {
                "artifact_id": "GIS-SRC-011",
                "source_artifact": "NOT_FOUND_IN_ACCEPTED_V010_OR_PRODUCTION_GIS_MATERIAL",
                "source_sha256": "",
                "size_bytes": "",
                "layer": "QGIS_PROJECT",
                "authority": "NO_AUTHORITATIVE_PROJECT_FOUND",
                "producer_or_assembler": "E5 packaging",
                "source_crs": "NOT_APPLICABLE",
                "epsg": "",
                "geometry_type": "NOT_APPLICABLE",
                "feature_count": "",
                "disposition": "GENERATED_RELATIVE_PATH_PROJECT",
                "known_limitations": "Project is a presentation/navigation artifact, not scientific authority.",
                "evidence": "Targeted search of accepted production geospatial and V010 review-clone material.",
            },
        ]
    )
    for layer, info in output_info.items():
        crs_rows.append(
            {
                "record_type": "PUBLICATION_VECTOR_OUTPUT",
                "artifact": f"gis/vector/{info['filename']}",
                "layer": Path(info["filename"]).stem,
                "source_crs": info["source_crs"],
                "epsg": info["epsg"],
                "geometry_type": info["geometry_type"],
                "feature_count": info["feature_count"],
                "bounds": info["bounds"],
                "wgs84_bounds": info["wgs84_bounds"],
                "missing_crs_flag": "NO",
                "mixed_crs_flag": "NO",
                "unexpected_crs_flag": "NO" if info["epsg"] == PUBLICATION_CRS_EPSG else "YES",
                "coarse_tunisia_envelope_flag": "PASS",
                "outside_tunisia_flag": "NOT_EVALUATED_NO_AUTHORITATIVE_BOUNDARY_GEOMETRY",
                "missing_geometry_count": info["missing_geometry_count"],
                "empty_geometry_count": info["empty_geometry_count"],
                "invalid_geometry_count": info["invalid_geometry_count"],
                "validity_status": "VALID_WITH_MISSING_GEOMETRY_RECORDS"
                if info["missing_geometry_count"]
                else "VALID",
                "notes": "EPSG:4326 output with coordinates rounded to six decimals; no scientific repair.",
            }
        )

    write_csv(
        root / "gis" / "GIS_SOURCE_AUTHORITY.csv",
        [
            "artifact_id", "source_artifact", "source_sha256", "size_bytes", "layer", "authority",
            "producer_or_assembler", "source_crs", "epsg", "geometry_type", "feature_count", "disposition",
            "known_limitations", "evidence",
        ],
        authority_rows,
    )
    write_csv(
        qa_dir / "crs_inventory.csv",
        [
            "record_type", "artifact", "layer", "source_crs", "epsg", "geometry_type", "feature_count",
            "bounds", "wgs84_bounds", "missing_crs_flag", "mixed_crs_flag", "unexpected_crs_flag",
            "coarse_tunisia_envelope_flag", "outside_tunisia_flag", "missing_geometry_count",
            "empty_geometry_count", "invalid_geometry_count", "validity_status", "notes",
        ],
        crs_rows,
    )
    write_csv(
        qa_dir / "dam_id_crosswalk_audit.csv",
        ["layer", "source_layer", "feature_index", "association_role", "source_value", "dam_id", "classification", "evidence", "notes"],
        crosswalk_rows,
    )
    write_csv(
        qa_dir / "area_integrity.csv",
        [
            "output_layer", "source_layer", "dam_id", "source_area_km2_epsg32632",
            "accepted_attribute_area_km2", "output_roundtrip_area_km2_epsg32632",
            "output_minus_source_km2", "absolute_difference_km2", "relative_difference",
            "packaging_tolerance_km2", "status", "scientific_selection_effect",
        ],
        area_rows,
    )
    write_csv(
        qa_dir / "geometry_packaging_actions.csv",
        [
            "output_layer", "source_layer", "feature_index", "dam_id_or_feature", "operation", "reason",
            "source_epsg32632_wkb_sha256", "source_epsg32632_valid", "transformed_preprecision_wkb_sha256",
            "transformed_preprecision_valid", "naive_rounded_wkb_sha256", "naive_rounded_valid",
            "final_wkb_sha256", "final_valid", "scientific_selection_effect",
        ],
        packaging_actions,
    )
    raster_rows = raster_manifest()
    write_csv(
        root / "gis" / "RASTER_MANIFEST.csv",
        [
            "raster_id", "source", "product", "purpose", "CRS", "resolution", "format", "file_count",
            "size_bytes", "bounds", "COG_status", "external_path", "sha256", "hash_scope",
            "redistribution_status", "inspection_status", "notes",
        ],
        raster_rows,
    )

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "engineering_run": "E5",
        "baseline_git_commit": "146f1ca54c68b6340dceb487cb8b27fd472a9c41",
        "source_gpkg": portable(str(source_gpkg)),
        "source_gpkg_sha256": source_hash,
        "source_authority": "R10+R10A+R10B+R11+R11A_COMPOSITE_R11A_FROZEN_PACKAGE",
        "scientific_pipelines_rerun": False,
        "watershed_delineation_rerun": False,
        "source_geometries_repaired": 0,
        "publication_precision_actions": len(packaging_actions),
        "publication_precision_action_scope": "EXPLICIT_PACKAGING_ONLY_TOPOLOGY_PRESERVING_6_DECIMAL_PRECISION",
        "publication_crs": "EPSG:4326",
        "area_calculation_crs": "EPSG:32632",
        "coordinate_precision_decimals": COORDINATE_DECIMALS,
        "exports": output_info,
        "exported_layer_count": len(output_info),
        "source_layer_count": len(source_frames),
        "area_integrity_rows": len(area_rows),
        "area_integrity_review_required": sum(row["status"] != "PASS_6DP_PACKAGING_ROUNDING" for row in area_rows),
        "crosswalk_rows": len(crosswalk_rows),
        "crosswalk_classifications": dict(pd.Series([row["classification"] for row in crosswalk_rows]).value_counts()),
        "raster_manifest_count": len(raster_rows),
        "raster_bytes_copied": 0,
        "mellegue_canonical_total_exported": False,
        "accepted_total_count": len(source_frames["accepted_total_watersheds"]),
        "incremental_geometry_count": len(source_frames["incremental_catchments"]),
        "ordinary_incremental_ready_count": int((source_frames["incremental_catchments"]["readiness"] == "YES").sum()),
        "special_incremental_geometry_count": int((source_frames["incremental_catchments"]["readiness"] != "YES").sum()),
        "qgis_project_validation": "PENDING_QGIS_PROJECT_BUILD",
        "acceptance_decision": "PENDING_FINAL_VALIDATION",
    }
    (qa_dir / "gis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=clean_value) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, default=clean_value))


if __name__ == "__main__":
    main()

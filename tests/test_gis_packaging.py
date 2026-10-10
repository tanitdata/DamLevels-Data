import csv
import json
import re
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / "gis" / "vector"


def load_geojson(name):
    return json.loads((VECTOR / name).read_text(encoding="utf-8"))


def dam_ids():
    with (ROOT / "data" / "dams.csv").open(encoding="utf-8-sig", newline="") as stream:
        return {row["dam_id"] for row in csv.DictReader(stream)}


def dam_coordinates():
    with (ROOT / "data" / "dams.csv").open(encoding="utf-8-sig", newline="") as stream:
        return {
            row["dam_id"]: (float(row["longitude"]), float(row["latitude"]))
            for row in csv.DictReader(stream)
        }


def iter_coordinates(value):
    if isinstance(value, list) and value and isinstance(value[0], (int, float)):
        yield from value
    elif isinstance(value, list):
        for item in value:
            yield from iter_coordinates(item)


def test_publication_layers_counts_crs_and_precision():
    expected = {
        "dams.geojson": 36,
        "catchments.geojson": 35,
        "catchments_incremental.geojson": 34,
        "transfer_network.geojson": 10,
        "natural_network.geojson": 8,
    }
    for name, count in expected.items():
        data = load_geojson(name)
        assert data["type"] == "FeatureCollection"
        assert data["metadata"]["publication_crs"] == "EPSG:4326"
        assert data["metadata"]["coordinate_precision_decimals"] == 6
        assert len(data["features"]) == count
        for feature in data["features"]:
            if feature["geometry"] is None:
                continue
            for coordinate in iter_coordinates(feature["geometry"]["coordinates"]):
                assert abs(coordinate * 1_000_000 - round(coordinate * 1_000_000)) < 1e-6


def test_stable_dam_ids_and_scientific_qualifications():
    ids = dam_ids()
    assert len(ids) == 36
    dams = load_geojson("dams.geojson")["features"]
    assert {feature["properties"]["dam_id"] for feature in dams} == ids
    expected_coordinates = dam_coordinates()
    for feature in dams:
        dam_id = feature["properties"]["dam_id"]
        expected_longitude, expected_latitude = expected_coordinates[dam_id]
        longitude, latitude = feature["geometry"]["coordinates"]
        assert abs(longitude - expected_longitude) <= 1e-6
        assert abs(latitude - expected_latitude) <= 1e-6

    totals = load_geojson("catchments.geojson")["features"]
    total_ids = {feature["properties"]["dam_id"] for feature in totals}
    assert len(total_ids) == 35
    assert "mellegue" not in total_ids
    assert total_ids <= ids

    incrementals = load_geojson("catchments_incremental.geojson")["features"]
    incremental_ids = {feature["properties"]["dam_id"] for feature in incrementals}
    assert len(incremental_ids) == 34
    assert "mellegue" not in incremental_ids
    assert "sidisalem" not in incremental_ids
    assert sum(feature["properties"]["readiness"] == "YES" for feature in incrementals) == 32
    assert sum(feature["properties"]["readiness"] != "YES" for feature in incrementals) == 2

    natural = load_geojson("natural_network.geojson")["features"]
    assert all(feature["properties"]["from_dam_id"] in ids for feature in natural)
    assert all(feature["properties"]["to_dam_id"] in ids for feature in natural)

    transfers = load_geojson("transfer_network.geojson")["features"]
    assert all(feature["properties"]["to_dam_id"] in ids for feature in transfers)
    assert all(
        feature["properties"]["from_dam_id"] is None
        or feature["properties"]["from_dam_id"] in ids
        for feature in transfers
    )
    assert sum(feature["geometry"] is None for feature in transfers) == 4


def test_qgis_project_is_relative_and_resolves():
    project = ROOT / "gis" / "project" / "DamLevels-Data.qgs"
    text = project.read_text(encoding="utf-8")
    # Check the drive roots that could leak from this Windows build host.
    # A generic ``[A-Za-z]:/`` pattern incorrectly matches the ``p:/`` in
    # XML namespace URLs such as ``http://www.qgis.org``.
    assert "C:\\" not in text and "C:/" not in text
    assert "D:\\" not in text and "D:/" not in text
    assert "\\Users\\" not in text and "/Users/" not in text
    assert not re.search(r"(?i)password|passwd|dbname=|host=|service=|token=", text)
    tree = ElementTree.parse(project)
    sources = [node.text for node in tree.findall(".//datasource") if node.text]
    assert len(sources) == 5
    for source in sources:
        assert not Path(source).is_absolute()
        assert (project.parent / source).resolve().exists()


def test_styles_are_presentation_only_and_well_formed():
    styles = sorted((ROOT / "gis" / "styles").glob("*.qml"))
    assert len(styles) == 5
    for style in styles:
        ElementTree.parse(style)
        assert "PRESENTATION_ONLY" in style.read_text(encoding="utf-8")


def test_area_and_precision_actions_are_explicit():
    with (ROOT / "qa" / "gis" / "area_integrity.csv").open(encoding="utf-8-sig", newline="") as stream:
        areas = list(csv.DictReader(stream))
    assert len(areas) == 69
    assert all(row["status"] == "PASS_6DP_PACKAGING_ROUNDING" for row in areas)
    assert all(row["scientific_selection_effect"] == "NONE" for row in areas)

    with (ROOT / "qa" / "gis" / "geometry_packaging_actions.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        actions = list(csv.DictReader(stream))
    assert len(actions) == 3
    assert all(row["source_epsg32632_valid"] == "True" for row in actions)
    assert all(row["naive_rounded_valid"] == "False" for row in actions)
    assert all(row["final_valid"] == "True" for row in actions)
    assert all(row["scientific_selection_effect"] == "NONE_PACKAGING_ONLY" for row in actions)


def test_rasters_are_manifest_only():
    with (ROOT / "gis" / "RASTER_MANIFEST.csv").open(encoding="utf-8-sig", newline="") as stream:
        rasters = list(csv.DictReader(stream))
    assert len(rasters) == 4
    assert all(row["inspection_status"] == "METADATA_INSPECTED" for row in rasters)
    assert not list((ROOT / "gis").rglob("*.tif"))
    assert not list((ROOT / "gis").rglob("*.tiff"))


"""QGIS Processing script that builds the repository-relative E5 project."""

from pathlib import Path

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProject,
    QgsVectorLayer,
)


class CreateDamLevelsProject(QgsProcessingAlgorithm):
    LAYERS = [
        ("catchments.geojson", "Accepted total catchments", "catchments.qml"),
        ("catchments_incremental.geojson", "Accepted incremental catchments", "catchments_incremental.qml"),
        ("natural_network.geojson", "Natural controlled-dam network", "natural_network.qml"),
        ("transfer_network.geojson", "Artificial transfer network", "transfer_network.qml"),
        ("dams.geojson", "Dam controls", "dams.qml"),
    ]

    def name(self):
        return "create_damlevels_project"

    def displayName(self):
        return "Create DamLevels-Data relative-path project"

    def group(self):
        return "DamLevels-Data"

    def groupId(self):
        return "damlevels_data"

    def shortHelpString(self):
        return "Packages existing E5 GeoJSON layers into an uncompressed relative-path QGIS project."

    def initAlgorithm(self, config=None):
        self.addOutput(QgsProcessingOutputFile("OUTPUT_PROJECT", "Created QGIS project"))

    def processAlgorithm(self, parameters, context, feedback):
        root = Path(__file__).resolve().parents[2]
        vector_root = root / "gis" / "vector"
        style_root = root / "gis" / "styles"
        output = root / "gis" / "project" / "DamLevels-Data.qgs"
        output.parent.mkdir(parents=True, exist_ok=True)

        project = QgsProject()
        project.clear()
        project.setTitle("DamLevels-Data — accepted Task21 spatial products")
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        project.setFilePathStorage(Qgis.FilePathType.Relative)
        project.writeEntry("DamLevels-Data", "authority", "R10+R10A+R10B+R11+R11A composite; R11A frozen package")
        project.writeEntry("DamLevels-Data", "publication_crs", "EPSG:4326")
        project.writeEntry("DamLevels-Data", "area_calculation_crs", "EPSG:32632")
        project.writeEntry("DamLevels-Data", "styles", "PRESENTATION_ONLY")

        for filename, title, style_name in self.LAYERS:
            source = vector_root / filename
            if not source.exists():
                raise QgsProcessingException(f"Missing publication layer: {source}")
            layer = QgsVectorLayer(str(source), title, "ogr")
            if not layer.isValid():
                raise QgsProcessingException(f"QGIS could not load publication layer: {source}")
            style = style_root / style_name
            if style.exists():
                message, loaded = layer.loadNamedStyle(str(style))
                if not loaded:
                    raise QgsProcessingException(f"Could not load style {style}: {message}")
            project.addMapLayer(layer)

        if not project.write(str(output)):
            raise QgsProcessingException(f"Could not write QGIS project: {output}")
        feedback.pushInfo(f"Created {output}")
        return {"OUTPUT_PROJECT": str(output)}

    def createInstance(self):
        return CreateDamLevelsProject()


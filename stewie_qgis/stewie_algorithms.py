"""STEWIE QGIS Processing algorithms (P-A #46). Two algorithms that call the live STEWIE FastAPI backend and
produce QGIS vector outputs, so a scientist/planner can run STEWIE analyses from the QGIS GUI / qgis_process
CLI / batch / a Model. The fetch+parse logic lives in the QGIS-free stewie_backend (unit-tested in CI); these
classes are the thin QGIS boundary. qgis.* is imported here (only loaded under a real QGIS runtime).
"""
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsFeature, QgsFeatureSink, QgsField, QgsFields, QgsGeometry,
    QgsPointXY, QgsProcessing, QgsProcessingAlgorithm, QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber, QgsProcessingParameterString, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from . import stewie_backend as B


class StewieTerramechanicsAlgorithm(QgsProcessingAlgorithm):
    """GET /world/terramechanics-layers?site= -> a table of the physics-computation decomposition."""
    SITE = "SITE"
    API = "API_BASE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "terramechanics"

    def displayName(self):
        return "STEWIE: Terramechanics spine"

    def group(self):
        return "STEWIE"

    def groupId(self):
        return "stewie"

    def shortHelpString(self):
        return ("Fetch the STEWIE terramechanics spine (which derived physics layer is computed from which "
                "terms, on which authority backend) for a work site from the live STEWIE backend, as a table.")

    def createInstance(self):
        return StewieTerramechanicsAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(self.SITE, "Work site", defaultValue="haworth"))
        self.addParameter(QgsProcessingParameterString(self.API, "STEWIE API base", defaultValue=B.DEFAULT_API_BASE))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, "Terramechanics spine", type=QgsProcessing.TypeVector))

    def processAlgorithm(self, parameters, context, feedback):
        site = self.parameterAsString(parameters, self.SITE, context)
        api = self.parameterAsString(parameters, self.API, context)
        feedback.pushInfo("STEWIE: GET terramechanics-layers for %s" % site)
        rows = B.terramechanics_rows(B.fetch_json(B.spine_url(api, site)))
        fields = QgsFields()
        for f in ("layer", "group", "terms", "computes", "backend"):
            fields.append(QgsField(f, QVariant.String))
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields)
        for r in rows:
            feat = QgsFeature(fields)
            feat.setAttributes([r["layer"], r["group"], r["terms"], r["computes"], r["backend"]])
            sink.addFeature(feat, QgsFeatureSink.FastInsert)
        feedback.pushInfo("STEWIE: %d derived layers on %s" % (len(rows), site))
        return {self.OUTPUT: dest}


class StewieSamplePointAlgorithm(QgsProcessingAlgorithm):
    """GET /world/point?site=&lon=&lat= -> a point feature carrying the per-cell terramechanics attributes."""
    SITE = "SITE"
    LON = "LON"
    LAT = "LAT"
    API = "API_BASE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "sample_point"

    def displayName(self):
        return "STEWIE: Sample point"

    def group(self):
        return "STEWIE"

    def groupId(self):
        return "stewie"

    def shortHelpString(self):
        return ("Query the per-cell terramechanics (elevation, slope, bearing, sinkage, slip, ...) at a "
                "selenographic lon/lat from the live STEWIE backend, as a point feature with the terms as fields.")

    def createInstance(self):
        return StewieSamplePointAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(self.SITE, "Work site", defaultValue="haworth"))
        self.addParameter(QgsProcessingParameterNumber(self.LON, "Longitude (selenographic)", type=QgsProcessingParameterNumber.Double, defaultValue=-26.6384))
        self.addParameter(QgsProcessingParameterNumber(self.LAT, "Latitude (selenographic)", type=QgsProcessingParameterNumber.Double, defaultValue=-86.1152))
        self.addParameter(QgsProcessingParameterString(self.API, "STEWIE API base", defaultValue=B.DEFAULT_API_BASE))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, "Sampled point", type=QgsProcessing.TypeVectorPoint))

    def processAlgorithm(self, parameters, context, feedback):
        site = self.parameterAsString(parameters, self.SITE, context)
        lon = self.parameterAsDouble(parameters, self.LON, context)
        lat = self.parameterAsDouble(parameters, self.LAT, context)
        api = self.parameterAsString(parameters, self.API, context)
        pa = B.point_attributes(B.fetch_json(B.point_url(api, site, lon, lat)))
        fields = QgsFields()
        fields.append(QgsField("site", QVariant.String))
        for a in pa["attributes"]:
            fields.append(QgsField(str(a["id"]), QVariant.String))   # String keeps mixed value types (float/bool) honest
        crs = QgsCoordinateReferenceSystem("IAU_2015:30100")
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields, QgsWkbTypes.Point, crs)
        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        feat.setAttributes([pa["site"]] + [str(a["value"]) for a in pa["attributes"]])
        sink.addFeature(feat, QgsFeatureSink.FastInsert)
        feedback.pushInfo("STEWIE: sampled %d terms at (%s, %s) on %s" % (len(pa["attributes"]), lon, lat, site))
        return {self.OUTPUT: dest}

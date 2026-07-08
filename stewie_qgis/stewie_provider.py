"""STEWIE QGIS Processing provider + the plugin wrapper classFactory returns. Registers the STEWIE
algorithms under the 'stewie' provider so they appear in the QGIS Toolbox / qgis_process / batch / Models.
qgis.* is imported here (loaded only under a real QGIS runtime; the CI pytest never imports this module).
"""
from qgis.core import QgsApplication, QgsProcessingProvider

from .stewie_algorithms import StewieSamplePointAlgorithm, StewieTerramechanicsAlgorithm


class StewieProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(StewieTerramechanicsAlgorithm())
        self.addAlgorithm(StewieSamplePointAlgorithm())

    def id(self):
        return "stewie"

    def name(self):
        return "STEWIE"

    def longName(self):
        return "STEWIE lunar mission-planning"


class StewiePlugin:
    """The plugin object classFactory returns; registers the provider on load, removes it on unload."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initProcessing(self):
        self.provider = StewieProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)

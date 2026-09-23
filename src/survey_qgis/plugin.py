"""QGIS plugin entry point: registers the Survey Suite provider.

QGIS instantiates this via ``classFactory(iface)`` in ``__init__.py``.
All QGIS imports are deferred to method bodies so the module imports
safely outside QGIS (tests, packaging, CLI).
"""

from __future__ import annotations


class SurveySuitePlugin:
    """QGIS plugin class: provider registration lifecycle."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initGui(self):  # noqa: N802 (QGIS API naming)
        from qgis.core import QgsApplication
        from .qgis_provider import create_provider
        self.provider = create_provider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        from qgis.core import QgsApplication
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

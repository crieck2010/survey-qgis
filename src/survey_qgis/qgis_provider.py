"""QGIS Processing provider for the survey suite.

:func:`create_provider` builds the provider instance. The ``qgis`` import
happens inside the factory so this module imports cleanly without QGIS
installed; the factory raises a clear error when QGIS is missing.
"""

from __future__ import annotations


def create_provider():
    """Create the Survey Suite Processing provider (QGIS only)."""
    try:
        from qgis.core import QgsProcessingProvider
    except ImportError as exc:
        raise RuntimeError(
            "QGIS Python API (qgis.core) is not available. The provider only "
            "runs inside QGIS. Use 'survey-qgis run' for headless execution."
        ) from exc

    from .algorithms import ALGORITHMS
    from .qgis_algorithm import create_algorithm_class

    class SurveySuiteProvider(QgsProcessingProvider):
        def id(self) -> str:  # noqa: N802 (QGIS API naming)
            return "surveysuite"

        def name(self) -> str:
            return "Survey Suite"

        def icon(self):
            return QgsProcessingProvider.icon(self)

        def loadAlgorithms(self):  # noqa: N802 (QGIS API naming)
            for spec in ALGORITHMS.values():
                self.addAlgorithm(create_algorithm_class(spec)())

    return SurveySuiteProvider()

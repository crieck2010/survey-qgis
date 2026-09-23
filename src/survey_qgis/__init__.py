"""survey-qgis: QGIS distribution layer for the survey suite.

This package is *both* a pip-installable library/CLI and a QGIS plugin:
the package directory itself is the plugin folder (``metadata.txt`` +
``classFactory`` live here), so ``survey-qgis package`` zips it straight
into a QGIS-installable archive.

Layering
--------
- :mod:`survey_qgis.params`, :mod:`survey_qgis.algorithms`,
  :mod:`survey_qgis.runners`, :mod:`survey_qgis.interop` — pure logic,
  importable anywhere, no QGIS and no engine imports at module load.
- :mod:`survey_qgis.qgis_algorithm`, :mod:`survey_qgis.qgis_provider`,
  :mod:`survey_qgis.plugin` — thin QGIS adapter; ``qgis`` imports are
  deferred into factory functions so the modules import without QGIS.
- :mod:`survey_qgis.cli` — headless runner over the same specs/runners.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__", "classFactory"]


def classFactory(iface):  # noqa: N802 (QGIS plugin API naming)
    """QGIS plugin entry point. Called by QGIS on plugin load."""
    from .plugin import SurveySuitePlugin
    return SurveySuitePlugin(iface)

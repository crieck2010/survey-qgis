"""Single source of truth for QGIS plugin metadata (metadata.txt).

:func:`render_metadata_txt` generates the ``metadata.txt`` QGIS reads from
the plugin folder. ``survey-qgis metadata`` regenerates the committed copy.
"""

from __future__ import annotations

from . import __version__

METADATA = {
    "name": "Survey Suite",
    "description": (
        "QGIS Processing provider for the survey-suite engines: change "
        "detection (survey-change), spectral indices (survey-imagery), and "
        "COGO computations (survey-cogo), runnable from the Processing "
        "toolbox or the model designer."
    ),
    "version": __version__,
    "qgisMinimumVersion": "3.16",
    "author": "crieck2010",
    "email": "",
    "about": (
        "Exposes the survey-suite Python engines as QGIS Processing "
        "algorithms under a 'Survey Suite' provider. Engines are imported "
        "lazily; install the ones you need (survey-change, survey-imagery, "
        "survey-cogo) alongside this plugin."
    ),
    "tracker": "https://github.com/crieck2010/survey-qgis/issues",
    "repository": "https://github.com/crieck2010/survey-qgis",
    "homepage": "https://github.com/crieck2010/survey-qgis",
    "category": "Analysis",
    "icon": "",
    "experimental": "False",
    "deprecated": "False",
}

# metadata.txt format: "[general]" header followed by key=value lines.
_FIELD_ORDER = (
    "name", "description", "version", "qgisMinimumVersion", "author", "email",
    "about", "tracker", "repository", "homepage", "category", "icon",
    "experimental", "deprecated",
)


def render_metadata_txt() -> str:
    lines = ["[general]", ""]
    for key in _FIELD_ORDER:
        lines.append(f"{key}={METADATA[key]}")
    return "\n".join(lines) + "\n"


def write_metadata_txt(path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_metadata_txt())
    return path

"""Suite-engine interop: lazy imports with clear missing-engine errors.

``survey-qgis`` intentionally declares **zero** install dependencies. Every
suite engine (``cogo``, ``imagery``, ``change``, ...) is imported lazily by
the runner that needs it. When an engine is missing, the user gets an
``EngineMissingError`` naming the exact ``pip install`` command — never a
bare ``ImportError`` traceback.
"""

from __future__ import annotations

import importlib
from typing import Dict, Optional

# pip package name -> import name, for every engine this layer can drive.
ENGINES: Dict[str, str] = {
    "survey-cogo": "cogo",
    "survey-levels": "levels",
    "survey-adjust": "adjust",
    "survey-geodesy": "geodesy",
    "survey-raster": "raster",
    "survey-pointcloud": "pointcloud",
    "survey-gnss": "gnss",
    "survey-imagery": "imagery",
    "survey-change": "change",
}

_GITHUB = "https://github.com/crieck2010"


class EngineMissingError(ImportError):
    """Raised when a wrapped suite engine is not installed."""

    def __init__(self, pip_name: str, install_hint: str = ""):
        self.pip_name = pip_name
        hint = install_hint or f"pip install git+{_GITHUB}/{pip_name}.git"
        super().__init__(
            f"This algorithm needs '{pip_name}', which is not installed. "
            f"Install it with: {hint}"
        )


def require_engine(pip_name: str):
    """Import a suite engine by pip name, or raise EngineMissingError."""
    if pip_name not in ENGINES:
        raise ValueError(f"unknown engine: {pip_name!r}")
    try:
        return importlib.import_module(ENGINES[pip_name])
    except ImportError as exc:
        raise EngineMissingError(pip_name) from exc


def engine_version(pip_name: str) -> Optional[str]:
    """Installed version of an engine, or None when not installed."""
    if pip_name not in ENGINES:
        raise ValueError(f"unknown engine: {pip_name!r}")
    try:
        mod = importlib.import_module(ENGINES[pip_name])
    except ImportError:
        return None
    return getattr(mod, "__version__", "unknown")


def check_engines() -> Dict[str, Optional[str]]:
    """Map every known engine to its installed version (None if missing)."""
    return {pip: engine_version(pip) for pip in ENGINES}


def require_rasterio():
    """Import rasterio, or raise a clear error (needed for raster runners)."""
    try:
        return importlib.import_module("rasterio")
    except ImportError as exc:
        raise EngineMissingError("rasterio",
                                 install_hint="pip install rasterio") from exc

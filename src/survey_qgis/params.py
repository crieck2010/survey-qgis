"""Parameter and output specifications (pure data, no QGIS imports).

A :class:`ParameterSpec` describes one algorithm input in QGIS-agnostic
terms; :class:`OutputSpec` describes one result. The QGIS adapter layer
(:mod:`survey_qgis.qgis_algorithm`) maps these onto
``QgsProcessingParameter*`` classes, while the CLI and tests use them
directly. Adding a new algorithm never requires touching QGIS code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Tuple

# Input parameter types
PARAM_RASTER = "raster"    # raster layer / raster file path
PARAM_VECTOR = "vector"    # vector layer / vector file path
PARAM_FILE = "file"        # generic input file path
PARAM_FOLDER = "folder"    # input folder path
PARAM_ENUM = "enum"        # choice from a fixed list
PARAM_NUMBER = "number"    # float
PARAM_INTEGER = "integer"  # int
PARAM_STRING = "string"
PARAM_BOOLEAN = "boolean"

# Output types
OUTPUT_RASTER = "raster"   # raster file written by the algorithm
OUTPUT_VECTOR = "vector"   # vector file written by the algorithm
OUTPUT_FILE = "file"       # generic file written by the algorithm
OUTPUT_FOLDER = "folder"   # folder written by the algorithm
OUTPUT_NUMBER = "number"   # scalar numeric result
OUTPUT_STRING = "string"   # scalar text result


@dataclass(frozen=True)
class ParameterSpec:
    """One algorithm input parameter."""

    name: str
    label: str
    type: str
    default: Any = None
    optional: bool = False
    options: Tuple[str, ...] = ()
    help: str = ""

    def __post_init__(self) -> None:
        valid = {PARAM_RASTER, PARAM_VECTOR, PARAM_FILE, PARAM_FOLDER,
                 PARAM_ENUM, PARAM_NUMBER, PARAM_INTEGER, PARAM_STRING,
                 PARAM_BOOLEAN}
        if self.type not in valid:
            raise ValueError(f"unknown parameter type: {self.type!r}")
        if self.type == PARAM_ENUM and not self.options:
            raise ValueError(f"enum parameter {self.name!r} needs options")


@dataclass(frozen=True)
class OutputSpec:
    """One algorithm output."""

    name: str
    label: str
    type: str

    def __post_init__(self) -> None:
        valid = {OUTPUT_RASTER, OUTPUT_VECTOR, OUTPUT_FILE, OUTPUT_FOLDER,
                 OUTPUT_NUMBER, OUTPUT_STRING}
        if self.type not in valid:
            raise ValueError(f"unknown output type: {self.type!r}")

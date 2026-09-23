"""Algorithm specifications and registry (pure data + validation).

Each :class:`AlgorithmSpec` fully describes one QGIS Processing algorithm:
its id, display name, group, parameters, outputs, the runner function that
implements it, and which suite engines it needs. The QGIS adapter, the CLI,
and the docs are all generated from this single source of truth — adding a
new algorithm means appending one spec here and one runner in
:mod:`survey_qgis.runners`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .interop import ENGINES
from .params import (
    OUTPUT_FILE,
    OUTPUT_FOLDER,
    OUTPUT_NUMBER,
    OUTPUT_RASTER,
    OUTPUT_STRING,
    OUTPUT_VECTOR,
    PARAM_BOOLEAN,
    PARAM_ENUM,
    PARAM_FILE,
    PARAM_INTEGER,
    PARAM_NUMBER,
    PARAM_RASTER,
    PARAM_STRING,
    OutputSpec,
    ParameterSpec,
)


@dataclass(frozen=True)
class AlgorithmSpec:
    """Complete description of one Processing algorithm."""

    id: str                    # stable id, e.g. "detect_change"
    name: str                  # display name in the Processing toolbox
    group: str                 # toolbox group, e.g. "Change detection"
    description: str           # short help shown in QGIS
    params: Tuple[ParameterSpec, ...]
    outputs: Tuple[OutputSpec, ...]
    runner: str                # function name in survey_qgis.runners
    engines: Tuple[str, ...] = ()  # required pip packages (suite engines)

    def __post_init__(self) -> None:
        for eng in self.engines:
            if eng not in ENGINES and eng != "rasterio":
                raise ValueError(f"unknown engine requirement: {eng!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "group": self.group,
            "description": self.description,
            "runner": self.runner,
            "engines": list(self.engines),
            "params": [
                {"name": p.name, "label": p.label, "type": p.type,
                 "default": p.default, "optional": p.optional,
                 "options": list(p.options), "help": p.help}
                for p in self.params
            ],
            "outputs": [
                {"name": o.name, "label": o.label, "type": o.type}
                for o in self.outputs
            ],
        }


def _p(name: str, label: str, type: str, default: Any = None,
       optional: bool = False, options: Tuple[str, ...] = (),
       help: str = "") -> ParameterSpec:
    return ParameterSpec(name=name, label=label, type=type, default=default,
                         optional=optional, options=options, help=help)


def _o(name: str, label: str, type: str) -> OutputSpec:
    return OutputSpec(name=name, label=label, type=type)


ALGORITHMS: Dict[str, AlgorithmSpec] = {}


def _register(spec: AlgorithmSpec) -> AlgorithmSpec:
    if spec.id in ALGORITHMS:
        raise ValueError(f"duplicate algorithm id: {spec.id!r}")
    ALGORITHMS[spec.id] = spec
    return spec


# --- Change detection (survey-change) -------------------------------------

_register(AlgorithmSpec(
    id="detect_change",
    name="Detect change between two rasters",
    group="Change detection",
    description="Compare an earlier and a later raster with a survey-change "
                "operator, threshold the change, and write a difference COG, "
                "a binary change mask, and a JSON summary report.",
    params=(
        _p("t1", "Earlier raster", PARAM_RASTER,
           help="Baseline acquisition (e.g. NDVI COG from survey-imagery)."),
        _p("t2", "Later raster", PARAM_RASTER,
           help="Comparison acquisition. Must align with the earlier raster."),
        _p("method", "Change method", PARAM_ENUM, default="difference",
           options=("difference", "normalized_difference", "relative_change",
                    "ratio", "cva")),
        _p("threshold_method", "Threshold method", PARAM_ENUM, default="otsu",
           options=("otsu", "manual", "percentile", "none")),
        _p("threshold", "Manual threshold", PARAM_NUMBER, default=0.2,
           optional=True, help="Used only with the manual threshold method."),
        _p("min_region_pixels", "Minimum region size (pixels)", PARAM_INTEGER,
           default=4, help="Drop change regions smaller than this."),
    ),
    outputs=(
        _o("difference", "Difference raster", OUTPUT_RASTER),
        _o("mask", "Change mask", OUTPUT_RASTER),
        _o("report", "Summary report", OUTPUT_FILE),
        _o("changed_pixels", "Changed pixels", OUTPUT_NUMBER),
    ),
    runner="run_detect_change",
    engines=("survey-change",),
))

_register(AlgorithmSpec(
    id="change_polygons",
    name="Vectorize change mask to polygons",
    group="Change detection",
    description="Label connected change regions in a binary mask and export "
                "them as polygons with area and per-region change statistics.",
    params=(
        _p("mask", "Change mask raster", PARAM_RASTER,
           help="Binary mask (nonzero = change), e.g. from Detect change."),
        _p("change_raster", "Signed change raster", PARAM_RASTER, optional=True,
           help="Optional: adds mean/min/max change attributes per polygon."),
        _p("simplify", "Simplification tolerance (map units)", PARAM_NUMBER,
           default=0.0, help="Douglas-Peucker tolerance; 0 disables."),
        _p("min_region_pixels", "Minimum region size (pixels)", PARAM_INTEGER,
           default=1),
    ),
    outputs=(
        _o("polygons", "Change polygons", OUTPUT_VECTOR),
        _o("feature_count", "Polygon count", OUTPUT_NUMBER),
    ),
    runner="run_change_polygons",
    engines=("survey-change",),
))

_register(AlgorithmSpec(
    id="classify_change",
    name="Post-classification change comparison",
    group="Change detection",
    description="Compare two land-cover label rasters and produce a from-to "
                "transition raster, a transition area table (CSV), and a "
                "summary report.",
    params=(
        _p("t1_labels", "Earlier label raster", PARAM_RASTER),
        _p("t2_labels", "Later label raster", PARAM_RASTER),
        _p("class_names", "Class names JSON", PARAM_FILE, optional=True,
           help='Optional JSON mapping, e.g. {"1": "forest"}.'),
    ),
    outputs=(
        _o("transition", "Transition raster", OUTPUT_RASTER),
        _o("table", "Transition table", OUTPUT_FILE),
        _o("changed_pixels", "Changed pixels", OUTPUT_NUMBER),
    ),
    runner="run_classify_change",
    engines=("survey-change",),
))

_register(AlgorithmSpec(
    id="timeseries_breaks",
    name="Find breaks in a monitor time series",
    group="Change detection",
    description="Scan a survey-imagery monitor timeseries.csv for abrupt "
                "breaks in an index's mean value between consecutive passes.",
    params=(
        _p("timeseries_csv", "Monitor timeseries.csv", PARAM_FILE),
        _p("index", "Spectral index", PARAM_STRING, default="NDVI"),
        _p("threshold", "Break threshold", PARAM_NUMBER, default=0.15,
           help="Minimum absolute mean-value step to report."),
    ),
    outputs=(
        _o("breaks", "Breaks table", OUTPUT_FILE),
        _o("break_count", "Break count", OUTPUT_NUMBER),
    ),
    runner="run_timeseries_breaks",
    engines=("survey-change",),
))

# --- Spectral indices (survey-imagery) ------------------------------------

_register(AlgorithmSpec(
    id="spectral_index",
    name="Compute spectral index",
    group="Imagery",
    description="Compute a survey-imagery spectral index (NDVI, NDWI, EVI, "
                "...) from per-band rasters and write it as a GeoTIFF.",
    params=(
        _p("index", "Index", PARAM_ENUM, default="NDVI",
           options=("NDVI", "NDWI", "NDMI", "NDBI", "NBR", "EVI", "SAVI", "BSI")),
        _p("red", "Red band raster", PARAM_RASTER, optional=True),
        _p("nir", "NIR band raster", PARAM_RASTER, optional=True),
        _p("green", "Green band raster", PARAM_RASTER, optional=True),
        _p("blue", "Blue band raster", PARAM_RASTER, optional=True),
        _p("swir1", "SWIR1 band raster", PARAM_RASTER, optional=True),
        _p("swir2", "SWIR2 band raster", PARAM_RASTER, optional=True),
    ),
    outputs=(
        _o("index_raster", "Index raster", OUTPUT_RASTER),
        _o("index_name", "Index name", OUTPUT_STRING),
    ),
    runner="run_spectral_index",
    engines=("survey-imagery", "rasterio"),
))

# --- COGO (survey-cogo) ----------------------------------------------------

_register(AlgorithmSpec(
    id="cogo_inverse",
    name="COGO inverse (bearing & distance)",
    group="COGO",
    description="Compute the azimuth, bearing, and horizontal distance "
                "between two plane-coordinate points.",
    params=(
        _p("northing1", "From northing (Y)", PARAM_NUMBER, default=0.0),
        _p("easting1", "From easting (X)", PARAM_NUMBER, default=0.0),
        _p("northing2", "To northing (Y)", PARAM_NUMBER, default=0.0),
        _p("easting2", "To easting (X)", PARAM_NUMBER, default=100.0),
    ),
    outputs=(
        _o("azimuth", "Azimuth (degrees)", OUTPUT_NUMBER),
        _o("bearing", "Bearing", OUTPUT_STRING),
        _o("distance", "Horizontal distance", OUTPUT_NUMBER),
    ),
    runner="run_cogo_inverse",
    engines=("survey-cogo",),
))

_register(AlgorithmSpec(
    id="cogo_forward",
    name="COGO forward (point by azimuth & distance)",
    group="COGO",
    description="Compute a new point from a start point, an azimuth, and a "
                "horizontal distance.",
    params=(
        _p("northing", "Start northing (Y)", PARAM_NUMBER, default=0.0),
        _p("easting", "Start easting (X)", PARAM_NUMBER, default=0.0),
        _p("azimuth", "Azimuth (degrees)", PARAM_NUMBER, default=0.0),
        _p("distance", "Horizontal distance", PARAM_NUMBER, default=100.0),
    ),
    outputs=(
        _o("northing_out", "Result northing (Y)", OUTPUT_NUMBER),
        _o("easting_out", "Result easting (X)", OUTPUT_NUMBER),
    ),
    runner="run_cogo_forward",
    engines=("survey-cogo",),
))

_register(AlgorithmSpec(
    id="cogo_polygon_area",
    name="COGO polygon area & perimeter",
    group="COGO",
    description="Compute the area (coordinate method) and perimeter of a "
                "polygon given as 'easting,northing;...' vertex pairs.",
    params=(
        _p("vertices", "Vertices (E,N;...)", PARAM_STRING,
           default="0,0;100,0;100,100;0,100",
           help="Semicolon-separated easting,northing pairs."),
    ),
    outputs=(
        _o("area", "Area (square units)", OUTPUT_NUMBER),
        _o("perimeter", "Perimeter (units)", OUTPUT_NUMBER),
    ),
    runner="run_cogo_polygon_area",
    engines=("survey-cogo",),
))


# --- Registry access --------------------------------------------------------

def get_algorithm(algorithm_id: str) -> AlgorithmSpec:
    """Return the spec for ``algorithm_id`` or raise KeyError."""
    try:
        return ALGORITHMS[algorithm_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown algorithm {algorithm_id!r}; "
            f"available: {sorted(ALGORITHMS)}"
        ) from exc


def list_algorithms(group: Optional[str] = None) -> List[AlgorithmSpec]:
    """All specs, optionally filtered by group, in registration order."""
    specs = list(ALGORITHMS.values())
    if group is not None:
        specs = [s for s in specs if s.group == group]
    return specs


def list_groups() -> List[str]:
    """Toolbox group names in first-seen order."""
    groups: List[str] = []
    for spec in ALGORITHMS.values():
        if spec.group not in groups:
            groups.append(spec.group)
    return groups


class ParamValidationError(ValueError):
    """Raised when runner parameters fail spec validation."""


def validate_params(spec: AlgorithmSpec, params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate ``params`` against ``spec`` and fill in defaults.

    Returns a normalized dict. Raises :class:`ParamValidationError` on
    missing required params, bad enum choices, or wrong scalar types.
    File/raster/vector params are passed through as path strings (QGIS
    hands the adapter layer objects; the adapter converts to paths first).
    """
    out: Dict[str, Any] = {}
    # File-ish outputs double as *destination parameters*: in QGIS they are
    # QgsProcessingParameter*Destination entries, and headless callers pass
    # plain paths under the output name. Accept them alongside params.
    dest_names = {o.name for o in spec.outputs
                  if o.type in (OUTPUT_RASTER, OUTPUT_VECTOR, OUTPUT_FILE, OUTPUT_FOLDER)}
    for p in spec.params:
        if p.name in params and params[p.name] not in (None, ""):
            value = params[p.name]
        elif p.optional:
            value = p.default
        elif p.default is not None:
            value = p.default
        else:
            raise ParamValidationError(
                f"algorithm '{spec.id}' is missing required parameter '{p.name}'"
            )
        out[p.name] = _coerce(p, value, spec.id)
    for name in dest_names:
        if name in params and params[name] not in (None, ""):
            out[name] = params[name]
        else:
            # Optional file outputs may be omitted; required ones must exist.
            opt = next(o for o in spec.outputs if o.name == name)
            if _output_optional(spec, name):
                out[name] = None
            else:
                raise ParamValidationError(
                    f"algorithm '{spec.id}' is missing the destination path "
                    f"for output '{name}'"
                )
    unknown = set(params) - {p.name for p in spec.params} - dest_names
    if unknown:
        raise ParamValidationError(
            f"algorithm '{spec.id}' got unknown parameters: {sorted(unknown)}"
        )
    return out


def _output_optional(spec: AlgorithmSpec, name: str) -> bool:
    # Only the summary-report style sidecars are optional; every layer
    # output is required. (Kept as a helper so the rule lives in one place.)
    return name in ("report",)


def _coerce(p: ParameterSpec, value: Any, algo_id: str) -> Any:
    if value is None:
        return None
    try:
        if p.type == PARAM_ENUM:
            if value not in p.options:
                raise ParamValidationError(
                    f"algorithm '{algo_id}': parameter '{p.name}' must be one of "
                    f"{list(p.options)}, got {value!r}"
                )
            return value
        if p.type == PARAM_NUMBER:
            return float(value)
        if p.type == PARAM_INTEGER:
            ivalue = int(float(value))
            if float(value) != ivalue:
                raise ParamValidationError(
                    f"algorithm '{algo_id}': parameter '{p.name}' must be an "
                    f"integer, got {value!r}"
                )
            return ivalue
        if p.type == PARAM_BOOLEAN:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "y")
            return bool(value)
        return value  # raster/vector/file/folder/string pass through as given
    except ParamValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise ParamValidationError(
            f"algorithm '{algo_id}': parameter '{p.name}' has an invalid value "
            f"{value!r}: {exc}"
        ) from exc

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
    PARAM_FOLDER,
    PARAM_INTEGER,
    PARAM_NUMBER,
    PARAM_RASTER,
    PARAM_STRING,
    PARAM_VECTOR,
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

# --- Imagery extras (survey-imagery) -----------------------------------------

_register(AlgorithmSpec(
    id="imagery_composite",
    name="Temporal composite of index rasters",
    group="Imagery",
    description="Stack same-shape index rasters from a folder and composite "
                "them (median/mean/max/min, NaN-aware) into one GeoTIFF.",
    params=(
        _p("input_folder", "Input rasters folder", PARAM_FOLDER,
           help="Folder of same-shape index rasters (e.g. per-pass NDVI)."),
        _p("method", "Composite method", PARAM_ENUM, default="median",
           options=("median", "mean", "max", "min")),
    ),
    outputs=(
        _o("composite", "Composite raster", OUTPUT_RASTER),
        _o("scene_count", "Scenes composited", OUTPUT_NUMBER),
    ),
    runner="run_imagery_composite",
    engines=("survey-imagery", "rasterio"),
))

_register(AlgorithmSpec(
    id="imagery_zonal_timeseries",
    name="Zonal time series from an index raster",
    group="Imagery",
    description="Compute per-zone statistics of an index raster inside "
                "polygons from a zones file, and append one record per zone "
                "to a survey-imagery time-series CSV.",
    params=(
        _p("index_raster", "Index raster", PARAM_RASTER),
        _p("zones", "Zones vector", PARAM_VECTOR,
           help="Polygons with an id/name attribute; CRS given below."),
        _p("zones_crs", "Zones CRS", PARAM_STRING, default="EPSG:4326"),
        _p("pass_id", "Pass id", PARAM_STRING, default="",
           help="Scene/pass identifier recorded in the CSV."),
        _p("pass_date", "Pass date (YYYY-MM-DD)", PARAM_STRING, default=""),
        _p("index_name", "Index name", PARAM_STRING, default="NDVI"),
        _p("cloud_cover", "Cloud cover (%)", PARAM_NUMBER, optional=True),
    ),
    outputs=(
        _o("timeseries_csv", "Time-series CSV", OUTPUT_FILE),
        _o("zone_count", "Zones processed", OUTPUT_NUMBER),
    ),
    runner="run_imagery_zonal_timeseries",
    engines=("survey-imagery", "rasterio"),
))

# --- Site monitoring (survey-monitor) ---------------------------------------

_register(AlgorithmSpec(
    id="monitor_run",
    name="Run site monitoring config",
    group="Site monitoring",
    description="Run a survey-monitor site config headlessly: list new "
                "satellite passes, compute per-pass index metrics, evaluate "
                "thresholds, and append alert events (alerts.jsonl + "
                "alerts.geojson) to the store folder.",
    params=(
        _p("site_config", "Site config file", PARAM_FILE,
           help="Site JSON/YAML config (see survey-monitor docs/SITE_CONFIG.md)."),
        _p("synthetic", "Use synthetic passes (no network)", PARAM_BOOLEAN,
           default=True,
           help="Seeded demo pass provider. Uncheck for live STAC "
                "acquisition (needs network + survey-imagery)."),
        _p("since", "Only passes since (YYYY-MM-DD)", PARAM_STRING,
           default="", optional=True),
    ),
    outputs=(
        _o("store_folder", "Monitor store folder", OUTPUT_FOLDER),
        _o("passes_processed", "Passes processed", OUTPUT_NUMBER),
        _o("alerts_fired", "Alerts fired", OUTPUT_NUMBER),
    ),
    runner="run_monitor_run",
    engines=("survey-monitor",),
))

_register(AlgorithmSpec(
    id="monitor_alerts_map",
    name="Alerts to GeoJSON layer",
    group="Site monitoring",
    description="Read a survey-monitor site's alerts.jsonl from its store "
                "folder and write a QGIS-ready alerts GeoJSON layer.",
    params=(
        _p("store_folder", "Monitor store folder", PARAM_FOLDER),
        _p("site_id", "Site id", PARAM_STRING),
        _p("severity", "Severity filter", PARAM_ENUM,
           default="all", options=("all", "info", "warning", "critical")),
    ),
    outputs=(
        _o("alerts_geojson", "Alerts GeoJSON", OUTPUT_VECTOR),
        _o("alert_count", "Alert count", OUTPUT_NUMBER),
    ),
    runner="run_monitor_alerts_map",
    engines=("survey-monitor",),
))

# --- Vegetation (survey-vegetation) ------------------------------------------

_register(AlgorithmSpec(
    id="vegetation_vigor_map",
    name="Vigor-class map",
    group="Vegetation",
    description="Classify a vigor-index raster (NDVI/EVI/SAVI) into vigor "
                "bands (water/bare/stressed/moderate/vigorous/very dense) "
                "and write a uint8 class GeoTIFF with a QGIS style sidecar.",
    params=(
        _p("index_raster", "Vigor index raster", PARAM_RASTER,
           help="e.g. an NDVI raster from Compute spectral index."),
    ),
    outputs=(
        _o("vigor_map", "Vigor-class raster", OUTPUT_RASTER),
        _o("classes_found", "Vigor classes present", OUTPUT_NUMBER),
    ),
    runner="run_vegetation_vigor_map",
    engines=("survey-vegetation", "rasterio"),
))

_register(AlgorithmSpec(
    id="vegetation_timeseries",
    name="Per-zone vigor time series",
    group="Vegetation",
    description="Compute per-zone vigor statistics of an index raster and "
                "append one record per zone to a survey-vegetation "
                "time-series CSV (incremental, deduplicated).",
    params=(
        _p("index_raster", "Vigor index raster", PARAM_RASTER),
        _p("zones", "Zones vector", PARAM_VECTOR),
        _p("pass_id", "Pass id", PARAM_STRING, default=""),
        _p("pass_date", "Pass date (YYYY-MM-DD)", PARAM_STRING, default=""),
        _p("index_name", "Index name", PARAM_STRING, default="NDVI"),
        _p("cloud_cover", "Cloud cover (%)", PARAM_NUMBER, optional=True),
    ),
    outputs=(
        _o("timeseries_csv", "Time-series CSV", OUTPUT_FILE),
        _o("zone_count", "Zones processed", OUTPUT_NUMBER),
    ),
    runner="run_vegetation_timeseries",
    engines=("survey-vegetation", "rasterio"),
))

# --- Flood (survey-flood) -----------------------------------------------------

_register(AlgorithmSpec(
    id="flood_water_mask",
    name="Water mask from index raster",
    group="Flood",
    description="Threshold an NDWI/MNDWI raster into a boolean water mask, "
                "despeckle it, and write a uint8 mask GeoTIFF with a QGIS "
                "style sidecar.",
    params=(
        _p("index_raster", "Water index raster", PARAM_RASTER,
           help="NDWI or MNDWI raster; water where index >= threshold."),
        _p("threshold", "Water threshold", PARAM_NUMBER, default=0.0),
        _p("despeckle_pixels", "Despeckle size (pixels)", PARAM_INTEGER,
           default=4, help="Drop water components smaller than this."),
    ),
    outputs=(
        _o("water_mask", "Water mask raster", OUTPUT_RASTER),
        _o("water_pixels", "Water pixels", OUTPUT_NUMBER),
    ),
    runner="run_flood_water_mask",
    engines=("survey-flood", "rasterio"),
))

_register(AlgorithmSpec(
    id="flood_polygons",
    name="Flood-extent polygons",
    group="Flood",
    description="Vectorize a binary water mask into flood-extent polygons "
                "(GeoJSON) with per-feature pixel counts and area in hectares.",
    params=(
        _p("water_mask", "Water mask raster", PARAM_RASTER,
           help="Binary mask (nonzero = water), e.g. from Water mask."),
        _p("min_pixels", "Minimum region size (pixels)", PARAM_INTEGER,
           default=4),
    ),
    outputs=(
        _o("polygons", "Flood polygons", OUTPUT_VECTOR),
        _o("feature_count", "Polygon count", OUTPUT_NUMBER),
    ),
    runner="run_flood_polygons",
    engines=("survey-flood", "rasterio"),
))

# --- Burn (survey-burn) --------------------------------------------------------

_register(AlgorithmSpec(
    id="burn_severity",
    name="dNBR burn severity",
    group="Burn",
    description="Compute dNBR (pre-fire NBR minus post-fire NBR) from two "
                "NBR rasters and classify it into USGS fire-severity bands; "
                "writes a dNBR raster and a severity-class raster with QGIS "
                "style sidecars.",
    params=(
        _p("pre_nbr", "Pre-fire NBR raster", PARAM_RASTER),
        _p("post_nbr", "Post-fire NBR raster", PARAM_RASTER,
           help="Must align with the pre-fire raster."),
    ),
    outputs=(
        _o("dnbr", "dNBR raster", OUTPUT_RASTER),
        _o("severity", "Severity-class raster", OUTPUT_RASTER),
        _o("burned_pixels", "Burned pixels", OUTPUT_NUMBER),
    ),
    runner="run_burn_severity",
    engines=("survey-burn", "rasterio"),
))

# --- Coast (survey-coast) ------------------------------------------------------

_register(AlgorithmSpec(
    id="coast_shoreline",
    name="Extract shoreline from water mask",
    group="Coast",
    description="Trace the water/land boundary of a binary water mask into "
                "shoreline polylines (GeoJSON LineStrings, map meters).",
    params=(
        _p("water_mask", "Water mask raster", PARAM_RASTER,
           help="Binary mask (nonzero = water)."),
        _p("pixel_size_m", "Pixel size (m)", PARAM_NUMBER, default=10.0),
        _p("min_length_m", "Minimum shoreline length (m)", PARAM_NUMBER,
           default=0.0, help="Drop shorter fragments (ponds, speckle)."),
    ),
    outputs=(
        _o("shoreline", "Shoreline GeoJSON", OUTPUT_VECTOR),
        _o("segment_count", "Shoreline segments", OUTPUT_NUMBER),
    ),
    runner="run_coast_shoreline",
    engines=("survey-coast", "rasterio"),
))

_register(AlgorithmSpec(
    id="coast_transect_positions",
    name="Shoreline positions on transects",
    group="Coast",
    description="Intersect a shoreline GeoJSON with transect lines and "
                "append per-transect shoreline positions (meters from "
                "transect origin) to a positions CSV for rate analysis.",
    params=(
        _p("shoreline", "Shoreline GeoJSON", PARAM_VECTOR),
        _p("transects", "Transects vector", PARAM_VECTOR,
           help="Line features running landward to seaward."),
        _p("pass_id", "Pass id", PARAM_STRING, default=""),
        _p("pass_date", "Pass date (YYYY-MM-DD)", PARAM_STRING, default=""),
        _p("index_name", "Water index used", PARAM_STRING, default="ndwi"),
        _p("pixel_size_m", "Pixel size (m)", PARAM_NUMBER, default=10.0),
    ),
    outputs=(
        _o("positions_csv", "Positions CSV", OUTPUT_FILE),
        _o("transect_count", "Transects processed", OUTPUT_NUMBER),
    ),
    runner="run_coast_transect_positions",
    engines=("survey-coast",),
))

# --- Thermal (survey-thermal) --------------------------------------------------

_register(AlgorithmSpec(
    id="thermal_lst",
    name="Land surface temperature (LST)",
    group="Thermal",
    description="Convert a Landsat Collection-2 Level-2 ST_B10 surface-"
                "temperature raster (DN) to land surface temperature in "
                "Celsius, with a QGIS style sidecar.",
    params=(
        _p("st_raster", "ST_B10 DN raster", PARAM_RASTER,
           help="Landsat C2L2 surface-temperature band (DN = K x 0.01)."),
    ),
    outputs=(
        _o("lst_celsius", "LST raster (Celsius)", OUTPUT_RASTER),
        _o("mean_celsius", "Mean LST (Celsius)", OUTPUT_NUMBER),
    ),
    runner="run_thermal_lst",
    engines=("survey-thermal", "rasterio"),
))

_register(AlgorithmSpec(
    id="thermal_uhi",
    name="Urban heat-island intensity",
    group="Thermal",
    description="Compute per-zone urban heat-island intensity (zone mean "
                "LST minus rural reference zone mean, in C) from an LST "
                "raster and write a UHI CSV.",
    params=(
        _p("lst_raster", "LST raster (Celsius)", PARAM_RASTER),
        _p("zones", "Zones vector", PARAM_VECTOR),
        _p("reference_zone", "Reference zone id", PARAM_STRING, default="",
           optional=True,
           help="Rural reference zone; blank auto-selects the coolest zone."),
        _p("pass_id", "Pass id", PARAM_STRING, default=""),
        _p("pass_date", "Pass date (YYYY-MM-DD)", PARAM_STRING, default=""),
    ),
    outputs=(
        _o("uhi_csv", "UHI CSV", OUTPUT_FILE),
        _o("zone_count", "Zones processed", OUTPUT_NUMBER),
    ),
    runner="run_thermal_uhi",
    engines=("survey-thermal", "rasterio"),
))

# --- Elevation (survey-3d) -----------------------------------------------------

_register(AlgorithmSpec(
    id="dem_difference",
    name="DEM difference raster",
    group="Elevation",
    description="Difference two aligned DEM rasters (later minus earlier) "
                "with a noise floor; writes the elevation-change raster "
                "(meters) with a QGIS style sidecar.",
    params=(
        _p("dem1", "Earlier DEM raster", PARAM_RASTER),
        _p("dem2", "Later DEM raster", PARAM_RASTER,
           help="Must align with the earlier DEM (same grid/CRS)."),
        _p("noise_floor", "Noise floor (m)", PARAM_NUMBER, default=0.0,
           help="|dh| below this counts as no-change."),
    ),
    outputs=(
        _o("difference", "Difference raster (m)", OUTPUT_RASTER),
        _o("changed_pixels", "Changed pixels", OUTPUT_NUMBER),
    ),
    runner="run_dem_difference",
    engines=("survey-3d", "rasterio"),
))

_register(AlgorithmSpec(
    id="dem_volumes",
    name="Cut/fill volumes per zone",
    group="Elevation",
    description="Compute cut/fill/net earthwork volumes (m3) per zone from "
                "a DEM-difference raster, with propagated uncertainty when "
                "DEM RMSEs are given; appends to a volume time-series CSV "
                "and writes change polygons (GeoJSON).",
    params=(
        _p("difference", "Difference raster (m)", PARAM_RASTER),
        _p("zones", "Zones vector", PARAM_VECTOR),
        _p("noise_floor", "Noise floor (m)", PARAM_NUMBER, default=0.0),
        _p("dem_rmse", "Per-DEM vertical RMSE (m)", PARAM_NUMBER,
           optional=True, help="Applied to both DEMs for uncertainty."),
        _p("pass_id", "Pass id", PARAM_STRING, default=""),
        _p("pass_date", "Pass date (YYYY-MM-DD)", PARAM_STRING, default=""),
    ),
    outputs=(
        _o("volumes_csv", "Volumes CSV", OUTPUT_FILE),
        _o("polygons", "Change polygons", OUTPUT_VECTOR),
        _o("net_m3", "Total net volume (m3)", OUTPUT_NUMBER),
    ),
    runner="run_dem_volumes",
    engines=("survey-3d", "rasterio"),
))

# --- Alerts (survey-alerts) -----------------------------------------------------

_register(AlgorithmSpec(
    id="alerts_render_report",
    name="Render alert report (HTML)",
    group="Alerts",
    description="Read a survey-monitor alerts.jsonl file and render a "
                "print-friendly HTML site report (print to PDF from a "
                "browser for the PDF deliverable).",
    params=(
        _p("alerts_jsonl", "Alerts JSONL file", PARAM_FILE,
           help="alerts.jsonl from a survey-monitor run."),
        _p("severity", "Minimum severity", PARAM_ENUM, default="info",
           options=("info", "warning", "critical")),
    ),
    outputs=(
        _o("report_html", "Report HTML", OUTPUT_FILE),
        _o("alert_count", "Alerts in report", OUTPUT_NUMBER),
    ),
    runner="run_alerts_render_report",
    engines=("survey-alerts",),
))

# --- Licensing (survey-license) --------------------------------------------------

_register(AlgorithmSpec(
    id="license_validate",
    name="Validate license key",
    group="Licensing",
    description="Inspect a survey-license key: parse its payload "
                "(plan, expiry, entitlements) and, when a vendor secret file "
                "is given, fully validate its signature offline.",
    params=(
        _p("key", "License key", PARAM_STRING, default="",
           help="The SL1.xxx.xxx license key string."),
        _p("secret_file", "Vendor secret file", PARAM_FILE, optional=True,
           help="File holding the HMAC secret for full validation."),
    ),
    outputs=(
        _o("status", "Validation status", OUTPUT_STRING),
        _o("key_id", "Key id", OUTPUT_STRING),
        _o("plan", "Plan", OUTPUT_STRING),
        _o("expires", "Expiry date", OUTPUT_STRING),
    ),
    runner="run_license_validate",
    engines=("survey-license",),
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

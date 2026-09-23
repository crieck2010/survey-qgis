"""Algorithm runners: pure implementations behind each AlgorithmSpec.

A runner is a plain function ``run_*(params, feedback=None) -> dict`` where
``params`` is already validated against the spec (see
:func:`run_algorithm`) and ``feedback`` is an optional callable
``feedback(message, percent)``. Runners import suite engines lazily via
:mod:`survey_qgis.interop`, so importing this module never requires any
engine — or QGIS.

The single entry point for all callers (CLI, QGIS adapter, embedding code)
is :func:`run_algorithm`.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Callable, Dict, List, Optional

from .algorithms import get_algorithm, validate_params
from .interop import require_engine, require_rasterio

Feedback = Optional[Callable[[str, Optional[float]], None]]


def _push(feedback: Feedback, message: str, percent: Optional[float] = None) -> None:
    if feedback is not None:
        feedback(message, percent)


def _write_records_csv(path: str, records: List[Dict[str, Any]],
                       fieldnames: List[str]) -> str:
    """Write records to CSV, tolerating an empty record list."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    return path


# --- change detection (survey-change) --------------------------------------

def run_detect_change(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    change = require_engine("survey-change")
    _push(feedback, "Reading rasters...", 5)
    t1 = change.io.read_grid(params["t1"], name="t1")
    t2 = change.io.read_grid(params["t2"], name="t2")
    cfg = change.ChangeConfig(
        method=params["method"],
        threshold_method=params["threshold_method"],
        threshold=params["threshold"],
        min_region_pixels=params["min_region_pixels"],
    )
    _push(feedback, f"Detecting change ({cfg.method})...", 40)
    res = change.detection.detect(t1, t2, cfg)
    _push(feedback, "Writing outputs...", 75)
    diff_path = params["difference"]
    mask_path = params["mask"]
    change.io.write_cog(res.change_grid, diff_path)
    change.io.write_mask_geotiff(res.change_mask, res.change_grid, mask_path)
    # QML sidecars so the rasters open in QGIS already styled.
    try:
        if res.change_mask.any():
            vmin = float(res.change_grid.data[res.change_mask].min())
            vmax = float(res.change_grid.data[res.change_mask].max())
        else:
            vmin, vmax = -1.0, 1.0
        change.qgis.write_qml(change.qgis.difference_raster_qml(vmin, vmax),
                              diff_path + ".qml")
        change.qgis.write_qml(change.qgis.mask_qml(), mask_path + ".qml")
    except Exception:
        pass  # styling is best-effort; the data products are what matter
    report_path = params.get("report")
    stats = change.statistics.summarize_change(
        res.change_grid, res.change_mask, res.gain_mask, res.loss_mask)
    stats["threshold_used"] = res.threshold_used
    stats["method"] = cfg.method
    if report_path:
        change.io.write_report(change.io.change_report(stats), report_path)
    return {
        "difference": diff_path,
        "mask": mask_path,
        "report": report_path,
        "changed_pixels": int(stats["pixels"]),
    }


def run_change_polygons(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    change = require_engine("survey-change")
    _push(feedback, "Reading change mask...", 10)
    mask_grid = change.io.read_grid(params["mask"])
    mask = mask_grid.data > 0
    change_grid = None
    if params.get("change_raster"):
        change_grid = change.io.read_grid(params["change_raster"])
    _push(feedback, "Labeling regions...", 40)
    labels, regions = change.segmentation.label_regions(mask)
    min_px = params["min_region_pixels"]
    regions = [r for r in regions if r["pixels"] >= min_px]
    _push(feedback, "Tracing polygons...", 70)
    feats = change.polygons.regions_to_features(
        labels, regions, mask_grid, change_grid,
        simplify_tolerance=params["simplify"], kind="change")
    out_path = params["polygons"]
    fc = change.polygons.features_to_geojson(feats, crs=mask_grid.crs)
    change.polygons.write_geojson(fc, out_path)
    try:
        change.qgis.write_qml(change.qgis.change_polygon_qml(), out_path + ".qml")
    except Exception:
        pass
    return {"polygons": out_path, "feature_count": len(feats)}


def run_classify_change(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    change = require_engine("survey-change")
    _push(feedback, "Reading label rasters...", 10)
    t1 = change.io.read_grid(params["t1_labels"])
    t2 = change.io.read_grid(params["t2_labels"])
    names: Dict[int, str] = {}
    if params.get("class_names"):
        with open(params["class_names"], encoding="utf-8") as fh:
            names = {int(k): str(v) for k, v in json.load(fh).items()}
    _push(feedback, "Comparing classifications...", 40)
    comp = change.classification.post_classification_compare(t1, t2, names or None)
    trans = change.classification.transition_grid(t1, t2)
    trans_path = params["transition"]
    change.io.write_cog(trans, trans_path)
    try:
        change.qgis.write_qml(
            change.qgis.transition_qml(names or {int(k): str(k) for k in comp["labels"]}),
            trans_path + ".qml")
    except Exception:
        pass
    records = change.classification.summarize_transitions(comp, t1.pixel_area, names or None)
    table_path = params["table"]
    _write_records_csv(table_path, records,
                       ["from_class", "to_class", "from_name", "to_name",
                        "pixels", "area"])
    return {
        "transition": trans_path,
        "table": table_path,
        "changed_pixels": int(comp["changed_pixels"]),
    }


def run_timeseries_breaks(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    change = require_engine("survey-change")
    _push(feedback, "Reading monitor archive...", 20)
    rows = change.timeseries.read_imagery_timeseries(params["timeseries_csv"])
    _push(feedback, "Scanning for breaks...", 60)
    breaks = change.timeseries.index_breaks(rows, params["index"], params["threshold"])
    out_path = params["breaks"]
    _write_records_csv(out_path, breaks,
                       ["index", "from_date", "to_date",
                        "from_mean", "to_mean", "delta"])
    return {"breaks": out_path, "break_count": len(breaks)}


# --- spectral indices (survey-imagery) ---------------------------------------

_BAND_PARAMS = ("red", "nir", "green", "blue", "swir1", "swir2")


def run_spectral_index(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    imagery = require_engine("survey-imagery")
    rasterio = require_rasterio()
    index_name = params["index"]
    needed = imagery.indices.required_bands(index_name)
    missing = [b for b in needed if not params.get(b)]
    if missing:
        from .algorithms import ParamValidationError
        raise ParamValidationError(
            f"index {index_name!r} needs band rasters for: {missing}")
    _push(feedback, f"Reading {len(needed)} band(s)...", 20)
    bands: Dict[str, Any] = {}
    profile = None
    shape = None
    for b in needed:
        with rasterio.open(params[b]) as src:
            arr = src.read(1).astype("float64")
            if shape is None:
                shape = arr.shape
                profile = src.profile.copy()
            elif arr.shape != shape:
                from .algorithms import ParamValidationError
                raise ParamValidationError(
                    f"band rasters have mismatched shapes: {shape} vs {arr.shape}")
            bands[b] = arr
    _push(feedback, f"Computing {index_name}...", 60)
    result = imagery.indices.compute(index_name, bands)
    out_path = params["index_raster"]
    profile.update(dtype="float32", count=1, compress="deflate", tiled=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(result.astype("float32"), 1)
    return {"index_raster": out_path, "index_name": index_name}


# --- COGO (survey-cogo) -------------------------------------------------------

def run_cogo_inverse(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    cogo = require_engine("survey-cogo")
    a = cogo.point.Point(northing=params["northing1"], easting=params["easting1"])
    b = cogo.point.Point(northing=params["northing2"], easting=params["easting2"])
    inv = cogo.inverse.inverse(a, b)
    bearing = cogo.angles.azimuth_to_bearing(inv.azimuth)
    return {"azimuth": inv.azimuth, "bearing": bearing, "distance": inv.distance}


def run_cogo_forward(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    cogo = require_engine("survey-cogo")
    start = cogo.point.Point(northing=params["northing"], easting=params["easting"])
    pt = cogo.forward.forward(start, params["azimuth"], params["distance"])
    return {"northing_out": pt.northing, "easting_out": pt.easting}


def _parse_vertices(text: str) -> List[tuple]:
    verts = []
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(",")
        if len(parts) != 2:
            from .algorithms import ParamValidationError
            raise ParamValidationError(
                f"vertices must be 'easting,northing' pairs, got {chunk!r}")
        try:
            verts.append((float(parts[0]), float(parts[1])))
        except ValueError as exc:
            from .algorithms import ParamValidationError
            raise ParamValidationError(f"invalid vertex {chunk!r}: {exc}") from exc
    return verts


def run_cogo_polygon_area(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    cogo = require_engine("survey-cogo")
    verts = _parse_vertices(params["vertices"])
    points = [cogo.point.Point(northing=n, easting=e) for e, n in verts]
    area = cogo.area.polygon_area(points)
    perimeter = cogo.area.polygon_perimeter(points)
    return {"area": area, "perimeter": perimeter}


# --- dispatcher ---------------------------------------------------------------

_RUNNERS = {
    "run_detect_change": run_detect_change,
    "run_change_polygons": run_change_polygons,
    "run_classify_change": run_classify_change,
    "run_timeseries_breaks": run_timeseries_breaks,
    "run_spectral_index": run_spectral_index,
    "run_cogo_inverse": run_cogo_inverse,
    "run_cogo_forward": run_cogo_forward,
    "run_cogo_polygon_area": run_cogo_polygon_area,
}


def run_algorithm(algorithm_id: str, params: Dict[str, Any],
                  feedback: Feedback = None) -> Dict[str, Any]:
    """Validate ``params`` against the algorithm spec and run it.

    Returns a dict mapping output names to values (file paths for layer
    outputs, scalars for numeric/text outputs). Raises
    :class:`ParamValidationError` for bad params and
    :class:`EngineMissingError` when a required suite engine is missing.
    """
    spec = get_algorithm(algorithm_id)
    normalized = validate_params(spec, params)
    try:
        runner = _RUNNERS[spec.runner]
    except KeyError as exc:
        raise RuntimeError(f"no runner registered for {spec.runner!r}") from exc
    _push(feedback, f"Running: {spec.name}", 0)
    result = runner(normalized, feedback)
    missing = [o.name for o in spec.outputs if o.name not in result]
    if missing:
        raise RuntimeError(
            f"runner {spec.runner!r} did not produce outputs: {missing}")
    _push(feedback, "Done.", 100)
    return result

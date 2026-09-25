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
import shutil
import tempfile
from typing import Any, Callable, Dict, List, Optional

from .algorithms import ParamValidationError, get_algorithm, validate_params
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


def _read_raster(path: str):
    """Read the first band of a raster as float64; return (array, profile, transform, crs)."""
    rasterio = require_rasterio()
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float64")
        profile = dict(src.profile)
        # Affine iterates as a 9-element 3x3 matrix; the engines take the
        # classic 6-tuple (a, b, c, d, e, f).
        transform = tuple(src.transform)[:6]
        crs = src.crs
    return arr, profile, transform, crs


def _write_geotiff(
    path: str,
    array,
    profile: dict,
    dtype: str,
    nodata,
) -> None:
    """Write a single-band GeoTIFF, keeping the source grid/profile."""
    rasterio = require_rasterio()
    profile = dict(profile)
    height = profile.get("height", 0)
    width = profile.get("width", 0)
    profile.update(
        dtype=dtype,
        count=1,
        nodata=nodata,
        compress="deflate",
        # Small rasters cannot be written tiled (rasterio defaults to
        # 256 px TIFF tiles, whose dimensions must be multiples of 16),
        # so tile only when the grid fits whole default blocks.
        tiled=bool(height >= 256 and width >= 256),
    )
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array, 1)


def _read_geojson(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_geojson(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def _qml_sidecar(writer, qml_path: str) -> None:
    """Best-effort QGIS style sidecar; never fails the algorithm."""
    try:
        writer(qml_path)
    except Exception:
        pass


def _submodule(engine, name: str):
    """Get a suite-engine submodule, importing it on demand.

    Stub engines in tests expose submodules as plain attributes; the real
    packages do not always import submodules in their ``__init__``, so fall
    back to an explicit (still lazy, execution-time) import when the
    attribute is absent.
    """
    sub = getattr(engine, name, None)
    if sub is not None:
        return sub
    import importlib

    return importlib.import_module(f"{engine.__name__}.{name}")


def _today_iso() -> str:
    import datetime

    return datetime.date.today().isoformat()


def _doy_year(date_iso: str):
    import datetime

    dt = datetime.date.fromisoformat(date_iso)
    return dt.timetuple().tm_yday, dt.year


# ---------------------------------------------------------------------------
# survey-imagery runners
# ---------------------------------------------------------------------------

def run_imagery_composite(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Stack index rasters from a folder and composite them."""
    import numpy as np

    imagery = require_engine("survey-imagery")
    rasterio = require_rasterio()
    folder = params["input_folder"]
    names = sorted(
        name
        for name in os.listdir(folder)
        if name.lower().endswith((".tif", ".tiff"))
    )
    if not names:
        raise ParamValidationError(
            f"no GeoTIFF rasters found in input folder: {folder}"
        )
    arrays = []
    profile = None
    for name in names:
        with rasterio.open(os.path.join(folder, name)) as src:
            arrays.append(src.read(1).astype("float64"))
            if profile is None:
                profile = dict(src.profile)
    composite = imagery.composites.temporal_composite(
        arrays, method=params.get("method", "median")
    )
    out_path = params["composite"]
    _write_geotiff(out_path, np.asarray(composite, dtype="float32"),
                   profile, "float32", nodata=np.nan)
    return {"composite": out_path, "scene_count": len(names)}


def run_imagery_zonal_timeseries(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Per-zone index statistics for one pass, appended to a time-series CSV."""
    imagery = require_engine("survey-imagery")
    require_rasterio()
    arr, _profile, transform, crs = _read_raster(params["index_raster"])
    fc = _read_geojson(params["zones"])
    features = fc.get("features", [])
    if not features:
        raise ParamValidationError("zones vector has no features")
    zones_crs = params.get("zones_crs") or "EPSG:4326"
    pass_id = params.get("pass_id") or ""
    pass_date = params.get("pass_date") or ""
    index_name = params.get("index_name") or "NDVI"
    cloud_cover = params.get("cloud_cover")
    records = []
    for position, feature in enumerate(features):
        props = feature.get("properties") or {}
        zone_id = str(
            props.get("id") or props.get("zone_id") or f"zone-{position + 1}"
        )
        zone_name = str(props.get("name") or zone_id)
        aoi = imagery.aoi.from_geojson(feature["geometry"], crs=zones_crs)
        stats = imagery.timeseries.zonal_stats(
            arr,
            transform,
            str(crs),
            aoi,
            scene_id=f"{pass_id}@{zone_id}" if pass_id else zone_id,
            datetime=pass_date,
            index=index_name,
            cloud_cover=cloud_cover,
        )
        record = dict(stats.to_dict())
        record["zone_id"] = zone_id
        record["zone_name"] = zone_name
        records.append(record)
    out_path = params["timeseries_csv"]
    fieldnames = ["zone_id", "zone_name", "scene_id", "datetime", "index",
                  "mean", "median", "std", "minimum", "maximum",
                  "p10", "p90", "valid_pixels", "total_pixels",
                  "cloud_cover"]
    records.sort(key=lambda r: (r["zone_id"], r.get("datetime") or ""))
    rows = [{key: r.get(key, "") for key in fieldnames} for r in records]
    _write_records_csv(out_path, rows, fieldnames)
    return {"timeseries_csv": out_path, "zone_count": len(records)}


# ---------------------------------------------------------------------------
# survey-monitor runners
# ---------------------------------------------------------------------------

def run_monitor_run(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Run a survey-monitor site config into a store folder."""
    monitor = require_engine("survey-monitor")
    config = monitor.load_site_config(params["site_config"])
    site_id = config.site_id
    config_dir = tempfile.mkdtemp(prefix="survey-qgis-monitor-")
    source = params["site_config"]
    ext = os.path.splitext(source)[1] or ".json"
    shutil.copy(source, os.path.join(config_dir, f"{site_id}{ext}"))
    store_dir = params["store_folder"]
    os.makedirs(store_dir, exist_ok=True)
    since = params.get("since") or None
    summary = monitor.run_site(
        site_id,
        config_dir,
        store_dir,
        synthetic=params.get("synthetic", True),
        since=since,
    )
    shutil.rmtree(config_dir, ignore_errors=True)
    return {
        "store_folder": store_dir,
        "passes_processed": int(summary.passes_processed),
        "alerts_fired": int(summary.alerts_fired),
    }


def run_monitor_alerts_map(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Read a monitor site's alerts.jsonl and write an alerts GeoJSON layer."""
    monitor = require_engine("survey-monitor")
    events = monitor.alerts.read_alerts(params["store_folder"], params["site_id"])
    severity = params.get("severity") or "all"
    if severity != "all":
        events = [e for e in events if e.severity == severity]
    feature_collection = monitor.alerts.alerts_to_geojson(events)
    out_path = params["alerts_geojson"]
    _write_geojson(out_path, feature_collection)
    return {"alerts_geojson": out_path, "alert_count": len(events)}


# ---------------------------------------------------------------------------
# survey-vegetation runners
# ---------------------------------------------------------------------------

def run_vegetation_vigor_map(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Classify a vigor-index raster into vigor bands."""
    veg = require_engine("survey-vegetation")
    vigor = _submodule(veg, "vigor")
    arr, profile, _transform, _crs = _read_raster(params["index_raster"])
    classes = vigor.classify(arr)
    out_path = params["vigor_map"]
    _write_geotiff(out_path, classes, profile, "uint8",
                   nodata=vigor.NODATA_CLASS)
    _qml_sidecar(_submodule(veg, "qml").write_vigor_qml, out_path + ".qml")
    histogram = vigor.class_histogram(classes)
    found = sum(1 for row in histogram if row.get("pixels", 0) > 0)
    return {"vigor_map": out_path, "classes_found": found}


def run_vegetation_timeseries(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Per-zone vigor statistics appended to a time-series CSV."""
    veg = require_engine("survey-vegetation")
    zones_mod = _submodule(veg, "zones")
    zonal_mod = _submodule(veg, "zonal")
    ts_mod = _submodule(veg, "timeseries")
    require_rasterio()
    arr, _profile, transform, _crs = _read_raster(params["index_raster"])
    zones = zones_mod.load_zones_geojson(params["zones"])
    if not zones:
        raise ParamValidationError("zones vector has no zones")
    masks = zonal_mod.masks_for_zones(zones, arr.shape, transform=transform)
    pass_id = params.get("pass_id") or ""
    pass_date = params.get("pass_date") or _today_iso()
    index_name = params.get("index_name") or "NDVI"
    cloud_cover = params.get("cloud_cover")
    records = []
    for zone, mask in zip(zones, masks):
        stats = zonal_mod.zonal_stats(arr, mask)
        records.append(
            ts_mod.ZonePassRecord.from_zonal_stats(
                zone.id, zone.name, pass_id, pass_date, index_name, stats,
                cloud_cover=cloud_cover if cloud_cover is not None else 0.0,
            )
        )
    out_path = params["timeseries_csv"]
    ts_mod.append_csv(records, out_path)
    return {"timeseries_csv": out_path, "zone_count": len(records)}


# ---------------------------------------------------------------------------
# survey-flood runners
# ---------------------------------------------------------------------------

def run_flood_water_mask(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Threshold an NDWI/MNDWI raster into a despeckled water mask."""
    import numpy as np

    flood = require_engine("survey-flood")
    watermask = _submodule(flood, "watermask")
    arr, profile, _transform, _crs = _read_raster(params["index_raster"])
    mask = watermask.water_mask(arr, params.get("threshold", 0.0))
    mask = watermask.despeckle(mask, params.get("despeckle_pixels", 4))
    out_path = params["water_mask"]
    _write_geotiff(out_path, mask.astype("uint8"), profile, "uint8", nodata=255)
    _qml_sidecar(_submodule(flood, "qml").write_water_qml, out_path + ".qml")
    return {"water_mask": out_path, "water_pixels": int(np.sum(mask))}


def run_flood_polygons(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Vectorize a binary water mask into flood-extent polygons."""
    flood = require_engine("survey-flood")
    polygons_mod = _submodule(flood, "polygons")
    arr, _profile, transform, _crs = _read_raster(params["water_mask"])
    mask = arr > 0
    features = polygons_mod.vectorize(
        mask, transform=transform, min_pixels=params.get("min_pixels", 4)
    )
    out_path = params["polygons"]
    polygons_mod.write_polygons_geojson(features, out_path)
    return {"polygons": out_path, "feature_count": len(features)}


# ---------------------------------------------------------------------------
# survey-burn runners
# ---------------------------------------------------------------------------

def run_burn_severity(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Compute dNBR from pre/post NBR rasters and classify burn severity."""
    import numpy as np

    burn = require_engine("survey-burn")
    dnbr_mod = _submodule(burn, "dnbr")
    severity_mod = _submodule(burn, "severity")
    qml_mod = _submodule(burn, "qml")
    pre, profile, _t, _c = _read_raster(params["pre_nbr"])
    post, _profile2, _t2, _c2 = _read_raster(params["post_nbr"])
    if pre.shape != post.shape:
        raise ParamValidationError(
            f"pre/post NBR rasters must share a grid: {pre.shape} vs {post.shape}"
        )
    dnbr = dnbr_mod.dnbr(pre, post)
    severity = severity_mod.classify(dnbr)
    dnbr_path = params["dnbr"]
    severity_path = params["severity"]
    _write_geotiff(dnbr_path, np.asarray(dnbr, dtype="float32"),
                   profile, "float32", nodata=np.nan)
    _write_geotiff(severity_path, np.asarray(severity, dtype="uint8"),
                   profile, "uint8", nodata=255)
    _qml_sidecar(lambda path: qml_mod.write_qml(path, kind="dnbr"),
                 dnbr_path + ".qml")
    _qml_sidecar(lambda path: qml_mod.write_qml(path, kind="severity"),
                 severity_path + ".qml")
    burned = int(np.sum(severity_mod.burned_mask(dnbr)))
    return {
        "dnbr": dnbr_path,
        "severity": severity_path,
        "burned_pixels": burned,
    }


# ---------------------------------------------------------------------------
# survey-coast runners
# ---------------------------------------------------------------------------

def run_coast_shoreline(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Trace the water/land boundary of a binary water mask."""
    import numpy as np

    coast = require_engine("survey-coast")
    shoreline_mod = _submodule(coast, "shoreline")
    geojson_mod = _submodule(coast, "geojson")
    arr, _profile, transform, _crs = _read_raster(params["water_mask"])
    mask = arr > 0
    # Affine (a, b, c, d, e, f): c/f are the top-left map origin.
    # extract_shoreline returns polylines already in map meters.
    _a, _b, origin_x, _d, _e, origin_y = transform
    lines = shoreline_mod.extract_shoreline(
        mask,
        pixel_size_m=params.get("pixel_size_m", 10.0),
        origin_x=origin_x,
        origin_y=origin_y,
        min_length_m=params.get("min_length_m", 0.0),
    )
    features = []
    for position, line in enumerate(lines):
        coords = [
            [float(x), float(y)]
            for x, y in np.asarray(line, dtype=float)
        ]
        features.append(
            geojson_mod.linestring_feature(
                coords,
                {
                    "segment": position + 1,
                    "length_m": shoreline_mod.shoreline_length_m([line]),
                },
            )
        )
    out_path = params["shoreline"]
    geojson_mod.write_geojson(out_path, features)
    return {"shoreline": out_path, "segment_count": len(features)}


def run_coast_transect_positions(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Measure shoreline positions on transect lines into a positions CSV."""
    import numpy as np

    coast = require_engine("survey-coast")
    transects_mod = _submodule(coast, "transects")
    positions_mod = _submodule(coast, "positions")
    shoreline_mod = _submodule(coast, "shoreline")
    feature_collection = _read_geojson(params["shoreline"])
    lines = [
        np.asarray(feature["geometry"]["coordinates"], dtype=float)
        for feature in feature_collection.get("features", [])
        if feature.get("geometry", {}).get("type") == "LineString"
    ]
    if not lines:
        raise ParamValidationError("shoreline GeoJSON has no LineString features")
    transects = transects_mod.load_transects_geojson(params["transects"])
    if not transects:
        raise ParamValidationError("transects vector has no features")
    pass_id = params.get("pass_id") or ""
    pass_date = params.get("pass_date") or _today_iso()
    doy, year = _doy_year(pass_date)
    index_name = params.get("index_name") or "ndwi"
    pixel_size_m = params.get("pixel_size_m", 10.0)
    total_length = sum(shoreline_mod.shoreline_length_m([line]) for line in lines)
    records = []
    for transect in transects:
        position = transects_mod.transect_position(transect, lines)
        valid = bool(np.isfinite(position))
        records.append(
            positions_mod.TransectPassRecord(
                transect_id=transect.id,
                transect_name=transect.name,
                site_id="",
                site_name="",
                pass_id=pass_id,
                date=pass_date,
                doy=doy,
                year=year,
                index=index_name,
                position_m=float(position),
                shoreline_length_m=total_length,
                valid=valid,
                cloud_cover=0.0,
                pixel_size_m=float(pixel_size_m),
            )
        )
    out_path = params["positions_csv"]
    positions_mod.append_records(out_path, records)
    return {"positions_csv": out_path, "transect_count": len(records)}


# ---------------------------------------------------------------------------
# survey-thermal runners
# ---------------------------------------------------------------------------

def run_thermal_lst(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Convert a Landsat ST_B10 DN raster to LST in Celsius."""
    import numpy as np

    thermal = require_engine("survey-thermal")
    temperature = _submodule(thermal, "temperature")
    arr, profile, _transform, _crs = _read_raster(params["st_raster"])
    celsius = temperature.st_dn_to_celsius(arr)
    out_path = params["lst_celsius"]
    _write_geotiff(out_path, np.asarray(celsius, dtype="float32"),
                   profile, "float32", nodata=np.nan)
    _qml_sidecar(_submodule(thermal, "qml").write_lst_qml, out_path + ".qml")
    valid = celsius[np.isfinite(celsius)]
    mean_celsius = float(np.mean(valid)) if valid.size else float("nan")
    return {"lst_celsius": out_path, "mean_celsius": mean_celsius}


def run_thermal_uhi(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Per-zone urban heat-island intensity from an LST raster."""
    thermal = require_engine("survey-thermal")
    zones_mod = _submodule(thermal, "zones")
    zonal_mod = _submodule(thermal, "zonal")
    ts_mod = _submodule(thermal, "timeseries")
    uhi_mod = _submodule(thermal, "uhi")
    require_rasterio()
    arr, _profile, transform, _crs = _read_raster(params["lst_raster"])
    zones = zones_mod.load_zones_geojson(params["zones"])
    if not zones:
        raise ParamValidationError("zones vector has no zones")
    pass_id = params.get("pass_id") or ""
    pass_date = params.get("pass_date") or _today_iso()
    records = []
    for zone in zones:
        stats = zonal_mod.zonal_lst_stats(arr, zone, transform)
        records.append(
            ts_mod.make_record(
                zone.id, zone.name, pass_id, pass_date, stats, cloud_cover=0.0
            )
        )
    reference = params.get("reference_zone") or None
    uhi_records = uhi_mod.compute_uhi(records, reference_id=reference)
    out_path = params["uhi_csv"]
    uhi_mod.write_uhi_csv(uhi_records, out_path)
    return {"uhi_csv": out_path, "zone_count": len(uhi_records)}


# ---------------------------------------------------------------------------
# survey-3d runners
# ---------------------------------------------------------------------------

def run_dem_difference(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Difference two aligned DEM rasters (later minus earlier)."""
    import numpy as np

    elev3d = require_engine("survey-3d")
    diff_mod = _submodule(elev3d, "diff")
    dem1, profile, _t, _c = _read_raster(params["dem1"])
    dem2, _profile2, _t2, _c2 = _read_raster(params["dem2"])
    if dem1.shape != dem2.shape:
        raise ParamValidationError(
            f"DEM rasters must share a grid: {dem1.shape} vs {dem2.shape}"
        )
    result = diff_mod.difference(dem1, dem2,
                                 noise_floor=params.get("noise_floor", 0.0))
    out_path = params["difference"]
    _write_geotiff(out_path,
                   np.asarray(result.diff_thresholded, dtype="float32"),
                   profile, "float32", nodata=np.nan)
    _qml_sidecar(_submodule(elev3d, "qml").write_qml, out_path + ".qml")
    return {"difference": out_path, "changed_pixels": int(result.changed_pixels)}


def run_dem_volumes(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Cut/fill volumes per zone from a DEM-difference raster."""
    import numpy as np

    elev3d = require_engine("survey-3d")
    zones_mod = _submodule(elev3d, "zones")
    zonal_mod = _submodule(elev3d, "zonal")
    volumes_mod = _submodule(elev3d, "volumes")
    ts_mod = _submodule(elev3d, "timeseries")
    polygons_mod = _submodule(elev3d, "polygons")
    require_rasterio()
    arr, _profile, transform, _crs = _read_raster(params["difference"])
    zones = zones_mod.load_zones_geojson(params["zones"])
    if not zones:
        raise ParamValidationError("zones vector has no zones")
    noise_floor = params.get("noise_floor", 0.0)
    rmse = params.get("dem_rmse")
    pass_id = params.get("pass_id") or ""
    pass_date = params.get("pass_date") or _today_iso()
    records = []
    for zone in zones:
        zonal_mask = zonal_mod.zone_mask(zone, arr.shape, transform)
        volumes = volumes_mod.zone_volumes(
            arr, zone, transform, noise_floor=noise_floor,
            rmse1=rmse, rmse2=rmse,
        )
        values = arr[zonal_mask & np.isfinite(arr)]
        zonal = {
            "mean": float(np.mean(values)) if values.size else float("nan"),
            "median": float(np.median(values)) if values.size else float("nan"),
            "std": float(np.std(values)) if values.size else float("nan"),
            "minimum": float(np.min(values)) if values.size else float("nan"),
            "maximum": float(np.max(values)) if values.size else float("nan"),
            "p10": float(np.percentile(values, 10)) if values.size else float("nan"),
            "p90": float(np.percentile(values, 90)) if values.size else float("nan"),
            "valid_pixels": int(np.sum(np.isfinite(arr[zonal_mask]))),
            "total_pixels": int(np.sum(zonal_mask)),
            "cloud_cover": 0.0,
        }
        records.append(
            ts_mod.make_record(
                zone.id, zone.name, pass_id, pass_date, zonal, volumes.to_dict()
            )
        )
    out_path = params["volumes_csv"]
    ts_mod.append_records(out_path, records)
    polygons = polygons_mod.change_polygons(
        arr, transform, threshold=noise_floor, min_pixels=4
    )
    feature_collection = polygons_mod.polygons_to_geojson(polygons)
    polygons_path = params["polygons"]
    _write_geojson(polygons_path, feature_collection)
    net_m3 = sum(record.net_m3 for record in records)
    return {
        "volumes_csv": out_path,
        "polygons": polygons_path,
        "net_m3": float(net_m3),
    }


# ---------------------------------------------------------------------------
# survey-alerts runners
# ---------------------------------------------------------------------------

def run_alerts_render_report(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Render a print-friendly HTML site report from alerts.jsonl."""
    alerts = require_engine("survey-alerts")
    reader = _submodule(alerts, "reader")
    model = _submodule(alerts, "model")
    html_mod = _submodule(alerts, "html")
    severity = params.get("severity") or "info"
    read_result = reader.read_alerts(params["alerts_jsonl"],
                                     min_severity=severity)
    if isinstance(read_result, tuple):
        # Released survey-alerts returns (records, skipped).
        records, _skipped = read_result
    else:
        # Older survey-alerts returned a bare record list.
        rank = {"info": 0, "warning": 1, "critical": 2}.get(severity, 0)
        records = [record for record in read_result
                   if record.severity_rank() >= rank]
    report = model.build_report(records)
    html_text = html_mod.render_html(report)
    out_path = params["report_html"]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    return {"report_html": out_path, "alert_count": len(records)}


# ---------------------------------------------------------------------------
# survey-license runners
# ---------------------------------------------------------------------------

def run_license_validate(params: Dict[str, Any], feedback: Feedback = None) -> Dict[str, Any]:
    """Inspect (and optionally fully validate) a license key."""
    licensekit = require_engine("survey-license")
    key = (params.get("key") or "").strip()
    if not key:
        return {
            "status": "no key provided",
            "key_id": "",
            "plan": "",
            "expires": "",
        }
    try:
        parsed = licensekit.keys.parse_key(key)
    except Exception as exc:  # KeyFormatError and friends
        return {
            "status": f"invalid key format: {exc}",
            "key_id": "",
            "plan": "",
            "expires": "",
        }
    # Released survey-license nests the payload dict under "payload";
    # older releases returned it directly.
    payload = parsed.get("payload", parsed) if isinstance(parsed, dict) else {}
    key_id = licensekit.keys.fingerprint(key)
    secret_path = params.get("secret_file")
    if secret_path:
        # The vendor secret is used only to validate the signature here;
        # it is never logged or returned.
        with open(secret_path, "rb") as fh:
            secret = fh.read().strip()
        result = licensekit.validate.check_license(key, secret=secret)
        status = "valid" if result.valid else f"invalid: {result.reason}"
    else:
        status = "format ok (signature not checked; no secret file given)"
    return {
        "status": status,
        "key_id": key_id,
        "plan": str(payload.get("plan", "")),
        "expires": str(payload.get("exp", "")),
    }

# --- dispatcher ---------------------------------------------------------------

_RUNNERS = {
    "run_detect_change": run_detect_change,
    "run_change_polygons": run_change_polygons,
    "run_classify_change": run_classify_change,
    "run_timeseries_breaks": run_timeseries_breaks,
    "run_spectral_index": run_spectral_index,
    "run_imagery_composite": run_imagery_composite,
    "run_imagery_zonal_timeseries": run_imagery_zonal_timeseries,
    "run_monitor_run": run_monitor_run,
    "run_monitor_alerts_map": run_monitor_alerts_map,
    "run_vegetation_vigor_map": run_vegetation_vigor_map,
    "run_vegetation_timeseries": run_vegetation_timeseries,
    "run_flood_water_mask": run_flood_water_mask,
    "run_flood_polygons": run_flood_polygons,
    "run_burn_severity": run_burn_severity,
    "run_coast_shoreline": run_coast_shoreline,
    "run_coast_transect_positions": run_coast_transect_positions,
    "run_thermal_lst": run_thermal_lst,
    "run_thermal_uhi": run_thermal_uhi,
    "run_dem_difference": run_dem_difference,
    "run_dem_volumes": run_dem_volumes,
    "run_alerts_render_report": run_alerts_render_report,
    "run_license_validate": run_license_validate,
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

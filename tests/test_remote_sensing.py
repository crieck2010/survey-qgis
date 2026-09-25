"""Tests for the survey-qgis remote-sensing algorithms (v0.2.0).

Stub suite engines are injected into ``sys.modules``; the real engine
packages are not required. No QGIS installation is needed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from survey_qgis import algorithms, interop, runners
from survey_qgis.algorithms import (
    ALGORITHMS,
    get_algorithm,
    list_algorithms,
    validate_params,
)
from survey_qgis.interop import EngineMissingError


# --------------------------------------------------------------------------
# Stub plumbing
# --------------------------------------------------------------------------

def drop_stubs(*names):
    for name in names:
        sys.modules.pop(name, None)


class _FakeRasterioDataset:
    def __init__(self, calls, mode, path):
        self._calls = calls
        self.mode = mode
        self.path = path
        self.profile = {
            "dtype": "float32", "count": 1, "height": 2, "width": 2,
            "transform": (10.0, 0.0, 100.0, 0.0, -10.0, 200.0),
            "crs": "EPSG:32618",
        }
        self.transform = (10.0, 0.0, 100.0, 0.0, -10.0, 200.0)
        self.crs = "EPSG:32618"

    def read(self, idx):
        return np.array([[0.5, 0.6], [0.4, 0.5]])

    def write(self, arr, idx):
        self._calls.setdefault("rasterio_write", []).append((self.path, idx))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def install_rasterio_stub(calls):
    rio = SimpleNamespace(
        open=lambda path, mode="r", **kw: calls.setdefault(
            "rasterio_open", []).append((path, mode)) or
        _FakeRasterioDataset(calls, mode, path))
    sys.modules["rasterio"] = rio
    return rio


def install_engine_stub(name, module):
    sys.modules[name] = module
    return module


def _write_stub_text(calls, key, path, text):
    calls.setdefault(key, []).append(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def install_imagery_stub(calls):
    imagery = SimpleNamespace(
        composites=SimpleNamespace(
            temporal_composite=lambda arrays, method="median": np.mean(
                np.asarray(arrays), axis=0)),
        aoi=SimpleNamespace(
            from_geojson=lambda geom, crs=None: SimpleNamespace(
                crs=crs, geometry=geom)),
        timeseries=SimpleNamespace(
            zonal_stats=lambda *a, **k: SimpleNamespace(
                to_dict=lambda: {
                    "scene_id": k.get("scene_id", ""),
                    "datetime": k.get("datetime", ""),
                    "index": k.get("index", ""),
                    "mean": 0.5, "median": 0.5, "std": 0.0,
                    "minimum": 0.4, "maximum": 0.6,
                    "p10": 0.42, "p90": 0.58,
                    "valid_pixels": 4, "total_pixels": 4,
                    "cloud_cover": k.get("cloud_cover") or 0.0,
                })))
    return install_engine_stub("imagery", imagery)


def install_monitor_stub(calls):
    alerts_ns = SimpleNamespace(
        read_alerts=lambda store_dir, site_id, **kw: calls.setdefault(
            "read_alerts", []).append(site_id) or [
                SimpleNamespace(severity="warning"),
                SimpleNamespace(severity="info")],
        alerts_to_geojson=lambda events: {
            "type": "FeatureCollection", "features": []})
    monitor = SimpleNamespace(
        load_site_config=lambda path: SimpleNamespace(
            site_id="demo-site", site_name="Demo"),
        run_site=lambda site_id, config_dir, store_dir, synthetic=True,
        since=None: SimpleNamespace(
            passes_processed=3, alerts_fired=2),
        alerts=alerts_ns)
    return install_engine_stub("monitor", monitor)


def install_vegetation_stub(calls):
    veg = SimpleNamespace(
        vigor=SimpleNamespace(
            NODATA_CLASS=255,
            classify=lambda arr: np.array([[2, 3], [1, 255]],
                                          dtype=np.uint8),
            class_histogram=lambda classes: [
                {"class_id": 2, "pixels": 2}]),
        qml=SimpleNamespace(
            write_vigor_qml=lambda path: calls.setdefault(
                "write_qml", []).append(path)),
        zones=SimpleNamespace(
            load_zones_geojson=lambda path: [
                SimpleNamespace(id="z1", name="Zone 1", geometry={})]),
        zonal=SimpleNamespace(
            masks_for_zones=lambda zones, shape, transform=None: [
                np.ones(shape, dtype=bool) for _ in zones],
            zonal_stats=lambda arr, mask: {
                "mean": 0.5, "median": 0.5, "std": 0.0,
                "minimum": 0.4, "maximum": 0.6,
                "p10": 0.42, "p90": 0.58,
                "valid_pixels": 4, "total_pixels": 4}),
        timeseries=SimpleNamespace(
            ZonePassRecord=SimpleNamespace(
                from_zonal_stats=lambda *a, **k: SimpleNamespace()),
            append_csv=lambda records, path: _write_stub_text(
                calls, "append_csv", path, "zone_id\n") and (path, len(records))))
    return install_engine_stub("vegetation", veg)


def install_flood_stub(calls):
    flood = SimpleNamespace(
        watermask=SimpleNamespace(
            water_mask=lambda arr, threshold=0.0: np.ones((2, 2), dtype=bool),
            despeckle=lambda mask, min_pixels=4: mask),
        qml=SimpleNamespace(
            write_water_qml=lambda path: calls.setdefault(
                "write_qml", []).append(path)),
        polygons=SimpleNamespace(
            vectorize=lambda mask, transform=None, min_pixels=4: [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {}}],
            write_polygons_geojson=lambda features, path: _write_stub_text(
                calls, "write_geojson", path, "{}")))
    return install_engine_stub("flood", flood)


def install_burn_stub(calls):
    burn = SimpleNamespace(
        dnbr=SimpleNamespace(
            dnbr=lambda pre, post: np.full((2, 2), 0.5)),
        severity=SimpleNamespace(
            classify=lambda arr: np.full((2, 2), 3, dtype=np.uint8),
            burned_mask=lambda arr: np.ones((2, 2), dtype=bool)),
        qml=SimpleNamespace(
            write_qml=lambda path, kind="dnbr": calls.setdefault(
                "write_qml", []).append((path, kind))))
    return install_engine_stub("burn", burn)


def install_coast_stub(calls):
    coast = SimpleNamespace(
        shoreline=SimpleNamespace(
            extract_shoreline=lambda mask, pixel_size_m=10.0, origin_x=0.0,
            origin_y=0.0, min_length_m=0.0: [[[1, 2], [3, 4]]],
            shoreline_length_m=lambda lines: 50.0),
        geojson=SimpleNamespace(
            linestring_feature=lambda coords, properties: {
                "type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": coords},
                "properties": properties},
            write_geojson=lambda path, features, **kw: calls.setdefault(
                "write_geojson", []).append(path) or
            Path(path).write_text(json.dumps({
                "type": "FeatureCollection", "features": features})) or path),
        transects=SimpleNamespace(
            load_transects_geojson=lambda path: [
                SimpleNamespace(id="t1", name="T1")],
            transect_position=lambda transect, lines: 12.5),
        positions=SimpleNamespace(
            TransectPassRecord=type(
                "TransectPassRecord", (),
                {"__init__": lambda self, **kw: setattr(
                    self, "__dict__", kw)}),
            append_records=lambda path, records: calls.setdefault(
                "append_records", []).append(path) or
            Path(path).write_text("transect_id\n") or (path, len(records), 0)))
    return install_engine_stub("coast", coast)


def install_thermal_stub(calls):
    thermal = SimpleNamespace(
        temperature=SimpleNamespace(
            st_dn_to_celsius=lambda arr: np.full((2, 2), 25.0)),
        qml=SimpleNamespace(
            write_lst_qml=lambda path: calls.setdefault(
                "write_qml", []).append(path)),
        zones=SimpleNamespace(
            load_zones_geojson=lambda path: [
                SimpleNamespace(id="z1", name="Zone 1", geometry={})]),
        zonal=SimpleNamespace(
            zonal_lst_stats=lambda arr, zone, transform: {
                "mean": 25.0, "median": 25.0, "std": 0.0,
                "minimum": 24.0, "maximum": 26.0,
                "p10": 24.5, "p90": 25.5,
                "valid_pixels": 4, "total_pixels": 4}),
        timeseries=SimpleNamespace(
            make_record=lambda *a, **k: SimpleNamespace()),
        uhi=SimpleNamespace(
            compute_uhi=lambda records, reference_id=None: records,
            write_uhi_csv=lambda records, path: calls.setdefault(
                "write_uhi", []).append(path) or
            Path(path).write_text("zone_id\n") or path))
    return install_engine_stub("thermal", thermal)


def install_elev3d_stub(calls):
    elev3d = SimpleNamespace(
        diff=SimpleNamespace(
            difference=lambda a, b, noise_floor=0.0: SimpleNamespace(
                diff=np.full((2, 2), 1.0),
                diff_thresholded=np.full((2, 2), 1.0),
                changed_pixels=4)),
        qml=SimpleNamespace(
            write_qml=lambda path: calls.setdefault(
                "write_qml", []).append(path)),
        zones=SimpleNamespace(
            load_zones_geojson=lambda path: [
                SimpleNamespace(id="z1", name="Zone 1", geometry={})]),
        zonal=SimpleNamespace(
            zone_mask=lambda zone, shape, transform: np.ones(
                shape, dtype=bool)),
        volumes=SimpleNamespace(
            zone_volumes=lambda arr, zone, transform, noise_floor=0.0,
            rmse1=None, rmse2=None: SimpleNamespace(
                net_m3=12.5,
                to_dict=lambda: {"cut_m3": 20.0, "fill_m3": 7.5,
                                 "net_m3": 12.5})),
        timeseries=SimpleNamespace(
            make_record=lambda *a, **k: SimpleNamespace(net_m3=12.5),
            append_records=lambda path, records: calls.setdefault(
                "append_records", []).append(path) or
            Path(path).write_text("zone_id\n") or len(records)),
        polygons=SimpleNamespace(
            change_polygons=lambda arr, transform, threshold=0.0,
            min_pixels=4: [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {}}],
            polygons_to_geojson=lambda polys: {
                "type": "FeatureCollection", "features": polys}))
    return install_engine_stub("elev3d", elev3d)


def install_alerts_engine_stub(calls):
    def _record(rank):
        return SimpleNamespace(severity_rank=lambda: rank)

    _rank = {"info": 0, "warning": 1, "critical": 2}

    def _read_alerts(path, min_severity=None, since=None):
        floor = _rank.get((min_severity or "info").lower(), 0)
        kept = [r for r in (_record(2), _record(0))
                if r.severity_rank() >= floor]
        return kept, 0

    alerts = SimpleNamespace(
        reader=SimpleNamespace(read_alerts=_read_alerts),
        model=SimpleNamespace(
            build_report=lambda records: SimpleNamespace(
                alert_count=len(records))),
        html=SimpleNamespace(
            render_html=lambda report: "<html>report</html>"))
    return install_engine_stub("alerts", alerts)


def install_license_stub(calls, bad_key=False):
    def _parse(key):
        if bad_key or key == "bad":
            raise ValueError("key must look like SL1.<payload>.<signature>")
        return {"plan": "pro", "exp": "2027-01-01"}

    licensekit = SimpleNamespace(
        keys=SimpleNamespace(
            parse_key=_parse,
            fingerprint=lambda key: "kid:ABCD"),
        validate=SimpleNamespace(
            check_license=lambda key, secret=None, **kw: calls.setdefault(
                "check_license", []).append(bool(secret)) or
            SimpleNamespace(valid=True, reason="")))
    return install_engine_stub("licensekit", licensekit)


# --------------------------------------------------------------------------
# Registry / interop
# --------------------------------------------------------------------------

class TestRemoteSensingRegistry(unittest.TestCase):
    def test_new_engine_import_names(self):
        self.assertEqual(interop.ENGINES["survey-monitor"], "monitor")
        self.assertEqual(interop.ENGINES["survey-alerts"], "alerts")
        self.assertEqual(interop.ENGINES["survey-license"], "licensekit")
        self.assertEqual(interop.ENGINES["survey-vegetation"], "vegetation")
        self.assertEqual(interop.ENGINES["survey-flood"], "flood")
        self.assertEqual(interop.ENGINES["survey-burn"], "burn")
        self.assertEqual(interop.ENGINES["survey-coast"], "coast")
        self.assertEqual(interop.ENGINES["survey-thermal"], "thermal")
        self.assertEqual(interop.ENGINES["survey-3d"], "elev3d")

    def test_new_algorithms_registered(self):
        ids = [
            "imagery_composite", "imagery_zonal_timeseries",
            "monitor_run", "monitor_alerts_map",
            "vegetation_vigor_map", "vegetation_timeseries",
            "flood_water_mask", "flood_polygons",
            "burn_severity",
            "coast_shoreline", "coast_transect_positions",
            "thermal_lst", "thermal_uhi",
            "dem_difference", "dem_volumes",
            "alerts_render_report",
            "license_validate",
        ]
        for algorithm_id in ids:
            self.assertIn(algorithm_id, ALGORITHMS,
                          f"missing algorithm {algorithm_id}")
        self.assertEqual(len(ids), 17)

    def test_algorithms_grouped_by_engine(self):
        groups = {spec.id: spec.group for spec in ALGORITHMS.values()}
        self.assertEqual(groups["imagery_composite"], "Imagery")
        self.assertEqual(groups["monitor_run"], "Site monitoring")
        self.assertEqual(groups["vegetation_vigor_map"], "Vegetation")
        self.assertEqual(groups["flood_water_mask"], "Flood")
        self.assertEqual(groups["burn_severity"], "Burn")
        self.assertEqual(groups["coast_shoreline"], "Coast")
        self.assertEqual(groups["thermal_lst"], "Thermal")
        self.assertEqual(groups["dem_difference"], "Elevation")
        self.assertEqual(groups["alerts_render_report"], "Alerts")
        self.assertEqual(groups["license_validate"], "Licensing")


class TestLazyEngineContract(unittest.TestCase):
    """Every new algorithm must fail only at execution when its engine
    (or rasterio) is missing — never at import or listing time."""

    NEW_IDS = [
        "imagery_composite", "imagery_zonal_timeseries",
        "monitor_run", "monitor_alerts_map",
        "vegetation_vigor_map", "vegetation_timeseries",
        "flood_water_mask", "flood_polygons",
        "burn_severity",
        "coast_shoreline", "coast_transect_positions",
        "thermal_lst", "thermal_uhi",
        "dem_difference", "dem_volumes",
        "alerts_render_report",
        "license_validate",
    ]

    def _dummy_params(self, tmp):
        spec = get_algorithm(self._current)
        params = {}
        for pspec in spec.params:
            name = pspec.name
            kind = pspec.type
            if kind in ("raster", "vector", "file", "folder"):
                params[name] = str(tmp / f"{name}.dat")
            elif kind == "string":
                params[name] = "demo"
            elif kind == "number":
                params[name] = 0.0
            elif kind == "integer":
                params[name] = 1
            elif kind == "boolean":
                params[name] = True
            elif kind == "enum":
                params[name] = pspec.options[0]
        from survey_qgis.params import (OUTPUT_FILE, OUTPUT_FOLDER,
                                        OUTPUT_RASTER, OUTPUT_VECTOR)
        dest_kinds = {OUTPUT_RASTER, OUTPUT_VECTOR, OUTPUT_FILE,
                      OUTPUT_FOLDER}
        for output in spec.outputs:
            if output.type in dest_kinds:
                params[output.name] = str(tmp / f"{output.name}.out")
        return params
    def test_missing_engine_raises_at_execution(self):
        drop_stubs("imagery", "monitor", "alerts", "licensekit",
                   "vegetation", "flood", "burn", "coast", "thermal",
                   "elev3d", "rasterio")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for algorithm_id in self.NEW_IDS:
                self._current = algorithm_id
                params = self._dummy_params(tmp)
                with self.assertRaises(EngineMissingError,
                                       msg=algorithm_id):
                    runners.run_algorithm(algorithm_id, params)


# --------------------------------------------------------------------------
# Runner tests with stub engines
# --------------------------------------------------------------------------

class _RunnerCase(unittest.TestCase):
    engine_names = ()

    def tearDown(self):
        drop_stubs(*self.engine_names, "rasterio")


class TestImageryRunners(_RunnerCase):
    engine_names = ("imagery",)

    def test_composite(self):
        calls = {}
        install_imagery_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "s1.tif").write_bytes(b"")
            (tmp / "s2.tif").write_bytes(b"")
            out = tmp / "composite.tif"
            result = runners.run_algorithm("imagery_composite", {
                "input_folder": str(tmp), "method": "median",
                "composite": str(out)})
            self.assertEqual(result["scene_count"], 2)
            self.assertEqual(result["composite"], str(out))
            self.assertTrue(calls.get("rasterio_write"))

    def test_composite_empty_folder_rejected(self):
        install_imagery_stub({})
        install_rasterio_stub({})
        with tempfile.TemporaryDirectory() as tmpdir:
            from survey_qgis.algorithms import ParamValidationError
            with self.assertRaises(ParamValidationError):
                runners.run_algorithm("imagery_composite", {
                    "input_folder": tmpdir, "method": "mean",
                    "composite": str(Path(tmpdir) / "c.tif")})

    def test_zonal_timeseries(self):
        calls = {}
        install_imagery_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            zones = tmp / "zones.geojson"
            zones.write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [[
                        [0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                    "properties": {"id": "z1", "name": "Zone 1"}}]}))
            out = tmp / "series.csv"
            result = runners.run_algorithm("imagery_zonal_timeseries", {
                "index_raster": str(tmp / "ndvi.tif"),
                "zones": str(zones), "zones_crs": "EPSG:4326",
                "pass_id": "S2A_001", "pass_date": "2026-06-01",
                "index_name": "NDVI",
                "timeseries_csv": str(out)})
            self.assertEqual(result["zone_count"], 1)
            self.assertTrue(out.exists())
            text = out.read_text()
            self.assertIn("z1", text)
            self.assertIn("S2A_001@z1", text)


class TestMonitorRunners(_RunnerCase):
    engine_names = ("monitor",)

    def test_monitor_run(self):
        calls = {}
        install_monitor_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            config = tmp / "demo-site.json"
            config.write_text(json.dumps({"site_id": "demo-site"}))
            store = tmp / "store"
            result = runners.run_algorithm("monitor_run", {
                "site_config": str(config), "synthetic": True,
                "store_folder": str(store)})
            self.assertEqual(result["passes_processed"], 3)
            self.assertEqual(result["alerts_fired"], 2)
            self.assertEqual(result["store_folder"], str(store))
            self.assertTrue(store.is_dir())

    def test_monitor_alerts_map(self):
        install_monitor_stub({})
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "alerts.geojson"
            result = runners.run_algorithm("monitor_alerts_map", {
                "store_folder": str(tmp), "site_id": "demo-site",
                "severity": "all", "alerts_geojson": str(out)})
            self.assertEqual(result["alert_count"], 2)
            self.assertTrue(out.exists())

    def test_monitor_alerts_map_severity_filter(self):
        install_monitor_stub({})
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "alerts.geojson"
            result = runners.run_algorithm("monitor_alerts_map", {
                "store_folder": str(tmp), "site_id": "demo-site",
                "severity": "critical", "alerts_geojson": str(out)})
            self.assertEqual(result["alert_count"], 0)


class TestVegetationRunners(_RunnerCase):
    engine_names = ("vegetation",)

    def test_vigor_map(self):
        calls = {}
        install_vegetation_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "vigor.tif"
            result = runners.run_algorithm("vegetation_vigor_map", {
                "index_raster": str(tmp / "ndvi.tif"),
                "vigor_map": str(out)})
            self.assertEqual(result["classes_found"], 1)
            self.assertIn("write_qml", calls)

    def test_timeseries(self):
        calls = {}
        install_vegetation_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "series.csv"
            result = runners.run_algorithm("vegetation_timeseries", {
                "index_raster": str(tmp / "ndvi.tif"),
                "zones": str(tmp / "zones.geojson"),
                "pass_id": "S2A_001", "pass_date": "2026-06-01",
                "index_name": "NDVI",
                "timeseries_csv": str(out)})
            self.assertEqual(result["zone_count"], 1)
            self.assertTrue(out.exists())


class TestFloodRunners(_RunnerCase):
    engine_names = ("flood",)

    def test_water_mask(self):
        calls = {}
        install_flood_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "mask.tif"
            result = runners.run_algorithm("flood_water_mask", {
                "index_raster": str(tmp / "ndwi.tif"),
                "threshold": 0.0, "despeckle_pixels": 4,
                "water_mask": str(out)})
            self.assertEqual(result["water_pixels"], 4)
            self.assertIn("write_qml", calls)

    def test_polygons(self):
        calls = {}
        install_flood_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "flood.geojson"
            result = runners.run_algorithm("flood_polygons", {
                "water_mask": str(tmp / "mask.tif"), "min_pixels": 4,
                "polygons": str(out)})
            self.assertEqual(result["feature_count"], 1)
            self.assertIn("write_geojson", calls)


class TestBurnRunners(_RunnerCase):
    engine_names = ("burn",)

    def test_severity(self):
        calls = {}
        install_burn_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            result = runners.run_algorithm("burn_severity", {
                "pre_nbr": str(tmp / "pre.tif"),
                "post_nbr": str(tmp / "post.tif"),
                "dnbr": str(tmp / "dnbr.tif"),
                "severity": str(tmp / "severity.tif")})
            self.assertEqual(result["burned_pixels"], 4)
            self.assertEqual(len(calls.get("write_qml", [])), 2)


class TestCoastRunners(_RunnerCase):
    engine_names = ("coast",)

    def test_shoreline(self):
        calls = {}
        install_coast_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "shoreline.geojson"
            result = runners.run_algorithm("coast_shoreline", {
                "water_mask": str(tmp / "mask.tif"),
                "pixel_size_m": 10.0, "min_length_m": 0.0,
                "shoreline": str(out)})
            self.assertEqual(result["segment_count"], 1)
            fc = json.loads(out.read_text())
            self.assertEqual(fc["features"][0]["geometry"]["type"],
                             "LineString")
            self.assertEqual(
                fc["features"][0]["properties"]["length_m"], 50.0)

    def test_transect_positions(self):
        calls = {}
        install_coast_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            shore = tmp / "shoreline.geojson"
            shore.write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "LineString",
                                 "coordinates": [[0, 0], [10, 0]]},
                    "properties": {}}]}))
            out = tmp / "positions.csv"
            result = runners.run_algorithm("coast_transect_positions", {
                "shoreline": str(shore),
                "transects": str(tmp / "transects.geojson"),
                "pass_id": "S2A_001", "pass_date": "2026-06-01",
                "index_name": "ndwi", "pixel_size_m": 10.0,
                "positions_csv": str(out)})
            self.assertEqual(result["transect_count"], 1)
            self.assertTrue(out.exists())

    def test_transect_positions_no_lines_rejected(self):
        install_coast_stub({})
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            shore = tmp / "shoreline.geojson"
            shore.write_text(json.dumps(
                {"type": "FeatureCollection", "features": []}))
            from survey_qgis.algorithms import ParamValidationError
            with self.assertRaises(ParamValidationError):
                runners.run_algorithm("coast_transect_positions", {
                    "shoreline": str(shore),
                    "transects": str(tmp / "t.geojson"),
                    "pass_id": "", "pass_date": "",
                    "index_name": "ndwi", "pixel_size_m": 10.0,
                    "positions_csv": str(tmp / "p.csv")})


class TestThermalRunners(_RunnerCase):
    engine_names = ("thermal",)

    def test_lst(self):
        calls = {}
        install_thermal_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "lst.tif"
            result = runners.run_algorithm("thermal_lst", {
                "st_raster": str(tmp / "st.tif"),
                "lst_celsius": str(out)})
            self.assertEqual(result["mean_celsius"], 25.0)
            self.assertIn("write_qml", calls)

    def test_uhi(self):
        calls = {}
        install_thermal_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "uhi.csv"
            result = runners.run_algorithm("thermal_uhi", {
                "lst_raster": str(tmp / "lst.tif"),
                "zones": str(tmp / "zones.geojson"),
                "reference_zone": "",
                "pass_id": "LC09_001", "pass_date": "2026-07-01",
                "uhi_csv": str(out)})
            self.assertEqual(result["zone_count"], 1)
            self.assertTrue(out.exists())


class TestElevationRunners(_RunnerCase):
    engine_names = ("elev3d",)

    def test_dem_difference(self):
        calls = {}
        install_elev3d_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "diff.tif"
            result = runners.run_algorithm("dem_difference", {
                "dem1": str(tmp / "d1.tif"),
                "dem2": str(tmp / "d2.tif"),
                "noise_floor": 0.05,
                "difference": str(out)})
            self.assertEqual(result["changed_pixels"], 4)
            self.assertIn("write_qml", calls)

    def test_dem_volumes(self):
        calls = {}
        install_elev3d_stub(calls)
        install_rasterio_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            csv_out = tmp / "volumes.csv"
            poly_out = tmp / "change.geojson"
            result = runners.run_algorithm("dem_volumes", {
                "difference": str(tmp / "diff.tif"),
                "zones": str(tmp / "zones.geojson"),
                "noise_floor": 0.05,
                "pass_id": "DEM_001", "pass_date": "2026-05-01",
                "volumes_csv": str(csv_out),
                "polygons": str(poly_out)})
            self.assertEqual(result["net_m3"], 12.5)
            self.assertTrue(csv_out.exists())
            fc = json.loads(poly_out.read_text())
            self.assertEqual(fc["type"], "FeatureCollection")


class TestAlertsRunner(_RunnerCase):
    engine_names = ("alerts",)

    def test_render_report(self):
        install_alerts_engine_stub({})
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out = tmp / "report.html"
            result = runners.run_algorithm("alerts_render_report", {
                "alerts_jsonl": str(tmp / "alerts.jsonl"),
                "severity": "warning",
                "report_html": str(out)})
            self.assertEqual(result["alert_count"], 1)
            self.assertIn("<html>", out.read_text())


class TestLicenseRunner(_RunnerCase):
    engine_names = ("licensekit",)

    def test_validate_format_only(self):
        install_license_stub({})
        result = runners.run_algorithm(
            "license_validate", {"key": "SL1.fake.fake"})
        self.assertEqual(result["plan"], "pro")
        self.assertEqual(result["expires"], "2027-01-01")
        self.assertIn("signature not checked", result["status"])

    def test_validate_with_secret(self):
        calls = {}
        install_license_stub(calls)
        with tempfile.TemporaryDirectory() as tmpdir:
            secret = Path(tmpdir) / "secret.bin"
            secret.write_bytes(b"vendor-secret")
            result = runners.run_algorithm("license_validate", {
                "key": "SL1.fake.fake", "secret_file": str(secret)})
            self.assertEqual(result["status"], "valid")
            self.assertTrue(calls.get("check_license"))

    def test_validate_bad_key(self):
        install_license_stub({}, bad_key=True)
        result = runners.run_algorithm("license_validate", {"key": "bad"})
        self.assertTrue(result["status"].startswith("invalid key format"))

    def test_validate_no_key(self):
        install_license_stub({})
        result = runners.run_algorithm("license_validate", {"key": ""})
        self.assertEqual(result["status"], "no key provided")


class TestListGroupsIncludeNew(unittest.TestCase):
    def test_list_algorithms_counts(self):
        self.assertEqual(len(list_algorithms(group="Vegetation")), 2)
        self.assertEqual(len(list_algorithms(group="Flood")), 2)
        self.assertEqual(len(list_algorithms(group="Burn")), 1)
        self.assertEqual(len(list_algorithms(group="Coast")), 2)
        self.assertEqual(len(list_algorithms(group="Thermal")), 2)
        self.assertEqual(len(list_algorithms(group="Elevation")), 2)
        self.assertEqual(len(list_algorithms(group="Site monitoring")), 2)
        self.assertEqual(len(list_algorithms(group="Alerts")), 1)
        self.assertEqual(len(list_algorithms(group="Licensing")), 1)


if __name__ == "__main__":
    unittest.main()

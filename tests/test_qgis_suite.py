"""Tests for survey-qgis.

The pure layer is tested with stub suite engines injected into
``sys.modules`` (the real ``cogo``/``imagery``/``change`` packages are not
required). QGIS adapter modules are tested for import-safety without QGIS
installed. CLI commands are exercised end to end.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import survey_qgis
from survey_qgis import algorithms, cli, interop, plugin_metadata, runners
from survey_qgis.algorithms import (
    ALGORITHMS,
    ParamValidationError,
    get_algorithm,
    list_algorithms,
    list_groups,
    validate_params,
)
from survey_qgis.interop import EngineMissingError, check_engines, require_engine


# --------------------------------------------------------------------------
# Stub engines
# --------------------------------------------------------------------------

class _FakeMask:
    def __init__(self, any_value=False):
        self._any = any_value

    def any(self):
        return self._any


def _fake_grid(**kw):
    g = SimpleNamespace(data=_FakeArray([[0.0] * 4 for _ in range(4)]),
                        crs="EPSG:32618", pixel_area=100.0, nodata=None)
    for k, v in kw.items():
        setattr(g, k, v)
    return g


def install_change_stub(calls):
    change_io = SimpleNamespace(
        read_grid=lambda path, name=None: calls.setdefault(
            "read_grid", []).append(path) or _fake_grid(),
        write_cog=lambda grid, path: calls.setdefault(
            "write_cog", []).append(path),
        write_mask_geotiff=lambda mask, ref, path: calls.setdefault(
            "write_mask", []).append(path),
        write_report=lambda report, path: calls.setdefault(
            "write_report", []).append(path),
        change_report=lambda stats: {"stats": stats},
        write_csv=lambda records, path: calls.setdefault(
            "write_csv", []).append(path),
    )
    change = SimpleNamespace(
        io=change_io,
        detection=SimpleNamespace(
            detect=lambda t1, t2, cfg: calls.setdefault(
                "detect", []).append(cfg) or SimpleNamespace(
                    change_grid=_fake_grid(),
                    change_mask=_FakeMask(False),
                    gain_mask=_FakeMask(False),
                    loss_mask=_FakeMask(False),
                    threshold_used=0.2)),
        ChangeConfig=lambda **kw: SimpleNamespace(**kw),
        segmentation=SimpleNamespace(
            label_regions=lambda mask: (
                [[0] * 4 for _ in range(4)], [{"pixels": 3, "label": 1}])),
        polygons=SimpleNamespace(
            regions_to_features=lambda *a, **k: [{"type": "Feature"}],
            features_to_geojson=lambda feats, crs=None: {
                "type": "FeatureCollection", "features": feats},
            write_geojson=lambda fc, path: calls.setdefault(
                "write_geojson", []).append(path)),
        classification=SimpleNamespace(
            post_classification_compare=lambda t1, t2, names: {
                "changed_pixels": 7, "labels": [1, 2]},
            transition_grid=lambda t1, t2: _fake_grid(),
            summarize_transitions=lambda comp, area, names: [
                {"from_class": 1, "to_class": 2, "from_name": "a",
                 "to_name": "b", "pixels": 7, "area": 700.0}]),
        timeseries=SimpleNamespace(
            read_imagery_timeseries=lambda path: [{"scene_id": "s1"}],
            index_breaks=lambda rows, index, thr: [
                {"index": index, "from_date": "2024-01-01",
                 "to_date": "2024-02-01", "from_mean": 0.5,
                 "to_mean": 0.2, "delta": -0.3}]),
        statistics=SimpleNamespace(
            summarize_change=lambda *a: {"pixels": 5, "gain_pixels": 1,
                                         "loss_pixels": 4}),
        qgis=SimpleNamespace(
            difference_raster_qml=lambda vmin, vmax: "<qgis/>",
            mask_qml=lambda: "<qgis/>",
            change_polygon_qml=lambda: "<qgis/>",
            transition_qml=lambda names: "<qgis/>",
            write_qml=lambda text, path: calls.setdefault(
                "write_qml", []).append(path)),
    )
    sys.modules["change"] = change
    return change


def install_imagery_stub(calls):
    imagery = SimpleNamespace(
        indices=SimpleNamespace(
            required_bands=lambda name: {"NDVI": ("nir", "red"),
                                         "EVI": ("nir", "red", "blue")}[name],
            compute=lambda name, bands: calls.setdefault(
                "compute", []).append((name, sorted(bands))) or
                _FakeArray([[0.5] * 4 for _ in range(4)])))
    sys.modules["imagery"] = imagery
    return imagery


class _FakeArray(list):
    """Minimal numpy stand-in: supports .shape and .astype()."""

    @property
    def shape(self):
        rows = len(self)
        cols = len(self[0]) if rows else 0
        return (rows, cols)

    def astype(self, dtype):
        return self

    def __gt__(self, other):
        return _FakeMask(False)

    def __lt__(self, other):
        return _FakeMask(False)


class _FakeRasterioDataset:
    def __init__(self, calls, mode):
        self._calls = calls
        self.mode = mode
        self.profile = {"dtype": "float32", "count": 1,
                        "height": 4, "width": 4}

    def read(self, idx):
        return _FakeArray([[0.5] * 4 for _ in range(4)])

    def write(self, arr, idx):
        self._calls.setdefault("rasterio_write", []).append((arr, idx))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def install_rasterio_stub(calls):
    rio = SimpleNamespace(
        open=lambda path, mode="r", **kw: calls.setdefault(
            "rasterio_open", []).append((path, mode)) or
            _FakeRasterioDataset(calls, mode))
    sys.modules["rasterio"] = rio
    return rio


def install_cogo_stub(calls):
    def _point(**kw):
        return SimpleNamespace(northing=kw.get("northing", 0.0),
                               easting=kw.get("easting", 0.0),
                               name=kw.get("name", ""))
    cogo = SimpleNamespace(
        point=SimpleNamespace(Point=lambda **kw: _point(**kw)),
        inverse=SimpleNamespace(
            inverse=lambda a, b: calls.setdefault(
                "inverse", []).append((a, b)) or
                SimpleNamespace(azimuth=90.0, distance=100.0)),
        angles=SimpleNamespace(
            azimuth_to_bearing=lambda az: "N 90-00-00 E"),
        forward=SimpleNamespace(
            forward=lambda start, az, dist, name="": SimpleNamespace(
                northing=start.northing + 1.0, easting=start.easting + 1.0)),
        area=SimpleNamespace(
            polygon_area=lambda pts: 10000.0,
            polygon_perimeter=lambda pts: 400.0),
    )
    sys.modules["cogo"] = cogo
    return cogo


def drop_stubs(*names):
    for n in names:
        sys.modules.pop(n, None)


# --------------------------------------------------------------------------
# Params / registry
# --------------------------------------------------------------------------

class TestParams(unittest.TestCase):
    def test_bad_param_type_rejected(self):
        from survey_qgis.params import ParameterSpec
        with self.assertRaises(ValueError):
            ParameterSpec(name="x", label="X", type="nope")

    def test_enum_needs_options(self):
        from survey_qgis.params import ParameterSpec, PARAM_ENUM
        with self.assertRaises(ValueError):
            ParameterSpec(name="x", label="X", type=PARAM_ENUM)

    def test_bad_output_type_rejected(self):
        from survey_qgis.params import OutputSpec
        with self.assertRaises(ValueError):
            OutputSpec(name="x", label="X", type="nope")


class TestRegistry(unittest.TestCase):
    def test_eight_algorithms_registered(self):
        self.assertEqual(len(ALGORITHMS), 8)

    def test_groups(self):
        self.assertEqual(list_groups(), ["Change detection", "Imagery", "COGO"])

    def test_get_unknown_raises(self):
        with self.assertRaises(KeyError):
            get_algorithm("nope")

    def test_list_filter(self):
        self.assertEqual(len(list_algorithms(group="COGO")), 3)
        self.assertEqual(len(list_algorithms()), 8)

    def test_runner_names_resolve(self):
        for spec in ALGORITHMS.values():
            self.assertIn(spec.runner, runners._RUNNERS,
                          f"no runner for {spec.id}")

    def test_to_dict_round_trip(self):
        d = get_algorithm("cogo_inverse").to_dict()
        self.assertEqual(d["id"], "cogo_inverse")
        self.assertEqual(len(d["params"]), 4)
        self.assertEqual(len(d["outputs"]), 3)

    def test_engines_known(self):
        for spec in ALGORITHMS.values():
            for eng in spec.engines:
                self.assertIn(eng, interop.ENGINES.keys() | {"rasterio"})


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

class TestValidateParams(unittest.TestCase):
    def setUp(self):
        self.spec = get_algorithm("detect_change")

    def test_defaults_filled(self):
        p = validate_params(self.spec, {
            "t1": "a.tif", "t2": "b.tif",
            "difference": "d.tif", "mask": "m.tif"})
        self.assertEqual(p["method"], "difference")
        self.assertEqual(p["threshold_method"], "otsu")
        self.assertEqual(p["min_region_pixels"], 4)
        self.assertIsNone(p["report"])  # optional destination

    def test_missing_required_param(self):
        with self.assertRaises(ParamValidationError):
            validate_params(self.spec, {"t1": "a.tif", "difference": "d.tif",
                                        "mask": "m.tif"})

    def test_missing_destination(self):
        with self.assertRaises(ParamValidationError):
            validate_params(self.spec, {"t1": "a.tif", "t2": "b.tif",
                                        "mask": "m.tif"})

    def test_bad_enum(self):
        with self.assertRaises(ParamValidationError):
            validate_params(self.spec, {"t1": "a.tif", "t2": "b.tif",
                                        "method": "bogus",
                                        "difference": "d.tif", "mask": "m.tif"})

    def test_unknown_param(self):
        with self.assertRaises(ParamValidationError):
            validate_params(self.spec, {"t1": "a.tif", "t2": "b.tif",
                                        "difference": "d.tif", "mask": "m.tif",
                                        "zzz": 1})

    def test_integer_coercion(self):
        p = validate_params(self.spec, {"t1": "a.tif", "t2": "b.tif",
                                        "difference": "d.tif", "mask": "m.tif",
                                        "min_region_pixels": "9"})
        self.assertEqual(p["min_region_pixels"], 9)

    def test_non_integer_rejected(self):
        with self.assertRaises(ParamValidationError):
            validate_params(self.spec, {"t1": "a.tif", "t2": "b.tif",
                                        "difference": "d.tif", "mask": "m.tif",
                                        "min_region_pixels": "2.5"})

    def test_cogo_defaults(self):
        p = validate_params(get_algorithm("cogo_inverse"), {})
        self.assertEqual(p["easting2"], 100.0)


# --------------------------------------------------------------------------
# Interop
# --------------------------------------------------------------------------

class TestInterop(unittest.TestCase):
    def test_missing_engine_message(self):
        drop_stubs("change")
        with self.assertRaises(EngineMissingError) as ctx:
            require_engine("survey-change")
        self.assertIn("survey-change", str(ctx.exception))
        self.assertIn("pip install", str(ctx.exception))

    def test_unknown_engine(self):
        with self.assertRaises(ValueError):
            require_engine("survey-nope")

    def test_check_engines_shape(self):
        status = check_engines()
        self.assertEqual(set(status), set(interop.ENGINES))
        for v in status.values():
            self.assertTrue(v is None or isinstance(v, str))

    def test_require_rasterio_missing(self):
        drop_stubs("rasterio")
        with self.assertRaises(EngineMissingError) as ctx:
            interop.require_rasterio()
        self.assertIn("rasterio", str(ctx.exception))


# --------------------------------------------------------------------------
# Runners with stub engines
# --------------------------------------------------------------------------

class TestCogoRunners(unittest.TestCase):
    def setUp(self):
        self.calls = {}
        install_cogo_stub(self.calls)

    def tearDown(self):
        drop_stubs("cogo")

    def test_inverse(self):
        out = runners.run_algorithm("cogo_inverse", {
            "northing1": 0, "easting1": 0, "northing2": 0, "easting2": 100})
        self.assertEqual(out["azimuth"], 90.0)
        self.assertEqual(out["distance"], 100.0)
        self.assertEqual(out["bearing"], "N 90-00-00 E")

    def test_forward(self):
        out = runners.run_algorithm("cogo_forward", {
            "northing": 10, "easting": 20, "azimuth": 45, "distance": 10})
        self.assertEqual(out["northing_out"], 11.0)
        self.assertEqual(out["easting_out"], 21.0)

    def test_polygon_area(self):
        out = runners.run_algorithm("cogo_polygon_area", {
            "vertices": "0,0;100,0;100,100;0,100"})
        self.assertEqual(out["area"], 10000.0)
        self.assertEqual(out["perimeter"], 400.0)

    def test_bad_vertices(self):
        with self.assertRaises(ParamValidationError):
            runners.run_algorithm("cogo_polygon_area", {"vertices": "0,0;oops"})

    def test_feedback_called(self):
        seen = []
        runners.run_algorithm("cogo_inverse", {}, feedback=lambda m, p: seen.append(m))
        self.assertTrue(any("Running" in m for m in seen))
        self.assertTrue(any("Done" in m for m in seen))


class TestChangeRunners(unittest.TestCase):
    def setUp(self):
        self.calls = {}
        install_change_stub(self.calls)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def tearDown(self):
        drop_stubs("change")

    def _p(self, name):
        return str(Path(self.tmp.name) / name)

    def test_detect_change(self):
        out = runners.run_algorithm("detect_change", {
            "t1": "a.tif", "t2": "b.tif", "method": "cva",
            "difference": self._p("d.tif"), "mask": self._p("m.tif"),
            "report": self._p("r.json")})
        self.assertEqual(out["difference"], self._p("d.tif"))
        self.assertEqual(out["mask"], self._p("m.tif"))
        self.assertEqual(out["changed_pixels"], 5)
        self.assertEqual(self.calls["read_grid"], ["a.tif", "b.tif"])
        cfg = self.calls["detect"][0]
        self.assertEqual(cfg.method, "cva")
        self.assertIn(self._p("d.tif"), self.calls["write_cog"])
        self.assertIn(self._p("r.json"), self.calls["write_report"])

    def test_change_polygons(self):
        out = runners.run_algorithm("change_polygons", {
            "mask": "m.tif", "polygons": self._p("p.geojson")})
        self.assertEqual(out["polygons"], self._p("p.geojson"))
        self.assertEqual(out["feature_count"], 1)
        self.assertIn(self._p("p.geojson"), self.calls["write_geojson"])

    def test_classify_change(self):
        out = runners.run_algorithm("classify_change", {
            "t1_labels": "a.tif", "t2_labels": "b.tif",
            "transition": self._p("t.tif"), "table": self._p("t.csv")})
        self.assertEqual(out["changed_pixels"], 7)
        table = Path(self._p("t.csv")).read_text()
        self.assertIn("from_class,to_class", table)
        self.assertIn("700.0", table)

    def test_timeseries_breaks(self):
        out = runners.run_algorithm("timeseries_breaks", {
            "timeseries_csv": "ts.csv", "index": "NDVI",
            "breaks": self._p("b.csv")})
        self.assertEqual(out["break_count"], 1)
        content = Path(self._p("b.csv")).read_text()
        self.assertIn("NDVI", content)
        self.assertIn("from_date", content)

    def test_missing_engine(self):
        drop_stubs("change")
        with self.assertRaises(EngineMissingError):
            runners.run_algorithm("detect_change", {
                "t1": "a.tif", "t2": "b.tif",
                "difference": "d.tif", "mask": "m.tif"})


class TestSpectralIndexRunner(unittest.TestCase):
    def setUp(self):
        self.calls = {}
        install_imagery_stub(self.calls)
        install_rasterio_stub(self.calls)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def tearDown(self):
        drop_stubs("imagery", "rasterio")

    def test_ndvi(self):
        out = str(Path(self.tmp.name) / "ndvi.tif")
        res = runners.run_algorithm("spectral_index", {
            "index": "NDVI", "nir": "nir.tif", "red": "red.tif",
            "index_raster": out})
        self.assertEqual(res["index_raster"], out)
        self.assertEqual(res["index_name"], "NDVI")
        self.assertEqual(self.calls["compute"][0], ("NDVI", ["nir", "red"]))
        opens = [p for p, m in self.calls["rasterio_open"]]
        self.assertIn("nir.tif", opens)
        self.assertIn("red.tif", opens)
        self.assertIn((out, "w"), self.calls["rasterio_open"])
        self.assertTrue(self.calls["rasterio_write"])

    def test_missing_band_rejected(self):
        with self.assertRaises(ParamValidationError):
            runners.run_algorithm("spectral_index", {
                "index": "EVI", "nir": "n.tif", "red": "r.tif",
                "index_raster": "e.tif"})

    def test_missing_imagery_engine(self):
        drop_stubs("imagery")
        with self.assertRaises(EngineMissingError):
            runners.run_algorithm("spectral_index", {
                "index": "NDVI", "nir": "n.tif", "red": "r.tif",
                "index_raster": "o.tif"})


# --------------------------------------------------------------------------
# QGIS adapter import safety (no QGIS installed here)
# --------------------------------------------------------------------------

class TestQgisAdapterSafety(unittest.TestCase):
    def test_adapter_modules_import_without_qgis(self):
        import survey_qgis.qgis_algorithm  # noqa: F401
        import survey_qgis.qgis_provider  # noqa: F401
        import survey_qgis.plugin  # noqa: F401

    def test_algorithm_factory_needs_qgis(self):
        from survey_qgis.qgis_algorithm import create_algorithm_class
        with self.assertRaises(RuntimeError) as ctx:
            create_algorithm_class(get_algorithm("cogo_inverse"))
        self.assertIn("QGIS", str(ctx.exception))

    def test_provider_factory_needs_qgis(self):
        from survey_qgis.qgis_provider import create_provider
        with self.assertRaises(RuntimeError):
            create_provider()

    def test_class_factory_without_qgis(self):
        plugin = survey_qgis.classFactory(iface=None)
        self.assertIsNone(plugin.provider)
        self.assertIsNone(plugin.iface)


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------

class TestMetadata(unittest.TestCase):
    def test_render(self):
        text = plugin_metadata.render_metadata_txt()
        self.assertTrue(text.startswith("[general]"))
        self.assertIn(f"version={survey_qgis.__version__}", text)
        self.assertIn("qgisMinimumVersion=3.16", text)

    def test_write_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "metadata.txt")
            plugin_metadata.write_metadata_txt(path)
            self.assertIn("name=Survey Suite", Path(path).read_text())


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _run_cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


class TestCLI(unittest.TestCase):
    def test_list(self):
        code, out = _run_cli(["list"])
        self.assertEqual(code, 0)
        for aid in ("detect_change", "spectral_index", "cogo_inverse"):
            self.assertIn(aid, out)

    def test_list_group(self):
        code, out = _run_cli(["list", "--group", "COGO"])
        self.assertEqual(code, 0)
        self.assertIn("cogo_inverse", out)
        self.assertNotIn("detect_change", out)

    def test_describe(self):
        code, out = _run_cli(["describe", "cogo_forward"])
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["id"], "cogo_forward")
        self.assertTrue(d["params"])

    def test_run_cogo_inverse(self):
        install_cogo_stub({})
        try:
            code, out = _run_cli(["run", "cogo_inverse",
                                  "--param", "northing1=0",
                                  "--param", "easting1=0",
                                  "--param", "northing2=0",
                                  "--param", "easting2=100"])
        finally:
            drop_stubs("cogo")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["distance"], 100.0)

    def test_run_bad_params_exit2(self):
        code, _ = _run_cli(["run", "cogo_inverse", "--param", "bogus=1"])
        self.assertEqual(code, 2)

    def test_run_missing_engine_exit3(self):
        drop_stubs("cogo")
        code, _ = _run_cli(["run", "cogo_inverse"])
        self.assertEqual(code, 3)

    def test_engines(self):
        code, out = _run_cli(["engines"])
        self.assertEqual(code, 0)
        self.assertIn("survey-change", out)

    def test_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "survey_qgis.zip")
            code, _ = _run_cli(["package", "--out", out])
            self.assertEqual(code, 0)
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
            self.assertIn("survey_qgis/metadata.txt", names)
            self.assertIn("survey_qgis/__init__.py", names)
            self.assertIn("survey_qgis/qgis_provider.py", names)

    def test_license(self):
        code, out = _run_cli(["license"])
        self.assertEqual(code, 0)
        self.assertIn("community", out)


# --------------------------------------------------------------------------
# Licensing
# --------------------------------------------------------------------------

class TestLicensing(unittest.TestCase):
    def test_update_check_newer(self):
        from survey_qgis import licensing
        payload = json.dumps({"tag_name": "v9.9.9",
                              "html_url": "https://example.com"}).encode()

        class _Resp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with mock.patch.object(licensing.urllib.request, "urlopen",
                               return_value=_Resp()):
            res = licensing.check_for_updates()
        self.assertTrue(res["available"])
        self.assertEqual(res["latest"], "9.9.9")

    def test_update_check_offline(self):
        from survey_qgis import licensing
        with mock.patch.object(licensing.urllib.request, "urlopen",
                               side_effect=OSError("no net")):
            res = licensing.check_for_updates()
        self.assertFalse(res["available"])
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()

# survey-qgis

**QGIS distribution layer for the survey suite** — exposes the survey-suite
Python engines as QGIS Processing algorithms, plus a headless CLI that runs
the exact same algorithms outside QGIS.

This is the 11th module of the
[surveying & remote sensing suite](https://github.com/crieck2010/survey-suite):
it doesn't implement geoprocessing itself, it *distributes* the other engines
where GIS users already work — inside QGIS.

## What it provides

A **Survey Suite** provider in the QGIS Processing toolbox with 8 algorithms
in 3 groups:

| Group | Algorithm | Engine |
|---|---|---|
| Change detection | Detect change between two rasters | `survey-change` |
| Change detection | Vectorize change mask to polygons | `survey-change` |
| Change detection | Post-classification change comparison | `survey-change` |
| Change detection | Find breaks in a monitor time series | `survey-change` |
| Imagery | Compute spectral index (NDVI, NDWI, EVI, …) | `survey-imagery` |
| COGO | Inverse (bearing & distance) | `survey-cogo` |
| COGO | Forward (point by azimuth & distance) | `survey-cogo` |
| COGO | Polygon area & perimeter | `survey-cogo` |

And a headless CLI (`survey-qgis`) that runs every algorithm identically
outside QGIS — for scripts, servers, and testing.

## Layering (the important design decision)

```
┌─────────────────────────────────────────────────────────┐
│ QGIS adapter  qgis_algorithm · qgis_provider · plugin    │  thin, QGIS-only
├─────────────────────────────────────────────────────────┤
│ Pure layer    algorithms (specs) · runners · interop     │  no QGIS imports
│               params · licensing · cli                  │  no engine imports
└─────────────────────────────────────────────────────────┘
```

- **Algorithm specs are data.** Each algorithm is one `AlgorithmSpec` in
  `algorithms.py` (id, name, group, params, outputs, runner, engines). The
  QGIS provider, the CLI, and the docs are all generated from that single
  registry — adding an algorithm means adding one spec + one runner.
- **Engines are lazy and optional.** The package installs with zero
  dependencies. Each runner imports its engine (`cogo`, `imagery`,
  `change`) on first use; a missing engine produces a clear
  `pip install git+https://github.com/crieck2010/<engine>.git` message,
  never a bare `ImportError`.
- **QGIS imports are quarantined.** `qgis.core` is imported only inside
  factory functions. Every other module — specs, runners, CLI, tests —
  imports and runs with no QGIS installed.

## Install

**As a QGIS plugin** (recommended for GIS users) — see
[docs/QGIS_INSTALL.md](docs/QGIS_INSTALL.md):

```bash
survey-qgis package --out survey_qgis.zip
# QGIS → Plugins → Manage and Install Plugins → Install from ZIP
```

**As a Python package** (headless use):

```bash
pip install git+https://github.com/crieck2010/survey-qgis.git
pip install git+https://github.com/crieck2010/survey-change.git  # for change algos
pip install git+https://github.com/crieck2010/survey-imagery.git  # for indices
pip install git+https://github.com/crieck2010/survey-cogo.git     # for COGO
pip install rasterio  # for the spectral-index algorithm
```

## Quick start

```bash
# What algorithms exist?
survey-qgis list

# What engines are installed?
survey-qgis engines

# COGO inverse, no QGIS needed
survey-qgis run cogo_inverse --param northing1=0 --param easting1=0 \
  --param northing2=0 --param easting2=100

# Change detection between two NDVI COGs
survey-qgis run detect_change --param t1=ndvi_2024.tif --param t2=ndvi_2025.tif \
  --param method=cva --param difference=diff.tif --param mask=mask.tif \
  --param report=report.json

# NDVI from Sentinel-2 bands
survey-qgis run spectral_index --param index=NDVI --param nir=B08.tif \
  --param red=B04.tif --param index_raster=ndvi.tif
```

Output destinations are passed under the *output name* (`difference=…`,
`mask=…`, `polygons=…`). In QGIS these become the usual Processing
destination fields automatically.

## In QGIS

Install the ZIP, then find **Survey Suite** in the Processing toolbox.
Algorithms accept raster layers straight from the map, chain in the
Graphical Modeler, and run in batch mode. Raster/vector outputs come with
`.qml` sidecars so they open already styled.

## Interoperability

- **survey-change**: full change-detection workflow (detect → polygons →
  post-classification → time-series breaks) with QML-styled outputs.
- **survey-imagery**: spectral indices from per-band rasters; feeds the
  change algorithms with NDVI/NDWI time series.
- **survey-cogo**: inverse/forward/area computations as toolbox algorithms.
- **survey-raster / survey-gnss / others**: the `interop.ENGINES` registry
  already knows every suite engine; new algorithms only need a spec entry.

See [docs/INTEROP.md](docs/INTEROP.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## API

```python
from survey_qgis.runners import run_algorithm

result = run_algorithm("cogo_inverse", {
    "northing1": 0, "easting1": 0, "northing2": 0, "easting2": 100})
# {"azimuth": 90.0, "bearing": "N 90-00-00 E", "distance": 100.0}
```

Full reference: [docs/API.md](docs/API.md).

## Tests

52 tests, no QGIS and no sibling engines required (stub engines are
injected into `sys.modules`):

```bash
python -m unittest discover -s tests
```

## Versioning

Semantic versioning with a changelog ([CHANGELOG.md](CHANGELOG.md)).
Current: **0.1.0**.

## License

MIT — see [LICENSE](LICENSE). Includes stubbed license-key and
update-check hooks (`survey-qgis license`, `survey-qgis update-check`)
per suite convention; payments go through a merchant of record
(Gumroad / Lemon Squeezy), never custom billing code.

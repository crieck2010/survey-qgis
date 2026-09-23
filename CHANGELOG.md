# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-23

### Added
- QGIS Processing provider ("Survey Suite") with 8 algorithms in 3 groups:
  - Change detection: `detect_change`, `change_polygons`, `classify_change`,
    `timeseries_breaks` (via `survey-change`)
  - Imagery: `spectral_index` — NDVI, NDWI, NDMI, NDBI, NBR, EVI, SAVI, BSI
    (via `survey-imagery` + rasterio)
  - COGO: `cogo_inverse`, `cogo_forward`, `cogo_polygon_area`
    (via `survey-cogo`)
- Pure, QGIS-free layer: `AlgorithmSpec` registry, spec validation with
  type coercion and defaults, runners with progress-feedback callbacks,
  lazy engine imports with `EngineMissingError` install hints.
- Thin QGIS adapter: spec-driven `QgsProcessingAlgorithm` factory,
  provider, plugin lifecycle class, generated `metadata.txt`.
- Headless CLI: `list`, `describe`, `run`, `engines`, `package` (builds the
  QGIS "Install from ZIP" archive), `metadata`, `license`, `update-check`.
- QML sidecars written next to raster/vector outputs so they open styled.
- License-key and update-check hooks (stubbed, per suite convention).
- 52 unittests covering specs, validation, runners (stub engines),
  QGIS-less import safety, metadata, CLI, and licensing.
- Docs: README, API reference, architecture, interoperability matrix,
  QGIS install guide; `examples/` with headless recipes.

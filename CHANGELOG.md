# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-09-25

### Added
- 17 new Processing algorithms covering the full earthwatch-suite
  remote-sensing line (registry grows from 8 to 25 algorithms in 12 groups):
  - Imagery: `imagery_composite` (temporal composite), `imagery_zonal_timeseries`
  - Site monitoring: `monitor_run` (run a survey-monitor site config,
    synthetic by default), `monitor_alerts_map` (alerts → GeoJSON layer)
  - Vegetation: `vegetation_vigor_map`, `vegetation_timeseries`
  - Flood: `flood_water_mask`, `flood_polygons`
  - Burn: `burn_severity` (dNBR + severity classification in one pass)
  - Coast: `coast_shoreline`, `coast_transect_positions`
  - Thermal: `thermal_lst`, `thermal_uhi`
  - Elevation: `dem_difference`, `dem_volumes` (cut/fill CSV + polygons)
  - Alerts: `alerts_render_report` (HTML site report from `alerts.jsonl`)
  - Licensing: `license_validate` (parse, and optionally HMAC-verify, a key)
- `docs/ALGORITHMS.md`: one section per algorithm (purpose, inputs,
  outputs, verified engine versions) plus a note on deliberate deferrals.
- 28 new unittests for the remote-sensing registry and runners
  (engine-stub based; no QGIS or real engines needed).

### Changed
- Bumped version to 0.2.0; README algorithm table and install list cover
  all 12 engines.
- QML sidecars are written next to all new raster/vector outputs, so
  change polygons and vigor/severity/water masks open styled — no
  separate styling algorithms were added.

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

# Interoperability

## Suite engine matrix

`interop.ENGINES` knows every suite engine (pip name → import name).
Algorithms declare what they need in `AlgorithmSpec.engines`; anything not
listed is never imported.

| Engine | Algorithms using it | How |
|---|---|---|
| `survey-change` | `detect_change`, `change_polygons`, `classify_change`, `timeseries_breaks` | `io.read_grid`/`write_cog`, `detection.detect` + `ChangeConfig`, `segmentation`, `polygons`, `classification`, `timeseries`, `statistics`, `qgis` QML writers |
| `survey-imagery` | `spectral_index` | `indices.required_bands` / `indices.compute`; consumes per-band rasters (e.g. Sentinel-2 COGs from a monitor run) and feeds change detection |
| `survey-cogo` | `cogo_inverse`, `cogo_forward`, `cogo_polygon_area` | `point.Point`, `inverse.inverse`, `angles.azimuth_to_bearing`, `forward.forward`, `area.polygon_area/perimeter` |
| `survey-raster`, `survey-gnss`, `survey-levels`, `survey-adjust`, `survey-geodesy`, `survey-pointcloud` | — (registry-ready) | Declared in `ENGINES`; add specs + runners to expose them |

`rasterio` is treated as an external (non-suite) requirement for the
`spectral_index` runner only.

## Canonical workflows across modules

**Monitor → detect → vectorize (the flagship loop):**

1. `survey-imagery` monitor refreshes a site → `timeseries.csv` + per-pass
   index COGs (NDVI).
2. `survey-qgis` → *Detect change between two rasters* on two NDVI COGs →
   difference COG + mask + report (QML-styled on load).
3. → *Vectorize change mask to polygons* → GeoJSON with per-polygon
   area and change statistics, ready for a disturbance report.
4. → *Find breaks in a monitor time series* on `timeseries.csv` → dated
   onset table.

**Post-classification:** two label rasters → *Post-classification change
comparison* → transition COG + from-to area CSV.

**Field COGO in the toolbox:** *Inverse* / *Forward* / *Polygon area*
expose `survey-cogo` to QGIS users without leaving the Processing toolbox,
and to scripts via `survey-qgis run`.

## Data contracts

- Rasters are passed as file paths (GeoTIFF/COG); CRS handling stays in the
  engines.
- `timeseries_breaks` reads the exact `timeseries.csv` schema written by
  `survey-imagery`'s monitor (`scene_id`, `date`, `<INDEX>_mean`, …) via
  `survey-change`'s `read_imagery_timeseries`.
- GeoJSON outputs carry the source CRS; QML sidecars make QGIS styling
  automatic.

## Adding a new engine binding

1. Ensure the engine is in `interop.ENGINES` (all suite engines already are).
2. Write the `AlgorithmSpec` + `run_*` function.
3. The QGIS provider, CLI, validation, and docs pick it up with no further
   changes.

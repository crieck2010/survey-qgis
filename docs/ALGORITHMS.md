# Algorithm reference

Every QGIS Processing algorithm shipped by survey-qgis, generated from the
`AlgorithmSpec` registry (`survey_qgis/algorithms.py`). Each section gives
the purpose, the inputs, the outputs, and the engine versions the runner was
verified against. Unless noted otherwise, raster inputs are read with
rasterio (any GDAL-readable format) and raster outputs are GeoTIFFs that keep
the input grid, CRS, and nodata handling; vector outputs are GeoJSON; QML
style sidecars are written next to raster/vector outputs on a best-effort
basis (a missing QML never fails the algorithm).

Engine compatibility was verified against the releases below (September
2026). The runners import engines lazily and only call documented public
APIs; patch releases of the engines stay compatible, minor releases are
re-verified before each survey-qgis release.

| Engine (pip) | Import | Verified version |
|---|---|---|
| `survey-imagery` | `imagery` | 0.1.1 |
| `survey-change` | `change` | 0.1.0 |
| `survey-monitor` | `monitor` | 0.1.0 |
| `survey-alerts` | `alerts` | 0.1.0 |
| `survey-license` | `licensekit` | 0.1.0 |
| `survey-vegetation` | `vegetation` | 0.1.0 |
| `survey-flood` | `flood` | 0.1.0 |
| `survey-burn` | `burn` | 0.1.0 |
| `survey-coast` | `coast` | 0.1.0 |
| `survey-thermal` | `thermal` | 0.1.0 |
| `survey-3d` | `elev3d` | 0.1.0 |
| `survey-cogo` | `cogo` | 0.1.0 |

Headless usage for every algorithm:

```bash
survey-qgis run <algorithm-id> --param key=value [--param key=value ...]
survey-qgis describe <algorithm-id>   # full spec as JSON
```

---

## Change detection (`survey-change` 0.1.0)

### `detect_change` — Detect change between two rasters

**Purpose.** Pixel-wise change detection between an earlier and a later
raster (difference, normalized difference, relative change, ratio, or change
vector analysis) with Otsu/manual/percentile thresholding.

**Inputs.** `t1` (raster, earlier), `t2` (raster, later, same grid),
`method` (enum), `threshold_method` (enum), `threshold` (number, optional),
`min_region_pixels` (integer, default 4).

**Outputs.** `difference` (raster), `mask` (raster), `report` (file),
`changed_pixels` (number).

### `change_polygons` — Vectorize change mask to polygons

**Purpose.** Label connected change regions and vectorize them to polygons
with per-feature statistics. A `.qml` style sidecar is written next to the
GeoJSON, so no separate styling algorithm is needed.

**Inputs.** `mask` (raster, binary), `change_raster` (raster, optional),
`simplify` (number, default 0.0), `min_region_pixels` (integer, default 1).

**Outputs.** `polygons` (vector GeoJSON), `feature_count` (number).

### `classify_change` — Post-classification change comparison

**Purpose.** Compare two classified rasters pixel-wise and summarize
from/to class transitions.

**Inputs.** `t1_labels` (raster), `t2_labels` (raster),
`class_names` (file, optional JSON mapping like `{"1": "forest"}`).

**Outputs.** `transition` (raster), `table` (file, transition table),
`changed_pixels` (number).

### `timeseries_breaks` — Find breaks in a monitor time series

**Purpose.** Detect breakpoints in a survey-imagery per-pass index
time-series CSV.

**Inputs.** `timeseries_csv` (file), `index` (string, default `NDVI`),
`threshold` (number, default 0.15 — minimum absolute mean-value step).

**Outputs.** `breaks` (file, breaks table), `break_count` (number).

---

## Imagery (`survey-imagery` 0.1.1)

### `spectral_index` — Compute spectral index (NDVI, NDWI, EVI, …)

**Purpose.** Compute NDVI, NDWI, NDMI, NDBI, NBR, EVI, SAVI, or BSI from
band rasters.

**Inputs.** `red`, `nir` (rasters), optional `blue`/`swir1` (rasters),
`index` (enum), `cloud` (raster, optional).

**Outputs.** `index` (raster GeoTIFF).

### `imagery_composite` — Temporal composite of index rasters

**Purpose.** Stack same-shape index rasters from a folder (e.g. per-pass
NDVI) and composite them with a NaN-aware median/mean/max/min.

**Inputs.** `input_folder` (folder), `method` (enum: median/mean/max/min,
default median).

**Outputs.** `composite` (raster GeoTIFF), `scene_count` (number).

### `imagery_zonal_timeseries` — Zonal time series from an index raster

**Purpose.** Compute per-zone statistics of one index raster inside polygons
from a zones file, and write one row per zone to a time-series CSV. The
`scene_id` column is namespaced as `<pass_id>@<zone_id>` (or just
`<zone_id>`) so rows from different zones never collide in
`survey-imagery`'s `(scene_id, index)` merge key.

**Inputs.** `index_raster` (raster), `zones` (vector), `zones_crs`
(string, default `EPSG:4326`), `pass_id` (string), `pass_date` (string),
`index_name` (string, default `NDVI`), `cloud_cover` (number, optional).

**Outputs.** `timeseries_csv` (file), `zone_count` (number).

---

## Site monitoring (`survey-monitor` 0.1.0)

### `monitor_run` — Run site monitoring config

**Purpose.** Run a survey-monitor site config headlessly: list new satellite
passes, compute per-pass index metrics, evaluate thresholds, and append
alert events (`alerts.jsonl` + `alerts.geojson`, plus `state.json` and
`summary.json`) to the store folder. With `synthetic` on (default), the
seeded demo pass provider is used and no network is needed.

**Inputs.** `site_config` (file — site JSON/YAML per
`survey-monitor/docs/SITE_CONFIG.md`), `synthetic` (boolean, default true),
`since` (string, optional, `YYYY-MM-DD`).

**Outputs.** `store_folder` (folder), `passes_processed` (number),
`alerts_fired` (number).

### `monitor_alerts_map` — Alerts to GeoJSON layer

**Purpose.** Read a monitored site's `alerts.jsonl` from its store folder
and write a QGIS-ready alerts GeoJSON layer, optionally filtered by
severity.

**Inputs.** `store_folder` (folder), `site_id` (string), `severity` (enum:
all/info/warning/critical, default all).

**Outputs.** `alerts_geojson` (vector), `alert_count` (number).

---

## Vegetation (`survey-vegetation` 0.1.0)

### `vegetation_vigor_map` — Vigor-class map

**Purpose.** Classify a vigor-index raster (NDVI/EVI/SAVI) into vigor bands
(water / bare / stressed / moderate / vigorous / very dense) and write a
uint8 class GeoTIFF with a QGIS style sidecar.

**Inputs.** `index_raster` (raster).

**Outputs.** `vigor_map` (raster), `classes_found` (number).

### `vegetation_timeseries` — Per-zone vigor time series

**Purpose.** Compute per-zone vigor statistics of an index raster and append
one record per zone to a survey-vegetation time-series CSV (incremental and
deduplicated across passes).

**Inputs.** `index_raster` (raster), `zones` (vector), `pass_id` (string),
`pass_date` (string), `index_name` (string, default `NDVI`), `cloud_cover`
(number, optional).

**Outputs.** `timeseries_csv` (file), `zone_count` (number).

---

## Flood (`survey-flood` 0.1.0)

### `flood_water_mask` — Water mask from index raster

**Purpose.** Threshold an NDWI/MNDWI raster into a boolean water mask,
despeckle small components, and write a uint8 mask GeoTIFF with a QGIS
style sidecar.

**Inputs.** `index_raster` (raster), `threshold` (number, default 0.0),
`despeckle_pixels` (integer, default 4).

**Outputs.** `water_mask` (raster), `water_pixels` (number).

### `flood_polygons` — Flood-extent polygons

**Purpose.** Vectorize a binary water mask into flood-extent polygons
(GeoJSON) with per-feature pixel counts and area in hectares.

**Inputs.** `water_mask` (raster, binary), `min_pixels` (integer,
default 4).

**Outputs.** `polygons` (vector GeoJSON), `feature_count` (number).

---

## Burn (`survey-burn` 0.1.0)

### `burn_severity` — dNBR burn severity

**Purpose.** Compute dNBR (pre-fire NBR minus post-fire NBR) from two
aligned NBR rasters and classify it into USGS fire-severity bands. Writes a
dNBR raster and a severity-class raster, each with a QGIS style sidecar.

**Inputs.** `pre_nbr` (raster), `post_nbr` (raster, same grid).

**Outputs.** `dnbr` (raster), `severity` (raster), `burned_pixels`
(number).

---

## Coast (`survey-coast` 0.1.0)

### `coast_shoreline` — Extract shoreline from water mask

**Purpose.** Trace the water/land boundary of a binary water mask into
shoreline polylines (GeoJSON LineStrings in the raster's map units). The
raster should be in a projected metre CRS; `pixel_size_m` should match its
resolution.

**Inputs.** `water_mask` (raster, binary), `pixel_size_m` (number, default
10.0), `min_length_m` (number, default 0.0).

**Outputs.** `shoreline` (vector GeoJSON), `segment_count` (number).

### `coast_transect_positions` — Shoreline positions on transects

**Purpose.** Intersect a shoreline GeoJSON with transect lines (running
landward to seaward, in map meters) and append per-transect shoreline
positions (meters from transect origin) to a positions CSV for rate
analysis.

**Inputs.** `shoreline` (vector GeoJSON), `transects` (vector),
`pass_id` (string), `pass_date` (string), `index_name` (string, default
`ndwi`), `pixel_size_m` (number, default 10.0).

**Outputs.** `positions_csv` (file), `transect_count` (number).

---

## Thermal (`survey-thermal` 0.1.0)

### `thermal_lst` — Land surface temperature (LST)

**Purpose.** Convert a Landsat Collection-2 Level-2 ST_B10
surface-temperature raster (digital numbers) to land surface temperature in
Celsius. Follows the engine's DN convention (`C = DN × 0.01 − 273.15`).

**Inputs.** `st_raster` (raster).

**Outputs.** `lst_celsius` (raster GeoTIFF), `mean_celsius` (number).

### `thermal_uhi` — Urban heat-island intensity

**Purpose.** Compute per-zone urban heat-island intensity (zone mean LST
minus rural reference zone mean, in °C) from an LST raster and write a UHI
CSV. Give `reference_zone` explicitly for a single pass; the engine
auto-selects the coolest zone once a zone has ≥ 3 passes.

**Inputs.** `lst_raster` (raster, Celsius), `zones` (vector),
`reference_zone` (string, optional), `pass_id` (string), `pass_date`
(string).

**Outputs.** `uhi_csv` (file), `zone_count` (number).

---

## Elevation (`survey-3d` 0.1.0)

### `dem_difference` — DEM difference raster

**Purpose.** Difference two aligned DEM rasters (later minus earlier) with
a noise floor; writes the thresholded elevation-change raster (meters) with
a QGIS style sidecar.

**Inputs.** `dem1` (raster, earlier), `dem2` (raster, later, same grid),
`noise_floor` (number, default 0.0).

**Outputs.** `difference` (raster GeoTIFF), `changed_pixels` (number).

### `dem_volumes` — Cut/fill volumes per zone

**Purpose.** Compute cut/fill/net earthwork volumes (m³) per zone from a
DEM-difference raster, with propagated uncertainty when a per-DEM vertical
RMSE is given. Appends to a volume time-series CSV and writes change
polygons (GeoJSON).

**Inputs.** `difference` (raster, Δh in meters), `zones` (vector),
`noise_floor` (number, default 0.0), `dem_rmse` (number, optional),
`pass_id` (string), `pass_date` (string).

**Outputs.** `volumes_csv` (file), `polygons` (vector GeoJSON),
`net_m3` (number).

---

## Alerts (`survey-alerts` 0.1.0)

### `alerts_render_report` — Render alert report (HTML)

**Purpose.** Read a survey-monitor `alerts.jsonl` file and render a
print-friendly HTML site report (print to PDF from a browser for the PDF
deliverable). Severity filtering is delegated to the engine's
`min_severity`.

**Inputs.** `alerts_jsonl` (file), `severity` (enum:
info/warning/critical, default info).

**Outputs.** `report_html` (file), `alert_count` (number).

---

## Licensing (`survey-license` 0.1.0)

### `license_validate` — Validate license key

**Purpose.** Inspect a survey-license key: parse its payload (plan, expiry,
entitlements) and, when a vendor secret file is given, fully validate its
HMAC signature offline. The secret is used only for validation — never
logged or returned.

**Inputs.** `key` (string), `secret_file` (file, optional).

**Outputs.** `status` (string), `key_id` (string), `plan` (string),
`expires` (string).

---

## COGO (`survey-cogo` 0.1.0)

### `cogo_inverse` — Inverse (bearing & distance)

**Purpose.** Bearing and distance between two known points.

**Inputs.** `from_northing`, `from_easting`, `to_northing`, `to_easting`
(numbers).

**Outputs.** `azimuth`, `distance` (numbers), `bearing` (string).

### `cogo_forward` — Forward (point by azimuth & distance)

**Purpose.** Coordinates of a point from a start point, azimuth, and
distance.

**Inputs.** `northing`, `easting` (numbers), `azimuth` (number, degrees),
`distance` (number).

**Outputs.** `northing_out`, `easting_out` (numbers).

### `cogo_polygon_area` — Polygon area & perimeter

**Purpose.** Area and perimeter of a polygon from a vertex list
(`easting,northing;…`).

**Inputs.** `vertices` (string).

**Outputs.** `area`, `perimeter` (numbers).

---

## Deliberately not added

- **Change-polygon styling pass.** `change_polygons` already writes a
  `.qml` style sidecar next to its GeoJSON, so a separate styling
  algorithm would add nothing.
- **Live STAC acquisition algorithms.** `monitor_run` covers pass
  acquisition through survey-monitor (synthetic provider by default,
  live STAC when `synthetic` is off); per-algorithm STAC downloaders
  would duplicate it.

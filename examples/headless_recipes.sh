#!/usr/bin/env bash
# Headless recipes for survey-qgis (no QGIS required).
# Requires the engines for the recipes you run; COGO needs survey-cogo only.
set -euo pipefail

echo "== Algorithms =="
survey-qgis list

echo "== Engine status =="
survey-qgis engines

echo "== COGO inverse: 100 m due east =="
survey-qgis run cogo_inverse \
  --param northing1=0 --param easting1=0 \
  --param northing2=0 --param easting2=100

echo "== COGO forward: 100 m at azimuth 90 =="
survey-qgis run cogo_forward \
  --param northing=0 --param easting=0 \
  --param azimuth=90 --param distance=100

echo "== Polygon area: 1 ha square =="
survey-qgis run cogo_polygon_area \
  --param vertices="0,0;100,0;100,100;0,100"

# --- Uncomment with real rasters + engines installed ---
# echo "== NDVI from Sentinel-2 bands =="
# survey-qgis run spectral_index --param index=NDVI \
#   --param nir=B08.tif --param red=B04.tif --param index_raster=ndvi.tif
#
# echo "== Change detection between two NDVI passes =="
# survey-qgis run detect_change --param t1=ndvi_2024.tif --param t2=ndvi_2025.tif \
#   --param method=cva --param difference=diff.tif --param mask=mask.tif \
#   --param report=report.json
#
# echo "== Vectorize the change mask =="
# survey-qgis run change_polygons --param mask=mask.tif --param change_raster=diff.tif \
#   --param polygons=change.geojson

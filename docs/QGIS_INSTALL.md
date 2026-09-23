# Installing survey-qgis in QGIS

## Option A — Install from ZIP (recommended)

On any machine with Python and this package installed:

```bash
pip install git+https://github.com/crieck2010/survey-qgis.git
survey-qgis package --out survey_qgis.zip
```

Then in QGIS:

1. **Plugins → Manage and Install Plugins → Install from ZIP**
2. Select `survey_qgis.zip` → Install Plugin
3. Enable it in the Installed tab if needed

The **Survey Suite** provider appears in the Processing toolbox
(**Processing → Toolbox**). Requires QGIS 3.16+.

> The ZIP is built from the installed `survey_qgis` package directory,
> which *is* the plugin folder (`metadata.txt` + `classFactory` live in
> the package). Re-run `survey-qgis package` after each upgrade.

## Option B — Manual copy (development)

Copy the `survey_qgis` package directory into your QGIS plugins folder
and restart QGIS:

- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

For live development, `pip install -e` the repo and symlink the source
`src/survey_qgis` directory into the plugins folder instead.

## Engine dependencies

The plugin itself needs nothing, but each algorithm needs its engine
installed **in the Python that QGIS uses**:

| Algorithm group | `pip install` (in QGIS's Python) |
|---|---|
| Change detection | `git+https://github.com/crieck2010/survey-change.git` |
| Imagery | `git+https://github.com/crieck2010/survey-imagery.git` + `rasterio` |
| COGO | `git+https://github.com/crieck2010/survey-cogo.git` |

If an engine is missing, the algorithm fails with a message naming the
exact install command. In QGIS, install packages via the **OSGeo4W Shell**
(Windows) or the Python running QGIS:

```bash
# OSGeo4W shell on Windows, or the QGIS python on other platforms:
python -m pip install "git+https://github.com/crieck2010/survey-change.git"
```

## Using the algorithms

- Find them under the **Survey Suite** provider in the Processing toolbox,
  grouped as *Change detection*, *Imagery*, *COGO*.
- Raster inputs accept layers straight from the map; outputs written by
  `survey-change` arrive with `.qml` sidecars so they open pre-styled.
- All algorithms work in the **Graphical Modeler** and **Batch Processing**
  mode like any native algorithm.
- Missing-engine errors appear in the algorithm log with the pip command
  to fix them.

## Headless / server use (no QGIS)

```bash
pip install git+https://github.com/crieck2010/survey-qgis.git
survey-qgis run detect_change --param t1=a.tif --param t2=b.tif \
  --param difference=diff.tif --param mask=mask.tif
```

Identical specs, validation, and runners as inside QGIS.

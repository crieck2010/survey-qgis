# API reference

## `survey_qgis.runners`

```python
from survey_qgis.runners import run_algorithm
```

**`run_algorithm(algorithm_id, params, feedback=None) -> dict`**
Validate `params` against the algorithm spec, run it, and return
`{output_name: value}`. File outputs are paths; scalar outputs are
numbers/strings. `feedback` is an optional `callable(message, percent)`.

Raises `ParamValidationError` (bad params), `EngineMissingError`
(missing suite engine), `KeyError` (unknown algorithm).

Individual runners (`run_detect_change`, `run_cogo_inverse`, …) take
already-validated params; prefer `run_algorithm`.

## `survey_qgis.algorithms`

- `ALGORITHMS: dict[str, AlgorithmSpec]` — the registry (8 entries).
- `get_algorithm(id) -> AlgorithmSpec` — `KeyError` if unknown.
- `list_algorithms(group=None)`, `list_groups()`.
- `validate_params(spec, params) -> dict` — fills defaults, coerces
  `number`/`integer`/`boolean`/`enum`, accepts destination paths under
  output names, raises `ParamValidationError`.
- `AlgorithmSpec.to_dict()` — JSON-serializable spec (`describe` output).

## `survey_qgis.params`

`ParameterSpec` / `OutputSpec` dataclasses. Parameter types: `raster`,
`vector`, `file`, `folder`, `enum`, `number`, `integer`, `string`,
`boolean`. Output types: `raster`, `vector`, `file`, `folder`,
`number`, `string`.

## `survey_qgis.interop`

- `ENGINES` — pip name → import name for all 9 suite engines.
- `require_engine(pip_name)` — import or raise `EngineMissingError`
  with the exact install command.
- `require_rasterio()` — same for rasterio.
- `engine_version(pip_name) -> str | None`, `check_engines()`.

## `survey_qgis.cli`

`survey-qgis list | describe <id> | run <id> --param k=v [--verbose] |
engines | package [--out] | metadata [--out] | license [--key] |
update-check`

`--param` values are sniffed (`true`→bool, `1`→int, `1.5`→float,
else string); full coercion happens in `validate_params`.

## `survey_qgis.qgis_algorithm` / `qgis_provider` / `plugin`

QGIS-only. `create_algorithm_class(spec)` builds a
`QgsProcessingAlgorithm` subclass; `create_provider()` builds the
`QgsProcessingProvider`; `SurveySuitePlugin` handles `initGui`/`unload`;
`classFactory(iface)` is the QGIS entry point. All raise a clear
`RuntimeError` when QGIS is unavailable instead of failing at import.

## `survey_qgis.plugin_metadata`

`METADATA` dict, `render_metadata_txt()`, `write_metadata_txt(path)`.
Regenerate the committed copy with `survey-qgis metadata`.

## `survey_qgis.licensing`

`check_license(key=None) -> dict`, `check_for_updates() -> dict`
(network failures return `{"available": False, "error": ...}`; never
called automatically).

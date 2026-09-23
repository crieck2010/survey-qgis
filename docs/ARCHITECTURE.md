# Architecture

## The problem this module solves

The survey suite is a set of pure-Python engines. GIS analysts live in QGIS.
`survey-qgis` is the **distribution layer**: it puts the engines inside the
QGIS Processing toolbox (and model designer, and batch runner) without
coupling the engines to QGIS.

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│ ADAPTER (QGIS-only, imported lazily)                          │
│  qgis_algorithm.py  spec -> QgsProcessingAlgorithm factory   │
│  qgis_provider.py   QgsProcessingProvider factory            │
│  plugin.py          plugin lifecycle (initGui/unload)        │
│  __init__.py        classFactory                             │
├──────────────────────────────────────────────────────────────┤
│ PURE LAYER (no qgis import, no engine import at module load) │
│  params.py       ParameterSpec / OutputSpec (data)           │
│  algorithms.py   AlgorithmSpec registry + validate_params    │
│  runners.py       run_* implementations + run_algorithm      │
│  interop.py      lazy engine imports, ENGINES registry       │
│  cli.py          headless runner over the same specs         │
│  licensing.py    license-key / update-check hooks            │
│  plugin_metadata.py  metadata.txt single source of truth     │
└──────────────────────────────────────────────────────────────┘
```

### Why specs are data

`ALGORITHMS` in `algorithms.py` is the single source of truth. The QGIS
provider builds `QgsProcessingAlgorithm` classes from it, the CLI's
`list`/`describe`/`run` read it, and `validate_params` enforces it. Adding
algorithm #9 is:

1. Append one `AlgorithmSpec` (id, name, group, params, outputs, runner,
   engines).
2. Add one `run_*` function in `runners.py` and register it in `_RUNNERS`.

No QGIS code changes. The spec also drives `docs` generation if we ever
want it.

### Destination parameters

QGIS convention: file outputs are *destination parameters*. So output
paths are keyed by **output name** (`difference=…`, `polygons=…`), not by
separate `output_*` params. `validate_params` accepts destination paths
under output names for file-ish outputs; the only optional one is the
JSON `report` sidecar. The QGIS adapter adds `QgsProcessingParameter*Destination`
entries named after the outputs and feeds the resolved paths back to the
runner under those names. Scalar outputs (numbers/strings) become
`QgsProcessingOutputNumber`/`String` entries.

### Feedback

Runners take an optional `feedback(message, percent)` callable. The CLI
wraps it as stderr progress lines; the QGIS adapter wraps
`QgsProcessingFeedback.pushInfo/setProgress`. Runners never import QGIS.

### Engine isolation and scaling

- Zero install dependencies. Engines import lazily inside runners, so a
  missing `survey-change` only affects the four change algorithms, with a
  precise install hint.
- Each runner is a pure function of `(params, feedback) -> dict` — trivially
  parallelizable (multiprocessing over scenes) and embeddable without QGIS.
- The QGIS algorithm classes are generated per-spec, so the provider scales
  to dozens of algorithms with no per-algorithm QGIS code.

## What is deliberately NOT here

- No engine logic duplicated: runners are thin orchestrators over the
  sibling packages' public APIs.
- No QGIS version branching: the adapter targets the stable
  `QgsProcessingAlgorithm` API (QGIS ≥ 3.16).
- No network calls at import or run time: `update-check` only runs when the
  user invokes it.

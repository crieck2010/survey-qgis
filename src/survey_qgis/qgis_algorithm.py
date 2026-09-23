"""QGIS Processing algorithm adapter (QGIS-only code lives here).

:func:`create_algorithm_class` builds a ``QgsProcessingAlgorithm`` subclass
from an :class:`~survey_qgis.algorithms.AlgorithmSpec`. The ``qgis`` imports
happen inside the factory, so importing this module without QGIS installed
is safe — the factory raises a clear error instead.

Parameter mapping
-----------------
- ``raster`` -> QgsProcessingParameterRasterLayer
- ``vector`` -> QgsProcessingParameterVectorLayer
- ``file``   -> QgsProcessingParameterFile
- ``folder`` -> QgsProcessingParameterFile (folder behavior)
- ``enum``   -> QgsProcessingParameterEnum
- ``number`` -> QgsProcessingParameterNumber (double)
- ``integer``-> QgsProcessingParameterNumber (integer)
- ``string`` -> QgsProcessingParameterString
- ``boolean``-> QgsProcessingParameterBoolean

Output mapping
--------------
- ``raster``/``vector``/``file`` outputs -> the matching
  ``QgsProcessingParameter*Destination`` (added as parameters, per QGIS
  convention); the runner receives the destination path.
- ``number``/``string``/``folder`` outputs -> ``QgsProcessingOutputNumber`` /
  ``QgsProcessingOutputString`` / ``QgsProcessingOutputFolder``.
"""

from __future__ import annotations

from typing import Any, Dict

from .algorithms import AlgorithmSpec
from .params import (
    OUTPUT_FILE,
    OUTPUT_FOLDER,
    OUTPUT_NUMBER,
    OUTPUT_RASTER,
    OUTPUT_STRING,
    OUTPUT_VECTOR,
    PARAM_BOOLEAN,
    PARAM_ENUM,
    PARAM_FILE,
    PARAM_FOLDER,
    PARAM_INTEGER,
    PARAM_NUMBER,
    PARAM_RASTER,
    PARAM_STRING,
    PARAM_VECTOR,
)


def _require_qgis():
    try:
        import qgis.core  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "QGIS Python API (qgis.core) is not available. The QGIS adapter "
            "only runs inside QGIS (or a QGIS Python environment). The pure "
            "layer — specs, validation, runners, CLI — works anywhere; see "
            "'survey-qgis run' for headless use."
        ) from exc
    import qgis.core
    return qgis.core


def create_algorithm_class(spec: AlgorithmSpec):
    """Build a QgsProcessingAlgorithm subclass for ``spec``."""
    core = _require_qgis()

    _PARAM_BUILDERS = {
        PARAM_RASTER: core.QgsProcessingParameterRasterLayer,
        PARAM_VECTOR: core.QgsProcessingParameterVectorLayer,
        PARAM_FILE: core.QgsProcessingParameterFile,
        PARAM_STRING: core.QgsProcessingParameterString,
        PARAM_BOOLEAN: core.QgsProcessingParameterBoolean,
    }

    class SuiteProcessingAlgorithm(core.QgsProcessingAlgorithm):
        _spec = spec

        def name(self) -> str:
            return self._spec.id

        def displayName(self) -> str:
            return self._spec.name

        def group(self) -> str:
            return self._spec.group

        def groupId(self) -> str:
            return self._spec.group.lower().replace(" ", "_")

        def shortHelpString(self) -> str:
            return self._spec.description

        def createInstance(self):
            return create_algorithm_class(self._spec)()

        def initAlgorithm(self, config=None):  # noqa: N803 (QGIS API naming)
            for p in self._spec.params:
                optional = p.optional or p.default is not None
                if p.type == PARAM_ENUM:
                    param = core.QgsProcessingParameterEnum(
                        p.name, p.label, options=list(p.options),
                        defaultValue=list(p.options).index(p.default)
                        if p.default in p.options else 0,
                        optional=optional)
                elif p.type == PARAM_NUMBER:
                    param = core.QgsProcessingParameterNumber(
                        p.name, p.label,
                        type=core.QgsProcessingParameterNumber.Double,
                        defaultValue=p.default, optional=optional)
                elif p.type == PARAM_INTEGER:
                    param = core.QgsProcessingParameterNumber(
                        p.name, p.label,
                        type=core.QgsProcessingParameterNumber.Integer,
                        defaultValue=p.default, optional=optional)
                elif p.type == PARAM_FOLDER:
                    param = core.QgsProcessingParameterFile(
                        p.name, p.label,
                        behavior=core.QgsProcessingParameterFile.Folder,
                        optional=optional)
                elif p.type in _PARAM_BUILDERS:
                    cls = _PARAM_BUILDERS[p.type]
                    if p.type == PARAM_FILE:
                        param = cls(p.name, p.label, optional=optional)
                    else:
                        param = cls(p.name, p.label, defaultValue=p.default,
                                    optional=optional)
                else:
                    raise RuntimeError(f"unmapped parameter type: {p.type!r}")
                if p.help:
                    param.setHelp(p.help)
                self.addParameter(param)
            # File-ish outputs are QGIS *destination parameters*.
            self._dest_outputs = []
            for o in self._spec.outputs:
                if o.type == OUTPUT_RASTER:
                    self.addParameter(core.QgsProcessingParameterRasterDestination(
                        o.name, o.label))
                    self._dest_outputs.append(o.name)
                elif o.type == OUTPUT_VECTOR:
                    self.addParameter(core.QgsProcessingParameterVectorDestination(
                        o.name, o.label))
                    self._dest_outputs.append(o.name)
                elif o.type in (OUTPUT_FILE, OUTPUT_FOLDER):
                    from .algorithms import _output_optional
                    self.addParameter(core.QgsProcessingParameterFileDestination(
                        o.name, o.label,
                        optional=_output_optional(self._spec, o.name)))
                    self._dest_outputs.append(o.name)
                elif o.type == OUTPUT_NUMBER:
                    self.addOutput(core.QgsProcessingOutputNumber(o.name, o.label))
                elif o.type == OUTPUT_STRING:
                    self.addOutput(core.QgsProcessingOutputString(o.name, o.label))

        def _qgis_value(self, parameters, context, p):
            """Convert one QGIS parameter value to a plain runner value."""
            if p.type == PARAM_RASTER:
                layer = self.parameterAsRasterLayer(parameters, p.name, context)
                return layer.source() if layer else self.parameterAsString(
                    parameters, p.name, context)
            if p.type == PARAM_VECTOR:
                layer = self.parameterAsVectorLayer(parameters, p.name, context)
                return layer.source() if layer else self.parameterAsString(
                    parameters, p.name, context)
            if p.type in (PARAM_FILE, PARAM_FOLDER, PARAM_STRING):
                return self.parameterAsString(parameters, p.name, context)
            if p.type == PARAM_ENUM:
                idx = self.parameterAsEnum(parameters, p.name, context)
                return p.options[idx] if 0 <= idx < len(p.options) else p.default
            if p.type in (PARAM_NUMBER, PARAM_INTEGER):
                return self.parameterAsDouble(parameters, p.name, context)
            if p.type == PARAM_BOOLEAN:
                return self.parameterAsBool(parameters, p.name, context)
            raise RuntimeError(f"unmapped parameter type: {p.type!r}")

        def processAlgorithm(self, parameters, context, feedback):  # noqa: N803
            from .runners import run_algorithm

            plain: Dict[str, Any] = {}
            for p in self._spec.params:
                plain[p.name] = self._qgis_value(parameters, context, p)
            # Destination parameters double as outputs: hand their resolved
            # paths to the runner under the output name.
            for o in self._spec.outputs:
                if o.name in getattr(self, "_dest_outputs", []):
                    plain[o.name] = self.parameterAsOutputLayer(
                        parameters, o.name, context)

            def _fb(message: str, percent=None):
                feedback.pushInfo(message)
                if percent is not None:
                    feedback.setProgress(percent)

            return run_algorithm(self._spec.id, plain, feedback=_fb)

    SuiteProcessingAlgorithm.__name__ = (
        "Suite" + "".join(w.capitalize() for w in spec.id.split("_")) + "Algorithm")
    SuiteProcessingAlgorithm.__qualname__ = SuiteProcessingAlgorithm.__name__
    return SuiteProcessingAlgorithm

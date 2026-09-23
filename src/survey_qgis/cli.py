"""Headless CLI over the same algorithm specs the QGIS provider exposes.

Every algorithm runs identically inside QGIS and from this CLI — the CLI
is the testable, scriptable surface of the distribution layer.

Usage:
    survey-qgis list [--group GROUP]
    survey-qgis describe <algorithm-id>
    survey-qgis run <algorithm-id> --param k=v [--param k=v ...]
    survey-qgis engines
    survey-qgis package [--out survey_qgis.zip]
    survey-qgis metadata [--out PATH]
    survey-qgis license [--key KEY]
    survey-qgis update-check
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile

from . import __version__
from .algorithms import (
    get_algorithm,
    list_algorithms,
    list_groups,
    ParamValidationError,
)
from .interop import EngineMissingError, check_engines
from .runners import run_algorithm


def _parse_param(text: str):
    if "=" not in text:
        raise SystemExit(f"bad --param {text!r}: expected k=v")
    key, value = text.split("=", 1)
    key = key.strip()
    value = value.strip()
    # Lightweight type sniffing; full coercion happens in validate_params.
    low = value.lower()
    if low in ("true", "false", "yes", "no"):
        return key, low in ("true", "yes")
    try:
        return key, int(value)
    except ValueError:
        pass
    try:
        return key, float(value)
    except ValueError:
        pass
    return key, value


def cmd_list(args) -> int:
    specs = list_algorithms(group=args.group)
    if not specs:
        print("No algorithms." + (f" in group {args.group!r}." if args.group else ""))
        return 0
    current = None
    for spec in specs:
        if spec.group != current:
            current = spec.group
            print(f"\n[{current}]")
        engines = ", ".join(spec.engines) if spec.engines else "none"
        print(f"  {spec.id:22s} {spec.name}  (engines: {engines})")
    print()
    return 0


def cmd_describe(args) -> int:
    spec = get_algorithm(args.algorithm_id)
    print(json.dumps(spec.to_dict(), indent=2))
    return 0


def cmd_run(args) -> int:
    params = dict(_parse_param(t) for t in args.param)

    def _feedback(message: str, percent=None):
        if args.verbose:
            pct = f" [{percent:.0f}%]" if percent is not None else ""
            print(f"  ... {message}{pct}", file=sys.stderr)

    try:
        result = run_algorithm(args.algorithm_id, params, feedback=_feedback)
    except ParamValidationError as exc:
        print(f"parameter error: {exc}", file=sys.stderr)
        return 2
    except EngineMissingError as exc:
        print(f"missing engine: {exc}", file=sys.stderr)
        return 3
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_engines(args) -> int:
    status = check_engines()
    width = max(len(k) for k in status)
    for pip_name, version in status.items():
        state = f"v{version}" if version else "NOT INSTALLED"
        print(f"  {pip_name:<{width}s}  {state}")
    return 0


def _package_root() -> str:
    # The installed (or source-tree) survey_qgis package directory — which
    # *is* the QGIS plugin folder (metadata.txt + classFactory live here).
    import survey_qgis
    return os.path.dirname(os.path.abspath(survey_qgis.__file__))


def cmd_package(args) -> int:
    root = _package_root()
    out = args.out or os.path.join(os.getcwd(), "survey_qgis.zip")
    staging = tempfile.mkdtemp(prefix="survey_qgis_pkg_")
    try:
        dest = os.path.join(staging, "survey_qgis")
        shutil.copytree(root, dest, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "*.pyo"))
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirnames, filenames in os.walk(dest):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, staging)
                    zf.write(full, rel)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"Wrote QGIS-installable plugin archive: {out}")
    print("Install in QGIS via Plugins > Manage and Install Plugins > "
          "Install from ZIP.")
    return 0


def cmd_metadata(args) -> int:
    from .plugin_metadata import write_metadata_txt
    out = args.out or os.path.join(_package_root(), "metadata.txt")
    write_metadata_txt(out)
    print(f"Wrote {out}")
    return 0


def cmd_license(args) -> int:
    from .licensing import check_license
    result = check_license(args.key)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


def cmd_update_check(args) -> int:
    from .licensing import check_for_updates
    result = check_for_updates()
    if result.get("available"):
        print(f"Update available: {result['current']} -> {result['latest']}")
        print(result.get("url") or "")
    elif result.get("error"):
        print(f"Update check failed: {result['error']}")
    else:
        print(f"Up to date (v{result['current']}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="survey-qgis",
        description="QGIS distribution layer for the survey suite "
                    f"(v{__version__}).")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="List available algorithms.")
    p.add_argument("--group", default=None, help="Filter by toolbox group.")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("describe", help="Show an algorithm's spec as JSON.")
    p.add_argument("algorithm_id")
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("run", help="Run an algorithm headlessly.")
    p.add_argument("algorithm_id")
    p.add_argument("--param", action="append", default=[],
                   help="Parameter as k=v (repeatable). Output destinations "
                        "are passed under the output name, e.g. "
                        "--param difference=/tmp/diff.tif")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("engines", help="Show installed suite engines.")
    p.set_defaults(func=cmd_engines)

    p = sub.add_parser("package",
                       help="Zip the plugin folder for QGIS 'Install from ZIP'.")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("metadata", help="Regenerate metadata.txt.")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_metadata)

    p = sub.add_parser("license", help="Check a license key.")
    p.add_argument("--key", default=None)
    p.set_defaults(func=cmd_license)

    p = sub.add_parser("update-check", help="Check for a newer release.")
    p.set_defaults(func=cmd_update_check)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Command line helpers for Praeparo metric definitions."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from ..env import ensure_env_loaded
from ..plugin_bootstrap import bootstrap_plugins
from ..schema import write_metric_schema
from .catalog import MetricDiscoveryError, load_metric_catalog
from .explain_command import run_explain_command


def _command_schema(args: argparse.Namespace) -> int:
    write_metric_schema(args.out)
    print(f"Wrote metric schema to {args.out}")
    return 0


def _command_validate(args: argparse.Namespace) -> int:
    try:
        catalog = load_metric_catalog(args.paths)
    except MetricDiscoveryError as exc:
        catalog = exc.catalog
        if catalog and catalog.files:
            for file_path in catalog.files:
                print(f"[OK] {file_path}")
        print("Validation failed:")
        for message in exc.errors:
            print(f"  - {message}")
        return 1

    if not catalog.files:
        print("No metric YAML files found.")
        return 0

    for file_path in catalog.files:
        print(f"[OK] {file_path}")
    print(f"Validated {len(catalog.files)} metric file(s).")
    return 0


def _command_explain(args: argparse.Namespace) -> int:
    try:
        return run_explain_command(args)
    except Exception as exc:  # noqa: BLE001
        print(f"Explain failed: {type(exc).__name__}: {exc}")
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="praeparo-metrics", description="Praeparo metric utilities")
    plugin_parent = argparse.ArgumentParser(add_help=False)
    plugin_parent.add_argument(
        "--plugin",
        dest="plugins",
        action="append",
        default=[],
        metavar="MODULE",
        help="Additional module(s) to import before executing commands (e.g. to register custom visuals).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("schema", help="Export metric JSON schema", parents=[plugin_parent])
    schema_parser.add_argument("--out", type=Path, required=True, help="Destination for the schema JSON file")
    schema_parser.set_defaults(func=_command_schema)

    validate_parser = subparsers.add_parser("validate", help="Validate metric YAML files", parents=[plugin_parent])
    validate_parser.add_argument("paths", nargs="+", type=Path, help="Files or directories to validate")
    validate_parser.set_defaults(func=_command_validate)

    explain_parser = subparsers.add_parser("explain", help="Export row-level evidence for a metric", parents=[plugin_parent])
    explain_parser.add_argument(
        "selector",
        help=(
            "Metric key/variant to explain, or a file-rooted selector: "
            "<visual_path>#<binding...>, <pack_path>#<slide>#<binding...>, "
            "<pack_path>#<slide>#<placeholder>#<binding...>."
        ),
    )
    explain_parser.add_argument(
        "dest",
        nargs="?",
        type=Path,
        help=(
            "Optional destination shorthand. A .csv path writes evidence to that location and "
            "defaults artifacts to <parent>/<stem>/_artifacts; a directory or extension-less path "
            "writes evidence to <dest>/evidence.csv with artifacts under <dest>/_artifacts."
        ),
    )
    explain_parser.add_argument(
        "--metrics-root",
        dest="metrics_root",
        type=Path,
        default=None,
        help="Root directory containing metric YAML files (defaults to the nearest registry/metrics).",
    )
    explain_parser.add_argument(
        "--context",
        dest="context",
        type=Path,
        action="append",
        default=[],
        help="Context layer YAML/JSON file (repeatable). Pack-shaped YAML is also accepted.",
    )
    explain_parser.add_argument(
        "--list-slides",
        dest="list_slides",
        action="store_true",
        help="For pack selectors, list available slides and exit.",
    )
    explain_parser.add_argument(
        "--list-bindings",
        dest="list_bindings",
        action="store_true",
        help="For visual/pack selectors, list available metric bindings and exit.",
    )
    explain_parser.add_argument(
        "--calculate",
        dest="calculate",
        action="append",
        default=[],
        help="Extra DAX calculate predicate (repeatable; appended after context layers).",
    )
    explain_parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=50_000,
        help="Maximum number of evidence rows to export.",
    )
    explain_parser.add_argument(
        "--variant-mode",
        dest="variant_mode",
        choices=["flag", "filter"],
        default="flag",
        help="Variant handling: flag emits __passes_variant where possible; filter applies variant filters to the rowset.",
    )
    explain_parser.add_argument(
        "--data-mode",
        dest="data_mode",
        choices=["mock", "live"],
        default="live",
        help="Datasource mode for evidence execution.",
    )
    explain_parser.add_argument(
        "--plan-only",
        dest="plan_only",
        action="store_true",
        help="Only write explain.dax (+ summary.json) without executing the query.",
    )
    explain_parser.add_argument(
        "--datasource",
        dest="datasource",
        default=None,
        help="Datasource name or YAML path (searched under datasources/ or registry/datasources/).",
    )
    explain_parser.add_argument(
        "--dataset-id",
        dest="dataset_id",
        default=None,
        help="Explicit Power BI dataset id (overrides datasource dataset_id).",
    )
    explain_parser.add_argument(
        "--workspace-id",
        dest="workspace_id",
        default=None,
        help="Explicit Power BI workspace id (overrides datasource workspace_id).",
    )
    explain_parser.add_argument(
        "--artefact-dir",
        dest="artefact_dir",
        type=Path,
        default=None,
        help="Optional directory for explain artifacts (overrides any defaults derived from dest).",
    )
    explain_parser.set_defaults(func=_command_explain)

    return parser


def run(argv: Sequence[str] | None = None) -> int:
    ensure_env_loaded()
    args_list = list(argv) if argv is not None else sys.argv[1:]
    try:
        bootstrap_plugins(args_list)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    parser = _build_parser()
    args = parser.parse_args(args_list)
    return args.func(args)


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


__all__ = ["run", "main"]

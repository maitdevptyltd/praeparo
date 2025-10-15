"""Command line helpers for Praeparo metric definitions."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from ..schema import write_metric_schema
from .catalog import MetricDiscoveryError, load_metric_catalog


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="praeparo-metrics", description="Praeparo metric utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("schema", help="Export metric JSON schema")
    schema_parser.add_argument("--out", type=Path, required=True, help="Destination for the schema JSON file")
    schema_parser.set_defaults(func=_command_schema)

    validate_parser = subparsers.add_parser("validate", help="Validate metric YAML files")
    validate_parser.add_argument("paths", nargs="+", type=Path, help="Files or directories to validate")
    validate_parser.set_defaults(func=_command_validate)

    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


__all__ = ["run", "main"]

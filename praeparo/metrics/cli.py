"""Command line helpers for Praeparo metric definitions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import yaml

from ..inheritance import validate_extends_graph
from .models import MetricDefinition
from ..schema import write_metric_schema


def _gather_yaml_files(target: Path) -> list[Path]:
    if target.is_file():
        if target.suffix.lower() in {".yml", ".yaml"}:
            return [target]
        raise ValueError(f"Unsupported file extension for {target}")

    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")

    files: list[Path] = []
    for pattern in ("*.yaml", "*.yml"):
        files.extend(target.rglob(pattern))
    return sorted(set(files))


def _command_schema(args: argparse.Namespace) -> int:
    write_metric_schema(args.out)
    print(f"Wrote metric schema to {args.out}")
    return 0


def _command_validate(args: argparse.Namespace) -> int:
    files: list[Path] = []
    for path in args.paths:
        files.extend(_gather_yaml_files(path))

    if not files:
        print("No metric YAML files found.")
        return 0

    errors: list[str] = []
    registry: dict[str, MetricDefinition] = {}
    source_map: dict[str, Path] = {}
    for file_path in files:
        try:
            data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
            metric = MetricDefinition.model_validate(data)
            if metric.key in registry:
                errors.append(
                    f"{file_path}: duplicate metric key '{metric.key}' also defined in {source_map[metric.key]}"
                )
                continue
            registry[metric.key] = metric
            source_map[metric.key] = file_path
            print(f"[OK] {file_path}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{file_path}: {exc}")

    # Validate extends relationships
    errors.extend(
        validate_extends_graph(
            registry,
            source_map,
            get_parent=lambda metric: metric.extends,
        )
    )

    if errors:
        print("Validation failed:")
        for message in errors:
            print(f"  - {message}")
        return 1

    print(f"Validated {len(files)} metric file(s).")
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

"""Utilities for exporting JSON schemas from Praeparo models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .metrics import MetricDefinition
from .models import MatrixConfig


def matrix_json_schema() -> dict[str, Any]:
    """Return the JSON schema for matrix configurations."""

    schema = MatrixConfig.model_json_schema()
    properties = schema.setdefault("properties", {})
    properties.setdefault(
        "parameters",
        {
            "type": "object",
            "title": "Parameters",
            "description": "Template values injected into the configuration before validation.",
            "additionalProperties": {"type": "string"},
            "default": {},
        },
    )
    properties.setdefault(
        "compose",
        {
            "title": "Compose",
            "description": "List of additional YAML files to merge before validation.",
            "anyOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
        },
    )
    return schema


def metric_json_schema() -> dict[str, Any]:
    """Return the JSON schema for metric definitions."""

    return MetricDefinition.model_json_schema()


def _write_schema(path: Path, schema: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2), encoding="utf-8")


def write_matrix_schema(path: Path) -> None:
    """Write the matrix configuration schema to *path*."""

    _write_schema(path, matrix_json_schema())


def write_metric_schema(path: Path) -> None:
    """Write the metric definition schema to *path*."""

    _write_schema(path, metric_json_schema())


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Praeparo JSON schemas.")
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("schemas/matrix.json"),
        help="Destination for the matrix schema JSON file.",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=None,
        help="Destination for the metric schema JSON file (omit to skip).",
    )
    args = parser.parse_args(argv)

    write_matrix_schema(args.matrix)
    print(f"Wrote matrix schema to {args.matrix}")

    if args.metrics is not None:
        write_metric_schema(args.metrics)
        print(f"Wrote metric schema to {args.metrics}")

    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = [
    "matrix_json_schema",
    "metric_json_schema",
    "write_matrix_schema",
    "write_metric_schema",
    "run",
    "main",
]


if __name__ == "__main__":
    main()


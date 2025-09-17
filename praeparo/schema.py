"""Utilities for exporting JSON schemas from Praeparo models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .models import MatrixConfig


def matrix_json_schema() -> dict[str, Any]:
    """Return the JSON schema for matrix configurations."""

    return MatrixConfig.model_json_schema()


def write_matrix_schema(path: Path) -> None:
    """Write the matrix configuration schema to *path*."""

    schema = matrix_json_schema()
    path.write_text(json.dumps(schema, indent=2), encoding="utf-8")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Praeparo JSON schemas.")
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("schemas/matrix.json"),
        help="Destination for the matrix schema JSON file.",
    )
    args = parser.parse_args(argv)

    args.matrix.parent.mkdir(parents=True, exist_ok=True)
    write_matrix_schema(args.matrix)
    print(f"Wrote matrix schema to {args.matrix}")
    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = ["matrix_json_schema", "write_matrix_schema", "run", "main"]


if __name__ == "__main__":
    main()

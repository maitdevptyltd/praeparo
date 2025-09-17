"""Command line interface for Praeparo proof-of-concept pipelines."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .dax import build_matrix_query
from .data import mock_matrix_data
from .io.yaml_loader import ConfigLoadError, load_matrix_config
from .rendering import matrix_html, matrix_png
from .templating import extract_field_references


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a Praeparo matrix from a YAML configuration.")
    parser.add_argument("config", type=Path, help="Path to the matrix YAML file.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("matrix.html"),
        help="Destination for the generated HTML output (defaults to ./matrix.html).",
    )
    parser.add_argument(
        "--png-out",
        type=Path,
        default=None,
        help="Optional destination for a static PNG snapshot of the matrix.",
    )
    parser.add_argument(
        "--print-dax",
        action="store_true",
        help="Print the generated DAX statement to stdout.",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_matrix_config(args.config)
    except ConfigLoadError as exc:
        parser.error(str(exc))
        return 2

    row_fields = extract_field_references([row.template for row in config.rows])
    query = build_matrix_query(config, row_fields)
    dataset = mock_matrix_data(config, row_fields)

    outputs: list[Path] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    matrix_html(config, dataset, str(args.out))
    outputs.append(args.out)

    if args.png_out is not None:
        try:
            args.png_out.parent.mkdir(parents=True, exist_ok=True)
            matrix_png(config, dataset, str(args.png_out))
            outputs.append(args.png_out)
        except RuntimeError as exc:
            parser.error(str(exc))
            return 2

    if args.print_dax:
        print(query.statement)

    if outputs:
        rendered = ", ".join(str(path) for path in outputs)
        print(f"Wrote matrix visualization to {rendered}")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

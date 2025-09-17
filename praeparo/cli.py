"""Command line interface for Praeparo proof-of-concept pipelines."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Sequence

from .dax import build_matrix_query
from .data import MatrixResultSet, mock_matrix_data, powerbi_matrix_data
from .io.yaml_loader import ConfigLoadError, load_matrix_config
from .powerbi import (
    PowerBIAuthenticationError,
    PowerBIConfigurationError,
    PowerBIQueryError,
)
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
        "--dataset-id",
        type=str,
        default=None,
        help="Execute the DAX query against the specified Power BI dataset instead of mock data.",
    )
    parser.add_argument(
        "--workspace-id",
        type=str,
        default=None,
        help="Optional workspace (group) id when querying a dataset via the Power BI API.",
    )
    parser.add_argument(
        "--print-dax",
        action="store_true",
        help="Print the generated DAX statement to stdout.",
    )
    return parser


def _matrix_png(config, dataset: MatrixResultSet, path: Path, parser: argparse.ArgumentParser) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        matrix_png(config, dataset, str(path))
        return True
    except RuntimeError as exc:
        parser.error(str(exc))
        return False


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

    dataset: MatrixResultSet
    if args.dataset_id:
        try:
            dataset = asyncio.run(
                powerbi_matrix_data(
                    config,
                    row_fields,
                    query,
                    dataset_id=args.dataset_id,
                    group_id=args.workspace_id,
                )
            )
        except (PowerBIConfigurationError, PowerBIAuthenticationError, PowerBIQueryError) as exc:
            parser.error(str(exc))
            return 2
    else:
        dataset = mock_matrix_data(config, row_fields)

    outputs: list[Path] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    matrix_html(config, dataset, str(args.out))
    outputs.append(args.out)

    if args.png_out is not None:
        if not _matrix_png(config, dataset, args.png_out, parser):
            return 2
        outputs.append(args.png_out)

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

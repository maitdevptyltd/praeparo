"""Command line interface for Praeparo proof-of-concept pipelines."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Sequence

from .data import MatrixResultSet, mock_matrix_data, powerbi_matrix_data
from .datasources import DataSourceConfigError, ResolvedDataSource, resolve_datasource
from .dax import build_matrix_query
from .io.yaml_loader import ConfigLoadError, load_visual_config
from .models import FrameConfig, MatrixConfig
from .powerbi import (
    PowerBIAuthenticationError,
    PowerBIConfigurationError,
    PowerBIQueryError,
)
from .rendering import frame_html, frame_png, matrix_html, matrix_png
from .templating import extract_field_references


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a Praeparo visual from a YAML configuration."
    )
    parser.add_argument("config", type=Path, help="Path to the visual YAML file.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Destination for the generated HTML output (defaults to <project>/build/<name>.html).",
    )
    parser.add_argument(
        "--png-out",
        type=Path,
        default=None,
        help="Optional destination for a static PNG snapshot of the visual.",
    )
    parser.add_argument(
        "--data-source",
        type=str,
        default=None,
        help="Name or path of the data source definition to use (overrides visual configuration).",
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
        help="Print the generated DAX statement(s) to stdout.",
    )
    return parser


def _project_root_for(path: Path) -> Path | None:
    current = path.parent
    while True:
        if current.name == "visuals":
            return current.parent
        if (current / "visuals").is_dir():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _default_output_path(
    config_path: Path, project_root: Path | None, extension: str
) -> Path:
    base = project_root or config_path.parent
    build_dir = base / "build"
    return build_dir / f"{config_path.stem}.{extension}"


def _ensure_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _resolve_datasource(
    config: MatrixConfig,
    args: argparse.Namespace,
    *,
    visual_path: Path,
) -> ResolvedDataSource:
    reference = args.datasource if args.datasource is not None else config.datasource
    return resolve_datasource(reference, visual_path=visual_path)


def _load_dataset(
    config: MatrixConfig,
    row_fields,
    query,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    visual_path: Path,
) -> MatrixResultSet | None:
    if args.dataset_id:
        try:
            return asyncio.run(
                powerbi_matrix_data(
                    config,
                    row_fields,
                    query,
                    dataset_id=args.dataset_id,
                    group_id=args.workspace_id,
                )
            )
        except (
            PowerBIConfigurationError,
            PowerBIAuthenticationError,
            PowerBIQueryError,
        ) as exc:
            parser.error(str(exc))
            return None

    try:
        datasource = _resolve_datasource(config, args, visual_path=visual_path)
    except DataSourceConfigError as exc:
        parser.error(str(exc))
        return None

    if datasource.type == "mock":
        return mock_matrix_data(config, row_fields)

    dataset_id = datasource.dataset_id
    if not dataset_id:
        parser.error(
            f"Data source '{datasource.name}' does not define a dataset_id and no --dataset-id override was provided."
        )
        return None

    workspace_id = args.workspace_id or datasource.workspace_id
    settings = datasource.settings

    try:
        return asyncio.run(
            powerbi_matrix_data(
                config,
                row_fields,
                query,
                dataset_id=dataset_id,
                group_id=workspace_id,
                settings=settings,
            )
        )
    except (
        PowerBIConfigurationError,
        PowerBIAuthenticationError,
        PowerBIQueryError,
    ) as exc:
        parser.error(str(exc))
        return None


def _matrix_png(
    config: MatrixConfig,
    dataset: MatrixResultSet,
    path: Path,
    parser: argparse.ArgumentParser,
) -> bool:
    try:
        _ensure_directory(path)
        matrix_png(config, dataset, str(path))
        return True
    except RuntimeError as exc:
        parser.error(str(exc))
        return False


def _frame_png(
    frame: FrameConfig,
    datasets: list[tuple[MatrixConfig, MatrixResultSet]],
    path: Path,
    parser: argparse.ArgumentParser,
) -> bool:
    try:
        _ensure_directory(path)
        frame_png(frame, datasets, str(path))
        return True
    except RuntimeError as exc:
        parser.error(str(exc))
        return False


def _render_matrix(
    config: MatrixConfig,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    config_path: Path,
    project_root: Path | None,
) -> int:
    row_fields = extract_field_references([row.template for row in config.rows])
    query = build_matrix_query(config, row_fields)

    dataset = _load_dataset(
        config, row_fields, query, args, parser, visual_path=config_path
    )
    if dataset is None:
        return 2

    outputs: list[Path] = []

    out_path = args.out or _default_output_path(config_path, project_root, "html")
    _ensure_directory(out_path)
    matrix_html(config, dataset, str(out_path))
    outputs.append(out_path)

    png_path = args.png_out
    if png_path is not None:
        if not _matrix_png(config, dataset, png_path, parser):
            return 2
        outputs.append(png_path)

    if args.print_dax:
        print(query.statement)

    if outputs:
        rendered = ", ".join(str(path) for path in outputs)
        print(f"Wrote matrix visualization to {rendered}")
    return 0


def _render_frame(
    frame: FrameConfig,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    config_path: Path,
    project_root: Path | None,
) -> int:
    child_outputs: list[tuple[MatrixConfig, MatrixResultSet]] = []
    printed_dax: list[str] = []

    for child in frame.children:
        config = child.config
        row_fields = extract_field_references([row.template for row in config.rows])
        query = build_matrix_query(config, row_fields)

        dataset = _load_dataset(
            config, row_fields, query, args, parser, visual_path=child.source
        )
        if dataset is None:
            return 2

        child_outputs.append((config, dataset))
        printed_dax.append(f"-- {config.title or child.source.name}\n{query.statement}")

    out_path = args.out or _default_output_path(config_path, project_root, "html")
    _ensure_directory(out_path)
    frame_html(frame, child_outputs, str(out_path))

    outputs = [out_path]
    png_path = args.png_out
    if png_path is not None:
        if not _frame_png(frame, child_outputs, png_path, parser):
            return 2
        outputs.append(png_path)

    if args.print_dax:
        print("\n\n".join(printed_dax))

    rendered = ", ".join(str(path) for path in outputs)
    print(f"Wrote frame visualization to {rendered}")
    return 0


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        visual = load_visual_config(args.config)
    except ConfigLoadError as exc:
        parser.error(str(exc))
        return 2

    project_root = _project_root_for(args.config)

    if isinstance(visual, MatrixConfig):
        return _render_matrix(
            visual, args, parser, config_path=args.config, project_root=project_root
        )

    if isinstance(visual, FrameConfig):
        return _render_frame(
            visual, args, parser, config_path=args.config, project_root=project_root
        )

    parser.error(f"Unsupported visual type in {args.config}")
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

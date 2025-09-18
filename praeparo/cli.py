"""Command line interface for Praeparo proof-of-concept pipelines."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .datasources import DataSourceConfigError
from .io.yaml_loader import ConfigLoadError, load_visual_config
from .models import BaseVisualConfig, FrameConfig, MatrixConfig
from .pipeline import (
    ExecutionContext,
    OutputTarget,
    PipelineDataOptions,
    PipelineOptions,
    VisualExecutionResult,
    VisualPipeline,
    build_default_query_planner_provider,
)
from .powerbi import (
    PowerBIAuthenticationError,
    PowerBIConfigurationError,
    PowerBIQueryError,
)


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
        dest="data_source",
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


def _collect_output_targets(args: argparse.Namespace, project_root: Path | None) -> list[OutputTarget]:
    html_path = args.out or _default_output_path(args.config, project_root, "html")
    targets = [OutputTarget.html(html_path)]
    if args.png_out is not None:
        targets.append(OutputTarget.png(args.png_out))
    return targets


def _print_dax(result: VisualExecutionResult) -> None:
    visual = result.config
    if isinstance(visual, MatrixConfig):
        for plan in result.plans:
            print(plan.statement)
        return

    if isinstance(visual, FrameConfig):
        segments: list[str] = []
        for index, child in enumerate(result.children, start=1):
            if not child.plans:
                continue
            title = getattr(child.config, "title", None) or f"Child {index}"
            segments.append(f"-- {title}\n{child.plans[0].statement}")
        if segments:
            print("\n\n".join(segments))
        return

    if result.plans:
        print(result.plans[0].statement)


def _summarize_outputs(result: VisualExecutionResult) -> str | None:
    if not result.outputs:
        return None
    rendered = ", ".join(str(artifact.path) for artifact in result.outputs)
    return f"Wrote {result.config.type} visualization to {rendered}"


def _build_context(
    args: argparse.Namespace,
    project_root: Path | None,
    targets: list[OutputTarget],
) -> ExecutionContext:
    options = PipelineOptions(
        data=PipelineDataOptions(
            datasource_override=args.data_source,
            dataset_id=args.dataset_id,
            workspace_id=args.workspace_id,
        ),
        outputs=targets,
        print_dax=args.print_dax,
    )
    return ExecutionContext(
        config_path=args.config,
        project_root=project_root,
        case_key=args.config.stem,
        options=options,
    )


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        visual = load_visual_config(args.config)
    except ConfigLoadError as exc:
        parser.error(str(exc))
        return 2

    project_root = _project_root_for(args.config)
    targets = _collect_output_targets(args, project_root)
    context = _build_context(args, project_root, targets)

    planner_provider = build_default_query_planner_provider()
    pipeline = VisualPipeline(planner_provider=planner_provider)

    try:
        result = pipeline.execute(visual, context)
    except (
        DataSourceConfigError,
        PowerBIConfigurationError,
        PowerBIAuthenticationError,
        PowerBIQueryError,
        RuntimeError,
    ) as exc:
        parser.error(str(exc))
        return 2

    if args.print_dax:
        _print_dax(result)

    message = _summarize_outputs(result)
    if message:
        print(message)

    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

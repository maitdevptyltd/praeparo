"""Praeparo command line interface."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence

from praeparo.datasources import DataSourceConfigError
from praeparo.env import ensure_env_loaded
from praeparo.io.yaml_loader import ConfigLoadError, load_visual_config
from praeparo.models import BaseVisualConfig, FrameConfig, MatrixConfig
from praeparo.pipeline import (
    ExecutionContext,
    OutputTarget,
    PipelineDataOptions,
    PipelineOptions,
    VisualExecutionResult,
    VisualPipeline,
    build_default_query_planner_provider,
)
from praeparo.pack import (
    PackConfigError,
    create_pack_jinja_env,
    load_pack_config,
    run_pack,
)
from praeparo.visuals.dax_compilers import (
    DaxCompilerRegistration,
    get_dax_compiler_registration,
    iter_dax_compiler_registrations,
)
from praeparo.powerbi import (
    PowerBIAuthenticationError,
    PowerBIConfigurationError,
    PowerBIQueryError,
)
from praeparo.visuals.context import ContextLoadError, load_context_file, merge_context_payload
from praeparo.visuals.registry import (
    VisualCLIArgument,
    VisualCLIOptions,
    VisualTypeRegistration,
    iter_visual_registrations,
)

LOG_LEVEL_ENV_VAR = "PRAEPARO_LOG_LEVEL"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging(log_level: str | None) -> None:
    env_level = os.getenv(LOG_LEVEL_ENV_VAR)
    candidate = (log_level or env_level or "DEBUG").upper()
    resolved = logging.getLevelName(candidate)
    level = resolved if isinstance(resolved, int) else logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger().setLevel(level)


# ---------------------------------------------------------------------------
# Argument helpers
# ---------------------------------------------------------------------------


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


def _default_output_path(config_path: Path, project_root: Path | None, extension: str) -> Path:
    base = project_root or config_path.parent
    build_dir = base / "build"
    return build_dir / f"{config_path.stem}.{extension}"


def _build_common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("config", type=Path, help="Path to the visual YAML file.")
    parser.add_argument(
        "--plugin",
        dest="plugins",
        action="append",
        default=[],
        metavar="MODULE",
        help="Additional module(s) to import before executing commands (e.g. to register custom visuals).",
    )
    parser.add_argument(
        "--artefact-dir",
        type=Path,
        dest="artefact_dir",
        help="Directory where schema/data artefacts will be written.",
    )
    parser.add_argument(
        "--metrics-root",
        type=Path,
        dest="metrics_root",
        help="Optional metrics directory to resolve relative paths.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        dest="seed",
        help="Seed used by mock data providers.",
    )
    parser.add_argument(
        "--scenario",
        dest="scenario",
        help="Mock scenario key defined in the visual configuration.",
    )
    parser.add_argument(
        "--data-mode",
        dest="data_mode",
        default="mock",
        help="Datasource mode (e.g. mock, live).",
    )
    parser.add_argument(
        "--datasource",
        "--data-source",
        dest="datasource",
        help="Datasource override key.",
    )
    parser.add_argument(
        "--dataset-id",
        dest="dataset_id",
        help="Power BI dataset identifier for live execution.",
    )
    parser.add_argument(
        "--workspace-id",
        dest="workspace_id",
        help="Optional Power BI workspace identifier.",
    )
    parser.add_argument(
        "--print-dax",
        dest="print_dax",
        action="store_true",
        help="Print the generated DAX statements to stdout.",
    )
    parser.add_argument(
        "--ignore-placeholders",
        dest="ignore_placeholders",
        action="store_true",
        help="Skip metrics marked as placeholders during execution.",
    )
    parser.add_argument(
        "--validate-define",
        dest="validate_define",
        action="store_true",
        help="Validate that DEFINE blocks emitted by planners match the visual definition.",
    )
    parser.add_argument(
        "--sort-rows",
        dest="sort_rows",
        action="store_true",
        help="Sort matrix rows alphabetically to stabilise outputs.",
    )
    parser.add_argument(
        "--meta",
        dest="meta",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional metadata key/value pairs forwarded to the pipeline.",
    )
    parser.add_argument(
        "--calculate",
        dest="calculate",
        action="append",
        default=[],
        metavar="EXPR",
        help="Top-level CALCULATE filter expression to apply.",
    )
    parser.add_argument(
        "--define",
        dest="define",
        action="append",
        default=[],
        metavar="EXPR",
        help="Top-level DEFINE statement to prepend to the generated query.",
    )
    parser.add_argument(
        "--context",
        dest="context_path",
        type=Path,
        help="Optional YAML/JSON file containing top-level context overrides.",
    )
    parser.add_argument(
        "--width",
        dest="width",
        type=int,
        help="Optional viewport width override supplied to renderers.",
    )
    parser.add_argument(
        "--height",
        dest="height",
        type=int,
        help="Optional viewport height override supplied to renderers.",
    )
    parser.add_argument(
        "--grain",
        dest="grain",
        action="append",
        default=[],
        metavar="COLUMN",
        help="Optional SUMMARIZECOLUMNS grain override (repeatable).",
    )
    parser.add_argument(
        "--measure-table",
        "--table",
        dest="measure_table",
        default="'adhoc'",
        help="Measure table used when emitting DEFINE statements (defaults to 'adhoc').",
    )
    return parser


def _build_run_specific_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--output-html",
        "--out",
        dest="output_html",
        type=Path,
        help="Destination for rendered HTML output.",
    )
    parser.add_argument(
        "--output-png",
        "--png-out",
        dest="output_png",
        type=Path,
        help="Destination for rendered PNG output.",
    )
    parser.add_argument(
        "--build-artifacts-dir",
        dest="build_artifacts_dir",
        type=Path,
        help="Directory for build artifacts emitted by visuals (e.g. exported PPTX/PNG). Defaults to .tmp/pbi_exports for Power BI visuals.",
    )
    parser.add_argument(
        "--png-scale",
        dest="png_scale",
        type=float,
        default=None,
        help="Scale factor applied to PNG outputs (defaults to pipeline configuration).",
    )
    return parser


def _register_pack_parsers(parent: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    pack_parser = parent.add_parser("pack", help="Pack pipeline commands.")
    pack_subparsers = pack_parser.add_subparsers(dest="pack_command", metavar="SUBCOMMAND")
    pack_subparsers.required = True

    run_parser = pack_subparsers.add_parser("run", help="Execute a pack and export PNGs.")
    run_parser.add_argument("pack", type=Path, help="Path to the pack YAML file.")
    run_parser.add_argument(
        "--artefact-dir",
        type=Path,
        dest="artefact_dir",
        required=True,
        help="Root directory for exported pack artefacts.",
    )
    run_parser.add_argument(
        "--meta",
        dest="meta",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional metadata key/value pairs forwarded to pipelines.",
    )
    run_parser.add_argument(
        "--data-mode",
        dest="data_mode",
        default="mock",
        help="Datasource mode (e.g. mock, live).",
    )
    run_parser.add_argument(
        "--datasource",
        "--data-source",
        dest="datasource",
        help="Datasource override key.",
    )
    run_parser.add_argument(
        "--dataset-id",
        dest="dataset_id",
        help="Power BI dataset identifier for live execution.",
    )
    run_parser.add_argument(
        "--workspace-id",
        dest="workspace_id",
        help="Optional Power BI workspace identifier.",
    )
    run_parser.add_argument(
        "--seed",
        dest="seed",
        type=int,
        help="Seed used by mock data providers.",
    )
    run_parser.add_argument(
        "--scenario",
        dest="scenario",
        help="Mock scenario key defined in the visual configuration.",
    )
    run_parser.add_argument(
        "--metrics-root",
        dest="metrics_root",
        type=Path,
        help="Optional metrics directory to resolve relative paths.",
    )
    run_parser.add_argument(
        "--measure-table",
        dest="measure_table",
        default="'adhoc'",
        help="Measure table used when emitting DEFINE statements (defaults to 'adhoc').",
    )
    run_parser.add_argument(
        "--ignore-placeholders",
        dest="ignore_placeholders",
        action="store_true",
        help="Skip metrics marked as placeholders during execution.",
    )
    run_parser.add_argument(
        "--build-artifacts-dir",
        dest="build_artifacts_dir",
        type=Path,
        help="Directory for build artifacts emitted by visuals (e.g. exported PPTX/PNG).",
    )
    run_parser.add_argument(
        "--png-scale",
        dest="png_scale",
        type=float,
        default=None,
        help="Scale factor applied to PNG outputs (defaults to pipeline configuration).",
    )
    run_parser.add_argument(
        "--width",
        dest="width",
        type=int,
        help="Optional viewport width override supplied to renderers.",
    )
    run_parser.add_argument(
        "--height",
        dest="height",
        type=int,
        help="Optional viewport height override supplied to renderers.",
    )
    run_parser.add_argument(
        "--grain",
        dest="grain",
        action="append",
        default=[],
        metavar="COLUMN",
        help="Optional SUMMARIZECOLUMNS grain override (repeatable).",
    )
    run_parser.add_argument(
        "--slides",
        dest="slides",
        action="append",
        default=[],
        metavar="ID_OR_TITLE",
        help="Limit execution to matching slide ids/titles/slugs (repeatable).",
    )
    run_parser.set_defaults(_handler=_handle_pack_run, print_dax=False, validate_define=False, sort_rows=False)


def _register_visual_type_parsers(
    parent: argparse.ArgumentParser,
    *,
    include_outputs: bool,
    registrations: Iterable[tuple[str, VisualTypeRegistration]],
) -> argparse._SubParsersAction[argparse.ArgumentParser]:
    common = _build_common_parser()
    extras = _build_run_specific_parser() if include_outputs else None

    type_subparsers = parent.add_subparsers(dest="_visual_type", metavar="TYPE")
    type_subparsers.required = True

    def _add_subparser(name: str, cli: VisualCLIOptions | None, help_text: str) -> None:
        parents = [common]
        if include_outputs:
            parents.append(extras)  # type: ignore[arg-type]
        subparser = type_subparsers.add_parser(name, parents=parents, add_help=True, help=help_text)
        subparser.set_defaults(_cli_options=cli)
        if cli:
            _attach_visual_arguments(subparser, cli)

    _add_subparser("auto", None, "Infer the visual type from the configuration file.")

    for type_name, registration in registrations:
        help_text = f"Execute the registered '{type_name}' visual"
        _add_subparser(type_name, registration.cli, help_text)

    return type_subparsers


def _attach_visual_arguments(parser: argparse.ArgumentParser, cli: VisualCLIOptions) -> None:
    for argument in cli.arguments:
        names = [argument.flag]
        dest = argument.dest or argument.flag.lstrip("-").replace("-", "_")
        kwargs: Dict[str, Any] = {"dest": dest, "help": argument.help}
        if argument.multiple and argument.action is None:
            kwargs["action"] = "append"
            kwargs["default"] = []
        elif argument.action is not None:
            kwargs["action"] = argument.action
        else:
            kwargs["default"] = argument.default
            if argument.type is not None:
                kwargs["type"] = argument.type
        if argument.metavar:
            kwargs["metavar"] = argument.metavar
        if argument.required:
            kwargs["required"] = True
        if argument.choices:
            kwargs["choices"] = argument.choices
        parser.add_argument(*names, **kwargs)


def _register_dax_type_parsers(
    parent: argparse.ArgumentParser,
    *,
    registrations: Iterable[tuple[str, DaxCompilerRegistration]],
) -> argparse._SubParsersAction[argparse.ArgumentParser]:
    common = _build_common_parser()
    extras = argparse.ArgumentParser(add_help=False)
    extras.add_argument(
        "--quiet",
        dest="quiet",
        action="store_true",
        help="Suppress per-plan status output.",
    )

    type_subparsers = parent.add_subparsers(dest="_dax_type", metavar="TYPE")
    type_subparsers.required = True

    def _add_subparser(name: str, registration: DaxCompilerRegistration | None) -> None:
        parents = [common, extras]
        help_text = (
            registration.description
            if registration and registration.description
            else f"Compile DAX for the '{name}' visual" if registration else "Infer the visual type from the configuration file."
        )
        subparser = type_subparsers.add_parser(
            name,
            parents=parents,
            add_help=True,
            help=help_text,
        )
        cli = registration.cli if registration else None
        subparser.set_defaults(_cli_options=cli)
        if cli:
            _attach_visual_arguments(subparser, cli)

    _add_subparser("auto", None)
    for type_name, registration in registrations:
        _add_subparser(type_name, registration)

    return type_subparsers


def _build_parser(
    visual_registrations: Iterable[tuple[str, VisualTypeRegistration]],
    dax_registrations: Iterable[tuple[str, DaxCompilerRegistration]],
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="praeparo", description="Praeparo visual execution tooling.")
    parser.add_argument(
        "--log-level",
        dest="log_level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"],
        help=f"Override log level (default DEBUG; also honours {LOG_LEVEL_ENV_VAR}).",
    )
    parser.add_argument(
        "--plugin",
        dest="plugins",
        action="append",
        default=[],
        metavar="MODULE",
        help="Additional module(s) to import before executing commands (e.g. to register custom visuals).",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    visual_parser = subparsers.add_parser("visual", help="Visual pipeline commands.")
    visual_subparsers = visual_parser.add_subparsers(dest="visual_command", metavar="SUBCOMMAND")
    visual_subparsers.required = True

    run_parser = visual_subparsers.add_parser("run", help="Execute a visual and render outputs.")
    _register_visual_type_parsers(run_parser, include_outputs=True, registrations=visual_registrations)
    run_parser.set_defaults(_handler=_handle_visual_run)

    artifacts_parser = visual_subparsers.add_parser("artifacts", help="Generate visual schema/data artefacts without rendering.")
    _register_visual_type_parsers(artifacts_parser, include_outputs=False, registrations=visual_registrations)
    artifacts_parser.set_defaults(_handler=_handle_visual_artifacts)

    dax_parser = visual_subparsers.add_parser("dax", help="Compile DAX statements for a visual.")
    _register_dax_type_parsers(dax_parser, registrations=dax_registrations)
    dax_parser.set_defaults(_handler=_handle_visual_dax)

    _register_pack_parsers(subparsers)

    return parser


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def _coerce_metadata_value(raw: str) -> object:
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"none", "null"}:
        return None
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def _parse_metadata_pairs(pairs: Sequence[str]) -> Dict[str, object]:
    metadata: Dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Metadata entry '{pair}' must be supplied as key=value")
        key, raw_value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("Metadata keys cannot be empty")
        metadata[key] = _coerce_metadata_value(raw_value.strip())
    return metadata


def _collect_visual_metadata(args: argparse.Namespace, cli: VisualCLIOptions | None) -> Dict[str, object]:
    if not cli:
        return {}
    payload: Dict[str, object] = {}
    for argument in cli.arguments:
        dest = argument.dest or argument.flag.lstrip("-").replace("-", "_")
        value = getattr(args, dest, None)
        if value is None:
            continue
        if isinstance(value, list) and not value:
            continue
        key = argument.metadata_key or dest
        payload[key] = value
    return payload


def _prepare_context_payload(args: argparse.Namespace) -> Dict[str, object]:
    base: Mapping[str, object] | None = None
    if args.context_path is not None:
        base = load_context_file(args.context_path)
    return merge_context_payload(base=base, calculate=args.calculate, define=args.define)


def _prepare_metadata(args: argparse.Namespace, cli: VisualCLIOptions | None) -> Dict[str, object]:
    metadata: Dict[str, object] = {}
    metadata.update(_parse_metadata_pairs(args.meta or []))
    metadata.update(_collect_visual_metadata(args, cli))
    context_payload = _prepare_context_payload(args)
    if context_payload:
        metadata["context"] = context_payload
    for field in ("seed", "scenario", "data_mode", "width", "height", "ignore_placeholders", "metrics_root", "measure_table"):
        value = getattr(args, field, None)
        if value is not None:
            metadata[field] = value
    metadata["data_mode"] = _normalise_data_mode(getattr(args, "data_mode", None))
    build_artifacts_dir = getattr(args, "build_artifacts_dir", None)
    if build_artifacts_dir is not None:
        metadata["build_artifacts_dir"] = build_artifacts_dir
    grain_override = getattr(args, "grain", None)
    if grain_override:
        metadata["grain"] = tuple(grain_override)
    if hasattr(args, "output_png") and args.output_png is not None:
        metadata.setdefault("png_output", args.output_png)
    return metadata


def _prepare_pack_metadata(args: argparse.Namespace) -> Dict[str, object]:
    metadata: Dict[str, object] = {}
    metadata.update(_parse_metadata_pairs(args.meta or []))
    metadata["data_mode"] = _normalise_data_mode(getattr(args, "data_mode", None))
    for field in ("seed", "scenario", "metrics_root", "measure_table", "ignore_placeholders", "width", "height"):
        value = getattr(args, field, None)
        if value is not None:
            metadata[field] = value
    build_artifacts_dir = getattr(args, "build_artifacts_dir", None)
    if build_artifacts_dir is not None:
        metadata["build_artifacts_dir"] = build_artifacts_dir
    grain_override = getattr(args, "grain", None)
    if grain_override:
        metadata["grain"] = tuple(grain_override)
    return metadata


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def _normalise_data_mode(value: str | None) -> str:
    if value is None:
        return "mock"
    candidate = value.strip().lower()
    return candidate or "mock"


def _resolve_datasource_override(args: argparse.Namespace, data_mode: str) -> tuple[str | None, str | None]:
    datasource = args.datasource
    provider_key: str | None = None

    if data_mode == "live":
        if not datasource:
            datasource = "default"
    else:
        provider_key = data_mode or "mock"

    return datasource, provider_key


def _build_pipeline_options(args: argparse.Namespace, metadata: Mapping[str, object], *, include_outputs: bool) -> PipelineOptions:
    data_mode = _normalise_data_mode(getattr(args, "data_mode", None))
    datasource_override, provider_key = _resolve_datasource_override(args, data_mode)

    options = PipelineOptions(
        data=PipelineDataOptions(
            datasource_override=datasource_override,
            dataset_id=args.dataset_id,
            workspace_id=args.workspace_id,
            provider_key=provider_key,
        ),
        artefact_dir=args.artefact_dir,
        metadata=dict(metadata),
        print_dax=args.print_dax,
        validate_define=args.validate_define,
        sort_rows=args.sort_rows,
    )

    if include_outputs:
        options.outputs = _collect_output_targets(args)
        if args.png_scale is not None:
            options.png_scale = args.png_scale
    else:
        options.outputs = []

    return options


def _collect_output_targets(args: argparse.Namespace) -> list[OutputTarget]:
    targets: list[OutputTarget] = []
    project_root = _project_root_for(args.config)
    html_path = args.output_html or _default_output_path(args.config, project_root, "html")
    targets.append(OutputTarget.html(html_path))
    if args.output_png is not None:
        targets.append(OutputTarget.png(args.output_png))
    return targets


def _print_dax_output(result: VisualExecutionResult) -> None:
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


def _summarise_outputs(result: VisualExecutionResult) -> str | None:
    if not result.outputs:
        return None
    rendered = ", ".join(str(artifact.path) for artifact in result.outputs)
    return f"Wrote {result.config.type} visualization to {rendered}"


def _load_visual(config_path: Path) -> BaseVisualConfig:
    try:
        return load_visual_config(config_path)
    except ConfigLoadError as exc:
        raise ValueError(str(exc)) from exc


def _execute_pipeline(
    visual: BaseVisualConfig,
    args: argparse.Namespace,
    options: PipelineOptions,
) -> VisualExecutionResult:
    project_root = _project_root_for(args.config)
    planner_provider = build_default_query_planner_provider()
    context = ExecutionContext(
        config_path=args.config,
        project_root=project_root,
        case_key=args.config.stem,
        options=options,
    )
    pipeline = VisualPipeline(planner_provider=planner_provider)

    try:
        return pipeline.execute(visual, context)
    except (
        DataSourceConfigError,
        PowerBIConfigurationError,
        PowerBIAuthenticationError,
        PowerBIQueryError,
        RuntimeError,
    ) as exc:
        raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _handle_pack_run(args: argparse.Namespace) -> int:
    if args.artefact_dir is None:
        raise ValueError("--artefact-dir must be supplied for pack execution.")

    try:
        pack = load_pack_config(args.pack)
    except PackConfigError as exc:
        raise ValueError(str(exc)) from exc

    metadata = _prepare_pack_metadata(args)
    jinja_env = create_pack_jinja_env()

    options = _build_pipeline_options(args, metadata, include_outputs=False)
    if args.png_scale is not None:
        options.png_scale = args.png_scale

    pipeline = VisualPipeline(planner_provider=build_default_query_planner_provider())
    slide_filter = tuple(args.slides or [])

    try:
        results = run_pack(
            args.pack,
            pack,
            output_root=args.artefact_dir,
            base_options=options,
            pipeline=pipeline,
            env=jinja_env,
            only_slides=slide_filter,
        )
    except ConfigLoadError as exc:
        raise ValueError(str(exc)) from exc
    except (
        DataSourceConfigError,
        PowerBIConfigurationError,
        PowerBIAuthenticationError,
        PowerBIQueryError,
        RuntimeError,
    ) as exc:
        raise RuntimeError(str(exc)) from exc

    png_count = sum(1 for item in results if item.png_path)
    if png_count:
        print(f"[ok] Wrote {png_count} PNG(s) to {args.artefact_dir}")
    else:
        print("[warn] No PNG outputs were produced.")

    return 0


def _handle_visual_run(args: argparse.Namespace) -> int:
    cli_options: VisualCLIOptions | None = getattr(args, "_cli_options", None)
    visual = _load_visual(args.config)

    if args._visual_type == "auto":
        args._visual_type = visual.type

    metadata = _prepare_metadata(args, cli_options)
    options = _build_pipeline_options(args, metadata, include_outputs=True)
    result = _execute_pipeline(visual, args, options)

    if args.print_dax:
        _print_dax_output(result)

    message = _summarise_outputs(result)
    if message:
        print(message)

    if cli_options and cli_options.hooks.post_execute:
        cli_options.hooks.post_execute(result, args)

    return 0


def _handle_visual_artifacts(args: argparse.Namespace) -> int:
    cli_options: VisualCLIOptions | None = getattr(args, "_cli_options", None)
    visual = _load_visual(args.config)

    if args._visual_type == "auto":
        args._visual_type = visual.type

    if args.artefact_dir is None:
        raise ValueError("--artefact-dir must be supplied when generating artefacts.")

    metadata = _prepare_metadata(args, cli_options)
    options = _build_pipeline_options(args, metadata, include_outputs=False)
    result = _execute_pipeline(visual, args, options)

    if cli_options and cli_options.hooks.post_execute:
        cli_options.hooks.post_execute(result, args)

    schema_path = result.schema_path
    dataset_path = result.dataset_path
    if schema_path and dataset_path:
        print(f"[ok] Wrote artefacts to {schema_path.parent}")
    elif schema_path or dataset_path:
        target = schema_path or dataset_path
        print(f"[ok] Wrote artefact to {target}")
    else:
        print("[warn] No artefacts were emitted.")

    return 0


def _handle_visual_dax(args: argparse.Namespace) -> int:
    cli_options: VisualCLIOptions | None = getattr(args, "_cli_options", None)
    config_path = Path(args.config)
    type_name = args._dax_type
    registration: DaxCompilerRegistration | None = None
    visual: object | None = None

    if type_name == "auto":
        candidate = _load_visual(config_path)
        candidate_type = getattr(candidate, "type", None)
        if not isinstance(candidate_type, str) or not candidate_type.strip():
            raise ValueError("Unable to infer visual type; specify it explicitly when using 'auto'.")
        type_name = candidate_type.strip().lower()
        args._dax_type = type_name
        registration = get_dax_compiler_registration(type_name)
        if registration is None:
            raise ValueError(f"No DAX compiler registered for visual type '{type_name}'.")
        if registration.loader is not None:
            visual = registration.loader(config_path)
        else:
            visual = candidate
    else:
        registration = get_dax_compiler_registration(type_name)

    if registration is None:
        raise ValueError(f"No DAX compiler registered for visual type '{type_name}'.")

    loader = registration.loader or _load_visual
    if visual is None:
        visual = loader(config_path)

    metadata = _prepare_metadata(args, cli_options)
    options = _build_pipeline_options(args, metadata, include_outputs=False)

    project_root = _project_root_for(args.config)
    context = ExecutionContext(
        config_path=args.config,
        project_root=project_root,
        case_key=args.config.stem,
        options=options,
    )

    artifacts = registration.compiler(visual, context, args)
    if not artifacts:
        if not args.quiet:
            print("[warn] No DAX plans were generated.")
        return 0

    printed = []
    for artifact in artifacts:
        output_path = artifact.path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(artifact.statement, encoding="utf-8")
        if not args.quiet:
            print(f"[ok] Wrote {output_path}")
        if (
            artifact.placeholders
            and getattr(args, "ignore_placeholders", False)
            and not args.quiet
        ):
            placeholders = ", ".join(sorted(set(artifact.placeholders)))
            print(f"[warn] {output_path.name} – omitted placeholders: {placeholders}")
        if args.print_dax:
            printed.append((output_path, artifact.statement))

    if args.print_dax:
        for path, statement in printed:
            header = f"-- {path}"
            print(f"{header}\n{statement}")

    return 0


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _iter_registrations() -> Sequence[tuple[str, VisualTypeRegistration]]:
    return tuple(iter_visual_registrations())


def _iter_dax_registrations() -> Sequence[tuple[str, DaxCompilerRegistration]]:
    return tuple(iter_dax_compiler_registrations())


def _normalise_argv(
    argv: Sequence[str],
    visual_registrations: Sequence[tuple[str, VisualTypeRegistration]],
    dax_registrations: Sequence[tuple[str, DaxCompilerRegistration]],
) -> list[str]:
    if not argv:
        return list(argv)
    commands = {"visual", "pack"}
    if argv[0] not in commands and not argv[0].startswith("-"):
        return ["visual", "run", "auto", *argv]
    if len(argv) >= 3 and argv[0] == "visual" and argv[1] in {"run", "artifacts", "dax"}:
        candidate = argv[2]
        if candidate.startswith("-"):
            return list(argv)
        if argv[1] == "dax":
            registered = {name for name, _ in dax_registrations}
        else:
            registered = {name for name, _ in visual_registrations}
        if candidate not in registered | {"auto"}:
            return [argv[0], argv[1], "auto", *argv[2:]]
    return list(argv)


def main(argv: Sequence[str] | None = None) -> None:
    ensure_env_loaded()
    args_list = list(argv) if argv is not None else sys.argv[1:]

    plugin_parser = argparse.ArgumentParser(add_help=False)
    plugin_parser.add_argument(
        "--plugin",
        dest="plugins",
        action="append",
        default=[],
    )
    preview_args, _ = plugin_parser.parse_known_args(args_list)
    for module_name in preview_args.plugins or []:
        if module_name:
            __import__(module_name)

    visual_registrations = _iter_registrations()
    dax_registrations = _iter_dax_registrations()
    args_list = _normalise_argv(args_list, visual_registrations, dax_registrations)

    parser = _build_parser(visual_registrations, dax_registrations)
    try:
        args = parser.parse_args(args_list)
        _configure_logging(getattr(args, "log_level", None))
        handler = getattr(args, "_handler", None)
        if handler is None:
            parser.error("No handler registered for command")
        exit_code = handler(args)
    except (ValueError, ContextLoadError) as exc:
        parser.error(str(exc))
        return
    except RuntimeError as exc:
        parser.error(str(exc))
        return

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

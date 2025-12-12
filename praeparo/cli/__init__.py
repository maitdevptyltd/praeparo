"""Praeparo command line interface."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Sequence

from pydantic import ValidationError

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
    PythonVisualBase,
    PYTHON_VISUAL_TYPE,
    build_default_query_planner_provider,
    register_visual_pipeline,
)
from praeparo.pipeline.python_visual_loader import load_python_visual
from praeparo.pack import (
    DEFAULT_POWERBI_CONCURRENCY,
    PackConfigError,
    PackPowerBIFailure,
    allocate_revision,
    create_pack_jinja_env,
    load_pack_config,
    render_value,
    restitch_pack_pptx,
    run_pack,
)
from praeparo.visuals.dax_compilers import (
    DaxCompilerRegistration,
    get_dax_compiler_registration,
    iter_dax_compiler_registrations,
)
from praeparo.visuals.dax import slugify
from praeparo.visuals.context_models import VisualContextModel
from praeparo.powerbi import (
    PowerBIAuthenticationError,
    PowerBIConfigurationError,
    PowerBIQueryError,
)
from praeparo.visuals.context import ContextLoadError, load_context_file, merge_context_payload, resolve_dax_context
from praeparo.visuals.registry import (
    VisualCLIArgument,
    VisualCLIOptions,
    VisualTypeRegistration,
    get_visual_registration,
    iter_visual_registrations,
)

LOG_LEVEL_ENV_VAR = "PRAEPARO_LOG_LEVEL"
INCLUDE_THIRD_PARTY_LOGS_ENV_VAR = "PRAEPARO_INCLUDE_THIRD_PARTY_LOGS"
PBI_CONCURRENCY_ENV_VAR = "PRAEPARO_PBI_MAX_CONCURRENCY"
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging(log_level: str | None, *, include_third_party_logs: bool | None = None) -> None:
    """Configure CLI logging.

    Praeparo logs are emitted at the selected level (default DEBUG). To avoid
    noisy dependencies during pack runs, logs from non-Praeparo libraries are
    suppressed unless they are WARNING+ by default. Set
    `--include-third-party-logs` or `PRAEPARO_INCLUDE_THIRD_PARTY_LOGS=1` to
    restore full third-party logging.
    """

    def _env_flag_enabled(raw: str | None) -> bool:
        if not raw:
            return False
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    env_level = os.getenv(LOG_LEVEL_ENV_VAR)
    candidate = (log_level or env_level or "DEBUG").upper()
    resolved = logging.getLevelName(candidate)
    level = resolved if isinstance(resolved, int) else logging.DEBUG

    include_env = _env_flag_enabled(os.getenv(INCLUDE_THIRD_PARTY_LOGS_ENV_VAR))
    include_third_party = include_env if include_third_party_logs is None else bool(include_third_party_logs)

    # Ensure our handler and filters apply even if a dependency configured logging early.
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    root = logging.getLogger()
    root.setLevel(level)

    if include_third_party:
        return

    third_party_threshold = logging.WARNING

    class _PraeparoOnlyFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.name.startswith("praeparo"):
                return True
            return record.levelno >= third_party_threshold

    for handler in root.handlers:
        handler.addFilter(_PraeparoOnlyFilter())


# ---------------------------------------------------------------------------
# Argument helpers
# ---------------------------------------------------------------------------


def _resolve_project_root(override: Path | None) -> Path:
    """Resolve the project root for discovery and default outputs.

    Prefer explicit overrides supplied via the CLI; otherwise default to the
    current working directory. Callers rely on this to keep pack and visual
    execution consistent.
    """

    if override is not None:
        return override.expanduser().resolve(strict=False)
    return Path.cwd().resolve()


def _default_output_path(config_path: Path, project_root: Path | None, extension: str) -> Path:
    base = project_root or config_path.parent
    build_dir = base / "build"
    return build_dir / f"{config_path.stem}.{extension}"


def _add_plugin_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--plugin",
        dest="plugins",
        action="append",
        default=[],
        metavar="MODULE",
        help="Additional module(s) to import before executing commands (e.g. to register custom visuals).",
    )


def _build_common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("config", type=Path, help="Path to the visual YAML file.")
    _add_plugin_argument(parser)
    parser.add_argument(
        "--project-root",
        dest="project_root",
        type=Path,
        help=(
            "Override the project root used for metrics/datasources discovery and default build paths. "
            "Defaults to the current working directory."
        ),
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
        "dest",
        nargs="?",
        type=Path,
        help=(
            "Optional destination shorthand. A .png or .html path sets default outputs; "
            "a directory or extension-less path defaults to <dest>/<slug>.png and "
            "<dest>/<slug>.html with artefacts under <dest>/_artifacts. Flags override."
        ),
    )
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


def _derive_pack_dest_defaults(pack_path: Path, dest: Path | None) -> tuple[Path | None, Path | None]:
    """
    Interpret the optional positional `dest` for pack runs.

    Returns (artefact_dir, result_file) defaults derived from the shorthand,
    leaving explicit flags to override later.
    """

    if dest is None:
        return None, None

    dest_str = str(dest).strip()
    if not dest_str:
        raise ValueError("Destination path cannot be empty.")

    destination = Path(dest_str).expanduser()
    if destination.suffix.lower() == ".pptx":
        artefact_dir = destination.parent / destination.stem / "_artifacts"
        return artefact_dir, destination

    pack_slug = slugify(pack_path.stem)
    artefact_dir = destination / "_artifacts"
    result_file = destination / f"{pack_slug}.pptx"
    return artefact_dir, result_file


def _derive_visual_dest_defaults(
    config_path: Path,
    dest: Path | None,
) -> tuple[Path | None, Path | None, Path | None]:
    """
    Interpret the optional positional `dest` for visual and python-visual runs.

    Returns (artefact_dir, html_output, png_output) defaults derived from the shorthand,
    leaving explicit flags to override later.
    """

    if dest is None:
        return None, None, None

    dest_str = str(dest).strip()
    if not dest_str:
        raise ValueError("Destination path cannot be empty.")

    destination = Path(dest_str).expanduser()
    suffix = destination.suffix.lower()

    if suffix == ".png":
        artefact_dir = destination.parent / destination.stem / "_artifacts"
        html_output = artefact_dir / f"{config_path.stem}.html"
        return artefact_dir, html_output, destination

    if suffix == ".html":
        artefact_dir = destination.parent / destination.stem / "_artifacts"
        return artefact_dir, destination, None

    visual_slug = slugify(config_path.stem)
    artefact_dir = destination / "_artifacts"
    html_output = destination / f"{visual_slug}.html"
    png_output = destination / f"{visual_slug}.png"
    return artefact_dir, html_output, png_output


def _register_pack_parsers(parent: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    pack_parser = parent.add_parser("pack", help="Pack pipeline commands.")
    pack_subparsers = pack_parser.add_subparsers(dest="pack_command", metavar="SUBCOMMAND")
    pack_subparsers.required = True

    run_parser = pack_subparsers.add_parser("run", help="Execute a pack and export PNGs.")
    run_parser.add_argument("pack", type=Path, help="Path to the pack YAML file.")
    run_parser.add_argument(
        "dest",
        nargs="?",
        type=Path,
        help=(
            "Optional destination shorthand. A .pptx path sets --result-file to that location and "
            "defaults --artefact-dir to <parent>/<stem>/_artifacts; a directory or extension-less "
            "path defaults to <dest>/_artifacts and <dest>/<pack-slug>.pptx. Flags override these defaults."
        ),
    )
    _add_plugin_argument(run_parser)
    run_parser.add_argument(
        "--artefact-dir",
        type=Path,
        dest="artefact_dir",
        help=(
            "Root directory for exported pack artefacts. Optional when using positional dest; "
            "overrides any defaults derived from dest when both are provided."
        ),
    )
    run_parser.add_argument(
        "--result-file",
        dest="result_file",
        type=Path,
        help=(
            "Optional PPTX destination. Overrides defaults derived from positional dest when supplied."
        ),
    )
    run_parser.add_argument(
        "--revision",
        dest="revision",
        help="Optional revision token (e.g. 2025-12, r17). Overrides any automatic revision allocation.",
    )
    run_parser.add_argument(
        "--revision-strategy",
        dest="revision_strategy",
        choices=["full", "minor"],
        help="Optional revision allocation strategy when no explicit --revision is supplied.",
    )
    run_parser.add_argument(
        "--revision-dry-run",
        dest="revision_dry_run",
        action="store_true",
        help="Allocate the next revision without executing visuals or writing PPTX.",
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
        default=None,
        help="Datasource mode (e.g. mock, live). Defaults to live for pack runs when omitted.",
    )
    run_parser.add_argument(
        "--max-pbi-concurrency",
        dest="max_pbi_concurrency",
        type=int,
        help=(
            "Maximum concurrent Power BI exports "
            f"(default {DEFAULT_POWERBI_CONCURRENCY}; env {PBI_CONCURRENCY_ENV_VAR})."
        ),
    )
    run_parser.add_argument(
        "--allow-partial",
        dest="allow_partial",
        action="store_true",
        help=(
            "Allow pack execution to keep successful slide outputs while still reporting failures at the end. "
            "When set, Power BI failures print a summary without a traceback; exit code remains non-zero."
        ),
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
        "--project-root",
        dest="project_root",
        type=Path,
        help=(
            "Override the project root used for metrics/datasources discovery and default build paths. "
            "Defaults to the current working directory."
        ),
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
        help="Limit execution to matching slide titles, ids, or slugified equivalents (repeatable).",
    )
    run_parser.add_argument(
        "--pptx-only",
        dest="pptx_only",
        action="store_true",
        help="Rebuild PPTX from existing artefacts without executing visuals.",
    )
    run_parser.set_defaults(_handler=_handle_pack_run, print_dax=False, validate_define=False, sort_rows=False)


def _update_config_argument_help(parser: argparse.ArgumentParser, help_text: str) -> None:
    """Override the help text for the shared 'config' positional argument."""

    for action in parser._actions:
        if getattr(action, "dest", None) == "config":
            action.help = help_text
            return


def _register_python_visual_parsers(parent: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    python_parser = parent.add_parser("python-visual", help="Python-backed visual commands.")
    python_subparsers = python_parser.add_subparsers(dest="python_visual_command", metavar="SUBCOMMAND")
    python_subparsers.required = True

    run_parser = python_subparsers.add_parser(
        "run",
        help="Execute a Python visual class from a module.",
        parents=[_build_common_parser(), _build_run_specific_parser()],
        add_help=True,
    )
    _update_config_argument_help(run_parser, "Path to the Python visual module.")
    run_parser.add_argument(
        "--visual-class",
        dest="visual_class",
        help="Optional class name to load when multiple visuals are defined in the module.",
    )
    run_parser.set_defaults(_handler=_handle_python_visual_run)


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
        "--include-third-party-logs",
        dest="include_third_party_logs",
        action="store_true",
        default=None,
        help=(
            "Include INFO/DEBUG logs from non-Praeparo libraries. "
            f"Defaults to WARNING+ only; also honours {INCLUDE_THIRD_PARTY_LOGS_ENV_VAR}."
        ),
    )
    _add_plugin_argument(parser)

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

    _register_python_visual_parsers(subparsers)
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


def _pack_to_visual_context_base(payload: Mapping[str, object]) -> Dict[str, object]:
    """
    Adapt a pack-like configuration payload into a visual context mapping.

    - Flattens the `context` section into the base mapping so visual context models can consume it directly.
    - Carries `calculate` and `define` forward for normalisation in merge_context_payload.
    """

    base: Dict[str, object] = {}

    context_section = payload.get("context")
    if isinstance(context_section, Mapping):
        for key, value in context_section.items():
            base[str(key)] = value

    if "calculate" in payload:
        base["calculate"] = payload["calculate"]

    if "define" in payload:
        base["define"] = payload["define"]

    return base


def _build_template_context(payload: Mapping[str, object]) -> Mapping[str, object]:
    """
    Derive a Jinja context from a context payload.

    Prefer an explicit `context` mapping; otherwise fall back to top-level keys
    that are likely to be templating variables rather than filter blocks.
    """

    context_section = payload.get("context")
    if isinstance(context_section, Mapping):
        return context_section

    skip_keys = {"calculate", "define", "filters", "slides", "schema"}
    fallback: Dict[str, object] = {}
    for key, value in payload.items():
        if key in skip_keys:
            continue
        fallback[str(key)] = value
    return fallback


def _prepare_context_payload(args: argparse.Namespace) -> Dict[str, object]:
    base: Mapping[str, object] | None = None
    template_context: Mapping[str, object] = {}
    if args.context_path is not None:
        raw = load_context_file(args.context_path)
        if isinstance(raw, Mapping) and "schema" in raw and "slides" in raw:
            base = _pack_to_visual_context_base(raw)
            context_section = raw.get("context")
            if isinstance(context_section, Mapping):
                template_context = context_section
        else:
            base = raw
            if isinstance(raw, Mapping):
                template_context = _build_template_context(raw)

    if base is not None:
        env = create_pack_jinja_env()
        base = dict(base)
        for key in ("calculate", "define", "filters"):
            if key in base:
                base[key] = render_value(base[key], env=env, context=template_context)

    return merge_context_payload(base=base, calculate=args.calculate, define=args.define)


def _instantiate_visual_context(
    *,
    args: argparse.Namespace,
    registration: VisualTypeRegistration | None,
    metadata: Mapping[str, object],
    project_root: Path | None,
) -> VisualContextModel | None:
    context_model: type[VisualContextModel] | None = None
    if registration is not None:
        context_model = registration.context_model
    if context_model is None:
        return None
    return _instantiate_context_model(
        args=args,
        context_model=context_model,
        metadata=metadata,
        project_root=project_root,
    )


def _instantiate_context_model(
    *,
    args: argparse.Namespace,
    context_model: type[VisualContextModel],
    metadata: Mapping[str, object],
    project_root: Path | None,
) -> VisualContextModel:
    raw_context: Dict[str, object] = dict(metadata)

    metrics_root: Path | None = None
    if getattr(args, "metrics_root", None) is not None:
        metrics_root = Path(args.metrics_root)
    else:
        existing_root = raw_context.get("metrics_root")
        if isinstance(existing_root, (str, Path)):
            metrics_root = Path(existing_root)

    if metrics_root is not None:
        raw_context["metrics_root"] = metrics_root.expanduser().resolve(strict=False)

    context_payload = raw_context.get("context")
    if isinstance(context_payload, Mapping):
        raw_context["context"] = dict(context_payload)

    grain_override = getattr(args, "grain", None)
    if grain_override:
        raw_context["grain"] = tuple(grain_override)

    calculate_filters: tuple[str, ...] = tuple()
    define_blocks: tuple[str, ...] = tuple()
    try:
        calculate_filters, define_blocks = resolve_dax_context(
            base=context_payload if isinstance(context_payload, Mapping) else None,
            calculate=getattr(args, "calculate", None),
            define=getattr(args, "define", None),
        )
    except Exception:
        # If DAX context cannot be resolved, fall back to defaults and let model validation surface errors.
        calculate_filters, define_blocks = (), ()

    raw_context["dax"] = {"calculate": calculate_filters, "define": define_blocks}

    return context_model.model_validate(raw_context)


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


def _prepare_pack_metadata(args: argparse.Namespace, *, pack_path: Path | None = None) -> Dict[str, object]:
    metadata: Dict[str, object] = {}
    metadata.update(_parse_metadata_pairs(args.meta or []))
    metadata["data_mode"] = _normalise_data_mode(getattr(args, "data_mode", None))
    for field in ("seed", "scenario", "metrics_root", "measure_table", "ignore_placeholders", "width", "height"):
        value = getattr(args, field, None)
        if value is not None:
            metadata[field] = value
    result_file = getattr(args, "result_file", None)
    if result_file is not None:
        metadata["result_file"] = result_file
    build_artifacts_dir = getattr(args, "build_artifacts_dir", None)
    if build_artifacts_dir is not None:
        metadata["build_artifacts_dir"] = build_artifacts_dir
    grain_override = getattr(args, "grain", None)
    if grain_override:
        metadata["grain"] = tuple(grain_override)
    revision_value = getattr(args, "revision", None)
    if revision_value is not None:
        metadata["revision"] = revision_value
    revision_minor = getattr(args, "revision_minor", None)
    if revision_minor is not None:
        metadata["revision_minor"] = revision_minor

    if "metrics_root" not in metadata and pack_path is not None:
        from praeparo.datasets.context import resolve_default_metrics_root_for_pack

        metadata["metrics_root"] = resolve_default_metrics_root_for_pack(pack_path)
    return metadata


def _resolve_max_pbi_concurrency(args: argparse.Namespace) -> int:
    if args.max_pbi_concurrency is not None:
        if args.max_pbi_concurrency < 1:
            raise ValueError("--max-pbi-concurrency must be at least 1")
        return args.max_pbi_concurrency

    env_value = os.getenv(PBI_CONCURRENCY_ENV_VAR)
    if env_value:
        try:
            value = int(env_value)
        except ValueError as exc:
            raise ValueError(f"{PBI_CONCURRENCY_ENV_VAR} must be an integer") from exc
        if value < 1:
            raise ValueError(f"{PBI_CONCURRENCY_ENV_VAR} must be at least 1")
        return value

    return DEFAULT_POWERBI_CONCURRENCY


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
    project_root = _resolve_project_root(getattr(args, "project_root", None))
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
        # Surface underlying validation details (e.g. Pydantic ValidationError)
        # so CLI users can see exactly which field failed.
        cause = exc.__cause__
        if isinstance(cause, ValidationError):
            lines: list[str] = []
            for error in cause.errors():
                loc = ".".join(str(part) for part in error.get("loc", ()))
                msg = error.get("msg", "")
                if loc:
                    lines.append(f"- {loc}: {msg}")
                else:
                    lines.append(f"- {msg}")
            detail = "\n".join(lines)
            message = f"{exc}\n\nValidation details:\n{detail}"
            raise ValueError(message) from exc
        raise ValueError(str(exc)) from exc


def _execute_pipeline(
    visual: BaseVisualConfig,
    args: argparse.Namespace,
    options: PipelineOptions,
    registration: VisualTypeRegistration | None,
) -> VisualExecutionResult:
    project_root = _resolve_project_root(getattr(args, "project_root", None))
    planner_provider = build_default_query_planner_provider()
    visual_context = _instantiate_visual_context(
        args=args,
        registration=registration,
        metadata=options.metadata,
        project_root=project_root,
    )
    context = ExecutionContext(
        config_path=args.config,
        project_root=project_root,
        case_key=args.config.stem,
        options=options,
        visual_context=visual_context,
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


def _handle_python_visual_run(args: argparse.Namespace) -> int:
    """Execute a PythonVisualBase subclass using the standard pipeline."""

    artefact_default, html_default, png_default = _derive_visual_dest_defaults(
        args.config,
        getattr(args, "dest", None),
    )
    if artefact_default is not None and args.artefact_dir is None:
        args.artefact_dir = artefact_default
    if html_default is not None and getattr(args, "output_html", None) is None:
        args.output_html = html_default
    if png_default is not None and getattr(args, "output_png", None) is None:
        args.output_png = png_default

    visual = load_python_visual(args.config, getattr(args, "visual_class", None))
    metadata = _prepare_metadata(args, cli=None)
    options = _build_pipeline_options(args, metadata, include_outputs=True)

    project_root = _resolve_project_root(getattr(args, "project_root", None))
    visual_context = _instantiate_context_model(
        args=args,
        context_model=visual.context_model,
        metadata=options.metadata,
        project_root=project_root,
    )

    context = ExecutionContext(
        config_path=args.config,
        project_root=project_root,
        case_key=args.config.stem,
        options=options,
        visual_context=visual_context,
    )

    definition = visual.to_definition()
    register_visual_pipeline(PYTHON_VISUAL_TYPE, definition, overwrite=True)
    pipeline = VisualPipeline(planner_provider=build_default_query_planner_provider())

    visual_config = visual.to_config()
    result = pipeline.execute(visual_config, context)

    if args.print_dax:
        _print_dax_output(result)

    message = _summarise_outputs(result)
    if message:
        print(message)

    return 0


def _handle_pack_run(args: argparse.Namespace) -> int:
    pack_path: Path = args.pack
    dest: Path | None = getattr(args, "dest", None)
    default_artefact_dir, default_result_file = _derive_pack_dest_defaults(pack_path, dest)

    explicit_result_file: Path | None = getattr(args, "result_file", None)
    if dest is not None and (args.artefact_dir or explicit_result_file):
        logger.info(
            "Positional dest supplied; explicit flags override derived defaults.",
            extra={
                "dest": str(dest),
                "artefact_dir": str(args.artefact_dir) if args.artefact_dir else None,
                "result_file": str(explicit_result_file) if explicit_result_file else None,
            },
        )

    artefact_dir = args.artefact_dir or default_artefact_dir
    result_file = explicit_result_file or default_result_file
    explicit_result_supplied = explicit_result_file is not None

    if artefact_dir is None and result_file is not None:
        artefact_dir = result_file.parent / result_file.stem / "_artifacts"

    if artefact_dir is None:
        raise ValueError("Provide --artefact-dir or a positional dest to choose output locations.")

    if getattr(args, "data_mode", None) is None:
        args.data_mode = "live"

    try:
        pack = load_pack_config(pack_path)
    except PackConfigError as exc:
        raise ValueError(str(exc)) from exc

    strategy_arg = getattr(args, "revision_strategy", None)
    override_revision = getattr(args, "revision", None)
    pptx_only = getattr(args, "pptx_only", False)
    has_slides = bool(args.slides)
    effective_strategy = strategy_arg
    if (
        effective_strategy is None
        and override_revision is None
        and not getattr(args, "revision_dry_run", False)
    ):
        if pptx_only or has_slides:
            effective_strategy = "minor"
        else:
            effective_strategy = "full"

    from praeparo.pack.metric_context import dump_context_payload

    revision_info = allocate_revision(
        pack_path,
        artefact_root=artefact_dir,
        pack_context=dump_context_payload(pack.context),
        strategy=effective_strategy,
        override=override_revision,
        dry_run=getattr(args, "revision_dry_run", False),
    )

    if revision_info:
        if getattr(args, "revision_dry_run", False):
            planned_result = result_file or (artefact_dir.parent / revision_info.pptx_name)
            print(
                f"Next revision for {pack_path.stem}: "
                f"revision={revision_info.revision} minor={revision_info.minor} "
                f"result_file={planned_result}"
            )
            return 0

        args.revision = revision_info.revision
        setattr(args, "revision_minor", revision_info.minor)

        if not explicit_result_supplied:
            base_result_dir = result_file.parent if result_file else artefact_dir.parent
            result_file = base_result_dir / revision_info.pptx_name

    args.artefact_dir = artefact_dir
    args.result_file = result_file

    if getattr(args, "pptx_only", False):
        if args.result_file is None:
            raise ValueError("PPTX-only restitch requires a result file; provide dest or --result-file.")
        metadata = _prepare_pack_metadata(args, pack_path=pack_path)
        options = _build_pipeline_options(args, metadata, include_outputs=False)
        if args.png_scale is not None:
            options.png_scale = args.png_scale
        restitch_pack_pptx(
            pack_path,
            pack,
            output_root=args.artefact_dir,
            result_file=args.result_file,
            base_options=options,
        )
        print(f"[ok] Restitched PPTX to {args.result_file}")
        return 0

    metadata = _prepare_pack_metadata(args, pack_path=pack_path)
    jinja_env = create_pack_jinja_env()

    options = _build_pipeline_options(args, metadata, include_outputs=False)
    if args.png_scale is not None:
        options.png_scale = args.png_scale

    max_pbi_concurrency = _resolve_max_pbi_concurrency(args)
    pipeline = VisualPipeline(planner_provider=build_default_query_planner_provider())
    slide_filter = tuple(args.slides or [])

    project_root = _resolve_project_root(getattr(args, "project_root", None))

    partial_failure = False
    try:
        results = run_pack(
            args.pack,
            pack,
            project_root=project_root,
            output_root=args.artefact_dir,
            max_powerbi_concurrency=max_pbi_concurrency,
            base_options=options,
            pipeline=pipeline,
            env=jinja_env,
            only_slides=slide_filter,
        )
    except ConfigLoadError as exc:
        raise ValueError(str(exc)) from exc
    except PackPowerBIFailure as exc:
        # Surface the richer summary to the user while preserving successful artefacts.
        if args.allow_partial:
            print(str(exc))
            results = exc.successful_results
            partial_failure = True
        else:
            raise RuntimeError(str(exc)) from exc
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

    # Even in partial mode, propagate a non-zero exit so automation can detect failures.
    if partial_failure:
        return 1

    return 0


def _handle_visual_run(args: argparse.Namespace) -> int:
    cli_options: VisualCLIOptions | None = getattr(args, "_cli_options", None)
    artefact_default, html_default, png_default = _derive_visual_dest_defaults(
        args.config,
        getattr(args, "dest", None),
    )
    if artefact_default is not None and args.artefact_dir is None:
        args.artefact_dir = artefact_default
    if html_default is not None and getattr(args, "output_html", None) is None:
        args.output_html = html_default
    if png_default is not None and getattr(args, "output_png", None) is None:
        args.output_png = png_default

    visual = _load_visual(args.config)

    if args._visual_type == "auto":
        args._visual_type = visual.type

    registration = get_visual_registration(args._visual_type)
    metadata = _prepare_metadata(args, cli_options)
    options = _build_pipeline_options(args, metadata, include_outputs=True)
    result = _execute_pipeline(visual, args, options, registration)

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

    registration = get_visual_registration(args._visual_type)
    if args.artefact_dir is None:
        raise ValueError("--artefact-dir must be supplied when generating artefacts.")

    metadata = _prepare_metadata(args, cli_options)
    options = _build_pipeline_options(args, metadata, include_outputs=False)
    result = _execute_pipeline(visual, args, options, registration)

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

    visual_registration: VisualTypeRegistration | None = None

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
        visual_registration = get_visual_registration(type_name)
        if registration.loader is not None:
            visual = registration.loader(config_path)
        else:
            visual = candidate
    else:
        registration = get_dax_compiler_registration(type_name)
        visual_registration = get_visual_registration(type_name)

    if registration is None:
        raise ValueError(f"No DAX compiler registered for visual type '{type_name}'.")

    loader = registration.loader or _load_visual
    if visual is None:
        visual = loader(config_path)

    metadata = _prepare_metadata(args, cli_options)
    options = _build_pipeline_options(args, metadata, include_outputs=False)

    project_root = _resolve_project_root(getattr(args, "project_root", None))
    visual_context = _instantiate_visual_context(
        args=args,
        registration=visual_registration,
        metadata=options.metadata,
        project_root=project_root,
    )
    context = ExecutionContext(
        config_path=args.config,
        project_root=project_root,
        case_key=args.config.stem,
        options=options,
        visual_context=visual_context,
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
    commands = {"visual", "pack", "python-visual"}
    if argv[0] not in commands and not argv[0].startswith("-"):
        if argv[0].endswith(".py"):
            return ["python-visual", "run", *argv]
        return ["visual", "run", "auto", *argv]
    if len(argv) >= 3 and argv[0] == "visual" and argv[1] in {"run", "artifacts", "dax"}:
        candidate = argv[2]
        if candidate.startswith("-"):
            return list(argv)
        if argv[1] == "run" and candidate.endswith(".py"):
            return ["python-visual", "run", candidate, *argv[3:]]
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
        _configure_logging(
            getattr(args, "log_level", None),
            include_third_party_logs=getattr(args, "include_third_party_logs", None),
        )
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

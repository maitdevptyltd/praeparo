"""Command line helpers for Praeparo metric definitions."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Sequence

from ..env import ensure_env_loaded
from ..pack.templating import create_pack_jinja_env, render_value
from ..models.scoped_calculate import ScopedCalculateMap
from ..schema import write_metric_schema
from ..visuals.context import resolve_dax_context
from ..visuals.context_layers import resolve_layered_context_payload
from .catalog import MetricDiscoveryError, load_metric_catalog
from .explain_runner import (
    derive_explain_outputs,
    resolve_explain_datasource,
    run_metric_explain,
    write_explain_dax,
    write_summary_json,
 )
from .explain import build_metric_explain_plan


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


def _render_path_template(value: Path | None, *, context: dict[str, object]) -> Path | None:
    if value is None:
        return None
    env = create_pack_jinja_env()
    rendered = render_value(str(value), env=env, context=context)
    if not isinstance(rendered, str):
        raise ValueError("Path templates must render to a string value.")
    return Path(rendered).expanduser()


def _discover_default_metrics_root(start: Path) -> Path:
    """Heuristically discover a `registry/metrics` root relative to *start*."""

    current = start.resolve()
    for _ in range(6):
        candidate = current / "registry" / "metrics"
        if candidate.is_dir():
            return candidate
        candidate = current / "metrics"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return start


def _command_explain(args: argparse.Namespace) -> int:
    metrics_root = (
        Path(args.metrics_root).expanduser().resolve(strict=False)
        if args.metrics_root
        else _discover_default_metrics_root(Path.cwd())
    )

    # Start by resolving layered context (registry defaults + explicit layers + CLI calculate).
    jinja_env = create_pack_jinja_env()
    context_payload = resolve_layered_context_payload(
        metrics_root=metrics_root,
        context_paths=tuple(args.context or ()),
        calculate=args.calculate,
        env=jinja_env,
    )

    # Packs store metric-context scoping defaults under `context.metrics.calculate`. For explain
    # runs we treat those defaults as additional calculate predicates so evidence exports are
    # automatically constrained (for example, to the current reporting month) without adding
    # standalone CLI flags like `--month`.
    metrics_calculate: object | None = None
    raw_metrics = context_payload.get("metrics")
    if isinstance(raw_metrics, dict):
        metrics_calculate = raw_metrics.get("calculate")
    rendered_metrics_calculate = (
        render_value(metrics_calculate, env=jinja_env, context=context_payload) if metrics_calculate else None
    )
    scoped_defaults = ScopedCalculateMap.from_raw(rendered_metrics_calculate) if rendered_metrics_calculate else ScopedCalculateMap()
    scoped_filters = [*scoped_defaults.flatten_define(), *scoped_defaults.flatten_evaluate()]

    calculate_filters, define_blocks = resolve_dax_context(base=context_payload, calculate=scoped_filters)

    dest = _render_path_template(args.dest, context=context_payload)
    artefact_dir = _render_path_template(args.artefact_dir, context=context_payload)

    outputs = derive_explain_outputs(
        metric_identifier=args.metric_key,
        dest=dest,
        artefact_dir=artefact_dir,
    )

    # With paths resolved, load the metric catalog and compile + execute the explain query.
    try:
        catalog = load_metric_catalog([metrics_root])
    except MetricDiscoveryError as exc:
        print("Failed to load metric catalog:")
        for message in exc.errors:
            print(f"  - {message}")
        return 1

    if args.plan_only:
        plan = build_metric_explain_plan(
            catalog,
            metric_identifier=args.metric_key,
            context_calculate_filters=calculate_filters,
            context_define_blocks=define_blocks,
            limit=int(args.limit),
            variant_mode=args.variant_mode,
        )
        write_explain_dax(outputs.dax_path, plan.statement)
        write_summary_json(
            outputs.summary_path,
            metric_identifier=args.metric_key,
            row_count=0,
            null_counts={},
            distinct_counts={},
            warnings=plan.warnings,
            evidence_path=None,
            dax_path=outputs.dax_path,
        )
        for warning in plan.warnings:
            print(f"[WARN] {warning}")
        print(f"DAX: {outputs.dax_path}")
        print(f"Summary: {outputs.summary_path}")
        return 0

    data_mode = args.data_mode or "live"
    if data_mode not in {"mock", "live"}:
        raise ValueError("data-mode must be one of {'mock', 'live'}.")

    datasource = None
    if data_mode == "live":
        datasource_ref = args.datasource
        dataset_id = args.dataset_id or os.getenv("PRAEPARO_PBI_DATASET_ID")
        workspace_id = args.workspace_id or os.getenv("PRAEPARO_PBI_WORKSPACE_ID")
        datasource = resolve_explain_datasource(
            datasource=datasource_ref,
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            cwd=Path.cwd(),
        )
        # Allow CLI overrides to win when provided.
        if args.workspace_id:
            datasource = datasource.__class__(
                name=datasource.name,
                type=datasource.type,
                dataset_id=datasource.dataset_id,
                workspace_id=args.workspace_id,
                settings=datasource.settings,
                source_path=datasource.source_path,
            )

    try:
        dax_path, evidence_path, summary_path, row_count, warnings = run_metric_explain(
            catalog=catalog,
            metric_identifier=args.metric_key,
            context_calculate_filters=calculate_filters,
            context_define_blocks=define_blocks,
            limit=int(args.limit),
            variant_mode=args.variant_mode,
            data_mode=data_mode,
            datasource=datasource,
            outputs=outputs,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Explain failed: {type(exc).__name__}: {exc}")
        print(f"Wrote query to {outputs.dax_path}")
        print(f"Wrote summary to {outputs.summary_path}")
        return 1

    for warning in warnings:
        print(f"[WARN] {warning}")

    print(f"Rows: {row_count}")
    print(f"DAX: {dax_path}")
    print(f"Evidence: {evidence_path}")
    print(f"Summary: {summary_path}")
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

    explain_parser = subparsers.add_parser("explain", help="Export row-level evidence for a metric")
    explain_parser.add_argument("metric_key", help="Metric key or dotted variant key to explain")
    explain_parser.add_argument(
        "dest",
        nargs="?",
        type=Path,
        help=(
            "Optional destination shorthand. A .csv path writes evidence to that location and "
            "defaults artifacts to <parent>/<stem>/_artifacts; a directory or extension-less path "
            "writes evidence to <dest>/evidence.csv with artifacts under <dest>/_artifacts."
        ),
    )
    explain_parser.add_argument(
        "--metrics-root",
        dest="metrics_root",
        type=Path,
        default=None,
        help="Root directory containing metric YAML files (defaults to the nearest registry/metrics).",
    )
    explain_parser.add_argument(
        "--context",
        dest="context",
        type=Path,
        action="append",
        default=[],
        help="Context layer YAML/JSON file (repeatable). Pack-shaped YAML is also accepted.",
    )
    explain_parser.add_argument(
        "--calculate",
        dest="calculate",
        action="append",
        default=[],
        help="Extra DAX calculate predicate (repeatable; appended after context layers).",
    )
    explain_parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=50_000,
        help="Maximum number of evidence rows to export.",
    )
    explain_parser.add_argument(
        "--variant-mode",
        dest="variant_mode",
        choices=["flag", "filter"],
        default="flag",
        help="Variant handling: flag emits __passes_variant where possible; filter applies variant filters to the rowset.",
    )
    explain_parser.add_argument(
        "--data-mode",
        dest="data_mode",
        choices=["mock", "live"],
        default="live",
        help="Datasource mode for evidence execution.",
    )
    explain_parser.add_argument(
        "--plan-only",
        dest="plan_only",
        action="store_true",
        help="Only write explain.dax (+ summary.json) without executing the query.",
    )
    explain_parser.add_argument(
        "--datasource",
        dest="datasource",
        default=None,
        help="Datasource name or YAML path (searched under datasources/).",
    )
    explain_parser.add_argument(
        "--dataset-id",
        dest="dataset_id",
        default=None,
        help="Explicit Power BI dataset id (overrides datasource dataset_id).",
    )
    explain_parser.add_argument(
        "--workspace-id",
        dest="workspace_id",
        default=None,
        help="Explicit Power BI workspace id (overrides datasource workspace_id).",
    )
    explain_parser.add_argument(
        "--artefact-dir",
        dest="artefact_dir",
        type=Path,
        default=None,
        help="Optional directory for explain artifacts (overrides any defaults derived from dest).",
    )
    explain_parser.set_defaults(func=_command_explain)

    return parser


def run(argv: Sequence[str] | None = None) -> int:
    ensure_env_loaded()
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


__all__ = ["run", "main"]

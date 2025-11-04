"""Register shared cartesian chart visual types."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping, Tuple

from praeparo.models import CartesianChartConfig
from praeparo.pipeline import build_default_query_planner_provider
from praeparo.visuals.dax_compilers import DaxCompileArtifact, register_dax_compiler
from praeparo.visuals.registry import register_visual_type


def _load_cartesian_visual(path: Path, payload: Mapping[str, object], stack: Tuple[Path, ...]) -> CartesianChartConfig:
    return CartesianChartConfig.model_validate(payload)


def _default_artefact_path(args: argparse.Namespace, context_path: Path, project_root: Path | None) -> Path:
    base = project_root or context_path.parent
    return base / "build" / f"{context_path.stem}.dax"


def _chart_dax_compiler(visual: object, context, args: argparse.Namespace) -> Tuple[DaxCompileArtifact, ...]:
    if not isinstance(visual, CartesianChartConfig):
        raise TypeError("Chart DAX compiler expects a CartesianChartConfig instance.")

    context.options.data.provider_key = "mock"
    context.options.data.dataset_id = None
    context.options.data.datasource_override = None

    planner_provider = build_default_query_planner_provider()
    planner = planner_provider.resolve(visual, context)
    result = planner.plan(visual, context=context)

    artefact_dir = context.options.artefact_dir
    config_path = Path(args.config)
    project_root = context.project_root if context.project_root else config_path.parent
    if artefact_dir is not None:
        base_dir = Path(artefact_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        output_path = base_dir / f"{config_path.stem}.dax"
    else:
        output_path = _default_artefact_path(args, config_path, project_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    artifact = DaxCompileArtifact(
        path=output_path,
        statement=result.plan.statement,
        plan=result.plan,
        placeholders=result.placeholders,
    )
    return (artifact,)


register_visual_type("column", _load_cartesian_visual, overwrite=True)
register_visual_type("bar", _load_cartesian_visual, overwrite=True)
register_dax_compiler("column", _chart_dax_compiler, overwrite=True)
register_dax_compiler("bar", _chart_dax_compiler, overwrite=True)

__all__ = []

"""Pack execution orchestrator."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from jinja2 import Environment

from praeparo.models import BaseVisualConfig, PackConfig, PackSlide
from praeparo.pack.filters import merge_calculate_filters, merge_odata_filters
from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.pipeline import (
    ExecutionContext,
    OutputKind,
    OutputTarget,
    PipelineOptions,
    VisualExecutionResult,
    VisualPipeline,
    build_default_query_planner_provider,
)
from praeparo.visuals.dax.planner_core import slugify
from praeparo.io.yaml_loader import load_visual_config
from praeparo.visuals.context import merge_context_payload


VisualLoader = Callable[[Path], BaseVisualConfig]


@dataclass
class PackSlideResult:
    """Outcome for a single slide execution."""

    slide: PackSlide
    visual_path: Path
    result: VisualExecutionResult
    png_path: Path | None


def _slug_for_slide(slide: PackSlide, index: int) -> str:
    if slide.id:
        return slugify(slide.id)
    if slide.title:
        return slugify(slide.title)
    return f"slide_{index}"


def _select_png_output(result: VisualExecutionResult, requested_outputs: Sequence[OutputTarget]) -> Path | None:
    png_targets = [target.path for target in requested_outputs if target.kind is OutputKind.PNG]
    if not png_targets:
        return None
    requested_paths = {path.resolve() for path in png_targets}
    for artifact in result.outputs:
        if artifact.kind is OutputKind.PNG and artifact.path.resolve() in requested_paths:
            return artifact.path
    return png_targets[0]


def _prepare_slide_options(
    base_options: PipelineOptions,
    *,
    slide_slug: str,
    artefact_root: Path,
    metadata_update: Mapping[str, object] | None = None,
    png_scale: float | None = None,
) -> tuple[PipelineOptions, Path]:
    """Clone base options and attach per-slide outputs/artefact directory."""

    slide_dir = artefact_root / slide_slug
    slide_dir.mkdir(parents=True, exist_ok=True)

    options = copy.deepcopy(base_options)
    options.outputs = [OutputTarget.png(artefact_root / f"{slide_slug}.png")]
    options.artefact_dir = slide_dir
    if png_scale is not None:
        options.png_scale = png_scale

    merged_metadata: dict[str, object] = {}
    merged_metadata.update(base_options.metadata or {})
    if metadata_update:
        merged_metadata.update(metadata_update)
    options.metadata = merged_metadata
    return options, slide_dir


def _should_run_slide(slide: PackSlide, *, only: set[str] | None) -> bool:
    if not only:
        return True
    candidates = {slide.title, slugify(slide.title)}
    if slide.id:
        candidates.add(slide.id)
        candidates.add(slugify(slide.id))
    return any(candidate in only for candidate in candidates)


def run_pack(
    pack_path: Path,
    pack: PackConfig,
    *,
    output_root: Path,
    base_options: PipelineOptions | None = None,
    visual_loader: VisualLoader = load_visual_config,
    pipeline: VisualPipeline | None = None,
    env: Environment | None = None,
    only_slides: Iterable[str] | None = None,
) -> list[PackSlideResult]:
    """Execute a pack and export PNGs for each visual slide."""

    output_root.mkdir(parents=True, exist_ok=True)

    jinja_env = env or create_pack_jinja_env()
    context_payload = dict(pack.context or {})

    rendered_global_filters = render_value(pack.filters, env=jinja_env, context=context_payload)
    rendered_global_calculate = render_value(pack.calculate, env=jinja_env, context=context_payload)

    resolved_pipeline = pipeline or VisualPipeline(
        planner_provider=build_default_query_planner_provider(),
    )
    base = base_options or PipelineOptions()

    slide_filter = {slugify(item) for item in only_slides} if only_slides else None

    results: list[PackSlideResult] = []
    for index, slide in enumerate(pack.slides, start=1):
        if slide.visual is None:
            continue
        if slide_filter and not _should_run_slide(slide, only=slide_filter):
            continue

        visual_ref = slide.visual.ref
        visual_path = (pack_path.parent / visual_ref).resolve()
        visual = visual_loader(visual_path)

        slide_filters = render_value(slide.visual.filters, env=jinja_env, context=context_payload)
        slide_calculate = render_value(slide.visual.calculate, env=jinja_env, context=context_payload)

        merged_filters = merge_odata_filters(rendered_global_filters, slide_filters)
        calculate_filters = merge_calculate_filters(rendered_global_calculate, slide_calculate)

        slide_slug = _slug_for_slide(slide, index)
        options, slide_dir = _prepare_slide_options(
            base,
            slide_slug=slide_slug,
            artefact_root=output_root,
            png_scale=base.png_scale,
        )

        if visual.type == "powerbi":
            if merged_filters:
                options.metadata["powerbi_filters"] = merged_filters
            options.metadata.setdefault("build_artifacts_dir", slide_dir / "pbi_exports")

        if calculate_filters:
            existing_context = options.metadata.get("context") if isinstance(options.metadata, dict) else {}
            merged_context = merge_context_payload(
                base=existing_context if isinstance(existing_context, Mapping) else {},
                calculate=calculate_filters,
            )
            options.metadata["context"] = merged_context

        execution_context = ExecutionContext(
            config_path=visual_path,
            project_root=pack_path.parent,
            case_key=slide_slug,
            options=options,
        )
        result = resolved_pipeline.execute(visual, execution_context)
        png_path = _select_png_output(result, options.outputs)

        results.append(
            PackSlideResult(
                slide=slide,
                visual_path=visual_path,
                result=result,
                png_path=png_path,
            )
        )

    return results


__all__ = ["PackSlideResult", "run_pack"]

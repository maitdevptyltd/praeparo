"""Pack execution orchestrator."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from jinja2 import Environment

from praeparo.models import BaseVisualConfig, FiltersType, PackConfig, PackPlaceholder, PackSlide, PackVisualRef
from praeparo.pack.filters import merge_calculate_filters, merge_odata_filters
from praeparo.pack.pbi_queue import PowerBIExportJob, PowerBIExportQueue, PowerBIExportResult
from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.pack.pptx import PlaceholderSize, assemble_pack_pptx, resolve_template_geometry
from praeparo.pipeline import (
    ExecutionContext,
    OutputKind,
    OutputTarget,
    PipelineOptions,
    PythonVisualBase,
    VisualExecutionResult,
    VisualPipeline,
    PYTHON_VISUAL_TYPE,
    build_default_query_planner_provider,
    register_visual_pipeline,
)
from praeparo.pipeline.python_visual_loader import load_python_visual
from praeparo.visuals.dax.planner_core import slugify
from praeparo.io.yaml_loader import load_visual_config, load_visual_from_payload
from praeparo.visuals.context import merge_context_payload, resolve_dax_context
from praeparo.visuals.registry import VisualTypeRegistration, get_visual_registration, _is_python_visual_type
from praeparo.visuals.context_models import VisualContextModel


VisualLoader = Callable[[Path], BaseVisualConfig]

logger = logging.getLogger(__name__)


@dataclass
class PackSlideResult:
    """Outcome for a single slide execution."""

    slide: PackSlide
    visual_path: Path
    result: VisualExecutionResult
    png_path: Path | None


DEFAULT_POWERBI_CONCURRENCY = 5


class PackPowerBIFailure(RuntimeError):
    """Raised when one or more Power BI slides fail during a pack run."""

    def __init__(
        self,
        message: str,
        *,
        successful_results: list[PackSlideResult],
        failed_exports: Sequence[PowerBIExportResult],
    ) -> None:
        super().__init__(message)
        self.successful_results = successful_results
        self.failed_exports = failed_exports


def _format_powerbi_failure_summary(failed_exports: Sequence[PowerBIExportResult]) -> str:
    """Build a human-readable summary of failed Power BI slide exports."""

    lines = [f"{len(failed_exports)} Power BI slide(s) failed:"]

    for item in failed_exports:
        exc = item.exception
        exc_type = exc.__class__.__name__ if exc else "Error"
        message = ""
        if exc:
            raw = str(exc)
            message = raw.splitlines()[0] if raw else repr(exc)
        title = f" ({item.job.slide_title})" if item.job.slide_title else ""
        lines.append(f"  - {item.job.slide_slug}{title}: {exc_type}: {message}".rstrip())

    focus_target = failed_exports[0].job.slide_title or failed_exports[0].job.slide_slug
    lines.append(
        f"Hint: re-run with --slides \"{focus_target}\" --max-pbi-concurrency 1 for focused debugging."
    )

    return "\n".join(lines)


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


def _instantiate_slide_context(
    *,
    registration: VisualTypeRegistration | None,
    metadata: Mapping[str, object],
    project_root: Path,
) -> VisualContextModel | None:
    if registration is None or registration.context_model is None:
        return None

    context_model = registration.context_model
    raw_context: dict[str, object] = dict(metadata)

    metrics_root = raw_context.get("metrics_root")
    if isinstance(metrics_root, (str, Path)):
        resolved_root = Path(metrics_root)
        raw_context["metrics_root"] = resolved_root.expanduser().resolve(strict=False)

    context_payload = raw_context.get("context")
    if isinstance(context_payload, Mapping):
        raw_context["context"] = dict(context_payload)

    calculate_filters: tuple[str, ...]
    define_blocks: tuple[str, ...]
    calculate_filters, define_blocks = resolve_dax_context(
        base=context_payload if isinstance(context_payload, Mapping) else None,
        calculate=None,
        define=None,
    )
    raw_context["dax"] = {"calculate": calculate_filters, "define": define_blocks}

    return context_model.model_validate(raw_context)


def _instantiate_python_visual_context(
    *,
    visual: PythonVisualBase,
    metadata: Mapping[str, object],
) -> VisualContextModel:
    """Instantiate the declared Python visual context model from pack metadata."""

    raw_context: dict[str, object] = dict(metadata or {})

    metrics_root = raw_context.get("metrics_root")
    if isinstance(metrics_root, (str, Path)):
        resolved_root = Path(metrics_root)
        raw_context["metrics_root"] = resolved_root.expanduser().resolve(strict=False)

    context_payload = raw_context.get("context")
    if isinstance(context_payload, Mapping):
        raw_context["context"] = dict(context_payload)

    calculate_filters, define_blocks = resolve_dax_context(
        base=context_payload if isinstance(context_payload, Mapping) else None,
        calculate=None,
        define=None,
    )
    raw_context["dax"] = {"calculate": calculate_filters, "define": define_blocks}

    return visual.context_model.model_validate(raw_context)


def _should_run_slide(slide: PackSlide, *, only: set[str] | None) -> bool:
    if not only:
        return True
    candidates = {slide.title, slugify(slide.title)}
    if slide.id:
        candidates.add(slide.id)
        candidates.add(slugify(slide.id))
    return any(candidate in only for candidate in candidates)


def _resolve_default_template(pack_path: Path) -> Path | None:
    """
    Try common locations for the shared pack PPTX template.

    Preference order:
    - Sibling to the pack file
    - Parent folder
    - registry/packs/pack_template.pptx (rooted from pack path)
    """

    candidates: list[Path] = []
    # Local to pack
    candidates.append(pack_path.parent / "pack_template.pptx")
    # One level up
    candidates.append(pack_path.parent.parent / "pack_template.pptx")
    # Shared registry/packs template relative to pack location
    try:
        candidates.append(pack_path.parent.parent / "packs" / "pack_template.pptx")
        candidates.append(pack_path.parent.parent.parent / "packs" / "pack_template.pptx")
        candidates.append(pack_path.parent.parent.parent / "registry" / "packs" / "pack_template.pptx")
    except IndexError:
        pass

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _reuse_existing_assets(
    *,
    slide: PackSlide,
    slide_slug: str,
    ordinal: str,
    pack_root: Path,
    output_root: Path,
    slide_png_map: dict[str, Path],
    placeholder_png_map: dict[str, dict[str, Path]],
) -> None:
    """Populate PNG maps from prior artefacts and static image definitions.

    This helper is used when slides are skipped (partial runs) and by the
    PPTX-only restitch path to reuse existing outputs without executing
    visuals. Static images remain mandatory: if a path is configured but not
    found on disk, surface an error so callers can fix the pack definition.
    """

    if slide.image:
        image_path = (pack_root / slide.image).expanduser().resolve(strict=False)
        if not image_path.exists():
            raise ValueError(f"Static slide image not found for '{slide_slug}': {image_path}")
        slide_png_map.setdefault(slide_slug, image_path)

    png_path = output_root / f"[{ordinal}]_{slide_slug}.png"
    if png_path.exists():
        slide_png_map.setdefault(slide_slug, png_path)

    if not slide.placeholders:
        return

    placeholder_map = placeholder_png_map.setdefault(slide_slug, {})
    for placeholder_id, placeholder in slide.placeholders.items():
        placeholder_slug = f"{slide_slug}__{slugify(placeholder_id)}"

        if placeholder.image:
            image_path = (pack_root / placeholder.image).expanduser().resolve(strict=False)
            if not image_path.exists():
                raise ValueError(
                    f"Static placeholder image not found for '{placeholder_id}' on slide '{slide_slug}': {image_path}"
                )
            placeholder_map.setdefault(placeholder_slug, image_path)

        placeholder_png = output_root / f"[{ordinal}]_{placeholder_slug}.png"
        if placeholder_png.exists():
            placeholder_map.setdefault(placeholder_slug, placeholder_png)


def _render_slide_metadata(*, pack: PackConfig, env: Environment, context: Mapping[str, object]) -> None:
    """Apply Jinja templating to slide-level metadata so downstream consumers see rendered text."""

    for slide in pack.slides:
        if slide.title:
            slide.title = render_value(slide.title, env=env, context=context)
        if slide.notes:
            slide.notes = render_value(slide.notes, env=env, context=context)


def run_pack(
    pack_path: Path,
    pack: PackConfig,
    *,
    output_root: Path,
    max_powerbi_concurrency: int | None = None,
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
    rendered_define = render_value(pack.define, env=jinja_env, context=context_payload)
    _render_slide_metadata(pack=pack, env=jinja_env, context=context_payload)
    visual_context_base: dict[str, object] = {}
    if context_payload:
        for key, value in context_payload.items():
            visual_context_base[str(key)] = value

    resolved_pipeline = pipeline or VisualPipeline(
        planner_provider=build_default_query_planner_provider(),
    )
    base = base_options or PipelineOptions()
    effective_concurrency = max_powerbi_concurrency or DEFAULT_POWERBI_CONCURRENCY
    # VisualPipeline is currently stateless per execute() call and relies on per-call
    # ExecutionContext plus per-visual planners/clients. If future changes add shared
    # mutable state, re-evaluate thread safety for PowerBIExportQueue.
    powerbi_queue = PowerBIExportQueue(
        resolved_pipeline,
        max_concurrent_exports=effective_concurrency,
    )

    slide_filter = {slugify(item) for item in only_slides} if only_slides else None
    logger.info(
        "Running pack",
        extra={
            "pack_path": str(pack_path),
            "artefact_dir": str(output_root),
            "slide_count": len(pack.slides),
            "only_slides": sorted(slide_filter) if slide_filter else None,
            "powerbi_concurrency": effective_concurrency,
        },
    )

    if context_payload:
        logger.debug("Rendered pack context", extra={"keys": sorted(context_payload.keys())})
    if rendered_global_filters:
        if isinstance(rendered_global_filters, Mapping):
            logger.debug("Rendered global filters", extra={"keys": sorted(rendered_global_filters.keys())})
        else:
            logger.debug("Rendered global filters", extra={"count": len(rendered_global_filters)})
    if rendered_global_calculate:
        if isinstance(rendered_global_calculate, Mapping):
            logger.debug("Rendered global calculate", extra={"keys": sorted(rendered_global_calculate.keys())})
        else:
            try:
                logger.debug("Rendered global calculate", extra={"count": len(rendered_global_calculate)})  # type: ignore[arg-type]
            except TypeError:
                logger.debug("Rendered global calculate", extra={"count": 1})

    ordered_results: list[tuple[int, PackSlideResult]] = []
    slide_png_map: dict[str, Path] = {}
    placeholder_png_map: dict[str, dict[str, Path]] = {}
    pack_root = pack_path.parent

    # Resolve PPTX template geometry once per pack so visuals can size their canvases.
    template_geometry_by_template: dict[str, PlaceholderSize] = {}
    template_geometry_by_placeholder: dict[tuple[str, str], PlaceholderSize] = {}
    template_for_geometry = _resolve_default_template(pack_path)
    if template_for_geometry is not None:
        try:
            slide_geom, placeholder_geom = resolve_template_geometry(template_for_geometry)
            template_geometry_by_template = slide_geom
            template_geometry_by_placeholder = placeholder_geom
        except Exception:
            logger.exception(
                "Failed to resolve PPTX template geometry; continuing without width/height hints",
                extra={"template_path": str(template_for_geometry)},
            )

    def _render_filters(value: object | None) -> FiltersType:
        return render_value(value, env=jinja_env, context=context_payload)

    for index, slide in enumerate(pack.slides, start=1):
        slide_slug = _slug_for_slide(slide, index)
        ordinal = f"{index:02d}"

        if slide_filter and not _should_run_slide(slide, only=slide_filter):
            _reuse_existing_assets(
                slide=slide,
                slide_slug=slide_slug,
                ordinal=ordinal,
                pack_root=pack_root,
                output_root=output_root,
                slide_png_map=slide_png_map,
                placeholder_png_map=placeholder_png_map,
            )
            continue

        def _execute_visual(
            *,
            visual_ref: PackVisualRef,
            slide_label: str,
            filters: FiltersType,
            calculate: FiltersType,
            placeholder_id: str | None = None,
            target_map: dict[str, Path],
        ) -> None:
            python_visual: PythonVisualBase | None = None
            visual_path: Path

            if visual_ref.ref:
                visual_path = (pack_path.parent / visual_ref.ref).resolve()
                is_python_visual = visual_path.suffix.lower() == ".py"

                if is_python_visual:
                    python_visual = load_python_visual(visual_path, class_name=None)
                    definition = python_visual.to_definition()
                    register_visual_pipeline(PYTHON_VISUAL_TYPE, definition, overwrite=True)
                    visual = python_visual.to_config()
                else:
                    visual = visual_loader(visual_path)
            else:
                visual_path = pack_path
                payload = visual_ref.model_dump()
                payload.pop("ref", None)
                payload.pop("filters", None)
                payload.pop("calculate", None)

                visual = load_visual_from_payload(visual_path, payload, preprocess=True)

                raw_type = payload.get("type")
                is_python_visual = isinstance(raw_type, str) and _is_python_visual_type(raw_type)

                if is_python_visual:
                    module_path = (pack_path.parent / str(raw_type)).resolve()
                    python_visual = load_python_visual(module_path, class_name=None)
                    register_visual_pipeline(PYTHON_VISUAL_TYPE, python_visual.to_definition(), overwrite=True)

            merged_filters = merge_odata_filters(rendered_global_filters, _render_filters(filters))
            calculate_filters = merge_calculate_filters(rendered_global_calculate, _render_filters(calculate))

            artifact_label = f"[{ordinal}]_{slide_label}"
            logger.info(
                "Processing slide",
                extra={
                    "slide": slide_label,
                    "index": index,
                    "title": slide.title,
                    "visual_ref": visual_ref,
                    "placeholder": placeholder_id,
                },
            )
            logger.debug(
                "Resolved visual",
                extra={"visual_path": str(visual_path), "visual_type": getattr(visual, "type", None)},
            )

            metadata_update: dict[str, object] = {}
            if visual_context_base:
                metadata_update["context"] = visual_context_base

            width_px: int | None = None
            height_px: int | None = None

            template_name = slide.template
            if placeholder_id is not None and template_name:
                geom = template_geometry_by_placeholder.get((template_name, placeholder_id))
                if geom:
                    width_px, height_px = geom.width_px, geom.height_px
            elif template_name:
                geom = template_geometry_by_template.get(template_name)
                if geom:
                    width_px, height_px = geom.width_px, geom.height_px

            base_meta = base.metadata or {}
            if width_px is not None and "width" not in base_meta:
                metadata_update.setdefault("width", width_px)
            if height_px is not None and "height" not in base_meta:
                metadata_update.setdefault("height", height_px)
            options, slide_dir = _prepare_slide_options(
                base,
                slide_slug=artifact_label,
                artefact_root=output_root,
                metadata_update=metadata_update,
                png_scale=base.png_scale,
            )

            if visual.type == "powerbi":
                if merged_filters:
                    options.metadata["powerbi_filters"] = merged_filters
                options.metadata.setdefault("build_artifacts_dir", slide_dir / "pbi_exports")

            if calculate_filters or rendered_define:
                existing_context = options.metadata.get("context") if isinstance(options.metadata, dict) else {}
                merged_context = merge_context_payload(
                    base=existing_context if isinstance(existing_context, Mapping) else {},
                    calculate=calculate_filters,
                    define=rendered_define,
                )
                options.metadata["context"] = merged_context
                logger.debug(
                    "Applied context to slide",
                    extra={
                        "slide": slide_label,
                        "calculate_count": len(calculate_filters) if calculate_filters else 0,
                        "has_define": bool(rendered_define),
                    },
                )

            if is_python_visual and python_visual is not None:
                visual_context = _instantiate_python_visual_context(
                    visual=python_visual,
                    metadata=options.metadata,
                )
            else:
                registration = get_visual_registration(visual.type)
                visual_context = _instantiate_slide_context(
                    registration=registration,
                    metadata=options.metadata,
                    project_root=pack_path.parent,
                )

            execution_context = ExecutionContext(
                config_path=visual_path,
                project_root=pack_path.parent,
                case_key=slide_label,
                options=options,
                visual_context=visual_context,
            )

            if visual.type == "powerbi":
                powerbi_queue.enqueue(
                    PowerBIExportJob(
                        slide_index=index,
                        slide_slug=slide_label,
                        slide_title=slide.title,
                        slide=slide,
                        visual=visual,
                        visual_path=visual_path,
                        execution_context=execution_context,
                    )
                )
                return

            try:
                logger.debug(
                    "Executing pipeline",
                    extra={
                        "slide": slide_label,
                        "visual_type": getattr(visual, "type", None),
                        "odata_filter_keys": sorted(merged_filters.keys()) if isinstance(merged_filters, Mapping) else None,
                        "calculate_count": len(calculate_filters) if calculate_filters else 0,
                        "png_target": str(options.outputs[0].path) if options.outputs else None,
                        "artefact_dir": str(options.artefact_dir) if options.artefact_dir else None,
                    },
                )
                result = resolved_pipeline.execute(visual, execution_context)
            except Exception:
                logger.exception(
                    "Slide failed",
                    extra={
                        "slide": slide_label,
                        "visual_ref": visual_ref,
                        "visual_path": str(visual_path),
                    },
                )
                raise
            png_path = _select_png_output(result, options.outputs)
            logger.info(
                "Slide completed",
                extra={
                    "slide": slide_label,
                    "visual_type": getattr(visual, "type", None),
                    "png_path": str(png_path) if png_path else None,
                    "artefact_dir": str(slide_dir),
                },
            )

            if png_path:
                target_map[slide_label] = png_path

            ordered_results.append(
                (
                    index,
                    PackSlideResult(
                        slide=slide,
                        visual_path=visual_path,
                        result=result,
                        png_path=png_path,
                    ),
                )
            )

        if slide.visual is not None:
            _execute_visual(
                visual_ref=slide.visual,
                slide_label=slide_slug,
                filters=slide.visual.filters,
                calculate=slide.visual.calculate,
                target_map=slide_png_map,
            )

        if slide.placeholders:
            placeholder_map = placeholder_png_map.setdefault(slide_slug, {})
            for placeholder_id, placeholder in slide.placeholders.items():
                placeholder_slug = f"{slide_slug}__{slugify(placeholder_id)}"
                if placeholder.image:
                    image_path = (pack_root / placeholder.image).expanduser().resolve(strict=False)
                    if not image_path.exists():
                        raise ValueError(
                            f"Static placeholder image not found for '{placeholder_id}' on slide '{slide_slug}': {image_path}"
                        )
                    placeholder_map[placeholder_slug] = image_path
                    continue

                if placeholder.visual is None:
                    raise ValueError(f"Placeholder '{placeholder_id}' on slide '{slide_slug}' is missing both visual and image")

                _execute_visual(
                    visual_ref=placeholder.visual,
                    slide_label=placeholder_slug,
                    filters=placeholder.visual.filters,
                    calculate=placeholder.visual.calculate,
                    placeholder_id=placeholder_id,
                    target_map=placeholder_map,
                )

    for index, slide in enumerate(pack.slides, start=1):
        slide_slug = _slug_for_slide(slide, index)
        if slide_slug in slide_png_map:
            continue
        if not slide.image:
            continue
        image_path = (pack_root / slide.image).expanduser().resolve(strict=False)
        if not image_path.exists():
            raise ValueError(f"Static slide image not found for '{slide_slug}': {image_path}")
        slide_png_map[slide_slug] = image_path

    powerbi_results = powerbi_queue.drain()
    failed_powerbi = [item for item in powerbi_results if item.exception]
    for item in powerbi_results:
        if item.result is None:
            continue
        png_path = _select_png_output(item.result, item.job.execution_context.options.outputs)
        if png_path:
            slide_slug = item.job.slide_slug
            if "__" in slide_slug:
                parent = slide_slug.split("__", 1)[0]
                placeholder_map = placeholder_png_map.setdefault(parent, {})
                placeholder_map[slide_slug] = png_path
            else:
                slide_png_map[slide_slug] = png_path
        ordered_results.append(
            (
                item.job.slide_index,
                PackSlideResult(
                    slide=item.job.slide,
                    visual_path=item.job.visual_path,
                    result=item.result,
                    png_path=png_path,
                ),
            )
        )

    ordered_results.sort(key=lambda pair: pair[0])
    sorted_results = [item[1] for item in ordered_results]

    if failed_powerbi:
        failed_slides = [item.job.slide_slug for item in failed_powerbi]
        logger.error(
            "Power BI slides failed",
            extra={"failed_slide_count": len(failed_slides), "failed_slides": failed_slides},
        )
        summary = _format_powerbi_failure_summary(failed_powerbi)
        raise PackPowerBIFailure(
            summary,
            successful_results=sorted_results,
            failed_exports=failed_powerbi,
        )

    raw_result_file = base.metadata.get("result_file") if base.metadata else None
    result_file: Path | None = None
    if isinstance(raw_result_file, (str, Path)):
        result_file = Path(raw_result_file)
    elif raw_result_file is not None:
        logger.warning(
            "Skipping PPTX assembly because result_file metadata is not path-like",
            extra={"pack": str(pack_path), "result_file_type": type(raw_result_file).__name__},
        )

    if result_file:
        raw_template = base.metadata.get("pptx_template") if base.metadata else None
        if isinstance(raw_template, (str, Path)):
            template_path: Path | None = Path(raw_template)
        else:
            if raw_template is not None:
                logger.warning(
                    "Ignoring pptx_template metadata because it is not path-like",
                    extra={"pack": str(pack_path), "template_type": type(raw_template).__name__},
                )
            template_path = _resolve_default_template(pack_path)

        if template_path is None:
            logger.warning(
                "Skipping PPTX assembly because no template was found",
                extra={"pack": str(pack_path), "result_file": str(result_file)},
            )
        else:
            try:
                assemble_pack_pptx(
                    pack=pack,
                    results=sorted_results,
                    slide_pngs=slide_png_map,
                    placeholder_pngs=placeholder_png_map,
                    result_path=result_file,
                    template_path=template_path,
                )
            except Exception:
                logger.exception("PPTX assembly failed", extra={"result_file": str(result_file)})
                raise

    return sorted_results


def restitch_pack_pptx(
    pack_path: Path,
    pack: PackConfig,
    *,
    output_root: Path,
    result_file: Path,
    base_options: PipelineOptions,
) -> None:
    """Rebuild a pack PPTX using existing artefacts and static images."""

    output_root.mkdir(parents=True, exist_ok=True)
    result_file.parent.mkdir(parents=True, exist_ok=True)

    # Align slide metadata with full runs so slug calculation matches previously
    # rendered artefacts when titles/notes use Jinja placeholders.
    jinja_env = create_pack_jinja_env()
    context_payload: dict[str, object] = dict(pack.context or {})
    _render_slide_metadata(pack=pack, env=jinja_env, context=context_payload)

    slide_png_map: dict[str, Path] = {}
    placeholder_png_map: dict[str, dict[str, Path]] = {}
    pack_root = pack_path.parent

    for index, slide in enumerate(pack.slides, start=1):
        slide_slug = _slug_for_slide(slide, index)
        ordinal = f"{index:02d}"

        _reuse_existing_assets(
            slide=slide,
            slide_slug=slide_slug,
            ordinal=ordinal,
            pack_root=pack_root,
            output_root=output_root,
            slide_png_map=slide_png_map,
            placeholder_png_map=placeholder_png_map,
        )

    template_override = base_options.metadata.get("pptx_template") if base_options.metadata else None
    if isinstance(template_override, (str, Path)):
        template_path: Path | None = Path(template_override)
    else:
        if template_override is not None:
            logger.warning(
                "Ignoring pptx_template metadata because it is not path-like",
                extra={"pack": str(pack_path), "template_type": type(template_override).__name__},
            )
        template_path = _resolve_default_template(pack_path)
    if template_path is None:
        logger.warning(
            "Skipping PPTX assembly because no template was found",
            extra={"pack": str(pack_path), "result_file": str(result_file)},
        )
        return

    assemble_pack_pptx(
        pack=pack,
        results=[],
        slide_pngs=slide_png_map,
        placeholder_pngs=placeholder_png_map,
        result_path=result_file,
        template_path=template_path,
    )


__all__ = ["PackPowerBIFailure", "PackSlideResult", "run_pack"]

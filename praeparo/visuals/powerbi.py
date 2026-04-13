"""Power BI export-backed visual registration."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, Tuple, cast

import logging

from praeparo.models import BaseVisualConfig, PowerBIVisualConfig
from praeparo.powerbi import (
    PowerBIClient,
    PowerBIExportDefaults,
    PowerBISettings,
    extract_png_from_pptx_export,
)
from praeparo.pipeline import ExecutionContext, VisualPipeline
from praeparo.pipeline.outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from praeparo.pipeline.registry import (
    DatasetArtifact,
    RenderOutcome,
    SchemaArtifact,
    VisualPipelineDefinition,
    default_json_writer,
    register_visual_pipeline,
)
from praeparo.visuals.context_models import VisualContextModel
from praeparo.visuals.dax.planner_core import slugify
from praeparo.visuals.registry import register_visual_schema, register_visual_type


def _load_powerbi_visual(path: Path, payload: Mapping[str, object], stack: Tuple[Path, ...]) -> PowerBIVisualConfig:
    return PowerBIVisualConfig.model_validate(payload)


logger = logging.getLogger(__name__)


def _normalise_filters(filters: Mapping[str, str] | Sequence[str] | None) -> list[str]:
    if not filters:
        return []
    if isinstance(filters, Mapping):
        return [str(v) for v in filters.values() if v]
    return [str(v) for v in filters if v]


def _merge_filters(
    inherited: Mapping[str, str] | Sequence[str] | None,
    local: Mapping[str, str] | Sequence[str] | None,
    strategy: str,
) -> list[str]:
    # Mirror governance pack semantics: merge by default, or allow wholesale replace.
    if strategy == "replace":
        return _normalise_filters(local)
    inherited_list = _normalise_filters(inherited)
    local_list = _normalise_filters(local)
    return [*inherited_list, *local_list]


def _build_export_payload(
    config: PowerBIVisualConfig,
    filters: Sequence[str],
    *,
    format: str,
) -> dict[str, object]:
    """Shape the ExportTo payload for the chosen mode/format."""
    fmt = format.upper()
    if config.mode == "paginated":
        paginated_configuration: dict[str, object] = {}
        payload: dict[str, object] = {"format": fmt, "paginatedReportConfiguration": paginated_configuration}
        if config.parameters:
            paginated_configuration["parameterValues"] = [
                {"name": p.name, "value": p.value} for p in config.parameters
            ]
        return payload

    report_configuration: dict[str, object] = {}
    payload: dict[str, object] = {"format": fmt, "powerBIReportConfiguration": report_configuration}
    if config.source.page:
        report_configuration["pages"] = [{"pageName": config.source.page}]
    if config.mode == "visual" and config.source.visual_id:
        report_configuration["visuals"] = [
            {"visualName": config.source.visual_id, "pageName": config.source.page}
        ]
    if filters:
        report_configuration["reportLevelFilters"] = [
            {"filter": " and ".join(filters)}
        ]
    return payload


def _default_export_paths(config: PowerBIVisualConfig, context) -> tuple[Path, Path]:
    """Pick deterministic output paths for the primary export and its JSON metadata.

    We keep everything under `.tmp/pbi_exports` by default so repeated renders
    land in a predictable location that downstream pack builders can reference.
    """
    # Prefer a standard build artifacts directory when provided; otherwise default.
    base_dir = context.options.metadata.get("build_artifacts_dir") or ".tmp/pbi_exports"

    base = Path(base_dir)
    visual_slug = slugify(config.title or config.description or "powerbi")

    # If the visual came from a file, bake that into the slug to avoid collisions
    # when multiple definitions share the same title.
    if context.config_path:
        visual_slug = slugify(f"{context.config_path.stem}_{visual_slug}")

    # Build a stem that stays readable: report id + page name when present.
    stem = f"{visual_slug}_{config.source.report_id}"
    if config.source.page:
        stem = f"{stem}_{slugify(config.source.page)}"

    base.mkdir(parents=True, exist_ok=True)
    main_path = base / f"{stem}.{config.render.format}"

    # Keep the manifest filename stable while avoiding collisions when multiple visuals export
    # into the same build-artifacts directory.
    manifest_dir = base / stem
    manifest_dir.mkdir(parents=True, exist_ok=True)
    data_path = manifest_dir / "data.json"
    return main_path, data_path


@dataclass
class PowerBIExportDataset:
    """Recorded artifacts for a rendered Power BI visual."""

    mode: str
    format: str
    export_path: str
    pptx_path: str | None
    image_path: str | None
    export_payload: dict[str, object]
    artifacts: dict[str, str]
    filters: list[str]


def _powerbi_schema_builder(
    pipeline: VisualPipeline[VisualContextModel],
    config: BaseVisualConfig,
    context: ExecutionContext[VisualContextModel],
) -> SchemaArtifact[dict]:
    if not isinstance(config, PowerBIVisualConfig):
        raise TypeError("Power BI pipeline expects a PowerBIVisualConfig instance.")
    return SchemaArtifact(value=config.model_dump(), filename="schema.json")


def _powerbi_dataset_builder(
    pipeline: VisualPipeline[VisualContextModel],
    config: BaseVisualConfig,
    schema: SchemaArtifact[dict],
    context: ExecutionContext[VisualContextModel],
) -> DatasetArtifact[PowerBIExportDataset]:
    if not isinstance(config, PowerBIVisualConfig):
        raise TypeError("Power BI pipeline expects a PowerBIVisualConfig instance.")

    # Start by merging any pack-level filters with the visual's own filters.
    raw_filters = context.options.metadata.get("powerbi_filters") if isinstance(context.options.metadata, dict) else None
    inherited_filters = cast(Mapping[str, str] | Sequence[str] | None, raw_filters)
    merged_filters = _merge_filters(inherited_filters, config.filters, config.filters_merge_strategy)

    # Resolve output defaults once so the export request, polling cadence, and
    # post-processing all honour the same `.env`-driven runtime knobs.
    export_defaults = PowerBIExportDefaults.from_env()

    # Decide where the primary export and its JSON manifest will land.
    main_path, data_path = _default_export_paths(config, context)
    logger.info(
        "Starting Power BI export",
        extra={
            "title": config.title or config.description,
            "mode": config.mode,
            "format": config.render.format,
            "report_id": config.source.report_id,
            "page": config.source.page,
            "visual_id": config.source.visual_id,
            "filter_count": len(merged_filters),
            "export_path": str(main_path),
            "manifest_path": str(data_path),
        },
    )

    settings = PowerBISettings.from_env()
    export_payload = _build_export_payload(config, merged_filters, format=config.render.format)

    async def _run_exports() -> tuple[str, str | None, dict[str, str]]:
        artifacts: dict[str, str] = {}
        async with PowerBIClient(settings) as client:
            # Kick off the primary export first so every downstream sidecar uses the
            # exact same payload, timeout budget, and artifact naming convention.
            main_export = await client.export_to_file(
                group_id=config.source.group_id,
                report_id=config.source.report_id,
                payload=export_payload,
                dest_path=main_path,
                mode=config.mode,
                poll_interval=export_defaults.poll_interval,
                timeout=export_defaults.timeout,
            )

            if config.mode == "paginated":
                # Emit additional paginated sidecars (PDF/XLSX/CSV) when requested.
                for fmt in config.export_formats:
                    if fmt == config.render.format:
                        artifacts[fmt] = str(main_export)
                        continue
                    alt_payload = _build_export_payload(config, merged_filters, format=fmt)
                    alt_path = main_path.with_suffix(f".{fmt}")
                    artifacts[fmt] = await client.export_to_file(
                        group_id=config.source.group_id,
                        report_id=config.source.report_id,
                        payload=alt_payload,
                        dest_path=alt_path,
                        mode=config.mode,
                        poll_interval=export_defaults.poll_interval,
                        timeout=export_defaults.timeout,
                    )

        # When the primary export is PPTX, extract the visual image so pack runs
        # can keep consuming PNG slide assets while still retaining the source deck.
        image_path = _maybe_extract_pptx_image(
            export_path=Path(main_export),
            stitch_slides=config.render.stitch_slides,
        )
        return str(main_export), image_path, artifacts

    try:
        export_path, image_path, artifacts = asyncio.run(_run_exports())
    except Exception:
        logger.exception(
            "Power BI export failed",
            extra={
                "report_id": config.source.report_id,
                "page": config.source.page,
                "visual_id": config.source.visual_id,
                "export_path": str(main_path),
            },
        )
        raise

    logger.info(
        "Power BI export completed",
        extra={
            "export_path": export_path,
            "image_path": image_path,
            "artifact_count": len(artifacts),
            "artifact_keys": sorted(artifacts.keys()),
        },
    )

    export_file = Path(export_path)
    dataset = PowerBIExportDataset(
        mode=config.mode,
        format=config.render.format,
        export_path=export_path,
        pptx_path=export_path if export_file.suffix.lower() == ".pptx" else None,
        image_path=image_path if image_path is not None else export_path if export_file.suffix.lower() == ".png" else None,
        export_payload=export_payload,
        artifacts=artifacts,
        filters=merged_filters,
    )

    return DatasetArtifact(
        value=dataset,
        filename=data_path.name,
        writer=default_json_writer,
        plans=(),
    )


def _powerbi_renderer(
    pipeline: VisualPipeline[VisualContextModel],
    config: BaseVisualConfig,
    schema: SchemaArtifact[dict],
    dataset: DatasetArtifact[PowerBIExportDataset],
    context: ExecutionContext[VisualContextModel],
    outputs: Sequence[OutputTarget],
) -> RenderOutcome:
    if not isinstance(config, PowerBIVisualConfig):
        raise TypeError("Power BI pipeline expects a PowerBIVisualConfig instance.")
    outcome = RenderOutcome()
    image_path = Path(dataset.value.image_path) if dataset.value.image_path else None

    for target in outputs:
        if target.kind != OutputKind.PNG:
            continue
        if image_path is None or not image_path.exists():
            raise RuntimeError("Power BI visual did not produce a PNG image.")
        # Copy the rendered PNG into the caller's requested location.
        target.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image_path, target.path)
        outcome.outputs.append(PipelineOutputArtifact(kind=OutputKind.PNG, path=target.path))
        logger.info(
            "Copied Power BI PNG",
            extra={"source": str(image_path), "target": str(target.path)},
        )

    return outcome


def _maybe_extract_pptx_image(*, export_path: Path, stitch_slides: bool) -> str | None:
    """Create a PNG sidecar when the primary export is a PPTX deck."""

    if export_path.suffix.lower() != ".pptx":
        return None

    # Keep the PNG beside the source deck so pack runs and manual inspection
    # can reuse the exact same Power BI export artefacts.
    png_path = export_path.with_suffix(".png")
    extracted = extract_png_from_pptx_export(
        export_path,
        dest_path=png_path,
        stitch_slides=stitch_slides,
    )
    return str(extracted)


register_visual_type("powerbi", _load_powerbi_visual, overwrite=True)
register_visual_schema("powerbi", PowerBIVisualConfig.model_json_schema, overwrite=True)
register_visual_pipeline(
    "powerbi",
    VisualPipelineDefinition[dict, PowerBIExportDataset, BaseVisualConfig, VisualContextModel](
        schema_builder=_powerbi_schema_builder,
        dataset_builder=_powerbi_dataset_builder,
        renderer=_powerbi_renderer,
    ),
    overwrite=True,
)

__all__ = []

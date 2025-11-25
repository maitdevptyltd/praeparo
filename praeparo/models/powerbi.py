"""Pydantic models for Power BI export-backed visuals."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .visual_base import BaseVisualConfig


PowerBIVisualMode = Literal["report", "visual", "paginated"]
PowerBIFilterMergeStrategy = Literal["merge", "replace"]
PowerBIExportFormat = Literal["png", "pptx", "pdf"]
PowerBIPaginatedArtifact = Literal["pptx", "pdf", "xlsx", "csv"]


class PowerBISource(BaseModel):
    """Identifiers that locate the Power BI asset."""

    group_id: str = Field(..., description="Power BI workspace (group) identifier.")
    report_id: str = Field(..., description="Power BI report or paginated report identifier.")
    page: str | None = Field(
        default=None,
        description="Power BI page name (required for report/visual modes).",
    )
    visual_id: str | None = Field(
        default=None,
        description="Optional target visual id (only when mode=visual).",
    )


class PowerBIParameter(BaseModel):
    """Parameter supplied to a paginated report export."""

    name: str
    value: str


class PowerBIRenderOptions(BaseModel):
    """Controls how the exported asset is materialised on disk."""

    format: PowerBIExportFormat = Field(
        default="png",
        description="Primary export format requested from Power BI.",
    )
    stitch_slides: bool = Field(
        default=True,
        description="Placeholder for future slide stitching (no-op for PNG).",
    )
    max_concurrency: int | None = Field(
        default=None,
        description="Optional per-visual concurrency cap (currently unused).",
    )


class PowerBIVisualConfig(BaseVisualConfig):
    """Declarative configuration for exporting a Power BI asset."""

    type: Literal["powerbi"] = "powerbi"
    mode: PowerBIVisualMode = Field(
        default="report",
        description="Export flavour: whole report page, single visual, or paginated.",
    )
    source: PowerBISource
    filters: dict[str, str] | list[str] = Field(
        default_factory=list,
        description="OData filters applied at export time.",
    )
    filters_merge_strategy: PowerBIFilterMergeStrategy = Field(
        default="merge",
        description="How to combine inherited filters with local ones.",
    )
    parameters: list[PowerBIParameter] = Field(
        default_factory=list,
        description="Parameter values for paginated reports.",
    )
    export_formats: list[PowerBIPaginatedArtifact] = Field(
        default_factory=lambda: ["xlsx"],
        description="Additional artifacts to emit for paginated exports.",
    )
    render: PowerBIRenderOptions = Field(
        default_factory=PowerBIRenderOptions,
        description="Render-time options for the exported asset.",
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: PowerBISource, info):
        mode: PowerBIVisualMode = info.data.get("mode", "report")  # type: ignore[arg-type]
        if mode in {"report", "visual"} and not value.page:
            raise ValueError("source.page is required when mode is 'report' or 'visual'.")
        if mode == "visual" and not value.visual_id:
            raise ValueError("source.visual_id is required when mode is 'visual'.")
        return value

    @field_validator("export_formats")
    @classmethod
    def _validate_export_formats(cls, value: list[PowerBIPaginatedArtifact], info):
        mode: PowerBIVisualMode = info.data.get("mode", "report")  # type: ignore[arg-type]
        if mode != "paginated" and value:
            # Non-paginated exports ignore additional formats; keep the list but warn via docs.
            return value
        cleaned: list[PowerBIPaginatedArtifact] = []
        seen: set[str] = set()
        for fmt in value:
            if fmt in seen:
                continue
            cleaned.append(fmt)
            seen.add(fmt)
        return cleaned


__all__ = [
    "PowerBIExportFormat",
    "PowerBIFilterMergeStrategy",
    "PowerBIParameter",
    "PowerBIRenderOptions",
    "PowerBISource",
    "PowerBIVisualConfig",
    "PowerBIVisualMode",
    "PowerBIPaginatedArtifact",
]

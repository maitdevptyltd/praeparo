"""Pack evidence export configuration.

This model defines an opt-in surface for pack authors to request that the pack
runner exports `praeparo-metrics explain` evidence for selected visual bindings.

The runner is intentionally generic: bindings are selected by the presence of
adapter-supplied metadata keys (for example `sla`), not by upstream knowledge
of any one domain.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PackEvidenceExplainConfig(BaseModel):
    """Controls how evidence queries are planned and executed."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    limit: int = Field(default=50000, ge=1, description="Maximum rows to export for each evidence query.")
    variant_mode: Literal["flag", "filter"] = Field(
        default="flag",
        description="Variant handling mode (matches praeparo-metrics explain).",
    )
    max_concurrency: int = Field(
        default=1,
        ge=1,
        description="Maximum concurrent evidence exports (bounded to avoid overload).",
    )
    skip_existing: bool = Field(
        default=True,
        description="Skip evidence exports when a prior matching fingerprint is present in manifest.json.",
    )


class PackEvidenceBindingsConfig(BaseModel):
    """Binding selection rules for evidence exports."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    select: list[str] = Field(
        default_factory=list,
        description="Attribute keys that must exist in binding.metadata for selection.",
    )
    select_mode: Literal["all", "any"] = Field(
        default="all",
        description="Whether all select keys must exist (all) or any one (any).",
    )
    include: list[str] = Field(
        default_factory=list,
        description="Binding IDs to force-include (unioned after select filtering).",
    )
    exclude: list[str] = Field(
        default_factory=list,
        description="Binding IDs to force-exclude (removed after include union).",
    )

    @field_validator("select", "include", "exclude", mode="before")
    @classmethod
    def _normalise_non_empty_strings(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                raise ValueError("selector entries cannot be empty.")
            return [candidate]
        if isinstance(value, list):
            cleaned: list[str] = []
            for entry in value:
                if not isinstance(entry, str):
                    raise TypeError("selector entries must be strings.")
                candidate = entry.strip()
                if not candidate:
                    raise ValueError("selector entries cannot be empty.")
                cleaned.append(candidate)
            return cleaned
        raise TypeError("selector entries must be a string or list of strings.")


class PackEvidenceConfig(BaseModel):
    """Pack-level evidence export configuration.

    When enabled, the pack runner exports `praeparo-metrics explain` artefacts for
    selected visual bindings after slide execution completes.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enabled: bool = Field(default=False, description="Whether evidence exports run for this pack.")
    output_dir: str = Field(
        default="_evidence",
        description="Directory under the pack artefact dir to store evidence exports (supports Jinja templates).",
    )
    when: Literal["pack_complete", "always"] = Field(
        default="pack_complete",
        description="When to execute evidence exports relative to the pack lifecycle.",
    )
    on_error: Literal["fail", "warn"] = Field(
        default="fail",
        description="Whether evidence failures fail the pack run (fail) or are recorded as warnings (warn).",
    )
    explain: PackEvidenceExplainConfig = Field(
        default_factory=PackEvidenceExplainConfig,
        description="Evidence execution options mirroring praeparo-metrics explain.",
    )
    bindings: PackEvidenceBindingsConfig = Field(
        default_factory=PackEvidenceBindingsConfig,
        description="Binding selection rules for evidence exports.",
    )

    @field_validator("output_dir")
    @classmethod
    def _normalise_output_dir(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("output_dir cannot be empty.")
        return candidate


__all__ = ["PackEvidenceBindingsConfig", "PackEvidenceConfig", "PackEvidenceExplainConfig"]


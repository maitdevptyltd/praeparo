"""Pydantic models describing pack definitions.

Phase 6 adds declarative metric bindings under `context.metrics` at both the pack root
and per-slide. These bindings are normalised and validated here so pack runs fail
fast before any Power BI or PPTX work begins.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from praeparo.visuals.metrics import normalise_str_sequence


FiltersType = str | Sequence[str] | Mapping[str, str] | None


_JINJA_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PackMetricBinding(BaseModel):
    """Binding describing how a metric value becomes a Jinja variable.

    Bindings may reference a catalogue metric (`key` + optional `variant`) or declare an
    arithmetic `expression` over other metrics/aliases. When `alias` is omitted it is
    derived from the full metric key by replacing dots with underscores.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str | None = Field(
        default=None,
        description="Catalogue metric key (e.g., documents_verified) or dotted variant key.",
    )
    alias: str | None = Field(
        default=None,
        description="Jinja-safe variable name exposed to templates.",
    )
    variant: str | None = Field(
        default=None,
        description="Optional variant path appended to `key` when `key` is not dotted.",
    )
    calculate: list[str] = Field(
        default_factory=list,
        description="Optional extra DAX CALCULATE predicates for this binding.",
    )
    format: str | None = Field(
        default=None,
        description="Optional formatting hint mirroring Praeparo format tokens.",
    )
    expression: str | None = Field(
        default=None,
        description="Optional arithmetic expression referencing metric keys or aliases.",
    )
    override: bool = Field(
        default=False,
        description="True when intentionally shadowing an inherited alias.",
    )

    _normalise_calculate = field_validator("calculate", mode="before")(normalise_str_sequence)

    @field_validator("key", "alias", "variant", "format", "expression", mode="before")
    @classmethod
    def _normalise_strings(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("must be a string")
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _apply_defaults_and_validate(self) -> "PackMetricBinding":
        if not self.key and not self.expression:
            raise ValueError("metric binding requires either 'key' or 'expression'")

        if self.variant:
            if not self.key:
                raise ValueError("variant requires a base key")
            if "." in self.key:
                raise ValueError("variant cannot be supplied when key is already dotted")

        full_key = self.full_key

        if not self.alias:
            if full_key:
                self.alias = full_key.replace(".", "_")
            elif self.expression:
                raise ValueError("alias is required for expression-only bindings")

        if not self.alias or not _JINJA_ALIAS_PATTERN.match(self.alias):
            raise ValueError(
                f"Invalid alias '{self.alias}'. Aliases must be valid Jinja identifiers."
            )

        return self

    @property
    def full_key(self) -> str | None:
        """Return the fully qualified metric key including variant."""

        if not self.key:
            return None
        if self.variant:
            return f"{self.key}.{self.variant}"
        return self.key

    def signature(self) -> tuple[str | None, tuple[str, ...], str | None, str | None]:
        """Return a hashable signature used for reuse checks."""

        calculate_sig = tuple(sorted(set(self.calculate or [])))
        return (self.full_key, calculate_sig, self.format, self.expression)


class PackContext(BaseModel):
    """Context payload shared by slides.

    Extra keys are allowed so packs can continue to pass arbitrary template values.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    metrics: list[PackMetricBinding] | None = Field(
        default=None,
        description="Optional metric bindings resolved into Jinja variables.",
    )

    @field_validator("metrics", mode="before")
    @classmethod
    def _normalise_metrics(cls, value: object) -> list[PackMetricBinding] | None:
        if value is None:
            return None

        if isinstance(value, Mapping):
            bindings: list[PackMetricBinding] = []
            for raw_key, raw_alias in value.items():
                metric_key = str(raw_key).strip()
                if not metric_key:
                    raise ValueError("metrics mapping keys cannot be empty")
                if raw_alias is None:
                    bindings.append(PackMetricBinding(key=metric_key))
                elif isinstance(raw_alias, str):
                    bindings.append(PackMetricBinding(key=metric_key, alias=raw_alias))
                else:
                    raise TypeError("metrics mapping values must be strings")
            return bindings or None

        if isinstance(value, Sequence) and not isinstance(value, str):
            bindings = []
            for item in value:
                if isinstance(item, PackMetricBinding):
                    bindings.append(item)
                elif isinstance(item, str):
                    bindings.append(PackMetricBinding(key=item))
                elif isinstance(item, Mapping):
                    bindings.append(PackMetricBinding.model_validate(item))
                else:
                    raise TypeError("metrics list entries must be strings or binding objects")
            return bindings or None

        raise TypeError("metrics must be a mapping or list")

    @model_validator(mode="after")
    def _validate_unique_aliases(self) -> "PackContext":
        if not self.metrics:
            return self

        seen: set[str] = set()
        duplicates: set[str] = set()
        for binding in self.metrics:
            alias = binding.alias or ""
            if alias in seen:
                duplicates.add(alias)
            else:
                seen.add(alias)

        if duplicates:
            dup_list = ", ".join(sorted(duplicates))
            raise ValueError(f"context.metrics defines duplicate aliases: {dup_list}")

        return self


class PackSlideContext(PackContext):
    """Context payload specific to an individual slide."""


class PackVisualRef(BaseModel):
    """Reference to a visual or an inline visual config plus optional slide-level overrides."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ref: str | None = Field(
        default=None,
        description="Optional path to the visual definition relative to the pack file.",
    )
    type: str | None = Field(
        default=None,
        description="Optional inline visual type or Python module path when embedding a config directly.",
    )
    filters: FiltersType = Field(
        default=None,
        description="Optional OData filters applied on top of pack-level defaults.",
    )
    calculate: FiltersType = Field(
        default=None,
        description="Optional DAX filters applied on top of pack-level defaults.",
    )

    @field_validator("ref")
    @classmethod
    def _normalise_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            msg = "visual.ref cannot be empty"
            raise ValueError(msg)
        return cleaned

    @model_validator(mode="after")
    def _validate_ref_or_type(self) -> "PackVisualRef":
        has_ref = bool(self.ref)
        has_type = bool(self.type)
        if has_ref == has_type:
            raise ValueError("visual must define exactly one of 'ref' or 'type'")
        return self


class PackPlaceholder(BaseModel):
    """Placeholder binding used by PPTX assembly."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    visual: PackVisualRef | None = Field(
        default=None,
        description="Visual rendered for this placeholder.",
    )
    image: str | None = Field(
        default=None,
        description="Optional static image path for this placeholder, relative to the pack file.",
    )
    text: str | list[str] | None = Field(
        default=None,
        description="Plain text (optionally templated) injected into a named text shape.",
    )

    @field_validator("image")
    @classmethod
    def _normalise_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("text")
    @classmethod
    def _normalise_text(cls, value: str | list[str] | None) -> str | list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        cleaned_items = [item.strip() for item in value if item and item.strip()]
        return cleaned_items or None

    @model_validator(mode="after")
    def _validate_exclusive_binding(self) -> "PackPlaceholder":
        has_visual = self.visual is not None
        has_image = bool(self.image)
        has_text = bool(self.text)

        if (has_visual + has_image + has_text) != 1:
            msg = "placeholder must define exactly one of visual, image, or text"
            raise ValueError(msg)
        return self


class PackSlide(BaseModel):
    """Single slide within a pack."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str = Field(..., description="Human-friendly slide title.")
    id: str | None = Field(default=None, description="Optional stable identifier for the slide.")
    context: PackSlideContext | None = Field(
        default=None,
        description="Optional template context merged with the pack-level context.",
    )
    notes: str | None = Field(default=None, description="Free-form notes for authors/reviewers.")
    visual: PackVisualRef | None = Field(
        default=None,
        description="Optional visual reference; absent for non-visual slides.",
    )
    template: str | None = Field(
        default=None,
        description="Optional PPTX template identifier (TEMPLATE_TAG) used during deck assembly.",
    )
    placeholders: dict[str, PackPlaceholder] | None = Field(
        default=None,
        description="Optional placeholder map when a slide template contains multiple picture placeholders.",
    )
    image: str | None = Field(
        default=None,
        description="Optional static image path when using a PPTX template without a visual.",
    )

    @field_validator("title")
    @classmethod
    def _normalise_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "title cannot be empty"
            raise ValueError(msg)
        return cleaned

    @field_validator("id")
    @classmethod
    def _normalise_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("image")
    @classmethod
    def _normalise_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("placeholders", mode="before")
    @classmethod
    def _normalise_placeholders(
        cls, value: object
    ) -> dict[str, PackPlaceholder] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            msg = "placeholders must be a mapping"
            raise TypeError(msg)

        normalised: dict[str, PackPlaceholder] = {}
        for placeholder_id, raw in value.items():
            if isinstance(raw, PackPlaceholder):
                normalised[str(placeholder_id)] = raw
                continue

            if isinstance(raw, str):
                placeholder = _placeholder_from_shorthand(raw)
                normalised[str(placeholder_id)] = placeholder
                continue

            if isinstance(raw, Mapping):
                placeholder = PackPlaceholder.model_validate(raw)
                normalised[str(placeholder_id)] = placeholder
                continue

            msg = f"Invalid placeholder value for '{placeholder_id}'"
            raise TypeError(msg)

        return normalised

    @model_validator(mode="after")
    def _validate_image_with_visual_and_template(self) -> "PackSlide":
        if self.image and self.visual is not None:
            msg = "slide cannot define both visual and image"
            raise ValueError(msg)
        if self.image and not self.template:
            msg = "slide-level image requires a template"
            raise ValueError(msg)
        return self


def _placeholder_from_shorthand(value: str) -> PackPlaceholder:
    """Convert string shorthand to a concrete placeholder binding."""

    cleaned = value.strip()
    lower = cleaned.lower()

    is_image = (
        "/" in cleaned
        or "\\" in cleaned
        or lower.endswith(
            (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".bmp",
                ".svg",
                ".webp",
            )
        )
    )

    if is_image:
        return PackPlaceholder(image=cleaned)

    return PackPlaceholder(text=cleaned)


class PackConfig(BaseModel):
    """Root configuration for a pack composed of slides."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())

    schema: str = Field(..., description="Schema or contract identifier for the pack.")
    context: PackContext = Field(default_factory=PackContext, description="Template context shared by slides.")
    define: str | None = Field(
        default=None,
        description="Optional DAX DEFINE block applied to DAX-backed visuals.",
    )
    calculate: FiltersType = Field(
        default=None,
        description="Pack-level DAX filters applied to DAX-backed visuals.",
    )
    filters: FiltersType = Field(
        default=None,
        description="Pack-level OData filters applied to Power BI visuals.",
    )
    slides: list[PackSlide] = Field(default_factory=list, description="Ordered slide definitions.")

    @field_validator("schema")
    @classmethod
    def _normalise_schema(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "schema cannot be empty"
            raise ValueError(msg)
        return cleaned

    @model_validator(mode="after")
    def _validate_slide_metric_overrides(self) -> "PackConfig":
        root_bindings = self.context.metrics or []
        root_by_alias = {binding.alias: binding for binding in root_bindings if binding.alias}

        if not root_by_alias:
            return self

        for slide in self.slides:
            slide_metrics = slide.context.metrics if slide.context else None
            if not slide_metrics:
                continue

            for binding in slide_metrics:
                alias = binding.alias or ""
                root_binding = root_by_alias.get(alias)
                if root_binding is None:
                    continue
                if binding.override:
                    continue
                if binding.signature() == root_binding.signature():
                    continue
                slide_label = slide.id or slide.title
                raise ValueError(
                    f"Slide '{slide_label}' declares context.metrics alias '{alias}' "
                    "that shadows a root binding; set override: true to override."
                )

        return self


__all__ = [
    "FiltersType",
    "PackConfig",
    "PackContext",
    "PackMetricBinding",
    "PackPlaceholder",
    "PackSlide",
    "PackSlideContext",
    "PackVisualRef",
]

"""Pydantic models describing pack definitions.

Phase 6 adds declarative metric bindings under `context.metrics` at both the pack root
and per-slide. These bindings are normalised and validated here so pack runs fail
fast before any Power BI or PPTX work begins.
"""

from __future__ import annotations

from pathlib import Path
import re
import warnings
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from praeparo.formatting import parse_format_token

from .scoped_calculate import ScopedCalculateFilters, ScopedCalculateMap
from .pack_evidence import PackEvidenceConfig


FiltersType = str | Sequence[str] | Mapping[str, str] | None


_JINJA_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_filter_for_signature(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_filters_for_signature(value: FiltersType) -> tuple[dict[str, str], list[str]]:
    """Split calculate-style filters into named and unlabelled components."""

    named: dict[str, str] = {}
    unlabelled: list[str] = []

    if value is None:
        return named, unlabelled

    if isinstance(value, str):
        candidate = _strip_filter_for_signature(value)
        if candidate:
            unlabelled.append(candidate)
        return named, unlabelled

    if isinstance(value, Mapping):
        for key, raw in value.items():
            candidate = _strip_filter_for_signature(raw)
            if candidate:
                named[str(key)] = candidate
        return named, unlabelled

    if isinstance(value, Sequence):
        for entry in value:
            if isinstance(entry, Mapping):
                for key, raw in entry.items():
                    candidate = _strip_filter_for_signature(raw)
                    if candidate:
                        named[str(key)] = candidate
                continue

            candidate = _strip_filter_for_signature(entry)
            if candidate:
                unlabelled.append(candidate)
        return named, unlabelled

    return named, unlabelled


def _merge_filter_signature(global_filters: FiltersType, local_filters: FiltersType) -> tuple[str, ...]:
    """Return a stable signature for merged global/local calculate filters."""

    global_named, global_unlabelled = _split_filters_for_signature(global_filters)
    local_named, local_unlabelled = _split_filters_for_signature(local_filters)

    merged_named = {**global_named, **local_named}
    merged_unlabelled = [*global_unlabelled, *local_unlabelled]
    combined = [*merged_named.values(), *merged_unlabelled]
    return tuple(sorted(set(combined)))


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
    calculate: ScopedCalculateFilters = Field(
        default_factory=ScopedCalculateFilters,
        description=(
            "Optional DAX CALCULATE predicates for this binding. "
            "Named entries default to DEFINE scope; use calculate.<name>.evaluate to "
            "apply a predicate around the measure in SUMMARIZECOLUMNS."
        ),
    )
    format: str | None = Field(
        default=None,
        description="Optional formatting hint mirroring Praeparo format tokens.",
    )
    ratio_to: bool | str | None = Field(
        default=None,
        description=(
            "Optional ratio semantics for this binding. "
            "`true` ratios against the base metric inferred from the dotted key. "
            "A string value must be a catalogue metric key used as the denominator."
        ),
    )
    expression: str | None = Field(
        default=None,
        description="Optional arithmetic expression referencing metric keys or aliases.",
    )
    override: bool = Field(
        default=False,
        description="True when intentionally shadowing an inherited alias.",
    )

    @field_validator("ratio_to", mode="before")
    @classmethod
    def _normalise_ratio_to(cls, value: object) -> bool | str | None:
        if value is None:
            return None
        if value is False:
            # Treat explicit false as "unset" so templated configs can disable ratio semantics.
            return None
        if value is True:
            return True
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                raise ValueError("ratio_to metric key cannot be empty")
            return candidate
        raise TypeError("ratio_to must be bool, str, or None")

    @field_validator("calculate", mode="before")
    @classmethod
    def _normalise_calculate(cls, value: object) -> ScopedCalculateFilters:
        return ScopedCalculateFilters.from_raw(value)

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

        if self.ratio_to is not None:
            if self.expression:
                raise ValueError("ratio_to is not supported for expression bindings yet")
            if not self.full_key:
                raise ValueError("ratio_to requires a metric key")
            if self.ratio_to is True and "." not in self.full_key:
                raise ValueError("ratio_to=true requires a dotted metric key to infer the base denominator")
            if not self.format:
                # ratio_to produces deterministic 0–1 values; default to percent formatting for
                # display-only rendering unless the pack author overrides it.
                self.format = "percent:0"

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

        if self.format and "{{" not in self.format and "}}" not in self.format:
            try:
                parse_format_token(self.format)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid format token '{self.format}' for context.metrics binding '{self.alias}': {exc}"
                ) from exc

        return self

    @property
    def full_key(self) -> str | None:
        """Return the fully qualified metric key including variant."""

        if not self.key:
            return None
        if self.variant:
            return f"{self.key}.{self.variant}"
        return self.key

    def signature(self) -> tuple[str | None, tuple[str, ...], str | None, str | None, bool | str | None]:
        """Return a hashable signature used for reuse checks."""

        calculate_sig = self.calculate.combined_signature() if self.calculate else tuple()
        return (self.full_key, calculate_sig, self.format, self.expression, self.ratio_to)


def _normalise_metric_bindings(value: object) -> list[PackMetricBinding] | None:
    """Normalise metric binding shorthand into concrete PackMetricBinding rows."""

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

    raise TypeError("metrics bindings must be a mapping or list")


class PackMetricsContext(BaseModel):
    """Metrics-only context for packs and slides.

    This wrapper scopes DAX predicates to metric-context resolution without
    affecting slide visuals.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    calculate: ScopedCalculateMap | None = Field(
        default=None,
        description=(
            "Optional DAX CALCULATE predicates applied to metric-context execution. "
            "Shorthand entries default to DEFINE scope (outer dataset scoping). "
            "Use calculate.<name>.evaluate to apply calculation-group filters around every "
            "bound series in SUMMARIZECOLUMNS."
        ),
    )
    bindings: list[PackMetricBinding] | None = Field(
        default=None,
        description="Metric bindings resolved into Jinja variables.",
    )

    @field_validator("calculate", mode="before")
    @classmethod
    def _normalise_calculate(cls, value: object) -> ScopedCalculateMap | None:
        if value is None:
            return None
        return ScopedCalculateMap.from_raw(value)

    _normalise_bindings = field_validator("bindings", mode="before")(_normalise_metric_bindings)

    @model_validator(mode="after")
    def _validate_unique_aliases(self) -> "PackMetricsContext":
        if not self.bindings:
            return self

        seen: set[str] = set()
        duplicates: set[str] = set()
        for binding in self.bindings:
            alias = binding.alias or ""
            if alias in seen:
                duplicates.add(alias)
            else:
                seen.add(alias)

        if duplicates:
            dup_list = ", ".join(sorted(duplicates))
            raise ValueError(f"context.metrics defines duplicate aliases: {dup_list}")

        return self


class PackContext(BaseModel):
    """Context payload shared by slides.

    Extra keys are allowed so packs can continue to pass arbitrary template values.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    calculate: FiltersType = Field(
        default=None,
        description="Deprecated alias for metrics.calculate; use context.metrics.calculate instead.",
    )
    metrics: PackMetricsContext | None = Field(
        default=None,
        description="Optional metric context bindings and scoping predicates.",
    )

    @field_validator("metrics", mode="before")
    @classmethod
    def _normalise_metrics(cls, value: object) -> PackMetricsContext | None:
        if value is None:
            return None

        if isinstance(value, PackMetricsContext):
            return value

        if isinstance(value, Mapping):
            if "bindings" in value or "calculate" in value:
                return PackMetricsContext.model_validate(
                    {
                        "calculate": value.get("calculate"),
                        "bindings": value.get("bindings"),
                    }
                )

            bindings = _normalise_metric_bindings(value)
            return PackMetricsContext(bindings=bindings)

        if isinstance(value, Sequence) and not isinstance(value, str):
            bindings = _normalise_metric_bindings(value)
            return PackMetricsContext(bindings=bindings)

        raise TypeError("metrics must be a mapping or list")

    @model_validator(mode="after")
    def _apply_deprecated_calculate(self) -> "PackContext":
        if self.calculate is None:
            return self

        warnings.warn(
            "context.calculate is deprecated; use context.metrics.calculate instead.",
            UserWarning,
        )

        if self.metrics is None:
            self.metrics = PackMetricsContext(calculate=ScopedCalculateMap.from_raw(self.calculate))
        elif self.metrics.calculate is None:
            self.metrics.calculate = ScopedCalculateMap.from_raw(self.calculate)

        return self


class PackSlideContext(PackContext):
    """Context payload specific to an individual slide."""


class PackVisualSeriesConfig(BaseModel):
    """Series payload used by pack-level visual series operations."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(
        ...,
        description="Series identifier.",
    )

    @field_validator("id")
    @classmethod
    def _normalise_id(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("series id cannot be empty")
        return candidate


class PackVisualSeriesUpdateOperation(BaseModel):
    """Patch operation targeting one existing visual series by id."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(
        ...,
        description="Target series id to patch.",
    )
    patch: Mapping[str, Any] = Field(
        ...,
        description="Deep-merge patch applied to the target series payload.",
    )

    @field_validator("id")
    @classmethod
    def _normalise_id(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("series_update.id cannot be empty")
        return candidate

    @field_validator("patch", mode="before")
    @classmethod
    def _normalise_patch(cls, value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("series_update.patch must be a mapping")
        patch = {str(key): item for key, item in value.items()}
        if not patch:
            raise ValueError("series_update.patch cannot be empty")
        return patch

    @model_validator(mode="after")
    def _validate_patch_id(self) -> "PackVisualSeriesUpdateOperation":
        raw_patch_id = self.patch.get("id")
        if raw_patch_id is None:
            return self
        if not isinstance(raw_patch_id, str):
            raise ValueError("series_update.patch.id must be a string when provided")
        patch_id = raw_patch_id.strip()
        if patch_id != self.id:
            raise ValueError("series_update.patch.id must match series_update.id when provided")
        return self


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
    series_add: list[PackVisualSeriesConfig] | None = Field(
        default=None,
        description="Optional series entries appended to a referenced visual's series list.",
    )
    series_update: list[PackVisualSeriesUpdateOperation] | None = Field(
        default=None,
        description="Optional series patches applied by id to a referenced visual's series list.",
    )
    series_remove: list[str] | None = Field(
        default=None,
        description="Optional series ids removed from a referenced visual's series list.",
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

    @field_validator("series_remove", mode="before")
    @classmethod
    def _normalise_series_remove(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            values: Sequence[object] = [value]
        elif isinstance(value, Sequence):
            values = value
        else:
            raise TypeError("series_remove must be a string or sequence of strings")

        cleaned: list[str] = []
        for entry in values:
            if not isinstance(entry, str):
                raise TypeError("series_remove entries must be strings")
            candidate = entry.strip()
            if not candidate:
                continue
            cleaned.append(candidate)
        return cleaned or None

    @model_validator(mode="after")
    def _validate_series_operations(self) -> "PackVisualRef":
        has_series_operations = bool(self.series_add or self.series_update or self.series_remove)
        if not has_series_operations:
            return self

        if not self.ref:
            raise ValueError("series_add/series_update/series_remove are only supported when visual.ref is set")

        extra = self.model_extra or {}
        if "series" in extra:
            raise ValueError("visual.series cannot be combined with series_add/series_update/series_remove")

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
    _source_root: Path | None = PrivateAttr(default=None)

    title: str = Field(..., description="Human-friendly slide title.")
    id: str | None = Field(default=None, description="Optional stable identifier for the slide.")
    context: PackSlideContext | None = Field(
        default=None,
        description="Optional template context merged with the pack-level context.",
    )
    calculate: FiltersType = Field(
        default=None,
        description=(
            "Optional DAX filters applied to all visuals on the slide, merged after pack-level "
            "calculate filters and before visual-level overrides."
        ),
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

    @property
    def source_root(self) -> Path | None:
        """Directory that declared this slide; used for relative asset resolution."""

        return self._source_root

    def set_source_root(self, path: Path | None) -> None:
        """Assign the directory used to resolve this slide's relative asset paths."""

        self._source_root = path


def _normalise_operation_slide_id(value: object, *, label: str) -> str:
    """Normalize and validate operation slide identifiers."""

    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} cannot be empty")
    return cleaned


class PackSlideReplaceOperation(BaseModel):
    """Replace an inherited slide by id."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(..., description="Inherited slide id to replace.")
    slide: PackSlide = Field(..., description="Replacement slide payload.")

    @field_validator("id", mode="before")
    @classmethod
    def _normalise_id(cls, value: object) -> str:
        return _normalise_operation_slide_id(value, label="slides_replace.id")

    @model_validator(mode="after")
    def _validate_slide_id_alignment(self) -> "PackSlideReplaceOperation":
        if not self.slide.id:
            raise ValueError("slides_replace.slide must define id")
        if self.slide.id != self.id:
            raise ValueError("slides_replace.slide.id must match slides_replace.id")
        return self


class PackSlideUpdateOperation(BaseModel):
    """Patch an inherited slide by id."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(..., description="Inherited slide id to patch.")
    patch: dict[str, Any] = Field(..., description="Deep-merged patch payload.")

    @field_validator("id", mode="before")
    @classmethod
    def _normalise_id(cls, value: object) -> str:
        return _normalise_operation_slide_id(value, label="slides_update.id")

    @field_validator("patch", mode="before")
    @classmethod
    def _normalise_patch(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("slides_update.patch must be a mapping")
        patch = {str(key): item for key, item in value.items()}
        if not patch:
            raise ValueError("slides_update.patch cannot be empty")
        return patch

    @model_validator(mode="after")
    def _validate_patch_id(self) -> "PackSlideUpdateOperation":
        raw_patch_id = self.patch.get("id")
        if raw_patch_id is None:
            return self
        patch_id = _normalise_operation_slide_id(raw_patch_id, label="slides_update.patch.id")
        if patch_id != self.id:
            raise ValueError("slides_update.patch.id must match slides_update.id when provided")
        return self


class PackSlideInsertOperation(BaseModel):
    """Insert a new slide before or after an existing anchor slide id."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    before: str | None = Field(default=None, description="Anchor slide id for insertion before this slide.")
    after: str | None = Field(default=None, description="Anchor slide id for insertion after this slide.")
    slide: PackSlide = Field(..., description="Slide payload to insert.")

    @field_validator("before", "after", mode="before")
    @classmethod
    def _normalise_anchor(cls, value: object) -> str | None:
        if value is None:
            return None
        return _normalise_operation_slide_id(value, label="slides_insert anchor")

    @model_validator(mode="after")
    def _validate_insert_operation(self) -> "PackSlideInsertOperation":
        has_before = self.before is not None
        has_after = self.after is not None
        if has_before == has_after:
            raise ValueError("slides_insert must define exactly one of before or after")
        if not self.slide.id:
            raise ValueError("slides_insert.slide must define id")
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
    extends: str | None = Field(
        default=None,
        description="Optional parent pack path resolved relative to this pack file.",
    )
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
    evidence: PackEvidenceConfig | None = Field(
        default=None,
        description="Optional evidence export configuration executed after pack completion.",
    )
    slides_remove: list[str] | None = Field(
        default=None,
        description="Optional inherited slide ids to remove (requires extends).",
    )
    slides_replace: list[PackSlideReplaceOperation] | None = Field(
        default=None,
        description="Optional slide replacements by id (requires extends).",
    )
    slides_update: list[PackSlideUpdateOperation] | None = Field(
        default=None,
        description="Optional slide patches by id (requires extends).",
    )
    slides_insert: list[PackSlideInsertOperation] | None = Field(
        default=None,
        description="Optional slide inserts anchored before/after an existing id (requires extends).",
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

    @field_validator("extends", mode="before")
    @classmethod
    def _normalise_extends(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("extends must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("extends cannot be empty")
        return cleaned

    @field_validator("slides_remove", mode="before")
    @classmethod
    def _normalise_slides_remove(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise TypeError("slides_remove must be a list of slide ids")
        cleaned: list[str] = []
        for entry in value:
            cleaned.append(_normalise_operation_slide_id(entry, label="slides_remove entry"))
        return cleaned or None

    @model_validator(mode="after")
    def _validate_inheritance_mode(self) -> "PackConfig":
        operation_fields = ("slides_remove", "slides_replace", "slides_update", "slides_insert")
        has_operations = any(field in self.model_fields_set for field in operation_fields)
        has_slides = "slides" in self.model_fields_set

        if self.extends is None:
            if has_operations:
                raise ValueError("slides_* operations require extends")
            return self

        if has_slides and has_operations:
            raise ValueError(
                "packs with extends cannot define both slides and slides_* operations; choose one mode"
            )
        return self

    @model_validator(mode="after")
    def _validate_slide_metric_overrides(self) -> "PackConfig":
        root_metrics_context = self.context.metrics
        root_bindings = root_metrics_context.bindings or [] if root_metrics_context else []
        root_scope_signature = (
            root_metrics_context.calculate.combined_signature()
            if root_metrics_context and root_metrics_context.calculate
            else tuple()
        )
        root_by_alias = {
            binding.alias: binding.signature() + (root_scope_signature,)
            for binding in root_bindings
            if binding.alias
        }

        if not root_by_alias:
            return self

        for slide in self.slides:
            slide_context = slide.context
            slide_metrics_context = slide_context.metrics if slide_context else None
            slide_metrics = slide_metrics_context.bindings if slide_metrics_context else None
            if not slide_metrics:
                continue
            slide_scope_signature = ScopedCalculateMap.merge(
                root_metrics_context.calculate if root_metrics_context else None,
                slide_metrics_context.calculate if slide_metrics_context else None,
            ).combined_signature()

            for binding in slide_metrics:
                alias = binding.alias or ""
                root_signature = root_by_alias.get(alias)
                if root_signature is None:
                    continue
                if binding.override:
                    continue
                slide_signature = binding.signature() + (slide_scope_signature,)
                if slide_signature == root_signature:
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
    "PackMetricsContext",
    "PackMetricBinding",
    "PackPlaceholder",
    "PackSlide",
    "PackSlideInsertOperation",
    "PackSlideReplaceOperation",
    "PackSlideContext",
    "PackSlideUpdateOperation",
    "PackVisualSeriesConfig",
    "PackVisualSeriesUpdateOperation",
    "PackVisualRef",
]

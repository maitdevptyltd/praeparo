"""Schema models for generic context-layer documents.

These models describe the authored YAML/JSON payloads discovered under
`registry/context/**` or passed via CLI `--context` flags. They intentionally
reuse the existing pack context models for nested `context.metrics.*` support
while staying permissive for arbitrary template values such as `month`,
`display_date`, or `business_time`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator
from pydantic.json_schema import JsonSchemaValue

from praeparo.models.pack import PackContext


def _named_string_fragments_schema() -> JsonSchemaValue:
    return {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }


def _mixed_named_string_sequence_schema() -> JsonSchemaValue:
    return {
        "type": "array",
        "items": {
            "anyOf": [
                {"type": "string"},
                _named_string_fragments_schema(),
            ]
        },
    }


def _validate_named_string_fragments(value: object, *, field_name: str) -> object:
    if value is None or isinstance(value, str):
        return value

    if isinstance(value, Mapping):
        for candidate in value.values():
            if candidate is None:
                continue
            if not isinstance(candidate, str):
                raise TypeError(
                    f"{field_name} mapping values must be strings when authored in a context layer."
                )
        return value

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, str):
                continue
            if isinstance(entry, Mapping):
                for candidate in entry.values():
                    if candidate is None:
                        continue
                    if not isinstance(candidate, str):
                        raise TypeError(
                            f"{field_name} mapping values must be strings when authored in a context layer."
                        )
                continue
            raise TypeError(
                f"{field_name} entries must be strings or mappings when authored in a context layer."
            )
        return value

    raise TypeError(
        f"{field_name} must be a string, mapping, or sequence of strings/mappings."
    )


class ContextLayerFragments(RootModel[object]):
    """Authored shape for top-level calculate/define/filters context fragments."""

    @model_validator(mode="before")
    @classmethod
    def _validate_fragments(cls, value: object) -> object:
        return _validate_named_string_fragments(value, field_name="context layer fragment")

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> JsonSchemaValue:
        return {
            "title": "ContextLayerFragments",
            "description": cls.__doc__,
            "anyOf": [
                {"type": "string"},
                _named_string_fragments_schema(),
                _mixed_named_string_sequence_schema(),
            ],
        }


class ContextLayerDocument(BaseModel):
    """Generic context-layer payload merged before pack and explain execution."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    context: PackContext | None = Field(
        default=None,
        description=(
            "Optional nested template context. Reuses the pack context contract so "
            "`context.metrics.bindings`, `context.metrics.calculate`, and "
            "`context.metrics.allow_empty` behave the same way in context layers."
        ),
    )
    calculate: ContextLayerFragments | None = Field(
        default=None,
        description="Optional top-level DAX CALCULATE fragments merged into the execution context.",
    )
    define: ContextLayerFragments | None = Field(
        default=None,
        description="Optional top-level DEFINE fragments merged into the execution context.",
    )
    filters: ContextLayerFragments | None = Field(
        default=None,
        description="Optional top-level filter fragments available to downstream templating and datasources.",
    )


__all__ = ["ContextLayerDocument", "ContextLayerFragments"]

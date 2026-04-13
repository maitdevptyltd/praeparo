"""Helpers for scoped calculate predicates.

Praeparo supports `calculate` shorthands in multiple places:

- Metric-context bindings (`context.metrics.bindings[].calculate`): split between
  adhoc `MEASURE` definitions (DEFINE) vs filters applied around the measure
  reference inside `SUMMARIZECOLUMNS` (EVALUATE).
- Metric-context scoping (`context.metrics.calculate` at pack root / per-slide):
  split between outer dataset scoping (DEFINE) vs default EVALUATE predicates
  applied to every bound series.

This module provides:

- `ScopedCalculateFilters`: binding-focused model that normalises supported YAML
  shapes into ordered `define` and `evaluate` lists.
- `ScopedCalculateMap`: named calculate entries with per-scope merge semantics so
  pack root `context.metrics.calculate` can be inherited and overridden by slide.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator
from pydantic.json_schema import JsonSchemaValue


_UNLABELLED_PREFIX = "__unlabelled_"


def _coerce_filters(value: object) -> list[str]:
    """Coerce a calculate payload into a list of predicate strings."""

    if value is None:
        return []

    if isinstance(value, str):
        candidate = value.strip()
        return [candidate] if candidate else []

    if isinstance(value, Mapping):
        cleaned: list[str] = []
        for item in value.values():
            if item is None:
                continue
            candidate = str(item).strip()
            if candidate:
                cleaned.append(candidate)
        return cleaned

    if isinstance(value, Sequence):
        cleaned: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, Mapping):
                cleaned.extend(_coerce_filters(item))
                continue
            candidate = str(item).strip()
            if candidate:
                cleaned.append(candidate)
        return cleaned

    raise TypeError("calculate entries must be strings, sequences, or mappings")


def _unlabelled_key(index: int) -> str:
    # Keep synthetic keys stable and unlikely to collide with authored names.
    return f"{_UNLABELLED_PREFIX}{index:04d}"


def _allocate_merge_key(existing: Mapping[str, object], base: str) -> str:
    if base not in existing:
        return base
    counter = 2
    candidate = f"{base}_{counter}"
    while candidate in existing:
        counter += 1
        candidate = f"{base}_{counter}"
    return candidate


def _string_array_schema() -> JsonSchemaValue:
    return {"type": "array", "items": {"type": "string"}}


def _scoped_object_schema() -> JsonSchemaValue:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "define": _string_array_schema(),
            "evaluate": _string_array_schema(),
        },
    }


def _scoped_named_entry_schema() -> JsonSchemaValue:
    return {
        "anyOf": [
            {"type": "string"},
            _string_array_schema(),
            _scoped_object_schema(),
        ]
    }


def _scoped_named_mapping_schema() -> JsonSchemaValue:
    return {
        "type": "object",
        "additionalProperties": _scoped_named_entry_schema(),
    }


def _mixed_scoped_sequence_schema() -> JsonSchemaValue:
    return {
        "type": "array",
        "items": {
            "anyOf": [
                {"type": "string"},
                _scoped_named_mapping_schema(),
            ]
        },
    }


def _parse_scoped_filters(value: object) -> tuple[list[str], list[str]]:
    """Parse calculate payloads into DEFINE/EVALUATE predicate lists."""

    if isinstance(value, ScopedCalculateFilters):
        return list(value.define), list(value.evaluate)

    define_filters: list[str] = []
    evaluate_filters: list[str] = []

    if value is None:
        return define_filters, evaluate_filters

    if isinstance(value, str):
        define_filters.extend(_coerce_filters(value))
        return define_filters, evaluate_filters

    if isinstance(value, Mapping):
        allowed = {"define", "evaluate"}
        # Support the "scoped object" shape directly:
        #   calculate: {define: [...], evaluate: [...]}
        #
        # This form is produced when configs are round-tripped through Pydantic
        # (model_dump -> model_validate), so we must keep it stable even when a
        # pack slide applies inline visual overrides that trigger re-validation.
        if set(value.keys()).issubset(allowed):
            define_filters.extend(_coerce_filters(value.get("define")))
            evaluate_filters.extend(_coerce_filters(value.get("evaluate")))
            return define_filters, evaluate_filters

    if isinstance(value, Mapping):
        entries = [value]
    elif isinstance(value, Sequence):
        entries = list(value)
    else:
        raise TypeError("calculate must be a string, list, or mapping")

    for entry in entries:
        if entry is None:
            continue
        if isinstance(entry, str):
            define_filters.extend(_coerce_filters(entry))
            continue
        if not isinstance(entry, Mapping):
            raise TypeError("calculate list entries must be strings or mappings")

        for _, raw in entry.items():
            if raw is None:
                continue
            if isinstance(raw, Mapping):
                allowed = {"define", "evaluate"}
                unknown = set(raw.keys()) - allowed
                if unknown:
                    raise ValueError(
                        f"calculate entries only support keys {sorted(allowed)}; found {sorted(unknown)}"
                    )
                define_filters.extend(_coerce_filters(raw.get("define")))
                evaluate_filters.extend(_coerce_filters(raw.get("evaluate")))
            else:
                # Shorthand defaults to DEFINE scope.
                define_filters.extend(_coerce_filters(raw))

    return define_filters, evaluate_filters


class ScopedCalculateEntry(BaseModel):
    """Named calculate entry split between DEFINE and EVALUATE scopes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    define: list[str] = Field(default_factory=list, description="Predicates applied in the DEFINE scope.")
    evaluate: list[str] = Field(
        default_factory=list,
        description="Predicates applied in the EVALUATE scope (around measures in SUMMARIZECOLUMNS).",
    )

    @classmethod
    def from_raw(cls, value: object) -> "ScopedCalculateEntry":
        """Normalise an individual calculate entry.

        Supported shapes:
        - string / list / mapping → DEFINE predicates (shorthand).
        - {define: ..., evaluate: ...} → scoped predicates.
        """

        if value is None:
            return cls()

        if isinstance(value, Mapping):
            allowed = {"define", "evaluate"}
            unknown = set(value.keys()) - allowed
            if unknown:
                # Treat unknown keys as shorthand DEFINE entries so we remain
                # compatible with prior "named mapping" patterns.
                return cls(define=_coerce_filters(value))

            return cls(
                define=_coerce_filters(value.get("define")),
                evaluate=_coerce_filters(value.get("evaluate")),
            )

        # Shorthand defaults to DEFINE scope.
        return cls(define=_coerce_filters(value))

    def has_define(self) -> bool:
        return bool(self.define)

    def has_evaluate(self) -> bool:
        return bool(self.evaluate)


class ScopedCalculateMap(RootModel[dict[str, ScopedCalculateEntry]]):
    """Named calculate map with per-scope merge helpers.

    This model is used for `context.metrics.calculate` at both pack root and slide
    scope so root definitions automatically apply to slide metric-context runs.
    """

    root: dict[str, ScopedCalculateEntry] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, value: object) -> "ScopedCalculateMap":
        """Normalise raw YAML calculate payload into a named map.

        Supported shapes:
        - string → synthetic unlabelled entry (DEFINE scope).
        - list containing strings and/or mappings → ordered union.
        - mapping name → predicate(s) → DEFINE scope for that name.
        - mapping name → {define: ..., evaluate: ...} → scoped predicates.
        """

        if value is None:
            return cls()

        if isinstance(value, ScopedCalculateMap):
            return value

        entries: list[object]
        if isinstance(value, str):
            entries = [value]
        elif isinstance(value, Mapping):
            entries = [value]
        elif isinstance(value, Sequence):
            entries = list(value)
        else:
            raise TypeError("calculate must be a string, list, or mapping")

        mapped: dict[str, ScopedCalculateEntry] = {}
        unlabelled_index = 0

        for entry in entries:
            if entry is None:
                continue

            if isinstance(entry, str):
                synthetic = _unlabelled_key(unlabelled_index)
                unlabelled_index += 1
                mapped[synthetic] = ScopedCalculateEntry.from_raw(entry)
                continue

            if not isinstance(entry, Mapping):
                raise TypeError("calculate list entries must be strings or mappings")

            for name, raw in entry.items():
                key = str(name).strip()
                if not key:
                    raise ValueError("calculate mapping keys cannot be empty")
                mapped[key] = ScopedCalculateEntry.from_raw(raw)

        return cls(mapped)

    @classmethod
    def merge(cls, root: "ScopedCalculateMap | None", slide: "ScopedCalculateMap | None") -> "ScopedCalculateMap":
        """Merge two maps with by-name per-scope override semantics.

        - Keys union (preserve root insertion order, then slide-only keys).
        - For colliding keys:
          - slide DEFINE replaces root DEFINE iff slide provided any DEFINE predicates.
          - slide EVALUATE replaces root EVALUATE iff slide provided any EVALUATE predicates.
        """

        root_map = cls.from_raw(root).root if root is not None else {}
        slide_map = cls.from_raw(slide).root if slide is not None else {}

        merged: dict[str, ScopedCalculateEntry] = {}
        for name, entry in root_map.items():
            merged[name] = entry

        for name, slide_entry in slide_map.items():
            if name not in merged:
                merged[name] = slide_entry
                continue

            # Synthetic unlabelled entries are intended to behave like the legacy
            # "unlabelled list" semantics (append root then slide). Because both
            # root/slide parsing starts indexing from zero, we avoid collisions by
            # allocating a new synthetic name when needed.
            if name.startswith(_UNLABELLED_PREFIX):
                merged[_allocate_merge_key(merged, name)] = slide_entry
                continue

            root_entry = merged[name]
            define = slide_entry.define if slide_entry.has_define() else root_entry.define
            evaluate = slide_entry.evaluate if slide_entry.has_evaluate() else root_entry.evaluate
            merged[name] = ScopedCalculateEntry(define=list(define), evaluate=list(evaluate))

        return cls(merged)

    def flatten_define(self) -> list[str]:
        """Flatten DEFINE predicates, preserving per-name ordering."""

        flattened: list[str] = []
        for entry in self.root.values():
            flattened.extend(entry.define)
        return flattened

    def flatten_evaluate(self) -> list[str]:
        """Flatten EVALUATE predicates, preserving per-name ordering."""

        flattened: list[str] = []
        for entry in self.root.values():
            flattened.extend(entry.evaluate)
        return flattened

    def combined_signature(self) -> tuple[str, ...]:
        """Return a stable signature over both scopes."""

        combined = [*self.flatten_define(), *self.flatten_evaluate()]
        return tuple(sorted(set(item.strip() for item in combined if item and item.strip())))

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> JsonSchemaValue:
        return {
            "title": "ScopedCalculateMap",
            "description": cls.__doc__,
            "anyOf": [
                {"type": "string"},
                _string_array_schema(),
                _scoped_named_mapping_schema(),
                _mixed_scoped_sequence_schema(),
            ],
        }


class ScopedCalculateFilters(BaseModel):
    """Split calculate predicates between DEFINE and EVALUATE scopes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    define: list[str] = Field(default_factory=list, description="Predicates applied inside adhoc MEASURE definitions.")
    evaluate: list[str] = Field(default_factory=list, description="Predicates applied around measures in SUMMARIZECOLUMNS.")

    @model_validator(mode="before")
    @classmethod
    def _coerce_scoped_filters(cls, value: object) -> dict[str, list[str]]:
        define_filters, evaluate_filters = _parse_scoped_filters(value)
        return {"define": define_filters, "evaluate": evaluate_filters}

    @classmethod
    def from_raw(cls, value: object) -> "ScopedCalculateFilters":
        """Normalise raw YAML calculate payload into scoped lists.

        Supported shapes:
        - string / list of strings → define predicates.
        - mapping name → predicate(s) → define predicates.
        - mapping name → {define: ..., evaluate: ...} → scoped predicates.
        - list containing strings and/or mappings → merged as above.
        """

        define_filters, evaluate_filters = _parse_scoped_filters(value)
        return cls(define=define_filters, evaluate=evaluate_filters)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> JsonSchemaValue:
        return {
            "title": "ScopedCalculateFilters",
            "description": cls.__doc__,
            "anyOf": [
                {"type": "string"},
                _string_array_schema(),
                _scoped_object_schema(),
                _scoped_named_mapping_schema(),
                _mixed_scoped_sequence_schema(),
            ],
        }

    def combined_signature(self) -> tuple[str, ...]:
        """Return a stable signature over both scopes."""

        combined = [*self.define, *self.evaluate]
        return tuple(sorted(set(item.strip() for item in combined if item and item.strip())))


__all__ = ["ScopedCalculateEntry", "ScopedCalculateFilters", "ScopedCalculateMap"]

"""Helpers for scoped calculate predicates.

Packs and visuals support `calculate` shorthands with named entries. For metric
context bindings, some predicates need to land in the adhoc MEASURE definition
(`DEFINE`) while others must wrap the measure reference in `SUMMARIZECOLUMNS`
(`EVALUATE`) to support calculation groups like Time Intelligence.

`ScopedCalculateFilters` normalises the supported YAML shapes into two ordered
lists: `define` and `evaluate`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


def _coerce_filters(value: object) -> list[str]:
    """Coerce a calculate payload into a list of predicate strings."""

    if value is None:
        return []

    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []

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


class ScopedCalculateFilters(BaseModel):
    """Split calculate predicates between DEFINE and EVALUATE scopes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    define: list[str] = Field(default_factory=list, description="Predicates applied inside adhoc MEASURE definitions.")
    evaluate: list[str] = Field(default_factory=list, description="Predicates applied around measures in SUMMARIZECOLUMNS.")

    @classmethod
    def from_raw(cls, value: object) -> "ScopedCalculateFilters":
        """Normalise raw YAML calculate payload into scoped lists.

        Supported shapes:
        - string / list of strings → define predicates.
        - mapping name → predicate(s) → define predicates.
        - mapping name → {define: ..., evaluate: ...} → scoped predicates.
        - list containing strings and/or mappings → merged as above.
        """

        define_filters: list[str] = []
        evaluate_filters: list[str] = []

        if value is None:
            return cls()

        if isinstance(value, str):
            define_filters.extend(_coerce_filters(value))
            return cls(define=define_filters, evaluate=evaluate_filters)

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

        return cls(define=define_filters, evaluate=evaluate_filters)

    def combined_signature(self) -> tuple[str, ...]:
        """Return a stable signature over both scopes."""

        combined = [*self.define, *self.evaluate]
        return tuple(sorted(set(item.strip() for item in combined if item and item.strip())))


__all__ = ["ScopedCalculateFilters"]

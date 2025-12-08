"""Helpers for templating and merging pack filters."""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from praeparo.models import FiltersType


def _strip(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalise_sequence(values: Sequence[object]) -> list[str]:
    cleaned: list[str] = []
    for entry in values:
        candidate = _strip(entry)
        if candidate:
            cleaned.append(candidate)
    return cleaned


def _normalise_mapping(values: Mapping[str, object]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in values.items():
        candidate = _strip(value)
        if candidate:
            cleaned[str(key)] = candidate
    return cleaned


def normalise_filters(value: FiltersType) -> dict[str, str] | list[str] | None:
    """Coerce filters into a mapping or list of strings, dropping empty entries."""

    if value is None:
        return None
    if isinstance(value, str):
        candidate = _strip(value)
        return [candidate] if candidate else None
    if isinstance(value, Mapping):
        return _normalise_mapping(value)
    if isinstance(value, Sequence):
        return _normalise_sequence(value)
    msg = f"Unsupported filter type: {type(value).__name__}"
    raise TypeError(msg)


def merge_odata_filters(
    global_filters: FiltersType,
    local_filters: FiltersType,
) -> dict[str, str] | list[str] | None:
    """Merge pack-level and slide-level OData filters following pack semantics."""

    merged_global = normalise_filters(global_filters)
    merged_local = normalise_filters(local_filters)

    if merged_local is None:
        return merged_global
    if merged_global is None:
        return merged_local

    if isinstance(merged_global, dict) and isinstance(merged_local, dict):
        return {**merged_global, **merged_local}

    # Fall back to concatenated lists when either side is a sequence.
    global_list = merged_global if isinstance(merged_global, list) else list(merged_global.values())
    local_list = merged_local if isinstance(merged_local, list) else list(merged_local.values())
    return [*global_list, *local_list]


def normalise_calculate_filters(value: FiltersType) -> list[str]:
    """Return calculate filters as an ordered list of strings."""

    normalised = normalise_filters(value)
    if normalised is None:
        return []
    if isinstance(normalised, dict):
        return list(normalised.values())
    return list(normalised)


def merge_calculate_filters(global_filters: FiltersType, local_filters: FiltersType) -> list[str]:
    """Combine pack-level and slide-level calculate filters, preserving order."""

    base = normalise_calculate_filters(global_filters)
    additions = normalise_calculate_filters(local_filters)
    return [*base, *additions]


__all__ = [
    "merge_odata_filters",
    "normalise_calculate_filters",
    "merge_calculate_filters",
    "normalise_filters",
]

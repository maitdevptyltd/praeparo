"""Helpers for composing top-level visual execution context."""

from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import cast

import yaml


class ContextLoadError(ValueError):
    """Raised when a provided context file cannot be parsed."""

def _normalise_sequence(value: object) -> list[str]:
    """Normalise simple sequence inputs (define blocks) into a list of strings."""

    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Mapping):
        items: list[str] = []
        for entry in value.values():
            if entry is None:
                continue
            if not isinstance(entry, str):
                raise TypeError("Context mapping values must be strings when used for calculate/define.")
            candidate = entry.strip()
            if candidate:
                items.append(candidate)
        return items
    if isinstance(value, Sequence):
        items: list[str] = []
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, Mapping):
                items.extend(_normalise_sequence(entry))
                continue
            if not isinstance(entry, str):
                raise TypeError("Context entries must be strings.")
            candidate = entry.strip()
            if candidate:
                items.append(candidate)
        return items
    raise TypeError("Context entries must be supplied as strings or iterables of strings.")


def _split_named_and_unlabelled(value: object) -> tuple[dict[str, str], list[str]]:
    """
    Return a tuple of (named, unlabelled) calculate fragments.

    - Named fragments come from mappings (including mappings embedded inside sequences).
    - Unlabelled fragments capture strings or non-mapping entries.
    """

    named: dict[str, str] = {}
    unlabelled: list[str] = []

    if value is None:
        return named, unlabelled

    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            unlabelled.append(candidate)
        return named, unlabelled

    if isinstance(value, Mapping):
        for key, candidate in value.items():
            if candidate is None:
                continue
            if not isinstance(candidate, str):
                raise TypeError("Context mapping values must be strings when used for calculate.")
            stripped = candidate.strip()
            if stripped:
                named[str(key)] = stripped
        return named, unlabelled

    if isinstance(value, Sequence):
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, Mapping):
                entry_named, entry_unlabelled = _split_named_and_unlabelled(entry)
                named.update(entry_named)
                unlabelled.extend(entry_unlabelled)
                continue
            if not isinstance(entry, str):
                raise TypeError("Context entries must be strings or mappings when used for calculate.")
            candidate = entry.strip()
            if candidate:
                unlabelled.append(candidate)
        return named, unlabelled

    raise TypeError("Context entries must be supplied as strings, mappings, or iterables thereof.")


def load_context_file(path: Path) -> Mapping[str, object]:
    """Load a JSON/YAML context file containing top-level calculate/define blocks."""

    if not path.exists():
        raise FileNotFoundError(f"Context file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(raw)
        else:
            payload = yaml.safe_load(raw)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:  # pragma: no cover - parser errors surface
        raise ContextLoadError(f"Failed to parse context file {path}: {exc}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ContextLoadError("Context file must define a mapping object.")
    return dict(payload)


def merge_context_payload(
    *,
    base: Mapping[str, object] | None = None,
    calculate: Sequence[str] | None = None,
    define: Sequence[str] | None = None,
) -> dict[str, object]:
    """Return a merged context dictionary containing calculate/define lists."""

    result: MutableMapping[str, object] = dict(base or {})

    existing_named, existing_unlabelled = _split_named_and_unlabelled(result.get("calculate"))
    incoming_named, incoming_unlabelled = _split_named_and_unlabelled(calculate)

    merged_named = dict(existing_named)
    merged_named.update(incoming_named)

    merged_unlabelled = list(existing_unlabelled)
    for item in incoming_unlabelled:
        if item not in merged_unlabelled:
            merged_unlabelled.append(item)

    merged_calculate = [*merged_named.values(), *merged_unlabelled]

    existing_define = _normalise_sequence(result.get("define"))
    merged_define = existing_define + [item for item in _normalise_sequence(define) if item not in existing_define]

    if merged_calculate:
        result["calculate"] = merged_calculate
    elif "calculate" in result:
        result["calculate"] = []

    if merged_define:
        result["define"] = merged_define
    elif "define" in result:
        result["define"] = []

    return dict(result)


def resolve_dax_context(
    *,
    base: Mapping[str, object] | None = None,
    calculate: Sequence[str] | str | None = None,
    define: Sequence[str] | str | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Merge and normalise global DAX fragments from CLI flags and context payload."""

    from praeparo.visuals.dax import normalise_define_blocks, normalise_filter_group

    merged = merge_context_payload(base=base, calculate=calculate, define=define)
    calculate_value = merged.get("calculate")
    define_value = merged.get("define")
    calculate_filters = normalise_filter_group(cast("Sequence[str] | str | None", calculate_value))
    define_blocks = normalise_define_blocks(cast("Sequence[str] | str | None", define_value))
    return calculate_filters, define_blocks


__all__ = ["ContextLoadError", "load_context_file", "merge_context_payload", "resolve_dax_context"]

"""Helpers for composing top-level visual execution context."""

from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path

import yaml


class ContextLoadError(ValueError):
    """Raised when a provided context file cannot be parsed."""

def _flatten_fragments(value: object, *, label: str) -> list[str]:
    """Flatten a mixed calculate/define payload into a list of strings."""

    named, unlabelled = _split_named_and_unlabelled(value, label=label)
    return [*named.values(), *unlabelled]


def _split_named_and_unlabelled(value: object, *, label: str) -> tuple[dict[str, str], list[str]]:
    """
    Return a tuple of (named, unlabelled) context fragments.

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
                raise TypeError(f"Context mapping values must be strings when used for {label}.")
            stripped = candidate.strip()
            if stripped:
                named[str(key)] = stripped
        return named, unlabelled

    if isinstance(value, Sequence):
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, Mapping):
                entry_named, entry_unlabelled = _split_named_and_unlabelled(entry, label=label)
                named.update(entry_named)
                unlabelled.extend(entry_unlabelled)
                continue
            if not isinstance(entry, str):
                raise TypeError(f"Context entries must be strings or mappings when used for {label}.")
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
    calculate: object | None = None,
    define: object | None = None,
) -> dict[str, object]:
    """Return a merged context dictionary containing calculate/define lists."""

    result: MutableMapping[str, object] = dict(base or {})

    existing_named, existing_unlabelled = _split_named_and_unlabelled(result.get("calculate"), label="calculate")
    incoming_named, incoming_unlabelled = _split_named_and_unlabelled(calculate, label="calculate")

    merged_named = dict(existing_named)
    merged_named.update(incoming_named)

    merged_unlabelled = list(existing_unlabelled)
    for item in incoming_unlabelled:
        if item not in merged_unlabelled:
            merged_unlabelled.append(item)

    merged_calculate: list[object] = [{key: value} for key, value in merged_named.items()]
    merged_calculate.extend(merged_unlabelled)

    existing_define_named, existing_define_unlabelled = _split_named_and_unlabelled(result.get("define"), label="define")
    incoming_define_named, incoming_define_unlabelled = _split_named_and_unlabelled(define, label="define")

    merged_define_named = dict(existing_define_named)
    merged_define_named.update(incoming_define_named)

    merged_define_unlabelled = list(existing_define_unlabelled)
    for item in incoming_define_unlabelled:
        if item not in merged_define_unlabelled:
            merged_define_unlabelled.append(item)

    merged_define: list[object] = [{key: value} for key, value in merged_define_named.items()]
    merged_define.extend(merged_define_unlabelled)

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
    calculate_filters = normalise_filter_group(_flatten_fragments(merged.get("calculate"), label="calculate"))
    define_blocks = normalise_define_blocks(_flatten_fragments(merged.get("define"), label="define"))

    for label, values in (("calculate", calculate_filters), ("define", define_blocks)):
        for value in values:
            if "{{" in value or "}}" in value:
                raise ValueError(
                    f"Unrendered Jinja template tokens found in {label} context: {value!r}. "
                    "Ensure the context layer defines required templating variables."
                )
    return calculate_filters, define_blocks


__all__ = ["ContextLoadError", "load_context_file", "merge_context_payload", "resolve_dax_context"]

"""Helpers for composing top-level visual execution context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

import yaml


class ContextLoadError(ValueError):
    """Raised when a provided context file cannot be parsed."""


def _normalise_sequence(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, Sequence):
        items: list[str] = []
        for entry in value:
            if entry is None:
                continue
            if not isinstance(entry, str):
                raise TypeError("Context entries must be strings.")
            candidate = entry.strip()
            if candidate:
                items.append(candidate)
        return items
    raise TypeError("Context entries must be supplied as strings or iterables of strings.")


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
    existing_calculate = _normalise_sequence(result.get("calculate"))
    existing_define = _normalise_sequence(result.get("define"))

    merged_calculate = existing_calculate + [item for item in _normalise_sequence(calculate) if item not in existing_calculate]
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


__all__ = ["ContextLoadError", "load_context_file", "merge_context_payload"]

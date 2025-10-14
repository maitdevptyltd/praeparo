"""Shared helpers for configuration inheritance graphs."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, TypeVar


T = TypeVar("T")


def validate_extends_graph(
    registry: Mapping[str, T],
    source_map: Mapping[str, Path],
    *,
    get_parent: Callable[[T], str | None],
) -> list[str]:
    """Validate a simple extends graph.

    Ensures all referenced parents exist and detects inheritance cycles.
    Returns a list of error strings; an empty list indicates the graph is valid.
    """

    errors: list[str] = []

    visited: set[str] = set()

    def resolve_chain(key: str, stack: list[str]) -> None:
        if key in visited:
            return
        obj = registry[key]
        parent_key = get_parent(obj)
        if not parent_key:
            visited.add(key)
            return
        if parent_key not in registry:
            location = source_map[key]
            errors.append(
                f"{location}: extends '{parent_key}' not found in provided metrics"
            )
            return
        if parent_key in stack:
            cycle = " → ".join(stack + [parent_key])
            errors.append(
                f"{source_map[key]}: inheritance cycle detected ({cycle})"
            )
            return
        stack.append(parent_key)
        resolve_chain(parent_key, stack)
        stack.pop()
        visited.add(key)

    for key in registry:
        resolve_chain(key, [])

    return errors


__all__ = ["validate_extends_graph"]

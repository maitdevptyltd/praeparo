"""Context-layer discovery and merging helpers.

This module provides a single place to resolve layered context payloads for
Praeparo executions. The flow is intentionally shared across CLI visual runs
and pack runs so that "global" definitions (for example, registry-owned helper
functions) apply consistently.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

from jinja2 import Environment

from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.visuals.context import load_context_file, merge_context_payload

_CONTEXT_SUFFIXES = {".yaml", ".yml", ".json"}


def discover_registry_context_paths(*, metrics_root: Path) -> tuple[Path, ...]:
    """Return context-layer files discovered under the default registry root.

    Registry context layers live alongside the metric catalogue:

    - metrics_root: `registry/metrics`
    - default context root: `registry/context`

    Files are discovered recursively and returned in deterministic, lexicographic
    order by their relative path.
    """

    context_root = metrics_root.parent / "context"
    if not context_root.exists():
        return ()

    paths: list[Path] = []
    for entry in context_root.rglob("*"):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in _CONTEXT_SUFFIXES:
            continue
        paths.append(entry)

    paths.sort(key=lambda path: path.relative_to(context_root).as_posix())
    return tuple(paths)


def resolve_layered_context_payload(
    *,
    metrics_root: Path,
    context_paths: Sequence[Path] = (),
    calculate: Sequence[str] | str | None = None,
    define: Sequence[str] | str | None = None,
    env: Environment | None = None,
) -> dict[str, object]:
    """Resolve registry + explicit context layers into one merged payload.

    Resolution order is:

    1) Registry context layers (auto-discovered under `registry/context/**`).
    2) Explicit context layers (repeatable `--context`, applied in CLI order).
    3) CLI `--calculate` / `--define` flags (highest priority).

    Each layer's `calculate`/`define`/`filters` blocks are rendered with Jinja
    using templating variables sourced from that same layer's `context` section
    when present (otherwise falling back to a best-effort mapping of top-level
    keys).
    """

    jinja_env = env or create_pack_jinja_env()

    merged: dict[str, object] = {}

    # Start with registry-owned layers so downstream repos can ship stable
    # helper definitions without repeating them in every pack.
    for path in discover_registry_context_paths(metrics_root=metrics_root):
        layer = _load_rendered_context_layer(path, env=jinja_env)
        merged = merge_context_layer_payload(base=merged, incoming=layer)

    # With registry defaults applied, layer explicit context overrides in the
    # caller-supplied order (last-writer-wins for named fragments).
    for path in context_paths:
        layer = _load_rendered_context_layer(path, env=jinja_env)
        merged = merge_context_layer_payload(base=merged, incoming=layer)

    # Finally apply any CLI fragments so they always win over file-based layers.
    merged = merge_context_payload(base=merged, calculate=calculate, define=define)
    _raise_on_unrendered_templates(merged)
    return merged


def _load_rendered_context_layer(path: Path, *, env: Environment) -> dict[str, object]:
    """Load and Jinja-render a single context-layer file."""

    raw = load_context_file(path)
    payload: dict[str, object]
    template_context: Mapping[str, Any] = {}

    if _is_pack_shaped_payload(raw):
        payload = _pack_payload_to_layer_base(raw)
        context_section = raw.get("context")
        if isinstance(context_section, Mapping):
            template_context = context_section
    else:
        payload = dict(raw)
        template_context = _build_template_context(raw)

    if payload:
        rendered = dict(payload)
        for key in ("calculate", "define", "filters"):
            if key in rendered:
                rendered[key] = render_value(rendered[key], env=env, context=template_context)
        payload = rendered

    return payload


def _pack_payload_to_layer_base(payload: Mapping[str, object]) -> dict[str, object]:
    """Adapt a pack-like payload into a layer base mapping."""

    base: dict[str, object] = {}

    context_section = payload.get("context")
    if isinstance(context_section, Mapping):
        for key, value in context_section.items():
            base[str(key)] = value

    for key in ("calculate", "define", "filters"):
        if key in payload:
            base[key] = payload[key]

    return base


def _build_template_context(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Derive a Jinja context mapping for templating within a layer file."""

    context_section = payload.get("context")
    if isinstance(context_section, Mapping):
        return context_section

    skip_keys = {"calculate", "define", "filters", "slides", "schema"}
    fallback: dict[str, object] = {}
    for key, value in payload.items():
        if key in skip_keys:
            continue
        fallback[str(key)] = value
    return fallback


def _is_pack_shaped_payload(payload: Mapping[str, object]) -> bool:
    """Return True when the payload looks like a full pack config."""

    return "schema" in payload and "slides" in payload


def merge_context_layer_payload(*, base: Mapping[str, object], incoming: Mapping[str, object]) -> dict[str, object]:
    """Merge two context payloads using deep merge plus named DAX fragment semantics."""

    merged: MutableMapping[str, object] = dict(base)

    # Start by deep-merging non-DAX payload so nested context mappings can be
    # overridden without replacing the entire branch.
    for key, value in incoming.items():
        if key in {"calculate", "define"}:
            continue
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge_mapping(existing, value)
        else:
            merged[key] = value

    # With the base payload merged, apply calculate/define fragments using the
    # shared merge semantics from praeparo.visuals.context.
    return merge_context_payload(
        base=merged,
        calculate=incoming.get("calculate"),
        define=incoming.get("define"),
    )


def _deep_merge_mapping(base: Mapping[str, object], incoming: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = dict(base)
    for key, value in incoming.items():
        existing = result.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[str(key)] = _deep_merge_mapping(existing, value)
        else:
            result[str(key)] = value
    return result


def _raise_on_unrendered_templates(payload: Mapping[str, object]) -> None:
    """Fail fast when templating markers survive context resolution."""

    for key in ("calculate", "define"):
        raw = payload.get(key)
        if raw is None:
            continue
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            continue
        for item in raw:
            candidates: list[str] = []
            if isinstance(item, str):
                candidates = [item]
            elif isinstance(item, Mapping):
                candidates = [value for value in item.values() if isinstance(value, str)]

            for candidate in candidates:
                if "{{" in candidate or "}}" in candidate:
                    raise ValueError(
                        f"Unrendered Jinja template tokens found in merged {key} context: {candidate!r}. "
                        "Ensure the context layer defines required templating variables."
                    )


__all__ = ["discover_registry_context_paths", "merge_context_layer_payload", "resolve_layered_context_payload"]

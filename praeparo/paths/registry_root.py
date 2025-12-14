"""Resolve paths anchored to the registry root (`@/`).

Praeparo historically resolves visual/module paths relative to the YAML file
being processed. This helper introduces an opt-in `@/` prefix that resolves
paths relative to the repository's `registry/` directory instead.
"""

from __future__ import annotations

from pathlib import Path


_ANCHOR_PREFIX = "@/"
_REGISTRY_DIRNAME = "registry"


def is_registry_anchored_path(value: str) -> bool:
    """Return True when *value* begins with the registry-root anchor prefix."""

    return value.startswith(_ANCHOR_PREFIX)


def resolve_registry_root(context_path: Path) -> Path:
    """Discover the `registry/` directory associated with *context_path*.

    Resolution order:
      1) If *context_path* is already within a directory named `registry`, use
         that ancestor directory.
      2) Otherwise, walk upwards and use the first ancestor that contains a
         child directory named `registry/`.
    """

    resolved_context_path = context_path.expanduser().resolve(strict=False)
    start = resolved_context_path.parent

    for ancestor in (start, *start.parents):
        if ancestor.name == _REGISTRY_DIRNAME:
            return ancestor

    for ancestor in (start, *start.parents):
        candidate = ancestor / _REGISTRY_DIRNAME
        if candidate.is_dir():
            return candidate.resolve(strict=False)

    raise ValueError(
        f"Unable to resolve registry root from context_path={resolved_context_path!s}: "
        "no registry directory was found in ancestors."
    )


def resolve_registry_anchored_path(value: str, *, context_path: Path) -> Path:
    """Resolve an `@/` anchored path to an absolute Path under the registry root."""

    if not is_registry_anchored_path(value):
        raise ValueError(f"Expected an anchored path starting with '@/': {value!r}")

    remainder = value[len(_ANCHOR_PREFIX) :]
    if not remainder:
        raise ValueError(f"Anchored path must include a non-empty relative path: {value!r}")
    if remainder.startswith(("/", "\\")):
        raise ValueError(
            f"Anchored path must be relative to the registry root (no leading slash): {value!r}"
        )

    try:
        registry_root = resolve_registry_root(context_path)
    except ValueError as exc:
        resolved_context_path = context_path.expanduser().resolve(strict=False)
        raise ValueError(
            f"Unable to resolve anchored path {value!r} from context_path={resolved_context_path!s}: "
            "no registry directory was found in ancestors."
        ) from exc

    resolved_registry_root = registry_root.expanduser().resolve(strict=False)
    resolved_path = (resolved_registry_root / remainder).resolve(strict=False)

    try:
        resolved_path.relative_to(resolved_registry_root)
    except ValueError as exc:
        raise ValueError(
            f"Anchored path {value!r} from context_path={context_path!s} resolves outside registry root "
            f"{resolved_registry_root!s}: {resolved_path!s}"
        ) from exc

    return resolved_path


__all__ = ["is_registry_anchored_path", "resolve_registry_anchored_path", "resolve_registry_root"]

"""Visual registry and loader utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Mapping, Tuple

import yaml

from praeparo.models.visual_base import BaseVisualConfig

VisualLoader = Callable[[Path, Mapping[str, object], Tuple[Path, ...]], BaseVisualConfig]

_VISUAL_REGISTRY: Dict[str, VisualLoader] = {}


def register_visual_type(type_name: str, loader: VisualLoader, *, overwrite: bool = False) -> None:
    """Register a loader for a visual type."""

    if not isinstance(type_name, str) or not type_name.strip():
        raise ValueError("type_name must be a non-empty string")
    key = type_name.strip().lower()
    if not overwrite and key in _VISUAL_REGISTRY:
        raise ValueError(f"Visual type '{key}' is already registered")
    _VISUAL_REGISTRY[key] = loader


def load_visual_definition(path: Path | str, *, base_path: Path | None = None, stack: Tuple[Path, ...] | None = None) -> BaseVisualConfig:
    """Load and validate a visual definition from disk."""

    target = Path(path)
    if not target.is_absolute():
        root = base_path or Path.cwd()
        target = (root / target).resolve()
    else:
        target = target.resolve()

    visit_stack = stack or tuple()
    if target in visit_stack:
        cycle = " -> ".join(p.as_posix() for p in visit_stack + (target,))
        raise ValueError(f"Circular visual reference detected: {cycle}")

    if not target.exists():
        raise FileNotFoundError(f"Visual file not found: {target}")

    raw_text = target.read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:  # pragma: no cover - surface parser errors
        raise ValueError(f"Failed to parse visual YAML at {target}: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise ValueError(f"Visual YAML at {target} must define a mapping")

    visual_type = payload.get("type")
    if not isinstance(visual_type, str) or not visual_type.strip():
        raise ValueError(f"Visual YAML at {target} must define a non-empty 'type' field")
    key = visual_type.strip().lower()
    loader = _VISUAL_REGISTRY.get(key)
    if loader is None:
        raise ValueError(f"Visual type '{visual_type}' is not registered")

    return loader(target, payload, visit_stack + (target,))


__all__ = ["VisualLoader", "load_visual_definition", "register_visual_type"]

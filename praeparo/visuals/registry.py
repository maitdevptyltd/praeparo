"""Visual registry and loader utilities."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, Iterable, Mapping, Sequence, Tuple, Type

import yaml

from praeparo.models.visual_base import BaseVisualConfig
from praeparo.visuals.context_models import VisualContextModel

if TYPE_CHECKING:  # pragma: no cover
    from praeparo.pipeline import VisualExecutionResult

VisualLoader = Callable[[Path, Mapping[str, object], Tuple[Path, ...]], BaseVisualConfig]


@dataclass(frozen=True)
class VisualCLIArgument:
    """Definition for an additional CLI flag exposed by a visual type."""

    flag: str
    help: str
    type: type | None = str
    default: object = None
    metavar: str | None = None
    required: bool = False
    choices: Sequence[object] | None = None
    action: str | None = None
    multiple: bool = False
    dest: str | None = None
    metadata_key: str | None = None


@dataclass(frozen=True)
class VisualCLIHooks:
    """Optional lifecycle hooks triggered by the CLI."""

    post_execute: Callable[["VisualExecutionResult", argparse.Namespace], None] | None = None


@dataclass(frozen=True)
class VisualCLIOptions:
    """CLI metadata registered for a visual type."""

    arguments: Sequence[VisualCLIArgument] = field(default_factory=tuple)
    hooks: VisualCLIHooks = field(default_factory=VisualCLIHooks)


@dataclass(frozen=True)
class VisualTypeRegistration:
    """Internal container holding loader & CLI metadata for a visual type."""

    loader: VisualLoader
    cli: VisualCLIOptions | None = None
    context_model: Type[VisualContextModel] | None = None


_VISUAL_REGISTRY: Dict[str, VisualTypeRegistration] = {}


def _is_python_visual_type(value: str) -> bool:
    candidate = value.strip()
    if not candidate.endswith(".py"):
        return False
    return "/" in candidate or "\\" in candidate or candidate.startswith((".", "/", "\\"))


def _load_python_visual_placeholder(
    path: Path,
    payload: Mapping[str, object],
    stack: Tuple[Path, ...],
) -> BaseVisualConfig:
    """Fail fast when users declare a YAML visual with type: python."""

    raise ValueError(
        "YAML-wrapped Python visuals must set 'type' to a module path like './my_visual.py' "
        "(not 'type: python'). The 'python' pipeline/type is registered dynamically per run."
    )


def register_visual_type(
    type_name: str,
    loader: VisualLoader,
    *,
    overwrite: bool = False,
    cli: VisualCLIOptions | None = None,
    context_model: Type[VisualContextModel] | None = None,
) -> None:
    """Register a loader (and optional CLI metadata) for a visual type."""

    if not isinstance(type_name, str) or not type_name.strip():
        raise ValueError("type_name must be a non-empty string")
    key = type_name.strip().lower()
    if not overwrite and key in _VISUAL_REGISTRY:
        raise ValueError(f"Visual type '{key}' is already registered")
    _VISUAL_REGISTRY[key] = VisualTypeRegistration(loader=loader, cli=cli, context_model=context_model)


def load_visual_definition(
    path: Path | str,
    *,
    base_path: Path | None = None,
    stack: Tuple[Path, ...] | None = None,
) -> BaseVisualConfig:
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

    if _is_python_visual_type(visual_type):
        from praeparo.pipeline import PYTHON_VISUAL_TYPE, register_visual_pipeline
        from praeparo.pipeline.python_visual_loader import load_python_visual_from_yaml

        visual, config = load_python_visual_from_yaml(target, payload)
        register_visual_pipeline(PYTHON_VISUAL_TYPE, visual.to_definition(), overwrite=True)
        register_visual_type(
            PYTHON_VISUAL_TYPE,
            _load_python_visual_placeholder,
            overwrite=True,
            context_model=visual.context_model,
        )
        return config  # type: ignore[return-value]

    key = visual_type.strip().lower()
    registration = _VISUAL_REGISTRY.get(key)
    if registration is None:
        raise ValueError(f"Visual type '{visual_type}' is not registered")

    return registration.loader(target, payload, visit_stack + (target,))


def get_visual_cli_options(type_name: str) -> VisualCLIOptions | None:
    registration = _VISUAL_REGISTRY.get(type_name.strip().lower())
    if registration is None:
        return None
    return registration.cli


def get_visual_registration(type_name: str) -> VisualTypeRegistration | None:
    """Return the registered loader metadata for the supplied visual type."""

    if not isinstance(type_name, str):
        raise TypeError("type_name must be a string")
    key = type_name.strip().lower()
    if not key:
        raise ValueError("type_name must be a non-empty string")
    return _VISUAL_REGISTRY.get(key)


def iter_visual_registrations() -> Iterable[tuple[str, VisualTypeRegistration]]:
    return tuple(_VISUAL_REGISTRY.items())


__all__ = [
    "VisualCLIArgument",
    "VisualCLIOptions",
    "VisualCLIHooks",
    "VisualLoader",
    "VisualTypeRegistration",
    "_is_python_visual_type",
    "get_visual_cli_options",
    "get_visual_registration",
    "iter_visual_registrations",
    "load_visual_definition",
    "register_visual_type",
]

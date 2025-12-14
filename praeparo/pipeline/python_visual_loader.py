"""Shared helpers for loading Python-backed visuals."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Mapping

from pydantic import BaseModel, ConfigDict

from praeparo.models import BaseVisualConfig
from praeparo.paths.registry_root import is_registry_anchored_path, resolve_registry_anchored_path
from praeparo.pipeline.python_visual import PYTHON_VISUAL_TYPE, PythonVisualBase


def load_python_module(path: Path) -> ModuleType:
    """Import and return a module from an arbitrary file path."""

    if not path.exists():
        raise ValueError(f"Python visual module not found: {path}")

    module_name = f"praeparo_python_visual_{path.stem}_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unable to load Python visual module at {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - surfaced to CLI users
        raise RuntimeError(f"Failed to import Python visual module '{path}': {exc}") from exc

    return module


def discover_python_visual(module: ModuleType, *, class_name: str | None = None) -> type[PythonVisualBase]:
    """Locate a PythonVisualBase subclass in *module*."""

    candidates = [
        member
        for member in module.__dict__.values()
        if inspect.isclass(member) and issubclass(member, PythonVisualBase) and member is not PythonVisualBase
    ]

    if class_name:
        for candidate in candidates:
            if candidate.__name__ == class_name:
                return candidate
        available = ", ".join(cls.__name__ for cls in candidates) or "none"
        raise ValueError(f"Python visual class '{class_name}' not found. Available: {available}")

    if not candidates:
        raise ValueError("No PythonVisualBase subclasses were found in the supplied module.")
    if len(candidates) > 1:
        names = ", ".join(cls.__name__ for cls in candidates)
        raise ValueError(f"Multiple Python visuals found; specify one with --visual-class. Options: {names}")

    return candidates[0]


def load_python_visual(path: Path, class_name: str | None = None) -> PythonVisualBase:
    """Import *path* and instantiate the requested Python visual class."""

    module = load_python_module(path)
    visual_cls = discover_python_visual(module, class_name=class_name)

    try:
        instance = visual_cls()
    except Exception as exc:  # pragma: no cover - surfaced to CLI users
        raise RuntimeError(f"Failed to instantiate visual '{visual_cls.__name__}': {exc}") from exc

    if getattr(instance, "context_model", None) is None:
        raise ValueError(f"Python visual '{visual_cls.__name__}' must declare a context_model attribute.")

    return instance


def load_python_visual_module(path: Path, class_name: str | None = None) -> type[PythonVisualBase]:
    """Import *path* and return the declared Python visual class."""

    module = load_python_module(path)
    return discover_python_visual(module, class_name=class_name)


def _default_python_visual_config_model() -> type[BaseVisualConfig]:
    """Fallback config model that accepts arbitrary fields."""

    class _DefaultConfig(BaseVisualConfig):
        model_config = ConfigDict(extra="allow", populate_by_name=True)
        type: str | None = None

    return _DefaultConfig


def load_python_visual_from_yaml(
    context_path: Path,
    payload: Mapping[str, object] | None,
) -> tuple[PythonVisualBase, BaseModel]:
    """Instantiate a Python visual and validate YAML payload against its config model.

    Reserved meta keys (type/schema) are stripped before validation so visuals
    can reuse config models without embedding the YAML discriminator.
    """

    raw_type = str(payload.get("type") or "").strip() if payload is not None else ""
    if is_registry_anchored_path(raw_type):
        module_path = resolve_registry_anchored_path(raw_type, context_path=context_path)
    else:
        module_path = (context_path.parent / raw_type).resolve()

    visual_cls = load_python_visual_module(module_path)
    try:
        visual_instance = visual_cls()
    except Exception as exc:  # pragma: no cover - surfaced to CLI users
        raise RuntimeError(f"Failed to instantiate visual '{visual_cls.__name__}': {exc}") from exc

    if getattr(visual_instance, "context_model", None) is None:
        raise ValueError(f"Python visual '{visual_cls.__name__}' must declare a context_model attribute.")

    config_model = getattr(visual_cls, "config_model", None) or _default_python_visual_config_model()
    if not issubclass(config_model, BaseModel):
        raise TypeError(f"config_model on '{visual_cls.__name__}' must extend BaseModel.")

    reserved_keys = {"type", "schema", "schema_version"}
    config_payload = {k: v for k, v in (payload or {}).items() if k not in reserved_keys}
    config_instance = config_model.model_validate(config_payload)
    try:
        config_instance = config_instance.model_copy(update={"type": PYTHON_VISUAL_TYPE})
    except Exception:
        try:
            object.__setattr__(config_instance, "type", PYTHON_VISUAL_TYPE)
        except Exception as exc:  # pragma: no cover - defensive fallback
            raise TypeError(
                f"Unable to assign pipeline type '{PYTHON_VISUAL_TYPE}' to config model '{config_model.__name__}'."
            ) from exc

    return visual_instance, config_instance


__all__ = [
    "discover_python_visual",
    "load_python_module",
    "load_python_visual",
    "load_python_visual_from_yaml",
    "load_python_visual_module",
]

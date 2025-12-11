"""Shared helpers for loading Python-backed visuals."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

from praeparo.pipeline.python_visual import PythonVisualBase


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


__all__ = ["discover_python_visual", "load_python_module", "load_python_visual"]

"""Registry for plugin-provided DAX compilers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Sequence

from praeparo.dax import DaxQueryPlan
from praeparo.models import BaseVisualConfig
from praeparo.pipeline import ExecutionContext

from .registry import VisualCLIOptions


@dataclass(frozen=True)
class DaxCompileArtifact:
    """Represents a compiled DAX statement ready for persistence."""

    path: Path
    statement: str
    plan: DaxQueryPlan | None = None
    placeholders: Sequence[str] = ()


DaxCompiler = Callable[
    [object, ExecutionContext, argparse.Namespace],
    Sequence[DaxCompileArtifact],
]


@dataclass(frozen=True)
class DaxCompilerRegistration:
    """Associates a compiler function with optional CLI metadata."""

    compiler: DaxCompiler
    cli: VisualCLIOptions | None = None
    description: str | None = None
    loader: Callable[[Path], object] | None = None


_REGISTRY: Dict[str, DaxCompilerRegistration] = {}


def register_dax_compiler(
    type_name: str,
    compiler: DaxCompiler,
    *,
    overwrite: bool = False,
    cli: VisualCLIOptions | None = None,
    description: str | None = None,
    loader: Callable[[Path], object] | None = None,
) -> None:
    """Register a DAX compiler for a given visual type."""

    if not isinstance(type_name, str) or not type_name.strip():
        raise ValueError("type_name must be a non-empty string.")
    key = type_name.strip().lower()
    if not overwrite and key in _REGISTRY:
        raise ValueError(f"DAX compiler '{key}' is already registered.")
    _REGISTRY[key] = DaxCompilerRegistration(
        compiler=compiler,
        cli=cli,
        description=description,
        loader=loader,
    )


def get_dax_compiler_registration(type_name: str) -> DaxCompilerRegistration | None:
    """Return the registered compiler metadata for *type_name*."""

    if not isinstance(type_name, str):
        raise TypeError("type_name must be a string")
    key = type_name.strip().lower()
    if not key:
        raise ValueError("type_name must be a non-empty string")
    return _REGISTRY.get(key)


def iter_dax_compiler_registrations() -> Iterable[tuple[str, DaxCompilerRegistration]]:
    """Iterate over registered DAX compiler metadata."""

    return tuple(_REGISTRY.items())


__all__ = [
    "DaxCompileArtifact",
    "DaxCompiler",
    "DaxCompilerRegistration",
    "get_dax_compiler_registration",
    "iter_dax_compiler_registrations",
    "register_dax_compiler",
]

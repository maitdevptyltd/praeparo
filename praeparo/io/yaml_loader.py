"""YAML loaders that validate against Praeparo models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..models import MatrixConfig


class ConfigLoadError(RuntimeError):
    """Raised when a configuration file cannot be parsed or validated."""


def load_matrix_config(path: Path) -> MatrixConfig:
    """Load and validate a matrix YAML file."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Failed to read configuration: {path}"
        raise ConfigLoadError(msg) from exc

    try:
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML syntax in {path}"
        raise ConfigLoadError(msg) from exc

    if not isinstance(data, dict):
        msg = f"Expected mapping at document root in {path}, found {type(data).__name__}."
        raise ConfigLoadError(msg)

    try:
        return MatrixConfig.model_validate(data)
    except ValidationError as exc:
        msg = f"Configuration validation failed for {path}"
        raise ConfigLoadError(msg) from exc


__all__ = ["ConfigLoadError", "load_matrix_config"]

"""Loader utilities for pack configurations."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Any

import yaml
from pydantic import ValidationError

from praeparo.models import PackConfig


class PackConfigError(ValueError):
    """Raised when a pack configuration cannot be loaded or validated."""


def load_pack_config(path: Path) -> PackConfig:
    """Load and validate a pack configuration from YAML."""

    resolved = path.expanduser().resolve()
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced in CLI
        msg = f"Failed to read pack configuration at {resolved}"
        raise PackConfigError(msg) from exc

    try:
        payload: Any = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - surfaced in CLI
        msg = f"Invalid YAML in pack configuration {resolved}"
        raise PackConfigError(msg) from exc

    if not isinstance(payload, Mapping):
        msg = f"Pack configuration must be a mapping at {resolved}"
        raise PackConfigError(msg)

    try:
        return PackConfig.model_validate(payload)
    except ValidationError as exc:  # pragma: no cover - surfaced in CLI
        raise PackConfigError(str(exc)) from exc


__all__ = ["PackConfigError", "load_pack_config"]

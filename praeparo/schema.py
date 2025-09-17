"""Utilities for exporting JSON schemas from Praeparo models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import MatrixConfig


def matrix_json_schema() -> dict[str, Any]:
    """Return the JSON schema for matrix configurations."""

    return MatrixConfig.model_json_schema()


def write_matrix_schema(path: Path) -> None:
    """Write the matrix configuration schema to *path*."""

    schema = matrix_json_schema()
    path.write_text(json.dumps(schema, indent=2), encoding="utf-8")


__all__ = ["matrix_json_schema", "write_matrix_schema"]

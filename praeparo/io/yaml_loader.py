"""YAML loaders that validate against Praeparo models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import re

import yaml
from pydantic import ValidationError

from ..models import MatrixConfig
from ..templating import render_template


class ConfigLoadError(RuntimeError):
    """Raised when a configuration file cannot be parsed or validated."""



PLACEHOLDER_RE = re.compile(r"\{\{\s*(?P<expr>[^}]+?)\s*\}}")

def _clean_placeholder(expression: str) -> str:
    base = expression.split("|", 1)[0].strip()
    return base

def _render_with_context(value: str, context: Mapping[str, str], *, location: str) -> str:
    missing: list[str] = []
    for match in PLACEHOLDER_RE.finditer(value):
        expr = _clean_placeholder(match.group("expr"))
        if expr not in context:
            missing.append(expr)
    rendered = render_template(value, context)
    if missing:
        missing_list = ", ".join(sorted(set(missing)))
        msg = f"Unresolved template variable(s) in {location}: {missing_list}"
        raise ConfigLoadError(msg)
    return rendered
def _merge_dicts(base: dict[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in update.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, Mapping)
        ):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_composed_yaml(path: Path, *, stack: tuple[Path, ...] = ()) -> dict[str, Any]:
    if path in stack:
        joined = " -> ".join(str(item) for item in stack + (path,))
        msg = f"Detected circular composition while loading {joined}"
        raise ConfigLoadError(msg)

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Failed to read configuration: {path}"
        raise ConfigLoadError(msg) from exc

    try:
        data: Any = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML syntax in {path}"
        raise ConfigLoadError(msg) from exc

    if not isinstance(data, dict):
        msg = f"Expected mapping at document root in {path}, found {type(data).__name__}."
        raise ConfigLoadError(msg)

    compose = data.get("compose") or []
    if isinstance(compose, str):
        compose = [compose]
    if not isinstance(compose, list):
        msg = f"compose must be a list when provided ({path})"
        raise ConfigLoadError(msg)

    base: dict[str, Any] = {}
    for entry in compose:
        if not isinstance(entry, str):
            msg = f"compose entries must be strings ({path})"
            raise ConfigLoadError(msg)
        parent_path = (path.parent / entry).resolve()
        base = _merge_dicts(base, _load_composed_yaml(parent_path, stack=stack + (path,)))

    child = {key: value for key, value in data.items() if key != "compose"}
    return _merge_dicts(base, child)


def _build_context(data: Mapping[str, Any], parameters: Mapping[str, Any]) -> dict[str, str]:
    context: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)):
            context[key] = str(value) if not isinstance(value, str) else value
    for key, value in parameters.items():
        context[key] = str(value) if not isinstance(value, str) else value
    return context


def _apply_parameter_templates(data: dict[str, Any], *, context: Mapping[str, str]) -> None:
    rows = data.get("rows")
    if isinstance(rows, list):
        for item in rows:
            if isinstance(item, Mapping):
                label = item.get("label")
                if isinstance(label, str) and "{{" in label:
                    item["label"] = _render_with_context(label, context, location="row label")

    filters = data.get("filters")
    if isinstance(filters, list):
        for item in filters:
            if isinstance(item, Mapping):
                expression = item.get("expression")
                if isinstance(expression, str) and "{{" in expression:
                    item["expression"] = _render_with_context(expression, context, location="filter expression")


def load_matrix_config(path: Path) -> MatrixConfig:
    """Load and validate a matrix YAML file with composition and parameters."""

    merged = _load_composed_yaml(path.resolve())

    parameters = merged.pop("parameters", {}) or {}
    if not isinstance(parameters, dict):
        msg = f"parameters must be a mapping when provided ({path})"
        raise ConfigLoadError(msg)

    context = _build_context(merged, parameters)
    _apply_parameter_templates(merged, context=context)

    try:
        return MatrixConfig.model_validate(merged)
    except ValidationError as exc:
        msg = f"Configuration validation failed for {path}"
        raise ConfigLoadError(msg) from exc


__all__ = ["ConfigLoadError", "load_matrix_config"]


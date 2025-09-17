"""YAML loaders that validate against Praeparo models."""

from __future__ import annotations

import copy
import re
from pathlib import Path

from typing import Annotated, Any, Mapping

import yaml
from pydantic import Field, TypeAdapter, ValidationError

from ..models import BaseVisualConfig, FrameConfig, MatrixConfig
from ..templating import render_template


class ConfigLoadError(RuntimeError):
    """Raised when a configuration file cannot be parsed or validated."""


PLACEHOLDER_RE = re.compile(r"\{\{\s*(?P<expr>[^}]+?)\s*\}}")

ComposeStack = tuple[Path, ...]  # Tracks nested compose references to prevent cycles.
VisualConfigUnion = Annotated[MatrixConfig | FrameConfig, Field(discriminator="type")]
VISUAL_ADAPTER = TypeAdapter(VisualConfigUnion)


def _clean_placeholder(expression: str) -> str:
    """Return the core template variable name before any Jinja filters."""

    base = expression.split("|", 1)[0].strip()
    return base


def _render_with_context(value: str, context: Mapping[str, str], *, location: str) -> str:
    """Render a template string and fail fast if any placeholders lack context."""

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
    """Deep-merge mapping values, favouring overrides for non-mapping entries."""

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


def _load_composed_yaml(path: Path, *, stack: ComposeStack = ()) -> dict[str, Any]:
    """Load a YAML document and resolve its compose chain depth-first."""

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
    """Generate a string-keyed context for template substitution."""

    context: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)):
            context[key] = str(value) if not isinstance(value, str) else value
    for key, value in parameters.items():
        context[key] = str(value) if not isinstance(value, str) else value
    return context


def _apply_parameter_templates(data: dict[str, Any], *, context: Mapping[str, str]) -> None:
    """Inject parameter defaults into templated labels and filters."""

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


def _prepare_payload(
    path: Path,
    data: Mapping[str, Any],
    *,
    overrides: Mapping[str, Any] | None,
    parameters_override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Apply overrides, merge parameters, and render templates prior to validation."""

    payload = copy.deepcopy(dict(data))

    if overrides:
        payload = _merge_dicts(payload, overrides)

    if parameters_override:
        existing = payload.get("parameters", {}) or {}
        if not isinstance(existing, Mapping):
            msg = f"parameters must be a mapping when provided ({path})"
            raise ConfigLoadError(msg)
        normalized_existing = {str(k): v for k, v in existing.items()}
        normalized_override = {str(k): v for k, v in parameters_override.items()}
        payload["parameters"] = {**normalized_existing, **normalized_override}

    parameters = payload.pop("parameters", {}) or {}
    if not isinstance(parameters, Mapping):
        msg = f"parameters must be a mapping when provided ({path})"
        raise ConfigLoadError(msg)

    context = _build_context(payload, parameters)
    _apply_parameter_templates(payload, context=context)

    return payload


def _finalize_visual(
    path: Path,
    payload: dict[str, Any],
    *,
    stack: ComposeStack,
) -> BaseVisualConfig:
    """Validate the prepared payload and resolve any nested visual references."""

    # Default to matrix for legacy documents that omit the visual discriminator.
    payload.setdefault("type", "matrix")

    try:
        visual = VISUAL_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        msg = f"Configuration validation failed for {path}"
        raise ConfigLoadError(msg) from exc

    def _load_child(
        target_path: Path,
        child_overrides: Mapping[str, Any] | None,
        child_parameters: Mapping[str, Any] | None,
        child_stack: ComposeStack,
    ) -> BaseVisualConfig:
        """Recursively load child visuals while preserving the compose stack."""

        return load_visual_config(
            target_path,
            overrides=child_overrides,
            parameters_override=child_parameters,
            stack=child_stack,
        )

    return visual.resolve(load_visual=_load_child, path=path, stack=stack)


def load_visual_config(
    path: Path,
    *,
    overrides: Mapping[str, Any] | None = None,
    parameters_override: Mapping[str, Any] | None = None,
    stack: ComposeStack | None = None,
) -> BaseVisualConfig:
    """Load a visual, applying overrides and resolving compose/child references."""

    resolved = path.resolve()
    compose_stack: ComposeStack = stack or ()
    # Resolve any declared compose chain before validation.
    merged = _load_composed_yaml(resolved, stack=compose_stack)
    payload = _prepare_payload(
        resolved,
        merged,
        overrides=overrides,
        parameters_override=parameters_override,
    )

    return _finalize_visual(resolved, payload, stack=compose_stack)


def load_matrix_config(
    path: Path,
    *,
    parameters_override: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
    stack: ComposeStack | None = None,
) -> MatrixConfig:
    """Load and validate a matrix YAML file."""

    visual = load_visual_config(
        path,
        overrides=overrides,
        parameters_override=parameters_override,
        stack=stack,
    )
    if not isinstance(visual, MatrixConfig):
        msg = f"Expected matrix visual but found type '{visual.type}' in {path}"
        raise ConfigLoadError(msg)
    return visual


__all__ = ["ConfigLoadError", "load_matrix_config", "load_visual_config"]

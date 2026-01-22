"""Metric composition helpers.

Phase 1.5 introduces reusable YAML "components" that can be composed into metrics
without changing the metric registry discovery rules. Components live outside
the metrics root (for example `registry/components/**`) and are only loaded when
referenced by a metric's `compose:` list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from praeparo.metrics.models import MetricExplainSpec


class MetricComponentError(ValueError):
    """Raised when a metric component cannot be resolved or validated."""


_COMPONENT_SCHEMA = "component-draft-1"
_ALLOWED_COMPONENT_KEYS = {"explain"}
_FORBIDDEN_COMPONENT_KEYS = {
    # Identity and publishing fields that must stay metric-owned.
    "key",
    "display_name",
    "section",
    "description",
    "define",
    "expression",
    "variants",
    "ratios",
    "format",
    "value_type",
    "tags",
    "notes",
    # Composition itself is metric-owned in Phase 1.5.
    "compose",
}


@dataclass(frozen=True)
class MetricComponentLayer:
    """Validated component payload that can be merged into a metric layer."""

    path: Path
    explain: MetricExplainSpec | None = None


def resolve_component_path(ref: str, *, declaring_file: Path) -> Path:
    """Resolve a component reference to an absolute path.

    - `@/…` refs are anchored to a derived project root.
    - Other refs are resolved relative to the YAML file that declared them.
    """

    if not ref or not ref.strip():
        raise MetricComponentError(f"{declaring_file}: compose reference cannot be empty.")

    candidate = ref.strip()
    if Path(candidate).is_absolute() and not candidate.startswith("@/"):
        raise MetricComponentError(
            f"{declaring_file}: compose reference must be relative or start with '@/': {ref!r}"
        )

    if candidate.startswith("@/"):
        project_root = _derive_project_root(declaring_file)
        resolved = (project_root / candidate[2:]).resolve()
    else:
        resolved = (declaring_file.parent / candidate).resolve()
    return resolved


def _derive_project_root(declaring_file: Path) -> Path:
    """Derive the project root for `@/…` anchored references.

    We infer the root from the declaring file location so `@/…` behaves
    consistently when the metrics root is either `registry/metrics` or `metrics`.
    """

    resolved = declaring_file.resolve()

    # Prefer the conventional `registry/metrics` shape: project root is the parent
    # of `registry/`.
    for parent in resolved.parents:
        if parent.name == "metrics" and parent.parent.name == "registry":
            return parent.parent.parent

    # Fall back to `metrics` living at the project root (or nested under it).
    for parent in resolved.parents:
        if parent.name == "metrics":
            return parent.parent

    # If we cannot infer a project root, treat the declaring directory as the root
    # so relative behaviour remains predictable in ad-hoc layouts.
    return resolved.parent


def load_component_payload(path: Path) -> MetricComponentLayer:
    """Load and validate a component YAML file."""

    if not path.exists():
        raise FileNotFoundError(str(path))

    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:  # pragma: no cover - parser errors surface
        raise MetricComponentError(f"{path}: failed to parse YAML: {exc}") from exc

    if payload is None:
        raise MetricComponentError(f"{path}: component document is empty.")
    if not isinstance(payload, Mapping):
        raise MetricComponentError(f"{path}: component document must define a mapping object.")

    document = dict(payload)
    schema = document.pop("schema", None)
    if schema != _COMPONENT_SCHEMA:
        raise MetricComponentError(
            f"{path}: component schema must be '{_COMPONENT_SCHEMA}' (got {schema!r})."
        )

    unexpected = set(document) - _ALLOWED_COMPONENT_KEYS
    if unexpected:
        forbidden = sorted(unexpected & _FORBIDDEN_COMPONENT_KEYS)
        if forbidden:
            raise MetricComponentError(
                f"{path}: component may not define metric identity keys: {forbidden}."
            )
        raise MetricComponentError(
            f"{path}: component contains unsupported keys: {sorted(unexpected)}. "
            f"Allowed keys are: {sorted(_ALLOWED_COMPONENT_KEYS)}."
        )

    if not document:
        raise MetricComponentError(
            f"{path}: component does not define any supported keys ({sorted(_ALLOWED_COMPONENT_KEYS)})."
        )

    explain_payload = document.get("explain")
    explain = MetricExplainSpec.model_validate(explain_payload) if explain_payload is not None else None
    return MetricComponentLayer(path=path, explain=explain)


class MetricComponentLoader:
    """Cache component reads so metric composition stays deterministic and cheap."""

    def __init__(self) -> None:
        self._cache: dict[Path, MetricComponentLayer] = {}

    def load(self, ref: str, *, declaring_file: Path) -> MetricComponentLayer:
        """Resolve + load a component reference."""

        path = resolve_component_path(ref, declaring_file=declaring_file)
        cached = self._cache.get(path)
        if cached is not None:
            return cached

        try:
            layer = load_component_payload(path)
        except FileNotFoundError as exc:
            raise MetricComponentError(
                f"{declaring_file}: compose reference {ref!r} not found at {path}"
            ) from exc

        self._cache[path] = layer
        return layer


__all__ = [
    "MetricComponentError",
    "MetricComponentLayer",
    "MetricComponentLoader",
    "load_component_payload",
    "resolve_component_path",
]


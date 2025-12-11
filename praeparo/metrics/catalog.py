"""Helpers for discovering and loading Praeparo metric definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import yaml

from ..inheritance import validate_extends_graph
from .models import MetricDefinition, MetricVariant


_SUPPORTED_EXTENSIONS = {".yaml", ".yml"}


@dataclass
class MetricCatalog:
    """Container of parsed metric definitions and their variant metadata."""

    metrics: dict[str, MetricDefinition]
    sources: dict[str, Path]
    files: list[Path]
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        variant_lookup: dict[str, tuple[str, MetricVariant]] = {}
        relative_variants: dict[str, set[str]] = {}

        for metric_key, metric in self.metrics.items():
            flat_variants = metric.flattened_variants()
            if flat_variants:
                relative_variants[metric_key] = set(flat_variants.keys())
            for variant_path, variant in flat_variants.items():
                full_key = f"{metric_key}.{variant_path}"
                variant_lookup[full_key] = (metric_key, variant)

        self._variant_lookup = variant_lookup
        self._relative_variants = relative_variants

    def metric_keys(self) -> set[str]:
        """Return the set of metric identifiers in the catalog."""

        return set(self.metrics.keys())

    def variant_keys(self) -> set[str]:
        """Return the set of fully qualified variant keys (metric.variant...)."""

        return set(self._variant_lookup.keys())

    def contains(self, key: str) -> bool:
        """Return True if the catalog contains the metric or variant reference."""

        if key in self.metrics:
            return True
        return key in self._variant_lookup

    def get_metric(self, key: str) -> MetricDefinition | None:
        """Retrieve a metric definition by key."""

        return self.metrics.get(key)

    def get_variant(self, key: str) -> MetricVariant | None:
        """Retrieve a variant by its fully qualified key (metric.variant)."""

        entry = self._variant_lookup.get(key)
        if entry is None:
            return None
        _, variant = entry
        return variant

    def has_variant(self, metric_key: str, variant_key: str) -> bool:
        """Return True if the metric defines the supplied variant path."""

        if metric_key not in self.metrics:
            return False
        relative = variant_key
        if variant_key.startswith(f"{metric_key}."):
            relative = variant_key[len(metric_key) + 1 :]
        allowed = self._relative_variants.get(metric_key, set())
        return relative in allowed

    def full_variant_keys_for(self, metric_key: str) -> set[str]:
        """Return fully qualified variant keys for a metric."""

        prefix = f"{metric_key}."
        return {key for key in self._variant_lookup if key.startswith(prefix)}


class MetricDiscoveryError(Exception):
    """Raised when metric discovery encounters parsing or validation issues."""

    def __init__(self, errors: Sequence[str], catalog: MetricCatalog | None = None):
        message = f"Encountered {len(errors)} error(s) while loading metric definitions. {errors}"
        super().__init__(message)
        self.errors = list(errors)
        self.catalog = catalog


def discover_metric_files(targets: Iterable[Path | str]) -> list[Path]:
    """Return a sorted list of metric YAML files discovered under the targets."""

    discovered: list[Path] = []
    seen: set[str] = set()

    for target in targets:
        path = Path(target)
        if path.is_file():
            if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                raise ValueError(f"Unsupported file extension for {path}")
            key = str(path.resolve())
            if key not in seen:
                discovered.append(path)
                seen.add(key)
            continue

        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        for pattern in ("*.yaml", "*.yml"):
            for candidate in path.rglob(pattern):
                key = str(candidate.resolve())
                if key not in seen:
                    discovered.append(candidate)
                    seen.add(key)

    return sorted(discovered, key=lambda item: str(item))


def load_metric_catalog(targets: Iterable[Path | str], *, raise_on_error: bool = True) -> MetricCatalog:
    """Parse metric YAML documents into a catalog, optionally raising on validation errors."""

    files = discover_metric_files(targets)
    registry: dict[str, MetricDefinition] = {}
    sources: dict[str, Path] = {}
    parsed_files: list[Path] = []
    errors: list[str] = []

    for file_path in files:
        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{file_path}: {exc}")
            continue

        try:
            payload = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            errors.append(f"{file_path}: {exc}")
            continue

        if payload is None:
            errors.append(f"{file_path}: document is empty")
            continue

        try:
            metric = MetricDefinition.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{file_path}: {exc}")
            continue

        if metric.key in registry:
            errors.append(
                f"{file_path}: duplicate metric key '{metric.key}' also defined in {sources[metric.key]}"
            )
            continue

        registry[metric.key] = metric
        sources[metric.key] = file_path
        parsed_files.append(file_path)

    errors.extend(
        validate_extends_graph(
            registry,
            sources,
            get_parent=lambda metric: metric.extends,
        )
    )

    catalog = MetricCatalog(metrics=registry, sources=sources, files=parsed_files)
    if errors and raise_on_error:
        raise MetricDiscoveryError(errors, catalog)

    if errors:
        # Attach errors for callers that opt into non-raising mode.
        catalog.errors = errors

    return catalog

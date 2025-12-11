"""Builder context discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence, TYPE_CHECKING

from praeparo.visuals.context_models import VisualContextModel
from praeparo.visuals.dax import DEFAULT_MEASURE_TABLE, normalise_define_blocks, normalise_filter_group

if TYPE_CHECKING:
    from praeparo.pipeline import ExecutionContext


def _ensure_path(value: str | Path | None, *, default: Path) -> Path:
    """Return *value* as a resolved path, falling back to *default* when missing."""

    if value is None:
        return default.expanduser().resolve(strict=False)
    candidate = Path(value)
    return candidate.expanduser().resolve(strict=False)


def _discover_metrics_root(project_root: Path) -> Path:
    """Find the most likely metrics directory relative to *project_root*."""

    candidates = [project_root / "registry" / "metrics", project_root / "metrics"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return project_root


def resolve_default_metrics_root_for_pack(pack_path: Path) -> Path:
    """Return a sensible default metrics_root for a pack file."""

    current = pack_path.parent
    for _ in range(5):
        candidate = current / "registry" / "metrics"
        if candidate.is_dir():
            return candidate.resolve()
        candidate = current / "metrics"
        if candidate.is_dir():
            return candidate.resolve()
        if current.parent == current:
            break
        current = current.parent

    return _discover_metrics_root(pack_path.parent).resolve()


def _discover_datasources_root(project_root: Path) -> Path | None:
    """Return the first datasources folder under *project_root*, if any."""

    candidate = project_root / "datasources"
    return candidate if candidate.is_dir() else None


def _select_datasource_file(datasources_root: Path | None) -> Path | None:
    """Heuristically choose a datasource YAML file from *datasources_root*."""

    if datasources_root is None or not datasources_root.is_dir():
        return None

    priority = ("live", "prod", "default")
    yaml_files = sorted(datasources_root.glob("*.yml")) + sorted(datasources_root.glob("*.yaml"))

    for stem in priority:
        for candidate in yaml_files:
            if candidate.stem == stem:
                return candidate

    return yaml_files[0] if len(yaml_files) == 1 else None


def normalise_filters(filters: Sequence[str] | str | None) -> tuple[str, ...]:
    """Expose filter normalisation so builder code can reuse the same helper."""

    return normalise_filter_group(filters)


@dataclass(frozen=True)
class MetricDatasetBuilderContext:
    """Resolved environment information used by the metric dataset builder."""

    project_root: Path
    metrics_root: Path
    datasources_root: Path | None = None
    datasource_file: Path | None = None
    default_datasource: str | None = None
    case_key: str | None = None
    measure_table: str = DEFAULT_MEASURE_TABLE
    ignore_placeholders: bool = False
    global_filters: tuple[str, ...] = field(default_factory=tuple)
    define_blocks: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, object] = field(default_factory=dict)
    use_mock: bool = False

    @classmethod
    def discover(
        cls,
        *,
        project_root: str | Path | None = None,
        metrics_root: str | Path | None = None,
        datasources_root: str | Path | None = None,
        datasource_file: str | Path | None = None,
        default_datasource: str | None = None,
        case_key: str | None = None,
        measure_table: str | None = None,
        ignore_placeholders: bool = False,
        calculate: Sequence[str] | str | None = None,
        define: Sequence[str] | str | None = None,
        metadata: Mapping[str, object] | None = None,
        use_mock: bool = False,
        visual_context: VisualContextModel | None = None,
    ) -> "MetricDatasetBuilderContext":
        """Resolve the builder context by inspecting the caller's working tree."""

        base = _ensure_path(project_root, default=Path.cwd().resolve())
        metrics_path = _ensure_path(metrics_root, default=_discover_metrics_root(base))

        if datasources_root is None:
            datasources_path = _discover_datasources_root(base)
        else:
            datasources_path = _ensure_path(datasources_root, default=Path(datasources_root))

        if datasource_file is not None:
            datasource_path = _ensure_path(datasource_file, default=Path(datasource_file))
        else:
            datasource_path = _select_datasource_file(datasources_path)

        default_reference = default_datasource
        if default_reference is None and datasource_path is not None:
            default_reference = str(datasource_path)

        context_filters: tuple[str, ...] = tuple()
        define_blocks: tuple[str, ...] = tuple()

        if visual_context is not None:
            context_filters = normalise_filters(visual_context.dax.calculate)
            define_blocks = normalise_define_blocks(visual_context.dax.define)

        calculate_overrides = normalise_filters(calculate)
        define_overrides = normalise_define_blocks(define)

        if calculate_overrides:
            context_filters = tuple(context_filters) + tuple(calculate_overrides) if context_filters else tuple(calculate_overrides)
        if define_overrides:
            define_blocks = tuple(define_blocks) + tuple(define_overrides) if define_blocks else tuple(define_overrides)

        return cls(
            project_root=base,
            metrics_root=metrics_path,
            datasources_root=datasources_path,
            datasource_file=datasource_path,
            default_datasource=default_reference,
            case_key=case_key,
            measure_table=measure_table or DEFAULT_MEASURE_TABLE,
            ignore_placeholders=ignore_placeholders,
            global_filters=context_filters,
            define_blocks=define_blocks,
            metadata=dict(metadata or {}),
            use_mock=use_mock,
        )


def _resolve_provider_key(execution: "ExecutionContext[VisualContextModel]") -> str | None:
    """Resolve the provider key with case-specific overrides."""

    data_options = execution.options.data
    overrides = getattr(data_options, "provider_case_overrides", {}) or {}

    if execution.case_key and execution.case_key in overrides:
        candidate = overrides[execution.case_key].strip().lower()
        if candidate:
            return candidate

    provider_key = getattr(data_options, "provider_key", None)
    if provider_key:
        candidate = provider_key.strip().lower()
        if candidate:
            return candidate

    return None


def discover_dataset_context(
    execution: "ExecutionContext[VisualContextModel]",
    *,
    default_metrics_root: Path | None = None,
) -> MetricDatasetBuilderContext:
    """Derive a MetricDatasetBuilderContext from pipeline execution state."""

    project_root = execution.project_root or (execution.config_path.parent if execution.config_path else Path.cwd())
    visual_context = execution.visual_context
    metadata = execution.options.metadata or {}

    # Prefer the visual-provided metrics root; otherwise fall back to caller hints or discovery.
    if visual_context is not None:
        metrics_root = visual_context.metrics_root
    elif default_metrics_root is not None:
        metrics_root = default_metrics_root
    else:
        metrics_root = _discover_metrics_root(project_root)

    use_mock = _resolve_provider_key(execution) == "mock"
    # The CLI/pack flag (--ignore-placeholders) flows via metadata for YAML-wrapped Python visuals
    # that do not declare a typed visual context. Prefer the typed context when present; otherwise
    # fall back to metadata so pack runs still honour the flag.
    ignore_placeholders = False
    if visual_context is not None:
        ignore_placeholders = bool(getattr(visual_context, "ignore_placeholders", False))
    if not ignore_placeholders:
        ignore_placeholders = bool(metadata.get("ignore_placeholders", False))

    return MetricDatasetBuilderContext.discover(
        project_root=project_root,
        metrics_root=metrics_root,
        default_datasource=execution.options.data.datasource_override,
        case_key=execution.case_key,
        ignore_placeholders=ignore_placeholders,
        visual_context=visual_context,
        metadata=metadata,
        use_mock=use_mock,
    )

__all__ = ["MetricDatasetBuilderContext", "discover_dataset_context", "normalise_filters"]

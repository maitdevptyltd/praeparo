"""Pack post-run evidence exports.

This module automates `praeparo-metrics explain` evidence exports after a pack
run completes. Packs opt in via `PackConfig.evidence`.

The runner is intentionally generic:

- Visual binding adapters emit `VisualMetricBinding.metadata` keys.
- Packs select bindings by the presence of those keys (for example `sla`).

The implementation reuses the same explain plan + executor surfaces as the
interactive CLI so evidence exports remain reproducible and traceable.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from jinja2 import Environment

from praeparo.metrics import MetricCatalog
from praeparo.metrics.explain import build_metric_binding_explain_plan
from praeparo.metrics.explain_runner import MetricExplainOutputs, run_explain_plan, write_explain_dax, write_summary_json
from praeparo.models import PackEvidenceConfig
from praeparo.pack.templating import render_value
from praeparo.powerbi import PowerBISettings
from praeparo.datasources import ResolvedDataSource, resolve_datasource
from praeparo.visuals import resolve_dax_context
from praeparo.visuals.bindings import VisualMetricBinding
from praeparo.visuals.dax import normalise_filter_group, slugify
from praeparo.visuals.metrics import CalculateInput

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PackEvidenceTarget:
    """Single binding instance selected for evidence export."""

    target_key: str
    selector_identifier: str
    visual_token: str
    slide_slug: str
    slide_id: str | None
    slide_index: int
    placeholder_id: str | None
    binding: VisualMetricBinding
    context_payload: Mapping[str, object]
    context_calculate_filters: tuple[str, ...]
    context_define_blocks: tuple[str, ...]
    numerator_define_filters: tuple[str, ...]


def select_evidence_bindings(
    bindings: Sequence[VisualMetricBinding],
    *,
    selector: PackEvidenceConfig,
) -> tuple[VisualMetricBinding, ...]:
    """Apply attribute selection plus include/exclude ordering to a bindings list."""

    select_keys = tuple(selector.bindings.select)
    mode = selector.bindings.select_mode
    include_ids = set(selector.bindings.include)
    exclude_ids = set(selector.bindings.exclude)

    def matches(binding: VisualMetricBinding) -> bool:
        if not select_keys:
            return True
        metadata = binding.metadata
        if mode == "all":
            return all(key in metadata for key in select_keys)
        return any(key in metadata for key in select_keys)

    by_id: dict[str, VisualMetricBinding] = {binding.binding_id: binding for binding in bindings}

    selected_ids: set[str] = {binding.binding_id for binding in bindings if matches(binding)}

    # Force-include explicitly referenced ids (when they exist in the adapter output).
    for binding_id in include_ids:
        if binding_id in by_id:
            selected_ids.add(binding_id)

    # Apply force-exclude last.
    selected_ids.difference_update(exclude_ids)

    # Preserve adapter order so manifests remain stable across reruns.
    ordered = [binding for binding in bindings if binding.binding_id in selected_ids]
    return tuple(ordered)


def derive_evidence_outputs(
    *,
    artefact_dir: Path,
    slide_slug: str,
    placeholder_id: str | None,
    binding: VisualMetricBinding,
) -> MetricExplainOutputs:
    """Return per-binding output paths under the pack evidence directory."""

    placeholder_token = placeholder_id or "visual"
    binding_dir = artefact_dir / slide_slug / placeholder_token / slugify(binding.binding_id)

    evidence_path = binding_dir / "evidence.csv"
    dax_path = binding_dir / "_artifacts" / "explain.dax"
    summary_path = binding_dir / "_artifacts" / "summary.json"
    return MetricExplainOutputs(
        artefact_dir=binding_dir / "_artifacts",
        evidence_path=evidence_path,
        dax_path=dax_path,
        summary_path=summary_path,
    )


def derive_flat_evidence_output_path(
    *,
    artefact_dir: Path,
    slide_slug: str,
    placeholder_id: str | None,
    binding: VisualMetricBinding,
) -> Path:
    """Return the root-level sibling CSV path for quick evidence access."""

    placeholder_token = placeholder_id or "visual"
    binding_slug = slugify(binding.binding_id)
    return artefact_dir / slide_slug / placeholder_token / f"{binding_slug}.csv"


def migrate_legacy_evidence_filename(*, outputs: MetricExplainOutputs, metric_slug: str) -> None:
    """Promote legacy `evidence_<metric_slug>.csv` files to `evidence.csv`."""

    if outputs.evidence_path.exists():
        return

    legacy_path = outputs.evidence_path.with_name(f"evidence_{metric_slug}.csv")
    if not legacy_path.exists():
        return

    outputs.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.replace(outputs.evidence_path)


def sync_flat_evidence_output(*, evidence_path: Path, flat_path: Path, overwrite: bool) -> None:
    """Copy canonical evidence into the root-level flat alias path."""

    if not evidence_path.exists():
        return

    if evidence_path == flat_path:
        return

    flat_path.parent.mkdir(parents=True, exist_ok=True)
    if flat_path.exists() and not overwrite:
        return

    shutil.copy2(evidence_path, flat_path)


def compute_inputs_fingerprint(payload: Mapping[str, object]) -> str:
    """Hash a JSON-serialisable payload into a stable fingerprint string."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_manifest_fingerprints(path: Path) -> dict[str, str]:
    """Load prior target_key -> fingerprint mapping from an existing manifest.json."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    bindings = payload.get("bindings")
    if not isinstance(bindings, list):
        return {}

    fingerprints: dict[str, str] = {}
    for entry in bindings:
        if not isinstance(entry, dict):
            continue
        key = entry.get("target_key")
        fingerprint = entry.get("fingerprint")
        if isinstance(key, str) and isinstance(fingerprint, str):
            fingerprints[key] = fingerprint
    return fingerprints


def should_skip_existing(
    *,
    target_key: str,
    fingerprint: str,
    prior_fingerprints: Mapping[str, str],
    outputs: MetricExplainOutputs,
) -> bool:
    prior = prior_fingerprints.get(target_key)
    if prior is None or prior != fingerprint:
        return False
    return outputs.evidence_path.exists() and outputs.dax_path.exists() and outputs.summary_path.exists()


def render_evidence_output_dir(
    *,
    config: PackEvidenceConfig,
    env: Environment,
    context: Mapping[str, object],
) -> Path:
    rendered = render_value(config.output_dir, env=env, context=context)
    if not isinstance(rendered, str):
        raise ValueError("evidence.output_dir must render to a string value.")
    candidate = rendered.strip()
    if not candidate:
        raise ValueError("evidence.output_dir cannot be empty after templating.")
    path = Path(candidate)
    if path.is_absolute():
        raise ValueError("evidence.output_dir must be relative to the pack artefact directory.")
    return path


ContextFragment = str | Mapping[str, str]


def flatten_context_fragments(value: object | None, *, label: str) -> list[ContextFragment]:
    """Flatten rendered calculate/define payloads into mergeable context fragments."""

    if value is None:
        return []
    if isinstance(value, str):
        candidate = value.strip()
        return [candidate] if candidate else []
    if isinstance(value, Mapping):
        flattened_mapping: dict[str, str] = {}
        for key, raw in value.items():
            if raw is None:
                continue
            if not isinstance(raw, str):
                raise TypeError(f"{label} context mapping values must be strings.")
            candidate = raw.strip()
            if candidate:
                flattened_mapping[str(key)] = candidate
        return [flattened_mapping] if flattened_mapping else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        flattened: list[ContextFragment] = []
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, str):
                candidate = entry.strip()
                if candidate:
                    flattened.append(candidate)
                continue
            if isinstance(entry, Mapping):
                flattened.extend(flatten_context_fragments(entry, label=label))
                continue
            raise TypeError(f"{label} context entries must be strings or mappings.")
        return flattened
    raise TypeError(f"{label} context entries must be strings, mappings, or sequences thereof.")


def build_pack_evidence_target(
    *,
    pack_token: str,
    visual_token: str,
    slide_slug: str,
    slide_id: str | None,
    slide_index: int,
    placeholder_id: str | None,
    binding: VisualMetricBinding,
    env: Environment,
    context_payload: Mapping[str, object],
    context_calculate: CalculateInput | None,
    context_define: CalculateInput | None,
) -> PackEvidenceTarget:
    """Normalise per-binding context inputs into an explain-ready target."""

    selector_identifier = _format_binding_identifier(
        base_token=pack_token,
        slide_id=slide_id,
        slide_index=slide_index,
        placeholder_id=placeholder_id,
        binding_segments=binding.selector_segments,
    )

    calculate_filters, define_blocks = resolve_dax_context(
        base=context_payload,
        calculate=context_calculate,
        define=context_define,
    )

    rendered_binding_define = normalise_filter_group(
        render_value(binding.calculate.define or None, env=env, context=context_payload)
        if binding.calculate.define
        else None
    )

    placeholder_token = placeholder_id or "visual"
    target_key = f"{slide_slug}/{placeholder_token}/{slugify(binding.binding_id)}"
    return PackEvidenceTarget(
        target_key=target_key,
        selector_identifier=selector_identifier,
        visual_token=visual_token,
        slide_slug=slide_slug,
        slide_id=slide_id,
        slide_index=slide_index,
        placeholder_id=placeholder_id,
        binding=binding,
        context_payload=context_payload,
        context_calculate_filters=calculate_filters,
        context_define_blocks=define_blocks,
        numerator_define_filters=tuple(rendered_binding_define),
    )


def run_pack_evidence_exports(
    *,
    config: PackEvidenceConfig,
    catalog: MetricCatalog,
    pack_path: Path,
    artefact_dir: Path,
    env: Environment,
    output_dir_context: Mapping[str, object],
    datasource: ResolvedDataSource | None,
    data_mode: str,
    targets: Sequence[PackEvidenceTarget],
) -> tuple[Path, list[dict[str, object]], bool]:
    """Execute all planned evidence targets and write a pack-level manifest.

    Returns (manifest_path, manifest_bindings_entries, has_failures).
    """

    evidence_root = artefact_dir / render_evidence_output_dir(config=config, env=env, context=output_dir_context)
    evidence_root.mkdir(parents=True, exist_ok=True)
    manifest_path = evidence_root / "manifest.json"

    prior_fingerprints = load_manifest_fingerprints(manifest_path) if config.explain.skip_existing else {}
    include_ids = set(config.bindings.include)

    datasource_payload = None
    if datasource is not None:
        datasource_payload = {
            "name": datasource.name,
            "type": datasource.type,
            "dataset_id": datasource.dataset_id,
            "workspace_id": datasource.workspace_id,
            "source_path": str(datasource.source_path) if datasource.source_path else None,
        }

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()

    has_failures = False
    manifest_bindings: list[dict[str, object]] = []

    logger.info(
        "Starting pack evidence exports",
        extra={
            "pack_path": str(pack_path),
            "artefact_dir": str(artefact_dir),
            "output_dir": str(config.output_dir),
            "evidence_root": str(evidence_root),
            "target_count": len(targets),
            "select": list(config.bindings.select),
            "select_mode": config.bindings.select_mode,
            "include_count": len(config.bindings.include),
            "exclude_count": len(config.bindings.exclude),
            "when": config.when,
            "on_error": config.on_error,
            "data_mode": data_mode,
            "max_concurrency": config.explain.max_concurrency,
            "skip_existing": config.explain.skip_existing,
            "limit": config.explain.limit,
            "variant_mode": config.explain.variant_mode,
        },
    )

    def _execute_target(target: PackEvidenceTarget, *, index: int, total: int) -> dict[str, object]:
        nonlocal has_failures

        binding = target.binding
        metric_key = binding.metric_key
        metric_slug = slugify(metric_key or binding.binding_id)

        logger.info(
            "Exporting evidence",
            extra={
                "pack_path": str(pack_path),
                "target": target.target_key,
                "ordinal": f"{index}/{total}",
                "slide_slug": target.slide_slug,
                "placeholder_id": target.placeholder_id,
                "binding_id": binding.binding_id,
                "metric_key": metric_key,
            },
        )

        outputs = derive_evidence_outputs(
            artefact_dir=evidence_root,
            slide_slug=target.slide_slug,
            placeholder_id=target.placeholder_id,
            binding=binding,
        )
        flat_evidence_path = derive_flat_evidence_output_path(
            artefact_dir=evidence_root,
            slide_slug=target.slide_slug,
            placeholder_id=target.placeholder_id,
            binding=binding,
        )
        migrate_legacy_evidence_filename(outputs=outputs, metric_slug=metric_slug)

        plan = None
        plan_statement_fingerprint = None
        if metric_key is not None:
            # Build the explain plan up-front so fingerprinting reflects metric-definition
            # changes (measure expression, metric.calculate predicates, explain.where tweaks, etc.).
            plan = build_metric_binding_explain_plan(
                catalog,
                metric_reference=metric_key,
                metric_identifier=target.selector_identifier,
                context_calculate_filters=target.context_calculate_filters,
                context_define_blocks=target.context_define_blocks,
                limit=int(config.explain.limit),
                variant_mode=config.explain.variant_mode,
                numerator_define_filters=target.numerator_define_filters,
                ratio_to=binding.ratio_to,
                visual_path=target.visual_token,
                binding_id=binding.binding_id,
                binding_label=binding.label,
            )
            plan_statement_fingerprint = compute_inputs_fingerprint({"statement": plan.statement})

        fingerprint_payload: dict[str, object] = {
            "selector_identifier": target.selector_identifier,
            "visual_token": target.visual_token,
            "slide_index": target.slide_index,
            "slide_id": target.slide_id,
            "slide_slug": target.slide_slug,
            "placeholder_id": target.placeholder_id,
            "binding_id": binding.binding_id,
            "selector_segments": list(binding.selector_segments),
            "metric_key": metric_key,
            "ratio_to": binding.ratio_to,
            "context_calculate_filters": list(target.context_calculate_filters),
            "context_define_blocks": list(target.context_define_blocks),
            "numerator_define_filters": list(target.numerator_define_filters),
            "plan": {"statement_fingerprint": plan_statement_fingerprint} if plan_statement_fingerprint else None,
            "explain": {
                "limit": config.explain.limit,
                "variant_mode": config.explain.variant_mode,
            },
            "datasource": {
                "data_mode": data_mode,
                **(datasource_payload or {}),
            },
        }
        fingerprint = compute_inputs_fingerprint(fingerprint_payload)

        if config.explain.skip_existing and should_skip_existing(
            target_key=target.target_key,
            fingerprint=fingerprint,
            prior_fingerprints=prior_fingerprints,
            outputs=outputs,
        ):
            sync_flat_evidence_output(
                evidence_path=outputs.evidence_path,
                flat_path=flat_evidence_path,
                overwrite=False,
            )
            logger.info(
                "Skipped evidence export (fingerprint match)",
                extra={
                    "pack_path": str(pack_path),
                    "target": target.target_key,
                    "ordinal": f"{index}/{total}",
                    "fingerprint": fingerprint,
                },
            )
            return {
                "target_key": target.target_key,
                "selector_identifier": target.selector_identifier,
                "binding_id": binding.binding_id,
                "metric_key": metric_key,
                "metric_slug": metric_slug,
                "fingerprint": fingerprint,
                "status": "skipped",
                "plan_statement_fingerprint": plan_statement_fingerprint,
                "paths": {
                    "evidence": str(outputs.evidence_path),
                    "evidence_flat": str(flat_evidence_path),
                    "dax": str(outputs.dax_path),
                    "summary": str(outputs.summary_path),
                },
            }

        if metric_key is None:
            # Expression-only bindings have no metric key; we can't build explain plans yet.
            explicitly_included = binding.binding_id in include_ids
            is_failure = explicitly_included and config.on_error == "fail"
            if is_failure:
                has_failures = True

            write_explain_dax(outputs.dax_path, "-- Skipped: binding does not reference a catalogue metric key.\n")
            logger.warning(
                "Skipping evidence export for non-catalog binding",
                extra={
                    "pack_path": str(pack_path),
                    "target": target.target_key,
                    "ordinal": f"{index}/{total}",
                    "binding_id": binding.binding_id,
                    "explicitly_included": explicitly_included,
                    "on_error": config.on_error,
                },
            )
            summary = {
                "target_key": target.target_key,
                "selector_identifier": target.selector_identifier,
                "binding_id": binding.binding_id,
                "metric_key": None,
                "metric_slug": metric_slug,
                "fingerprint": fingerprint,
                "status": "failed" if is_failure else "skipped_non_catalog",
                "plan_statement_fingerprint": plan_statement_fingerprint,
                "warning": "Binding does not reference a catalogue metric key.",
                "explicitly_included": explicitly_included,
                "paths": {
                    "evidence": str(outputs.evidence_path),
                    "evidence_flat": str(flat_evidence_path),
                    "dax": str(outputs.dax_path),
                    "summary": str(outputs.summary_path),
                },
            }
            write_summary_json(
                outputs.summary_path,
                metric_identifier=target.selector_identifier,
                row_count=0,
                null_counts={},
                distinct_counts={},
                warnings=("Binding does not reference a catalogue metric key.",),
                error="Binding does not reference a catalogue metric key." if is_failure else None,
                datasource=datasource_payload,
                evidence_path=outputs.evidence_path,
                dax_path=outputs.dax_path,
            )
            return summary

        assert plan is not None

        started = time.perf_counter()
        try:
            dax_path, evidence_path, summary_path, row_count, warnings = run_explain_plan(
                plan=plan,
                limit=int(config.explain.limit),
                data_mode=data_mode,
                datasource=datasource,
                outputs=outputs,
            )
            sync_flat_evidence_output(
                evidence_path=evidence_path,
                flat_path=flat_evidence_path,
                overwrite=True,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "Evidence export completed",
                extra={
                    "pack_path": str(pack_path),
                    "target": target.target_key,
                    "ordinal": f"{index}/{total}",
                    "status": "success",
                    "row_count": row_count,
                    "duration_ms": elapsed_ms,
                    "evidence_path": str(evidence_path),
                },
            )
            return {
                "target_key": target.target_key,
                "selector_identifier": target.selector_identifier,
                "binding_id": binding.binding_id,
                "binding_label": binding.label,
                "metric_key": metric_key,
                "metric_slug": metric_slug,
                "fingerprint": fingerprint,
                "status": "success",
                "plan_statement_fingerprint": plan_statement_fingerprint,
                "row_count": row_count,
                "warnings": list(warnings),
                "duration_ms": elapsed_ms,
                "paths": {
                    "evidence": str(evidence_path),
                    "evidence_flat": str(flat_evidence_path),
                    "dax": str(dax_path),
                    "summary": str(summary_path),
                },
            }
        except Exception as exc:  # noqa: BLE001
            has_failures = True
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "Evidence export failed",
                extra={
                    "pack_path": str(pack_path),
                    "target": target.target_key,
                    "ordinal": f"{index}/{total}",
                    "duration_ms": elapsed_ms,
                },
            )
            return {
                "target_key": target.target_key,
                "selector_identifier": target.selector_identifier,
                "binding_id": binding.binding_id,
                "binding_label": binding.label,
                "metric_key": metric_key,
                "metric_slug": metric_slug,
                "fingerprint": fingerprint,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "duration_ms": elapsed_ms,
                "paths": {
                    "evidence": str(outputs.evidence_path),
                    "evidence_flat": str(flat_evidence_path),
                    "dax": str(outputs.dax_path),
                    "summary": str(outputs.summary_path),
                },
            }

    max_workers = int(config.explain.max_concurrency)
    ordered_targets = sorted(
        targets,
        key=lambda target: (
            target.slide_index,
            target.slide_slug,
            target.placeholder_id or "",
            target.binding.binding_id,
        ),
    )

    if max_workers <= 1 or len(ordered_targets) <= 1:
        total = len(ordered_targets)
        for index, target in enumerate(ordered_targets, start=1):
            manifest_bindings.append(_execute_target(target, index=index, total=total))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            total = len(ordered_targets)
            futures = [
                executor.submit(_execute_target, target, index=index, total=total)
                for index, target in enumerate(ordered_targets, start=1)
            ]
            for future in concurrent.futures.as_completed(futures):
                manifest_bindings.append(future.result())

        manifest_bindings.sort(key=lambda entry: str(entry.get("target_key") or ""))

    manifest_payload: dict[str, object] = {
        "generated_at": started_at.isoformat(),
        "pack_path": str(pack_path),
        "output_dir": str(config.output_dir),
        "when": config.when,
        "on_error": config.on_error,
        "data_mode": data_mode,
        "datasource": datasource_payload,
        "bindings": manifest_bindings,
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, default=str) + "\n", encoding="utf-8")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    failure_count = sum(1 for entry in manifest_bindings if entry.get("status") == "failed")
    skipped_count = sum(1 for entry in manifest_bindings if str(entry.get("status", "")).startswith("skipped"))
    logger.info(
        "Pack evidence exports completed",
        extra={
            "pack_path": str(pack_path),
            "manifest_path": str(manifest_path),
            "target_count": len(ordered_targets),
            "failure_count": failure_count,
            "skipped_count": skipped_count,
            "has_failures": has_failures,
            "duration_ms": elapsed_ms,
        },
    )

    return manifest_path, manifest_bindings, has_failures


def resolve_evidence_datasource(
    pack_path: Path,
    *,
    dataset_id: str | None,
    workspace_id: str | None,
    datasource_name: str | None,
) -> ResolvedDataSource:
    """Resolve a live Power BI datasource for pack evidence exports.

    Prefer explicit dataset/workspace ids when provided (CLI flags), otherwise fall back
    to the pack's configured datasource reference (typically "default").
    """

    if dataset_id:
        settings = PowerBISettings.from_env()
        return ResolvedDataSource(
            name=datasource_name or "powerbi",
            type="powerbi",
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            settings=settings,
            source_path=None,
        )

    resolved = resolve_datasource(datasource_name or "default", visual_path=pack_path)
    if workspace_id and resolved.workspace_id != workspace_id:
        resolved = resolved.__class__(
            name=resolved.name,
            type=resolved.type,
            dataset_id=resolved.dataset_id,
            workspace_id=workspace_id,
            settings=resolved.settings,
            source_path=resolved.source_path,
        )

    if resolved.type != "powerbi" or not resolved.dataset_id:
        raise ValueError(
            "Evidence exports in live mode require a Power BI datasource with dataset_id "
            "(provide --dataset-id or configure a powerbi datasource)."
        )
    return resolved


def _format_binding_identifier(
    *,
    base_token: str,
    slide_id: str | None,
    slide_index: int,
    placeholder_id: str | None,
    binding_segments: Sequence[str],
) -> str:
    slide_token = slide_id or str(slide_index)
    parts = [base_token, slide_token]
    if placeholder_id:
        parts.append(placeholder_id)
    parts.extend(binding_segments)
    return "#".join(parts)


__all__ = [
    "PackEvidenceTarget",
    "build_pack_evidence_target",
    "flatten_context_fragments",
    "compute_inputs_fingerprint",
    "load_manifest_fingerprints",
    "render_evidence_output_dir",
    "resolve_evidence_datasource",
    "run_pack_evidence_exports",
    "select_evidence_bindings",
    "should_skip_existing",
]

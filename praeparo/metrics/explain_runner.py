"""Orchestration helpers for `praeparo-metrics explain`.

This module keeps the CLI handler thin by centralising the multi-step flow:

1) Compile the row-based evidence query (DAX) using the same metric + context semantics
   as pack runs.
2) Persist the query as `explain.dax` so results are reproducible even if execution fails.
3) Execute the query (live Power BI, or mock mode) and export the resulting rows to CSV/XLSX.
4) Emit a compact `summary.json` with row counts and basic diagnostics.
"""

from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from praeparo.datasources import DataSourceConfigError, ResolvedDataSource, resolve_datasource
from praeparo.metrics import MetricCatalog, build_metric_explain_plan
from praeparo.powerbi import PowerBIClient, PowerBIQueryError, PowerBISettings
from praeparo.visuals.dax import slugify


@dataclass(frozen=True)
class MetricExplainOutputs:
    """Resolved output locations for an explain run."""

    artefact_dir: Path
    evidence_path: Path
    dax_path: Path
    summary_path: Path


def derive_explain_outputs(
    *,
    metric_identifier: str,
    dest: Path | None,
    artefact_dir: Path | None = None,
) -> MetricExplainOutputs:
    """Derive explain outputs from the optional positional dest plus overrides.

    Mirrors pack-run ergonomics:

    - No dest: `.tmp/explain/<metric_slug>` with evidence at `evidence.csv`.
    - Dest is a file (`.csv` or `.xlsx`): write evidence to that file and artifacts under
      `<parent>/<stem>/_artifacts`.
    - Dest is a directory or extension-less path: write evidence to `<dest>/evidence.csv`
      and artifacts under `<dest>/_artifacts`.

    Explicit `artefact_dir` overrides any derived artifacts directory.
    """

    metric_slug = slugify(metric_identifier)

    if dest is None:
        root = Path(".tmp") / "explain" / metric_slug
        resolved_artefacts = root / "_artifacts"
        evidence_path = root / "evidence.csv"
    else:
        destination = Path(str(dest)).expanduser()
        suffix = destination.suffix.lower()
        if suffix in {".csv", ".xlsx"}:
            evidence_path = destination
            resolved_artefacts = destination.parent / destination.stem / "_artifacts"
        else:
            evidence_path = destination / "evidence.csv"
            resolved_artefacts = destination / "_artifacts"

    resolved_artefacts = Path(artefact_dir).expanduser() if artefact_dir is not None else resolved_artefacts
    dax_path = resolved_artefacts / "explain.dax"
    summary_path = resolved_artefacts / "summary.json"
    return MetricExplainOutputs(
        artefact_dir=resolved_artefacts,
        evidence_path=evidence_path,
        dax_path=dax_path,
        summary_path=summary_path,
    )


def resolve_explain_datasource(
    *,
    datasource: str | None,
    dataset_id: str | None,
    workspace_id: str | None,
    cwd: Path,
) -> ResolvedDataSource:
    """Resolve an execution datasource for a live explain run."""

    if dataset_id:
        settings = PowerBISettings.from_env()
        return ResolvedDataSource(
            name=datasource or "powerbi",
            type="powerbi",
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            settings=settings,
            source_path=None,
        )

    if datasource is None:
        raise DataSourceConfigError(
            "No datasource supplied. Provide --datasource or --dataset-id for live explain runs."
        )

    dummy_visual_path = cwd / "metric_explain.yaml"
    return resolve_datasource(datasource, visual_path=dummy_visual_path)


def write_explain_dax(path: Path, statement: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(statement.strip() + "\n", encoding="utf-8")


def write_evidence_csv(path: Path, rows: Sequence[Mapping[str, object]], *, columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _coerce_csv_value(row.get(key)) for key in columns})


def write_summary_json(
    path: Path,
    *,
    metric_identifier: str,
    row_count: int,
    null_counts: Mapping[str, int],
    distinct_counts: Mapping[str, int],
    warnings: Sequence[str] = (),
    error: str | None = None,
    datasource: Mapping[str, object] | None = None,
    evidence_path: Path | None = None,
    dax_path: Path | None = None,
) -> None:
    payload: dict[str, object] = {
        "metric_identifier": metric_identifier,
        "row_count": row_count,
        "null_counts": dict(null_counts),
        "distinct_counts": dict(distinct_counts),
    }
    if warnings:
        payload["warnings"] = list(warnings)
    if error:
        payload["error"] = error
    if datasource is not None:
        payload["datasource"] = dict(datasource)
    if evidence_path is not None:
        payload["evidence_path"] = str(evidence_path)
    if dax_path is not None:
        payload["dax_path"] = str(dax_path)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def summarise_evidence(rows: Sequence[Mapping[str, object]], *, columns: Sequence[str]) -> tuple[dict[str, int], dict[str, int]]:
    """Compute basic null/distinct diagnostics from exported evidence rows."""

    null_counts: dict[str, int] = {col: 0 for col in columns}
    for row in rows:
        for col in columns:
            if row.get(col) is None:
                null_counts[col] += 1

    distinct_counts: dict[str, int] = {}
    for candidate in ("MatterId", "matter_id", "__grain", "event_key"):
        if candidate not in columns:
            continue
        values = {row.get(candidate) for row in rows if row.get(candidate) is not None}
        distinct_counts[candidate] = len(values)
    return null_counts, distinct_counts


def run_metric_explain(
    *,
    catalog: MetricCatalog,
    metric_identifier: str,
    context_calculate_filters: Sequence[str],
    context_define_blocks: Sequence[str],
    limit: int,
    variant_mode: str,
    data_mode: str,
    datasource: ResolvedDataSource | None,
    outputs: MetricExplainOutputs,
) -> tuple[Path, Path, Path, int, tuple[str, ...]]:
    """Compile + execute an explain query and write all output artifacts.

    Returns (dax_path, evidence_path, summary_path, row_count, warnings).
    """

    # Start by compiling the query plan and writing `explain.dax` so failures are still reproducible.
    plan = build_metric_explain_plan(
        catalog,
        metric_identifier=metric_identifier,
        context_calculate_filters=context_calculate_filters,
        context_define_blocks=context_define_blocks,
        limit=limit,
        variant_mode=variant_mode,
    )

    write_explain_dax(outputs.dax_path, plan.statement)

    if outputs.evidence_path.suffix.lower() == ".xlsx":
        raise ValueError("XLSX evidence export is not supported yet; use a .csv dest (or a directory dest).")

    datasource_payload = None
    if datasource is not None:
        datasource_payload = {
            "name": datasource.name,
            "type": datasource.type,
            "dataset_id": datasource.dataset_id,
            "workspace_id": datasource.workspace_id,
            "source_path": str(datasource.source_path) if datasource.source_path else None,
        }

    try:
        # With a reproducible query on disk, execute the plan in mock or live mode.
        if data_mode == "mock":
            rows: Sequence[Mapping[str, object]] = []
            mock_rows: list[dict[str, object]] = []
            for index in range(min(10, limit)):
                record: dict[str, object] = {col: None for col in plan.column_order}
                record["__metric_key"] = metric_identifier
                record["__metric_value"] = 0
                record["__grain"] = index + 1 if "__grain" in record else None
                mock_rows.append(record)
            rows = mock_rows
        elif data_mode == "live":
            if datasource is None or datasource.type != "powerbi" or not datasource.dataset_id:
                raise DataSourceConfigError("Live explain runs require a Power BI datasource with dataset_id.")

            settings = datasource.settings or PowerBISettings.from_env()
            dataset_id = datasource.dataset_id
            assert dataset_id is not None

            async def _execute() -> list[dict[str, Any]]:
                async with PowerBIClient(settings) as client:
                    return await client.execute_dax(
                        dataset_id,
                        plan.statement,
                        group_id=datasource.workspace_id,
                    )

            raw_rows = asyncio.run(_execute())
            rows = [{key: value for key, value in row.items()} for row in raw_rows]
        else:
            raise ValueError("data_mode must be one of {'mock', 'live'}.")

        # With rows materialised, write the requested evidence format.
        write_evidence_csv(outputs.evidence_path, rows, columns=plan.column_order)

        null_counts, distinct_counts = summarise_evidence(rows, columns=plan.column_order)
        write_summary_json(
            outputs.summary_path,
            metric_identifier=metric_identifier,
            row_count=len(rows),
            null_counts=null_counts,
            distinct_counts=distinct_counts,
            warnings=plan.warnings,
            datasource=datasource_payload,
            evidence_path=outputs.evidence_path,
            dax_path=outputs.dax_path,
        )

        return outputs.dax_path, outputs.evidence_path, outputs.summary_path, len(rows), plan.warnings
    except Exception as exc:  # noqa: BLE001
        # On failure we still emit a summary so callers can grab paths + error detail.
        write_summary_json(
            outputs.summary_path,
            metric_identifier=metric_identifier,
            row_count=0,
            null_counts={},
            distinct_counts={},
            warnings=plan.warnings,
            error=f"{type(exc).__name__}: {exc}",
            datasource=datasource_payload,
            evidence_path=outputs.evidence_path,
            dax_path=outputs.dax_path,
        )
        raise


def _coerce_csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, default=str)


__all__ = [
    "MetricExplainOutputs",
    "derive_explain_outputs",
    "resolve_explain_datasource",
    "run_metric_explain",
    "write_explain_dax",
    "write_summary_json",
]

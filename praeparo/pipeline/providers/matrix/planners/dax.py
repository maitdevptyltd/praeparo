"""Matrix query planner backed by a DAX execution client."""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Awaitable, Mapping, Sequence, TYPE_CHECKING, Callable

from praeparo.data import MatrixResultSet, mock_matrix_data
from praeparo.dax import DaxQueryPlan, build_matrix_query
from praeparo.datasources import DataSourceConfigError, ResolvedDataSource, resolve_datasource
from praeparo.models import MatrixConfig
from praeparo.templating import FieldReference, extract_field_references

from .base import MatrixPlannerResult, MatrixQueryPlanner
from ...dax.clients.base import DaxExecutionClient

if TYPE_CHECKING:  # pragma: no cover
    from ....core import ExecutionContext


logger = logging.getLogger(__name__)


class DaxBackedMatrixPlanner(MatrixQueryPlanner):
    """Plans matrix visuals by delegating execution to a DAX client."""

    def __init__(
        self,
        *,
        dax_client: DaxExecutionClient,
        datasource_resolver: Callable[[str | None, Path], ResolvedDataSource] | None = None,
        mock_provider: Callable[[MatrixConfig, Sequence[FieldReference]], MatrixResultSet] = mock_matrix_data,
    ) -> None:
        self._dax_client = dax_client
        if datasource_resolver is None:
            def _default_resolver(reference: str | None, visual_path: Path) -> ResolvedDataSource:
                return resolve_datasource(reference, visual_path=visual_path)
            self._resolve_datasource = _default_resolver
        else:
            self._resolve_datasource = datasource_resolver
        self._mock_provider = mock_provider

    def plan(self, config: MatrixConfig, *, context: "ExecutionContext") -> MatrixPlannerResult:
        row_fields = tuple(self._extract_row_fields(config))
        plan = build_matrix_query(config, row_fields)

        context_payload = context.options.metadata.get("context") if isinstance(context.options.metadata, Mapping) else {}
        calculate_filters = context_payload.get("calculate") if isinstance(context_payload, Mapping) else None
        define_block = context_payload.get("define") if isinstance(context_payload, Mapping) else None
        if calculate_filters or define_block:
            logger.debug(
                "Applying DAX context",
                extra={
                    "case": context.case_key,
                    "calculate_count": len(calculate_filters) if isinstance(calculate_filters, Sequence) else (1 if calculate_filters else 0),
                    "has_define": bool(define_block),
                },
            )

        data_options = context.options.data
        dataset_override = getattr(data_options, "dataset_id", None)
        workspace_override = getattr(data_options, "workspace_id", None)
        provider_key = self._resolve_provider_key(context, data_options)

        if dataset_override:
            logger.info(
                "Executing matrix with dataset override",
                extra={
                    "case": context.case_key,
                    "dataset_id": dataset_override,
                    "workspace_id": workspace_override,
                },
            )
            dataset = self._execute_with_override(config, row_fields, plan, dataset_override, workspace_override)
            return MatrixPlannerResult(plan=plan, dataset=dataset)

        if provider_key == "mock":
            logger.info(
                "Executing matrix with mock provider",
                extra={"case": context.case_key, "title": config.title},
            )
            dataset = self._mock_provider(config, row_fields)
            return MatrixPlannerResult(plan=plan, dataset=dataset)

        dataset = self._execute_from_datasource(config, row_fields, plan, context, data_options)
        logger.info(
            "Matrix execution completed",
            extra={
                "case": context.case_key,
                "rows": len(dataset.rows),
                "columns": [field.placeholder for field in row_fields],
            },
        )
        return MatrixPlannerResult(plan=plan, dataset=dataset)

    def _extract_row_fields(self, config: MatrixConfig) -> Sequence[FieldReference]:
        return extract_field_references([row.template for row in config.rows])

    def _resolve_provider_key(self, context: "ExecutionContext", data_options) -> str | None:
        case_key = context.case_key
        overrides = getattr(data_options, "provider_case_overrides", {}) or {}
        if case_key and case_key in overrides:
            candidate = overrides[case_key].strip().lower()
            if candidate:
                return candidate
        provider_key = getattr(data_options, "provider_key", None)
        if provider_key:
            candidate = provider_key.strip().lower()
            if candidate:
                return candidate
        return None

    def _execute_with_override(
        self,
        config: MatrixConfig,
        row_fields: Sequence[FieldReference],
        plan: DaxQueryPlan,
        dataset_id: str,
        workspace_override: str | None,
    ) -> MatrixResultSet:
        result = self._dax_client.execute_matrix(
            config,
            row_fields,
            plan,
            dataset_id=dataset_id,
            workspace_id=workspace_override,
        )
        return self._resolve_result(result)

    def _execute_from_datasource(
        self,
        config: MatrixConfig,
        row_fields: Sequence[FieldReference],
        plan: DaxQueryPlan,
        context: "ExecutionContext",
        data_options,
    ) -> MatrixResultSet:
        reference = getattr(data_options, "datasource_override", None) or config.datasource
        visual_path = context.config_path
        if visual_path is None:
            msg = "Matrix execution requires a config_path to resolve datasources."
            raise DataSourceConfigError(msg)

        datasource = self._resolve_datasource(reference, visual_path)
        if datasource.type == "mock":
            return self._mock_provider(config, row_fields)

        dataset_id = datasource.dataset_id
        if not dataset_id:
            title = config.title or "matrix"
            msg = f"Data source '{datasource.name}' for {title} lacks a dataset_id."
            raise DataSourceConfigError(msg)

        workspace_override = getattr(data_options, "workspace_id", None)
        logger.info(
            "Executing matrix via datasource",
            extra={
                "case": context.case_key,
                "datasource": datasource.name,
                "dataset_id": dataset_id,
                "workspace_id": workspace_override or datasource.workspace_id,
            },
        )
        result = self._dax_client.execute_matrix(
            config,
            row_fields,
            plan,
            dataset_id=dataset_id,
            workspace_id=workspace_override or datasource.workspace_id,
            settings=datasource.settings,
        )
        return self._resolve_result(result)

    def _resolve_result(
        self,
        result: MatrixResultSet | Awaitable[MatrixResultSet],
    ) -> MatrixResultSet:
        if inspect.isawaitable(result):
            try:
                resolved = asyncio.run(result)  # type: ignore[arg-type]
            except RuntimeError as exc:  # pragma: no cover
                msg = (
                    "DAX execution returned an awaitable while an event loop is already running. "
                    "Provide a synchronous client or adapt the call site to handle async planners."
                )
                raise RuntimeError(msg) from exc
        else:
            resolved = result
        if not isinstance(resolved, MatrixResultSet):
            msg = "DAX execution client must return a MatrixResultSet."
            raise TypeError(msg)
        return resolved

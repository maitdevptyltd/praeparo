from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from dataclasses import dataclass, field
from importlib import util
from typing import Awaitable, Callable, Mapping, Sequence

from plotly.graph_objects import Figure

from praeparo.data import MatrixResultSet
from praeparo.dax import DaxQueryPlan
from praeparo.models import FrameConfig, MatrixConfig
from praeparo.rendering import matrix_figure
from praeparo.rendering._shared import estimate_table_height
from praeparo.rendering.frame import (
    AUTO_FRAME_VERTICAL_SPACING,
    DEFAULT_CHILD_HEIGHT,
    FRAME_TITLE_MARGIN,
    SUBPLOT_TITLE_MARGIN,
)
from praeparo.rendering.matrix import MATRIX_TITLE_MARGIN
from praeparo.templating import FieldReference, label_from_template
from tests.snapshot_extensions import (
    DaxSnapshotExtension,
    PlotlyHtmlSnapshotExtension,
    PlotlyPngSnapshotExtension,
)
from tests.utils.visual_cases import FrameChildArtifacts, MatrixArtifacts

MatrixArtifactLike = MatrixArtifacts | FrameChildArtifacts
MatrixDataProvider = Callable[
    [MatrixConfig, Sequence[FieldReference], DaxQueryPlan],
    MatrixResultSet | Awaitable[MatrixResultSet],
]


@dataclass(frozen=True)
class MatrixDataProviderRegistry:
    default: MatrixDataProvider
    overrides: Mapping[str, MatrixDataProvider] = field(default_factory=dict)

    def resolve(self, case: str) -> MatrixDataProvider:
        override = self.overrides.get(case)
        if override is not None:
            return override
        return self.default


@dataclass(frozen=True)
class MatrixCaseResult:
    dataset: MatrixResultSet
    figure: Figure


def slugify(value: str) -> str:
    slug = value.strip().lower().replace(" ", "_")
    return "".join(char for char in slug if char.isalnum() or char in {"_", "-"}) or "section"


def expected_matrix_height(config: MatrixConfig, dataset: MatrixResultSet) -> int:
    height = estimate_table_height(len(dataset.rows))
    if config.title:
        height += MATRIX_TITLE_MARGIN
    return height


def expected_frame_height(
    frame: FrameConfig,
    child_pairs: Sequence[tuple[MatrixConfig, MatrixResultSet]],
) -> int:
    top_margin = FRAME_TITLE_MARGIN if frame.title else 0
    if frame.show_titles:
        top_margin += SUBPLOT_TITLE_MARGIN

    row_count = len(child_pairs)
    if frame.auto_height:
        child_heights: list[int] = []
        for config, dataset in child_pairs:
            if config.auto_height:
                height = estimate_table_height(len(dataset.rows))
            else:
                height = DEFAULT_CHILD_HEIGHT
            child_heights.append(height)

        content_height = sum(child_heights)
        spacing_fraction = AUTO_FRAME_VERTICAL_SPACING if row_count > 1 else 0.0
        domain_fraction = 1 - spacing_fraction * (row_count - 1)
        if domain_fraction <= 0:
            domain_fraction = 1.0
        base_height = content_height / domain_fraction
        return int(round(base_height + top_margin))

    return DEFAULT_CHILD_HEIGHT * row_count + top_margin


def assert_matrix_headers(
    config: MatrixConfig,
    dataset: MatrixResultSet,
    header_values: Sequence[str],
) -> None:
    visible_rows = [row for row in config.rows if not row.hidden]
    row_header_values = header_values[: len(visible_rows)]
    for index, row in enumerate(visible_rows):
        expected = row.label or label_from_template(row.template, dataset.row_fields)
        assert row_header_values[index] == expected

    hidden_rows = [row for row in config.rows if row.hidden]
    for row in hidden_rows:
        expected = row.label or label_from_template(row.template, dataset.row_fields)
        assert expected not in row_header_values


def _resolve_dataset(
    provider: MatrixDataProvider,
    config: MatrixConfig,
    row_fields: Sequence[FieldReference],
    plan: DaxQueryPlan,
) -> MatrixResultSet:
    result = provider(config, row_fields, plan)
    if inspect.isawaitable(result):
        try:
            return asyncio.run(result)
        except RuntimeError as exc:
            msg = (
                "Matrix data provider returned an awaitable while an event loop is already running. "
                "Wrap the provider in a synchronous adapter before passing it to run_matrix_case."
            )
            raise RuntimeError(msg) from exc
    return result


SNAPSHOT_BASENAME = "test_snapshot"


def snapshot_file_stem(case: str, snapshot_path: Path | None = None) -> str:
    if snapshot_path is not None:
        normalized = snapshot_path.as_posix().strip("/" + chr(92))
        if normalized:
            return f"{normalized}/{SNAPSHOT_BASENAME}"
        return SNAPSHOT_BASENAME
    return f"{SNAPSHOT_BASENAME}__{case}"


def run_matrix_case(
    snapshot,
    case: str,
    artifacts: MatrixArtifactLike,
    *,
    data_provider: MatrixDataProvider,
    snapshot_path: Path | None = None,
    capture_html: bool = True,
    capture_png: bool = True,
    png_requires_kaleido: bool = True,
    ensure_non_empty_rows: bool = False,
    ensure_values_present: bool = False,
    validate_define: bool = False,
    html_div_id: str | None = None,
    png_scale: float = 2.0,
    sort_rows: bool = False,
) -> MatrixCaseResult:
    config = artifacts.config
    row_fields = artifacts.row_fields
    plan = artifacts.plan

    if validate_define:
        if config.define:
            assert plan.define == config.define.strip()
        else:
            assert plan.define is None

    dataset = _resolve_dataset(data_provider, config, row_fields, plan)
    if sort_rows and dataset.rows:
        sorted_rows = sorted(
            dataset.rows,
            key=lambda row: tuple(str(row.get(field.placeholder)) for field in dataset.row_fields),
        )
        dataset = MatrixResultSet(rows=sorted_rows, row_fields=dataset.row_fields)
    if ensure_non_empty_rows:
        assert dataset.rows, f"Matrix data provider for {case} returned no rows"

    snapshot_stem = snapshot_file_stem(case, snapshot_path)
    dax_extension = type(
        f"DaxSnapshotExtension_{case}",
        (DaxSnapshotExtension,),
        {"snapshot_name": snapshot_stem},
    )
    snapshot.use_extension(dax_extension).assert_match(plan.statement)

    figure = matrix_figure(config, dataset)
    assert figure.data

    header_values = list(figure.data[0].header["values"])
    assert_matrix_headers(config, dataset, header_values)

    if config.auto_height:
        expected_height = expected_matrix_height(config, dataset)
        assert figure.layout.height == expected_height
        assert figure.layout.autosize is False
    else:
        assert figure.layout.height in {None, 0}

    if ensure_values_present and dataset.rows:
        first_row = dataset.rows[0]
        for value in config.values:
            alias = value.label or value.id
            assert first_row.get(alias) is not None, f"Value '{alias}' missing from dataset row"

    if capture_html:
        html_extension = type(
            f"PlotlyHtmlSnapshotExtension_{case}",
            (PlotlyHtmlSnapshotExtension,),
            {"snapshot_name": snapshot_stem},
        )
        html_snapshot = snapshot.use_extension(html_extension)
        div_id = html_div_id or case
        html_snapshot.assert_match(
            figure.to_html(full_html=True, include_plotlyjs="cdn", div_id=div_id)
        )

    if capture_png:
        if not png_requires_kaleido or util.find_spec("kaleido") is not None:
            png_extension = type(
                f"PlotlyPngSnapshotExtension_{case}",
                (PlotlyPngSnapshotExtension,),
                {"snapshot_name": snapshot_stem},
            )
            png_snapshot = snapshot.use_extension(png_extension)
            png_kwargs = {"format": "png", "scale": png_scale}
            if figure.layout.height:
                png_kwargs["height"] = figure.layout.height
            png_snapshot.assert_match(figure.to_image(**png_kwargs))

    return MatrixCaseResult(dataset=dataset, figure=figure)


__all__ = [
    "MatrixCaseResult",
    "MatrixDataProvider",
    "MatrixDataProviderRegistry",
    "assert_matrix_headers",
    "expected_frame_height",
    "expected_matrix_height",
    "run_matrix_case",
    "slugify",
    "snapshot_file_stem",
]

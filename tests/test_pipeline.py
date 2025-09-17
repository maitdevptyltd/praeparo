from importlib import util
from pathlib import Path

import pytest

from praeparo.data import MatrixResultSet, mock_matrix_data
from praeparo.models import MatrixConfig
from praeparo.rendering import (
    frame_figure,
    frame_html,
    frame_png,
    matrix_figure,
    matrix_html,
    matrix_png,
)
from praeparo.templating import label_from_template
from tests.snapshot_extensions import (
    DaxSnapshotExtension,
    PlotlyHtmlSnapshotExtension,
    PlotlyPngSnapshotExtension,
)
from tests.utils.visual_cases import (
    FrameArtifacts,
    FrameChildArtifacts,
    MatrixArtifacts,
    case_name,
    discover_yaml_files,
    load_visual_artifacts,
)

VISUAL_ROOT = Path("tests/visuals")
VISUAL_FILES = discover_yaml_files(VISUAL_ROOT)


def _slugify(value: str) -> str:
    slug = value.strip().lower().replace(" ", "_")
    return "".join(char for char in slug if char.isalnum() or char in {"_", "-"}) or "section"


def _assert_matrix_headers(config: MatrixConfig, dataset: MatrixResultSet, header_values: list[str]) -> None:
    visible_rows = [row for row in config.rows if not row.hidden]
    row_header_values = header_values[: len(visible_rows)]
    for index, row in enumerate(visible_rows):
        expected = row.label or label_from_template(row.template, dataset.row_fields)
        assert row_header_values[index] == expected

    hidden_rows = [row for row in config.rows if row.hidden]
    for row in hidden_rows:
        expected = row.label or label_from_template(row.template, dataset.row_fields)
        assert expected not in row_header_values


@pytest.mark.parametrize("yaml_path", VISUAL_FILES, ids=lambda path: case_name(path, VISUAL_ROOT))
def test_visual_snapshots(snapshot, yaml_path: Path) -> None:
    artifacts = load_visual_artifacts(yaml_path)
    case = case_name(yaml_path, VISUAL_ROOT)

    if isinstance(artifacts, MatrixArtifacts):
        dataset: MatrixResultSet = mock_matrix_data(artifacts.config, artifacts.row_fields)

        dax_extension = type(
            f"DaxSnapshotExtension_{case}",
            (DaxSnapshotExtension,),
            {"snapshot_name": f"test_snapshot__{case}"},
        )
        snapshot.use_extension(dax_extension).assert_match(artifacts.plan.statement)

        figure = matrix_figure(artifacts.config, dataset)
        assert figure.data

        header_values = list(figure.data[0].header["values"])
        _assert_matrix_headers(artifacts.config, dataset, header_values)

        html_extension = type(
            f"PlotlyHtmlSnapshotExtension_{case}",
            (PlotlyHtmlSnapshotExtension,),
            {"snapshot_name": f"test_snapshot__{case}"},
        )
        html_snapshot = snapshot.use_extension(html_extension)
        html_snapshot.assert_match(
            figure.to_html(full_html=True, include_plotlyjs="cdn", div_id=case),
        )

        if util.find_spec("kaleido") is not None:
            png_extension = type(
                f"PlotlyPngSnapshotExtension_{case}",
                (PlotlyPngSnapshotExtension,),
                {"snapshot_name": f"test_snapshot__{case}"},
            )
            png_snapshot = snapshot.use_extension(png_extension)
            png_snapshot.assert_match(
                figure.to_image(format="png", scale=2.0),
            )
        return

    assert isinstance(artifacts, FrameArtifacts)
    child_datasets: list[tuple[FrameChildArtifacts, MatrixResultSet]] = []

    for index, child in enumerate(artifacts.children, start=1):
        dataset = mock_matrix_data(child.config, child.row_fields)
        child_slug = f"{case}__{_slugify(child.config.title or f'child_{index}') }"

        dax_extension = type(
            f"DaxSnapshotExtension_{child_slug}",
            (DaxSnapshotExtension,),
            {"snapshot_name": f"test_snapshot__{child_slug}"},
        )
        snapshot.use_extension(dax_extension).assert_match(child.plan.statement)

        header_values = list(
            matrix_figure(child.config, dataset).data[0].header["values"]
        )
        _assert_matrix_headers(child.config, dataset, header_values)

        child_datasets.append((child, dataset))

    figure = frame_figure(
        artifacts.config,
        [(child.config, dataset) for child, dataset in child_datasets],
    )
    html_extension = type(
        f"PlotlyHtmlSnapshotExtension_{case}",
        (PlotlyHtmlSnapshotExtension,),
        {"snapshot_name": f"test_snapshot__{case}"},
    )
    html_snapshot = snapshot.use_extension(html_extension)
    html_snapshot.assert_match(
        figure.to_html(full_html=True, include_plotlyjs="cdn", div_id=case),
    )

    if util.find_spec("kaleido") is not None:
        png_extension = type(
            f"PlotlyPngSnapshotExtension_{case}",
            (PlotlyPngSnapshotExtension,),
            {"snapshot_name": f"test_snapshot__{case}"},
        )
        png_snapshot = snapshot.use_extension(png_extension)
        png_snapshot.assert_match(
            figure.to_image(format="png", scale=2.0),
        )


@pytest.mark.parametrize("yaml_path", VISUAL_FILES, ids=lambda path: case_name(path, VISUAL_ROOT))
def test_matrix_html_and_png_writers(tmp_path: Path, yaml_path: Path) -> None:
    artifacts = load_visual_artifacts(yaml_path)
    case = case_name(yaml_path, VISUAL_ROOT)

    if isinstance(artifacts, MatrixArtifacts):
        dataset = mock_matrix_data(artifacts.config, artifacts.row_fields)

        html_output = tmp_path / f"{case}.html"
        matrix_html(artifacts.config, dataset, str(html_output))
        assert html_output.exists() and html_output.read_text(encoding="utf-8")

        png_output = tmp_path / f"{case}.png"
        if util.find_spec("kaleido") is not None:
            matrix_png(artifacts.config, dataset, str(png_output))
            assert png_output.exists() and png_output.stat().st_size > 0
        else:
            with pytest.raises(RuntimeError):
                matrix_png(artifacts.config, dataset, str(png_output))
        return

    assert isinstance(artifacts, FrameArtifacts)
    datasets = [
        (child.config, mock_matrix_data(child.config, child.row_fields))
        for child in artifacts.children
    ]

    html_output = tmp_path / f"{case}.html"
    frame_html(artifacts.config, datasets, str(html_output))
    assert html_output.exists() and html_output.read_text(encoding="utf-8")

    png_output = tmp_path / f"{case}.png"
    if util.find_spec("kaleido") is not None:
        frame_png(artifacts.config, datasets, str(png_output))
        assert png_output.exists() and png_output.stat().st_size > 0
    else:
        with pytest.raises(RuntimeError):
            frame_png(artifacts.config, datasets, str(png_output))


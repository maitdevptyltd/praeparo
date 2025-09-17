from importlib import util
from pathlib import Path

import pytest

from praeparo.data import MatrixResultSet, mock_matrix_data
from praeparo.rendering import matrix_figure, matrix_html, matrix_png
from praeparo.templating import label_from_template
from tests.snapshot_extensions import (
    DaxSnapshotExtension,
    PlotlyHtmlSnapshotExtension,
    PlotlyPngSnapshotExtension,
)
from tests.utils.visual_cases import case_name, discover_yaml_files, load_visual_artifacts

VISUAL_ROOT = Path("tests/visuals")
VISUAL_FILES = discover_yaml_files(VISUAL_ROOT)


@pytest.mark.parametrize("yaml_path", VISUAL_FILES, ids=lambda path: case_name(path, VISUAL_ROOT))
def test_visual_snapshots(snapshot, yaml_path: Path) -> None:
    config, row_fields, plan = load_visual_artifacts(yaml_path)
    if config.define:
        assert plan.define == config.define.strip()
    else:
        assert plan.define is None
    dataset: MatrixResultSet = mock_matrix_data(config, row_fields)

    case = case_name(yaml_path, VISUAL_ROOT)

    dax_extension = type(
        f"DaxSnapshotExtension_{case}",
        (DaxSnapshotExtension,),
        {"snapshot_name": f"test_snapshot__{case}"},
    )
    dax_snapshot = snapshot.use_extension(dax_extension)
    dax_snapshot.assert_match(plan.statement)

    figure = matrix_figure(config, dataset)
    assert figure.data

    header_values = list(figure.data[0].header["values"])
    visible_rows = [row for row in config.rows if not row.hidden]
    row_header_values = header_values[: len(visible_rows)]
    for index, row in enumerate(visible_rows):
        expected = row.label or label_from_template(row.template, dataset.row_fields)
        assert row_header_values[index] == expected

    hidden_rows = [row for row in config.rows if row.hidden]
    for row in hidden_rows:
        expected = row.label or label_from_template(row.template, dataset.row_fields)
        assert expected not in row_header_values

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
    config, row_fields, plan = load_visual_artifacts(yaml_path)
    if config.define:
        assert plan.define == config.define.strip()
    else:
        assert plan.define is None
    dataset = mock_matrix_data(config, row_fields)
    case = case_name(yaml_path, VISUAL_ROOT)

    html_output = tmp_path / f"{case}.html"
    matrix_html(config, dataset, str(html_output))
    assert html_output.exists() and html_output.read_text(encoding="utf-8")

    png_output = tmp_path / f"{case}.png"
    if util.find_spec("kaleido") is not None:
        matrix_png(config, dataset, str(png_output))
        assert png_output.exists() and png_output.stat().st_size > 0
    else:
        with pytest.raises(RuntimeError):
            matrix_png(config, dataset, str(png_output))

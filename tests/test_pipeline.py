from importlib import util
from pathlib import Path

import pytest

from praeparo.data import mock_matrix_data
from praeparo.dax import build_matrix_query
from praeparo.io.yaml_loader import load_matrix_config
from praeparo.rendering import matrix_figure, matrix_html, matrix_png
from praeparo.templating import extract_field_references


def _load_pipeline_artifacts():
    config_path = Path("tests/matrix/basic/auto.yaml")
    config = load_matrix_config(config_path)
    row_fields = extract_field_references(config.rows)
    plan = build_matrix_query(config, row_fields)
    dataset = mock_matrix_data(config, row_fields)
    return config, dataset, plan


def test_pipeline_renders_html(tmp_path: Path) -> None:
    config, dataset, plan = _load_pipeline_artifacts()

    assert "EVALUATE" in plan.statement
    assert dataset.rows

    figure = matrix_figure(config, dataset)
    assert figure.data  # ensure table created

    html_output = tmp_path / "matrix.html"
    matrix_html(config, dataset, str(html_output))
    assert html_output.exists()


@pytest.mark.skipif(util.find_spec("kaleido") is None, reason="Kaleido is required for PNG export")
def test_pipeline_renders_png(tmp_path: Path) -> None:
    config, dataset, _ = _load_pipeline_artifacts()

    png_output = tmp_path / "matrix.png"
    matrix_png(config, dataset, str(png_output))
    assert png_output.exists() and png_output.stat().st_size > 0

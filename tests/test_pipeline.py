from importlib import util
from pathlib import Path
from typing import Callable

import pytest

from praeparo.data import mock_matrix_data
from praeparo.dax import build_matrix_query
from praeparo.io.yaml_loader import load_matrix_config
from praeparo.rendering import matrix_figure, matrix_html, matrix_png
from praeparo.templating import extract_field_references, label_from_template
from .snapshot_extensions import PlotlyHtmlSnapshotExtension, PlotlyPngSnapshotExtension, DaxSnapshotExtension

VISUAL_ROOT = Path("tests/visuals")


def _visual_files() -> list[Path]:
    return sorted(VISUAL_ROOT.glob("**/*.yaml"))


def _case_name(path: Path) -> str:
    relative = path.relative_to(VISUAL_ROOT)
    parts = list(relative.parts)
    parts[-1] = path.stem
    return "_".join(parts)


def _load_artifacts(yaml_path: Path):
    config = load_matrix_config(yaml_path)
    row_fields = extract_field_references(row.template for row in config.rows)
    plan = build_matrix_query(config, row_fields)
    dataset = mock_matrix_data(config, row_fields)
    return config, dataset, plan


def _snapshot_test(yaml_path: Path) -> Callable:
    case = _case_name(yaml_path)

    def test(snapshot):
        config, dataset, plan = _load_artifacts(yaml_path)

        assert "EVALUATE" in plan.statement
        assert dataset.rows

        dax_extension = type(
            f"DaxSnapshotExtension_{case}",
            (DaxSnapshotExtension,),
            {"snapshot_name": f"test_snapshot__{case}"},
        )
        dax_snapshot = snapshot.use_extension(dax_extension)
        dax_snapshot.assert_match(plan.statement)

        figure = matrix_figure(config, dataset)
        assert figure.data  # ensure table created

        header_values = list(figure.data[0].header["values"])
        for index, row in enumerate(config.rows):
            expected = row.label or label_from_template(row.template, dataset.row_fields)
            assert header_values[index] == expected

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

    test.__name__ = f"test_snapshot__{case}"
    return test


def _writer_test(yaml_path: Path) -> Callable:
    case = _case_name(yaml_path)

    def test(tmp_path: Path):
        config, dataset, _ = _load_artifacts(yaml_path)

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

    test.__name__ = f"test_writers__{case}"
    return test


for visual_file in _visual_files():
    globals()[f"test_snapshot__{_case_name(visual_file)}"] = _snapshot_test(visual_file)
    globals()[f"test_writers__{_case_name(visual_file)}"] = _writer_test(visual_file)


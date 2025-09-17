from importlib import util
from pathlib import Path
from typing import Sequence

import pytest

from praeparo.data import MatrixResultSet, mock_matrix_data
from praeparo.models import MatrixConfig
from praeparo.rendering import (
    frame_figure,
    frame_html,
    frame_png,
    matrix_html,
    matrix_png,
)
from tests.snapshot_extensions import (
    PlotlyHtmlSnapshotExtension,
    PlotlyPngSnapshotExtension,
)
from tests.utils.matrix_cases import (
    MatrixDataProviderRegistry,
    expected_frame_height,
    run_matrix_case,
    slugify,
)
from tests.utils.visual_cases import (
    FrameArtifacts,
    MatrixArtifacts,
    case_name,
    discover_yaml_files,
    load_visual_artifacts,
)

VISUAL_ROOT = Path("tests/visuals")
VISUAL_FILES = discover_yaml_files(VISUAL_ROOT)


def _mock_matrix_provider(
    config: MatrixConfig,
    row_fields: Sequence,
    plan,
):
    return mock_matrix_data(config, row_fields)


DATA_PROVIDERS = MatrixDataProviderRegistry(default=_mock_matrix_provider)


@pytest.mark.parametrize("yaml_path", VISUAL_FILES, ids=lambda path: case_name(path, VISUAL_ROOT))
def test_visual_snapshots(snapshot, yaml_path: Path) -> None:
    artifacts = load_visual_artifacts(yaml_path)
    case = case_name(yaml_path, VISUAL_ROOT)

    provider = DATA_PROVIDERS.resolve(case)

    if isinstance(artifacts, MatrixArtifacts):
        run_matrix_case(snapshot, case, artifacts, data_provider=provider)
        return

    assert isinstance(artifacts, FrameArtifacts)
    child_results: list[tuple[MatrixConfig, MatrixResultSet]] = []

    for index, child in enumerate(artifacts.children, start=1):
        child_case = f"{case}__{slugify(child.config.title or f'child_{index}')}"
        child_provider = DATA_PROVIDERS.resolve(child_case)
        child_result = run_matrix_case(
            snapshot,
            child_case,
            child,
            data_provider=child_provider,
            capture_html=False,
            capture_png=False,
        )
        child_results.append((child.config, child_result.dataset))

    figure = frame_figure(artifacts.config, child_results)

    expected_height = expected_frame_height(artifacts.config, child_results)
    assert figure.layout.height == expected_height
    assert figure.layout.autosize is False

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
        png_kwargs = {"format": "png", "scale": 2.0}
        if figure.layout.height:
            png_kwargs["height"] = figure.layout.height
        png_snapshot.assert_match(
            figure.to_image(**png_kwargs),
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

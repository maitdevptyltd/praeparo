import asyncio
import os
from pathlib import Path

import pytest

from praeparo.data import powerbi_matrix_data
from praeparo.rendering import matrix_figure
from praeparo.templating import label_from_template
from tests.snapshot_extensions import (
    DaxSnapshotExtension,
    PlotlyHtmlSnapshotExtension,
    PlotlyPngSnapshotExtension,
)
from tests.utils.visual_cases import case_name, discover_yaml_files, load_visual_artifacts

GROUP_ID = "ca3752a3-d81b-41f9-a991-143521f57c2e"
DATASET_ID = "937e5b45-9241-4079-8caf-94ec91ac70bd"
REQUIRED_ENV = (
    "PRAEPARO_PBI_CLIENT_ID",
    "PRAEPARO_PBI_CLIENT_SECRET",
    "PRAEPARO_PBI_TENANT_ID",
    "PRAEPARO_PBI_REFRESH_TOKEN",
)
INTEGRATION_ROOT = Path("tests/integration")
INTEGRATION_FILES = discover_yaml_files(INTEGRATION_ROOT)


def _ensure_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing Power BI environment variables: {', '.join(missing)}")


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("PRAEPARO_RUN_POWERBI_TESTS") != "1",
    reason="Set PRAEPARO_RUN_POWERBI_TESTS=1 to enable live Power BI integration tests.",
)
@pytest.mark.parametrize("yaml_path", INTEGRATION_FILES, ids=lambda path: case_name(path, INTEGRATION_ROOT))
def test_powerbi_matrix_snapshot(snapshot, yaml_path: Path) -> None:
    _ensure_env()

    config, row_fields, plan = load_visual_artifacts(yaml_path)
    if config.define:
        assert plan.define == config.define.strip()
    else:
        assert plan.define is None

    dataset = asyncio.run(
        powerbi_matrix_data(
            config,
            row_fields,
            plan,
            dataset_id=DATASET_ID,
            group_id=GROUP_ID,
        )
    )

    assert dataset.rows, "Power BI query returned no rows"

    case = case_name(yaml_path, INTEGRATION_ROOT)

    dax_extension = type(
        f"DaxSnapshotExtension_{case}",
        (DaxSnapshotExtension,),
        {"snapshot_name": f"test_snapshot__{case}"},
    )
    dax_snapshot = snapshot.use_extension(dax_extension)
    dax_snapshot.assert_match(plan.statement)

    figure = matrix_figure(config, dataset)

    header_values = list(figure.data[0].header["values"])
    for index, row in enumerate(config.rows):
        expected = row.label or label_from_template(row.template, dataset.row_fields)
        assert header_values[index] == expected

    first_row = dataset.rows[0]
    for value in config.values:
        alias = value.label or value.id
        assert first_row.get(alias) is not None, f"Value '{alias}' missing from dataset row"

    html_extension = type(
        f"PlotlyHtmlSnapshotExtension_{case}",
        (PlotlyHtmlSnapshotExtension,),
        {"snapshot_name": f"test_snapshot__{case}"},
    )
    html_snapshot = snapshot.use_extension(html_extension)
    html_snapshot.assert_match(
        figure.to_html(full_html=True, include_plotlyjs="cdn", div_id=case),
    )

    if os.getenv("PRAEPARO_PBI_CAPTURE_PNG", "1") == "1":
        png_extension = type(
            f"PlotlyPngSnapshotExtension_{case}",
            (PlotlyPngSnapshotExtension,),
            {"snapshot_name": f"test_snapshot__{case}"},
        )
        png_snapshot = snapshot.use_extension(png_extension)
        png_snapshot.assert_match(
            figure.to_image(format="png", scale=2.0),
        )

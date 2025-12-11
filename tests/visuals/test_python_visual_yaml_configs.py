from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from praeparo.cli import main as cli_main
from praeparo.io.yaml_loader import load_visual_config
from praeparo.models import CartesianChartConfig
from praeparo.models.cartesian import PythonCartesianChartConfig
from praeparo.pipeline import ExecutionContext, PipelineOptions, VisualPipeline, PYTHON_VISUAL_TYPE
from praeparo.pipeline.python_visual_loader import load_python_visual_module
from praeparo.pipeline.registry import get_visual_pipeline_definition
from praeparo.pipeline.registry import SchemaArtifact


FIXTURES = Path(__file__).parent.parent / "fixtures" / "python_visuals"


def test_yaml_python_visual_uses_declared_config_model() -> None:
    config_path = FIXTURES / "simple_yaml_visual.yaml"
    visual_config = load_visual_config(config_path)

    assert visual_config.__class__.__name__ == "SimpleYamlConfig"
    assert getattr(visual_config, "message", None) == "hello world"
    assert getattr(visual_config, "type", None) == PYTHON_VISUAL_TYPE
    assert "schema" not in visual_config.model_dump()

    definition = get_visual_pipeline_definition(PYTHON_VISUAL_TYPE)
    assert definition is not None


def test_python_cartesian_visual_receives_cartesian_config() -> None:
    config_path = FIXTURES / "cartesian_python_visual.yaml"
    visual_config = load_visual_config(config_path)

    assert isinstance(visual_config, PythonCartesianChartConfig)
    assert getattr(visual_config, "type", None) == PYTHON_VISUAL_TYPE
    assert visual_config.series[0].metric.key == "some_metric"

    definition = get_visual_pipeline_definition(PYTHON_VISUAL_TYPE)
    assert definition is not None

    pipeline = VisualPipeline()
    context = ExecutionContext(options=PipelineOptions())
    schema_artifact: SchemaArtifact[object] = definition.schema_builder(pipeline, visual_config, context)
    dataset_artifact = definition.dataset_builder(pipeline, visual_config, schema_artifact, context)

    assert dataset_artifact.value == {"series_ids": ["s1"]}


def test_python_visual_loader_surfaces_missing_and_multiple_visuals() -> None:
    zero_path = FIXTURES / "no_python_visual.py"
    multi_path = FIXTURES / "multiple_python_visuals.py"

    with pytest.raises(ValueError, match="No PythonVisualBase subclasses"):
        load_python_visual_module(zero_path)

    with pytest.raises(ValueError, match="Multiple Python visuals found"):
        load_python_visual_module(multi_path)


def test_registered_cartesian_visuals_still_load() -> None:
    visual_path = Path("tests/cartesian/visual.yaml")
    visual_config = load_visual_config(visual_path)

    assert isinstance(visual_config, CartesianChartConfig)
    assert visual_config.type == "column"


def test_yaml_python_visual_cli_applies_context_calculate_filters(tmp_path, capsys) -> None:
    builder_module = (FIXTURES / "builder_visual.py").resolve()

    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    (metrics_root / "documents_sent.yaml").write_text(
        "\n".join(
            [
                "schema: draft-1",
                "key: documents_sent",
                "display_name: Documents sent",
                "section: Test",
                "define: 'COUNTROWS ( \"fact_documents\" )'",
                "variants:",
                "  within_4_hours:",
                "    display_name: Documents sent within 4 hours",
                "    calculate:",
                "      - TRUE()",
            ]
        ),
        encoding="utf-8",
    )

    visual_yaml_path = tmp_path / "builder_visual.yaml"
    visual_yaml_path.write_text(
        dedent(
            f"""
            type: "{builder_module.as_posix()}"
            """
        ).lstrip(),
        encoding="utf-8",
    )

    context_yaml_path = tmp_path / "context.yaml"
    context_yaml_path.write_text(
        dedent(
            """
            context:
              lender_id: 199
            calculate:
              lender: "'dim_lender'[LenderId] = {{ lender_id }}"
            """
        ).lstrip(),
        encoding="utf-8",
    )

    dest_png_path = tmp_path / "out.png"
    argv = [
        "visual",
        "run",
        str(visual_yaml_path),
        str(dest_png_path),
        "--context",
        str(context_yaml_path),
        "--metrics-root",
        str(metrics_root),
        "--print-dax",
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    captured = capsys.readouterr().out
    assert "'dim_lender'[LenderId] = 199" in captured

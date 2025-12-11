from __future__ import annotations

from pathlib import Path

import pytest

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

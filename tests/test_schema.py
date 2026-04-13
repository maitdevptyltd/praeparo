from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from collections.abc import Mapping

from praeparo.models import BaseVisualConfig
from praeparo.schema import (
    component_json_schema,
    context_layer_json_schema,
    run as run_schema_cli,
    visual_umbrella_json_schema,
    write_component_schema,
    write_context_layer_schema,
    write_visual_umbrella_schema,
)
from praeparo.visuals import register_visual_schema


class _PluginSchemaVisual(BaseVisualConfig):
    type: Literal["plugin_schema_visual"] = "plugin_schema_visual"
    value: str


def _resolve_branch(schema: dict[str, object], type_name: str) -> dict[str, object]:
    discriminator = schema["discriminator"]
    assert isinstance(discriminator, Mapping)
    mapping = discriminator["mapping"]
    assert isinstance(mapping, Mapping)
    ref = mapping[type_name]
    key = str(ref).split("/")[-1]
    definitions = schema["$defs"]
    assert isinstance(definitions, Mapping)
    branch = definitions[key]
    assert isinstance(branch, dict)
    return branch


def _resolve_nullable_ref(property_schema: dict[str, object]) -> str:
    any_of = property_schema.get("anyOf")
    assert isinstance(any_of, list)
    for entry in any_of:
        assert isinstance(entry, dict)
        ref = entry.get("$ref")
        if isinstance(ref, str):
            return ref.split("/")[-1]
    raise AssertionError("Expected nullable ref entry.")


def test_visual_umbrella_schema_contains_builtin_branches() -> None:
    schema = visual_umbrella_json_schema()
    mapping = schema["discriminator"]["mapping"]

    assert {"matrix", "frame", "column", "bar", "powerbi"} <= set(mapping)

    matrix_branch = _resolve_branch(schema, "matrix")
    frame_branch = _resolve_branch(schema, "frame")
    cartesian_branch = _resolve_branch(schema, "column")
    powerbi_branch = _resolve_branch(schema, "powerbi")

    matrix_properties = matrix_branch["properties"]
    frame_properties = frame_branch["properties"]
    cartesian_properties = cartesian_branch["properties"]
    powerbi_properties = powerbi_branch["properties"]

    assert isinstance(matrix_properties, dict)
    assert isinstance(frame_properties, dict)
    assert isinstance(cartesian_properties, dict)
    assert isinstance(powerbi_properties, dict)

    assert "compose" in matrix_properties
    assert "compose" in frame_properties
    assert "compose" in cartesian_properties
    assert "compose" in powerbi_properties

    assert isinstance(matrix_properties["parameters"], dict)
    assert isinstance(frame_properties["parameters"], dict)
    assert isinstance(cartesian_properties["parameters"], dict)
    assert isinstance(powerbi_properties["parameters"], dict)

    assert matrix_properties["parameters"]["type"] == "object"
    assert frame_properties["parameters"]["type"] == "object"
    assert cartesian_properties["parameters"]["type"] == "object"
    assert powerbi_properties["parameters"]["type"] == "array"


def test_visual_umbrella_schema_includes_registered_plugin_branch() -> None:
    register_visual_schema(
        "plugin_schema_visual",
        _PluginSchemaVisual.model_json_schema,
        overwrite=True,
        authoring_parameters=True,
    )

    schema = visual_umbrella_json_schema()
    branch = _resolve_branch(schema, "plugin_schema_visual")

    properties = branch["properties"]
    assert isinstance(properties, dict)
    assert "compose" in properties
    assert isinstance(properties["parameters"], dict)
    assert properties["parameters"]["type"] == "object"


def test_write_visual_umbrella_schema_writes_destination(tmp_path: Path) -> None:
    destination = tmp_path / "schemas" / "visual_umbrella.schema.json"

    write_visual_umbrella_schema(destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["title"] == "PraeparoVisualUmbrellaConfig"


def test_component_schema_only_exposes_supported_top_level_keys() -> None:
    schema = component_json_schema()

    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {"schema", "explain"}
    assert schema["additionalProperties"] is False

    required = schema["required"]
    assert isinstance(required, list)
    assert set(required) == {"schema", "explain"}

    schema_property = properties["schema"]
    explain_property = properties["explain"]
    assert isinstance(schema_property, dict)
    assert isinstance(explain_property, dict)
    assert schema_property["const"] == "component-draft-1"
    assert "$ref" in explain_property


def test_write_component_schema_writes_destination(tmp_path: Path) -> None:
    destination = tmp_path / "schemas" / "components.json"

    write_component_schema(destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["title"] == "MetricComponentDocument"


def test_context_layer_schema_supports_pack_metrics_and_top_level_fragments() -> None:
    schema = context_layer_json_schema()

    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert {"context", "calculate", "define", "filters"} <= set(properties)
    assert schema["additionalProperties"] is True

    context_property = properties["context"]
    calculate_property = properties["calculate"]
    assert isinstance(context_property, dict)
    assert isinstance(calculate_property, dict)
    assert "anyOf" in context_property
    assert "anyOf" in calculate_property

    definitions = schema["$defs"]
    assert isinstance(definitions, dict)

    context_ref = _resolve_nullable_ref(context_property)
    fragments_ref = _resolve_nullable_ref(calculate_property)
    context_definition = definitions[context_ref]
    fragments_definition = definitions[fragments_ref]

    assert isinstance(context_definition, dict)
    assert isinstance(fragments_definition, dict)

    context_properties = context_definition["properties"]
    assert isinstance(context_properties, dict)
    assert "metrics" in context_properties
    assert context_definition["additionalProperties"] is True

    metrics_property = context_properties["metrics"]
    assert isinstance(metrics_property, dict)
    metrics_ref = str(metrics_property["anyOf"][0]["$ref"]).split("/")[-1]
    metrics_definition = definitions[metrics_ref]
    assert isinstance(metrics_definition, dict)

    metrics_properties = metrics_definition["properties"]
    assert isinstance(metrics_properties, dict)
    assert {"bindings", "calculate", "allow_empty"} <= set(metrics_properties)

    fragments_any_of = fragments_definition["anyOf"]
    assert isinstance(fragments_any_of, list)
    assert {"string", "object", "array"} == {entry["type"] for entry in fragments_any_of}


def test_write_context_layer_schema_writes_destination(tmp_path: Path) -> None:
    destination = tmp_path / "schemas" / "context_layer.json"

    write_context_layer_schema(destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["title"] == "ContextLayerDocument"


def test_advanced_component_export_only_writes_requested_schema(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = run_schema_cli(["--components", "schemas/components.json"])

    assert exit_code == 0
    assert (tmp_path / "schemas" / "components.json").exists()
    assert not (tmp_path / "schemas" / "matrix.json").exists()


def test_advanced_context_layer_export_only_writes_requested_schema(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = run_schema_cli(["--context-layer", "schemas/context_layer.json"])

    assert exit_code == 0
    assert (tmp_path / "schemas" / "context_layer.json").exists()
    assert not (tmp_path / "schemas" / "visual_umbrella.schema.json").exists()

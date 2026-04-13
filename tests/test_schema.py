from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from collections.abc import Mapping

from praeparo.models import BaseVisualConfig
from praeparo.schema import visual_umbrella_json_schema, write_visual_umbrella_schema
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

from pathlib import Path

import pytest

from praeparo.io.yaml_loader import ConfigLoadError, load_matrix_config, load_visual_config
from praeparo.models import MatrixConfig


def test_load_matrix_config_success(tmp_path: Path) -> None:
    path = tmp_path / "matrix.yaml"
    path.write_text(
        """
        type: matrix
        rows:
          - "{{table.column}}"
        values:
          - id: "Value"


        """,
        encoding="utf-8",
    )

    config = load_matrix_config(path)

    assert config.type == "matrix"
    assert [row.template for row in config.rows] == ["{{table.column}}"]
    assert config.values[0].id == "Value"


def test_load_matrix_config_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("type: [::]", encoding="utf-8")

    with pytest.raises(ConfigLoadError):
        load_matrix_config(path)


def test_load_matrix_config_supports_composition_and_parameters(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        """
        type: matrix
        title: Base Title
        rows:
          - template: "{{dim.City}}"
            label: "{{title}}"
        values:
          - id: "Total"
        filters:
          - expression: "Flag = {{Flag}}"
        parameters:
          Flag: "DEFAULT"
        """,
        encoding="utf-8",
    )

    child = tmp_path / "child.yaml"
    child.write_text(
        """
        compose:
          - ./base.yaml
        title: Child Title
        parameters:
          Flag: "TRUE()"
        """,
        encoding="utf-8",
    )

    config = load_matrix_config(child)

    assert config.title == "Child Title"
    assert config.rows[0].label == "Child Title"
    assert config.filters[0].expression == "Flag = TRUE()"


def test_load_visual_config_frame_resolves_parameters_and_overrides(tmp_path: Path) -> None:
    matrix = tmp_path / "child.yaml"
    matrix.write_text(
        """
        type: matrix
        title: Matrix Title
        rows:
          - template: "{{dim.City}}"
            label: "{{CityLabel}}"
        values:
          - id: "Total"
        filters:
          - expression: "{{FilterExpression}}"
        parameters:
          CityLabel: "Default"
          FilterExpression: "Flag = DEFAULT"
        """,
        encoding="utf-8",
    )

    frame = tmp_path / "frame.yaml"
    frame.write_text(
        """
        type: frame
        title: Parent Frame
        children:
          - ref: ./child.yaml
            parameters:
              CityLabel: Downtown
              FilterExpression: "Flag = TRUE()"
            title: "Child Override Title"
            description: "Child override description"
        """,
        encoding="utf-8",
    )

    visual = load_visual_config(frame)
    assert visual.type == "frame"
    assert len(visual.children) == 1

    child = visual.children[0]
    assert child.visual.title == "Child Override Title"
    assert child.visual.description == "Child override description"
    assert child.visual.filters[0].expression == "Flag = TRUE()"
    assert child.visual.rows[0].label == "Downtown"
    assert child.parameters == {"CityLabel": "Downtown", "FilterExpression": "Flag = TRUE()"}
    assert child.overrides == {"title": "Child Override Title", "description": "Child override description"}


def test_load_visual_config_applies_runtime_overrides(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.yaml"
    matrix.write_text(
        """
        type: matrix
        title: Base Title
        rows:
          - template: "{{dim.City}}"
        values:
          - id: "Total"
        filters:
          - expression: "{{Expression}}"
        parameters:
          Expression: "Flag = DEFAULT"
        """,
        encoding="utf-8",
    )

    visual = load_visual_config(
        matrix,
        overrides={"title": "Runtime Title"},
        parameters_override={"Expression": "Flag = FALSE()"},
    )

    assert isinstance(visual, MatrixConfig)
    assert visual.title == "Runtime Title"
    assert visual.filters[0].expression == "Flag = FALSE()"

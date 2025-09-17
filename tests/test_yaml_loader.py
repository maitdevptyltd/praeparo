from pathlib import Path

import pytest

from praeparo.io.yaml_loader import ConfigLoadError, load_matrix_config


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

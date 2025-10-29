from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.models.visual_base import BaseVisualConfig
from praeparo.visuals import load_visual_definition, register_visual_type


class DummyVisual(BaseVisualConfig):
    model_config = BaseVisualConfig.model_config

    payload: str


def _dummy_loader(path: Path, payload: dict[str, object], stack: tuple[Path, ...]) -> DummyVisual:
    return DummyVisual(type=payload["type"], title=payload.get("title"), description=None, payload=payload.get("payload", ""))


def test_register_and_load_visual(tmp_path: Path) -> None:
    register_visual_type("dummy", _dummy_loader, overwrite=True)
    visual_path = tmp_path / "visual.yaml"
    visual_path.write_text("""type: dummy\npayload: example""", encoding="utf-8")

    config = load_visual_definition(visual_path)
    assert isinstance(config, DummyVisual)
    assert config.payload == "example"


def test_load_visual_unknown_type(tmp_path: Path) -> None:
    visual_path = tmp_path / "visual.yaml"
    visual_path.write_text("""type: unknown""", encoding="utf-8")

    with pytest.raises(ValueError, match="not registered"):
        load_visual_definition(visual_path)


def test_load_visual_missing_type(tmp_path: Path) -> None:
    visual_path = tmp_path / "visual.yaml"
    visual_path.write_text("""title: Missing Type""", encoding="utf-8")

    with pytest.raises(ValueError, match="must define a non-empty 'type'"):
        load_visual_definition(visual_path)


def test_register_visual_type_prevents_duplicate() -> None:
    register_visual_type("duplicate", _dummy_loader, overwrite=True)
    with pytest.raises(ValueError):
        register_visual_type("duplicate", _dummy_loader)


def test_load_visual_detects_cycle(tmp_path: Path) -> None:
    register_visual_type("cycle", _dummy_loader, overwrite=True)
    file_a = tmp_path / "a.yaml"
    file_b = tmp_path / "b.yaml"
    file_a.write_text("""type: cycle\nnext: b.yaml""", encoding="utf-8")
    file_b.write_text("""type: cycle\nnext: a.yaml""", encoding="utf-8")

    def loader(path: Path, payload: dict[str, object], stack: tuple[Path, ...]) -> DummyVisual:
        next_ref = payload.get("next")
        if isinstance(next_ref, str):
            load_visual_definition(next_ref, base_path=path.parent, stack=stack)
        return DummyVisual(type=payload["type"], title=None, description=None, payload="cycle")

    register_visual_type("cycle", loader, overwrite=True)

    with pytest.raises(ValueError, match="Circular visual reference"):
        load_visual_definition(file_a)

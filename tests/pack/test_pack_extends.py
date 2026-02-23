from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from praeparo.pack.loader import PackConfigError, load_pack_config


def _write(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def test_pack_extends_applies_slide_operations_in_order(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    _write(
        base,
        """
        schema: base-pack
        context:
          customer: "Base"
        slides:
          - id: a
            title: "A"
            visual:
              ref: one.yaml
          - id: b
            title: "B"
            visual:
              ref: two.yaml
          - id: c
            title: "C"
            visual:
              ref: three.yaml
          - id: tail
            title: "Tail"
            visual:
              ref: tail.yaml
        """,
    )

    child = tmp_path / "child.yaml"
    _write(
        child,
        """
        schema: child-pack
        extends: ./base.yaml
        context:
          customer: "Child"
        slides_remove:
          - c
        slides_replace:
          - id: b
            slide:
              id: b
              title: "B replaced"
              visual:
                ref: two_replaced.yaml
        slides_update:
          - id: a
            patch:
              notes: "patched a"
              visual:
                ref: one_updated.yaml
        slides_insert:
          - after: b
            slide:
              id: b_extra
              title: "B extra"
              visual:
                ref: b_extra.yaml
        """,
    )

    pack = load_pack_config(child)
    assert pack.context.model_dump(mode="python").get("customer") == "Child"
    assert [slide.id for slide in pack.slides] == ["a", "b", "b_extra", "tail"]

    slide_a = pack.slides[0]
    assert slide_a.notes == "patched a"
    assert slide_a.visual is not None
    assert slide_a.visual.ref == "one_updated.yaml"

    slide_b = pack.slides[1]
    assert slide_b.title == "B replaced"
    assert slide_b.visual is not None
    assert slide_b.visual.ref == "two_replaced.yaml"


def test_pack_extends_full_slide_override_mode(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    _write(
        base,
        """
        schema: base-pack
        slides:
          - id: a
            title: "A"
            visual:
              ref: one.yaml
          - id: b
            title: "B"
            visual:
              ref: two.yaml
        """,
    )

    child = tmp_path / "child.yaml"
    _write(
        child,
        """
        schema: child-pack
        extends: ./base.yaml
        slides:
          - id: x
            title: "Only X"
            visual:
              ref: x.yaml
        """,
    )

    pack = load_pack_config(child)
    assert [slide.id for slide in pack.slides] == ["x"]


def test_pack_extends_rejects_mixed_override_modes(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    _write(
        base,
        """
        schema: base-pack
        slides:
          - id: a
            title: "A"
            visual:
              ref: one.yaml
        """,
    )

    child = tmp_path / "child.yaml"
    _write(
        child,
        """
        schema: child-pack
        extends: ./base.yaml
        slides:
          - id: b
            title: "B"
            visual:
              ref: two.yaml
        slides_remove: []
        """,
    )

    with pytest.raises(PackConfigError, match="cannot define both slides and slides_\\* operations"):
        load_pack_config(child)


def test_pack_extends_rejects_missing_parent(tmp_path: Path) -> None:
    child = tmp_path / "child.yaml"
    _write(
        child,
        """
        schema: child-pack
        extends: ./missing.yaml
        """,
    )

    with pytest.raises(PackConfigError, match="Failed to read pack configuration"):
        load_pack_config(child)


def test_pack_extends_detects_circular_extends(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"

    _write(
        first,
        """
        schema: first-pack
        extends: ./second.yaml
        """,
    )
    _write(
        second,
        """
        schema: second-pack
        extends: ./first.yaml
        """,
    )

    with pytest.raises(PackConfigError, match="circular pack extends"):
        load_pack_config(first)


def test_pack_extends_insert_anchor_must_exist(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    _write(
        base,
        """
        schema: base-pack
        slides:
          - id: a
            title: "A"
            visual:
              ref: one.yaml
        """,
    )

    child = tmp_path / "child.yaml"
    _write(
        child,
        """
        schema: child-pack
        extends: ./base.yaml
        slides_insert:
          - after: missing_anchor
            slide:
              id: x
              title: "Inserted"
              visual:
                ref: x.yaml
        """,
    )

    with pytest.raises(PackConfigError, match="anchor 'missing_anchor' was not found"):
        load_pack_config(child)


def test_pack_extends_patch_mode_requires_inherited_slide_ids(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    _write(
        base,
        """
        schema: base-pack
        slides:
          - title: "No id"
            visual:
              ref: one.yaml
        """,
    )

    child = tmp_path / "child.yaml"
    _write(
        child,
        """
        schema: child-pack
        extends: ./base.yaml
        slides_update:
          - id: x
            patch:
              notes: "test"
        """,
    )

    with pytest.raises(PackConfigError, match="requires slide.id"):
        load_pack_config(child)


def test_pack_extends_rebases_inherited_pptx_template_path(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    child_dir = tmp_path / "child"
    base_dir.mkdir(parents=True, exist_ok=True)
    child_dir.mkdir(parents=True, exist_ok=True)

    base = base_dir / "base.yaml"
    _write(
        base,
        """
        schema: base-pack
        pptx_template: ./templates/base_template.pptx
        slides:
          - id: a
            title: "A"
            visual:
              ref: one.yaml
        """,
    )

    child = child_dir / "child.yaml"
    _write(
        child,
        """
        schema: child-pack
        extends: ../base/base.yaml
        """,
    )

    pack = load_pack_config(child)
    assert pack.pptx_template == "../base/templates/base_template.pptx"

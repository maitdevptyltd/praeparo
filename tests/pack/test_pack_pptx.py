from __future__ import annotations

import base64
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches

from praeparo.pack.pptx import assemble_pack_pptx
from praeparo.models import PackConfig, PackPlaceholder, PackSlide, PackVisualRef
from praeparo.visuals.dax.planner_core import slugify


def _write_png(path: Path) -> None:
    # 1x1 transparent PNG
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
        "AAL/AXx5lXcAAAAASUVORK5CYII="
    )
    path.write_bytes(data)


def _build_template(path: Path) -> None:
    prs = Presentation()
    blank = prs.slide_layouts[6]

    # Single-image template
    single = prs.slides.add_slide(blank)
    tmp_img = path.parent / "tmp.png"
    _write_png(tmp_img)
    pic = single.shapes.add_picture(str(tmp_img), Inches(1), Inches(1), width=Inches(4), height=Inches(3))
    pic.name = "image"
    single.notes_slide.notes_text_frame.text = "TEMPLATE_TAG=single_image"

    # Two-up template
    two_up = prs.slides.add_slide(blank)
    left = two_up.shapes.add_picture(str(tmp_img), Inches(0.5), Inches(1), width=Inches(3), height=Inches(2.5))
    left.name = "left_chart"
    right = two_up.shapes.add_picture(str(tmp_img), Inches(4), Inches(1), width=Inches(3), height=Inches(2.5))
    right.name = "right_chart"
    two_up.notes_slide.notes_text_frame.text = "TEMPLATE_TAG=two_up"

    prs.save(path)
    tmp_img.unlink(missing_ok=True)


def test_assemble_pptx_single_placeholder_shorthand(tmp_path: Path) -> None:
    template_path = tmp_path / "template.pptx"
    _build_template(template_path)

    pack = PackConfig(
        schema="test-pack",
        slides=[
            PackSlide(
                title="With Template",
                id="with_template",
                template="single_image",
                visual=PackVisualRef(ref="vis.yaml"),
            )
        ],
    )

    slide_slug = slugify("with_template")
    png_path = tmp_path / f"{slide_slug}.png"
    _write_png(png_path)

    out = tmp_path / "deck.pptx"
    assemble_pack_pptx(
        pack=pack,
        results=[],
        slide_pngs={slide_slug: png_path},
        placeholder_pngs={},
        result_path=out,
        template_path=template_path,
    )

    prs = Presentation(out)
    assert len(prs.slides) == 1
    picture_shapes = [s for s in prs.slides[0].shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert picture_shapes  # image placed


def test_assemble_pptx_multi_placeholder_and_skip_no_template(tmp_path: Path) -> None:
    template_path = tmp_path / "template.pptx"
    _build_template(template_path)

    pack = PackConfig(
        schema="test-pack",
        slides=[
            PackSlide(
                title="Two Up",
                id="two_up",
                template="two_up",
                placeholders={
                    "left_chart": PackPlaceholder(visual=PackVisualRef(ref="left.yaml")),
                    "right_chart": PackPlaceholder(visual=PackVisualRef(ref="right.yaml")),
                },
            ),
            PackSlide(
                title="No Template",
                id="no_template",
                visual=PackVisualRef(ref="plain.yaml"),
            ),
            PackSlide(
                title="Another Template",
                id="another_template",
                template="single_image",
                visual=PackVisualRef(ref="third.yaml"),
            ),
        ],
    )

    two_slug = slugify("two_up")
    left_png = tmp_path / f"{two_slug}_left.png"
    right_png = tmp_path / f"{two_slug}_right.png"
    _write_png(left_png)
    _write_png(right_png)
    placeholder_pngs = {two_slug: {f"{two_slug}__{slugify('left_chart')}": left_png, f"{two_slug}__{slugify('right_chart')}": right_png}}

    third_slug = slugify("another_template")
    third_png = tmp_path / f"{third_slug}.png"
    _write_png(third_png)

    out = tmp_path / "deck_multi.pptx"
    assemble_pack_pptx(
        pack=pack,
        results=[],
        slide_pngs={third_slug: third_png},
        placeholder_pngs=placeholder_pngs,
        result_path=out,
        template_path=template_path,
    )

    prs = Presentation(out)
    assert len(prs.slides) == 2  # no-template slide skipped

    first_slide_pictures = [s for s in prs.slides[0].shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert len(first_slide_pictures) >= 2

    second_slide_pictures = [s for s in prs.slides[1].shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert second_slide_pictures


def test_assemble_pptx_handles_template_only_slide(tmp_path: Path) -> None:
    template_path = tmp_path / "template.pptx"
    _build_template(template_path)

    pack = PackConfig(
        schema="test-pack",
        slides=[
            PackSlide(title="Static Home", id="static-home", template="single_image"),
            PackSlide(
                title="Visual Slide",
                id="visual-slide",
                template="single_image",
                visual=PackVisualRef(ref="one.yaml"),
            ),
        ],
    )

    slide_slug = slugify("visual-slide")
    png_path = tmp_path / f"{slide_slug}.png"
    _write_png(png_path)

    out = tmp_path / "deck_static.pptx"
    assemble_pack_pptx(
        pack=pack,
        results=[],
        slide_pngs={slide_slug: png_path},
        placeholder_pngs={},
        result_path=out,
        template_path=template_path,
    )

    prs = Presentation(out)
    assert len(prs.slides) == 2
    static_pictures = [s for s in prs.slides[0].shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert static_pictures, "Template-only slide should retain its image without errors"

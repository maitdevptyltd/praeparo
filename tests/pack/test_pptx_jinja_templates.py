from __future__ import annotations

from datetime import date
from pathlib import Path

from pptx import Presentation

from praeparo.models import PackConfig, PackSlide
from praeparo.pack.pptx import _iter_shapes, _notes_template_tags, assemble_pack_pptx


ASSET_TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "pack_template.pptx"


def _paragraph_texts(slide) -> list[str]:
    texts: list[str] = []
    for shape in _iter_shapes(slide.shapes):
        if not getattr(shape, "has_text_frame", False):
            continue
        text_frame = shape.text_frame
        if text_frame is None:
            continue
        for paragraph in text_frame.paragraphs:
            texts.append(paragraph.text)
    return texts


def test_pptx_template_renders_display_date(tmp_path: Path) -> None:
    pack = PackConfig(
        schema="test-pack",
        context={"display_date": date(2025, 1, 15)},
        slides=[PackSlide(title="Home", id="home-slide", template="home")],
    )

    out = tmp_path / "rendered.pptx"
    assemble_pack_pptx(
        pack=pack,
        results=[],
        slide_pngs={},
        placeholder_pngs={},
        result_path=out,
        template_path=ASSET_TEMPLATE,
    )

    prs = Presentation(out)
    slide = prs.slides[0]
    texts = _paragraph_texts(slide)
    joined = " ".join(texts)

    assert "{{display_date}}" not in joined
    assert "2025-01-15" in joined


def test_pptx_jinja_preserves_static_text(tmp_path: Path) -> None:
    template_prs = Presentation(ASSET_TEMPLATE)
    template_lookup = _notes_template_tags(template_prs)
    expected_static = {
        "Instructions Received",
        "Documents Sent",
        "Matters Settled",
    }
    template_name, template_slide = next(
        (
            name,
            slide,
        )
        for name, slide in template_lookup.items()
        if expected_static.issubset(set(_paragraph_texts(slide)))
    )

    pack = PackConfig(
        schema="test-pack",
        context={"display_date": date(2025, 1, 15)},
        slides=[
            PackSlide(
                title="Highlights",
                id="highlights-slide",
                template=template_name,
            )
        ],
    )

    out = tmp_path / "static.pptx"
    assemble_pack_pptx(
        pack=pack,
        results=[],
        slide_pngs={},
        placeholder_pngs={},
        result_path=out,
        template_path=ASSET_TEMPLATE,
    )

    rendered_slide = Presentation(out).slides[0]
    rendered_static = {text for text in _paragraph_texts(rendered_slide) if text and "{{" not in text}

    assert expected_static.issubset(rendered_static)

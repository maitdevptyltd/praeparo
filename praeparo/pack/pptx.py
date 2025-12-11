"""PPTX assembly helpers for pack outputs.

Slides without a PPTX template are deliberately skipped: PNG artefacts remain
available for downstream consumers, and PPTX composition stays an optional
layer on top of the pack PNG pipeline.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

from praeparo.models import PackConfig, PackSlide
from praeparo.visuals.dax.planner_core import slugify


def _slug_for_slide(slide: PackSlide, index: int) -> str:
    if slide.id:
        return slugify(slide.id)
    if slide.title:
        return slugify(slide.title)
    return f"slide_{index}"

logger = logging.getLogger(__name__)


def _clear_slides(presentation: Presentation) -> None:
    """Remove all slides from *presentation* preserving layouts and theme."""
    # python-pptx does not expose public removal; prefer starting from a fresh
    # presentation when possible. This helper is retained for future use but
    # intentionally left empty to avoid relying on private attributes.
    if presentation.slides:
        return


def _clone_slide(presentation: Presentation, template_slide) -> object:
    """Clone *template_slide* into *presentation* preserving shapes."""

    blank_layout = presentation.slide_layouts[0]
    new_slide = presentation.slides.add_slide(blank_layout)

    # Drop any shapes added by the blank layout so the clone matches the template.
    for shape in list(new_slide.shapes):
        new_slide.shapes._spTree.remove(shape._element)  # type: ignore[attr-defined]

    for shape in template_slide.shapes:
        new_slide.shapes._spTree.insert_element_before(copy.deepcopy(shape._element), "p:extLst")  # type: ignore[attr-defined]

    return new_slide


def _picture_shapes(slide) -> list:
    shapes = []
    for shape in slide.shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            shapes.append(shape)
            continue
        if getattr(shape, "is_placeholder", False):
            try:
                if shape.placeholder_format.type == PP_PLACEHOLDER.PICTURE:
                    shapes.append(shape)
            except ValueError:
                # Some placeholders (e.g. missing type) may raise; skip them.
                continue
    return shapes


def _replace_picture(shape, image_path: Path) -> None:
    slide = shape.part.slide
    left, top, width, height = shape.left, shape.top, shape.width, shape.height
    name = getattr(shape, "name", None)
    shape._element.getparent().remove(shape._element)
    pic = slide.shapes.add_picture(str(image_path), left, top, width=width, height=height)
    if name:
        pic.name = name


def _notes_template_tags(presentation: Presentation) -> dict[str, object]:
    """Return a mapping of TEMPLATE_TAG id -> slide object."""

    tags: dict[str, object] = {}
    for slide in presentation.slides:
        try:
            text = "".join(slide.notes_slide.notes_text_frame.text.split())
        except Exception:
            continue
        if "TEMPLATE_TAG=" not in text:
            continue
        token = text.split("TEMPLATE_TAG=", 1)[1].split()[0]
        if token:
            tags[token] = slide
    return tags


def assemble_pack_pptx(
    *,
    pack: PackConfig,
    results: Sequence[object] | None,
    slide_pngs: Mapping[str, Path],
    placeholder_pngs: Mapping[str, Mapping[str, Path]] | None = None,
    result_path: Path,
    template_path: Path | None = None,
) -> None:
    """Build a PPTX from pack results using optional slide templates.

    Slides without a template are skipped rather than failing the run.
    """

    placeholder_pngs = placeholder_pngs or {}

    presentation = Presentation()

    template_lookup: Mapping[str, object] = {}
    template_source = Presentation(template_path) if template_path else None
    if template_source:
        template_lookup = _notes_template_tags(template_source)

    def _lookup_placeholder(slide_slug: str, placeholder_id: str) -> Path | None:
        placeholders = placeholder_pngs.get(slide_slug, {})
        key_slug = f"{slide_slug}__{slugify(placeholder_id)}"
        return placeholders.get(key_slug)

    for index, slide in enumerate(pack.slides, start=1):
        slide_slug = _slug_for_slide(slide, index)

        if slide.template:
            template_slide = template_lookup.get(slide.template)
            if template_slide is None:
                raise ValueError(f"Template '{slide.template}' not found for slide '{slide_slug}'")
        else:
            logger.info(
                "Skipping PPTX assembly for slide without template",
                extra={"slide": slide_slug},
            )
            continue

        cloned = _clone_slide(presentation, template_slide)

        # Title placeholder, if present.
        for shape in cloned.shapes:
            if getattr(shape, "is_placeholder", False):
                try:
                    if shape.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE):
                        shape.text = slide.title
                        break
                except ValueError:
                    continue

        has_placeholders = bool(slide.placeholders)
        has_visual = slide.visual is not None

        if has_placeholders:
            placeholders = slide.placeholders or {}
            for placeholder_id in placeholders:
                image_path = _lookup_placeholder(slide_slug, placeholder_id)
                if image_path is None:
                    raise ValueError(f"Missing PNG for placeholder '{placeholder_id}' on slide '{slide_slug}'")

                picture_shapes = [shape for shape in cloned.shapes if getattr(shape, "name", None) == placeholder_id]
                if not picture_shapes:
                    picture_shapes = _picture_shapes(cloned)
                    picture_shapes = [shape for shape in picture_shapes if getattr(shape, "name", None) == placeholder_id]

                if not picture_shapes:
                    raise ValueError(f"Placeholder '{placeholder_id}' not found on template '{slide.template}'")

                _replace_picture(picture_shapes[0], image_path)
        elif has_visual:
            image_path = slide_pngs.get(slide_slug)
            if image_path is None:
                raise ValueError(f"Missing PNG for slide '{slide_slug}'")

            picture_shapes = _picture_shapes(cloned)
            if len(picture_shapes) != 1:
                raise ValueError(
                    f"Slide '{slide_slug}' uses single-visual shorthand but template '{slide.template}' "
                    f"has {len(picture_shapes)} picture placeholders."
                )
            _replace_picture(picture_shapes[0], image_path)
        else:
            logger.info(
                "Rendering template-only slide without visual or placeholders",
                extra={"slide": slide_slug, "template": slide.template},
            )

    result_path.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(result_path)
    logger.info(
        "Wrote PPTX",
        extra={"result_file": str(result_path), "slide_count": len(presentation.slides)},
    )


__all__ = ["assemble_pack_pptx"]

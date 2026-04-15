# Epic: Pack PPTX Shape Blocks (Phase 4)

> Status: **Draft** – Introduce YAML-authored shapes/cards that are rendered directly via python-pptx during pack assembly, letting authors lay out KPI tiles without editing PPTX masters.

> Matrix/table shapes are intentionally out of scope here and will be handled in Phase 5 so the card/text pipeline can ship without a dependency on table rendering.

## 1. Problem

Phase 1 unlocked text placeholders that bind into pre-existing PPTX shapes. Authors still need to open PowerPoint when they want repeatable cards, banners, or captions that do not already exist in the template. A common request is: “Render three KPI cards with a caption centered below them.” Those cards are pure rectangles with text, so we should be able to describe them declaratively in YAML and rely on python-pptx to materialise them in the cloned slide.

## 2. Goals

1. Allow pack slides to declare `shapes:` alongside `placeholders:`.
2. Mirror python-pptx naming so the schema feels native: `auto_shape_type`, `left`, `top`, `width`, `height`, `fill`, `line`, `text_frame` settings.
3. Support anchoring/aligning one shape relative to another (e.g., center card referencing the previous card).
4. Keep text content Jinja-friendly and driven by pack context.
5. Ensure deterministic layering so YAML order === z-order.

Out of scope for this phase: complex grouping, rotation, gradients, or free-form connectors.

## 3. Proposed UX

### 3.1 Slide YAML

```yaml
slides:
  - title: "Overview"
    template: "home"
    placeholders: { ... }  # Phase 1 behaviors
    shapes:
      - id: instructions_card
        auto_shape_type: rounded_rectangle             # mirrors MSO_AUTO_SHAPE_TYPE
        left: 2cm                                      # python-pptx util strings (cm/in)
        top: 4cm
        width: 7.2cm
        height: 3cm
        fill:
          color: "#dae9ff"
        line:
          color: "#7aa0d8"
          width: 2pt
        text_frame:
          paragraphs:
            - style: title
              text: "Instructions Received"
            - style: subtitle
              text: "{{ count_instructions }}"
      - id: documents_card
        inherit: instructions_card                     # optional style preset
        anchor:
          ref: instructions_card
          align: middle_right                          # uses PP_ALIGN tokens for clarity
          offset_x: 0.5cm
        text_frame:
          paragraphs:
            - style: title
              text: "Documents Sent"
            - style: subtitle
              text: "{{ count_docs_sent }}"
      - id: matters_card
        inherit: instructions_card
        anchor:
          ref: documents_card
          align: middle_right
          offset_x: 0.5cm
        text_frame:
          paragraphs:
            - style: title
              text: "Matters Settled"
            - style: subtitle
              text: "{{ count_settlements }}"
      - id: highlights_body
        auto_shape_type: text_box
        anchor:
          ref: documents_card
          align: bottom_center
          offset_y: 1cm
        width: 7.2cm
        height: 2cm
        text_frame:
          vertical_anchor: middle                      # maps to MSO_VERTICAL_ANCHOR
          paragraphs:
            - style: body
              text: "{{ governance_highlights }}"
              alignment: center                        # PP_ALIGN.CENTER
```

Key ergonomics:
- Dimensions default to cm or in strings; parser converts to EMUs using python-pptx `Cm`/`Inches` helpers.
- `auto_shape_type` accepts python-pptx names (case-insensitive) and maps to `MSO_AUTO_SHAPE_TYPE` values.
- `anchor.align` uses `PP_ALIGN` tokens (`left`, `center`, `right`, `top`, `middle`, `bottom`, plus combos like `bottom_center`).
- `text_frame.vertical_anchor` maps to `MSO_VERTICAL_ANCHOR`.
- `paragraphs[].alignment` maps to `PP_ALIGN` for horizontal alignment.
- `inherit` lets a shape clone fill/line/text styles from a previous definition to avoid repetition.

### 3.2 Authoring rules

- `id` must be unique per slide.
- Either absolute positioning (`left` & `top`) or `anchor.ref` is required. When `anchor` is present, you can omit `left`/`top` and supply offsets.
- YAML order determines z-order (first entry is rendered first / sits underneath later entries).
- Text content is rendered after shapes are added so we can reuse Phase 1’s Jinja pipeline.

Note: if you reference a slide-context field like `{{ governance_highlights }}` and that field’s value itself contains Jinja (for example `{{ count_instructions_mom }}` from metric bindings), Praeparo must render that slide-context string after metric bindings resolve. Otherwise the inner placeholders will remain unexpanded.

## 4. Design

### 4.1 Schema (`praeparo.models.pack`)

- Add `PackSlideShape` model with fields:
  - `id: str`
  - `auto_shape_type: str = "rounded_rectangle"`
  - `left | top | width | height: Optional[Dimension]` where `Dimension` accepts strings like `"7cm"`, numbers (EMU), or dictionaries (`{cm: 7}`) and normalises to EMUs using python-pptx `Cm`, `Inches`, or raw integers.
  - `anchor: SlideAnchor | None` with fields `ref: str`, `align: PPAlignLiteral`, `offset_x`, `offset_y`.
  - `inherit: str | None` referencing a prior shape `id`.
  - `fill: FillStyle`, `line: LineStyle`, `text_frame: TextFrameStyle` mirroring python-pptx property names (`fill.fore_color`, `line.width`, `text_frame.vertical_anchor`, etc.).
- Validation:
  - Ensure inherits/anchors reference shapes defined earlier in the list.
  - Require either (`left` & `top`) or `anchor`.
  - Provide friendly errors when a developer uses an unknown `auto_shape_type` or `PP_ALIGN` string.

### 4.2 Rendering (`praeparo.pack.pptx`)

1. During slide assembly, after placeholders are processed, iterate over `slide.shapes_config` (new property) and create shapes using python-pptx APIs:
   - Resolve size/position via EMUs.
   - Use `slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE, left, top, width, height)` for cards, or `add_textbox` when `auto_shape_type == "text_box"`.
   - Apply fill via `shape.fill.solid()` and `shape.fill.fore_color.rgb`.
   - Apply line settings (`shape.line.color.rgb`, `shape.line.width`).
2. If `inherit` is set, clone visual properties from the source shape after creation.
3. Apply text:
   - Clear existing paragraphs.
   - For each YAML paragraph, add a python-pptx paragraph, set `alignment` (maps to `PP_ALIGN`), assign font tokens (size, bold, color) via `paragraph.font`.
   - Render `text` through the same Jinja env + slide context.
   - Respect `text_frame.vertical_anchor` (maps to `shape.text_frame.vertical_anchor`).
4. Store each shape’s bounding box so later anchors can use it.
5. Offsets (cm or px) convert to EMUs and add to the referenced edge before positioning.

### 4.3 Testing

- Unit tests for the new models to ensure:
  - Dimension parsing works for cm/in/pt/raw integers.
  - Invalid `auto_shape_type` / `align` produce clear errors.
  - Anchor ordering validation.
- Integration test in `tests/pack/test_pack_runner.py` (or dedicated module) that:
  - Builds a slide with the three cards + caption example.
  - Opens the generated PPTX and asserts shapes exist with expected `left/top` values (± small tolerance) and rendered text.
  - Confirms z-order (e.g., caption sits above cards when declared later).

## 5. Validation

From the Praeparo repo root:

```bash
poetry run pytest tests/pack/test_pack_runner.py::test_yaml_shapes
poetry run pyright praeparo/models/pack.py praeparo/pack/pptx.py
poetry run python -m praeparo.schema --pack schemas/pack.json
```

## 6. Risks / Open Questions

- **Unit interpretation:** `python-pptx` accepts integers (EMUs) or helpers (`Cm`). We standardise on strings with unit suffixes to avoid confusion, but need solid documentation.
- **Style inheritance depth:** MVP supports single-level inherit; nested inheritance may complicate validation and can be deferred.
- **Performance:** Rendering extra shapes adds python-pptx overhead; acceptable for small card counts.
- **Accessibility:** Need to ensure text remains accessible for screen readers (python-pptx should maintain structure, but confirm).

## 7. Next Steps

1. Implement schema + validators for `shapes`.
2. Extend PPTX assembler to render shapes post-placeholder.
3. Add tests + schema regen.
4. Update `docs/projects/pack_runner.md` with authoring guidance/examples.
```

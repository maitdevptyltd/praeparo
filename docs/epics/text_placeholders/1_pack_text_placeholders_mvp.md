# Epic: Pack Text Placeholders (Phase 1)

> Status: **Complete** – packs can bind `placeholders.*.text` into named PPTX text shapes using the pack’s Jinja context (2025-12-13).

- Implementation landed upstream in `praeparo/models/pack.py` (placeholder `text` binding) and `praeparo/pack/pptx.py` (injection by shape name).
- Canonical operator docs live in `docs/projects/pack_runner.md` (“Text placeholders”).
- Coverage exists in `tests/pack/test_pack_runner.py` (named text placeholder pack run).

## 1. Problem

Pack templates can rely on inline Jinja inside PPTX text runs. This works, but
is fragile:

- Authors must edit the PPTX to add `{{ ... }}` tokens directly into text boxes.
- Complex templates with multiple runs can split a token across runs, making
  it hard to maintain.
- The pack YAML has no first‑class way to declare “this placeholder should be
  replaced with this string”.

We want parity with image/visual placeholders: the YAML should be able to bind
content to a **named text placeholder** without requiring inline Jinja in the
template itself.

## 2. Goals

Phase 1 delivers:

1. Extend pack schema so placeholders can bind plain text.
2. Render those bindings using the same Jinja context that powers packs.
3. Inject rendered text into named text shapes during PPTX assembly.
4. Preserve existing inline‑Jinja behavior for backward compatibility.

Out of scope:

- Markdown / rich text formatting (Phase 2).
- Cross‑slide computed context (future).
- HTML authoring.

## 3. Proposed UX

### 3.1 Template authoring

In the PPTX template, authors create a text box (or text placeholder) and set
its **Name** to match the YAML placeholder key, e.g. `display_date_text`.

The box may contain a “seed” run with desired font/size/color. The injector
will try to preserve this style.

### 3.2 Pack YAML

**Long form (explicit bindings):**

```yaml
context:
  display_date: "November 2025"

slides:
  - title: "Home"
    template: "home"
    placeholders:
      header_image:
        image: "./assets/logo.png"
      display_date_text:
        text: "{{ display_date }}"
      subtitle_text:
        text:
          - "Customer: {{ customer }}"
          - "Month: {{ month }}"
```

**Shorthand ergonomics (equivalent to long form):**

```yaml
context:
  display_date: "November 2025"

slides:
  - title: "Home"
    template: "home"
    placeholders:
      header_image: "./assets/logo.png"
      display_date_text: "{{ display_date }}"
      subtitle_text:
        text:
          - "Customer: {{ customer }}"
          - "Month: {{ month }}"
```

Rules:
- Placeholder entries remain mutually exclusive:
  - `visual` (existing)
  - `image` (existing)
  - `text` (new)
- Placeholder values may be declared in shorthand:
  - A scalar string is interpreted as `image` when it looks path-like (contains `/` or `\`, or ends in a common image extension).
  - Otherwise the scalar string is interpreted as `text`.
  - The shorthand is purely ergonomic; the long form above is the canonical representation.
  - Use the explicit object form (`image: ...` or `text: ...`) to force a specific binding when in doubt.
- `text` may be a string or a list of strings. Lists are joined with `\n`.

### 3.3 Render order

During PPTX assembly:
1. Clone template slide.
2. Apply inline Jinja for any text runs already containing `{{ ... }}`.
3. Apply named text placeholders from YAML.
4. Replace picture placeholders from YAML.

This ensures placeholder text can still include Jinja (e.g. `{{ display_date }}`)
and see the same slide context as inline tokens.
> Declarative YAML shape blocks graduated into their own Phase 4 epic (`4_pptx_shape_blocks.md`) so Phase 1 can stay focused on text bindings.

## 4. Design

### 4.1 Schema changes (Praeparo)

File: `praeparo/models/pack.py`

- Extend `PackPlaceholder` with:
  - `text: str | list[str] | None`
- Update validators so **exactly one** of `visual`, `image`, or `text` is set.
- Extend `PackSlide.placeholders` to accept scalar shorthand strings and normalise them into `PackPlaceholder` bindings using the path-like heuristic above.

### 4.2 PPTX assembly changes

File: `praeparo/pack/pptx.py`

Add a text replacement path to `assemble_pack_pptx`:

1. When iterating placeholders, if a placeholder has `text`:
   - Resolve matching text shape by name (`shape.name == placeholder_id`)
     and `shape.has_text_frame`.
   - Render the text via `render_value(..., env=jinja_env, context=slide_context)`.
2. Replace the shape’s runs:
   - Prefer preserving styling by replacing the first run’s text and clearing
     any remaining runs.
   - Fall back to `text_frame.text = rendered_text` if no runs exist.
3. If no matching text shape is found:
   - Raise a `ValueError` listing the missing placeholder name (fail fast).


### 4.3 Unit tests

File: `tests/pack/test_pack_runner.py`

- Add a template fixture with a named text box and named picture placeholders.
- Build a pack that binds:
  - One `image` placeholder.
  - One `text` placeholder.
  - One `visual` placeholder (existing path).
- Assert that:
  - The PPTX writes successfully.
  - The named text box contains rendered content.
  - Existing image/visual behavior remains unchanged.

## 5. Validation

Run in the Praeparo repo root:

```bash
poetry run pytest tests/pack/test_pack_runner.py
poetry run pyright praeparo/models/pack.py praeparo/pack/pptx.py
poetry run python -m praeparo.schema --pack schemas/pack.json
```

## 6. Risks / Open Questions

- **Style preservation:** python‑pptx can lose formatting when setting
  `text_frame.text`. MVP should preserve the first run’s style but may still
  flatten complex templates.
- **Template naming:** Requires PPTX authors to maintain stable shape names.
- **Interplay with inline Jinja:** Both systems may be used simultaneously;
  render order is chosen to keep behavior predictable.

## 7. Next Steps

- Implement schema + injector.
- Land tests and schema regeneration.
- Update pack runner docs with authoring guidance.

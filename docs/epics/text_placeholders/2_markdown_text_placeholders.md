# Epic: Markdown Text Placeholders (Phase 2)

> Status: **Draft** – allow text placeholders to declare Markdown content and render it into PPTX text frames with basic formatting.

## 1. Problem

Phase 1 introduces plain text injection. That unlocks context‑nourished strings,
but many packs need richer layouts:

- Bulleted commentary blocks.
- Emphasis / callouts (bold, italic).
- Multi‑paragraph narratives.

PPTX templates can style these manually, but dynamic text becomes brittle again.
We want authors to write Markdown in YAML and have Praeparo render it into the
named text placeholder with predictable formatting.

## 2. Goals

Phase 2 SHOULD:

1. Extend placeholder schema with a Markdown binding.
2. Parse Markdown using a maintained, CommonMark‑compatible library.
3. Render a **supported subset** of Markdown into PPTX paragraphs/runs.
4. Preserve base style from the template placeholder.

Out of scope:

- Arbitrary HTML authoring.
- Full Markdown feature set (tables, code fences, images).
- Layout‑level CSS fidelity.

## 3. Library choice

Prefer an existing parser rather than a bespoke one. Candidate libraries:

- `markdown-it-py` – CommonMark compliant, stable token stream, active maintainer.
- `mistune` – fast, extensible, but less aligned with CommonMark defaults.

Recommendation: **markdown-it-py** for predictable CommonMark behavior and a
structured token stream that maps well to PPTX runs.

### 3.1 Prior art / decision record

We reviewed existing Markdown→PPTX projects to see whether we could reuse a
renderer for placeholder‑level injection:

- `md2pptx` (Python + `python-pptx`) is mature for full deck generation, but its
  parser/renderer is tightly coupled to slide construction and does not expose a
  clean “render into an existing text frame” API.
- `md-converter` and `markdown-docx` (Node + `pptxgenjs`) have strong AST‑driven
  rendering, but adopting them would introduce a second PPTX backend and runtime.
- `mdtopptx` (PyPI) is lightweight but supports only a shallow subset and is
  deck‑oriented.
- Pandoc‑based converters provide high Markdown fidelity, but require an
  external binary and cannot target a single placeholder inside a pre‑existing
  template.

Decision: implement a Praeparo‑native Markdown renderer using `markdown-it-py`,
mapping a documented subset into PPTX paragraphs and runs. The above projects
remain useful references for bullet layout and run segmentation, but are not
dependencies.

## 4. Proposed UX

```yaml
slides:
  - title: "Summary"
    template: "home"
    placeholders:
      summary_text:
        markdown: |
          **Highlights**
          - Settlements increased {{ increase_pct }}% MoM.
          - SLA attainment held at *{{ sla_pct }}%*.

          _Notes_: Missed settlements metric is placeholder until feed lands.
```

Rules:
- `markdown` is mutually exclusive with `text`, `image`, `visual`.
- `markdown` may be a string or list of strings (joined with `\n`).

## 5. Design

### 5.1 Schema changes

File: `praeparo/models/pack.py`

- Add `markdown: str | list[str] | None` to `PackPlaceholder`.
- Ensure only one binding is supplied.

### 5.2 Rich text AST

Introduce a small internal representation to decouple parsing from rendering:

```python
class RichTextSpan:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False

class RichTextParagraph:
    spans: list[RichTextSpan]
    bullet: bool = False
    bullet_level: int = 0

class RichTextDocument:
    paragraphs: list[RichTextParagraph]
```

### 5.3 Markdown parsing

File: new module `praeparo/pack/text_markdown.py`

- Use `markdown-it-py` to parse Markdown into tokens.
- Convert tokens into `RichTextDocument`.
- Supported subset for Phase 2:
  - Paragraphs.
  - Unordered/ordered lists (`-`, `*`, `1.`).
  - Bold/italic emphasis.
  - Soft/hard line breaks.
  - Inline code (monospace span).

Unsupported tokens should be downgraded to plain text with a warning.

### 5.4 Rendering to PPTX

File: `praeparo/pack/pptx.py`

- When placeholder has `markdown`, parse → document → render.
- Rendering rules:
  - Clear the text frame.
  - For each paragraph, add a PPTX paragraph.
  - Apply bullets and bullet levels when needed.
  - Create runs for each span; set bold/italic/code based on span flags.
- Preserve style:
  - Capture base font properties from the template’s first run (family, size,
    color, alignment). Apply to new runs unless Markdown requires bold/italic.

## 6. Tests

File: `tests/pack/test_pack_runner.py`

- Add fixtures for:
  - Markdown with bullets + emphasis.
  - Multi‑paragraph blocks.
  - Inline code.
- Validate:
  - The resulting PPTX contains expected text.
  - Bullets are present at the correct level.
  - Bold/italic flags are set on runs.

## 7. Validation

```bash
poetry run pytest tests/pack/test_pack_runner.py
poetry run pyright praeparo/pack/text_markdown.py praeparo/pack/pptx.py praeparo/models/pack.py
poetry run python -m praeparo.schema --pack schemas/pack.json
```

## 8. Risks / Open Questions

- **Markdown → PPTX fidelity:** Some Markdown constructs have no PPTX analogue.
  Keep subset explicit and documented.
- **Theme coupling:** Base style capture assumes a single styled seed run.
  Complex templates may need Phase 3 enhancements.

## 9. Next Steps

- Land parser module + AST.
- Integrate renderer into PPTX assembly.
- Extend docs with supported Markdown subset.

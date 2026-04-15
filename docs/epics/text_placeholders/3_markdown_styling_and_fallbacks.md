# Epic: Advanced Markdown Styling & Fallbacks (Phase 3)

> Status: **Draft** – enrich Markdown rendering, add style overrides, and provide a safe fallback for unsupported layouts.

## 1. Problem

Phase 2 covers a pragmatic Markdown subset. Real packs will likely need:

- Headings / hierarchy.
- Simple tables or definition lists.
- Block quotes / callout panels.
- Controlled spacing and emphasis for “executive summary” tiles.

Some of these map cleanly to PPTX; others do not. We need a roadmap for richer
Markdown without drifting into full HTML/CSS authoring.

## 2. Goals

Phase 3 SHOULD:

1. Expand the supported Markdown subset in a backwards‑compatible way.
2. Allow placeholder‑level style overrides in YAML.
3. Provide an optional **render‑as‑image** fallback for Markdown blocks that
   can’t be faithfully expressed in PPTX runs.

## 3. Proposed Enhancements

### 3.1 Markdown subset expansion

Add support for:
- Headings (`#`, `##`, `###`) → larger font + bold, mapped to levels.
- Blockquotes (`>`) → italic or tinted text depending on template style.
- Horizontal rules (`---`) → paragraph spacing cue (no visible line by default).

Keep tables out of scope unless a clear PPTX mapping is agreed.

### 3.2 Placeholder style overrides

Schema addition (optional):

```yaml
placeholders:
  summary_text:
    markdown: |
      # Highlights
      - ...
    style:
      font_size: 16
      color: "#0B3D91"
      line_spacing: 1.2
      bullet_indent_px: 14
```

Rules:
- Overrides apply on top of the template seed run.
- Only allow safe, declarative properties; ignore unknown keys with warnings.

### 3.3 Render-as-image fallback

For complex Markdown blocks:

```yaml
placeholders:
  complex_text:
    markdown: |
      ...
    render_as_image: true
```

Behavior:
- Parse Markdown → HTML using markdown-it-py.
- Render HTML to PNG using the existing Choreographer/Kaleido stack already
  required for Plotly PNGs.
- Inject PNG via existing picture replacement pipeline.

This keeps Markdown as the authoring surface while allowing richer layout
without introducing HTML authoring.

## 4. Tests / Validation

- Snapshot tests for headings/quotes.
- Integration test for render‑as‑image path guarded behind an env flag.
- Ensure fallback does not require network access beyond existing Kaleido needs.

## 5. Risks / Open Questions

- **Perf:** HTML→PNG rendering adds overhead; keep opt‑in and cacheable.
- **Template fit:** Image fallback must respect placeholder geometry.
- **Style drift:** Too many overrides can diverge from template system; keep narrow.

## 6. Next Steps

- Decide which Markdown constructs are priority for packs.
- Design `style` schema and safe property list.
- Prototype render‑as‑image flow on a single slide.


# Epic: Pack PPTX Matrix/Table Shapes (Phase 5)

> Status: **Draft** – enable YAML-authored tables that render via python-pptx so packs can lay down commentary blocks and tabular call-outs without editing templates.

## 1. Problem

Phases 1–4 let authors bind text, images, visuals, and rectangle-style cards to PPTX slides entirely from YAML. Packs still rely on PowerPoint masters for commentary tables. These tables mix narrative bullet points with structured rows/columns, require consistent header shading, and often need metric-driven values. Editing them in PPTX breaks reproducibility and requires manual layout tweaks. We need a declarative way to define tables/matrices that mirrors python-pptx and reuses pack context for data.

## 2. Goals

1. Extend slide YAML with a `tables:` collection that mirrors python-pptx’s table API (`rows`, `cols`, `cell.text_frame`).
2. Support hybrid layouts: commentary text stacked above/beside the table within the same block.
3. Leverage pack context + Jinja for cell content.
4. Provide styling knobs aligned to python-pptx objects (`table.style`, `cell.fill`, `cell.border`, `paragraph.font`).
5. Allow anchoring just like Phase 4 shapes (absolute or relative). Order should determine z-order.

Out of scope: fully dynamic row/column spanning logic beyond simple `rowspan`/`colspan`, automatic pagination, or Excel-like formulas.

## 3. Proposed UX

### 3.1 YAML example

```yaml
slides:
  - title: "Documents Commentary"
    template: "metrics"
    tables:
      - id: documents_commentary
        anchor:
          ref: slide
          left: 1.5cm
          top: 3cm
        width: 20cm
        style: "TableStyleMedium9"              # python-pptx built-in name
        header:
          background: "#4a78b8"
          font:
            color: "#ffffff"
            bold: true
        layout:
          columns:
            - width: 6cm
            - width: 6cm
            - width: 4cm
          rows:
            - cells:
                - kind: bullets
                  bullet_prefix: "•"
                  text:
                    - "In {{ month_long }}: **{{ pct_docs_sla }}%** of issued packs were signed within 3 days."
                    - "This is {{ pct_docs_delta }} higher than peer average."
                - merge: right     # spans second + third column for commentary
            - cells:
                - text: "Timeframe for Return"
                - text: "Documents Returned"
                - text: "% in Timeframe"
              role: header
            - cells:
                - text: "< 3 hours"
                - text: "{{ docs_lt_3h }}"
                - text: "{{ docs_lt_3h_pct | percent }}"
            - cells:
                - text: "< 1 day"
                - text: "{{ docs_lt_1d }}"
                - text: "{{ docs_lt_1d_pct | percent }}"
            - cells:
                - text: "TOTAL"
                - text: "{{ docs_total }}"
                - text: ""
              row_style:
                fill: "#d9d9d9"
```

Ergonomics:
- `layout.columns[].width` mirrors python-pptx `Column.width` (EMUs). Accepts unit strings.
- `rows[].role` lets us apply presets like `header`, `body`, `total`.
- Cells can specify:
  - `text` or `text_frame` (same structure as Phase 4) for simple content.
  - `kind: bullets` to auto-create bullet paragraphs from a list.
  - `merge: right` / `merge: down` for simple spanning (backed by python-pptx’s `cell.merge`).
- Table-level `style` maps to built-in names or custom table styles already embedded in the template.

### 3.2 Anchoring

`tables` share the same `anchor` model as Phase 4 shapes so authors can align tables beneath KPI cards or center them relative to another block. When omitted, `left/top` are required.

## 4. Design

### 4.1 Schema additions (`praeparo.models.pack`)

- Add `PackSlideTable` with fields:
  - `id`, `anchor | left/top`, `width`, optional `height` (auto-resize if omitted).
  - `style: str | None` (python-pptx table style name).
  - `layout: TableLayout` where `columns` is a list of widths and `rows` is a list of `RowConfig` entries.
  - `RowConfig` contains `role`, `cells`, `row_style`.
  - `CellConfig` supports `text`, `kind`, `text_frame`, `merge`, `cell_style` (fill, borders, font overrides).
- Validation ensures `columns` count matches cell counts (accounting for merges), merges stay within bounds, and IDs unique.
- Reuse the same unit parsing helpers from Phase 4 for widths/heights.

### 4.2 Rendering (`praeparo.pack.pptx`)

1. After shapes render, process `tables` in declaration order.
2. Create table via `slide.shapes.add_table(rows=len(rows), cols=len(columns), left, top, width, height)`.
3. Apply table style + column widths.
4. Iterate rows & cells:
   - Merge when `merge` specified using python-pptx `cell.merge`.
   - Populate text frames with Phase 1 text pipeline (Jinja + paragraph formatting).
   - Apply row/cell style tokens (fill, borders, font) by mapping to python-pptx properties.
5. Support bullet cells: set `paragraph.level`, `paragraph.font`, and `paragraph.text` sequentially.
6. Store final bounding box for potential downstream features (optional).

### 4.3 Testing

- Unit tests for schema validation (row/column counts, merge bounds, style parsing).
- Integration test building the commentary/table example, then reading the PPTX to assert:
  - Table exists with expected column widths and header fill colors.
  - Text content matches rendered values.
  - Merge operations produced the correct cell spans.

## 5. Validation

```bash
poetry run pytest tests/pack/test_pack_runner.py::test_yaml_tables
poetry run pyright praeparo/models/pack.py praeparo/pack/pptx.py
poetry run python -m praeparo.schema --pack schemas/pack.json
```

## 6. Risks / Open Questions

- **Merge complexity:** python-pptx merges are pairwise; we may need helper logic to support multi-column spans elegantly.
- **Auto-height calculation:** we may need to measure text height to size the table when `height` is omitted.
- **Performance:** Large tables might slow pack assembly; consider caching fonts/styles.
- **Style parity:** Built-in table styles vary by PPT theme. Document assumptions around template styles.

## 7. Next Steps

1. Socialize the schema with Praeparo maintainers (especially merge semantics).
2. Implement schema + renderer updates in the Praeparo submodule.
3. Add representative tests and regenerate schemas/docs.
4. Update `docs/projects/pack_runner.md` with table authoring guidance.
```

# Epic: Dataset-backed PPTX Tables (Phase 9)

> Status: **Draft** – extend pack tables so their rows/columns can be generated from a DAX dataset (field-selected “axes”), avoiding hardcoded month/date headers or legend/category lists in YAML.

## 1. Problem

Phase 5 (`5_pptx_matrix_shapes.md`) enables YAML-authored PPTX tables, but the author still has to hardcode:

- the number of rows/columns, and
- axis-like headers (dates/months/categories) in the YAML.

This becomes brittle for tables where the “axis” is dynamic:

- Month columns depend on the reporting month and trailing window.
- Week blocks depend on calendar alignment (e.g., “week containing month start”).
- Category columns/rows depend on data availability (and we generally want zero-fill rather than dropping categories).

We want an authoring model closer to Power BI:

- pick the **row field** and **column field** (the table axes),
- pick the **measures** (values),
- let Praeparo generate the grid deterministically at render time.

## 2. Goals

1. Support **dataset-backed tables** in packs (native PPTX table output, not screenshots).
2. Allow authors to select axes by field reference:
   - `rows.field` (e.g., `'dim_state'[StateName]`)
   - `columns.field` (e.g., `'dim_calendar'[month]`)
3. Bind one or more measures (metrics/expressions) as the value cells.
4. Handle ordering and formatting:
   - `rows.order_by`, `columns.order_by`
   - `rows.format`, `columns.format`, `values.format`
5. Support common table ergonomics without bespoke code per customer:
   - optional totals (row/column grand totals)
   - optional sparse vs zero-fill behavior for missing axis combinations
   - optional multi-level headers (where feasible)
6. Keep Phase 5 “static tables” as a valid fallback for purely narrative grids.

Out of scope for Phase 9:

- fully general pivot formulas,
- complex rowspan/colspan templates driven by arbitrary loops,
- “top-N lists” with dynamic text (covered by a separate top-N/bindings epic if needed).

## 3. Proposed UX

### 3.1 Pack slide YAML

Add a new table kind that declares a dataset and pivot:

```yaml
slides:
  - title: "Settlement Timeframes"
    tables:
      - id: settlement_timeframes
        anchor:
          ref: slide
          left: 1.2cm
          top: 3.0cm
        width: 24cm
        style: "TableStyleMedium9"

        dataset:
          grain:
            - "'dim_calendar'[month]"
            - "'dim_state'[StateName]"
          metrics:
            - key: avg_business_days_from_docs_returned_to_settlement
              alias: avg_days

        pivot:
          rows:
            field: "'dim_state'[StateName]"
            order: asc
          columns:
            field: "'dim_calendar'[month]"
            order: asc
            format: "MMM-yy"
          values:
            - field: avg_days
              format: "number:1"
          fill: zero
```

Notes:

- `dataset.grain` defines the dataset axes (like `SUMMARIZECOLUMNS` group-by fields).
- `dataset.metrics[]` is the value list; each entry is a metric key/variant or an expression alias.
- `pivot.*` declares how to map the dataset into a 2D grid.
- `fill: zero` means missing row/column combinations render as 0/blank deterministically rather than disappearing.

### 3.2 Styling integration

Phase 9 should reuse the Phase 5 table styling surface:

- table `style`
- header fill/font presets
- per-cell number formatting and alignment

## 4. Design

### 4.1 Schema additions (Praeparo)

Add to pack schema:

- `PackSlideDataset` (dataset builder config)
  - `grain: list[str]`
  - `calculate` / `define` / `datasource` (mirroring visual configs)
  - `metrics: list[MetricBindingLike]` (reuse existing metric reference models where possible)
- `PackSlidePivotTable`
  - `dataset: PackSlideDataset`
  - `pivot: PivotConfig`
    - `rows.field`, `columns.field`, `values[]`
    - ordering, formatting, fill behavior

### 4.2 Rendering pipeline (Praeparo pack)

1. Build the dataset via `MetricDatasetBuilder` (single execution per table).
2. Materialise a pivot grid:
   - enumerate unique row keys + column keys (respect ordering)
   - populate values per cell (with deterministic fill semantics)
3. Create a PPTX table sized to the pivoted shape.
4. Apply Phase 5 styling rules and write cell content.

### 4.3 Determinism and axis generation

To avoid “hardcoded axes” while staying deterministic:

- Row/column keys should default to the dataset’s distinct values.
- When `fill: zero`, the set of categories should be driven by:
  - the relevant dimension table (if present and safe), or
  - a declared `axis.domain` list (optional escape hatch), or
  - generated series (e.g., time-of-day buckets) via a standard helper.

This allows packs to avoid embedding “Jan-25, Dec-24…” lists in YAML.

## 5. Validation

- Schema validation tests for pivot config and field references.
- Integration test: build a pack slide that renders a pivot table, then assert:
  - correct row/column counts
  - correct header formatting
  - correct values and fill behavior

## 6. Consumers / motivating cases

- Monthly reporting decks with dynamic week/date headers and trailing-window columns.
- Operational tables where row/column headers depend on the selected reporting period.

## 7. Next steps

1. Align the schema UX with Praeparo maintainers (pivot semantics and fill rules).
2. Implement in Praeparo.
3. Add tests and update docs.
4. Update downstream pack docs/examples to consume this feature once available.

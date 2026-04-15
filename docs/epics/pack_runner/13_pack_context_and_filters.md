# Phase 13: Pack Context And Filters

> Status: **Implemented** – pack-level `context`, `define`, `calculate`, and `filters` now flow through Praeparo's pack runner and context-layer merge semantics.

Use this page as implementation history for the pack context/filter contract.
For the current supported behavior, start with [Projects / Pack Runner](../../projects/pack_runner.md)
and [Projects / Context Layers](../../projects/context_layers.md).

## 1. Purpose

This phase established the foundational pack contract for:

- shared pack `context` values exposed to Jinja,
- pack-level DAX `define` and `calculate` inputs,
- pack-level OData `filters` for Power BI visuals,
- and slide-level `visual.filters` / `visual.calculate` overrides.

The goal was to let one pack YAML describe shared report context once, then
reuse it across Power BI and DAX-backed slides without hardcoding customer-
specific logic into the runner.

## 2. Pack Contract

The foundational shape is a pack YAML with:

```yaml
schema: example-pack-draft-1

context:
  team_id: 201
  month: "2025-10-01"
  team_name: "Operations"

define: |
  DEFINE VAR TeamId = {{ team_id }}

calculate:
  team: "'dim_team'[TeamId] = {{ team_id }}"

filters:
  team: "dim_team/TeamId eq {{ team_id }}"
  dates: "{{ odata_months_back_range('dim_calendar/month', month, 3) }}"

slides:
  - title: "Overview"
    visual:
      ref: visuals/overview.yaml

  - title: "Self-Service Share"
    visual:
      ref: visuals/self_service_share.yaml
      filters:
        dates: "{{ odata_months_back_range('dim_calendar/month', month, 6) }}"
        channel: "dim_channel/ChannelName eq 'Self Service'"
```

This phase focused on the contract, not on customer-local slide layouts or
operator workflows.

## 3. Semantics

### 3.1 `context`

`context` is the shared source of templated values for the run.

- Keys are exposed to Jinja as top-level variables.
- The same values remain available under the nested compatibility mapping
  (`context.<name>`).
- Later context layers or CLI overrides may replace earlier values.

Typical examples include entity ids, month anchors, display labels, and other
pack-wide runtime inputs.

### 3.2 `calculate`

`calculate` is the pack-level DAX filter surface for DAX-backed visuals.

It may be expressed as:

- a single string,
- a list of strings,
- or a dict of named filters.

When the dict form is used, values are the effective DAX expressions and names
act as merge keys. Later named entries override earlier ones; unnamed list
entries append in order.

### 3.3 `filters`

`filters` is the pack-level OData filter surface for Power BI visuals.

It follows the same three shapes:

- a single string,
- a list of strings,
- or a dict of named filters.

These filters are the pack defaults. Slide-level `visual.filters` may extend
or override them.

### 3.4 Slide-level filter overrides

Slides can layer additional Power BI filters on top of the pack defaults:

```yaml
slides:
  - title: "Broker Share"
    visual:
      ref: visuals/share.yaml
      filters:
        channel: "dim_channel/ChannelName eq 'Broker'"
```

Merge semantics are:

- dict + dict -> local keys override pack keys,
- list + list -> concatenate,
- string -> coerce to a one-item list before merging.

The same layering pattern applies to DAX-backed visuals via slide-level
`calculate` and per-visual `visual.calculate`.

## 4. Execution Model

Praeparo now resolves this contract in a consistent flow:

1. Load workspace context layers, then the pack payload, then explicit
   invocation overrides.
2. Merge and hoist `context` values into the Jinja payload.
3. Render `define`, `calculate`, and `filters` with that payload.
4. Merge pack-level and slide-level DAX/OData inputs.
5. Forward:
   - merged OData filters to Power BI via `metadata["powerbi_filters"]`,
   - merged `calculate` filters and rendered `define` to DAX-backed visuals via
     the pack execution context.

This keeps the pack layer focused on orchestration while the existing visual
pipelines remain responsible for actual execution.

## 5. Relationship To Later Pack Phases

This phase defined the shared context/filter contract that later phases built
on:

- Phase 14 adds the generic pack -> PNG execution path.
- Phase 15 adds the bounded Power BI export queue.
- Phase 16 adds PPTX assembly and revision flows.

Later pack-runner phases also refined artifacts, revisions, and template
geometry without changing the core `context` / `define` / `calculate` /
`filters` model introduced here.

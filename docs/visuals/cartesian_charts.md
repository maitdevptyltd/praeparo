# Cartesian Charts

> **Status:** Implemented for shared column and bar chart visuals.

## What it is

Cartesian charts are Praeparo’s shared column and bar chart family. Use them
when the visual needs one category axis and one or more series that can appear
as columns, bars, or a mix of columns and lines.

The same model supports:

- ordinary column charts,
- bar charts,
- dual-axis overlays,
- stacked and percent-stacked series,
- inline metric expressions,
- mock data for previews and tests.

## Authoring flow

1. Define the category axis.
2. Define the value axes.
3. Add one or more series with stable identifiers.
4. Apply layout and mock settings only when the visual needs presentation or preview tuning.

That shape keeps the chart easy to read. The category axis tells Praeparo what
to group by, and each series tells it which metric or expression to draw.

## YAML contract

```yaml
type: column
title: Monthly activity
description: Compare actual activity with a target line.

category:
  field: dim_calendar.month
  label: Month
  data_type: string
  order: asc
  limit: 12

value_axes:
  primary:
    label: Activity
    format: 0,0
  secondary:
    label: Target
    format: 0,0

series:
  - id: actual
    label: Actual
    type: column
    axis: primary
    metric:
      key: orders.activity

  - id: target
    label: Target
    type: line
    axis: secondary
    metric:
      key: orders.target

layout:
  legend:
    position: top
```

## Key fields

- `category.field` identifies the semantic-model column used for grouping.
- `category.order` and `category.sort` control the order of the visible buckets.
- `value_axes.primary` is required; `value_axes.secondary` is optional when the
  chart needs an overlay or second scale.
- `series[].id` is the stable identifier used for bindings, stacking, and series
  operations.
- `series[].type` selects how the series renders. Column and line traces can be
  mixed in the same chart.
- `series[].axis` chooses whether the series uses the primary or secondary axis.
- `series[].stacking` groups related columns into a stack or percent-of-total
  view.
- `series[].metric.key` references the metric or virtual identifier consumed by
  the visual.
- `series[].metric.calculate` adds series-specific filters without duplicating
  the chart-level filters.
- `series[].metric.ratio_to` supports derived ratio series when the chart needs
  relative values instead of absolute ones.
- `layout.legend` controls presentation only; it should not change the data
  shape.

## Result shape

Praeparo resolves the category axis first, then evaluates each series against
that set. The rendered chart is built from:

- the category labels,
- the resolved value for each series,
- the chosen trace type,
- the configured axis assignment,
- optional stacking or transform rules.

That keeps the chart definition compact even when the output has several
traces. The author defines the inputs and lets Praeparo assemble the final
figure.

## Preview and mock data

Mock scenarios let the chart render cleanly before live data is ready. Keep
mock data close to the chart definition while the visual is still being
iterated:

```yaml
mock:
  scenarios:
    baseline:
      label: Baseline
      multiplier: 1.0
```

Use mock scenarios to make the category order, series mix, and legend or axis
layout visible before the semantic model is wired in.

## Practical guidance

- Prefer stable series ids over labels; labels are presentation text, ids are
  part of the visual contract.
- Use a line series for trend or target overlays when that improves readability.
- Keep `category.limit` conservative so the rendered figure stays legible.
- Use `stacking` when the business question is composition, not comparison.
- Keep expressions and filters in the series definition when only one series
  needs the override.

## When to choose cartesian charts

Use this visual family when the reader needs to compare values across a known
set of categories. It is a better fit than a table when the main question is
“how do the series compare across the axis?” and a better fit than a single KPI
when trend or comparison matters more than one aggregate.

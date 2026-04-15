# TMDL Generation

Use this guide when you want to turn a metric registry into generated Power BI
objects such as TMDL tables or measures.

Praeparo owns the metric loading, inheritance, expression compilation, and DAX
generation pieces. The consuming project still decides how compiled metrics are
named, grouped, and written into a semantic model.

## What Praeparo Owns

- loading and validating metric YAML
- resolving `extends`, `variants`, and `compose`
- compiling `define:` and `expression:` metrics into reusable DAX snippets
- preserving scoped `calculate:` filters and dependency order

Start with [Metric -> DAX Builder](metric_dax_builder.md) for the compilation
API itself.

## What The Consuming Project Owns

Praeparo does not prescribe a single generated-model layout. The consuming
project decides:

- which metric folders or domains map to generated tables
- how generated tables and measures are named
- whether generated objects are isolated from handcrafted ones
- how generated output coexists with an existing semantic model during rollout

One common pattern is to group metrics by domain and emit one generated table
per domain. Some projects isolate those generated tables with a naming
convention such as `**<domain>`, but that remains a project-level choice rather
than a Praeparo default.

## Registry Authoring Rules For TMDL-Friendly Metrics

- Keep metrics in the domain that owns the business concept. Do not fork metric
  definitions per customer just because different packs render them in
  different places.
- Keep customer filtering in pack filters, visual bindings, or context layers
  unless the business contract itself is customer-specific.
- Choose stable, business-readable `key` values so downstream generators do not
  need a second naming translation layer.
- Reuse existing semantic-model clocks, denominators, and established business
  measure names where possible when migrating from a handcrafted model.
- Record intentional drift in `notes` so the generated-model rollout has clear
  traceability.

## Choose `define`, `expression`, or `extends`

Use `define` when the metric owns a concrete base expression:

```yaml
key: documents_verified
define: |
  DISTINCTCOUNT ( 'fact_events'[MatterId] )
calculate:
  - dim_wf_component.WFComponentName = "Check Returned Documents"
```

Use `expression` when the metric is arithmetic over other metrics or variants:

```yaml
key: requisitions_open_older_than_10_network_days_pct
expression: |
  1 - ratio_to(requisitions_open_older_than_10_network_days, "requisitions_open")
format: percent:1
```

Use `extends` when the metric is a filtered or relabelled subset of an
existing business contract:

```yaml
key: discharge_payout_requested_within_1_day
extends: discharge_settlements_booked
```

Practical rule:

- `define` for the base measure
- `extends` for subset or overlay variants
- `expression` for composed scores, percentages, and arithmetic wrappers

## Variants, Domains, And Naming Collisions

- Prefer `variants:` when child measures clearly belong to one base metric and
  share the same business clock or denominator.
- Keep output naming collisions in mind before renaming a key or reorganising a
  domain. A generator can only emit clean semantic-model objects if the project
  naming scheme remains stable.
- If the consuming project emits one generated table per domain, keep that
  domain split stable enough that generated object placement does not thrash
  between releases.

## Alignment With Existing Semantic Models

When a project is migrating from a handcrafted semantic model:

- treat the existing model as the comparison point until generated parity is
  proven
- reuse existing table and column names in `define:` blocks instead of
  inventing parallel aliases
- compare date bases, denominator rules, and known caveats before treating the
  registry as complete
- retire handcrafted measures only after the generated output is validated
  against the current business contract

## Validation Checklist

1. Update the metric YAML in the project registry.
2. Compare the change against the relevant semantic-model implementation or
   other source of truth before treating the YAML as complete.
3. Run metric validation:
   - `poetry run praeparo-metrics validate <path/to/metrics>`
4. If the project has a TMDL writer or other generated-model test flow, run it
   and check for naming or placement collisions.
5. Update the project-level docs or exception notes when the business contract
   or migration strategy changes.

The goal is not just valid YAML. The goal is a metric definition that can move
cleanly from a registry into generated semantic-model objects without
reinterpreting the business contract later.

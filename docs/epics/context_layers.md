# Epic: Context Layers

> Status: **Implemented**

This page preserves the detailed phase record for layered context files and
repeatable `--context` semantics.

Current developer guidance lives in:

- [Projects / Context Layers](../projects/context_layers.md)
- [Projects / Pack Runner](../projects/pack_runner.md)

## Scope

`CTX-1` introduced a project-level context convention under `registry/context/**`
and made `--context` repeatable so shared values, helper `DEFINE` fragments,
and reusable `calculate` filters could be layered deterministically.

The broad contract landed upstream, while this epic record remained useful for
the original goals, merge semantics, guardrails, and business-time examples
that motivated the feature.

## Problem

Praeparo needed a small, reusable way to apply shared values, helper
definitions, and filter fragments across visual runs, explain flows, and pack
execution without copying the same payload into every file.

The missing pieces were:

- no automatic global layer that was always present
- effectively single-file `--context` input
- named override semantics for `calculate`, but append-only behavior for
  `define`

That made it hard to offer stable wrapper helpers such as
`GetCustomerBusinessDays(...)` and `GetCustomerBusinessHours(...)` that could
source working windows or holiday definitions from declarative configuration
instead of forcing every metric author to inline the same DAX.

## Goals

The original phase set out to preserve these design goals:

1. Add a workspace convention: `registry/context/**` as a default global
   context root.
2. Make CLI context layering first-class by allowing multiple `--context`
   flags.
3. Support pack-shaped context layers containing `context`, `calculate`,
   `define`, and optionally `filters`.
4. Introduce named `DEFINE` blocks so later layers can override specific
   helpers without concatenating duplicates.
5. Keep metric YAML authoring simple by letting metrics call stable wrapper
   names instead of repeating configuration plumbing.

## Non-goals

The epic explicitly did not try to:

- template or re-render the metric catalogue itself
- require new model tables or bridges for customer config
- rename or replace deployed semantic-model helper functions

## Terminology

- **Context layer**: a YAML or JSON document that can supply `context`,
  `calculate`, `define`, and optionally `filters`.
- **Registry context**: layers loaded automatically from `registry/context/**`.
- **Explicit context**: user-provided layers passed through repeatable
  `--context` flags.
- **Last writer wins**: later named entries override earlier ones, while
  unlabelled fragments append with de-duplication.

## Proposed Contract

### Default location and ordering

The epic proposed:

- a default root at `registry/context/`
- loading all `*.yaml`, `*.yml`, and `*.json` files under that root
- deterministic ordering by relative file path

This kept shared project defaults reviewable and allowed splitting the context
surface by concern instead of maintaining one oversized file.

### Merge precedence

The original merge order was:

1. registry context layers (`registry/context/**`, ordered)
2. CLI `--context` layers (in the order supplied)
3. CLI `--calculate` / `--define` flags as the highest-priority overrides

Within the merged payload:

- `context`: deep-merge mappings; later keys override earlier ones
- `calculate`: preserve named + unlabelled merge behavior
- `define`: adopt the same named + unlabelled contract as `calculate`
- `filters`: merge by key when represented as mappings

### Named `DEFINE` blocks

The phase introduced a concrete contract for `define`:

```yaml
define:
  get_business_days: |
    FUNCTION GetCustomerBusinessDays = (...) =>
      ...
  get_business_hours: |
    FUNCTION GetCustomerBusinessHours = (...) =>
      ...
```

Rules:

- mapping-form `define` entries are named blocks
- string or list forms remain unlabelled fragments
- named entries override by key
- unlabelled fragments append in order and de-duplicate exact duplicates
- output ordering remains stable so merged results stay reviewable

This avoided `DEFINE` bloat and made targeted overrides predictable.

## Business-Time Example

The main motivating example was a business-time wrapper layer.

### Default layer

The default layer under `registry/context/business_time.yaml` carried:

- `context.business_time` values such as `work_start`, `work_end`, and
  `weekend_code`
- reusable holiday helpers
- wrapper functions that called the deployed semantic-model functions
  `GetBusinessDays` and `GetBusinessHours`

The important design point was that wrapper names stayed stable for metric
authors, while downstream repos could override working windows or holiday logic
through context instead of changing metrics.

### Overrides

The phase also documented two override shapes:

- a later context layer that only overrides `context.business_time.*`
- a later layer that overrides the named `define` blocks responsible for
  holiday sourcing or wrapper behavior

That combination was the reason named `define` overrides mattered so much.

## CLI UX

The original CLI design wanted two explicit ergonomics:

- automatic loading of `registry/context/**` when available
- repeatable `--context` arguments, applied in order

It also proposed optional escape hatches:

- `--no-registry-context` to disable automatic loading
- `--registry-context-root <path>` to override the default location

One deliberate design choice was to Jinja-render the merged context payload
after layering, not before. That allowed later overrides to influence helper
definitions loaded earlier.

## Implementation Notes

The original implementation plan called for:

1. resolving the context root from `metrics_root` or `project_root`
2. loading context layers sequentially from `registry/context/**`
3. making `--context` append to a list instead of replacing prior values
4. extending the merge engine so `define` mirrors `calculate`
5. failing fast when templated DAX still contains unresolved `{{ ... }}`

The epic also called for tests around:

- registry context auto-load ordering
- repeatable `--context` precedence
- named `define` override behavior

## Recorded Phase Milestones

The original phase changelog captured three key steps:

- the first draft that proposed automatic `registry/context` loading,
  repeatable `--context`, and named `define` overrides
- the later split of business-time wrappers into individually named
  `define` keys so overrides could stay clean and targeted
- the final rendering adjustment that templated merged context fragments
  against the merged payload so later overrides flowed into shared helpers

## Risks And Rollback

The phase record explicitly called out:

- backwards-compatibility expectations for a single `--context`
- the risk of surprising default `DEFINE` content once registry context became
  automatic
- naming collisions across helpers without a clear prefixing convention

The escape hatch for rollback was straightforward: keep
`--no-registry-context` available so callers could disable global layers if a
workspace-level default behaved unexpectedly.

## Lasting Design Decisions

These parts of the original epic survived and still matter:

- context layers are a workspace contract, not a business-domain feature
- ordering must be deterministic, never filesystem-accidental
- later named layers override earlier ones
- Jinja rendering happens after merge so later values can feed earlier helper
  fragments

This epic page preserves that design history. For current behavior, use
[Projects / Context Layers](../projects/context_layers.md).

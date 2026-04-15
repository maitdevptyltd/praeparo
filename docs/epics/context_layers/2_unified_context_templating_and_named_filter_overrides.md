# Epic: Unified Context Templating And Named Filter Overrides (Phase 2)

> Status: **Implemented** – delivered in Praeparo, with unified Jinja templating for CLI context files and last-writer-wins behavior for named `calculate` / `filters` where supported.

- Canonical developer docs live in `docs/projects/context_layers.md`, `docs/projects/pack_runner.md`, and `docs/visuals/visual_context_model.md`.

## Problem

After Phase 1, the context-layer contract still had gaps across standalone
visual flows and pack-driven flows:

1. **CLI vs pack templating drift**
   - pack runs rendered `context`, `calculate`, and `filters` with Jinja
     before those fragments reached visual pipelines;
   - standalone `praeparo visual ... --context <file>` flows did not always
     treat context files as pack-shaped payloads or apply the same templating
     semantics.
2. **Named filters lost their labels too early**
   - mapping-form `calculate` and `filters` were useful for targeted
     overrides, but some code paths flattened them too early and lost the key
     that should control override behavior.
3. **No clear layer-by-layer override story**
   - users increasingly wanted to combine registry context layers, pack
     context, slide overrides, and explicit `--context` files while keeping
     the rule simple: later named entries override earlier ones; unlabelled
     fragments append.

The net effect was that standalone visual runs and pack runs did not fully
share the same mental model for context templating and named filter merges.

## Goal

Phase 2 refined the context-layer contract so both visual and pack flows shared
one coherent story:

1. Treat pack-shaped `--context` files as first-class layered context payloads.
2. Apply Jinja templating consistently after merge so later overrides can feed
   earlier helpers.
3. Keep named `calculate`, `define`, and `filters` entries intact until the
   final hand-off into DAX or OData.
4. Apply **last-writer-wins** semantics for named entries across layers while
   leaving unlabelled strings/lists as append-only ordered fragments.
5. Keep Praeparo responsible for context loading, templating, merging, and
   final typed-context population so downstream visuals consume the result
   without re-implementing the rules.

## Proposed Architecture

### 1. Context layers and resolution order

For a standalone visual (`praeparo visual ...`), the intended resolution model
was:

1. base context from `--context <file>`
2. additional explicit context layers in CLI order
3. CLI `--calculate` / `--define` fragments as highest-priority unlabelled
   overrides

For a pack-driven visual (`praeparo pack run`), the intended resolution model
was:

1. workspace context layers
2. pack-level `context`, `calculate`, and `filters`
3. slide-level overrides

Resolution rules:

- named filters (mapping form) override by key, with later layers winning;
- unlabelled filters (string/list form) append in order;
- flattening to DAX or OData lists happens only at the final hand-off stage.

### 2. DAX: named calculate and define handling

Phase 2 refined DAX context handling as follows:

- allow mapping inputs to survive through DAX context resolution for
  `calculate`;
- preserve mapping semantics during merge so last-writer-wins can apply by key
  across layers;
- flatten only at the end into the ordered tuple used by
  `DAXContextModel.calculate`;
- continue treating CLI `--calculate` / `--define` flags as unlabelled
  fragments appended at the highest-priority layer.

### 3. OData: reinforce named filter semantics

For OData filters, the intended contract remained:

- dict + dict merges use local-overrides-global behavior by key;
- mixed mapping/sequence forms fall back to effective list concatenation;
- named filter behavior is documented explicitly as part of the shared
  context-layer story rather than an implementation accident of the pack
  runner.

### 4. Typed models and boundaries

The public typed models remained unchanged:

- `VisualContextModel` carries generic execution context plus
  `dax: DAXContextModel`;
- `DAXContextModel` exposes `calculate: tuple[str, ...]` and
  `define: tuple[str, ...]`;
- `MetricDatasetBuilderContext` receives the final DAX filters and define
  blocks derived from that typed context.

Phase 2 did not add new public model fields. It refined the functions that
populate those models from raw layered context payloads and pack configs.

## Migration Plan

1. Extend context loaders so pack-shaped and plain context files both fit the
   layered model.
2. Apply Jinja templating consistently after merge across visual and pack
   flows.
3. Preserve mapping-style `calculate`, `define`, and `filters` values until
   the final DAX/OData hand-off.
4. Document the order of context layers and named-vs-unlabelled semantics in
   Praeparo’s active docs.

## Validation

Phase 2 is considered implemented when:

- pack-shaped CLI context files participate in the same templated merge model
  as pack runs;
- named `calculate` and `filters` entries override by key across later layers;
- unlabelled fragments still append in deterministic order;
- the active docs describe the context-layer order and named override
  semantics clearly enough for downstream repos to rely on the contract.

## Lasting Design Decisions

Phase 2 clarified and reinforced these rules:

- pack-shaped context files are valid inputs for standalone visual flows, not
  just `praeparo pack run`;
- named `calculate` and `filters` behave like named `define` helpers:
  later layers override earlier layers by key;
- unlabelled fragments still append in deterministic order because they have
  no stable key to override;
- typed visual context remains the public API, while the merge machinery stays
  behind Praeparo's loading and pipeline helpers.

# Phase 17: Pack Schema And Registry Wiring

> Status: **Draft** – design for a stable pack schema, validation, and `registry/packs/**` discovery.

Use this page as implementation history for the proposed pack-schema and
registry-wiring work. The current supported pack contract still lives in
[Projects / Pack Runner](../../projects/pack_runner.md).

## 1. Purpose

Earlier pack phases established a working `PackConfig` model and `praeparo pack
run` execution flow. This phase proposes the next step: make packs a
first-class authored surface with:

- a stable, versioned pack schema,
- JSON-schema-backed validation,
- and a dedicated `registry/packs/**` hierarchy for pack discovery and reuse.

The goal is to move from ad-hoc pack-shaped files toward a formal registry
surface that is easier to validate, discover, and share across projects.

## 2. Target Layout

The target workspace shape is:

```text
registry/
  packs/
    governance/
      operations_governance.yaml
      settlements_governance.yaml
  customers/
    customer_a/
      customer_a_governance.yaml
    customer_b/
      customer_b_governance.yaml
```

Under this model:

- `registry/packs/**` holds the canonical pack definitions,
- `registry/customers/**` can reference those packs and apply local overrides,
- and pack validation/discovery operates over the registry pack root instead of
  one-off paths.

## 3. Pack Schema Expectations

Praeparo already has a `PackConfig` model. This phase proposes promoting that
model to a stable authoring contract with JSON schema support.

Illustrative shape:

```yaml
schema: pack-v1

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
  - id: overview
    title: "Overview"
    visual:
      ref: "@/visuals/powerbi/overview.yaml"
  - id: self_service
    title: "Self-Service Share"
    visual:
      ref: "@/visuals/powerbi/self_service_share.yaml"
      filters:
        dates: "{{ odata_months_back_range('dim_calendar/month', month, 6) }}"
        channel: "dim_channel/ChannelName eq 'Self Service'"
```

Key expectations:

- `schema` is versioned and stable.
- `context`, `define`, `calculate`, `filters`, and `slides` follow the pack
  model already introduced in earlier phases.
- `visual.ref` supports both pack-relative and registry-anchored (`@/...`)
  paths.
- Inline visual configs remain valid where a full `visual` payload is supplied
  instead of a reference.
- metrics-root discovery continues to prefer the nearest `registry/metrics`
  unless the CLI overrides it explicitly.

## 4. `registry/packs/**` Wiring

This phase proposes `registry/packs/**` as the authoritative authored location
for pack definitions.

Expectations:

- each file under `registry/packs/**` is one `PackConfig` document,
- Praeparo can validate/discover packs by walking that tree,
- customer-local files can reference shared packs instead of duplicating all
  slide definitions.

Illustrative customer wrapper:

```yaml
schema: customer-pack-ref-v1

packs:
  - ref: ../../packs/governance/operations_governance.yaml
    context_override:
      display_date: "October 2025"
```

The exact reference shape is intentionally left open in this draft. The key
design point is that canonical packs live under `registry/packs/**`.

## 5. Validation And Tooling Expectations

This phase expects Praeparo to provide:

- a generated JSON schema for packs,
- a validator such as:

  ```bash
  poetry run praeparo pack validate ./registry/packs
  ```

- and basic structural checks such as:
  - malformed pack documents,
  - duplicate slide ids,
  - unresolvable `visual.ref` paths.

## 6. Relationship To Existing Pack Docs

This phase is still draft. It does not replace the current pack-runner docs or
the existing `PackConfig` behavior already implemented in Praeparo.

If this work proceeds, it should build on top of the current pack contract
rather than introducing a second incompatible pack shape.

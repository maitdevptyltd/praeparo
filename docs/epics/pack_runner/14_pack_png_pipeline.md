# Phase 14: Pack PNG Pipeline

> Status: **Implemented** – `praeparo pack run` resolves `visual.ref` entries, merges pack context/filter inputs, and exports per-slide PNG artifacts.

Use this page as implementation history for the foundational pack -> PNG flow.
For the current supported contract, start with [Projects / Pack Runner](../../projects/pack_runner.md).

## 1. Purpose

This phase introduced the generic pack execution path that:

- loads one pack YAML as the source of truth for slide ordering and shared
  context,
- resolves each slide's `visual.ref` through the normal visual registry,
- merges pack-level and slide-level context/filter inputs,
- and exports PNG artifacts for every slide that owns a visual.

This phase was intentionally PNG-only. PPTX composition and later artifact
conventions were handled in subsequent pack-runner phases.

## 2. Input Contract

The pack file provides:

- shared `context`,
- optional pack-level `define`,
- optional pack-level `calculate`,
- optional pack-level `filters`,
- and ordered `slides` with `visual.ref` plus optional slide overrides.

Example:

```yaml
schema: example-pack-draft-1

context:
  month: "2025-10-01"
  team_id: 201
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

## 3. Desired Behavior

The pack runner now:

1. Loads the pack.
2. Builds a Jinja payload from workspace context layers, pack context, and
   explicit invocation overrides.
3. Renders pack-level and slide-level `define` / `calculate` / `filters`.
4. Resolves each `visual.ref` to a typed visual config.
5. Dispatches execution through the existing visual registry instead of
   hardcoding per-type behavior.
6. Writes a PNG and slide-scoped artifact directory for each visualized slide.

The pack layer remains orchestration only. Existing Power BI, matrix, and
Python-backed visual pipelines still own execution.

## 4. Filter And Dispatch Semantics

### 4.1 Power BI visuals

For `type: powerbi` visuals:

- pack-level and slide-level OData filters are merged,
- rendered values are passed via `metadata["powerbi_filters"]`,
- and the Power BI pipeline combines them with any visual-local filters using
  its normal merge logic.

### 4.2 DAX-backed visuals

For matrix, cartesian, and Python-backed visuals that consume DAX context:

- pack-level `calculate`,
- slide-level `calculate`,
- per-visual `visual.calculate`,
- and the rendered `define` block

are forwarded through the pack execution context so the visual runs with the
same resolved filter story as if it had been invoked directly.

### 4.3 Visual resolution

The pack runner resolves `visual.ref` through Praeparo's existing config
loader and visual registry. That keeps pack execution aligned with standalone
`praeparo visual ...` flows instead of maintaining a separate dispatch system.

## 5. CLI Shape

The foundational CLI is:

```bash
poetry run praeparo pack run projects/example/pack.yaml --artefact-dir out/example/pack_png
```

This phase established the generic `pack run` surface. Later phases refined:

- artifact naming,
- Power BI queueing,
- PPTX output,
- revisions,
- and template geometry.

## 6. Artifact Notes

This phase established the one-slide-per-artifact execution model and the
separate slide artifact directories used by later phases.

Later pack-runner work finalized the ordinal-prefixed naming contract. Use
[Phase 9: Pack Artifact Naming Convention](9_pack_artifact_naming_convention.md)
and the active pack-runner docs for the authoritative current layout.

# Context Layers

Praeparo context layers are small YAML or JSON files that add shared settings
before visual- or pack-specific overrides are applied. They are useful when
multiple visuals or packs need the same helper definitions, filters, or values
without copying them into every file.

In the default Praeparo workspace, shared context files live under
`registry/context/**` next to `registry/metrics`, `registry/datasources`, and
the other authored registry folders. That location is part of Praeparo's
normal workspace layout. Explicit `--context` files still work for portable
examples, ad-hoc runs, or alternative layouts.

Use context layers when you want to:

  - share reusable defaults across a project,
  - keep invocation-specific overrides separate from authored files,
  - and let later layers fill in values used by shared helper fragments.

## Resolution Semantics

Praeparo resolves layered context in a predictable order:

### Visual and explain flows

1. Workspace context layers auto-discovered under `registry/context/**`
   relative to the default `metrics_root`.
2. Explicit `--context` files, applied in CLI order.
3. CLI `--calculate` / `--define` overrides, which always win last.

### Pack-run flows

1. Workspace context layers auto-discovered under `registry/context/**`.
2. Pack-level `context` defaults from the pack payload.
3. Explicit `--context` overrides supplied for the invocation.

All workspace context files are loaded recursively and sorted by their relative
path in deterministic lexicographic order before merging starts.

After the layers are merged, Praeparo renders `calculate`, `define`, and
`filters` with Jinja. That lets a later layer set values that shared helper
fragments defined earlier can use.

## Supported File Shapes

Praeparo accepts two kinds of context-layer input:

- **Plain layer payloads**: YAML or JSON documents that carry mergeable context
  fragments directly at the top level.
- **Pack-shaped payloads**: full pack files that include `schema` and
  `slides`. Praeparo extracts the top-level `context`, `calculate`, `define`,
  and `filters` fragments and treats them as a context layer.

Both shapes may include nested `context` mappings. Those mappings are deep-
merged so a later layer can update one field without replacing the whole
branch.

Named `calculate` and `define` entries use last-writer-wins semantics when the
same key appears in more than one layer. Sequence forms are preserved in merge
order.

## Neutral Example

`registry/context/00_shared.yaml`

```yaml
context:
  project: <project>
  team: <team>
  entity: <entity>

define:
  shared_label: "{{ project }} / {{ team }}"

filters:
  entity: "dim_entity/EntityName eq '{{ entity }}'"
```

`registry/context/20_override.yaml`

```yaml
context:
  artefact_dir: <artefact-dir>
```

If a visual run also passes `--context local.yaml`, Praeparo merges the
workspace layers first, then `local.yaml`, then any CLI `--calculate` or
`--define` values. The final templated result can reuse `{{ shared_label }}` and
`{{ artefact_dir }}` in later fragments.

## Schema Support

Generate the generic context-layer schema with:

```bash
poetry run python -m praeparo.schema --context-layer schemas/context_layer.json
```

Use this schema in editors or downstream tools when you want completion for
standalone context files.

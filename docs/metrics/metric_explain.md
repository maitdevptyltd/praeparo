# Metric Explain (Evidence Exports)

`praeparo-metrics explain` exports row-level evidence for a metric or binding instance, using the same layered context as pack runs (`registry` context layers, plus `--context` and `--calculate`).

Use it when the headline KPI or SLA value is not enough and you need the rows, timestamps, deltas, and pass/fail flags behind it in a reproducible extract.

## YAML schema: `explain:`

Metrics (and variants) may define an `explain:` block:

```yaml
explain:
  from: fact_activity                   # optional; defaults to fact_events
  where:                                # optional; appended after compiled calculate filters
    - dim_region[RegionId] = 201
  grain: fact_activity[ActivityKey]     # optional; overrides the default explain grain
  define:                               # optional; explain-only DEFINE helpers (context-style shapes)
    __latest_activity_key: |
      MEASURE 'adhoc'[__latest_activity_key] = MAX(fact_activity[ActivityKey])
  select:                               # optional; label -> DAX expression
    activity_timestamp_utc: fact_activity[ActivityTimestampUTC]
    elapsed_business_days: GetBusinessDaysBetween(
      fact_activity[StartTimestampUTC],
      fact_activity[EndTimestampUTC]
    )
```

Notes:

- `select` and mapping-form `grain` keys must be `snake_case`.
- Labels starting with `__` are reserved for framework fields (`__metric_key`, `__metric_value`, …).
- The explain CLI exports `__grain_table` and `__grain_key` (constant strings) and grain columns such as `__grain` so evidence consumers can see where each row identity comes from.
- `explain.define` supports `__`-prefixed helper names and applies only to explain queries. It does not change the compiled metric measures.

### Inheritance and merging

Explain config follows the same merge pattern as other metric surfaces:

- `extends` chain merges first (root → leaf).
- Variant paths patch after that (parent variant → leaf variant).

Merge rules:

- `from`: last-writer-wins
- `grain` (mapping form): merge by key, last-writer-wins
- `select`: merge by key, last-writer-wins
- `where`: append-only
- `define`: context-like merge (named entries last-writer-wins, unlabelled entries de-duped)

## CLI: `praeparo-metrics explain`

### Selector forms (metrics, visuals, packs)

`praeparo-metrics explain` accepts a single positional `selector` that can target:

- A catalogue metric key (including dotted variants)
- A specific binding inside a visual YAML (`<visual_path>#<binding_id>`)
- A specific binding inside a pack slide (`<pack_path>#<slide>#<binding_id>`)
- A placeholder binding inside a pack slide (`<pack_path>#<slide>#<placeholder_id>#<binding_id>`)

All numeric selectors are **0-based** (for example, `#0` selects the first slide).

Selector identity is binding-oriented:

- The raw metric key identifies the catalogue metric.
- The binding id identifies one concrete instance of that metric in a visual or pack.
- Evidence exports and binding discovery work on binding ids because the same metric key can appear in multiple slides, placeholders, or visuals with different aliases, filters, or presentation metadata.

Basic metric usage:

```bash
poetry run praeparo-metrics explain requests_processed
poetry run praeparo-metrics explain requests_processed.within_1_day
```

Visual binding usage:

```bash
poetry run praeparo-metrics explain projects/example/visual.yaml#series_id
```

Pack discovery + binding usage:

```bash
# List slides in YAML order (0-based index + optional id).
poetry run praeparo-metrics explain projects/example/pack.yaml --list-slides

# List metric bindings for a slide (slide selector: id or 0-based index).
poetry run praeparo-metrics explain projects/example/pack.yaml#0 --list-bindings
poetry run praeparo-metrics explain projects/example/pack.yaml#home --list-bindings

# Explain a binding on a single-visual slide.
poetry run praeparo-metrics explain projects/example/pack.yaml#0#series_id

# Placeholder slides require an explicit placeholder id (or 0-based placeholder index).
poetry run praeparo-metrics explain projects/example/pack.yaml#2#chart#series_id
```

Discovery is the easiest way to avoid guessing identifiers:

1. Run `--list-slides` on the pack to see slide ids and 0-based positions.
2. Run `--list-bindings` on the target slide to see the exact binding ids Praeparo resolved.
3. Feed the selected binding id back into `praeparo-metrics explain` for the binding you want to inspect.

This output is especially useful for placeholder-based slides, where the same visual may expose multiple bindings under different placeholder ids.

Generate the query without executing it:

```bash
poetry run praeparo-metrics explain requests_processed.within_1_day --plan-only
```

### Plugins (`--plugin`)

Some visual types and binding adapters are registered by downstream repos. Use `--plugin` to import them before loading visuals/packs:

```bash
poetry run praeparo-metrics explain \
  --plugin custom_visuals_plugin \
  projects/example/custom/visual.yaml --list-bindings
```

`--plugin` is repeatable and may appear anywhere in the command line.

### Context (month/date windows come from context)

The explain CLI does not accept a standalone `--month`. Date windows should be supplied via the layered context payload:

```bash
poetry run praeparo-metrics explain requests_processed.within_1_day \
  --metrics-root <metrics_root> \
  --context projects/example/context/month.yaml \
  --context projects/example/pack.yaml
```

### Output locations (`dest`)

`dest` is optional:

- No `dest`: writes to a generated output directory such as `build/explain/<metric_slug>/…`
- `dest` is a file (`.csv`): writes evidence to that file and artifacts under `<parent>/<stem>/_artifacts`
- `dest` is a directory: writes evidence to `<dest>/evidence.csv` and artifacts under `<dest>/_artifacts`

Example:

```bash
poetry run praeparo-metrics explain requests_processed.within_1_day out/evidence.csv
```

Pack-qualified explain runs and pack evidence exports share the same selector model. When the same metric is bound more than once in a pack, each binding can produce its own evidence output instead of collapsing everything down to the raw metric key.

See [Pack Runner](../projects/pack_runner.md) for how those binding instances are selected and written during pack execution.

### Variant handling (`--variant-mode`)

By default, explaining a variant keeps the base population rowset and emits a `__passes_variant` flag when possible:

```bash
poetry run praeparo-metrics explain requests_processed.within_1_day --variant-mode flag
```

To export only passing rows:

```bash
poetry run praeparo-metrics explain requests_processed.within_1_day --variant-mode filter
```

`__passes_variant` is best-effort. For common cross-table variant filters, Praeparo falls back to a row-level contribution check so the flag tracks whether each row contributes to the variant numerator. When filters still cannot be converted safely, Praeparo omits the column and emits a warning; authors can supply an explicit boolean column via `explain.select` when needed.

### Execution (`--data-mode`)

```bash
poetry run praeparo-metrics explain requests_processed --data-mode mock
poetry run praeparo-metrics explain requests_processed --data-mode live --dataset-id <id> --workspace-id <id>
```

For live runs, provide either:

- `--dataset-id` (and optionally `--workspace-id`), or
- `--datasource <name-or-yaml>` (searched under `datasources/` or `registry/datasources/`, matching other Praeparo CLIs).

## DAX shape (row-based, no measure-per-row)

The evidence query is row-based and keeps the headline value constant:

- `VAR __metric_value = <compiled measure evaluated once in context>`
- `VAR __rows_raw = CALCULATETABLE(<driving table>, <filters...>)`
- `RETURN SELECTCOLUMNS(__rows, "__metric_value", __metric_value, ...)`

This avoids grouping by high-cardinality keys and re-evaluating the measure for every row.

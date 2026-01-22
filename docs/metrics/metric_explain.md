# Metric Explain (Evidence Exports)

`praeparo-metrics explain` exports row-level “show your working” evidence for a metric, using the same layered context semantics as pack runs (registry context layers + `--context` + `--calculate`).

This is designed for analyst workflows where the headline KPI/SLA value is not enough — you need the underlying EventKeys, timestamps, deltas, and pass/fail flags in a reproducible extract.

## YAML schema: `explain:`

Metrics (and variants) may define an `explain:` block:

```yaml
explain:
  from: fact_events                     # optional; defaults to fact_events
  where:                                # optional; appended after compiled calculate filters
    - dim_customer[CustomerId] = 201
  grain: fact_events[EventKey]          # optional; defaults to fact_events[EventKey]
  define:                               # optional; explain-only DEFINE helpers (context-style shapes)
    __latest_event_key: |
      MEASURE 'adhoc'[__latest_event_key] = MAX(fact_events[EventKey])
  select:                               # optional; label -> DAX expression
    event_timestamp_utc: fact_events[EventTimestampUTC]
    business_days_to_send: GetCustomerBusinessDays(
      fact_events[StartTimestampUTC],
      fact_events[EndTimestampUTC]
    )
```

Notes:

- `select` and mapping-form `grain` keys must be `snake_case`.
- Labels starting with `__` are reserved for framework fields (`__metric_key`, `__metric_value`, …).
- `explain.define` supports `__`-prefixed helper names and is scoped to explain queries only (it does not affect compiled metric measures).

### Inheritance and merging

Explain config follows the same “patching” pattern as other metric surfaces:

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
- A specific metric binding inside a visual YAML (`<visual_path>#...`)
- A specific metric binding inside a pack slide (`<pack_path>#<slide>#...`)

All numeric selectors are **0-based** (for example, `#0` selects the first slide).

Basic metric usage:

```bash
poetry run praeparo-metrics explain documents_verified
poetry run praeparo-metrics explain documents_verified.within_1_day
```

Visual binding usage:

```bash
poetry run praeparo-metrics explain registry/visuals/example.yaml#series_id
```

Pack discovery + binding usage:

```bash
# List slides in YAML order (0-based index + optional id).
poetry run praeparo-metrics explain registry/customers/<customer>/<pack>.yaml --list-slides

# List metric bindings for a slide (slide selector: id or 0-based index).
poetry run praeparo-metrics explain registry/customers/<customer>/<pack>.yaml#0 --list-bindings
poetry run praeparo-metrics explain registry/customers/<customer>/<pack>.yaml#home --list-bindings

# Explain a binding on a single-visual slide.
poetry run praeparo-metrics explain registry/customers/<customer>/<pack>.yaml#0#series_id

# Placeholder slides require an explicit placeholder id (or 0-based placeholder index).
poetry run praeparo-metrics explain registry/customers/<customer>/<pack>.yaml#2#chart#series_id
```

Generate the query without executing it:

```bash
poetry run praeparo-metrics explain documents_verified.within_1_day --plan-only
```

### Plugins (`--plugin`)

Some visual types and binding adapters are registered by downstream repos. Use `--plugin` to import them before loading visuals/packs:

```bash
poetry run praeparo-metrics explain \
  --plugin msanational_metrics \
  registry/customers/amp/visuals/performance_dashboard.yaml --list-bindings
```

`--plugin` is repeatable and may appear anywhere in the command line.

### Context (month/date windows come from context)

The explain CLI does not accept a standalone `--month`. Date windows should be supplied via the layered context payload:

```bash
poetry run praeparo-metrics explain documents_verified.within_1_day \
  --metrics-root registry/metrics \
  --context registry/context/month.yaml \
  --context registry/customers/<customer>/<pack>.yaml
```

### Output ergonomics (pack-like `dest`)

`dest` is optional:

- No `dest`: writes to `.tmp/explain/<metric_slug>/…`
- `dest` is a file (`.csv`): writes evidence to that file and artifacts under `<parent>/<stem>/_artifacts`
- `dest` is a directory: writes evidence to `<dest>/evidence.csv` and artifacts under `<dest>/_artifacts`

Example:

```bash
poetry run praeparo-metrics explain documents_verified.within_1_day out/evidence.csv
```

### Variant handling (`--variant-mode`)

By default, explaining a variant keeps the base population rowset and emits a `__passes_variant` flag when possible:

```bash
poetry run praeparo-metrics explain documents_verified.within_1_day --variant-mode flag
```

To export only passing rows:

```bash
poetry run praeparo-metrics explain documents_verified.within_1_day --variant-mode filter
```

`__passes_variant` is best-effort. When variant filters cannot be converted into a per-row boolean predicate without regressing performance, Praeparo omits the column and emits a warning; authors can supply an explicit boolean column via `explain.select` when required.

### Execution (`--data-mode`)

```bash
poetry run praeparo-metrics explain documents_verified --data-mode mock
poetry run praeparo-metrics explain documents_verified --data-mode live --dataset-id <id> --workspace-id <id>
```

For live runs, provide either:

- `--dataset-id` (and optionally `--workspace-id`), or
- `--datasource <name-or-yaml>` (searched under `datasources/`, matching other Praeparo CLIs).

## DAX shape (row-based, no measure-per-row)

The evidence query is row-based and keeps the headline value constant:

- `VAR __metric_value = <compiled measure evaluated once in context>`
- `VAR __rows_raw = CALCULATETABLE(<driving table>, <filters...>)`
- `RETURN SELECTCOLUMNS(__rows, "__metric_value", __metric_value, ...)`

This avoids the slow pattern of grouping by high-cardinality keys and re-evaluating the measure per row.

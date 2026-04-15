# Epic: Friendly Field References for DAX Columns (Phase 1)

> Status: **Draft** – partial field-reference support already exists in Praeparo, but the contract is still fragmented across templating, lookup heuristics, and individual visual surfaces rather than flowing through one central normalisation pipeline.

## 0. Current State

Praeparo already ships some field-reference ergonomics today:

- `praeparo.templating.FieldReference` parses `table.column` placeholders for
  matrix row templates.
- `praeparo.datasets.models.lookup_column(...)` already tries several payload
  key variants, including dotted `table.column` inputs.
- cartesian chart docs and examples already show `category.field:
  dim_calendar.month`.

However, that support is still incomplete:

- the support is not expressed as one documented, first-class developer
  contract;
- the behaviour is spread across multiple helpers with different assumptions;
- DAX planning and dataset builders still mostly treat grain columns as raw
  strings rather than a shared field-reference type.

## 1. Problem

Today, Praeparo expects **DAX column syntax** in most places that refer to
table/column fields:

- visual column fields use strings like `"'dim_calendar'[month]"`;
- metric dataset builders use `grain("'dim_calendar'[month])` and pass those
  strings straight into `SUMMARIZECOLUMNS`;
- dataset normalisation keys rows by the exact grain column strings in the
  plan.

While this is technically correct, it is ergonomically unfriendly:

- developers have to remember and type full DAX references
  (`'table'[Column]`) in YAML and CLI args;
- the same logical field often appears in multiple places with slightly
  different formatting:
  - DAX: `"'dim_calendar'[month]"`;
  - Power BI payload: `dim_calendar[month]` and `month`;
  - YAML: sometimes `"'dim_calendar'[Month]"`, sometimes a bare `month`;
- it is easy to introduce **mismatches** between:
  - the DAX grain reference in visuals / builders;
  - the field names expected in JSON payloads;
  - the keys used in mapping code.

Historically we attempted to “patch” this at multiple layers:

- `lookup_column(raw, column)` in Praeparo’s dataset layer grew its own
  heuristics to resolve variants like:
  - `"'dim_calendar'[month]"`, `dim_calendar[month]`, and `month`;
  - `dim_calendar.month` to synthetic candidates such as `month` and
    `"'dim_calendar'[month]"`;
- dataset builders and downstream adapters sometimes added their own string
  handling:
  - checking for `[` / `]` to decide whether something was “already DAX”;
  - manually constructing keys for `mock_column` and row normalisation.

That approach has proven fragile:

- DAX generation still uses the *raw* string unless every caller normalises it
  first;
- YAML fields like `columns.field` must still be written in valid DAX if the
  downstream mapping code cannot interpret shorthand;
- mapping logic diverged from the dataset layer’s heuristics, so changing a
  field from `"'dim_calendar'[month]"` to `dim_calendar.month` could:
  - produce correct DAX,
  - but fail to map the live payload back into downstream JSON because each
    “normaliser” made different assumptions.

In practice this created confusion and brittle configs:

- developers reasonably want to write `dim_calendar.month` or `month` in YAML;
- the engine wants `'dim_calendar'[month]` for DAX and a stable key for JSON;
- there was no **single, developer-friendly way** to say “this field” at the
  edge; they had to reason about:
  - DAX syntax,
  - Power BI payload conventions,
  - and the quirks of whatever helper a given code path happened to use.

## 2. Goal

Phase 1 should make **field references ergonomic and consistent** across
Praeparo and downstream consumers:

1. Allow developers to write field references in **object-like notation** where
   it is natural:
   - `dim_calendar.month`
   - `dim_calendar[month]`
   - `month`
2. Centralise field reference parsing and normalisation so Praeparo can:
   - use **one** shared pipeline to interpret field references, regardless of
     where they appear:
     - `SUMMARIZECOLUMNS` grain columns;
     - DAX `CALCULATE` filters when fields appear there;
     - matrix row templates and value fields;
   - produce valid DAX references automatically for any ergonomic input;
   - resolve data from JSON payloads regardless of variant
     (`dim_calendar[month]`, `month`, etc.), using the same rules everywhere.
3. Remove the need for developers to juggle multiple syntaxes for the same
   field:
   - YAML and CLI should accept the ergonomic form; Praeparo converts as
     needed;
   - downstream adapters must **not** re-interpret those strings; they should
     treat the normalised representation as canonical.
4. Preserve backwards compatibility:
   - continue to accept full DAX syntax (`'table'[Column]`) verbatim;
   - continue to support existing YAML/CLI configs where possible.

The end state:

- **one mental model** for “field references” at the edge;
- **one central implementation** of field normalisation in Praeparo;
- no duplicate or conflicting heuristics in downstream adapters.

## 3. Proposed Architecture

### 3.1 FieldReference model and parsing

Introduce a small, reusable abstraction in Praeparo, e.g. `FieldReference`:

- location: `praeparo/visuals/fields.py` or similar;
- responsibilities:
  - parse input strings such as:
    - `'dim_calendar'[month]`
    - `dim_calendar[month]`
    - `dim_calendar.month`
    - `[month]`
    - `month`
  - normalise into a canonical representation:
    - `table: str | None` (e.g. `"dim_calendar"`)
    - `column: str` (e.g. `"month"`)
  - emit:
    - `to_dax()` -> `"'dim_calendar'[month]"` or `[month]` when table is not
      known/needed;
    - `candidate_keys()` -> ordered list of possible JSON keys:
      - `"'dim_calendar'[month]"`, `dim_calendar[month]`, `month`, etc.

Parsing guidelines:

- accept only well-structured inputs; error clearly on ambiguous cases;
- prefer explicit table + column when possible; treat bare `month` as
  `table=None, column="month"`;
- preserve case where it matters, but treat mapping to underlying model as
  case-insensitive when resolving payload keys;
- treat parsing as the **single gate** between ergonomic strings and internal
  representations:
  - no other module should guess at `[` / `]` or `.`; they should defer to
    `parse_field_reference` / `FieldReference`.

### 3.2 DAX integration

Adapt DAX generation to use `FieldReference` wherever grain columns or
field-level filters are emitted:

- in `MetricDatasetBuilder` and other planners using `VisualPlan.grain_columns`:
  - treat `FieldReference` as the **canonical type** for grain columns inside
    Praeparo;
  - when rendering DAX (`render_visual_plan`):
    - if an entry is a `FieldReference`, call `to_dax()` to get the correct
      `'<table>'[Column]` form;
    - continue to accept raw strings only as a legacy escape hatch.

For filters:

- when planners or builders accept grain/field references in configuration or
  CLI:
  - parse them into `FieldReference` as early as possible;
  - store `FieldReference` in internal plans and use `to_dax()` when
    inserting into `CALCULATE` / `KEEPFILTERS` expressions.

### 3.3 Dataset mapping and lookup

Standardise how JSON payloads are mapped back to fields:

- extend `lookup_column` to accept either:
  - a `FieldReference`, or
  - a string that is immediately parsed into one, then resolved;
- implementation:
  - use `FieldReference.candidate_keys()` to generate a small set of candidate
    keys:
    - for `dim_calendar.month` -> `"'dim_calendar'[month]"`,
      `dim_calendar[month]`, `month`, etc.;
  - search these candidates in the JSON payload (`raw_rows`) or normalised
    rows;
  - keep current behaviour for existing string-based call sites.

For downstream consumers:

- when normalising rows in dataset builders:
  - call `lookup_column` with a `FieldReference` built from the configured
    field value;
- when mapping `MetricDatasetResult.rows` into downstream JSON:
  - use the same `FieldReference` when resolving grain values, rather than a
    raw string key.

### 3.4 YAML and CLI surfaces

Define where ergonomic field references are allowed and how they are
interpreted:

- **YAML models**:
  - fields that represent a DAX column should document that they accept:
    - full DAX syntax (`'dim_calendar'[month]`);
    - shorthand syntax (`dim_calendar.month`, `dim_calendar[month]`,
      `month`);
  - add pydantic validators that:
    - parse the provided string into a `FieldReference`;
    - store either:
      - the canonical DAX string (`to_dax()`) as the model field value, or
      - a structured `FieldReference` instance if the model wants richer
        behaviour.
- **CLI arguments**:
  - flags like `--grain` should accept ergonomic forms:
    - `--grain dim_calendar.month`;
  - CLI should:
    - parse each argument into a `FieldReference`;
    - store the canonical `to_dax()` string into metadata or visual context.

### 3.5 Backwards compatibility and migration

Phase 1 should keep existing configs running while unlocking ergonomic
notation:

- accept existing full DAX references unchanged;
- where models or CLI now parse into `FieldReference`, detect when the input
  string already looks like canonical DAX and avoid rewriting it
  unnecessarily;
- provide clear error messages for:
  - malformed shorthand (`dim_calendar.month.extra`);
  - ambiguous references when table context is required but missing.

For downstream repos:

- existing visuals can remain on full DAX syntax in the short term;
- new visuals and docs should preferentially use ergonomic notation
  (`dim_calendar.month`) once the field-normalisation pipeline is implemented
  upstream.

## 4. Work in Praeparo

1. **Introduce FieldReference and parsing utilities**
   - add `FieldReference` and parsing helpers under `praeparo.visuals.fields`
     (or similar);
   - implement `parse_field_reference(str) -> FieldReference`;
   - implement `FieldReference.to_dax()` and `FieldReference.candidate_keys()`.

2. **Wire FieldReference into datasets and planners**
   - update `MetricDatasetBuilder` and other DAX planners to:
     - consume `FieldReference` where appropriate for `grain_columns`;
     - use `to_dax()` when emitting DAX;
   - extend `lookup_column` to accept `FieldReference` and use
     `candidate_keys()` for payload lookup.

3. **Update YAML models and CLI in Praeparo**
   - identify fields in Praeparo models that represent DAX columns (grain,
     category, sort fields);
   - add validators to normalise ergonomic input
     (`dim_calendar.month`) into canonical DAX strings for storage;
   - update `--grain` and any similar CLI flags to run through the same
     normaliser.

4. **Documentation and examples**
   - add a dedicated section in Praeparo docs describing:
     - supported field reference syntaxes;
     - how they map to DAX and payload keys;
   - update existing examples to use ergonomic notation where appropriate.

## 5. Work in Downstream Repos

Once Phase 1 is implemented in Praeparo:

1. **Update YAML**
   - adopt ergonomic field notation only after Praeparo’s central field
     normalisation is in place, for example:

     ```yaml
     columns:
       - field: dim_calendar.month
         format: "MMM-yy"
         type: "date"
         order: "asc"
     ```

   - rely on Praeparo to normalise `dim_calendar.month` to
     `'dim_calendar'[month]` in DAX and to resolve payload keys.
   - adapters must not try to “fix” `dim_calendar.month` themselves; they
     should:
     - pass the configured grain/field straight through to Praeparo’s dataset
       builder;
     - use whatever canonical field name Praeparo returns as the single source
       of truth when mapping downstream JSON.

2. **Simplify mapping code**
   - ensure downstream adapters use only the configured field and trust
     Praeparo’s normalisation;
   - where mapping is required, use the canonical grain key from
     `MetricDatasetPlan.grain_columns` or the dataset builder’s column field,
     rather than re-deriving it via new string heuristics.

3. **Docs and epics**
   - update downstream docs to reference the new field reference capability;
   - make it clear that:
     - metrics and visuals should use `table.column` or `column` in YAML where
       possible;
     - DAX `'table'[Column]` remains valid as an explicit escape hatch, but is
       no longer required for everyday usage.

## 6. Validation

Once Phase 1 is implemented:

- **Praeparo tests**
  - add unit tests for `FieldReference.parse` and `to_dax()` covering:
    - `'dim_calendar'[month]`, `dim_calendar[month]`, `dim_calendar.month`,
      `[month]`, `month`;
  - add tests that:
    - use ergonomic `--grain dim_calendar.month` in a CLI call and assert
      that:
      - generated DAX uses `'dim_calendar'[month]`;
      - JSON payload mapping still works via `lookup_column`, without
        additional heuristics in dataset code.

- **Downstream tests**
  - configure a dataset-backed visual with `field: dim_calendar.month`;
  - verify:
    - DAX grain uses `'dim_calendar'[month]`;
    - downstream JSON correctly reflects the live payload’s month values;
    - downstream mapping relies solely on Praeparo’s canonical field keys and
      does not introduce new string-level normalisation.

This phase keeps DAX syntax and payload mapping internally rigorous while
letting developers work with more natural `table.column` notation at the
boundaries. The critical guardrail is **central field normalisation in
Praeparo**: downstream consumers must treat that pipeline as the single source
of truth, rather than re-implementing ergonomics locally.

# Epic: Pack CLI Context Overrides for Base Pack Reuse (Phase 4)

> Status: **Implemented** - `praeparo pack run` now supports repeatable `--context` files, pack-shaped overrides, path templating against the effective context payload, and explicit override precedence over base pack defaults (2026-04-15).

- Active docs for the surrounding contract already live in `docs/projects/pack_runner.md`.

## Scope

Phase 4 is implemented upstream. This phase record remains as implementation
history for the original CLI/runtime gaps and the intended precedence model.

The active developer-facing contract now lives in:

- `docs/projects/pack_runner.md`

## 1. Problem

We wanted canonical base packs to run with override context files without
cloning or rewriting pack YAML.

Before implementation, this was not supported end-to-end:

- `praeparo pack run` rejects `--context` as an unknown argument;
- pack path templating (`dest`, `--artefact-dir`, `--result-file`) is rendered
  without external context override files;
- pack runner context precedence currently causes pack defaults to overwrite
  explicit metadata context.

This blocks the intended workflow:

```bash
poetry run praeparo pack run ./registry/packs/standard/standard_pack.yaml \
  --context ./registry/packs/overrides/customer_a.yaml \
  --artefact-dir ./.tmp/standard_pack_customer_a/_artifacts \
  --result-file ./.tmp/standard_pack_customer_a/standard_pack_customer_a.pptx
```

## 2. Goals

1. Add `--context` support to `pack run`, with the same file semantics as
   `visual run`.
2. Ensure context overrides can be pack-shaped files.
3. Make explicit context overrides win over base pack defaults.
4. Ensure output path templating and runtime execution use the same effective
   context model.
5. Preserve backwards compatibility for existing runs that do not use
   `--context`.

## 3. Non-goals

- No changes to pack YAML schema.
- No new dedicated `context_ref` field in pack YAML.
- No migration of downstream packs in this phase.
- No changes to Power BI export logic, slide ordering, or template handling.

## 4. Original Gaps

### 4.1 CLI surface gap

- `--context` existed on shared/common CLI parsers used by visual commands.
- `pack run` did not expose it.

### 4.2 Path templating gap

- pack path template resolution handled registry + pack context only.
- it did not apply additional context files, so `dest` / `--result-file`
  templating could not reflect override values.

### 4.3 Runner precedence gap

Pack runner originally applied merges in a way that effectively let pack
defaults overwrite explicit metadata context:

1. Base context payload is resolved with registry layers + metadata context +
   pack context.
2. `run_pack(...)` then re-merges `pack.context` again over the resolved base
   payload.

This second merge prevented explicit overrides from sticking.

## 5. Implemented Behavior

### 5.1 Add `--context` to `pack run`

Praeparo now exposes repeatable `--context` arguments on `pack run`:

- type: `Path`
- repeatable: `action="append"`
- help text aligned with visual CLI semantics

### 5.2 Resolve pack context payload for CLI metadata

Pack metadata preparation now includes a merged context payload when
`--context` is provided:

- reuse layered context resolver behavior (registry context layers + explicit
  context files);
- accept pack-shaped files as context layers;
- store the resolved payload under `PipelineOptions.metadata["context"]`.

### 5.3 Use effective context for path templating

Pack path template resolution now renders `dest` / `--artefact-dir` /
`--result-file` / `--build-artifacts-dir` against the same effective context
used at runtime, including `--context` overrides.

### 5.4 Fix precedence in runner

The implemented precedence is explicit and deterministic:

1. Registry context defaults (lowest).
2. Pack context from pack YAML (base pack defaults).
3. Explicit metadata context (from `--context` and/or metadata injection)
   (highest).

Implementation detail:

- the extra post-resolution merge that reapplied `pack.context` over the
  resolved payload is gone;
- code comments and docstrings now describe the actual precedence behavior.

### 5.5 Backward compatibility expectations

- Existing commands with no `--context` keep current behavior.
- Existing `--meta context=...` users get more intuitive precedence (explicit
  override wins).

## 6. Public Contract (CLI Behavior)

After this phase, these should be valid:

```bash
poetry run praeparo pack run ./registry/packs/standard/standard_pack.yaml \
  --context ./registry/packs/overrides/customer_a.yaml \
  --artefact-dir ./.tmp/standard_pack_customer_a/_artifacts \
  --result-file ./.tmp/standard_pack_customer_a/standard_pack_customer_a.pptx
```

And multiple context files should apply in CLI order (last writer wins for
named fragments and keys):

```bash
poetry run praeparo pack run ./registry/packs/standard/standard_pack.yaml \
  --context ./context/base.yaml \
  --context ./context/customer_a.yaml \
  --artefact-dir ./.tmp/out
```

## 7. Completion Notes

Implementation evidence lives in:

1. `praeparo/cli/__init__.py`
   - `pack run` exposes repeatable `--context`.
   - pack metadata preparation resolves and forwards the effective context.
   - path templates render against the effective context payload.
2. `praeparo/pack/runner.py`
   - pack execution preserves precedence `registry < pack < explicit override`.
3. `tests/test_cli_entrypoint.py`
   - CLI tests cover pack-shaped context files, override precedence, and output
     path templating using override values.
4. `docs/projects/pack_runner.md`
   - active developer docs describe the supported CLI contract and precedence.

## 8. Test Plan

### 8.1 CLI tests

- `pack run` accepts `--context`.
- `pack run --context <pack-shaped-yaml>` forwards context payload to runner
  metadata.
- `pack run` path templates resolve values provided by `--context`.

### 8.2 Runner tests

- metadata context overrides pack context for overlapping keys.
- `run_pack` forwards overridden context into typed visual context models.
- no regression when no metadata context is supplied.

### 8.3 Regression safety

- existing pack run tests for `dest`, `result_file`, revisions, `--slides`,
  and `--pptx-only` remain green.

## 9. Validation

```bash
poetry run pytest tests/test_cli_entrypoint.py -k "pack and context"
poetry run pytest tests/pack/test_pack_runner.py -k "context"
poetry run pytest tests/pack/test_pack_runner.py
```

If the implementation touches broader context-layer behavior, include:

```bash
poetry run pytest tests/visuals/test_context_layers.py
```

## 10. Risks and Mitigations

- Risk: changing precedence could affect workflows relying on pack context
  overriding metadata.
  - Mitigation: document precedence clearly and add explicit tests.
- Risk: double-merging context payloads can duplicate fragments.
  - Mitigation: centralize merge order and keep one source of truth for final
    pack payload.
- Risk: path templating/runtime context drift.
  - Mitigation: derive both from the same effective context payload
    construction path.

## 11. Effort Estimate

- Code changes: 2-4 hours.
- Tests: 2-3 hours.
- Docs: 0.5-1 hour.
- Total: approximately 1 working day including review feedback.

## 12. Follow-up Notes

- This phase is complete. Any future work should focus on broader base-pack
  ergonomics or additional pack-runner capabilities rather than reopening the
  `--context` contract itself.

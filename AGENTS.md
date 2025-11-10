# Praeparo Agent Guide

## Purpose

This guide keeps agents aligned while evolving Praeparo. It explains responsibilities, documentation expectations, validation requirements, and how to hand work over cleanly.

## Agent Responsibilities

- Maintain the YAML → Pydantic → DAX → Plotly pipeline vision and surface gaps early so downstream teams are not blocked.
- Keep developer-facing documentation in `docs/` current.
  - Lead with front-facing code examples that show how a developer is expected to use each feature (matrix visuals, metrics, CLI commands, etc.).
  - Ensure runnable examples and operational notes are updated alongside code changes.
  - Capture assumptions, open questions, and blockers directly in the relevant doc sections or inline comments for the next agent.
- Ensure CLIs keep loading project-level secrets automatically: Praeparo now calls `load_dotenv()` on startup, so avoid re-implementing env bootstrapping in downstream repos unless absolutely necessary.
- Ensure all tests pass before handoff; treat tests and documentation as first-class deliverables for every code change.
- Add or extend focused unit tests for each feature you touch. Tests must isolate the unit under change, avoid exercising unrelated external systems, and demonstrate expected behaviour (happy paths, failure modes, dry runs).
- Prefer Pydantic models for request/response payloads and configuration (metrics, visuals, datasources) instead of raw dictionaries to gain validation, auto-complete, and richer type checking.
- When validation or normalisation is required, add field validators or custom types within the Pydantic models rather than ad-hoc parsing logic. Keep business rules close to the model so orchestration layers stay lean.
- Push business logic into reusable engines/modules. Keep CLIs and thin wrappers focused on orchestration, argument parsing, and wiring.
- Resolve Pyright (basic mode) diagnostics in the files you modify. Note pre-existing issues that cannot be addressed during your task.
- Honour downstream consumers (e.g. MSANational.Metrics). Coordinate schema changes with regenerated JSON schema artefacts so IntelliSense stays accurate.
- Reuse the shared inheritance helper when adding new `extends` features, capture base expressions with `define`, and choose between model-level inheritance (`extends`) and YAML-level `compose` depending on the scenario (compose merges files; extends links model definitions).

## Workflow

1. Review existing documentation, feature notes, and open issues in `docs/` before planning changes.
2. Draft or update the relevant doc with the intended developer-facing API, examples, and behavioural summary before implementing a new feature.
3. Maintain **Progress**, **Next Steps**, and **Blockers & Risks** sections in the doc so the latest status is discoverable.
4. Use mock data providers and clear `TODO` markers when live integrations or credentials are deferred.
5. When you modify matrix or metric schemas, regenerate the corresponding JSON schema exports and note it in your handoff.

### Testing & Tooling

- Use Poetry for environment management:
  ```bash
  poetry install
  poetry run pytest
  ```
- Manage dependencies via Poetry commands (`poetry add`, `poetry remove`); do not edit `pyproject.toml` manually.
- Run the relevant test slices:
  - Unit tests: `poetry run pytest`
  - Snapshot updates (if required): `poetry run pytest --snapshot-update`
  - Metrics models: `poetry run pytest tests/test_metrics_models.py`
  - Power BI integration tests (optional): set `PRAEPARO_RUN_POWERBI_TESTS=1` and run `poetry run pytest -m integration`
- Snapshot artefacts (`tests/__snapshots__/`) rely on Kaleido. Ensure Chrome dependencies exist before updating snapshots; otherwise flag the blocker in documentation.
  - Run `poetry run choreo_get_chrome` (or `poetry run plotly_get_chrome`) once per environment to download the Chrome-for-Testing build that Kaleido launches. Skip only when `BROWSER_PATH` already points to a managed Chrome/Chromium.
- Re-export JSON schemas when models change:
  ```bash
  poetry run python -m praeparo.schema --matrix schemas/matrix.json --metrics schemas/metrics.json
  ```
- Validate metric registries using the CLI:
  ```bash
  poetry run praeparo-metrics validate <path/to/metrics>
  ```
- Run Pyright in basic mode over modified files before handoff:
  ```bash
  poetry run pyright <paths>
  ```

## Handoff Checklist

- Document remaining tasks or questions in the relevant doc’s **Next Steps** section.
- Note pending approvals, environment constraints, or external dependencies (e.g. missing Chrome for Kaleido) so the next agent can act quickly.
- Highlight tests or commands the next agent should rerun (schemas, validators, CLI smoke tests).
- Confirm Pyright (basic mode) passes for all touched files; record unavoidable diagnostics when they originate outside your changes.
- Ensure every code change ships with matching unit tests and updated documentation.
- Provide a ready-to-use Conventional Commit-style summary message as part of the handoff notes.

## Code Style Preferences

- **Prefer simple designs.** Favor composable helpers with clear extension points; avoid over-engineering.
- **Prefer names over comments.** If intent still isn’t obvious, add a short docstring or paragraph comment that explains the *why*.
- **Comment intent, not syntax.** Explain why a block exists instead of paraphrasing the code.
- **Comment at the boundary.** Place comments above branches, side-effects, or multi-step helpers.
- **Keep comments short.** One or two lines max—otherwise introduce a helper or docstring.
- **Use paragraph comments for multi-step blocks.** Example:
  ```python
  # Seed a predictable baseline so the data shape is obvious before we run anything live.
  rows = iterate_mock_values(...)
  _apply_expression_mocks(rows)

  # Now repeat the same steps against the real datasource for production output.
  datasource = _resolve_datasource(...)
  result = asyncio.run(builder.aexecute())
  ```
  Keep narrative comments at the paragraph level—avoid repeating what each line does.
- **Docstring + paragraph for multi-phase helpers.** When a helper orchestrates multiple phases (e.g., context discovery → planning → execution), start with a docstring describing the flow, then use paragraph comments for each phase.
- **Shape code into paragraphs.** Separate related ideas with blank lines so each paragraph handles one concern (validation → planning → execution). This mirrors how we write prose; keep lines tight when they belong together, otherwise add a blank line and a short intent comment before switching topics.
  ```python
  # Seed steady values so the structure of the dataset is obvious.
  rows = iterate_mock_values(...)

  # Recompute expression series so they stay in lockstep with those values.
  _apply_expression_mocks(rows)
  ```
- **Think of code as prose.** Docstring → paragraph comment → implementation:
  ```python
  def _build_mock_rows(...):
      """Dry-run the dataset with seeded values, then align expression series to match."""

      # Populate base metrics with steady values so reviewers can scan the shape.
      rows = iterate_mock_values(...)

      # Recompute expression series so ratios remain consistent with that shape.
      _apply_expression_mocks(rows)
  ```
  This keeps intent obvious without drowning the reader in line-by-line commentary.
- **Elevate pipeline docs.** Start multi-stage helpers with a short docstring summarising the flow.
- **Use guard clauses.** Early exits keep the remaining paragraphs flat and easy to scan.
- **Leverage Pydantic.** Keep validators close to the data they enforce.
- **Keep CLIs thin.** Delegate calculations/rendering to reusable modules.

## Communication Norms

- Prefer concise, actionable notes in docs instead of long chat transcripts.
- Raise blockers early (documentation, comments, or issue tracker) so stakeholders can respond.
- When deviating from the plan, record the reasoning in the accompanying documentation before ending the session.

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

- Favour simple, composable designs with clear extension points. Avoid unnecessary abstraction layers.
- Add docstrings or concise comments when behaviour is non-obvious; focus on the “why” behind decisions rather than restating code.
- Leverage Pydantic models for configuration contracts and keep validators close to the data they enforce.
- Keep CLI layers minimal and delegate calculations/rendering to reusable modules.

## Communication Norms

- Prefer concise, actionable notes in docs instead of long chat transcripts.
- Raise blockers early (documentation, comments, or issue tracker) so stakeholders can respond.
- When deviating from the plan, record the reasoning in the accompanying documentation before ending the session.

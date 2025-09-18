# Praeparo Agent Guide

## Purpose

This guide keeps Codex/agents aligned while evolving the Praeparo proof of concept. It explains responsibilities, handoff expectations, and how to record decisions.

## Agent Responsibilities

- Maintain the YAML -> Pydantic -> DAX -> Plotly pipeline plan and surface gaps early.
- Keep developer-facing documentation current by adding or updating feature files that describe the front-facing API, runnable examples, and operational notes.
- Note assumptions and unresolved questions in the relevant docs section (Progress/Next Steps/Blockers & Risks) or code comments for the next agent.

## Workflow

1. Review the existing documentation for the feature area you are touching before making changes.
2. Before planning new feature work, draft or update the corresponding documentation file with the desired developer-facing API, detailed examples, and a summary of the intended behaviour.
3. Maintain Progress, Next Steps, and Blockers & Risks sections inside that documentation so the latest status lives alongside the feature notes.
4. Coordinate schema changes with generated JSON schema updates so IDE IntelliSense stays accurate.
5. Use mock data providers and clear TODOs when live integrations are deferred.

## Testing & Tooling

- Use the Poetry environment for local commands: `poetry install` and `poetry run pytest`.
- Manage dependencies with Poetry commands (`poetry add`, `poetry remove`) instead of editing `pyproject.toml` by hand.
- `pytest` relies on `pytest.ini` for root import paths; keep it in sync if the package layout changes.
- Snapshot tests run via `syrupy`; regenerate expected output with `poetry run pytest --snapshot-update`.
- Snapshot artifacts (DAX/HTML/PNG) live in `tests/__snapshots__/`; regenerate with `poetry run pytest --snapshot-update`. Kaleido is required for PNG snapshots (`poetry add kaleido`).
- Configure Power BI credentials in `.env` (`PRAEPARO_PBI_CLIENT_ID`, `PRAEPARO_PBI_CLIENT_SECRET`, `PRAEPARO_PBI_TENANT_ID`, `PRAEPARO_PBI_REFRESH_TOKEN`) when running live queries.
- Integration tests are gated behind `PRAEPARO_RUN_POWERBI_TESTS=1`; run `poetry run pytest -m integration` for live validation.
- When new CLI features arrive, add smoke tests or fixture updates so `poetry run pytest` stays green.

## Handoff Checklist

- Ensure open tasks are captured in the "Next Steps" section of the relevant documentation file.
- Mention pending approvals or environment constraints.
- Highlight any tests or commands that future agents should rerun.
- After closing out work, propose a Conventional Commit-style message summarizing the changes.


## Code Style Preferences

- Favour high-quality, prudent SOLID design; prefer composition and clear extension points without unnecessary abstractions.
- Add docstrings or concise comments whenever behaviour is non-obvious from structure alone (e.g. complex control flow, regex helpers, or template handling).
- Keep code comments focused and actionable; explain why decisions were made rather than restating what the code does.

## Communication Norms

- Prefer concise, actionable notes in docs rather than long chat transcripts.
- Flag blockers early in the relevant documentation so stakeholders can intervene.
- When deviating from the plan, explain the reasoning in the documentation entry before concluding the session.

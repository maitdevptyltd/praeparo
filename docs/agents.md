# Praeparo Agent Guide

## Purpose
This guide keeps Codex/agents aligned while evolving the Praeparo proof of concept. It explains responsibilities, handoff expectations, and how to record decisions.

## Agent Responsibilities
- Maintain the YAML -> Pydantic -> DAX -> Plotly pipeline plan and surface gaps early.
- Keep documentation current (`docs/mvp/index.md`, dated timelines, and README excerpts).
- Note assumptions and unresolved questions in timeline entries or code comments for the next agent.

## Workflow
1. Review the latest timeline entry (`docs/mvp/YYYY-MM-DD.md`) before making changes.
2. Update the plan with new findings; append or create a new dated timeline file after significant progress.
3. Coordinate schema changes with generated JSON schema updates so IDE IntelliSense stays accurate.
4. Use mock data providers and clear TODOs when live integrations are deferred.

## Testing & Tooling
- Use the Poetry environment for local commands: `poetry install` and `poetry run pytest`.
- Manage dependencies with Poetry commands (`poetry add`, `poetry remove`) instead of editing `pyproject.toml` by hand.
- `pytest` relies on `pytest.ini` for root import paths; keep it in sync if the package layout changes.
- Snapshot tests run via `syrupy`; regenerate expected output with `poetry run pytest --snapshot-update`.
- PNG exports require Kaleido. Install it via Poetry (`poetry add kaleido`) and run `poetry run pytest` to verify the optional PNG test.
- When new CLI features arrive, add smoke tests or fixture updates so `poetry run pytest` stays green.

## Handoff Checklist
- Ensure open tasks are captured in "Next Steps" of the latest timeline entry.
- Mention pending approvals or environment constraints.
- Highlight any tests or commands that future agents should rerun.

## Communication Norms
- Prefer concise, actionable notes in docs rather than long chat transcripts.
- Flag blockers early in the timeline so stakeholders can intervene.
- When deviating from the plan, explain the reasoning in the dated entry before concluding the session.

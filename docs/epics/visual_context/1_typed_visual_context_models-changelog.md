2026-04-15T16:27:18+10:00 – Moved GM-4 upstream into Praeparo under the visual-context epics, genericized the custom-visual framing, and confirmed the active contract already lives in `docs/visuals/visual_context_model.md`.

2025-12-09T10:32:14+10:00 – Implemented GM‑4: added VisualContextModel to Praeparo with generic pipeline typing, CLI/pack context instantiation, GovernanceMatrixContextModel registration, and refactored governance matrix pipeline/builders to consume the typed context directly with updated tests.

2025-12-08T15:45:00-05:00 – Drafted GM‑4 epic to introduce Pydantic-based visual context models in Praeparo, register a GovernanceMatrixContextModel, attach typed context to ExecutionContext, and simplify governance matrix pipeline to consume the typed context directly instead of parsing metadata.

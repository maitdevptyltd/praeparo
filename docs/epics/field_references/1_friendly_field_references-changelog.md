2026-04-15T17:36:00+10:00 – Clarified that Praeparo already has partial field-reference support (`templating.FieldReference`, `lookup_column(...)` heuristics, and cartesian examples using `dim_calendar.month`), while keeping the phase in draft because the feature is not yet centralised or documented as a first-class contract.

2026-04-15T17:24:00+10:00 – Moved GM-8 upstream into Praeparo under a dedicated `field_references/` epic family, stripped repo-specific governance wording, and kept the phase as draft because there is no first-class active Praeparo docs page for the feature yet.

2025-12-09T17:15:00+10:00 – Refined the phase to emphasise central FieldReference normalisation in Praeparo, no duplicate heuristics in downstream datasets, and ergonomics for YAML field notation only after the shared pipeline is in place.

2025-12-09T16:40:00+10:00 – Drafted the phase for ergonomic field references (`dim_calendar.month`) with automatic DAX and payload normalisation in Praeparo and downstream consumers.

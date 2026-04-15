2026-04-15T16:22:15+10:00 – Removed leftover project-specific matrix wording from the upstream schema export epic and aligned the archived scope to Praeparo's actual built-in families.

2026-04-15T16:19:11+10:00 – Moved the schema export epic upstream into Praeparo, genericized the downstream examples, and linked it to the new active `praeparo schema` developer docs.

2026-04-13T17:38:55+10:00 – Landed the Praeparo-side implementation and root repo consumption: `praeparo schema` now emits the umbrella schema, plugin auto-discovery works across the CLI surface through `praeparo.yaml` / env / opt-in package metadata, and the root repo now consumes the generated umbrella artifact for supported visual families.

2026-04-13T17:27:00+10:00 – Preferred a root `praeparo.yaml` manifest over `.praeparo/plugins.yaml` for plugin discovery, and clarified that it can declare plugin modules for normal auto-loading.

2026-04-13T17:11:27+10:00 – Added a concrete plugin-discovery model for the proposed schema CLI: explicit `--plugin` overrides, `PRAEPARO_PLUGINS`, a `.praeparo/plugins.yaml` workspace manifest, and a narrow opt-in convention scan for the current and future package layouts.

2026-04-13T17:18:00+10:00 – Simplified the proposal so the normal path is `praeparo schema` or `praeparo schema <dest>`, fixed the default output path to `./schemas/visual_umbrella.schema.json`, and kept plugin auto-detection for the default flow.

2026-04-13T17:00:51+10:00 – Revised the proposal to use `praeparo schema visual --out ...` as the natural CLI shape and made automatic plugin discovery a first-class requirement so repo-local visuals do not depend on remembering `--plugin msanational_metrics`.

2026-04-13T16:54:37+10:00 – Added a review-only RR-1 proposal for a Praeparo CLI that emits an umbrella visual schema with a default or overridable output path, plus the downstream repo consumption plan.

# Praeparo MVP

Praeparo turns YAML-defined visuals into automated, Plotly-powered presentations. The minimum viable product (MVP) focuses on validating the developer workflow for defining matrices and generating interactive output without depending on live Power BI connectivity.

## Goals

- Validate the YAML -> Pydantic -> DAX -> Plotly pipeline end-to-end
- Ship an opinionated matrix visual based on `tests/visuals/matrix/auto.yaml`
- Document agent workflow and decision logs so contributions stay aligned

## Quick Links

- [Visual model architecture](../visual_model_architecture.md)
- [Agent guidelines](../../AGENTS.md)

## How to Update

1. Before planning changes, update the relevant feature documentation with the intended developer-facing API, examples, and operational notes.
2. Record Progress, Next Steps, and Blockers & Risks inside that feature document so status travels with the implementation details.
3. Add new feature docs under `docs/` as needed and link to them from this index to keep discovery simple.
4. Use the archived dated timelines for historical context only; do not create new entries.


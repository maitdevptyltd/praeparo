# Praeparo Documentation

Use this folder as the canonical developer documentation for Praeparo. Start here, then drill into the area you’re working on.

## Getting Started

- Projects (recommended structure): [`projects/index.md`](projects/index.md)
- Datasource definitions (Power BI + env placeholders): [`datasources/index.md`](datasources/index.md)
- Visual registry + CLI overview: [`visuals/index.md`](visuals/index.md)
- Pack runner (Pack → PNG/PPTX): [`projects/pack_runner.md`](projects/pack_runner.md)

## Visuals

- Visual registry, typed context, CLI shorthand: [`visuals/index.md`](visuals/index.md)
- Visual context models (`--context`, `--calculate`, `--define`): [`visuals/visual_context_model.md`](visuals/visual_context_model.md)
- Metric expressions (`expression:` and `ratio_to()`): [`visuals/metric_expressions.md`](visuals/metric_expressions.md)
- Python-backed visuals (`praeparo python-visual ...`): [`visuals/python_visuals.md`](visuals/python_visuals.md)
- Power BI visual (design / pending implementation): [`visuals/powerbi_visual.md`](visuals/powerbi_visual.md)
- Power BI visual implementation plan: [`visuals/plan_powerbi_visual.md`](visuals/plan_powerbi_visual.md)

## Metrics

- Metric → DAX builder (registry compilation): [`metrics/metric_dax_builder.md`](metrics/metric_dax_builder.md)
- Metric debugging and evidence workflows: [`metrics/metric_debugging.md`](metrics/metric_debugging.md)
- TMDL generation and generated-model planning: [`metrics/tmdl_generation.md`](metrics/tmdl_generation.md)

## Architecture (Reference)

- Visual model architecture (loader + models): [`visual_model_architecture.md`](visual_model_architecture.md)
- Visual pipeline engine (planner/provider model): [`visual_pipeline_engine.md`](visual_pipeline_engine.md)

## Epics

- MVP-era notes: [`mvp/index.md`](mvp/index.md)
- Framework feature epics: [`epics/index.md`](epics/index.md)

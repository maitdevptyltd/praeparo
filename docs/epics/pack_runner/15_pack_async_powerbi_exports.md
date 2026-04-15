# Phase 15: Pack Async Power BI Exports

> Status: **Implemented** – Power BI slides run through a bounded export queue with `--max-pbi-concurrency` and queue-aware logging.

Use this page as implementation history for the Power BI export queue.
For the current supported contract, start with [Projects / Pack Runner](../../projects/pack_runner.md).

## 1. Purpose

Once the generic pack -> PNG flow existed, Power BI slides became the dominant
source of wall-clock time in larger packs. This phase introduced a bounded,
observable queue for `type: powerbi` slides so pack execution could overlap
long-running exports without changing the pack YAML contract.

## 2. Scope

This phase applies to:

- Power BI visuals executed by `praeparo pack run`,
- shared queue configuration for those exports,
- and queue-level logging/error reporting.

It does not change the pack schema, PPTX assembly, or non-Power BI visual
behavior.

## 3. Desired Behavior

During a pack run:

1. Praeparo plans the pack once and resolves each slide's visual.
2. Power BI slides are enqueued as export jobs.
3. Non-Power BI slides continue to run inline through their existing pipelines.
4. The runner waits for the queued Power BI jobs to drain before finalizing the
   pack result.

Each queued job carries:

- the slide identity,
- the resolved Power BI visual config,
- merged OData filters,
- and the slide-specific artifact/output paths.

The queue is orchestration only. Each worker still calls the existing Power BI
pipeline to perform the export.

## 4. Concurrency Contract

Power BI concurrency is:

- bounded by a per-run limit,
- configurable via `--max-pbi-concurrency`,
- optionally defaulted from `PRAEPARO_PBI_MAX_CONCURRENCY`,
- and conservative by default.

Example:

```bash
poetry run praeparo pack run \
  projects/example/pack.yaml \
  --artefact-dir out/example/pack_png \
  --max-pbi-concurrency 3
```

This allows up to three Power BI exports to run in parallel while other visual
types continue to follow the runner's normal execution path.

## 5. Logging And Failure Model

This phase also established queue-aware observability:

- queue initialization logs the effective concurrency,
- slide jobs log when they are queued, started, completed, or failed,
- and pack-level summaries list any failed slide slugs before the CLI exits
  non-zero.

The current pack-runner docs remain the source of truth for exact log-level and
failure-policy details.

## 6. Relationship To Later Pack Phases

This phase only covers concurrent Power BI exports. It does not imply general
concurrency for DAX-backed visuals or placeholder rendering.

Later pack-runner phases preserved the same queue model while refining:

- artifact naming,
- error context,
- PPTX assembly,
- and template geometry.
